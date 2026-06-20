from __future__ import annotations

from app.seek.traversal import (
    assess_seek_job_detail_completeness,
    build_seek_mvp_accuracy_summary,
    build_seek_mvp_run_report,
    merge_seek_job_details,
)


def _detail_slice(**overrides):
    base = {
        "contract_version": "seek_job_detail_v1",
        "job_id": "seek_job_demo",
        "title": "Software Engineer",
        "company": "Example Tech",
        "location": "Auckland",
        "work_type": "Full time",
        "classification": None,
        "salary_text": None,
        "description_sections": [{"index": 0, "role": "body", "text": "About the role"}],
        "requirements": ["Requirements: Python and automation experience."],
        "responsibilities": [],
        "benefits": [],
        "apply_button_state": {"visible": True, "label": "Apply", "bbox": {"x": 10, "y": 20, "w": 80, "h": 40}, "click_point": {"x": 50, "y": 40}},
        "save_button_state": {"visible": True, "label": "Save", "bbox": {"x": 100, "y": 20, "w": 80, "h": 40}},
        "detail_container": {"container_id": "seek:job_detail"},
        "detail_scroll_history": [],
        "trace_paths": ["logs/traces/actions/open.json"],
        "evidence": {"text_count": 2, "action_count": 2, "texts": ["About the role"], "source_contract": "screen_inventory_v1"},
    }
    base.update(overrides)
    return base


def test_merge_seek_job_details_deduplicates_sections_and_preserves_buttons() -> None:
    first = _detail_slice()
    second = _detail_slice(
        description_sections=[
            {"index": 0, "role": "body", "text": "About the role"},
            {"index": 1, "role": "section_hint", "text": "You will build test systems."},
        ],
        responsibilities=["You will build test systems."],
        benefits=["Benefits include flexible work."],
        trace_paths=["logs/traces/actions/open.json", "logs/traces/actions/scroll.json"],
        evidence={"text_count": 2, "action_count": 1, "texts": ["You will build test systems."], "source_contract": "screen_inventory_v1"},
    )

    merged = merge_seek_job_details([first, second])

    assert merged["contract_version"] == "seek_job_detail_v1"
    assert merged["title"] == "Software Engineer"
    assert merged["apply_button_state"]["visible"] is True
    assert [section["text"] for section in merged["description_sections"]] == [
        "About the role",
        "You will build test systems.",
    ]
    assert merged["requirements"] == ["Requirements: Python and automation experience."]
    assert merged["responsibilities"] == ["You will build test systems."]
    assert merged["benefits"] == ["Benefits include flexible work."]
    assert merged["trace_paths"] == ["logs/traces/actions/open.json", "logs/traces/actions/scroll.json"]


def test_merge_seek_job_details_deduplicates_scroll_history() -> None:
    first = _detail_slice(
        detail_scroll_history=[
            {
                "trace_path": "logs/traces/actions/scroll-1.json",
                "missing_evidence": ["responsibilities"],
            }
        ]
    )
    second = _detail_slice(
        detail_scroll_history=[
            {
                "trace_path": "logs/traces/actions/scroll-1.json",
                "missing_evidence": ["responsibilities"],
            },
            {
                "trace_path": "logs/traces/actions/scroll-2.json",
                "missing_evidence": ["requirements"],
            },
        ]
    )

    merged = merge_seek_job_details([first, second])

    assert [entry["trace_path"] for entry in merged["detail_scroll_history"]] == [
        "logs/traces/actions/scroll-1.json",
        "logs/traces/actions/scroll-2.json",
    ]


def test_detail_completeness_accepts_requirements_as_role_evidence() -> None:
    decision = assess_seek_job_detail_completeness(_detail_slice(), scroll_count=0, max_scrolls=3)

    assert decision["contract_version"] == "seek_job_detail_completeness_v1"
    assert decision["complete"] is True
    assert decision["should_scroll"] is False
    assert decision["missing_evidence"] == []


