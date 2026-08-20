from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.seek.application import build_seek_application_final_review_audit


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON in {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a SEEK station-internal application fill record before final submit.")
    parser.add_argument("--record", type=Path, required=True, help="Path to application_fill_record.json")
    parser.add_argument("--out", type=Path, default=None, help="Output audit JSON path")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit non-zero unless the audit passes")
    args = parser.parse_args()

    record = _read_json(args.record)
    audit = build_seek_application_final_review_audit(
        record,
        base_dir=Path.cwd(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    out = args.out or (args.record.parent / "final_review_audit.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "decision": audit["decision"]}, ensure_ascii=False))

    if args.fail_on_error and audit["decision"] != "pass_stopped_before_final_submit":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
