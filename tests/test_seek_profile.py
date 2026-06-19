from __future__ import annotations

from app.seek.profile import assess_candidate_profile_readiness


def test_profile_readiness_blocks_smoke_profile() -> None:
    readiness = assess_candidate_profile_readiness(
        {
            "contract_version": "candidate_profile_v1",
            "profile_purpose": "smoke_test_only_not_user_resume",
            "experience_summary": ["Synthetic smoke profile. Do not use for real applications."],
            "skills": ["Python"],
            "email": "smoke@example.com",
        }
    )

    assert readiness["contract_version"] == "candidate_profile_readiness_v1"
    assert readiness["is_smoke_or_test_profile"] is True
    assert readiness["safe_fill_ready"] is False
    assert readiness["cover_letter_ready"] is False
    assert readiness["decision"] == "blocked_need_real_candidate_profile"
    assert "real_profile_purpose" in readiness["missing_requirements"]


def test_profile_readiness_accepts_real_profile_with_safe_text_value() -> None:
    readiness = assess_candidate_profile_readiness(
            {
                "contract_version": "candidate_profile_v1",
                "profile_source": "real_user_candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
            "candidate_name": "Alex Chen",
            "email": "alex@example.com",
            "experience_summary": ["Built production-style Python and JavaScript automation projects."],
            "skills": ["Python", "JavaScript"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Auckland", "Remote"],
            "work_rights_summary": "Open work rights in New Zealand.",
        }
    )

    assert readiness["is_smoke_or_test_profile"] is False
    assert readiness["matching_ready"] is True
    assert readiness["safe_fill_ready"] is True
    assert readiness["cover_letter_ready"] is True
    assert readiness["live_smoke_ready"] is True
    assert readiness["profile_source"] == "real_user_candidate_profile_v1"
    assert readiness["real_user_profile_source"] is True
    assert readiness["pii_redaction_enabled"] is True
    assert readiness["decision"] == "ready_for_single_safe_field_live_smoke"
    assert {item["field"] for item in readiness["safe_fill_values"]} >= {"candidate_name", "email"}


def test_profile_readiness_does_not_flag_test_automation_as_test_profile() -> None:
    readiness = assess_candidate_profile_readiness(
            {
                "contract_version": "candidate_profile_v1",
                "profile_source": "real_user_candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
            "candidate_name": "Alex Chen",
            "email": "alex@example.com",
            "experience_summary": ["Built C# test automation and Python GUI agent projects."],
            "skills": ["C#", "test automation", "Python"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Auckland"],
            "work_rights_summary": "Open work rights in New Zealand.",
        }
    )

    assert readiness["is_smoke_or_test_profile"] is False
    assert readiness["smoke_or_test_markers"] == []
    assert readiness["decision"] == "ready_for_single_safe_field_live_smoke"


def test_profile_readiness_blocks_real_looking_profile_without_explicit_source() -> None:
    readiness = assess_candidate_profile_readiness(
        {
            "contract_version": "candidate_profile_v1",
            "profile_purpose": "real_resume_profile",
            "candidate_name": "Alex Chen",
            "email": "alex@example.com",
            "experience_summary": ["Built C# test automation and Python GUI agent projects."],
            "skills": ["C#", "test automation", "Python"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Auckland"],
            "work_rights_summary": "Open work rights in New Zealand.",
        }
    )

    assert readiness["matching_ready"] is True
    assert readiness["cover_letter_ready"] is False
    assert readiness["safe_fill_ready"] is False
    assert readiness["live_smoke_ready"] is False
    assert readiness["decision"] == "blocked_need_real_candidate_profile"
    assert "profile_source_real_user_candidate_profile_v1" in readiness["missing_requirements"]


def test_profile_readiness_requires_safe_text_value_for_live_fill() -> None:
    readiness = assess_candidate_profile_readiness(
            {
                "contract_version": "candidate_profile_v1",
                "profile_source": "real_user_candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
            "experience_summary": ["Backend automation project experience."],
            "skills": ["Python"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Auckland"],
            "work_rights_summary": "Open work rights in New Zealand.",
        }
    )

    assert readiness["cover_letter_ready"] is True
    assert readiness["matching_ready"] is True
    assert readiness["safe_fill_ready"] is False
    assert readiness["live_smoke_ready"] is False
    assert "at_least_one_safe_text_field_value" in readiness["missing_requirements"]


def test_profile_readiness_requires_location_and_work_rights_for_live_smoke() -> None:
    readiness = assess_candidate_profile_readiness(
            {
                "contract_version": "candidate_profile_v1",
                "profile_source": "real_user_candidate_profile_v1",
                "profile_purpose": "real_resume_profile",
            "candidate_name": "Alex Chen",
            "email": "alex@example.com",
            "experience_summary": ["Backend automation project experience."],
            "skills": ["Python"],
            "target_roles": ["Software Engineer"],
        }
    )

    assert readiness["cover_letter_ready"] is True
    assert readiness["safe_fill_ready"] is True
    assert readiness["matching_ready"] is False
    assert readiness["live_smoke_ready"] is False
    assert readiness["decision"] == "blocked_need_real_candidate_profile"
    assert "location_constraints" in readiness["missing_requirements"]
    assert "work_rights_summary" in readiness["missing_requirements"]
