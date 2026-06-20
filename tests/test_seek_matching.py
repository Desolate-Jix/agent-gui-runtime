from __future__ import annotations

import json
from pathlib import Path

from app.seek.matching import load_candidate_profile, merge_seek_job_identity, save_suitable_job_record, score_seek_job


def _card() -> dict:
    return {
        "contract_version": "seek_job_card_v1",
        "job_id": "seek_job_software_engineer",
        "title": "Software Engineer",
        "company": "Example Systems",
        "location": "Auckland CBD, Auckland",
    }


def _detail() -> dict:
    return {
        "contract_version": "seek_job_detail_v1",
        "job_id": "seek_job_software_engineer",
        "title": "Software Engineer",
        "company": "Example Systems",
        "location": "Auckland CBD, Auckland",
        "requirements": ["C# programming experience", "SQL and test automation"],
        "responsibilities": ["Build backend services and support production systems."],
        "benefits": ["Hybrid work"],
        "evidence": {"texts": ["C# programming", "SQL", "test automation", "backend services"]},
    }


def test_missing_profile_requires_user_review() -> None:
    decision = score_seek_job(profile=None, card=_card(), detail=_detail())

    assert decision["contract_version"] == "seek_job_match_decision_v1"
    assert decision["decision"] == "need_user_review"
    assert decision["score"] == 0.0
    assert "do_not_invent_experience" in decision["risk_flags"]
    assert decision["unknowns"] == ["candidate_profile_v1 missing or incomplete"]


