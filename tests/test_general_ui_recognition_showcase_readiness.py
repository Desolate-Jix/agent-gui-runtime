from __future__ import annotations

from scripts.check_general_ui_recognition_showcase_readiness import evaluate_readiness


def _benchmark() -> dict:
    return {
        "contract_version": "general_ui_recognition_benchmark_report_v1",
        "summary": {
            "valid_case_count": 12,
            "supported_application_family_count": 8,
            "reliability_status": "minimum_diversity_reached",
            "known_limitation_count": 1,
            "invalid_fixture_count": 0,
        },
        "ownership_golden_holdout": {
            "fixture_status": "valid",
            "passed": 32,
            "attempted": 32,
            "annotated_application_family_count": 8,
            "reliability_status": "minimum_thresholds_met",
            "mismatches": [],
        },
        "review_evidence_summary": {"available": 12, "invalid": 0},
        "fixture_validity_failures": [],
        "known_limitations": [{"case_id": "transparent_overlay"}],
        "safety": {
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
            "declared_side_effect_counts": {"model_calls": 0, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "static_source_audit": {"passed": True},
        },
    }


def _panel_smoke() -> dict:
    return {
        "contract_version": "general_ui_recognition_panel_smoke_v1",
        "source": "actual_local_panel",
        "desktop": {
            "compiled_overlay_rendered": True,
            "hierarchy_rendered": True,
            "page_details_rendered": True,
            "horizontal_overflow": False,
            "screenshot_path": "logs/panel/desktop.png",
        },
        "mobile": {
            "compiled_overlay_rendered": True,
            "hierarchy_rendered": True,
            "page_details_rendered": True,
            "horizontal_overflow": False,
            "screenshot_path": "logs/panel/mobile.png",
        },
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def test_showcase_readiness_is_ready_only_when_all_coverage_and_panel_gates_pass() -> None:
    report = evaluate_readiness(_benchmark(), _panel_smoke())

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["blocked"] is False
    assert report["failed_gate_ids"] == []
    assert report["interpretation"].startswith("Showcase evidence gate")
    assert "overall_success_rate" not in report


def test_showcase_readiness_needs_review_when_diversity_and_owner_holdout_are_small() -> None:
    benchmark = _benchmark()
    benchmark["summary"]["supported_application_family_count"] = 4
    benchmark["summary"]["reliability_status"] = "insufficient_application_diversity"
    benchmark["ownership_golden_holdout"]["attempted"] = 14
    benchmark["ownership_golden_holdout"]["passed"] = 14
    benchmark["ownership_golden_holdout"]["annotated_application_family_count"] = 4
    benchmark["ownership_golden_holdout"]["reliability_status"] = (
        "insufficient_sample_size_and_application_diversity"
    )

    report = evaluate_readiness(benchmark, _panel_smoke())

    assert report["status"] == "needs_review"
    assert report["ready"] is False
    assert report["blocked"] is False
    assert {item["gate_id"] for item in report["needs_review_gates"]} >= {
        "application_family_diversity",
        "ownership_holdout_sample_size",
        "ownership_holdout_family_diversity",
    }


def test_showcase_readiness_blocks_invalid_fixture_or_unsafe_boundary() -> None:
    benchmark = _benchmark()
    benchmark["fixture_validity_failures"] = [{"case_id": "stale", "failure_category": "stale_fixture"}]
    benchmark["safety"]["execute_binding_enabled"] = True

    report = evaluate_readiness(benchmark, _panel_smoke())

    assert report["status"] == "blocked"
    assert report["blocked"] is True
    assert {item["gate_id"] for item in report["blocking_gates"]} >= {
        "fixture_validity",
        "no_execute_binding",
    }


def test_showcase_readiness_blocks_missing_actual_panel_evidence() -> None:
    panel = _panel_smoke()
    panel["source"] = "fixture_only"
    panel["mobile"]["screenshot_path"] = ""

    report = evaluate_readiness(_benchmark(), panel)

    assert report["status"] == "blocked"
    assert {item["gate_id"] for item in report["blocking_gates"]} >= {
        "actual_panel_source",
        "panel_mobile_screenshot",
    }
