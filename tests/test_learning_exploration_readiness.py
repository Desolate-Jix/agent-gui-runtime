from pathlib import Path

import scripts.check_learning_exploration_readiness as readiness


def _baseline_report(region_count: int = 1) -> dict:
    return {
        "contract_version": "learning_protected_set_review_check_v1",
        "summary": {"failed": 0},
        "archive_node": {
            "contract_version": "learning_protected_archive_node_v1",
            "checkpoint_id": "baseline",
            "cases": [
                {
                    "case_id": "demo",
                    "source_path": "artifacts/demo.json",
                    "compiled_overlay_path": "artifacts/review-overlays/demo.png",
                    "state_count": 1,
                    "region_count": region_count,
                    "action_template_count": 1,
                    "page_detail_section_count": 1,
                    "passed": True,
                    "model_grounding_status": "not_valid_for_model_grounding_evidence",
                }
            ],
        },
    }


def _protected_report(region_count: int = 1) -> dict:
    report = _baseline_report(region_count)
    report["archive_node"]["checkpoint_id"] = "current"
    return report


def _historical_report(*, invalid_files: int = 0, grounding_cases: int = 0) -> dict:
    return {
        "summary": {
            "invalid_files": invalid_files,
            "model_grounding_evidence_cases": grounding_cases,
            "model_accuracy_claim_allowed": False,
        }
    }


