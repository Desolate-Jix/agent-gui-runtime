from __future__ import annotations

import json

from scripts.diagnose_general_ui_recognition_regression import _diagnose_ownership, diagnose_reports


def test_region_alias_drift_is_not_misreported_as_missing_capability() -> None:
    result = _diagnose_ownership(
        {
            "failure_category": "ownership_region_missing",
            "region_id": "structure_region_primary_area",
            "item_id": "source_item",
        },
        current_region_roles={"main_content"},
        source_ids={"source_item"},
        baseline_passed=True,
    )

    assert result["diagnosis"] == "benchmark_region_identity_contract_drift"
    assert result["responsibility"] == "benchmark_contract"
    assert result["equivalent_region_present"] is True


def test_source_item_present_but_missing_owner_is_lineage_regression() -> None:
    result = _diagnose_ownership(
        {
            "failure_category": "ownership_item_missing",
            "region_id": "structure_region_top_bar",
            "item_id": "source_item",
        },
        current_region_roles={"top_bar"},
        source_ids={"source_item"},
        baseline_passed=True,
    )

    assert result["diagnosis"] == "stage2_source_item_lineage_loss"
    assert result["responsibility"] == "code_regression"
    assert result["source_item_present"] is True


def test_generated_item_contract_drift_remains_separate_from_source_lineage() -> None:
    result = _diagnose_ownership(
        {
            "failure_category": "ownership_item_missing",
            "region_id": "structure_region_main_content",
            "item_id": "generated_item",
        },
        current_region_roles={"main_content"},
        source_ids=set(),
        baseline_passed=True,
    )

    assert result["diagnosis"] == "generated_candidate_id_contract_drift"
    assert result["responsibility"] == "benchmark_or_generated_contract"


def test_known_limitation_drift_is_not_promoted_to_code_regression(tmp_path) -> None:
    two_stage_path = tmp_path / "two_stage.json"
    trace_path = tmp_path / "trace.json"
    two_stage_path.write_text(
        json.dumps({"stage1_source": "fixture", "stage2_numbering": {"regions": []}}),
        encoding="utf-8",
    )
    trace_path.write_text(json.dumps({"result": {}}), encoding="utf-8")
    current = {
        "cases": [
            {
                "case_id": "known_limit",
                "case_outcome": "known_limitation_drifted",
                "screenshot_sha256": "same",
                "two_stage_report_path": str(two_stage_path),
                "trace_path": str(trace_path),
                "failed_assertions": [
                    {
                        "assertion_id": "hierarchy_expected_status",
                        "category": "hierarchy",
                        "expected": "blocked",
                        "actual": "passed",
                    }
                ],
            }
        ]
    }
    baseline = {
        "cases": [
            {
                "case_id": "known_limit",
                "screenshot_sha256": "same",
                "two_stage_report_path": str(two_stage_path),
                "assertions": [{"assertion_id": "hierarchy_expected_status", "passed": True}],
            }
        ]
    }

    diagnosis = diagnose_reports(current, baseline)

    assert diagnosis["cases"][0]["root_causes"] == ["known_limitation_expectation_drift"]
