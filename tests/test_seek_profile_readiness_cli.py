from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seek_profile_readiness.py"
spec = importlib.util.spec_from_file_location("seek_profile_readiness", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def test_build_report_blocks_missing_profile() -> None:
    report = cli.build_report()

    assert report["contract_version"] == "seek_profile_readiness_cli_report_v1"
    assert report["readiness"]["decision"] == "blocked_need_real_candidate_profile"
    assert "candidate_profile_json" in report["readiness"]["missing_requirements"]


def test_cli_writes_blank_template_without_safe_values(tmp_path) -> None:
    template_path = tmp_path / "candidate_profile_template.json"

    report = cli.build_report(template_path=template_path)
    payload = json.loads(template_path.read_text(encoding="utf-8"))

    assert report["template_written_path"] == str(template_path)
    assert payload["contract_version"] == "candidate_profile_v1"
    assert payload["profile_source"] == "real_user_candidate_profile_v1"
    assert payload["profile_purpose"] == "real_resume_profile"
    assert payload["email"] == ""
    assert payload["skills"] == []
    assert payload["education_summary"] == []
    assert payload["work_rights_summary"] == ""
    assert payload["avoid_roles"] == []
    assert report["readiness"]["safe_fill_ready"] is False


def test_cli_accepts_real_profile_and_writes_report(tmp_path, capsys) -> None:
    profile_path = tmp_path / "candidate_profile.json"
    out_path = tmp_path / "readiness.json"
    profile_path.write_text(
        json.dumps(
            {
                "contract_version": "candidate_profile_v1",
                "profile_source": "real_user_candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
                "candidate_name": "Alex Chen",
                "email": "alex@example.com",
                "skills": ["Python", "JavaScript"],
                "target_roles": ["Software Engineer"],
                "location_constraints": ["Auckland", "Remote"],
                "work_rights_summary": "Open work rights in New Zealand.",
                "experience_summary": ["Built automation projects with Python and JavaScript."],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(["--candidate-profile", str(profile_path), "--out", str(out_path), "--fail-if-blocked"])
    printed = json.loads(capsys.readouterr().out)
    report = json.loads(out_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert printed["decision"] == "ready_for_single_safe_field_live_smoke"
    assert printed["profile_source"] == "real_user_candidate_profile_v1"
    assert printed["real_user_profile_source"] is True
    assert printed["pii_redaction_enabled"] is True
    assert report["readiness"]["profile_source"] == "real_user_candidate_profile_v1"
    assert report["readiness"]["pii_redaction_enabled"] is True
    assert report["readiness"]["matching_ready"] is True
    assert report["readiness"]["safe_fill_ready"] is True
    assert report["readiness"]["live_smoke_ready"] is True
    assert {item["field"] for item in report["readiness"]["safe_fill_values"]} >= {"candidate_name", "email"}


def test_cli_fail_if_blocked_returns_2_for_smoke_profile(capsys) -> None:
    smoke_profile = Path(__file__).resolve().parent / "smoke" / "seek_candidate_profile_smoke.json"

    exit_code = cli.main(["--candidate-profile", str(smoke_profile), "--fail-if-blocked"])
    printed = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert printed["decision"] == "blocked_need_real_candidate_profile"
