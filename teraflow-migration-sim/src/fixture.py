"""Stable satellite ports and a genuine Release 7 L2NM intent."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from uuid import UUID, uuid5
from .snapshot import snapshot

HOSTS = [{"name": "h1", "satellite": 53848, "ip": "10.0.0.1/24", "mac": "00:00:00:00:00:01"},
         {"name": "h2", "satellite": 53913, "ip": "10.0.0.2/24", "mac": "00:00:00:00:00:02"}]


NAMESPACE = UUID("200e3a1f-2223-534f-a100-758e29c37f40")
def stable_id(name): return str(uuid5(NAMESPACE, name))
CONTEXT_UUID = stable_id("migration-lab")
TOPOLOGY_UUID = stable_id(CONTEXT_UUID + "/starlink-17")
TOPOLOGY_ID = {"context_id": {"context_uuid": {"uuid": CONTEXT_UUID}}, "topology_uuid": {"uuid": TOPOLOGY_UUID}}
def device_id(sid): return {"device_uuid": {"uuid": stable_id(f"sat-{sid}")}}
def endpoint_id(sid, port):
    did = device_id(sid)
    return {"device_id": did, "endpoint_uuid": {"uuid": stable_id(TOPOLOGY_UUID+"/"+did["device_uuid"]["uuid"]+"/"+str(port))},
            "topology_id": TOPOLOGY_ID}


def build(root: Path):
    selection = json.loads((root / "config/selected_constellation.json").read_text())
    windows = json.loads((root / "results/direct_link_windows.json").read_text())["windows"]
    ids = sorted(row["norad_id"] for row in selection["satellites"])
    pairs = sorted({tuple(sorted((row["sat_a"], row["sat_b"]))) for row in windows})
    ports = {sid: {} for sid in ids}
    devices = []
    for index, sid in enumerate(ids):
        neighbors = sorted(b if a == sid else a for a, b in pairs if sid in (a, b))
        ports[sid] = {str(neighbor): port+1 for port, neighbor in enumerate(neighbors)}
        host = next((host for host in HOSTS if host["satellite"] == sid), None)
        if host: ports[sid][host["name"]] = len(neighbors)+1
        devices.append({"norad": sid, "dpid": index+1, "name": f"s{index+1}",
                        "grpc_port": 50001+index, "proxy_port": 51001+index, "ports": ports[sid]})
    return {"schema_version": 1, "context": "migration-lab", "topology": "starlink-17",
            "service": "migration-l2", "emulator": {"devices": devices, "pairs": pairs, "hosts": HOSTS},
            "controller_proxy": "p4-proxy", "pipeline_binary": "/experiment/deploy/p4/bmv2.json",
            "pipeline_info": "/experiment/deploy/p4/p4info.txt"}


def state(fixture, graph, role="sat-a"):
    context_id = {"context_uuid": {"uuid": CONTEXT_UUID}}
    topology_id = TOPOLOGY_ID
    entities = {"contexts": [{"context_id": context_id, "name": fixture["context"]}],
                "devices": [], "links": [], "topologies": [], "services": [], "connections": []}
    ports = {row["norad"]: row["ports"] for row in fixture["emulator"]["devices"]}
    for row in fixture["emulator"]["devices"]:
        sid = row["norad"]
        settings = {"id": row["dpid"], "name": f"sat-{sid}", "vendor": "P4.org", "hw_ver": "BMv2",
                    "sw_ver": "simple_switch_grpc", "timeout": 10,
                    "p4bin": fixture["pipeline_binary"], "p4info": fixture["pipeline_info"]}
        settings["endpoints"] = [{"uuid": endpoint_id(sid, port)["endpoint_uuid"]["uuid"],
                                   "name": str(port), "type": "port", "context_uuid": CONTEXT_UUID,
                                   "topology_uuid": TOPOLOGY_UUID} for port in sorted(row["ports"].values())]
        config = []
        for key, value in (("address", fixture["controller_proxy"]),
                           ("port", row["proxy_port"] + (1000 if role == "sat-b" else 0)), ("settings", settings)):
            config.append({"action": "CONFIGACTION_SET", "custom": {"resource_key": "_connect/"+key,
                "resource_value": json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value)}})
        entities["devices"].append({"device_id": device_id(sid), "name": f"sat-{sid}",
            "device_type": "p4-switch", "device_drivers": ["DEVICEDRIVER_P4"],
            "device_operational_status": "DEVICEOPERATIONALSTATUS_DISABLED",
            "device_config": {"config_rules": config},
            "device_endpoints": [{"endpoint_id": endpoint_id(sid, port), "endpoint_type": "port", "name": str(port)}
                                 for port in sorted(row["ports"].values())]})
    for a, b in fixture["emulator"]["pairs"]:
        if b not in graph[a]: continue
        for source, target in ((a, b), (b, a)):
            entities["links"].append({"link_id": {"link_uuid": {"uuid": stable_id(f"isl-{source}-{target}")}},
                "name": f"isl-{source}-{target}", "link_type": "LINKTYPE_RADIO",
                "link_endpoint_ids": [endpoint_id(source, ports[source][str(target)]),
                                      endpoint_id(target, ports[target][str(source)])]})
    # Include all devices and currently available directed links.
    entities["topologies"] = [{"topology_id": topology_id, "name": fixture["topology"],
        "device_ids": [row["device_id"] for row in entities["devices"]],
        "link_ids": [row["link_id"] for row in entities["links"]]}]
    from .orbit import shortest_paths
    # Compute deterministic forwarding settings only for nodes on a valid path.
    switch_info = []
    for row in fixture["emulator"]["devices"]:
        sid = row["norad"]
        port_list = [{"port_id": port, "port_type": "host" if key in {"h1", "h2"} else "switch", "vlan_id": 4094}
                     for key, port in row["ports"].items()]
        fwd = []
        for host in HOSTS:
            if host["satellite"] == sid:
                port = row["ports"][host["name"]]
            else:
                distances = shortest_paths(graph, host["satellite"])
                reachable = [(graph[sid][neighbor] + distances[neighbor], neighbor)
                             for neighbor in graph[sid] if neighbor in distances]
                if not reachable: continue
                port = row["ports"][str(min(reachable)[1])]
            fwd.append({"port_id": port, "host_mac": host["mac"]})
        if not port_list or not fwd:
            continue
        switch_info.append({f"sat-{sid}": {"arch": "v1model", "dpid": row["dpid"],
                                           "port_list": port_list, "fwd_list": fwd}})
    entities["services"] = [{"service_id": {"context_id": context_id, "service_uuid": {"uuid": stable_id(CONTEXT_UUID+"/"+fixture["service"])}},
        "name": fixture["service"], "service_type": "SERVICETYPE_L2NM",
        "service_endpoint_ids": [endpoint_id(host["satellite"], ports[host["satellite"]][host["name"]]) for host in HOSTS],
        "service_constraints": [], "service_config": {"config_rules": [{"action": "CONFIGACTION_SET", "custom": {
            "resource_key": "/settings", "resource_value": json.dumps({"switch_info": switch_info}, sort_keys=True)}}]}}]
    return snapshot(entities)


def for_destination(document, fixture):
    result = copy.deepcopy(document)
    by_name = {f"sat-{row['norad']}": row for row in fixture["emulator"]["devices"]}
    for device in result["entities"]["devices"]:
        row = by_name[device["name"]]
        for rule in device["device_config"]["config_rules"]:
            custom = rule.get("custom", {})
            if custom.get("resource_key") == "_connect/port":
                custom["resource_value"] = str(row["proxy_port"]+1000)
    return result
