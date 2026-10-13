"""Independent UDP stream: no TCP setup dependency when the data path is down."""
import argparse
import json
import signal
import socket
import struct
import time

HEADER = struct.Struct("!QQ")


def run(args):
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        if args.mode == "receive":
            connection.bind((args.address, args.port))
            connection.settimeout(0.2)
        started = time.monotonic()
        sequence = 0
        while not stopped:
            if args.mode == "send":
                target = started+sequence*args.packet_bytes*8/args.rate_bps
                delay = target-time.monotonic()
                if delay > 0:
                    time.sleep(min(delay, 0.05))
                    continue
                stamp = time.time_ns()
                packet = HEADER.pack(sequence, stamp)+bytes(args.packet_bytes-HEADER.size)
                connection.sendto(packet, (args.address, args.port))
                print(json.dumps({"kind": "sent", "sequence": sequence,
                                  "sent_unix_ns": stamp, "bytes": len(packet)}), flush=True)
                sequence += 1
            else:
                try:
                    packet, _ = connection.recvfrom(65535)
                except socket.timeout:
                    continue
                stamp = time.time_ns()
                if len(packet) < HEADER.size:
                    continue
                sequence, sent = HEADER.unpack_from(packet)
                print(json.dumps({"kind": "received", "sequence": sequence, "sent_unix_ns": sent,
                                  "received_unix_ns": stamp, "bytes": len(packet)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("send", "receive"))
    parser.add_argument("--address", required=True)
    parser.add_argument("--port", type=int, default=19000)
    parser.add_argument("--rate-bps", type=int, default=1000000)
    parser.add_argument("--packet-bytes", type=int, default=1200)
    args = parser.parse_args()
    if args.rate_bps <= 0 or not HEADER.size <= args.packet_bytes <= 65507:
        parser.error("Invalid UDP rate or packet size")
    run(args)
