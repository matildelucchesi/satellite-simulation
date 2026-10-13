"""Analyze raw ping/UDP observations without inventing recovery or zero loss."""
from __future__ import annotations

import json
import re
from pathlib import Path

STAMP = re.compile(r"^\[(\d+(?:\.\d+)?)\]")
SEQ = re.compile(r"icmp_seq[= ](\d+)")
RTT = re.compile(r"time([=<])(\d+(?:\.\d+)?)\s*ms")


def ping_observations(text: str) -> list[dict]:
    observed = {}
    for line in text.splitlines():
        stamp, seq = STAMP.search(line), SEQ.search(line)
        if not stamp or not seq:
            continue
        rtt = RTT.search(line)
        success = rtt is not None and "bytes from" in line
        if not success and "no answer yet" not in line and "Unreachable" not in line:
            continue
        identifier = int(seq[1])
        item = {"sequence": identifier, "unix_s": float(stamp[1]), "success": success,
                "rtt_ms": float(rtt[2]) if success else None,
                "rtt_is_upper_bound": bool(success and rtt[1] == "<")}
        # ping -O may report pending before a late successful reply arrives.
        if identifier not in observed or success:
            observed[identifier] = item
    return [observed[key] for key in sorted(observed)]


def summarize_ping(observations, *, stable_successes=10, migration_start_unix_s=None,
                   baseline_path_available=None):
    if stable_successes < 1:
        raise ValueError("Stable recovery needs positive consecutive successes")
    rtts = [row["rtt_ms"] for row in observations if row["success"]]
    first_loss = recovery = None
    consecutive = longest_consecutive = 0
    previous = None
    for row in observations:
        if migration_start_unix_s is not None and row["unix_s"] < migration_start_unix_s:
            continue
        if not row["success"]:
            if first_loss is None:
                first_loss = row["unix_s"]
            consecutive = 0
        else:
            consecutive = consecutive + 1 if previous is None or row["sequence"] == previous + 1 else 1
            longest_consecutive = max(longest_consecutive, consecutive)
            if first_loss is not None and recovery is None and consecutive >= stable_successes:
                recovery = row["unix_s"]
        previous = row["sequence"]
    total = len(observations)
    losses = total-len(rtts)
    attributable = baseline_path_available is True
    return {"observed_probes": total, "successful_probes": len(rtts), "lost_probes": losses,
            "loss_fraction": losses/total if total else None,
            "rtt_mean_ms": sum(rtts)/len(rtts) if rtts else None,
            "rtt_min_ms": min(rtts) if rtts else None, "rtt_max_ms": max(rtts) if rtts else None,
            "first_loss_unix_s": first_loss, "stable_recovery_unix_s": recovery,
            "time_to_stable_recovery_s": recovery-first_loss if recovery is not None and attributable else None,
            "continuous_during_observation": total > 0 and losses == 0,
            "recovery_observed": recovery is not None,
            "longest_consecutive_successes": longest_consecutive,
            "baseline_path_available": baseline_path_available}


def json_lines(path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid observation {path}:{number}") from exc


def summarize_udp(sent_path: Path, received_path: Path):
    sent = {row["sequence"]: row for row in json_lines(sent_path) if row.get("kind") == "sent"}
    received = {}
    duplicates = 0
    for row in json_lines(received_path):
        if row.get("kind") != "received":
            continue
        if row["sequence"] in received:
            duplicates += 1
        else:
            received[row["sequence"]] = row
    valid = [row for seq, row in received.items() if seq in sent]
    valid.sort(key=lambda row: row["received_unix_ns"])
    jitter = 0.0
    previous_transit = None
    for row in valid:
        transit = (row["received_unix_ns"]-row["sent_unix_ns"])/1e6
        if previous_transit is not None:
            jitter += (abs(transit-previous_transit)-jitter)/16
        previous_transit = transit
    duration = ((max(row["sent_unix_ns"] for row in sent.values())-
                 min(row["sent_unix_ns"] for row in sent.values()))/1e9) if len(sent) > 1 else None
    size = sum(row["bytes"] for row in valid)
    return {"sent_packets": len(sent), "received_packets": len(valid), "duplicate_packets": duplicates,
            "lost_packets": len(sent)-len(valid),
            "loss_fraction": (len(sent)-len(valid))/len(sent) if sent else None,
            "received_payload_bytes": size, "observation_s": duration,
            "throughput_bps": size*8/duration if duration else None,
            "jitter_ms": jitter if len(valid) > 1 else None,
            "jitter_method": "RFC3550 transit-difference EWMA (1/16)"}


def analyze_directory(directory: Path, **ping_options):
    ping_path = directory/"ping.log"
    observations = ping_observations(ping_path.read_text(encoding="utf-8") if ping_path.exists() else "")
    return {"schema_version": 1, "ping": summarize_ping(observations, **ping_options),
            "udp": summarize_udp(directory/"udp-sent.jsonl", directory/"udp-received.jsonl")}


def classify_observations(observations, geometry, heartbeats):
    """Join probes with the latest preceding observations, never future state.

    Missing/stale measurements remain unknown; heartbeat unreachability is a
    separate flag because forwarding may continue without controller access.
    """
    geometry = sorted(geometry, key=lambda row: row['unix_s'])
    heartbeats = sorted(heartbeats, key=lambda row: row['unix_s'])
    output = []
    gi = hi = 0
    last_geometry = last_heartbeat = None
    for probe in sorted(observations, key=lambda row: row['unix_s']):
        stamp = probe['unix_s']
        while gi < len(geometry) and geometry[gi]['unix_s'] <= stamp:
            last_geometry = geometry[gi];gi += 1
        while hi < len(heartbeats) and heartbeats[hi]['unix_s'] <= stamp:
            last_heartbeat = heartbeats[hi];hi += 1
        path = last_geometry.get('service_path_available') if last_geometry and stamp-last_geometry['unix_s'] <= 3 else None
        control = any(last_heartbeat['controllers'].values()) if last_heartbeat and stamp-last_heartbeat['unix_s'] <= 10 else None
        category = ('service_available' if probe['success'] else
            'no_geometric_path' if path is False else
            'loss_with_path' if path is True else 'unknown_geometry')
        output.append({**probe,'classification':category,'geometric_path_available':path,
            'control_reachable':control})
    return output
