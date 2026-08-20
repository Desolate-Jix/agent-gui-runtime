from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.runtime_storage_cleanup import apply_cleanup_plan, build_cleanup_plan


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely prune old temporary files and unreferenced review overlays.",
    )
    parser.add_argument("--older-than-days", type=int, default=14)
    parser.add_argument("--keep-latest-per-directory", type=int, default=3)
    parser.add_argument(
        "--out",
        default="logs/cleanup",
        help="Project-local directory for the plan and apply report.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete exactly the unchanged files in the generated plan.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    output_dir = (ROOT / args.out).resolve()
    try:
        output_dir.relative_to(ROOT)
    except ValueError as exc:
        raise SystemExit("--out must remain inside the project root") from exc
    output_dir.mkdir(parents=True, exist_ok=True)

    plan = build_cleanup_plan(
        root=ROOT,
        older_than_days=args.older_than_days,
        keep_latest_per_directory=args.keep_latest_per_directory,
    )
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    plan_path = output_dir / f"runtime_storage_cleanup_plan_{timestamp}.json"
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result: dict[str, object] = {
        "mode": "dry_run",
        "plan_path": str(plan_path.relative_to(ROOT)).replace("\\", "/"),
        "candidate_files": plan["candidate_files"],
        "candidate_bytes": plan["candidate_bytes"],
        "protected_files": plan["protected_files"],
        "reference_scan_errors": len(plan["reference_scan_errors"]),
    }
    if args.apply:
        report_path = output_dir / f"runtime_storage_cleanup_report_{timestamp}.json"
        report = apply_cleanup_plan(plan, report_path=report_path)
        result.update(
            {
                "mode": "applied",
                "report_path": str(report_path.relative_to(ROOT)).replace("\\", "/"),
                "deleted_files": report["deleted_files"],
                "deleted_bytes": report["deleted_bytes"],
                "removed_directories": report["removed_directories"],
                "skipped_files": len(report["skipped"]),
            }
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"{result['mode']}: {result['candidate_files']} candidate files, "
            f"{int(result['candidate_bytes']) / (1024 ** 3):.2f} GiB"
        )
        print(f"plan: {result['plan_path']}")
        if args.apply:
            print(
                f"deleted: {result['deleted_files']} files, "
                f"{int(result['deleted_bytes']) / (1024 ** 3):.2f} GiB"
            )
            print(f"removed empty directories: {result['removed_directories']}")
            print(f"report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
