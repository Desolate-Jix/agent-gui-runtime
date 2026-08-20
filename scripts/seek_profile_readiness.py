from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.seek.matching import load_candidate_profile
from app.seek.profile import assess_candidate_profile_readiness


DEFAULT_TEMPLATE: dict[str, Any] = {
    "contract_version": "candidate_profile_v1",
    "profile_source": "real_user_candidate_profile_v1",
    "profile_purpose": "real_resume_profile",
    "candidate_name": "",
    "first_name": "",
    "last_name": "",
    "preferred_name": "",
    "email": "",
    "phone": "",
    "city": "",
    "suburb": "",
    "github_url": "",
    "linkedin_url": "",
    "portfolio_url": "",
    "skills": [],
    "target_roles": [],
    "location_constraints": [],
    "experience_summary": [],
    "education_summary": [],
    "work_rights_summary": "",
    "availability_summary": "",
    "salary_preference": "",
    "preferred_work_modes": [],
    "avoid_roles": [],
    "avoid_companies": [],
    "do_not_apply_to": [],
    "risk_do_not_invent": True,
    "template_notes": [
        "Fill this with real resume/profile evidence before live SEEK safe-fill.",
        "Do not put smoke, test, synthetic, or placeholder values into a live profile.",
        "Include target roles, target locations, work-rights summary, and real project/work evidence before matching jobs.",
        "The readiness report records safe-fill field names and value lengths, not full values.",
    ],
}


def write_template(path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(DEFAULT_TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def build_report(
    *,
    candidate_profile_path: str | Path | None = None,
    template_path: str | Path | None = None,
) -> dict[str, Any]:
    template_written = write_template(template_path) if template_path else None
    profile = load_candidate_profile(candidate_profile_path) if candidate_profile_path else None
    readiness = assess_candidate_profile_readiness(profile)
    return {
        "contract_version": "seek_profile_readiness_cli_report_v1",
        "candidate_profile_path": str(candidate_profile_path) if candidate_profile_path else None,
        "template_written_path": str(template_written) if template_written else None,
        "readiness": readiness,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check candidate_profile_v1 readiness before SEEK live safe-fill.")
    parser.add_argument("--candidate-profile", type=Path, default=None, help="candidate_profile_v1 JSON to assess.")
    parser.add_argument("--write-template", type=Path, default=None, help="Write a blank candidate_profile_v1 template.")
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON report output path.")
    parser.add_argument(
        "--fail-if-blocked",
        action="store_true",
        help="Exit 2 when the profile is not ready for a single safe-field live smoke.",
    )
    args = parser.parse_args(argv)

    report = build_report(candidate_profile_path=args.candidate_profile, template_path=args.write_template)
    if args.out:
        _write_json(args.out, report)
    readiness = report["readiness"]
    summary = {
        "success": True,
        "decision": readiness.get("decision"),
        "profile_source": readiness.get("profile_source"),
        "real_user_profile_source": readiness.get("real_user_profile_source"),
        "pii_redaction_enabled": readiness.get("pii_redaction_enabled"),
        "matching_ready": readiness.get("matching_ready"),
        "safe_fill_ready": readiness.get("safe_fill_ready"),
        "cover_letter_ready": readiness.get("cover_letter_ready"),
        "live_smoke_ready": readiness.get("live_smoke_ready"),
        "missing_requirements": readiness.get("missing_requirements"),
        "optional_profile_gaps": readiness.get("optional_profile_gaps"),
        "candidate_profile_path": report.get("candidate_profile_path"),
        "template_written_path": report.get("template_written_path"),
        "out": str(args.out) if args.out else None,
    }
    print(json.dumps(summary, ensure_ascii=False))
    if args.fail_if_blocked and readiness.get("decision") != "ready_for_single_safe_field_live_smoke":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