def _structure_report(
    *,
    blocked: int = 0,
    invalid: int = 0,
    stress: int = 1,
    runtime_ready: int = 0,
    near_full_passed: int = 3,
    near_full_required_ratio: float = 0.98,
) -> dict:
    return {
        "summary": {
            "attempted": 3,
            "display_review_candidate": max(0, 3 - blocked - invalid - stress),
            "stress_only_needs_review": stress,
            "blocked_structure_repair": blocked,
            "invalid_cases": invalid,
            "runtime_pathgraph_ready": runtime_ready,
        },
        "cases": [
            {
                "case_id": f"case_{index}",
                "checks": {"stage1_partition_near_full_coverage": index < near_full_passed},
                "structure_metrics": {
                    "stage1_near_full_partition_required_ratio": near_full_required_ratio,
                    "stage1_screen_coverage_ratio": 1.0 if index < near_full_passed else 0.8,
                },
            }
            for index in range(3)
        ],
        "safety_boundary": {
            "runtime_pathgraph_promotion": runtime_ready > 0,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
    }


def _inventory_report(*, allowed: bool = True) -> dict:
    return {
        "candidate_count": 1 if allowed else 0,
        "intake_gate": {
            "allowed": allowed,
            "status": "ready_for_safe_free_exploration" if allowed else "blocked_until_real_observe_capture",
            "blockers": [] if allowed else ["no_usable_non_protected_observe_trace"],
        },
    }


def test_exploration_readiness_passes_when_protected_and_historical_gates_pass(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(readiness, "run_learning_protected_set_review", lambda **_: _protected_report())
    monkeypatch.setattr(readiness, "run_historical_model_evidence_audit", lambda **_: _historical_report())
    monkeypatch.setattr(readiness, "run_learning_structure_quality_check", lambda **_: _structure_report())
    monkeypatch.setattr(readiness, "run_free_exploration_source_inventory", lambda **_: _inventory_report())
    monkeypatch.setattr(readiness, "_read_json", lambda _: _baseline_report())
    monkeypatch.setattr(readiness, "_resolve_project_path", lambda path, root=readiness.ROOT: Path(path))

    report = readiness.run_learning_exploration_readiness_check(
        baseline_path="baseline.json",
        checkpoint_id="test",
        root=tmp_path,
    )

    assert report["ready_for_new_interface_exploration"] is True
    assert report["blockers"] == []
    assert report["summary"]["protected_set_passed"] is True
    assert report["summary"]["historical_model_evidence_boundary_passed"] is True
    assert report["summary"]["structure_quality_boundary_passed"] is True
    assert report["summary"]["structure_quality_stress_only_cases"] == 1
    assert report["summary"]["runtime_pathgraph_promotion_blocked"] is True
    assert report["summary"]["structure_stage1_near_full_partition_required_ratio"] == 0.98
    assert report["summary"]["structure_stage1_near_full_partition_passed"] == 3
    assert report["summary"]["structure_stage1_near_full_partition_attempted"] == 3
    assert report["ready_for_free_exploration_replay"] is True
    assert report["summary"]["free_exploration_intake_allowed"] is True
    assert report["safety_boundary"]["live_clicks"] == 0


def test_exploration_readiness_default_baseline_uses_near_full_partition_checkpoint() -> None:
    assert "stage1_near_full_partition_gate" in readiness.DEFAULT_BASELINE


def test_exploration_readiness_blocks_on_protected_set_drift(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(readiness, "run_learning_protected_set_review", lambda **_: _protected_report(region_count=2))
    monkeypatch.setattr(readiness, "run_historical_model_evidence_audit", lambda **_: _historical_report())
    monkeypatch.setattr(readiness, "run_learning_structure_quality_check", lambda **_: _structure_report())
    monkeypatch.setattr(readiness, "run_free_exploration_source_inventory", lambda **_: _inventory_report())
    monkeypatch.setattr(readiness, "_read_json", lambda _: _baseline_report(region_count=1))
    monkeypatch.setattr(readiness, "_resolve_project_path", lambda path, root=readiness.ROOT: Path(path))

    report = readiness.run_learning_exploration_readiness_check(
        baseline_path="baseline.json",
        checkpoint_id="test",
        root=tmp_path,
    )

    assert report["ready_for_new_interface_exploration"] is False
    assert "protected_set_drift" in report["blockers"]
    assert report["protected_set"]["baseline_comparison"]["status"] == "fail"


def test_exploration_readiness_blocks_on_historical_evidence_boundary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(readiness, "run_learning_protected_set_review", lambda **_: _protected_report())
    monkeypatch.setattr(
        readiness,
        "run_historical_model_evidence_audit",
        lambda **_: _historical_report(grounding_cases=1),
    )
    monkeypatch.setattr(readiness, "run_learning_structure_quality_check", lambda **_: _structure_report())
    monkeypatch.setattr(readiness, "run_free_exploration_source_inventory", lambda **_: _inventory_report())
    monkeypatch.setattr(readiness, "_read_json", lambda _: _baseline_report())
    monkeypatch.setattr(readiness, "_resolve_project_path", lambda path, root=readiness.ROOT: Path(path))

    report = readiness.run_learning_exploration_readiness_check(
        baseline_path="baseline.json",
        checkpoint_id="test",
        root=tmp_path,
    )

    assert report["ready_for_new_interface_exploration"] is False
    assert "historical_model_evidence_boundary_failed" in report["blockers"]
    assert report["summary"]["historical_model_evidence_boundary_passed"] is False


def test_exploration_readiness_blocks_on_structure_repair(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(readiness, "run_learning_protected_set_review", lambda **_: _protected_report())
    monkeypatch.setattr(readiness, "run_historical_model_evidence_audit", lambda **_: _historical_report())
    monkeypatch.setattr(
        readiness,
        "run_learning_structure_quality_check",
        lambda **_: _structure_report(blocked=1, stress=0),
    )
    monkeypatch.setattr(readiness, "run_free_exploration_source_inventory", lambda **_: _inventory_report())
    monkeypatch.setattr(readiness, "_read_json", lambda _: _baseline_report())
    monkeypatch.setattr(readiness, "_resolve_project_path", lambda path, root=readiness.ROOT: Path(path))

    report = readiness.run_learning_exploration_readiness_check(
        baseline_path="baseline.json",
        checkpoint_id="test",
        root=tmp_path,
    )

    assert report["ready_for_new_interface_exploration"] is False
    assert "structure_quality_repair_required" in report["blockers"]
    assert report["summary"]["structure_quality_boundary_passed"] is False


def test_exploration_readiness_reports_free_replay_blocked_separately(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(readiness, "run_learning_protected_set_review", lambda **_: _protected_report())
    monkeypatch.setattr(readiness, "run_historical_model_evidence_audit", lambda **_: _historical_report())
    monkeypatch.setattr(readiness, "run_learning_structure_quality_check", lambda **_: _structure_report())
    monkeypatch.setattr(readiness, "run_free_exploration_source_inventory", lambda **_: _inventory_report(allowed=False))
    monkeypatch.setattr(readiness, "_read_json", lambda _: _baseline_report())
    monkeypatch.setattr(readiness, "_resolve_project_path", lambda path, root=readiness.ROOT: Path(path))

    report = readiness.run_learning_exploration_readiness_check(
        baseline_path="baseline.json",
        checkpoint_id="test",
        root=tmp_path,
    )

    assert report["ready_for_new_interface_exploration"] is True
    assert report["ready_for_free_exploration_replay"] is False
    assert report["summary"]["free_exploration_intake_allowed"] is False
    assert report["free_exploration_replay_blockers"] == ["no_usable_non_protected_observe_trace"]
