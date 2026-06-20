from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.seek.application_artifacts import build_seek_application_flow_artifact


def read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_export(
    *,
    record_path: str | Path,
    audit_path: str | Path | None = None,
    final_review_extraction_path: str | Path | None = None,
) -> dict[str, Any]:
    record_file = Path(record_path)
    audit_file = Path(audit_path) if audit_path else None
    extraction_file = Path(final_review_extraction_path) if final_review_extraction_path else None
    return build_seek_application_flow_artifact(
        read_json(record_file),
        audit=read_json(audit_file) if audit_file and audit_file.exists() else None,
        final_review_extraction=read_json(extraction_file) if extraction_file and extraction_file.exists() else None,
        record_path=record_file,
        audit_path=audit_file,
        final_review_extraction_path=extraction_file,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a SEEK station-internal application-fill milestone as Learn Mode evidence."
    )
    parser.add_argument("--record", type=Path, required=True, help="seek_application_fill_record_v1 JSON path.")
    parser.add_argument("--audit", type=Path, default=None, help="Optional seek_application_final_review_audit_v1 path.")
    parser.add_argument(
        "--final-review-extraction",
        type=Path,
        default=None,
        help="Optional seek_final_review_extraction_v1 JSON path.",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output seek_application_flow_artifact_v1 path.")
    args = parser.parse_args(argv)

    artifact = build_export(
        record_path=args.record,
        audit_path=args.audit,
        final_review_extraction_path=args.final_review_extraction,
    )
    write_json(args.out, artifact)
    print(
        json.dumps(
            {
                "success": True,
                "contract_version": artifact.get("contract_version"),
                "out": str(args.out),
                "audit_decision": artifact.get("source", {}).get("audit_decision"),
                "final_review_extraction_status": artifact.get("source", {}).get("final_review_extraction_status"),
                "state_count": len(artifact.get("state_sequence") or []),
                "action_template_count": len(artifact.get("action_templates") or []),
                "artifact_is_authorization": artifact.get("milestone", {}).get("artifact_is_authorization"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
