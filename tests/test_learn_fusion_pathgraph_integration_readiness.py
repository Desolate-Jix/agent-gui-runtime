from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.report_learn_fusion_pathgraph_integration_readiness import (
    report_learn_fusion_pathgraph_integration_readiness,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _reviewed_candidate(path: Path) -> Path:
    return _write_json(
        path,
        {
            "contract_version": "reviewed_template_candidate_v1",
            "draft": {
                "contract_version": "learning_template_draft_v1",
                "screen_summary": "SEEK results with calibrated actions.",
                "state_guess": "seek_results",
                "states": [{"state_id": "seek_results", "label": "SEEK results"}],
                "regions": [{"region_id": "job_card_1", "label": "Job card", "bbox": {"x": 10, "y": 20, "w": 200, "h": 80}}],
                "action_templates": [
                    {
                        "action_template_id": "open_job_card",
                        "semantic_action": "open_detail",
                        "target_entity": "job_card_1",
                        "target_region_id": "job_card_1",
                    }
                ],
                "blockers": [{"blocker_id": "final_submit_forbidden", "label": "Final submit forbidden"}],
                "verification_rules": [{"rule_id": "verify_detail_visible", "label": "Detail visible"}],
                "safety": {"final_submit_forbidden": True},
            },
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
            "counts_as_pure_model_generated": False,
        },
    )


def _candidate_package(tmp_path: Path, *, validation_status: str) -> Path:
    candidate_dir = tmp_path / "artifacts" / "learning-draft-review" / "sample" / "pathgraph_candidate"
    reviewed_path = _reviewed_candidate(candidate_dir.parent / "reviewed_template_candidate.json")
    validation = {
        "contract_version": "pathgraph_candidate_validation_report_v1",
        "validation_status": validation_status,
        "checks": [
            {"check_id": "states_present", "passed": True},
            {"check_id": "regions_present", "passed": True},
            {"check_id": "action_templates_present", "passed": True},
            {"check_id": "unsafe_final_actions_absent", "passed": True},
            {
                "check_id": "precise_understanding_ready_for_pathgraph_candidate",
                "passed": validation_status == "passed_candidate",
            },
            {"check_id": "precise_understanding_evidence_integrity_complete", "passed": True},
        ],
        "summary": {
            "state_count": 1,
            "region_count": 1,
            "action_template_count": 1,
            "failed_check_count": 0 if validation_status == "passed_candidate" else 1,
            "candidate_only": True,
            "operation_dispatch": "not_executed",
            "precise_understanding_readiness_summary": {
                "readiness_status": "ready_for_pathgraph_candidate_review"
                if validation_status == "passed_candidate"
                else "needs_pending_calibration",
                "pending_calibration_ready_count": 0 if validation_status == "passed_candidate" else 6,
            },
            "evidence_integrity": {"status": "complete"},
        },
        "precise_understanding_readiness_summary": {
            "readiness_status": "ready_for_pathgraph_candidate_review"
            if validation_status == "passed_candidate"
            else "needs_pending_calibration",
            "pending_calibration_ready_count": 0 if validation_status == "passed_candidate" else 6,
        },
        "evidence_integrity": {"status": "complete"},
        "pending_detail_observe_requests": [],
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
        },
    }
    _write_json(candidate_dir / "promotion_validation_report.json", validation)
    return _write_json(
        candidate_dir / "pathgraph_candidate.json",
        {
            "contract_version": "pathgraph_candidate_v1",
            "candidate_status": validation_status,
            "reviewed_template_candidate_path": str(reviewed_path.relative_to(tmp_path)),
            "validation_report_path": str((candidate_dir / "promotion_validation_report.json").relative_to(tmp_path)),
            "validation_status": validation_status,
            "validation_summary": validation["summary"],
            "precise_understanding_readiness_summary": validation["precise_understanding_readiness_summary"],
            "evidence_integrity": validation["evidence_integrity"],
            "pending_detail_observe_requests": [],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
        },
    )


def test_pathgraph_integration_readiness_blocks_pending_calibration(tmp_path: Path) -> None:
    candidate = _candidate_package(tmp_path, validation_status="blocked_pending_calibration")

    report = report_learn_fusion_pathgraph_integration_readiness(
        pathgraph_candidate_path=candidate,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["contract_version"] == "learn_fusion_pathgraph_integration_readiness_report_v1"
    assert report["integration_readiness_status"] == "blocked_pending_calibration"
    assert report["ready_for_audited_pathgraph_review"] is False
    assert report["ready_for_runtime_pathgraph_promotion"] is False
    assert "pending_calibration_required" in report["blockers"]
    assert report["next_required_steps"][0] == "run_approved_numbered_region_calibration_batch"
    assert report["safety"]["execute_binding_enabled"] is False
    assert report["safety"]["artifact_is_authorization"] is False


def test_pathgraph_integration_readiness_allows_only_audited_review_when_candidate_gate_passes(tmp_path: Path) -> None:
    candidate = _candidate_package(tmp_path, validation_status="passed_candidate")

    report = report_learn_fusion_pathgraph_integration_readiness(
        pathgraph_candidate_path=candidate,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["integration_readiness_status"] == "ready_for_audited_pathgraph_review"
    assert report["ready_for_audited_pathgraph_review"] is True
    assert report["ready_for_runtime_pathgraph_promotion"] is False
    assert report["blockers"] == []
    assert report["next_required_steps"] == ["human_audit_before_runtime_pathgraph_promotion"]
    assert report["not_runtime_promotion"] is True


def test_pathgraph_integration_readiness_blocks_stale_calibration_pre_run_evidence(tmp_path: Path) -> None:
    candidate = _candidate_package(tmp_path, validation_status="passed_candidate")
    candidate_dir = candidate.parent
    approval_packet = _write_json(
        candidate_dir / "learn_fusion_model_start_approval_packet.json",
        {
            "contract_version": "learn_fusion_model_start_approval_packet_v1",
            "approval_packet_status": "ready_for_user_approval",
            "requires_explicit_user_approval": True,
            "may_run_calibration_batch_now": False,
        },
    )
    stale_sha256 = hashlib.sha256(approval_packet.read_bytes()).hexdigest()
    _write_json(
        approval_packet,
        {
            "contract_version": "learn_fusion_model_start_approval_packet_v1",
            "approval_packet_status": "ready_for_user_approval",
            "requires_explicit_user_approval": True,
            "may_run_calibration_batch_now": False,
            "changed_after_pre_run": True,
        },
    )
    _write_json(
        candidate_dir / "learn_fusion_calibration_pre_run_check_report.json",
        {
            "contract_version": "learn_fusion_calibration_pre_run_check_v1",
            "pre_run_status": "ready_after_explicit_approval",
            "approval_packet_path": str(approval_packet.relative_to(tmp_path)),
            "approval_packet_sha256": stale_sha256,
            "may_run_calibration_batch_now": False,
            "blockers": [],
        },
    )

    report = report_learn_fusion_pathgraph_integration_readiness(
        pathgraph_candidate_path=candidate,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["integration_readiness_status"] == "blocked_stale_pre_run_evidence"
    assert report["ready_for_audited_pathgraph_review"] is False
    assert "stale_calibration_pre_run_evidence" in report["blockers"]
    assert report["calibration_pre_run_check"]["effective_pre_run_status"] == "stale_pre_run_evidence"
