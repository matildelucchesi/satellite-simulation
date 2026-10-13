"""Summarize raw service observations, leaving unobserved values null."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.probes import analyze_directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--migration-start-unix-s", type=float)
    parser.add_argument("--baseline-path", choices=("available", "unavailable", "unknown"), default="unknown")
    args = parser.parse_args()
    result = analyze_directory(args.directory, migration_start_unix_s=args.migration_start_unix_s,
                               baseline_path_available={"available": True, "unavailable": False, "unknown": None}[args.baseline_path])
    text = json.dumps(result, indent=2, allow_nan=False)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