def test_profile_match_scores_and_saves_suitable_job(tmp_path) -> None:
    profile_path = tmp_path / "candidate.json"
    profile_path.write_text(
        json.dumps(
            {
                "contract_version": "candidate_profile_v1",
                "skills": ["C#", "SQL", "test automation", "backend"],
                "target_roles": ["Software Engineer"],
                "location_constraints": ["Auckland"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    profile = load_candidate_profile(profile_path)
    decision = score_seek_job(profile=profile, card=_card(), detail=_detail())
    saved_path = save_suitable_job_record(
        decision=decision,
        card=_card(),
        detail=_detail(),
        output_dir=tmp_path / "saved",
    )

    assert decision["decision"] == "strong_apply"
    assert decision["score"] >= 0.7
    assert decision["fit_summary"].startswith("strong_apply with score")
    assert "matched_skills" in decision["fit_summary"]
    assert decision["recommended_next_action"] == "open_apply_entry_and_prepare_safe_fields"
    assert any("matched_skills" in item for item in decision["positive_evidence"])
    assert saved_path is not None
    saved = json.loads((tmp_path / "saved" / "seek_job_software_engineer.json").read_text(encoding="utf-8"))
    assert saved["contract_version"] == "saved_seek_job_record_v1"
    assert saved["decision"]["decision"] == "strong_apply"


def test_profile_match_normalizes_ai_and_api_ocr_variants() -> None:
    detail = {
        **_detail(),
        "title": "Intermediate Engineer - Al Automation & Integration",
        "requirements": ["Implement Al-enabled solutions", "Design APl integrations", "React frontend delivery"],
        "responsibilities": ["Build chatbots and workflow automation with Azure Al services."],
    }

    decision = score_seek_job(
        profile={
            "contract_version": "candidate_profile_v1",
            "skills": ["AI", "API", "React", "Automation"],
            "target_roles": ["AI Engineer", "Automation Engineer"],
            "location_constraints": ["Auckland"],
            "preferred_work_modes": ["hybrid"],
        },
        card={**_card(), "title": "Intermediate Engineer - Al Automation & Integration"},
        detail=detail,
    )

    assert decision["decision"] == "strong_apply"
    assert any("AI" in item and "API" in item for item in decision["positive_evidence"])


def test_profile_match_target_role_allows_reordered_role_tokens() -> None:
    decision = score_seek_job(
        profile={
            "contract_version": "candidate_profile_v1",
            "skills": ["AI", "Automation"],
            "target_roles": ["AI Engineer", "Automation Engineer"],
            "location_constraints": ["Auckland"],
            "preferred_work_modes": ["hybrid"],
        },
        card={
            **_card(),
            "title": "IntermediateEngineer-AlAutomation&Integration",
            "location": "Auckland CBD, Auckland (Hybrid)",
        },
        detail={
            **_detail(),
            "title": "IntermediateEngineer-AlAutomation&Integration",
            "location": "Auckland CBD, Auckland (Hybrid)",
            "requirements": ["Build Al automation and integration solutions"],
            "benefits": ["Hybrid work"],
        },
    )

    assert decision["decision"] == "strong_apply"
    assert any("matched_target_roles" in item for item in decision["positive_evidence"])


def test_location_mismatch_can_skip() -> None:
    decision = score_seek_job(
        profile={
            "contract_version": "candidate_profile_v1",
            "skills": ["C#"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Wellington"],
        },
        card=_card(),
        detail=_detail(),
    )

    assert decision["decision"] == "skip"
    assert any("location_mismatch" in item for item in decision["negative_evidence"])


def test_new_zealand_constraint_accepts_other_nz_cities() -> None:
    decision = score_seek_job(
        profile={
            "contract_version": "candidate_profile_v1",
            "skills": ["React", "SQL", "Frontend"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Auckland", "New Zealand"],
        },
        card={**_card(), "location": "Christchurch Central, Canterbury"},
        detail={
            **_detail(),
            "location": "Christchurch Central, Canterbury",
            "requirements": ["React frontend development", "SQL"],
        },
    )

    assert any("location_matches: Christchurch Central, Canterbury" in item for item in decision["positive_evidence"])
    assert not any("location_mismatch" in item for item in decision["negative_evidence"])
    assert decision["decision"] in {"strong_apply", "maybe_apply"}


def test_incomplete_detail_forces_review_even_with_matching_profile(tmp_path) -> None:
    decision = score_seek_job(
        profile={
            "contract_version": "candidate_profile_v1",
            "skills": ["C#", "SQL", "test automation", "backend"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Auckland"],
        },
        card=_card(),
        detail=_detail(),
        detail_complete=False,
        missing_detail_evidence=["responsibilities"],
    )
    saved_path = save_suitable_job_record(
        decision=decision,
        card=_card(),
        detail=_detail(),
        output_dir=tmp_path / "saved",
    )

    assert decision["decision"] == "need_user_review"
    assert decision["score"] == 0.0
    assert "detail_incomplete_do_not_apply" in decision["risk_flags"]
    assert "missing_detail_evidence: responsibilities" in decision["unknowns"]
    assert saved_path is None


def test_candidate_profile_exclusions_skip_and_do_not_save(tmp_path) -> None:
    decision = score_seek_job(
        profile={
            "contract_version": "candidate_profile_v1",
            "skills": ["C#", "SQL", "backend"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Auckland"],
            "avoid_roles": ["test systems"],
            "avoid_companies": ["Example Systems"],
        },
        card=_card(),
        detail={**_detail(), "title": "Software Engineer - Test Systems"},
    )
    saved_path = save_suitable_job_record(
        decision=decision,
        card=_card(),
        detail=_detail(),
        output_dir=tmp_path / "saved",
    )

    assert decision["decision"] == "skip"
    assert decision["score"] == 0.0
    assert "candidate_profile_exclusion_matched" in decision["risk_flags"]
    assert any("excluded_role_or_term_matches" in item for item in decision["negative_evidence"])
    assert any("excluded_company_matches" in item for item in decision["negative_evidence"])
    assert saved_path is None


def test_preferred_work_mode_adds_evidence_without_overriding_safety() -> None:
    decision = score_seek_job(
        profile={
            "contract_version": "candidate_profile_v1",
            "skills": ["C#", "SQL", "test automation", "backend"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Auckland"],
            "preferred_work_modes": ["Hybrid"],
        },
        card=_card(),
        detail=_detail(),
    )

    assert decision["decision"] == "strong_apply"
    assert any("matched_preferred_work_modes: Hybrid" in item for item in decision["positive_evidence"])


def test_work_rights_or_background_check_terms_require_review() -> None:
    detail = {
        **_detail(),
        "requirements": [
            "C# programming experience",
            "Applicants must have NZ citizenship and security clearance.",
        ],
    }

    decision = score_seek_job(
        profile={
            "contract_version": "candidate_profile_v1",
            "skills": ["C#", "SQL", "test automation", "backend"],
            "target_roles": ["Software Engineer"],
            "location_constraints": ["Auckland"],
            "work_rights_summary": "Open work rights in New Zealand.",
        },
        card=_card(),
        detail=detail,
    )

    assert decision["decision"] == "need_user_review"
    assert "work_rights_or_background_check_requires_review" in decision["risk_flags"]
    assert any("work_rights_or_background_check_requires_review" in item for item in decision["unknowns"])


def test_card_identity_repairs_compact_ocr_title_and_missing_location(tmp_path) -> None:
    card = {
        **_card(),
        "title": "Senior Android Developer",
        "company": "Fiserv New Zealand Limited",
        "location": "Auckland CBD, Auckland",
    }
    detail = {
        **_detail(),
        "job_id": "seek_job_android",
        "title": "SeniorAndroid Developer",
        "company": "Fiserv New Zealand Limited",
        "location": None,
        "requirements": ["Android development", "React Native", "AI tools"],
        "evidence": {"texts": ["Android", "React Native", "AI tools"]},
    }

    decision = score_seek_job(
        profile={
            "contract_version": "candidate_profile_v1",
            "skills": ["Android", "React Native", "AI"],
            "target_roles": ["Android Developer"],
            "location_constraints": ["Auckland"],
        },
        card=card,
        detail=detail,
    )
    saved_path = save_suitable_job_record(decision=decision, card=card, detail=detail, output_dir=tmp_path / "saved")

    assert decision["title"] == "Senior Android Developer"
    assert any("location_matches: Auckland CBD, Auckland" in item for item in decision["positive_evidence"])
    assert saved_path is not None
    saved = json.loads(Path(saved_path).read_text(encoding="utf-8"))
    assert saved["detail"]["title"] == "Senior Android Developer"
    assert saved["detail"]["location"] == "Auckland CBD, Auckland"


def test_merge_seek_job_identity_is_reusable_for_apply_entry_goal() -> None:
    merged = merge_seek_job_identity(
        {"title": "Senior Android Developer", "company": "Fiserv", "location": "Auckland CBD, Auckland"},
        {"title": "SeniorAndroid Developer", "company": "Fiserv", "location": None},
    )

    assert merged["title"] == "Senior Android Developer"
    assert merged["location"] == "Auckland CBD, Auckland"
