from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.profile.cv import build_candidate_profile_from_cv_text, extract_cv_text
from app.seek.profile import assess_candidate_profile_readiness


def build_profile_from_cv(*, cv_path: str | Path) -> dict:
    extraction = extract_cv_text(cv_path)
    profile = build_candidate_profile_from_cv_text(extraction["text"], source_path=cv_path)
    profile["profile_generation"]["source_text_hash"] = extraction["text_hash"]
    profile["profile_generation"]["source_format"] = extraction["source_format"]
    profile["profile_generation"]["source_character_count"] = extraction["character_count"]
    return profile


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _summary(profile: dict, *, cv_path: Path, out_path: Path | None) -> dict:
    readiness = assess_candidate_profile_readiness(profile)
    return {
        "success": True,
        "contract_version": "candidate_profile_from_cv_summary_v1",
        "cv_path": str(cv_path),
        "out": str(out_path) if out_path else None,
        "candidate_name_present": bool(profile.get("candidate_name")),
        "email_length": len(str(profile.get("email") or "")),
        "phone_length": len(str(profile.get("phone") or "")),
        "skill_count": len(profile.get("skills") or []),
        "target_roles": profile.get("target_roles") or [],
        "location_constraints": profile.get("location_constraints") or [],
        "work_rights_present": bool(profile.get("work_rights_summary")),
        "profile_review_required": profile.get("profile_review_required"),
        "readiness_decision": readiness.get("decision"),
        "missing_requirements": readiness.get("missing_requirements"),
        "optional_profile_gaps": readiness.get("optional_profile_gaps"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a candidate_profile_v1 draft from a local CV document.")
    parser.add_argument("--cv", type=Path, required=True, help="Path to a local .docx, .txt, or .md CV.")
    parser.add_argument("--out", type=Path, default=None, help="Output candidate_profile_v1 JSON path.")
    args = parser.parse_args(argv)

    profile = build_profile_from_cv(cv_path=args.cv)
    if args.out:
        _write_json(args.out, profile)
    print(json.dumps(_summary(profile, cv_path=args.cv, out_path=args.out), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
