"""Exercise the genuine L2NM fixture; persist API evidence even on failure."""
import json
import argparse
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.fixture import state, for_destination
from src.orbit import Orbit
from src.tfs_adapter import TfsAdapter
from src.artifacts import canonical_bytes
from src.probes import analyze_directory


def admin(port, path, body=None):
    request = Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else canonical_bytes(body),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response: return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-fixture", action="store_true",
                        help="Remove only the migration fixture from both hosts before recreating it.")
    args = parser.parse_args()
    fixture = json.loads((ROOT/"config/fixture.json").read_text())
    orbit = Orbit(ROOT/"artifacts/orbit/replay.npz")
    graph = orbit.graph(0)
    a, b = TfsAdapter("http://127.0.0.1:18080"), TfsAdapter("http://127.0.0.1:18081")
    output = ROOT / "results/preflight"; output.mkdir(exist_ok=True)
    evidence = {"schema_version": 1, "execution_kind": "live", "success": False, "stage": "environment"}
    try:
        evidence["emulator"] = admin(18090, "/")
        evidence["proxy"] = admin(18091, "/")
        fixture["controller_proxy"] = evidence["proxy"]["ipv4"]
        if not evidence["emulator"]["switches_alive"]: raise RuntimeError("BMv2 process failed")
        if not all(row["upstream_master"] for row in evidence["proxy"]["states"]): raise RuntimeError("Upstream arbitration incomplete")
        admin(18090, "/links", {"pairs": [[a,b] for a in graph for b in graph[a] if a < b]})
        evidence["stage"] = "create_fixture"
        if args.reset_fixture:
            b.cleanup(b.export())
            a.cleanup(a.export())
        initial = state(fixture, graph)
        (output/"fixture-state.json").write_bytes(canonical_bytes(initial))
        a.restore(initial)
        source = a.export()
        (output/"source-snapshot.json").write_bytes(canonical_bytes(source))
        evidence["source_entity_counts"] = {key: len(value) for key,value in source["entities"].items()}
        if len(source["entities"]["devices"]) != 17: raise RuntimeError("Fixture did not create all 17 devices")
        evidence["stage"] = "restore_standby"
        expected = for_destination(source, fixture)
        b.restore(expected)
        evidence["verification"] = b.verify(expected)
        if not evidence["verification"]["equivalent"]: raise RuntimeError("Standby API state mismatch")
        evidence["stage"] = "service_probe"
        probe_id = "preflight-"+str(time.time_ns())
        admin(18090, "/probes/start", {"run_id": probe_id})
        try:
            time.sleep(5)
        finally:
            admin(18090, "/probes/stop", {})
        evidence["probes"] = analyze_directory(ROOT/"results/lab"/probe_id,
                                                baseline_path_available=True)
        evidence["probe_run_id"] = probe_id
        if evidence["probes"]["ping"]["longest_consecutive_successes"] < 10:
            raise RuntimeError("API restore passed but fewer than 10 consecutive successful end-to-end pings")
        if evidence["probes"]["udp"]["received_packets"] == 0:
            raise RuntimeError("API restore passed but no UDP payload reached the destination")
        evidence["success"] = True
        evidence["stage"] = "api_restore_and_service_verified"
    except Exception as exc:
        evidence["error"] = str(exc)
    finally:
        evidence["api_calls_a"], evidence["api_calls_b"] = a.calls, b.calls
        (output/"live-preflight.json").write_text(json.dumps(evidence, indent=2)+"\n")
    print(json.dumps({key: value for key,value in evidence.items() if key not in {"api_calls_a", "api_calls_b", "verification"}}, indent=2))
    return 0 if evidence["success"] else 2


if __name__ == "__main__": raise SystemExit(main())