def test_detail_completeness_requires_bottom_when_requested() -> None:
    decision = assess_seek_job_detail_completeness(
        _detail_slice(detail_bottom_reached=False),
        scroll_count=0,
        max_scrolls=3,
        require_bottom=True,
    )

    assert decision["complete"] is False
    assert decision["should_scroll"] is True
    assert decision["missing_evidence"] == ["detail_bottom"]
    assert decision["bottom_reached"] is False

    complete = assess_seek_job_detail_completeness(
        _detail_slice(detail_bottom_reached=True),
        scroll_count=1,
        max_scrolls=3,
        require_bottom=True,
    )

    assert complete["complete"] is True
    assert complete["bottom_reached"] is True


def test_detail_completeness_requests_scroll_until_role_evidence_or_max_scrolls() -> None:
    incomplete = _detail_slice(requirements=[], responsibilities=[])

    decision = assess_seek_job_detail_completeness(incomplete, scroll_count=1, max_scrolls=3)

    assert decision["contract_version"] == "seek_job_detail_completeness_v1"
    assert decision["complete"] is False
    assert decision["should_scroll"] is True
    assert decision["missing_evidence"] == ["role_evidence"]
    assert decision["next_scroll_request"]["target_container_id"] == "seek:job_detail"

    stopped = assess_seek_job_detail_completeness(incomplete, scroll_count=3, max_scrolls=3)

    assert stopped["complete"] is False
    assert stopped["should_scroll"] is False
    assert stopped["stop_reason"] == "max_scrolls_reached"


def test_seek_run_report_keeps_final_submissions_zero() -> None:
    card = {
        "contract_version": "seek_job_card_v1",
        "job_id": "seek_job_demo",
        "title": "Software Engineer",
        "company": "Example Tech",
        "location": "Auckland",
    }
    detail = _detail_slice(responsibilities=["You will build test systems."])

    report = build_seek_mvp_run_report(
        job_cards=[card],
        job_details=[detail],
        match_decisions=[{"decision": "strong_apply", "score": 0.88}],
        started_application_flows=1,
        cover_letters_generated=1,
        forms_filled_until_review=1,
        elapsed_ms=1234,
    )

    assert report["contract_version"] == "seek_mvp_run_report_v1"
    assert report["jobs_seen"] == 1
    assert report["jobs_opened"] == 1
    assert report["jobs_fully_read"] == 1
    assert report["strong_apply"] == 1
    assert report["application_flows_started"] == 1
    assert report["cover_letters_generated"] == 1
    assert report["forms_filled_until_review"] == 1
    assert report["final_submissions"] == 0
    assert report["accuracy_summary"]["contract_version"] == "seek_mvp_accuracy_summary_v1"
    assert report["accuracy_summary"]["opened_rate"] == 1.0
    assert report["accuracy_summary"]["detail_read_completion_rate"] == 1.0
    assert report["accuracy_summary"]["match_decision_coverage_rate"] == 1.0
    assert report["accuracy_summary"]["safety_invariants"]["final_submissions_zero"] is True


def test_accuracy_summary_detects_wrong_scope_scrolls_and_final_submission_risk() -> None:
    summary = build_seek_mvp_accuracy_summary(
        {
            "jobs_seen": 2,
            "jobs_opened": 1,
            "jobs_fully_read": 1,
            "match_decisions": [{"decision": "maybe_apply"}],
            "submit_clicks": 1,
            "final_submissions": 0,
            "results_list_scrolls": [
                {
                    "target_pane": "job_detail",
                    "target_container_id": "seek:job_detail",
                    "trace_path": "logs/traces/actions/wrong-scroll.json",
                    "effect_validation": {"wrong_scope_detected": True},
                }
            ],
        }
    )

    assert summary["opened_rate"] == 0.5
    assert summary["wrong_scope_scroll_count"] == 1
    assert summary["safety_invariants"]["submit_clicks_zero"] is False
    assert summary["safety_invariants"]["wrong_scope_scrolls_zero"] is False
    assert summary["status"] == "needs_review"
