from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.history_cleanup import (
    apply_application_history_cleanup_plan,
    build_application_history_cleanup_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely remove learned history for selected applications."
    )
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
    )
    parser.add_argument("--application-key", action="append", default=[])
    parser.add_argument("--interface-prefix", action="append", default=[])
    parser.add_argument("--run-name-token", action="append", default=[])
    parser.add_argument("--report")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    plan = build_application_history_cleanup_plan(
        project_root=root,
        application_identity_keys=set(args.application_key),
        interface_id_prefixes=tuple(args.interface_prefix),
        learning_run_name_tokens=tuple(args.run_name_token),
    )
    result = plan
    if args.apply:
        if not args.report:
            raise SystemExit("--report is required with --apply")
        result = apply_application_history_cleanup_plan(
            plan,
            report_path=args.report,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"{result.get('status') or result.get('mode')}: "
            f"{len(result.get('deleted_paths') or result.get('delete_paths') or [])} paths"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
