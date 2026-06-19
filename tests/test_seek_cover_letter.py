from __future__ import annotations

from app.seek.cover_letter import build_cover_letter_draft


def _detail() -> dict:
    return {
        "contract_version": "seek_job_detail_v1",
        "job_id": "job-1",
        "title": "Software Engineer",
        "company": "Example Systems",
        "requirements": ["Build Python APIs", "Debug production issues"],
        "responsibilities": ["Develop backend services", "Write automated tests"],
        "evidence": {"texts": ["Python", "automated tests", "backend services"]},
    }


def _decision() -> dict:
    return {
        "contract_version": "seek_job_match_decision_v1",
        "job_id": "job-1",
        "title": "Software Engineer",
        "company": "Example Systems",
        "decision": "strong_apply",
        "positive_evidence": ["matched_skills: Python, test automation, backend"],
        "negative_evidence": [],
        "risk_flags": ["do_not_invent_experience"],
    }


def test_cover_letter_draft_blocks_smoke_profile() -> None:
    draft = build_cover_letter_draft(
        profile={
            "contract_version": "candidate_profile_v1",
            "profile_purpose": "smoke_test_only_not_user_resume",
            "skills": ["Python"],
            "experience_summary": ["Synthetic smoke profile."],
        },
        detail=_detail(),
        match_decision=_decision(),
    )

    assert draft["contract_version"] == "cover_letter_draft_v1"
    assert draft["status"] == "blocked_need_real_resume_profile"
    assert draft["draft"] == ""
    assert draft["blocked_reason"] == "candidate_profile_is_missing_or_marked_smoke_test"


def test_cover_letter_draft_generates_truthful_draft_for_real_profile() -> None:
    draft = build_cover_letter_draft(
        profile={
            "contract_version": "candidate_profile_v1",
            "candidate_name": "Alex Chen",
            "profile_purpose": "real_resume_summary",
            "skills": ["Python", "test automation", "backend"],
            "target_roles": ["Software Engineer"],
            "experience_summary": [
                "Built a Windows GUI automation runtime with gated execution and trace logging",
                "Implemented backend APIs and test automation for local developer tools",
            ],
            "risk_do_not_invent": True,
        },
        detail=_detail(),
        match_decision=_decision(),
    )

    assert draft["status"] == "draft_only_not_pasted"
    assert "Software Engineer" in draft["draft"]
    assert "Example Systems" in draft["draft"]
    assert "Python" in draft["draft"]
    assert "Alex Chen" in draft["draft"]
    assert draft["truthfulness_checks"]["does_not_claim_commercial_years"] is True
    assert draft["truthfulness_checks"]["does_not_claim_submitted_application"] is True
    assert draft["truthfulness_checks"]["does_not_invent_skills"] is True
    assert draft["truthfulness_checks"]["draft_only_not_pasted"] is True


def test_cover_letter_draft_requires_strong_apply() -> None:
    decision = {**_decision(), "decision": "maybe_apply"}

    draft = build_cover_letter_draft(
        profile={
            "contract_version": "candidate_profile_v1",
            "profile_purpose": "real_resume_summary",
            "skills": ["Python"],
            "experience_summary": ["Built backend APIs."],
        },
        detail=_detail(),
        match_decision=decision,
    )

    assert draft["status"] == "blocked_decision_not_strong_apply"
    assert draft["draft"] == ""
