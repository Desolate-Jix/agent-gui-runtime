from __future__ import annotations

import pytest

from scripts.aggregate_learning_practical_acceptance import (
    aggregate_acceptance_reports,
    collect_batch_report_paths,
    main,
)


def _completed_report(case_id: str, *, three_image: bool = True, chain_success: bool = True) -> dict:
    return {
        "contract_version": "learning_interface_chain_smoke_report_v2",
        "status": "completed_batch",
        "completed_case_ids": [case_id],
        "pending_case_ids": [],
        "safety": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
        },
        "cases": [
            {
                "case_id": case_id,
                "case_report_path": f"logs/{case_id}.json",
                "chain_success": chain_success,
                "chain_completion": {
                    "success": chain_success,
                    "failed_requirements": [] if chain_success else ["three_image_audit"],
                },
                "three_image_audit": {
                    "complete": three_image,
                    "source": {"path": f"artifacts/{case_id}_source.png"},
                    "stage1": {"path": f"artifacts/{case_id}_stage1.png"},
                    "final": {"path": f"artifacts/{case_id}_final.png"},
                },
                "class_expectation_audit": {"status": "passed", "issues": []},
                "quality": {"status": "review_only_chain_ready"},
            }
        ],
    }


def test_collect_batch_report_paths_appends_new_batch_to_prior_aggregate(tmp_path) -> None:
    first_batch = tmp_path / "batch_0.json"
    second_batch = tmp_path / "batch_1.json"
    first_batch.write_text("{}\n", encoding="utf-8")
    second_batch.write_text("{}\n", encoding="utf-8")
    prior_aggregate = tmp_path / "aggregate.json"
    prior_aggregate.write_text(
        __import__("json").dumps(
            {
                "contract_version": "learning_practical_acceptance_aggregate_v1",
                "batch_report_paths": [str(first_batch), str(second_batch)],
            }
        ),
        encoding="utf-8",
    )

    collected = collect_batch_report_paths(
        batch_report_paths=[second_batch],
        resume_aggregate_paths=[prior_aggregate],
    )

    assert collected == [first_batch.resolve(), second_batch.resolve()]


def test_cli_accepts_resume_aggregate_and_new_batch(tmp_path, monkeypatch) -> None:
    prior_aggregate = tmp_path / "prior_aggregate.json"
    new_batch = tmp_path / "new_batch.json"
    out_dir = tmp_path / "out"
    captured = {}

    def fake_build_acceptance_aggregate(**kwargs):
        captured.update(kwargs)
        return {
            "collection_status": "pending_cases",
            "quality_status": "not_covered",
            "report_path": str(out_dir / "report.json"),
        }

    monkeypatch.setattr(
        "scripts.aggregate_learning_practical_acceptance.build_acceptance_aggregate",
        fake_build_acceptance_aggregate,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "aggregate_learning_practical_acceptance.py",
            "--resume-aggregate",
            str(prior_aggregate),
            "--batch-report",
            str(new_batch),
            "--out",
            str(out_dir),
        ],
    )

    exit_code = main()

    assert exit_code == 2
    assert captured["resume_aggregate_paths"] == [prior_aggregate]
    assert captured["batch_report_paths"] == [new_batch]


def test_aggregate_acceptance_reports_keeps_unrun_cases_pending() -> None:
    completed = _completed_report("case_a")
    resource_blocked = {
        "contract_version": "learning_interface_chain_smoke_report_v2",
        "status": "resource_blocked",
        "completed_case_ids": [],
        "pending_case_ids": ["case_b"],
        "model_calls_attempted": 0,
        "cases": [],
        "safety": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
        },
    }

    aggregate = aggregate_acceptance_reports(
        [completed, resource_blocked],
        expected_case_ids=["case_a", "case_b"],
    )

    assert aggregate["collection_status"] == "pending_cases"
    assert aggregate["completed_case_ids"] == ["case_a"]
    assert aggregate["pending_case_ids"] == ["case_b"]
    assert aggregate["metrics"]["three_image_audit"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
        "interpretation": "three-image evidence completeness only; not recognition accuracy",
    }
    assert aggregate["safety"]["live_clicks"] == 0


def test_aggregate_acceptance_reports_rejects_duplicate_completed_case() -> None:
    with pytest.raises(ValueError, match="duplicate completed case ids: case_a"):
        aggregate_acceptance_reports(
            [_completed_report("case_a"), _completed_report("case_a")],
            expected_case_ids=["case_a"],
        )


def test_aggregate_acceptance_reports_separates_collection_from_quality() -> None:
    aggregate = aggregate_acceptance_reports(
        [_completed_report("case_a", three_image=False, chain_success=False)],
        expected_case_ids=["case_a"],
    )

    assert aggregate["collection_status"] == "collection_complete"
    assert aggregate["quality_status"] == "needs_review"
    assert aggregate["metrics"]["three_image_audit"]["passed"] == 0
    assert aggregate["metrics"]["chain_completion"]["passed"] == 0
    assert aggregate["failure_cases"][0]["case_id"] == "case_a"
    assert "three_image_audit" in aggregate["failure_cases"][0]["failed_requirements"]


def test_failure_case_preserves_current_three_image_evidence_paths() -> None:
    report = _completed_report("case_a", chain_success=False)
    report["cases"][0]["source_trace_path"] = "logs/traces/case_a_observe.json"
    audit = report["cases"][0]["three_image_audit"]
    audit.pop("stage1")
    audit.pop("final")
    audit["stage1_bar_localization"] = {"path": "artifacts/case_a_stage1_current.png"}
    audit["final_fused_overlay"] = {"path": "artifacts/case_a_final_current.png"}

    aggregate = aggregate_acceptance_reports([report], expected_case_ids=["case_a"])

    failure = aggregate["failure_cases"][0]
    assert failure["stage1_image_path"] == "artifacts/case_a_stage1_current.png"
    assert failure["final_image_path"] == "artifacts/case_a_final_current.png"
    assert failure["trace_path"] == "logs/traces/case_a_observe.json"
    assert failure["failure_category"] == "chain_completion_needs_review"


def test_failure_case_prioritizes_class_expectation_category() -> None:
    report = _completed_report("case_a", chain_success=False)
    report["cases"][0]["class_expectation_audit"] = {
        "status": "needs_review",
        "issues": ["insufficient_required_role:table_row"],
    }

    aggregate = aggregate_acceptance_reports([report], expected_case_ids=["case_a"])

    assert aggregate["failure_cases"][0]["failure_category"] == "class_expectation_needs_review"
