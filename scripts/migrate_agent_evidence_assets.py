from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.agent_evidence import migrate_agent_evidence_assets

def main() -> int:
    parser = argparse.ArgumentParser(
        description="为旧单界面资产生成 Agent 可读语义证据旁路文件。"
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--application-identity-key")
    parser.add_argument("--out")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = migrate_agent_evidence_assets(
        project_root=Path(args.project_root),
        application_identity_key=args.application_identity_key,
    )
    if args.out:
        output_path = Path(args.out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "Agent evidence migration: "
            f"assets={report['asset_count']} "
            f"agent_usable={report['agent_usable_count']} "
            f"needs_human_review={report['needs_human_review_count']} "
            f"invalid={report['invalid_count']}"
        )
    return 0 if report["invalid_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
