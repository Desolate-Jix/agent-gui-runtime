from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agent.navigation_reading_replay import run_navigation_reading_replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay reviewed multi-interface navigation, information reading, "
            "and scroll evidence without live GUI actions."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_navigation_reading_replay(
        manifest_path=args.manifest,
        out_dir=args.out,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"report: {report['report_path']}")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
