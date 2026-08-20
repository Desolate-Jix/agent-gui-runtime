from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.agent.profile.cv import build_candidate_profile_from_cv_text, extract_cv_text
from app.seek.profile import assess_candidate_profile_readiness


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "candidate_profile_from_cv.py"
spec = importlib.util.spec_from_file_location("candidate_profile_from_cv", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


CV_TEXT = """EXAMPLE USER
Auckland, New Zealand
+1 555 010 0000 | user@example.invalid
SUMMARY
IT graduate from the University of Auckland with data analytics and frontend applications experience.
Built Python and JavaScript automation projects with React, SQL, Power BI, and API integration.
"""


def test_build_candidate_profile_from_cv_text_keeps_real_source_but_requires_review() -> None:
    profile = build_candidate_profile_from_cv_text(CV_TEXT, source_path="D:/example/cv.docx")
    readiness = assess_candidate_profile_readiness(profile)

    assert profile["contract_version"] == "candidate_profile_v1"
    assert profile["profile_source"] == "real_user_candidate_profile_v1"
    assert profile["candidate_name"] == "Example User"
    assert profile["email"] == "user@example.invalid"
    assert profile["phone"] == "+1 555 010 0000"
    assert {"Python", "JavaScript", "React", "SQL", "Power BI"} <= set(profile["skills"])
    assert "Software Engineer" in profile["target_roles"]
    assert "Data Analyst" in profile["target_roles"]
    assert profile["profile_review_required"] is True
    assert readiness["decision"] == "blocked_need_real_candidate_profile"
    assert "work_rights_summary" in readiness["missing_requirements"]


def test_extract_cv_text_reads_utf8_text_file(tmp_path) -> None:
    path = tmp_path / "cv.txt"
    path.write_text(CV_TEXT, encoding="utf-8")

    result = extract_cv_text(path)

    assert result["contract_version"] == "cv_text_extraction_v1"
    assert result["source_format"] == "txt"
    assert result["line_count"] >= 5
    assert result["text_hash"]


def test_cli_writes_profile_and_redacts_summary_values(tmp_path, capsys) -> None:
    cv_path = tmp_path / "cv.txt"
    out_path = tmp_path / "candidate_profile.json"
    cv_path.write_text(CV_TEXT, encoding="utf-8")

    exit_code = cli.main(["--cv", str(cv_path), "--out", str(out_path)])
    printed = capsys.readouterr().out
    summary = json.loads(printed)
    profile = json.loads(out_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert summary["success"] is True
    assert summary["email_length"] == len("user@example.invalid")
    assert summary["phone_length"] == len("+1 555 010 0000")
    assert "user@example.invalid" not in printed
    assert "+1 555 010 0000" not in printed
    assert profile["email"] == "user@example.invalid"
