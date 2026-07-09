from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_NAME = "actual_parser_output_with_fusion_status.json"
REPORT_NAME = "fusion_status_attach_result.json"


def attach_fusion_status_to_learning_trial(
    *,
    trial_path: str | Path,
    fusion_status_path: str | Path,
    gate_diagnosis_path: str | Path | None = None,
    pathgraph_review_queue_path: str | Path | None = None,
    pathgraph_preflight_plan_path: str | Path | None = None,
    review_patch_proposal_path: str | Path | None = None,
    calibration_batch_plan_path: str | Path | None = None,
    calibration_handoff_report_path: str | Path | None = None,
    calibration_batch_acceptance_report_path: str | Path | None = None,
    calibration_handoff_consistency_report_path: str | Path | None = None,
    model_start_runbook_path: str | Path | None = None,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    trial_file = _resolve_path(trial_path, root)
    status_file = _resolve_path(fusion_status_path, root)
    diagnosis_file = _resolve_path(gate_diagnosis_path, root) if gate_diagnosis_path is not None else None
    queue_file = _resolve_path(pathgraph_review_queue_path, root) if pathgraph_review_queue_path is not None else None
    preflight_file = _resolve_path(pathgraph_preflight_plan_path, root) if pathgraph_preflight_plan_path is not None else None
    proposal_file = _resolve_path(review_patch_proposal_path, root) if review_patch_proposal_path is not None else None
    batch_plan_file = _resolve_path(calibration_batch_plan_path, root) if calibration_batch_plan_path is not None else None
    handoff_file = _resolve_path(calibration_handoff_report_path, root) if calibration_handoff_report_path is not None else None
    acceptance_file = (
        _resolve_path(calibration_batch_acceptance_report_path, root)
        if calibration_batch_acceptance_report_path is not None
        else None
    )
    consistency_file = (
        _resolve_path(calibration_handoff_consistency_report_path, root)
        if calibration_handoff_consistency_report_path is not None
        else None
    )
    runbook_file = _resolve_path(model_start_runbook_path, root) if model_start_runbook_path is not None else None
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    trial = _read_json(trial_file)
    status = _read_json(status_file)
    draft = _select_draft(trial)
    page_details = draft.setdefault("page_details", {})
    if not isinstance(page_details, dict):
        page_details = {}
        draft["page_details"] = page_details
    pipeline_audit = page_details.setdefault("pipeline_audit", {})
    if not isinstance(pipeline_audit, dict):
        pipeline_audit = {}
        page_details["pipeline_audit"] = pipeline_audit

    diagnosis = _read_json(diagnosis_file) if diagnosis_file is not None else None
    queue = _read_json(queue_file) if queue_file is not None else None
    preflight = _read_json(preflight_file) if preflight_file is not None else None
    proposal = _read_json(proposal_file) if proposal_file is not None else None
    batch_plan = _read_json(batch_plan_file) if batch_plan_file is not None else None
    handoff_report = _read_json(handoff_file) if handoff_file is not None else None
    acceptance_report = _read_json(acceptance_file) if acceptance_file is not None else None
    consistency_report = _read_json(consistency_file) if consistency_file is not None else None
    runbook = _read_json(runbook_file) if runbook_file is not None else None
    attached = _attached_status_payload(
        status=status,
        status_path=status_file,
        root=root,
        diagnosis=diagnosis,
        diagnosis_path=diagnosis_file,
        pathgraph_review_queue=queue,
        queue_path=queue_file,
        pathgraph_preflight_plan=preflight,
        preflight_path=preflight_file,
        review_patch_proposal=proposal,
        proposal_path=proposal_file,
        calibration_batch_plan=batch_plan,
        batch_plan_path=batch_plan_file,
        calibration_handoff_report=handoff_report,
        handoff_path=handoff_file,
        calibration_batch_acceptance_report=acceptance_report,
        acceptance_path=acceptance_file,
        calibration_handoff_consistency_report=consistency_report,
        consistency_path=consistency_file,
        model_start_runbook=runbook,
        runbook_path=runbook_file,
    )
    pipeline_audit["precise_understanding_fusion_status"] = deepcopy(attached)
    page_details["precise_understanding_fusion_status"] = deepcopy(attached)
    trial["precise_understanding_fusion_status"] = deepcopy(attached)

    output_path = out / OUTPUT_NAME
    output_path.write_text(json.dumps(trial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = {
        "contract_version": "learn_precise_understanding_fusion_status_attach_result_v1",
        "source_trial_path": _relative_path(trial_file, root),
        "fusion_status_path": _relative_path(status_file, root),
        "gate_diagnosis_path": _relative_path(diagnosis_file, root) if diagnosis_file is not None else None,
        "pathgraph_review_queue_path": _relative_path(queue_file, root) if queue_file is not None else None,
        "pathgraph_preflight_plan_path": _relative_path(preflight_file, root) if preflight_file is not None else None,
        "review_patch_proposal_path": _relative_path(proposal_file, root) if proposal_file is not None else None,
        "calibration_batch_plan_path": _relative_path(batch_plan_file, root) if batch_plan_file is not None else None,
        "calibration_handoff_report_path": _relative_path(handoff_file, root) if handoff_file is not None else None,
        "calibration_batch_acceptance_report_path": _relative_path(acceptance_file, root) if acceptance_file is not None else None,
        "calibration_handoff_consistency_report_path": _relative_path(consistency_file, root) if consistency_file is not None else None,
        "model_start_runbook_path": _relative_path(runbook_file, root) if runbook_file is not None else None,
        "output_path": str(output_path.resolve()),
        "attach_status": "attached",
        "attached_contract": attached["contract_version"],
        "display_readiness_status": attached.get("display_readiness", {}).get("status"),
        "pathgraph_preparation_status": attached.get("pathgraph_preparation", {}).get("status"),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "display_only": True,
        "interpretation": (
            "Fusion status is attached for Learning Draft display and human PathGraph preparation review only; "
            "it does not authorize Execute, clicks, safe fill, submit, or Runtime PathGraph promotion."
        ),
    }
    report_path = out / REPORT_NAME
    result["attach_report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _attached_status_payload(
    *,
    status: dict[str, Any],
    status_path: Path,
    root: Path,
    diagnosis: dict[str, Any] | None = None,
    diagnosis_path: Path | None = None,
    pathgraph_review_queue: dict[str, Any] | None = None,
    queue_path: Path | None = None,
    pathgraph_preflight_plan: dict[str, Any] | None = None,
    preflight_path: Path | None = None,
    review_patch_proposal: dict[str, Any] | None = None,
    proposal_path: Path | None = None,
    calibration_batch_plan: dict[str, Any] | None = None,
    batch_plan_path: Path | None = None,
    calibration_handoff_report: dict[str, Any] | None = None,
    handoff_path: Path | None = None,
    calibration_batch_acceptance_report: dict[str, Any] | None = None,
    acceptance_path: Path | None = None,
    calibration_handoff_consistency_report: dict[str, Any] | None = None,
    consistency_path: Path | None = None,
    model_start_runbook: dict[str, Any] | None = None,
    runbook_path: Path | None = None,
) -> dict[str, Any]:
    full_overlay_path = status.get("full_screen_understanding_overlay_path")
    compiled_overlay_path = status.get("compiled_overlay_path")
    payload = {
        "contract_version": "learning_draft_precise_understanding_fusion_status_v1",
        "source_status_report_path": _relative_path(status_path, root),
        "source_calibration_report_path": status.get("source_report_path"),
        "screenshot_path": status.get("screenshot_path"),
        "full_screen_understanding_overlay_path": full_overlay_path,
        "compiled_overlay_path": compiled_overlay_path,
        "display_readiness": _attached_display_readiness(
            status.get("display_readiness"),
            full_overlay_path=full_overlay_path,
            compiled_overlay_path=compiled_overlay_path,
            screenshot_path=status.get("screenshot_path"),
        ),
        "pathgraph_preparation": _attached_pathgraph_preparation(
            status.get("pathgraph_preparation"),
            pathgraph_review_queue=pathgraph_review_queue,
        ),
        "summary": deepcopy(status.get("summary")) if isinstance(status.get("summary"), dict) else {},
        "block_reason_counts": deepcopy(status.get("block_reason_counts")) if isinstance(status.get("block_reason_counts"), dict) else {},
        "calibration_status_counts": deepcopy(status.get("calibration_status_counts"))
        if isinstance(status.get("calibration_status_counts"), dict)
        else {},
        "gate_safety_counts": deepcopy(status.get("gate_safety_counts")) if isinstance(status.get("gate_safety_counts"), dict) else {},
        "point_quality_counts": deepcopy(status.get("point_quality_counts")) if isinstance(status.get("point_quality_counts"), dict) else {},
        "calibration_backlog": _attached_calibration_backlog(status.get("calibration_backlog")),
        "items": deepcopy(status.get("items")) if isinstance(status.get("items"), list) else [],
        "precise_understanding_readiness_summary": _attached_readiness_summary(
            status.get("precise_understanding_readiness_summary")
        ),
        "display_only": True,
        "not_accuracy": True,
        "not_e2e_success": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Attached fused understanding status for display/review. "
            "This is not recognition accuracy, Execute authorization, live fill, submit, or PathGraph promotion."
        ),
    }
    if isinstance(status.get("targeted_rerun_correction"), dict):
        payload["targeted_rerun_correction"] = deepcopy(status["targeted_rerun_correction"])
        payload["targeted_rerun_correction"]["execute_binding_enabled"] = False
        payload["targeted_rerun_correction"]["artifact_is_authorization"] = False
    if isinstance(diagnosis, dict):
        payload["gate_rejection_diagnosis"] = {
            "contract_version": "learning_draft_fusion_gate_rejection_diagnosis_v1",
            "source_diagnosis_report_path": _relative_path(diagnosis_path, root) if diagnosis_path is not None else "",
            "summary": deepcopy(diagnosis.get("summary")) if isinstance(diagnosis.get("summary"), dict) else {},
            "cases": deepcopy(diagnosis.get("cases")) if isinstance(diagnosis.get("cases"), list) else [],
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "interpretation": "Gate rejection diagnosis is review-only and does not authorize clicks.",
        }
    if isinstance(pathgraph_review_queue, dict):
        payload["pathgraph_review_queue"] = {
            "contract_version": "learning_draft_fusion_pathgraph_review_queue_v1",
            "source_queue_path": _relative_path(queue_path, root) if queue_path is not None else "",
            "summary": deepcopy(pathgraph_review_queue.get("summary"))
            if isinstance(pathgraph_review_queue.get("summary"), dict)
            else {},
            "queue_items": deepcopy(pathgraph_review_queue.get("queue_items"))
            if isinstance(pathgraph_review_queue.get("queue_items"), list)
            else [],
            "display_only": True,
            "candidate_only": True,
            "not_pathgraph_promotion": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "interpretation": "PathGraph review queue is display/review-only and does not authorize clicks or promotion.",
        }
    embedded_preflight_plan = (
        pathgraph_preflight_plan
        if isinstance(pathgraph_preflight_plan, dict)
        else status.get("pathgraph_preflight_plan")
        if isinstance(status.get("pathgraph_preflight_plan"), dict)
        else None
    )
    embedded_preflight_path = preflight_path if isinstance(pathgraph_preflight_plan, dict) else None
    if isinstance(embedded_preflight_plan, dict):
        pending_batch = (
            embedded_preflight_plan.get("pending_calibration_batch")
            if isinstance(embedded_preflight_plan.get("pending_calibration_batch"), dict)
            else {}
        )
        payload["pathgraph_preflight_plan"] = {
            "contract_version": "learning_draft_fusion_pathgraph_preflight_plan_v1",
            "source_preflight_plan_path": _relative_path(embedded_preflight_path, root) if embedded_preflight_path is not None else "",
            "summary": deepcopy(embedded_preflight_plan.get("summary"))
            if isinstance(embedded_preflight_plan.get("summary"), dict)
            else {},
            "proposed_states": deepcopy(embedded_preflight_plan.get("proposed_states"))
            if isinstance(embedded_preflight_plan.get("proposed_states"), list)
            else [],
            "proposed_transitions": deepcopy(embedded_preflight_plan.get("proposed_transitions"))
            if isinstance(embedded_preflight_plan.get("proposed_transitions"), list)
            else [],
            "review_action_items": deepcopy(embedded_preflight_plan.get("review_action_items"))
            if isinstance(embedded_preflight_plan.get("review_action_items"), list)
            else [],
            "blocked_items": deepcopy(embedded_preflight_plan.get("blocked_items"))
            if isinstance(embedded_preflight_plan.get("blocked_items"), list)
            else [],
            "pending_calibration_batch": _attached_pending_calibration_batch(pending_batch),
            "display_only": True,
            "candidate_only": True,
            "not_pathgraph_promotion": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "interpretation": "PathGraph preflight plan is review-only and does not create or promote a Runtime PathGraph.",
        }
    if isinstance(review_patch_proposal, dict):
        payload["review_patch_proposal"] = {
            "contract_version": "learning_draft_fusion_review_patch_proposal_v1",
            "source_proposal_path": _relative_path(proposal_path, root) if proposal_path is not None else "",
            "summary": deepcopy(review_patch_proposal.get("summary"))
            if isinstance(review_patch_proposal.get("summary"), dict)
            else {},
            "review_patch": deepcopy(review_patch_proposal.get("review_patch"))
            if isinstance(review_patch_proposal.get("review_patch"), dict)
            else {},
            "display_only": True,
            "candidate_only": True,
            "not_pathgraph_promotion": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "interpretation": "Review patch proposal is for human review and does not save or promote a Runtime PathGraph.",
        }
    embedded_batch_plan = (
        calibration_batch_plan
        if isinstance(calibration_batch_plan, dict)
        else status.get("calibration_batch_plan")
        if isinstance(status.get("calibration_batch_plan"), dict)
        else None
    )
    embedded_batch_path = batch_plan_path if isinstance(calibration_batch_plan, dict) else None
    if isinstance(embedded_batch_plan, dict):
        payload["calibration_batch_plan"] = {
            "contract_version": "learning_draft_numbered_region_calibration_batch_plan_v1",
            "source_batch_plan_path": _relative_path(embedded_batch_path, root) if embedded_batch_path is not None else "",
            "summary": deepcopy(embedded_batch_plan.get("summary"))
            if isinstance(embedded_batch_plan.get("summary"), dict)
            else {},
            "ready_region_numbers": deepcopy(embedded_batch_plan.get("ready_region_numbers"))
            if isinstance(embedded_batch_plan.get("ready_region_numbers"), list)
            else [],
            "review_blocked_region_numbers": deepcopy(embedded_batch_plan.get("review_blocked_region_numbers"))
            if isinstance(embedded_batch_plan.get("review_blocked_region_numbers"), list)
            else [],
            "run_command_preview": embedded_batch_plan.get("run_command_preview"),
            "command_executes_now": False,
            "post_batch_refresh_command_preview": embedded_batch_plan.get("post_batch_refresh_command_preview"),
            "post_batch_refresh_command_executes_now": False,
            "post_batch_refresh_requires_completed_batch": embedded_batch_plan.get("post_batch_refresh_requires_completed_batch") is True,
            "display_only": True,
            "not_calibration_execution": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "interpretation": "Calibration batch plan is a review-only command preview; it does not start models or execute calibration.",
        }
    embedded_handoff = (
        calibration_handoff_report
        if isinstance(calibration_handoff_report, dict)
        else status.get("calibration_handoff_report")
        if isinstance(status.get("calibration_handoff_report"), dict)
        else None
    )
    embedded_handoff_path = handoff_path if isinstance(calibration_handoff_report, dict) else None
    if isinstance(embedded_handoff, dict):
        payload["calibration_handoff_report"] = _attached_calibration_handoff_report(
            embedded_handoff,
            source_path=_relative_path(embedded_handoff_path, root) if embedded_handoff_path is not None else "",
        )
    embedded_acceptance = (
        calibration_batch_acceptance_report
        if isinstance(calibration_batch_acceptance_report, dict)
        else status.get("calibration_batch_acceptance_report")
        if isinstance(status.get("calibration_batch_acceptance_report"), dict)
        else None
    )
    embedded_acceptance_path = acceptance_path if isinstance(calibration_batch_acceptance_report, dict) else None
    if isinstance(embedded_acceptance, dict):
        payload["calibration_batch_acceptance_report"] = _attached_calibration_batch_acceptance_report(
            embedded_acceptance,
            source_path=_relative_path(embedded_acceptance_path, root) if embedded_acceptance_path is not None else "",
        )
    embedded_consistency = (
        calibration_handoff_consistency_report
        if isinstance(calibration_handoff_consistency_report, dict)
        else status.get("calibration_handoff_consistency_report")
        if isinstance(status.get("calibration_handoff_consistency_report"), dict)
        else None
    )
    embedded_consistency_path = consistency_path if isinstance(calibration_handoff_consistency_report, dict) else None
    if isinstance(embedded_consistency, dict):
        payload["calibration_handoff_consistency_report"] = _attached_calibration_handoff_consistency_report(
            embedded_consistency,
            source_path=_relative_path(embedded_consistency_path, root) if embedded_consistency_path is not None else "",
        )
    embedded_runbook = (
        model_start_runbook
        if isinstance(model_start_runbook, dict)
        else status.get("model_start_runbook")
        if isinstance(status.get("model_start_runbook"), dict)
        else None
    )
    embedded_runbook_path = runbook_path if isinstance(model_start_runbook, dict) else None
    if isinstance(embedded_runbook, dict):
        payload["model_start_runbook"] = _attached_model_start_runbook(
            embedded_runbook,
            source_path=_relative_path(embedded_runbook_path, root) if embedded_runbook_path is not None else "",
        )
    return payload


def _attached_display_readiness(
    value: Any,
    *,
    full_overlay_path: Any,
    compiled_overlay_path: Any,
    screenshot_path: Any,
) -> dict[str, Any]:
    display = deepcopy(value) if isinstance(value, dict) else {}
    has_full = bool(str(full_overlay_path or "").strip())
    has_compiled = bool(str(compiled_overlay_path or "").strip())
    has_screenshot = bool(str(screenshot_path or "").strip())
    if not display:
        display = {
            "status": "display_ready" if has_full or has_compiled else "display_evidence_missing",
            "full_screen_overlay_available": has_full,
            "overlay_available": has_compiled,
            "screenshot_available": has_screenshot,
        }
    else:
        display.setdefault("status", "display_ready" if has_full or has_compiled else "display_evidence_missing")
        display.setdefault("full_screen_overlay_available", has_full)
        display.setdefault("overlay_available", has_compiled)
        display.setdefault("screenshot_available", has_screenshot)
    display["interpretation"] = display.get("interpretation") or "display readiness only; it does not authorize Execute or PathGraph promotion"
    return display


def _attached_pathgraph_preparation(value: Any, *, pathgraph_review_queue: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict) and value:
        return deepcopy(value)
    queue_items = _list_of_dicts(pathgraph_review_queue.get("queue_items")) if isinstance(pathgraph_review_queue, dict) else []
    if not queue_items:
        return {}
    return {
        "status": "blocked_from_pathgraph_candidate_review",
        "promotable_item_count": 0,
        "blocked_item_count": len(queue_items),
        "interpretation": "derived from review queue for display only; not Runtime PathGraph promotion",
    }


def _attached_calibration_backlog(value: Any) -> dict[str, Any]:
    backlog = deepcopy(value) if isinstance(value, dict) else {}
    if not backlog:
        return {
            "contract_version": "numbered_region_calibration_backlog_v1",
            "summary": {
                "uncalibrated_locator_cards": 0,
                "display_only": True,
                "execute_binding_enabled": False,
            },
            "items": [],
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    summary = backlog.get("summary") if isinstance(backlog.get("summary"), dict) else {}
    summary["display_only"] = True
    summary["execute_binding_enabled"] = False
    backlog["summary"] = summary
    backlog["items"] = deepcopy(backlog.get("items")) if isinstance(backlog.get("items"), list) else []
    backlog["display_only"] = True
    backlog["execute_binding_enabled"] = False
    backlog["artifact_is_authorization"] = False
    return backlog


def _attached_readiness_summary(value: Any) -> dict[str, Any]:
    summary = deepcopy(value) if isinstance(value, dict) else {}
    if not summary:
        return {
            "contract_version": "precise_understanding_readiness_summary_v1",
            "readiness_status": "not_available",
            "pending_calibration_ready_count": 0,
            "pending_calibration_review_count": 0,
            "display_only": True,
            "not_accuracy": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    summary["display_only"] = True
    summary["not_accuracy"] = True
    summary["execute_binding_enabled"] = False
    summary["artifact_is_authorization"] = False
    return summary


def _attached_pending_calibration_batch(pending_batch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(pending_batch, dict) or not pending_batch:
        return {
            "contract_version": "learning_draft_fusion_pending_calibration_batch_v1",
            "ready_region_numbers": [],
            "review_blocked_region_numbers": [],
            "run_command_preview": "",
            "command_executes_now": False,
            "display_only": True,
            "not_calibration_execution": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    return {
        "contract_version": "learning_draft_fusion_pending_calibration_batch_v1",
        "source_batch_plan_path": pending_batch.get("source_batch_plan_path"),
        "summary": deepcopy(pending_batch.get("summary")) if isinstance(pending_batch.get("summary"), dict) else {},
        "ready_region_numbers": deepcopy(pending_batch.get("ready_region_numbers"))
        if isinstance(pending_batch.get("ready_region_numbers"), list)
        else [],
        "review_blocked_region_numbers": deepcopy(pending_batch.get("review_blocked_region_numbers"))
        if isinstance(pending_batch.get("review_blocked_region_numbers"), list)
        else [],
        "run_command_preview": pending_batch.get("run_command_preview"),
        "command_executes_now": False,
        "display_only": True,
        "not_calibration_execution": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Pending calibration batch is attached for PathGraph preparation review only; "
            "it does not start models or execute calibration."
        ),
    }


def _attached_calibration_handoff_report(report: dict[str, Any], *, source_path: str) -> dict[str, Any]:
    future_outputs = report.get("future_outputs") if isinstance(report.get("future_outputs"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    return {
        "contract_version": "learning_draft_calibration_handoff_report_v1",
        "source_handoff_report_path": source_path,
        "handoff_status": str(report.get("handoff_status") or ""),
        "safe_to_start_after_user_approval": report.get("safe_to_start_after_user_approval") is True,
        "ready_region_numbers": _list_of_ints(report.get("ready_region_numbers")),
        "review_blocked_region_numbers": _list_of_ints(report.get("review_blocked_region_numbers")),
        "future_outputs": {
            "rerun_report_path": future_outputs.get("rerun_report_path"),
            "rerun_report_status": str(future_outputs.get("rerun_report_status") or ""),
            "post_batch_refresh_requires_completed_batch": future_outputs.get("post_batch_refresh_requires_completed_batch") is True,
        },
        "blockers": _list_of_strings(report.get("blockers")),
        "warnings": _list_of_strings(report.get("warnings")),
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": safety.get("final_submit_forbidden") is not False,
            "real_clicks": _int_value(safety.get("real_clicks"), 0),
            "live_fill": safety.get("live_fill") is True,
            "live_submit": safety.get("live_submit") is True,
        },
        "display_only": True,
        "not_calibration_execution": True,
        "not_pathgraph_promotion": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": "Calibration handoff report is preflight evidence only; it does not start models or authorize execution.",
    }


def _attached_calibration_batch_acceptance_report(report: dict[str, Any], *, source_path: str) -> dict[str, Any]:
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    return {
        "contract_version": "learning_draft_calibration_batch_acceptance_report_v1",
        "source_acceptance_report_path": source_path,
        "acceptance_status": str(report.get("acceptance_status") or ""),
        "ready_for_post_batch_refresh": report.get("ready_for_post_batch_refresh") is True,
        "coverage": {
            "expected_ready_region_numbers": _list_of_ints(coverage.get("expected_ready_region_numbers")),
            "accepted_region_numbers": _list_of_ints(coverage.get("accepted_region_numbers")),
            "missing_ready_region_numbers": _list_of_ints(coverage.get("missing_ready_region_numbers")),
            "unexpected_region_numbers": _list_of_ints(coverage.get("unexpected_region_numbers")),
            "review_blocked_region_numbers_in_rerun": _list_of_ints(coverage.get("review_blocked_region_numbers_in_rerun")),
        },
        "checks": deepcopy(checks),
        "blockers": _list_of_strings(report.get("blockers")),
        "warnings": _list_of_strings(report.get("warnings")),
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": safety.get("final_submit_forbidden") is not False,
            "real_clicks": _int_value(safety.get("real_clicks"), 0),
        },
        "display_only": True,
        "not_calibration_execution": True,
        "not_pathgraph_promotion": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": "Calibration batch acceptance report is pre-refresh evidence only; it does not refresh, merge, start models, or authorize execution.",
    }


def _attached_calibration_handoff_consistency_report(report: dict[str, Any], *, source_path: str) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    return {
        "contract_version": "learning_draft_calibration_handoff_consistency_report_v1",
        "source_consistency_report_path": source_path,
        "consistency_status": str(report.get("consistency_status") or ""),
        "summary": {
            "readiness_status": str(summary.get("readiness_status") or ""),
            "handoff_status": str(summary.get("handoff_status") or ""),
            "acceptance_status": str(summary.get("acceptance_status") or ""),
            "ready_region_numbers": _list_of_ints(summary.get("ready_region_numbers")),
            "review_blocked_region_numbers": _list_of_ints(summary.get("review_blocked_region_numbers")),
            "post_batch_refresh_has_batch_plan": summary.get("post_batch_refresh_has_batch_plan") is True,
            "refresh_blocks_before_future_rerun": summary.get("refresh_blocks_before_future_rerun") is True,
        },
        "checks": deepcopy(checks),
        "blockers": _list_of_strings(report.get("blockers")),
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_started": safety.get("model_started") is True,
            "live_clicks": _int_value(safety.get("live_clicks"), 0),
            "live_fills": _int_value(safety.get("live_fills"), 0),
            "live_submits": _int_value(safety.get("live_submits"), 0),
            "runtime_pathgraph_promotion": safety.get("runtime_pathgraph_promotion") is True,
        },
        "display_only": True,
        "not_calibration_execution": True,
        "not_pathgraph_promotion": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": "Handoff consistency report is package-level preflight evidence only; it does not start models, merge evidence, or authorize execution.",
    }


def _attached_model_start_runbook(report: dict[str, Any], *, source_path: str) -> dict[str, Any]:
    guards = report.get("guards") if isinstance(report.get("guards"), dict) else {}
    safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
    return {
        "contract_version": "learning_draft_model_start_runbook_v1",
        "source_runbook_path": source_path,
        "runbook_status": str(report.get("runbook_status") or ""),
        "approval_required": report.get("approval_required") is True,
        "may_start_model_after_user_approval": report.get("may_start_model_after_user_approval") is True,
        "may_run_calibration_batch_now": False,
        "next_manual_action": str(report.get("next_manual_action") or ""),
        "ready_region_numbers": _list_of_ints(report.get("ready_region_numbers")),
        "review_blocked_region_numbers": _list_of_ints(report.get("review_blocked_region_numbers")),
        "guards": {
            "post_batch_refresh_has_batch_plan": guards.get("post_batch_refresh_has_batch_plan") is True,
            "prebatch_refresh_blocks_before_future_rerun": guards.get("prebatch_refresh_blocks_before_future_rerun") is True,
            "acceptance_required_before_refresh": guards.get("acceptance_required_before_refresh") is True,
            "accepted_for_post_batch_refresh": guards.get("accepted_for_post_batch_refresh") is True,
        },
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_started": safety.get("model_started") is True,
            "live_clicks": _int_value(safety.get("live_clicks"), 0),
            "live_fills": _int_value(safety.get("live_fills"), 0),
            "live_submits": _int_value(safety.get("live_submits"), 0),
            "display_only_until_user_approval": safety.get("display_only_until_user_approval") is not False,
        },
        "blockers": _list_of_strings(report.get("blockers")),
        "display_only": True,
        "not_calibration_execution": True,
        "not_pathgraph_promotion": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": "Model-start runbook is an offline checklist only; it does not start models or authorize execution.",
    }


def _select_draft(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("learning_draft", "best_learning_draft", "draft"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    if payload.get("contract_version") == "learning_template_draft_v1":
        return payload
    raise ValueError("trial does not contain a learning draft")


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_of_ints(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _int_value(*values: Any) -> int:
    for value in values:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attach precise-understanding fusion status to a Learning Draft trial.")
    parser.add_argument("--trial", required=True, help="Path to actual_parser_output/trial JSON containing learning_draft")
    parser.add_argument("--fusion-status", required=True, help="Path to learn_precise_understanding_fusion_status_report.json")
    parser.add_argument("--gate-diagnosis", help="Optional path to learn_fusion_gate_rejection_diagnosis_report.json")
    parser.add_argument("--pathgraph-review-queue", help="Optional path to learn_fusion_pathgraph_review_queue.json")
    parser.add_argument("--pathgraph-preflight-plan", help="Optional path to learn_fusion_pathgraph_preflight_plan.json")
    parser.add_argument("--review-patch-proposal", help="Optional path to learn_fusion_review_patch_proposal.json")
    parser.add_argument("--calibration-batch-plan", help="Optional path to numbered_region_calibration_batch_plan.json")
    parser.add_argument("--calibration-handoff-report", help="Optional path to learn_fusion_calibration_handoff_report.json")
    parser.add_argument(
        "--calibration-batch-acceptance-report",
        help="Optional path to learn_fusion_calibration_batch_acceptance_report.json",
    )
    parser.add_argument(
        "--calibration-handoff-consistency-report",
        help="Optional path to learn_fusion_handoff_consistency_report.json",
    )
    parser.add_argument("--model-start-runbook", help="Optional path to learn_fusion_model_start_runbook.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    attach_fusion_status_to_learning_trial(
        trial_path=args.trial,
        fusion_status_path=args.fusion_status,
        gate_diagnosis_path=args.gate_diagnosis,
        pathgraph_review_queue_path=args.pathgraph_review_queue,
        pathgraph_preflight_plan_path=args.pathgraph_preflight_plan,
        review_patch_proposal_path=args.review_patch_proposal,
        calibration_batch_plan_path=args.calibration_batch_plan,
        calibration_handoff_report_path=args.calibration_handoff_report,
        calibration_batch_acceptance_report_path=args.calibration_batch_acceptance_report,
        calibration_handoff_consistency_report_path=args.calibration_handoff_consistency_report,
        model_start_runbook_path=args.model_start_runbook,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
