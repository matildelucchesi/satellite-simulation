"""Linux Mininet/BMv2 runner controlled through a local lab HTTP endpoint."""
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from mininet.net import Mininet
from mininet.node import Switch


class Bmv2(Switch):
    def __init__(self, name, dpid_value, grpc_port, **kwargs):
        super().__init__(name, **kwargs)
        self.device_id_value = dpid_value
        self.grpc_port = grpc_port
        self.process = None

    def start(self, controllers):
        command = ["simple_switch_grpc", "--device-id", str(self.device_id_value), "--no-p4",
                   "--log-console", "--log-level", "warn", "--thrift-port", str(9000+self.device_id_value)]
        for intf in self.intfList():
            if intf.name != "lo": command.extend(["-i", str(self.ports[intf])+"@"+intf.name])
        command.extend(["--", "--grpc-server-addr", "0.0.0.0:"+str(self.grpc_port), "--cpu-port", "255"])
        log = open("/results/"+self.name+".log", "a")
        self.process = self.popen(command, stdout=log, stderr=subprocess.STDOUT)
        log.close()

    def stop(self, deleteIntfs=True):
        if self.process:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
        super().stop(deleteIntfs)


def run(fixture):
    os.makedirs("/results", exist_ok=True)
    net = Mininet(controller=None, build=False)
    switches = {}
    rows = {row["norad"]: row for row in fixture["emulator"]["devices"]}
    for sid, row in rows.items():
        switches[sid] = net.addSwitch(row["name"], cls=Bmv2, dpid_value=row["dpid"], grpc_port=row["grpc_port"])
    links = {}
    for a, b in fixture["emulator"]["pairs"]:
        links[(a,b)] = net.addLink(switches[a], switches[b], port1=rows[a]["ports"][str(b)], port2=rows[b]["ports"][str(a)])
    hosts = {}
    for row in fixture["emulator"]["hosts"]:
        host = net.addHost(row["name"], ip=row["ip"], mac=row["mac"])
        hosts[row["name"]] = host
        net.addLink(host, switches[row["satellite"]], port2=rows[row["satellite"]]["ports"][row["name"]])
    net.build(); net.start()
    # BMv2 forwards bytes through packet sockets; it cannot complete veth's
    # deferred transport checksum or segmentation offload on host packets.
    for host in hosts.values():
        interface = host.defaultIntf().name
        _, error, status = host.pexec(["ethtool", "-K", interface, "tx", "off", "rx", "off",
                                      "tso", "off", "gso", "off", "gro", "off"])
        if status:
            raise RuntimeError("Cannot disable host offload on " + interface + ": " + error)
    for row in fixture["emulator"]["hosts"]:
        other = next(host for host in fixture["emulator"]["hosts"] if host["name"] != row["name"])
        hosts[row["name"]].setARP(other["ip"].split("/")[0], other["mac"])
    probes = []
    lock = threading.RLock()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({"switch_count": len(switches),
                "switches_alive": all(switch.process.poll() is None for switch in switches.values()),
                "probes": [process.poll() for process in probes]}).encode())
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with lock:
                    if self.path == "/links":
                        available = {tuple(sorted(pair)) for pair in body["pairs"]}
                        for pair, link in links.items():
                            state = "up" if pair in available else "down"
                            link.intf1.ifconfig(state); link.intf2.ifconfig(state)
                    elif self.path == "/probes/start":
                        if probes: raise ValueError("Probes already running")
                        run_id = body["run_id"]
                        if not run_id.replace("-", "").replace("_", "").isalnum(): raise ValueError("Invalid run ID")
                        directory = Path("/results") / run_id; directory.mkdir(exist_ok=False)
                        for host, command, name in ((hosts["h1"], ["ping", "-n", "-D", "-O", "-i", "0.1", "10.0.0.2"], "ping.log"),
                            (hosts["h2"], ["python3", "-u", "-m", "src.udp_probe", "receive", "--address", "10.0.0.2"], "udp-received.jsonl"),
                            (hosts["h1"], ["python3", "-u", "-m", "src.udp_probe", "send", "--address", "10.0.0.2"], "udp-sent.jsonl")):
                            with (directory / name).open("w") as output:
                                probes.append(host.popen(command, stdout=output, stderr=subprocess.STDOUT))
                    elif self.path == "/probes/stop":
                        for process in probes:
                            process.terminate()
                            try: process.wait(timeout=5)
                            except subprocess.TimeoutExpired: process.kill(); process.wait()
                        probes.clear()
                    else: raise ValueError("Unknown endpoint")
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            except Exception as exc:
                self.send_response(409); self.end_headers(); self.wfile.write(json.dumps({"error": str(exc)}).encode())
    try: ThreadingHTTPServer(("0.0.0.0", 8089), Handler).serve_forever()
    finally: net.stop()


if __name__ == "__main__":
    import sys
    with open(sys.argv[1]) as handle: run(json.load(handle))
