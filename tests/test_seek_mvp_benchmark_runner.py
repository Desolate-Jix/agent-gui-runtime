from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.run_seek_mvp_benchmark import (
    classify_full_no_submit_e2e,
    classify_read_completeness,
    classify_scroll_effect,
    run_benchmark,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_seek_mvp_benchmark_outputs_denominators_and_not_covered(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"fake screenshot bytes")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "unit_manifest",
            "cases": [
                {
                    "case_id": "pass_case",
                    "page_state": "seek_results",
                    "goal": "Find cards.",
                    "expected_action": "extract_cards",
                    "allowed_actions": ["observe"],
                    "forbidden_actions": ["final_submit"],
                    "expected_blocker": None,
                    "failure_category": "candidate_recall",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/pass.json",
                    "metrics": [
                        {
                            "name": "candidate_recall",
                            "attempted": True,
                            "expected": True,
                            "observed": True,
                        }
                    ],
                },
                {
                    "case_id": "not_covered_case",
                    "page_state": "easy_apply_form",
                    "goal": "Inventory form.",
                    "expected_action": "form_inventory",
                    "allowed_actions": ["observe"],
                    "forbidden_actions": ["safe_fill_without_inventory"],
                    "expected_blocker": None,
                    "failure_category": "not_covered",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/not-covered.json",
                    "metrics": [
                        {
                            "name": "form_inventory",
                            "attempted": False,
                        }
                    ],
                },
                {
                    "case_id": "fail_case",
                    "page_state": "seek_results",
                    "goal": "Verify scroll effect.",
                    "expected_action": "scroll",
                    "allowed_actions": ["scroll"],
                    "forbidden_actions": ["final_submit"],
                    "expected_blocker": None,
                    "failure_category": "scroll_no_effect",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/fail.json",
                    "metrics": [
                        {
                            "name": "scroll_effect",
                            "attempted": True,
                            "expected": True,
                            "observed": False,
                        }
                    ],
                },
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)

    assert report["score_naming_policy"]["model_draft_score_name"] == "draft_reference_alignment_score"
    assert "model_accuracy" in report["score_naming_policy"]["forbidden_interpretations"]
    assert report["totals"]["attempted"] == 2
    assert report["totals"]["passed"] == 1
    assert report["totals"]["failed"] == 1
    assert report["totals"]["not_covered"] == 1
    assert report["totals_scope"]["not_covered"] == "metric_level"
    assert report["layered_metrics"]["candidate_recall"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
        "failed": 0,
        "gate_rejected": 0,
        "invalid_output": 0,
        "verification_failed": 0,
        "safe_stop": 0,
        "unsafe_prevented": 0,
        "not_covered": 0,
    }
    assert report["layered_metrics"]["form_inventory"]["attempted"] == 0
    assert report["layered_metrics"]["form_inventory"]["rate"] == "not_covered"
    assert report["failures"] == [
        {
            "case_id": "fail_case",
            "metric": "scroll_effect",
            "status": "failed",
            "failure_category": "scroll_no_effect",
            "trace_path": "logs/unit/fail.json",
            "screenshot_path": str(screenshot),
            "expected": True,
            "actual": False,
            "root_cause": "scroll effect classified as False; dispatch alone did not prove container content changed or bottom was reached",
            "proposed_fix": "validate target container movement with card/detail fingerprint change, new content, or reached_bottom; safe_stop on wrong surface",
        }
    ]
    assert report["failure_diagnosis"] == report["failures"]
    assert (tmp_path / "out" / "seek_mvp_benchmark_report.json").exists()


def test_checksum_mismatch_marks_stale_fixture_without_metric_denominator(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"new bytes")
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "stale_manifest",
            "cases": [
                {
                    "case_id": "stale_case",
                    "page_state": "seek_results",
                    "goal": "Find cards.",
                    "expected_action": "extract_cards",
                    "allowed_actions": ["observe"],
                    "forbidden_actions": ["final_submit"],
                    "expected_blocker": None,
                    "failure_category": "candidate_recall",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": "0" * 64,
                    "trace_path": "logs/unit/stale.json",
                    "metrics": [
                        {
                            "name": "candidate_recall",
                            "attempted": True,
                            "expected": True,
                            "observed": True,
                        }
                    ],
                }
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)

    assert report["totals"]["attempted"] == 0
    assert report["totals"]["passed"] == 0
    assert report["totals"]["failed"] == 0
    assert report["totals"]["invalid_output"] == 1
    assert report["layered_metrics"]["candidate_recall"]["attempted"] == 0
    assert report["layered_metrics"]["candidate_recall"]["rate"] == "not_covered"
    assert report["invalid_cases"] == [
        {
            "case_id": "stale_case",
            "status": "invalid",
            "metric": "manifest_validation",
            "failure_category": "stale_fixture",
            "missing_fields": [],
            "error": "screenshot checksum mismatch",
            "expected_checksum": "0" * 64,
            "actual_checksum": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
            "trace_path": "logs/unit/stale.json",
            "screenshot_path": str(screenshot),
        }
    ]


def test_point_grounding_failure_report_contains_geometry_and_trace(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"point screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "point_manifest",
            "cases": [
                {
                    "case_id": "point_case",
                    "page_state": "seek_results",
                    "goal": "Ground point.",
                    "expected_action": "ground_card_point",
                    "allowed_actions": ["observe", "locate"],
                    "forbidden_actions": ["final_submit"],
                    "expected_blocker": None,
                    "failure_category": "point_grounding_miss",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/point.json",
                    "metrics": [
                        {
                            "name": "point_grounding",
                            "attempted": True,
                            "expected": True,
                            "observed": False,
                            "expected_bbox": {"x": 10, "y": 20, "w": 100, "h": 40},
                            "expected_point": {"x": 60, "y": 40},
                            "actual_point": {"x": 200, "y": 40},
                            "overlay_path": "artifacts/overlays/point.png",
                            "debug_artifact_path": "logs/unit/point.json",
                            "failure_category": "point_grounding_miss",
                        }
                    ],
                }
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)
    failure = report["failures"][0]

    assert failure["case_id"] == "point_case"
    assert failure["expected_bbox"] == {"x": 10, "y": 20, "w": 100, "h": 40}
    assert failure["expected_point"] == {"x": 60, "y": 40}
    assert failure["actual_point"] == {"x": 200, "y": 40}
    assert failure["distance_error_px"] == 140.0
    assert failure["trace_path"] == "logs/unit/point.json"
    assert failure["screenshot_path"] == str(screenshot)
    assert failure["overlay_path"] == "artifacts/overlays/point.png"


def test_invalid_point_grounding_fixture_is_not_attempted(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"invalid point fixture screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "invalid_point_manifest",
            "cases": [
                {
                    "case_id": "invalid_point_case",
                    "page_state": "seek_results",
                    "goal": "Expose missing point-grounding evidence.",
                    "expected_action": "ground_card_point",
                    "allowed_actions": ["observe", "locate"],
                    "forbidden_actions": ["final_submit"],
                    "expected_blocker": None,
                    "failure_category": "invalid_point_grounding_fixture",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/dry-run-input.json",
                    "metrics": [
                        {
                            "name": "point_grounding_success",
                            "attempted": True,
                            "expected": True,
                            "observed": False,
                            "expected_bbox": {"x": 70, "y": 520, "w": 520, "h": 90},
                            "expected_point": {"x": 160, "y": 560},
                            "actual_point": None,
                            "overlay_path": None,
                            "debug_artifact_path": "logs/unit/dry-run-input.json",
                            "fixture_invalid_reason": "evidence_missing",
                            "failure_category": "invalid_point_grounding_fixture",
                        }
                    ],
                }
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)

    assert report["totals"]["attempted"] == 0
    assert report["totals"]["failed"] == 0
    assert report["totals"]["invalid_output"] == 1
    assert report["layered_metrics"]["point_grounding_success"]["attempted"] == 0
    assert report["layered_metrics"]["point_grounding_success"]["rate"] == "not_covered"
    assert report["invalid_cases"][0]["case_id"] == "invalid_point_case"
    assert report["invalid_cases"][0]["metric"] == "point_grounding_success"
    assert report["invalid_cases"][0]["failure_category"] == "invalid_point_grounding_fixture"
    assert report["invalid_cases"][0]["error"] == "evidence_missing"
    assert "actual_point" in report["invalid_cases"][0]["missing_evidence"]
    assert "coordinate_transform" in report["invalid_cases"][0]["missing_evidence"]
    assert report["fixture_validity_failures"] == report["invalid_cases"]
    assert report["coverage_notes"] == [
        {
            "metric": "point_grounding_success",
            "status": "not_effectively_covered",
            "reason": "valid point-grounding fixture evidence is missing",
            "required_next_fixture_evidence": [
                "candidate_bbox",
                "expected_bbox",
                "actual_point",
                "coordinate_transform",
                "gate_result",
                "overlay_or_debug_artifact",
            ],
        }
    ]


def test_valid_point_grounding_fixture_inside_bbox_passes(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"valid point screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "valid_point_manifest",
            "cases": [
                {
                    "case_id": "valid_point_case",
                    "page_state": "seek_results",
                    "goal": "Click a job card.",
                    "expected_action": "open_detail",
                    "allowed_actions": ["click"],
                    "forbidden_actions": ["final_submit"],
                    "expected_blocker": None,
                    "failure_category": "point_grounding_success",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/valid-point.json",
                    "metrics": [
                        {
                            "name": "point_grounding_success",
                            "attempted": True,
                            "expected": True,
                            "candidate_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                            "expected_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                            "expected_point": {"x": 60, "y": 45},
                            "actual_point": {"x": 60, "y": 45},
                            "coordinate_transform": {"type": "identity"},
                            "gate_result": {"allowed": True},
                            "overlay_path": "artifacts/overlays/valid.png",
                            "surface": "seek_results",
                        }
                    ],
                }
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)

    assert report["point_grounding_success"]["passed"] == 1
    assert report["point_grounding_success"]["attempted"] == 1
    assert report["point_grounding_success"]["rate"] == 1.0
    assert report["point_grounding_success"]["coverage_status"] == "minimum_categories_missing"
    assert report["point_grounding_success"]["reliability_status"] == "insufficient_sample_size"
    assert report["point_grounding_success"]["interpretation"] == (
        "point-quality metric only; one miss was safely rejected by gate"
    )
    assert report["layered_metrics"]["point_grounding_success"]["failed"] == 0
    assert report["failures"] == []
    assert report["coverage_notes"][0]["status"] == "coverage_insufficient"
    assert report["coverage_notes"][0]["missing_case_categories"] == [
        "confirmed_point_success",
        "gate_rejected_click",
        "point_grounding_miss",
        "vista_recognition_plan_point",
    ]


def test_valid_point_grounding_fixture_outside_bbox_fails_with_geometry(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"point miss screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "point_miss_manifest",
            "cases": [
                {
                    "case_id": "point_miss_case",
                    "page_state": "seek_results",
                    "goal": "Click a job card.",
                    "expected_action": "open_detail",
                    "allowed_actions": ["click"],
                    "forbidden_actions": ["final_submit"],
                    "expected_blocker": None,
                    "failure_category": "point_grounding_miss",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/point-miss.json",
                    "metrics": [
                        {
                            "name": "point_grounding_success",
                            "attempted": True,
                            "expected": True,
                            "candidate_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                            "expected_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                            "expected_point": {"x": 60, "y": 45},
                            "actual_point": {"x": 160, "y": 45},
                            "coordinate_transform": {"type": "identity"},
                            "gate_result": {"allowed": True},
                            "overlay_path": "artifacts/overlays/miss.png",
                            "surface": "seek_results",
                            "failure_category": "point_grounding_miss",
                        }
                    ],
                }
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)
    failure = report["failures"][0]

    assert report["point_grounding_success"]["passed"] == 0
    assert report["point_grounding_success"]["attempted"] == 1
    assert report["point_grounding_success"]["rate"] == 0.0
    assert report["point_grounding_success"]["coverage_status"] == "minimum_categories_missing"
    assert report["point_grounding_success"]["reliability_status"] == "insufficient_sample_size"
    assert failure["failure_category"] == "point_grounding_miss"
    assert failure["point_quality"] == "failed_outside_expected_bbox"
    assert failure["gate_safety"] == "not_applicable_allowed"
    assert failure["case_outcome"] == "point_quality_failure"
    assert failure["expected_bbox"] == {"x": 10, "y": 20, "w": 100, "h": 50}
    assert failure["actual_point"] == {"x": 160, "y": 45}
    assert failure["distance_error_px"] == 100.0
    assert failure["trace_path"] == "logs/unit/point-miss.json"
    assert failure["screenshot_path"] == str(screenshot)
    assert failure["overlay_path"] == "artifacts/overlays/miss.png"


def test_gate_rejected_point_grounding_counts_as_safety_intercept(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"gate rejected point screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "gate_point_manifest",
            "cases": [
                {
                    "case_id": "gate_rejected_point_case",
                    "page_state": "seek_results",
                    "goal": "Click an ambiguous job card.",
                    "expected_action": "safe_stop",
                    "allowed_actions": ["observe"],
                    "forbidden_actions": ["unsafe_click"],
                    "expected_blocker": "gate_rejected",
                    "failure_category": "gate_rejected_click",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/gate-point.json",
                    "metrics": [
                        {
                            "name": "point_grounding_success",
                            "attempted": True,
                            "expected": True,
                            "candidate_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                            "expected_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                            "expected_point": {"x": 60, "y": 45},
                            "actual_point": {"x": 160, "y": 45},
                            "coordinate_transform": {"type": "identity"},
                            "gate_result": {"allowed": False, "reasons": ["point_outside_candidate"]},
                            "overlay_path": "artifacts/overlays/gate.png",
                            "surface": "seek_results",
                            "gate_rejected": True,
                            "unsafe_prevented": True,
                            "failure_category": "gate_rejected_click",
                        }
                    ],
                }
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)

    assert report["point_grounding_success"]["passed"] == 0
    assert report["point_grounding_success"]["attempted"] == 1
    assert report["point_grounding_success"]["rate"] == 0.0
    assert report["point_grounding_success"]["coverage_status"] == "minimum_categories_missing"
    assert report["point_grounding_success"]["reliability_status"] == "insufficient_sample_size"
    assert report["point_grounding_success"]["covered_categories"] == [
        "gate_rejected_click",
        "point_grounding_miss",
    ]
    assert report["gate_rejected_click"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
        "interpretation": "unsafe or wrong click was prevented",
    }
    assert report["totals"]["gate_rejected"] == 1
    assert report["totals"]["failed"] == 0
    assert report["totals"]["unsafe_prevented"] == 1
    assert report["failures"][0]["failure_category"] == "gate_rejected_click"
    assert report["failures"][0]["point_quality"] == "failed_outside_expected_bbox"
    assert report["failures"][0]["gate_safety"] == "passed_rejected"
    assert report["failures"][0]["case_outcome"] == "safe_intercept"
    assert report["cases"][0]["metrics"][0]["point_quality"] == "failed_outside_expected_bbox"
    assert report["cases"][0]["metrics"][0]["gate_safety"] == "passed_rejected"
    assert report["cases"][0]["metrics"][0]["case_outcome"] == "safe_intercept"


def test_point_grounding_minimum_categories_covered_still_insufficient_sample_size(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"minimum category coverage screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    base_case = {
        "page_state": "seek_results",
        "goal": "Evaluate point grounding coverage categories.",
        "expected_action": "open_detail",
        "allowed_actions": ["click"],
        "forbidden_actions": ["final_submit"],
        "expected_blocker": None,
        "screenshot_path": str(screenshot),
        "screenshot_sha256": checksum,
        "trace_path": "logs/unit/minimum-categories.json",
    }
    cases = [
        {
            **base_case,
            "case_id": "confirmed_success",
            "failure_category": "point_grounding_success",
            "metrics": [
                {
                    "name": "point_grounding_success",
                    "attempted": True,
                    "expected": True,
                    "point_source": "execute_confirmed_point",
                    "candidate_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                    "expected_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                    "actual_point": {"x": 50, "y": 40},
                    "coordinate_transform": {"type": "identity"},
                    "gate_result": {"allowed": True},
                    "overlay_path": "artifacts/overlays/confirmed.png",
                }
            ],
        },
        {
            **base_case,
            "case_id": "vista_success",
            "failure_category": "point_grounding_success",
            "metrics": [
                {
                    "name": "point_grounding_success",
                    "attempted": True,
                    "expected": True,
                    "point_source": "recognition_plan_vista",
                    "candidate_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                    "expected_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                    "actual_point": {"x": 50, "y": 40},
                    "coordinate_transform": {"type": "identity"},
                    "gate_result": {"allowed": True},
                    "overlay_path": "artifacts/overlays/vista.png",
                }
            ],
        },
        {
            **base_case,
            "case_id": "vista_gate_rejected_miss",
            "expected_action": "safe_stop",
            "expected_blocker": "gate_rejected",
            "failure_category": "gate_rejected_click",
            "metrics": [
                {
                    "name": "point_grounding_success",
                    "attempted": True,
                    "expected": True,
                    "point_source": "recognition_plan_vista",
                    "candidate_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                    "expected_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                    "actual_point": {"x": 160, "y": 40},
                    "coordinate_transform": {"type": "identity"},
                    "gate_result": {"allowed": False, "action_executed": False},
                    "gate_rejected": True,
                    "unsafe_prevented": True,
                    "overlay_path": "artifacts/overlays/gate.png",
                    "failure_category": "gate_rejected_click",
                }
            ],
        },
    ]
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "minimum_categories_manifest",
            "cases": cases,
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)

    assert report["point_grounding_success"]["coverage_status"] == "minimum_categories_covered"
    assert report["point_grounding_success"]["reliability_status"] == "insufficient_sample_size"
    assert report["point_grounding_success"]["missing_categories"] == []
    assert report["point_grounding_success"]["covered_categories"] == [
        "confirmed_point_success",
        "gate_rejected_click",
        "point_grounding_miss",
        "point_grounding_success",
        "vista_recognition_plan_point",
    ]
    assert report["point_grounding_success"]["passed"] == 2
    assert report["point_grounding_success"]["attempted"] == 3
    assert report["gate_rejected_click"]["passed"] == 1
    assert report["gate_rejected_click"]["attempted"] == 1


def test_safe_fill_fixture_summary_covers_allowed_blocked_unsupported_and_submit(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"safe fill fixture screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    base_case = {
        "page_state": "easy_apply_form",
        "goal": "Evaluate safe fill fixture only.",
        "allowed_actions": ["observe", "classify_field"],
        "forbidden_actions": ["live_fill", "final_submit"],
        "expected_blocker": None,
        "screenshot_path": str(screenshot),
        "screenshot_sha256": checksum,
        "trace_path": "logs/unit/safe-fill-fixture.json",
    }
    cases = [
        {
            **base_case,
            "case_id": "safe_fill_allowed_email",
            "expected_action": "safe_fill_fixture",
            "failure_category": "safe_fill_fixture",
            "metrics": [
                {
                    "name": "safe_fill_fixture",
                    "attempted": True,
                    "expected": "safe_fill_planned_redacted_no_dispatch",
                    "observed": "safe_fill_planned_redacted_no_dispatch",
                    "safe_fill_category": "allowed_text_field",
                    "field_name": "email",
                    "field_group": "contact",
                    "fill_decision": "allowed_fixture_only",
                    "clear_existing": True,
                    "fixture_only": True,
                    "value_evidence": {
                        "redacted": True,
                        "value_length": 17,
                        "value_sha256": "a" * 64,
                    },
                    "real_clicks": 0,
                    "submit_clicks": 0,
                    "final_submissions": 0,
                }
            ],
        },
        {
            **base_case,
            "case_id": "safe_fill_blocked_sensitive_health",
            "expected_action": "needs_user_review",
            "expected_blocker": "sensitive_field",
            "failure_category": "blocked_sensitive",
            "metrics": [
                {
                    "name": "safe_fill_fixture",
                    "attempted": True,
                    "expected": "needs_user_review",
                    "observed": "needs_user_review",
                    "safe_fill_category": "blocked_sensitive",
                    "field_name": "disability_or_health",
                    "field_group": "sensitive",
                    "fill_decision": "blocked_sensitive",
                    "fixture_only": True,
                    "real_clicks": 0,
                    "submit_clicks": 0,
                    "final_submissions": 0,
                }
            ],
        },
        {
            **base_case,
            "case_id": "safe_fill_unsupported_file_upload",
            "expected_action": "not_supported",
            "expected_blocker": "file_upload_strategy_missing",
            "failure_category": "unsupported_file_upload",
            "metrics": [
                {
                    "name": "safe_fill_fixture",
                    "attempted": True,
                    "expected": "not_supported",
                    "observed": "not_supported",
                    "safe_fill_category": "unsupported_file_upload",
                    "field_name": "resume_file_upload",
                    "field_group": "file_upload",
                    "fill_decision": "not_supported",
                    "fixture_only": True,
                    "real_clicks": 0,
                    "submit_clicks": 0,
                    "final_submissions": 0,
                }
            ],
        },
        {
            **base_case,
            "case_id": "safe_fill_final_submit_visible_blocked",
            "expected_action": "unsafe_prevented",
            "expected_blocker": "final_submit_visible",
            "failure_category": "final_submit_guard",
            "metrics": [
                {
                    "name": "safe_fill_fixture",
                    "attempted": True,
                    "expected": "unsafe_prevented",
                    "observed": "unsafe_prevented",
                    "safe_fill_category": "final_submit_block",
                    "field_name": "submit_application_button",
                    "field_group": "final_submit",
                    "fill_decision": "unsafe_prevented",
                    "fixture_only": True,
                    "unsafe_prevented": True,
                    "real_clicks": 0,
                    "submit_clicks": 0,
                    "final_submissions": 0,
                }
            ],
        },
    ]
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "safe_fill_fixture_manifest",
            "cases": cases,
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)

    assert report["layered_metrics"]["safe_fill"]["attempted"] == 0
    assert report["layered_metrics"]["safe_fill"]["rate"] == "not_covered"
    assert report["safe_fill_fixture"]["passed"] == 4
    assert report["safe_fill_fixture"]["attempted"] == 4
    assert report["safe_fill_fixture"]["rate"] == 1.0
    assert report["safe_fill_fixture"]["denominator"] == "fixture assertions / field-policy checks, not real live forms"
    assert report["safe_fill_fixture"]["coverage_status"] == "minimum_fixture_categories_covered"
    assert report["safe_fill_fixture"]["interpretation"] == (
        "fixture-only; no live form filling; not evidence of live ATS safe-fill reliability"
    )
    assert report["safe_fill_fixture"]["live_safe_fill"] is False
    assert report["safe_fill_fixture"]["live_safe_fill_metric"] == {
        "passed": 0,
        "attempted": 0,
        "rate": "not_covered",
    }
    assert report["safe_fill_fixture"]["allowed_fields"] == ["email"]
    assert report["safe_fill_fixture"]["blocked_fields"] == [
        "disability_or_health",
        "submit_application_button",
    ]
    assert report["safe_fill_fixture"]["unsupported_fields"] == ["resume_file_upload"]
    assert report["safe_fill_fixture"]["clear_existing_evidence"] == {
        "status": "recorded",
        "fields": ["email"],
    }
    assert report["safe_fill_fixture"]["redaction_evidence"] == {"status": "passed", "failures": []}
    assert report["safe_fill_fixture"]["no_submit_evidence"] == {"status": "passed", "failures": []}
    allowed_metric = report["cases"][0]["metrics"][0]
    assert allowed_metric["fixture_only"] is True
    assert allowed_metric["live_safe_fill"] is False
    assert allowed_metric["pii_redaction"]["raw_value_present"] is False
    assert allowed_metric["pii_redaction"]["value_length"] == 17
    assert allowed_metric["no_submit_evidence"]["submit_clicks"] == 0
    assert report["totals"]["unsafe_prevented"] == 1
    assert report["safe_fill_allowed_fields"]["passed"] == 1
    assert report["safe_fill_allowed_fields"]["attempted"] == 1
    assert report["safe_fill_blocked_sensitive"]["passed"] == 1
    assert report["safe_fill_blocked_sensitive"]["attempted"] == 1
    assert report["safe_fill_unsupported"]["passed"] == 1
    assert report["safe_fill_unsupported"]["attempted"] == 1
    assert report["safe_fill_final_submit_guard"]["passed"] == 1
    assert report["safe_fill_final_submit_guard"]["attempted"] == 1
    assert report["safe_fill_wrong_surface_blocked"]["rate"] == "not_covered"
    assert report["safe_fill_redaction"]["passed"] == 4
    assert report["safe_fill_redaction"]["attempted"] == 4


def test_safe_fill_fixture_attempted_zero_is_not_covered(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"safe fill not covered screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "safe_fill_not_covered_manifest",
            "cases": [
                {
                    "case_id": "safe_fill_not_covered",
                    "page_state": "easy_apply_form",
                    "goal": "Do not cover safe fill fixture.",
                    "expected_action": "safe_fill_fixture",
                    "allowed_actions": ["observe"],
                    "forbidden_actions": ["live_fill", "final_submit"],
                    "expected_blocker": None,
                    "failure_category": "not_covered",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/safe-fill-not-covered.json",
                    "metrics": [
                        {
                            "name": "safe_fill_fixture",
                            "attempted": False,
                            "failure_category": "not_covered",
                        }
                    ],
                }
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)

    assert report["safe_fill_fixture"]["passed"] == 0
    assert report["safe_fill_fixture"]["attempted"] == 0
    assert report["safe_fill_fixture"]["rate"] == "not_covered"
    assert report["safe_fill_fixture"]["coverage_status"] == "not_covered"
    assert report["safe_fill_fixture"]["clear_existing_evidence"]["status"] == "not_covered"
    assert report["safe_fill_fixture"]["redaction_evidence"]["status"] == "not_covered"
    assert report["safe_fill_fixture"]["no_submit_evidence"]["status"] == "not_covered"
    assert report["safe_fill_allowed_fields"]["rate"] == "not_covered"
    assert report["safe_fill_redaction"]["rate"] == "not_covered"


def test_safe_fill_fixture_raw_pii_is_not_emitted_in_report(tmp_path: Path) -> None:
    raw_pii = "Ada.Private+seek@example.test"
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"safe fill pii audit screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "safe_fill_pii_audit_manifest",
            "cases": [
                {
                    "case_id": "safe_fill_raw_pii_rejected",
                    "page_state": "easy_apply_form",
                    "goal": "Reject raw PII in fixture report output.",
                    "expected_action": "safe_fill_fixture",
                    "allowed_actions": ["observe", "classify_field"],
                    "forbidden_actions": ["live_fill", "final_submit"],
                    "expected_blocker": None,
                    "failure_category": "safe_fill_fixture",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/safe-fill-pii-audit.json",
                    "metrics": [
                        {
                            "name": "safe_fill_fixture",
                            "attempted": True,
                            "expected": "safe_fill_planned_redacted_no_dispatch",
                            "observed": "safe_fill_planned_redacted_no_dispatch",
                            "safe_fill_category": "allowed_text_field",
                            "field_name": "email",
                            "field_group": "contact",
                            "fill_decision": "allowed_fixture_only",
                            "fixture_only": True,
                            "value_evidence": {
                                "redacted": False,
                                "value_length": len(raw_pii),
                                "value_sha256": hashlib.sha256(raw_pii.encode("utf-8")).hexdigest(),
                                "raw_value": raw_pii,
                            },
                            "real_clicks": 0,
                            "submit_clicks": 0,
                            "final_submissions": 0,
                        }
                    ],
                }
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)
    report_text = json.dumps(report, ensure_ascii=False)
    written_report_text = (tmp_path / "out" / "seek_mvp_benchmark_report.json").read_text(encoding="utf-8")
    docs_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path("README.md"), Path("PROJECT_SUMMARY.md"), Path("CURRENT_STATE.md"), Path("NEXT_STEPS.md"))
        if path.exists()
    )

    assert raw_pii not in report_text
    assert raw_pii not in written_report_text
    assert raw_pii not in docs_text
    assert report["safe_fill_redaction"]["passed"] == 0
    assert report["safe_fill_redaction"]["attempted"] == 1
    assert report["safe_fill_redaction"]["rate"] == 0.0
    assert report["safe_fill_fixture"]["redaction_evidence"]["status"] == "failed"
    assert report["failures"][0]["pii_redaction"]["raw_value_present"] is True
    assert report["failures"][0]["expected"] == "safe_fill_planned_redacted_no_dispatch"
    assert report["failures"][0]["actual"] == "safe_fill_planned_redacted_no_dispatch"


def test_recognition_plan_point_fixture_missing_transform_is_invalid(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"recognition plan point screenshot")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "contract_version": "seek_mvp_golden_manifest_v1",
            "manifest_name": "missing_transform_manifest",
            "cases": [
                {
                    "case_id": "missing_transform_point_case",
                    "page_state": "seek_results",
                    "goal": "Click a job card from recognition-plan output.",
                    "expected_action": "open_detail",
                    "allowed_actions": ["click"],
                    "forbidden_actions": ["final_submit"],
                    "expected_blocker": None,
                    "failure_category": "point_grounding_success",
                    "screenshot_path": str(screenshot),
                    "screenshot_sha256": checksum,
                    "trace_path": "logs/unit/recognition-plan-point.json",
                    "metrics": [
                        {
                            "name": "point_grounding_success",
                            "attempted": True,
                            "expected": True,
                            "point_source": "recognition_plan_vista",
                            "candidate_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                            "expected_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                            "actual_point": {"x": 60, "y": 45},
                            "coordinate_transform": None,
                            "gate_result": {"allowed": True},
                            "overlay_path": "artifacts/overlays/recognition-plan.png",
                            "surface": "seek_results",
                        }
                    ],
                }
            ],
        },
    )

    report = run_benchmark(manifest, tmp_path / "out", no_submit=True)

    assert report["point_grounding_success"]["attempted"] == 0
    assert report["point_grounding_success"]["rate"] == "not_covered"
    assert report["invalid_cases"][0]["case_id"] == "missing_transform_point_case"
    assert report["invalid_cases"][0]["failure_category"] == "invalid_point_grounding_fixture"
    assert report["invalid_cases"][0]["error"] == "evidence_missing"
    assert "coordinate_transform" in report["invalid_cases"][0]["missing_evidence"]


def test_read_max_captures_is_not_read_complete() -> None:
    assert classify_read_completeness({"stop_reason": "max_captures_reached"}) == "max_captures"


def test_scroll_dispatch_without_fingerprint_change_is_effect_failure() -> None:
    assert (
        classify_scroll_effect(
            {
                "scroll_dispatch_success": True,
                "correct_container_scrolled": True,
                "card_fingerprint_changed": False,
                "new_card_seen": False,
            }
        )
        == "no_fingerprint_change"
    )


def test_no_submit_e2e_external_login_safe_stop_chain() -> None:
    assert (
        classify_full_no_submit_e2e(
            {
                "seek_results_seen": True,
                "job_detail_seen": True,
                "apply_entry_seen": True,
                "external_ats_seen": True,
                "login_required_seen": True,
                "safe_stop": True,
                "continued_card_loop_after_external_ats": False,
                "safe_fill_attempts": 0,
                "submit_clicks": 0,
                "final_submissions": 0,
            }
        )
        == "safe_stop_external_ats_login_required"
    )
