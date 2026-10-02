#!/usr/bin/env python3
"""Choose the three representative events from a trigger-qualified event file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from src.event_sampling import select_percentile_events


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results" / "trigger_qualified_events.json"
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "config" / "selected_events.json"
    if not source.exists():
        print(f"NOT READY: trigger-qualified events not available at {source}")
        return 2
    document = json.loads(source.read_text(encoding="utf-8"))
    selected = select_percentile_events(document["events"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"source": str(source), "percentile_method": "linear Type-7; nearest unique events",
                                  "events": selected}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected": [{"percentile_case": event["percentile_case"],
                                     "event_id": event["event_id"],
                                     "orbital_margin_s": event["orbital_margin_s"]}
                                    for event in selected], "output": str(target)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
