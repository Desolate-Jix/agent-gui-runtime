from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app.core.runtime_artifacts import write_trace
from app.learn.recognition import (
    build_learning_recognition_trial,
    fusion_status_from_two_stage,
)
from app.learn.workflow_contracts import (
    LearningTaskFailure,
    LearningTaskResult,
    RecognitionTaskInput,
)

TrialBuilder = Callable[..., dict[str, Any]]
GroundingAdapter = Callable[..., dict[str, Any]]
TrialSaver = Callable[..., str]
TraceWriter = Callable[..., str]


def run_recognition_task(
    task_input: RecognitionTaskInput,
    *,
    project_root: Path,
    trial_builder: TrialBuilder = build_learning_recognition_trial,
    grounding_adapter: GroundingAdapter | None = None,
    trial_saver: TrialSaver | None = None,
    trace_writer: TraceWriter = write_trace,
) -> LearningTaskResult:
    """生成只读学习草稿，并保持执行授权始终关闭。"""

    root = project_root.resolve()
    try:
        observe_bundle = _build_observe_bundle(task_input)
        two_stage_report = _load_two_stage_report(
            task_input.two_stage_report_path,
            project_root=root,
        )
        two_stage_review_evidence = _attach_numbered_review_regions(
            observe_bundle,
            two_stage_report,
        )
        summary = task_input.summary or _recognition_summary(
            task_input.observation_evidence
        )
        result = trial_builder(
            observe_bundle=observe_bundle,
            state_guess=task_input.state_hint,
            summary=summary,
            grounding_adapter=grounding_adapter or _calibrated_target_grounding,
            crop_size=task_input.crop_size if task_input.crop_size else None,
            two_stage_understanding_override=two_stage_report,
        )
        fusion_status = _fusion_status_from_report(two_stage_report)
        if fusion_status:
            fusion_status = _attach_current_calibrated_overlay(
                fusion_status,
                task_input.observation_evidence,
                project_root=root,
            )
            _attach_fusion_status_to_result(result, fusion_status)

        precise_status = _precise_understanding_status(fusion_status)
        review_box_status = _review_box_status(
            two_stage_review_evidence=two_stage_review_evidence,
            fusion_status=fusion_status,
        )
        safety = {
            **(result.get("safety") if isinstance(result.get("safety"), dict) else {}),
            "real_clicks_performed": 0,
            "promotion_allowed": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "live_safe_fill_attempted": 0,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
        }
        provider_summary = _omniparser_provider_summary(
            observe_bundle=observe_bundle,
            result=result,
        )
        _attach_provider_summary_to_draft(result, provider_summary)
        model_provenance = _model_provenance(
            observe_bundle,
            project_root=root,
        )
        actual_model_call = (
            model_provenance["actual_model_call_evidence_count"] > 0
        )
        saved_payload = {
            **result,
            "app_name": task_input.app_name,
            "state_hint": task_input.state_hint,
            "summary": summary,
            "artifact_type": "learn_recognition_trial",
            "draft_only": True,
            "draft_graph_preview": True,
            "runtime_path_graph": False,
            "promotion_allowed": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks": 0,
            "live_safe_fill_attempted": 0,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
            "precise_understanding_status": precise_status,
            "learn_all_targets": review_box_status,
            "best_attempt_index": 0,
            "best_learning_draft": result.get("learning_draft"),
            "source_type": "panel_observe_coordinate_evidence",
            "actual_model_call_in_this_run": actual_model_call,
            "model_generated": actual_model_call,
            "source_after_review": "mixed" if actual_model_call else "fixture_only",
            "counts_as_pure_model_generated": False,
            "model_provenance": model_provenance,
            "provider_summary": provider_summary,
            "panel_learning_studio": {
                "contract_version": "panel_learning_recognition_trial_v1",
                "draft_graph_preview": True,
                "display_only": True,
                "source": "panel_run_learning_recognition_trial",
                "two_stage_report_path": _text(task_input.two_stage_report_path),
                "two_stage_report_authoritative": bool(two_stage_report),
                "uses_execute_mode": False,
                "live_clicks": 0,
                "live_safe_fill": 0,
            },
            "observe_bundle": observe_bundle,
            "safety": safety,
        }
        save_trial = trial_saver or save_recognition_trial
        trial_path = save_trial(
            saved_payload,
            app_name=task_input.app_name,
            project_root=root,
        )
        trace_path = trace_writer(
            category="panel",
            operation="run-learning-recognition-trial",
            payload={
                "success": True,
                "request": task_input.model_dump(mode="json"),
                "result": {
                    "trial_path": trial_path,
                    "status": saved_payload.get("status"),
                    "artifact_type": saved_payload.get("artifact_type"),
                    "draft_only": True,
                    "real_clicks": 0,
                    "promotion_allowed": False,
                },
            },
            name_hint="learning_recognition_trial",
        )
        payload = {
            "contract_version": "panel_learning_recognition_trial_run_v1",
            "artifact_type": "learn_recognition_trial",
            "draft_only": True,
            "draft_graph_preview": True,
            "runtime_path_graph": False,
            "trial_path": trial_path,
            "trace_path": trace_path,
            "status": saved_payload.get("status"),
            "promotion_allowed": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks": 0,
            "live_safe_fill_attempted": 0,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
            "safety": safety,
            "learn_all_targets": review_box_status,
            "provider_summary": provider_summary,
            "summary": {
                "app_name": task_input.app_name,
                "state_hint": task_input.state_hint,
                "screen_inventory_count": len(
                    saved_payload.get("screen_inventory") or []
                ),
                "two_stage_report_attached": bool(fusion_status),
                "two_stage_review_region_count": _int_or_zero(
                    two_stage_review_evidence.get("attached_count")
                ),
                "two_stage_stage1_gate_status": (
                    fusion_status.get("stage1_gate_status")
                    if fusion_status
                    else ""
                ),
                "two_stage_stage2_numbering_skipped": (
                    bool(fusion_status.get("stage2_numbering_skipped"))
                    if fusion_status
                    else False
                ),
                "two_stage_review_box_count": (
                    _int_or_zero(fusion_status.get("review_box_count"))
                    if fusion_status
                    else 0
                ),
                "precise_understanding_status": precise_status,
                "accepted_for_grounding_count": int(
                    (
                        (saved_payload.get("classification") or {}).get(
                            "summary"
                        )
                        or {}
                    ).get("accepted_for_grounding_count")
                    or 0
                ),
                "grounding_validation_count": len(
                    saved_payload.get("grounding_validations") or []
                ),
                "draft_section_counts": _draft_section_counts(
                    saved_payload.get("learning_draft")
                ),
            },
        }
        return LearningTaskResult(outcome="completed", payload=payload)
    except Exception as exc:
        return LearningTaskResult(
            outcome="failed",
            payload={
                "app_name": task_input.app_name,
                "state_hint": task_input.state_hint,
            },
            failure=LearningTaskFailure(
                code="learning_recognition_trial_failed",
                details=str(exc),
            ),
        )


def save_recognition_trial(
    payload: dict[str, Any],
    *,
    app_name: str,
    project_root: Path,
) -> str:
    run_root = project_root / "artifacts" / "learning-runs"
    run_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    millis = int((time.time() % 1) * 1000)
    safe_app = _safe_slug(app_name or payload.get("app_name") or "unknown_app")
    run_dir = run_root / f"panel_{timestamp}-{millis:03d}_{safe_app}"
    run_dir.mkdir(parents=True, exist_ok=False)
    trial_path = run_dir / "trial_result.json"
    trial_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return _relative_path(trial_path, project_root=project_root)


def _build_observe_bundle(task_input: RecognitionTaskInput) -> dict[str, Any]:
    evidence = (
        task_input.observation_evidence
        if isinstance(task_input.observation_evidence, dict)
        else {}
    )
    screen_size = _first_dict(
        evidence.get("screen_size"),
        evidence.get("viewport_size"),
        evidence.get("image_size"),
    )
    targets = _normalized_calibrated_targets(evidence.get("calibrated_targets"))
    review_boxes = _normalized_review_boxes(evidence.get("review_boxes"))
    screen_map = (
        evidence.get("screen_map")
        if isinstance(evidence.get("screen_map"), dict)
        else {}
    )
    interface_classification = (
        evidence.get("interface_classification")
        if isinstance(evidence.get("interface_classification"), dict)
        else {}
    )
    sources: dict[str, Any] = {
        "calibrated_targets": {
            "targets": targets,
            "source_trace_path": _text(
                evidence.get("coordinate_trace_path") or evidence.get("trace_path")
            ),
            "source_overlay_path": _text(evidence.get("coordinate_overlay_path")),
        }
    }
    candidates = (
        screen_map.get("candidates")
        if isinstance(screen_map.get("candidates"), list)
        else []
    )
    if candidates or interface_classification:
        sources["vision"] = {}
        if candidates:
            sources["vision"]["regions"] = candidates
        if interface_classification:
            sources["vision"]["interface_classification"] = interface_classification
    omniparser = (
        evidence.get("omniparser")
        if isinstance(evidence.get("omniparser"), dict)
        else {}
    )
    if omniparser:
        sources["omniparser"] = deepcopy(omniparser)
    if review_boxes:
        ocr_boxes = [
            item for item in review_boxes if item.get("role") == "ocr_text_review_only"
        ]
        region_boxes = [
            item for item in review_boxes if item.get("role") != "ocr_text_review_only"
        ]
        if ocr_boxes:
            sources["ocr"] = {"texts": ocr_boxes}
        if region_boxes:
            vision = (
                dict(sources.get("vision") or {})
                if isinstance(sources.get("vision"), dict)
                else {}
            )
            existing_regions = list(
                vision.get("regions") or []
            )
            vision["regions"] = [*existing_regions, *region_boxes]
            sources["vision"] = vision
    return {
        "contract_version": "learn_observe_bundle_v1",
        "app_name": task_input.app_name,
        "state_hint": task_input.state_hint,
        "screen_size": screen_size,
        "capture_id": _text(evidence.get("capture_id")),
        "source_run_id": _text(evidence.get("source_run_id") or evidence.get("run_id")),
        "screenshot_sha256": _text(
            evidence.get("screenshot_sha256") or evidence.get("image_sha256")
        ),
        "coordinate_space": _text(evidence.get("coordinate_space")),
        "image_path": _text(
            evidence.get("current_image_path") or evidence.get("image_path")
        ),
        "source_image_path": _text(
            evidence.get("current_image_path") or evidence.get("image_path")
        ),
        "sources": sources,
        "panel_observation_evidence": {
            "contract_version": _text(evidence.get("contract_version")),
            "evidence_quality": _text(evidence.get("evidence_quality")),
            "model_roles": (
                evidence.get("model_roles")
                if isinstance(evidence.get("model_roles"), dict)
                else {}
            ),
            "interface_classification": interface_classification,
            "coordinate_overlay_path": _text(
                evidence.get("coordinate_overlay_path")
            ),
            "learn_all_targets_summary": (
                evidence.get("learn_all_targets_summary")
                if isinstance(evidence.get("learn_all_targets_summary"), dict)
                else {}
            ),
            "review_box_count": len(review_boxes),
        },
    }


def _load_two_stage_report(
    path: str | None,
    *,
    project_root: Path,
) -> dict[str, Any] | None:
    if not _text(path):
        return None
    resolved = _resolve_artifact_file(_text(path), project_root=project_root)
    report = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict):
        raise ValueError("two-stage report must be a JSON object")
    result = dict(report)
    result["source_two_stage_report_path"] = _relative_path(
        resolved,
        project_root=project_root,
    )
    result["attachment_source"] = (
        "panel_run_learning_recognition_trial.two_stage_report_path"
    )
    result["display_only"] = True
    result["artifact_is_authorization"] = False
    result["execute_binding_enabled"] = False
    return result


def _attach_numbered_review_regions(
    observe_bundle: dict[str, Any],
    report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not report:
        return {"attached_count": 0, "reason": "no_two_stage_report_path"}
    source_path = _text(report.get("source_two_stage_report_path"))
    review_regions = _numbered_items_as_review_regions(
        report,
        source_path=source_path,
    )
    if not review_regions:
        _record_review_evidence_summary(
            observe_bundle,
            source_path=source_path,
            attached_count=0,
            skipped_reason="no_numbered_items",
        )
        return {
            "attached_count": 0,
            "reason": "no_numbered_items",
            "source_two_stage_report_path": source_path,
        }
    sources = observe_bundle.setdefault("sources", {})
    if not isinstance(sources, dict):
        sources = {}
        observe_bundle["sources"] = sources
    vision = (
        sources.get("vision")
        if isinstance(sources.get("vision"), dict)
        else {}
    )
    regions = (
        vision.get("regions")
        if isinstance(vision.get("regions"), list)
        else []
    )
    vision["regions"] = [*regions, *review_regions]
    sources["vision"] = vision
    _record_review_evidence_summary(
        observe_bundle,
        source_path=source_path,
        attached_count=len(review_regions),
        skipped_reason="",
    )
    return {
        "attached_count": len(review_regions),
        "reason": "attached_two_stage_numbered_items_as_review_only_regions",
        "source_two_stage_report_path": source_path,
    }


def _numbered_items_as_review_regions(
    report: dict[str, Any],
    *,
    source_path: str,
) -> list[dict[str, Any]]:
    stage2 = (
        report.get("stage2_numbering")
        if isinstance(report.get("stage2_numbering"), dict)
        else {}
    )
    regions = (
        stage2.get("regions")
        if isinstance(stage2.get("regions"), list)
        else []
    )
    output: list[dict[str, Any]] = []
    for region_index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            continue
        parent_id = _text(
            region.get("region_id") or f"stage2_region_{region_index}"
        )
        parent_label = _text(region.get("label") or parent_id)
        items = (
            region.get("numbered_items")
            if isinstance(region.get("numbered_items"), list)
            else []
        )
        for item_index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            bbox = _normalized_bbox(item.get("bbox"))
            label = _text(
                item.get("label")
                or item.get("text")
                or item.get("name")
                or item.get("number")
            )
            if not label or not bbox["w"] or not bbox["h"]:
                continue
            item_id = _text(
                item.get("item_id")
                or item.get("id")
                or item.get("number")
                or f"item_{item_index}"
            )
            output.append(
                {
                    "id": f"two_stage_review_{parent_id}_{item_id}",
                    "region_id": f"two_stage_review_{parent_id}_{item_id}",
                    "label": label,
                    "role": _text(item.get("role") or "review_only"),
                    "bbox": bbox,
                    "description": (
                        f"Stage2 read-only item "
                        f"{item.get('number') or item_index} in {parent_label}"
                    ),
                    "parent_region_id": parent_id,
                    "parent_region_label": parent_label,
                    "stage2_number": _text(item.get("number")),
                    "source": "two_stage_numbered_item_review_only",
                    "source_two_stage_report_path": source_path,
                    "review_only": True,
                    "display_only": True,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                    "no_click_authorization": True,
                    "text_lines": (
                        [
                            _text(line)
                            for line in item.get("text_lines", [])
                            if _text(line)
                        ]
                        if isinstance(item.get("text_lines"), list)
                        else []
                    ),
                }
            )
    return output


def _record_review_evidence_summary(
    observe_bundle: dict[str, Any],
    *,
    source_path: str,
    attached_count: int,
    skipped_reason: str,
) -> None:
    evidence = observe_bundle.get("panel_observation_evidence")
    if not isinstance(evidence, dict):
        evidence = {}
        observe_bundle["panel_observation_evidence"] = evidence
    evidence["two_stage_numbered_review_evidence"] = {
        "contract_version": "panel_two_stage_numbered_review_evidence_v1",
        "source_two_stage_report_path": source_path,
        "attached_count": int(attached_count),
        "skipped_reason": skipped_reason,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "interpretation": (
            "Stage2 numbered items are read-only learning draft evidence. "
            "They are not calibrated targets, click authorization, or "
            "Runtime PathGraph promotion evidence."
        ),
    }


def _fusion_status_from_report(
    report: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not report:
        return None
    fusion_status = (
        report.get("fusion_status")
        if isinstance(report.get("fusion_status"), dict)
        else {}
    )
    if not fusion_status:
        fusion_status = fusion_status_from_two_stage(report)
    result = dict(fusion_status)
    result["source_two_stage_report_path"] = _text(
        report.get("source_two_stage_report_path")
    )
    result["attachment_source"] = (
        "panel_run_learning_recognition_trial.two_stage_report_path"
    )
    result["display_only"] = True
    result["artifact_is_authorization"] = False
    result["execute_binding_enabled"] = False
    stage1 = (
        report.get("stage1_gate")
        if isinstance(report.get("stage1_gate"), dict)
        else {}
    )
    stage2 = (
        report.get("stage2_numbering")
        if isinstance(report.get("stage2_numbering"), dict)
        else {}
    )
    fusion = (
        report.get("fusion")
        if isinstance(report.get("fusion"), dict)
        else {}
    )
    review_boxes = (
        fusion.get("fused_review_boxes")
        if isinstance(fusion.get("fused_review_boxes"), list)
        else []
    )
    summary = (
        result.get("summary")
        if isinstance(result.get("summary"), dict)
        else {}
    )
    result["stage1_gate_status"] = _text(stage1.get("status"))
    result["stage2_numbering_skipped"] = bool(
        report.get("stage2_numbering_skipped")
    )
    result["review_box_count"] = len(review_boxes) or _int_or_zero(
        summary.get("fused_review_box_count")
    )
    result["stage2_numbered_region_count"] = len(
        stage2.get("regions")
        if isinstance(stage2.get("regions"), list)
        else []
    )
    return result


def _attach_current_calibrated_overlay(
    fusion_status: dict[str, Any],
    observation_evidence: dict[str, Any],
    *,
    project_root: Path,
) -> dict[str, Any]:
    result = dict(fusion_status)
    evidence = (
        observation_evidence
        if isinstance(observation_evidence, dict)
        else {}
    )
    overlay = (
        evidence.get("coordinate_overlay")
        if isinstance(evidence.get("coordinate_overlay"), dict)
        else {}
    )
    summary = (
        evidence.get("learn_all_targets_summary")
        if isinstance(evidence.get("learn_all_targets_summary"), dict)
        else {}
    )
    qualifies = (
        _text(result.get("stage1_gate_status")) == "passed"
        and overlay.get("status") == "ready"
        and overlay.get("base_visual_source") == "two_stage_numbered_overlay"
        and overlay.get("final_fusion_overlay") is True
        and summary.get("coordinate_calibration_status")
        == "model_validation_completed"
        and _int_or_zero(summary.get("calibration_target_count")) > 0
        and _int_or_zero(summary.get("vista_validated_count")) > 0
    )
    overlay_value = _text(evidence.get("coordinate_overlay_path"))
    if not qualifies or not overlay_value:
        return result
    overlay_path = _resolve_artifact_file(
        overlay_value,
        project_root=project_root,
    )
    relative_overlay = _relative_path(
        overlay_path,
        project_root=project_root,
    )
    previous_compiled = _text(result.get("compiled_overlay_path"))
    previous_full = _text(
        result.get("full_screen_understanding_overlay_path")
    )
    result.update(
        {
            "stage2_compiled_overlay_path": previous_compiled or previous_full,
            "stage2_full_screen_understanding_overlay_path": (
                previous_full or previous_compiled
            ),
            "calibration_overlay_path": relative_overlay,
            "precise_calibration_overlay_path": relative_overlay,
            "compiled_overlay_path": relative_overlay,
            "full_screen_understanding_overlay_path": relative_overlay,
            "display_overlay_source": "two_stage_plus_precise_calibration",
            "final_fusion_overlay": True,
            "calibration_evidence_status": "model_validation_completed",
        }
    )
    return result


def _attach_fusion_status_to_result(
    result: dict[str, Any],
    fusion_status: dict[str, Any],
) -> None:
    draft = (
        result.get("learning_draft")
        if isinstance(result.get("learning_draft"), dict)
        else {}
    )
    if not draft:
        return
    page_details = (
        draft.get("page_details")
        if isinstance(draft.get("page_details"), dict)
        else {}
    )
    pipeline_audit = (
        page_details.get("pipeline_audit")
        if isinstance(page_details.get("pipeline_audit"), dict)
        else {}
    )
    current_status = (
        pipeline_audit.get("precise_understanding_fusion_status")
        if isinstance(
            pipeline_audit.get("precise_understanding_fusion_status"),
            dict,
        )
        else {}
    )
    attached = dict(fusion_status)
    current_values = {
        key: value
        for key, value in current_status.items()
        if value not in (None, "", [], {})
    }
    if attached.get("final_fusion_overlay") is True:
        final_overlay_keys = {
            "compiled_overlay_path",
            "full_screen_understanding_overlay_path",
            "calibration_overlay_path",
            "precise_calibration_overlay_path",
            "stage2_compiled_overlay_path",
            "stage2_full_screen_understanding_overlay_path",
            "display_overlay_source",
            "final_fusion_overlay",
            "calibration_evidence_status",
        }
        attached.update(
            {
                key: value
                for key, value in current_values.items()
                if key not in final_overlay_keys or key not in attached
            }
        )
    else:
        attached.update(current_values)
    pipeline_audit["precise_understanding_fusion_status"] = attached
    page_details["pipeline_audit"] = pipeline_audit
    if attached.get("compiled_overlay_path"):
        page_details["compiled_overlay_path"] = attached.get(
            "compiled_overlay_path"
        )
    if attached.get("full_screen_understanding_overlay_path"):
        page_details["full_screen_understanding_overlay_path"] = attached.get(
            "full_screen_understanding_overlay_path"
        )
    draft["page_details"] = page_details
    result["learning_draft"] = draft


def _precise_understanding_status(
    fusion_status: dict[str, Any] | None,
) -> str:
    if not fusion_status:
        return "not_attached"
    if (
        fusion_status.get("stage1_gate_status")
        == "blocked_before_stage2_numbering"
    ):
        return "review_overlay_attached_stage1_blocked"
    if (
        _int_or_zero(fusion_status.get("review_box_count"))
        or fusion_status.get("compiled_overlay_path")
    ):
        return "review_overlay_attached"
    return "attached_without_review_overlay"


def _review_box_status(
    *,
    two_stage_review_evidence: dict[str, Any],
    fusion_status: dict[str, Any] | None,
) -> dict[str, Any]:
    attached_count = _int_or_zero(
        two_stage_review_evidence.get("attached_count")
    )
    fusion = fusion_status if isinstance(fusion_status, dict) else {}
    summary = (
        fusion.get("summary")
        if isinstance(fusion.get("summary"), dict)
        else {}
    )
    review_box_count = max(
        attached_count,
        _int_or_zero(fusion.get("review_box_count")),
        _int_or_zero(summary.get("fused_review_box_count")),
    )
    numbered_region_count = _int_or_zero(
        fusion.get("stage2_numbered_region_count")
    )
    stage1_gate_status = _text(fusion.get("stage1_gate_status"))
    if stage1_gate_status == "blocked_before_stage2_numbering":
        status = "blocked_before_stage2_numbering"
    elif review_box_count or numbered_region_count:
        status = "review_boxes_ready"
    else:
        status = "empty"
    return {
        "contract_version": "panel_learning_review_box_status_v1",
        "status": status,
        "target_count": 0,
        "validated_count": 0,
        "invalid_count": 0,
        "review_box_count": review_box_count,
        "stage1_gate_status": stage1_gate_status,
        "stage2_numbered_region_count": numbered_region_count,
        "source_two_stage_report_path": _text(
            fusion.get("source_two_stage_report_path")
        ),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "no_click_authorization": True,
        "interpretation": (
            "review boxes are learning-draft display evidence only; "
            "target_count remains zero until separate grounding evidence "
            "creates executable candidates"
        ),
    }


def _model_provenance(
    observe_bundle: dict[str, Any],
    *,
    project_root: Path,
) -> dict[str, Any]:
    observation = (
        observe_bundle.get("panel_observation_evidence")
        if isinstance(observe_bundle.get("panel_observation_evidence"), dict)
        else {}
    )
    model_roles = (
        observation.get("model_roles")
        if isinstance(observation.get("model_roles"), dict)
        else {}
    )
    evidence: list[dict[str, Any]] = []
    for role, role_data in model_roles.items():
        if not isinstance(role_data, dict):
            continue
        trace_value = _text(role_data.get("trace_path"))
        entry: dict[str, Any] = {
            "role": _text(role),
            "model_profile_id": _text(role_data.get("model_profile_id")),
            "trace_path": trace_value,
            "actual_model_call_in_this_run": False,
        }
        if not trace_value:
            entry["reason"] = "trace_path_missing"
            evidence.append(entry)
            continue
        try:
            trace_path = _resolve_artifact_file(
                trace_value,
                project_root=project_root,
            )
            trace_payload = json.loads(
                trace_path.read_text(encoding="utf-8-sig")
            )
        except (
            FileNotFoundError,
            ValueError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            entry["reason"] = f"trace_unavailable:{type(exc).__name__}"
            evidence.append(entry)
            continue
        trace_result = (
            trace_payload.get("result")
            if isinstance(trace_payload, dict)
            and isinstance(trace_payload.get("result"), dict)
            else {}
        )
        model_io = (
            trace_result.get("model_io")
            if isinstance(trace_result.get("model_io"), dict)
            else {}
        )
        targets = (
            trace_result.get("learn_all_targets")
            if isinstance(trace_result.get("learn_all_targets"), dict)
            else {}
        )
        vista = (
            targets.get("vista_coordinate_validation")
            if isinstance(targets.get("vista_coordinate_validation"), dict)
            else {}
        )
        qwen_actual = (
            trace_payload.get("success") is True
            and model_io.get("status") == "success"
            and bool(_text(model_io.get("raw_text")))
        )
        vista_results = (
            vista.get("results")
            if isinstance(vista.get("results"), list)
            else []
        )
        vista_attempted = _int_or_zero(vista.get("attempted_count"))
        vista_actual = (
            trace_payload.get("success") is True
            and vista.get("status") == "ready"
            and vista_attempted > 0
            and any(
                isinstance(item, dict)
                and isinstance(item.get("vista_point"), dict)
                for item in vista_results
            )
        )
        if qwen_actual:
            entry.update(
                {
                    "actual_model_call_in_this_run": True,
                    "evidence_type": "screen_understanding_model_io",
                    "provider": _text(model_io.get("provider")),
                    "model_name": _text(model_io.get("model_name")),
                    "status": _text(model_io.get("status")),
                }
            )
        elif vista_actual:
            entry.update(
                {
                    "actual_model_call_in_this_run": True,
                    "evidence_type": "vista_point_grounding_batch",
                    "provider": "local_grounding",
                    "model_name": _text(vista.get("model_name")),
                    "status": _text(vista.get("status")),
                    "attempted_count": vista_attempted,
                    "validated_count": _int_or_zero(
                        vista.get("validated_count")
                    ),
                }
            )
        else:
            entry["reason"] = "trace_does_not_prove_model_inference"
        entry["trace_path"] = _relative_path(
            trace_path,
            project_root=project_root,
        )
        evidence.append(entry)
    actual_count = sum(
        1
        for item in evidence
        if item.get("actual_model_call_in_this_run") is True
    )
    return {
        "contract_version": "panel_learning_model_provenance_v1",
        "source_type": "mixed" if actual_count else "fixture_only",
        "actual_model_call_evidence_count": actual_count,
        "evidence": evidence,
        "counts_as_pure_model_generated": False,
        "interpretation": (
            "Verified model traces prove inference occurred in this panel run. "
            "The saved learning draft also includes OCR, UIA, calibration, "
            "and deterministic rules, so it is mixed rather than pure model output."
        ),
    }


def _calibrated_target_grounding(
    *,
    item: dict[str, Any],
    roi_crop: dict[str, Any],
) -> dict[str, Any]:
    metadata = (
        item.get("metadata")
        if isinstance(item.get("metadata"), dict)
        else {}
    )
    layout_cleanup = (
        metadata.get("layout_cleanup")
        if isinstance(metadata.get("layout_cleanup"), dict)
        else {}
    )
    merged_support = (
        layout_cleanup.get("merged_support")
        if isinstance(layout_cleanup.get("merged_support"), dict)
        else {}
    )
    if isinstance(metadata.get("click_point"), dict):
        point = metadata["click_point"]
        point_source = "metadata.click_point"
        coordinate_source = metadata.get("coordinate_source")
    elif isinstance(merged_support.get("click_point"), dict):
        point = merged_support["click_point"]
        point_source = "layout_cleanup.merged_support.click_point"
        coordinate_source = merged_support.get("coordinate_source")
    else:
        point = {}
        point_source = "missing"
        coordinate_source = ""
    return {
        "screen_point": _normalized_point(point) if point else {},
        "screen_bbox": (
            item.get("bbox")
            if isinstance(item.get("bbox"), dict)
            else {}
        ),
        "evidence": {
            "coordinate_transform_replay": True,
            "screenshot_freshness": True,
            "uia_or_dom_or_parser_overlap": True,
            "ocr_anchor_overlap": True,
        },
        "debug": {
            "adapter": "panel_calibrated_target_replay",
            "roi_contract": roi_crop.get("contract_version"),
            "point_source": point_source,
            "coordinate_source": _text(coordinate_source),
        },
    }


def _attach_provider_summary_to_draft(
    result: dict[str, Any],
    provider_summary: dict[str, Any],
) -> None:
    """保留只读摘要，使加载后的草稿审阅仍可显示 provider 状态。"""
    draft = result.get("learning_draft")
    if not isinstance(draft, dict):
        return
    page_details = (
        deepcopy(draft.get("page_details"))
        if isinstance(draft.get("page_details"), dict)
        else {}
    )
    page_details["provider_summary"] = deepcopy(provider_summary)
    draft["page_details"] = page_details


def _omniparser_provider_summary(
    *,
    observe_bundle: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """将 OmniParser 证据压缩为稳定的只读面板状态，绝不授予执行权限。"""
    sources = (
        observe_bundle.get("sources")
        if isinstance(observe_bundle.get("sources"), dict)
        else {}
    )
    provider_result = (
        sources.get("omniparser")
        if isinstance(sources.get("omniparser"), dict)
        else {}
    )
    elements = (
        provider_result.get("elements")
        if isinstance(provider_result.get("elements"), list)
        else []
    )
    profile_id = _text(provider_result.get("profile_id"))
    model_revision = _text(provider_result.get("model_revision"))
    capture_id = _text(provider_result.get("capture_id"))
    source_run_id = _text(provider_result.get("source_run_id"))
    screenshot_sha256 = _text(provider_result.get("screenshot_sha256"))
    image_size = (
        provider_result.get("image_size")
        if isinstance(provider_result.get("image_size"), dict)
        else {}
    )
    coordinate_space = _text(provider_result.get("coordinate_space"))
    warnings: list[str] = []
    if not provider_result:
        warnings.append("provider_result_unavailable")
    if provider_result and provider_result.get("contract_version") != "screen_parser_result_v1":
        warnings.append("provider_contract_invalid")
    for field, value in (
        ("profile_id", profile_id),
        ("model_revision", model_revision),
        ("capture_id", capture_id),
        ("source_run_id", source_run_id),
        ("screenshot_sha256", screenshot_sha256),
    ):
        if not value:
            warnings.append(f"missing_{field}")
    if (
        _positive_int(image_size.get("width")) <= 0
        or _positive_int(image_size.get("height")) <= 0
    ):
        warnings.append("invalid_image_size")
    if coordinate_space not in {"image_normalized_xyxy", "image_pixel_xyxy"}:
        warnings.append("invalid_coordinate_space")

    invalid_bbox_count = sum(
        not _valid_provider_bbox(
            item.get("bbox") if isinstance(item, dict) else None,
            image_size=image_size,
            coordinate_space=coordinate_space,
        )
        for item in elements
    )
    if invalid_bbox_count:
        warnings.append("invalid_element_bbox")
    grounding_eligible_count = min(
        len(elements),
        sum(
            1
            for item in _classification_items(result, "accepted_for_grounding")
            if _has_omniparser_source(item)
        ),
    )
    provider_error = (
        deepcopy(provider_result.get("error"))
        if isinstance(provider_result.get("error"), dict)
        else None
    )
    return {
        "contract_version": "learning_recognition_provider_summary_v1",
        "provider": _text(provider_result.get("provider")) or "omniparser",
        "provider_status": _text(provider_result.get("status")) or "not_available",
        "profile_id": profile_id,
        "model_revision": model_revision,
        "capture_id_present": bool(capture_id),
        "screenshot_sha256_present": bool(screenshot_sha256),
        "source_run_id_present": bool(source_run_id),
        "element_total": len(elements),
        "interactive_evidence_count": sum(
            1
            for item in elements
            if isinstance(item, dict) and bool(item.get("interactivity"))
        ),
        "grounding_eligible_count": grounding_eligible_count,
        "review_only_count": max(len(elements) - grounding_eligible_count, 0),
        "invalid_bbox_count": invalid_bbox_count,
        "lineage_complete": not warnings,
        "lineage_warnings": warnings,
        "provider_error": provider_error,
        "execution_authorized": False,
    }


def _classification_items(result: dict[str, Any], field: str) -> list[dict[str, Any]]:
    classification = (
        result.get("classification")
        if isinstance(result.get("classification"), dict)
        else {}
    )
    items = (
        classification.get(field)
        if isinstance(classification.get(field), list)
        else []
    )
    return [item for item in items if isinstance(item, dict)]


def _has_omniparser_source(item: dict[str, Any]) -> bool:
    sources = item.get("source_evidence")
    return isinstance(sources, list) and any(
        _text(source).casefold() == "omniparser" for source in sources
    )


def _positive_int(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _valid_provider_bbox(
    bbox: Any,
    *,
    image_size: dict[str, Any],
    coordinate_space: str,
) -> bool:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    try:
        x1, y1, x2, y2 = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
        return False
    max_x = (
        1.0
        if coordinate_space == "image_normalized_xyxy"
        else float(_positive_int(image_size.get("width")))
    )
    max_y = (
        1.0
        if coordinate_space == "image_normalized_xyxy"
        else float(_positive_int(image_size.get("height")))
    )
    return 0.0 <= x1 < x2 <= max_x and 0.0 <= y1 < y2 <= max_y


def _recognition_summary(evidence: dict[str, Any]) -> str:
    if not isinstance(evidence, dict):
        return ""
    screen_map = (
        evidence.get("screen_map")
        if isinstance(evidence.get("screen_map"), dict)
        else {}
    )
    summary = (
        screen_map.get("summary")
        if isinstance(screen_map.get("summary"), dict)
        else {}
    )
    return _text(
        evidence.get("screen_summary")
        or summary.get("screen_summary")
        or screen_map.get("state_hint")
        or evidence.get("goal")
    )


def _draft_section_counts(draft: Any) -> dict[str, int]:
    if not isinstance(draft, dict):
        return {
            "states": 0,
            "regions": 0,
            "action_templates": 0,
            "blockers": 0,
            "verification_rules": 0,
        }
    workflow = (
        draft.get("workflow_draft")
        if isinstance(draft.get("workflow_draft"), dict)
        else {}
    )
    interface = (
        draft.get("interface_draft")
        if isinstance(draft.get("interface_draft"), dict)
        else {}
    )
    return {
        "states": len(workflow.get("states") or draft.get("states") or []),
        "regions": len(
            interface.get("regions") or draft.get("regions") or []
        ),
        "action_templates": len(
            workflow.get("action_templates")
            or draft.get("action_templates")
            or []
        ),
        "blockers": len(draft.get("blockers") or []),
        "verification_rules": len(
            workflow.get("verification_rules")
            or draft.get("verification_rules")
            or []
        ),
    }


def _normalized_calibrated_targets(value: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, target in enumerate(value if isinstance(value, list) else []):
        if not isinstance(target, dict):
            continue
        item = dict(target)
        item.setdefault(
            "candidate_id",
            item.get("item_id") or item.get("id") or f"panel_target_{index + 1}",
        )
        item.setdefault(
            "role",
            item.get("semantic_action") or item.get("type") or "actionable",
        )
        bbox = _normalized_bbox(item.get("bbox"))
        point = _normalized_point(item.get("click_point"))
        item["bbox"] = bbox
        item["click_point"] = point
        validation = (
            item.get("coordinate_validation")
            if isinstance(item.get("coordinate_validation"), dict)
            else {}
        )
        if not validation:
            status = _text(
                item.get("coordinate_validation_status")
                or item.get("vista_status")
                or "valid"
            )
            validation = {
                "status": status or "valid",
                "bbox_present": bool(bbox["w"] and bbox["h"]),
                "click_point_present": point != {"x": 0, "y": 0},
                "bbox_inside_image": True,
                "click_point_inside_image": True,
                "click_point_inside_bbox": _point_inside_bbox(point, bbox),
            }
        item["coordinate_validation"] = validation
        output.append(item)
    return output


def _normalized_review_boxes(value: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, box in enumerate(value if isinstance(value, list) else []):
        if not isinstance(box, dict):
            continue
        bbox = _normalized_bbox(box.get("bbox"))
        label = _text(box.get("label") or box.get("text") or box.get("name"))
        if not label or not bbox["w"] or not bbox["h"]:
            continue
        output.append(
            {
                "id": _text(
                    box.get("candidate_id")
                    or box.get("item_id")
                    or box.get("id")
                    or f"review_box_{index + 1}"
                ),
                "text": label,
                "label": label,
                "role": _text(box.get("role") or "review_only"),
                "bbox": bbox,
                "confidence": box.get("confidence"),
                "source": _text(
                    box.get("source") or "learn_all_targets.review_boxes"
                ),
                "review_status": _text(
                    box.get("review_status") or "review_only"
                ),
                "children": (
                    box.get("children")
                    if isinstance(box.get("children"), list)
                    else []
                ),
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return output


def _resolve_artifact_file(path: str, *, project_root: Path) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = project_root / resolved
    resolved = resolved.resolve()
    allowed_roots = [
        (project_root / "artifacts").resolve(),
        (project_root / "logs").resolve(),
    ]
    if not any(
        resolved == allowed or allowed in resolved.parents
        for allowed in allowed_roots
    ):
        raise ValueError(str(resolved))
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved


def _relative_path(path: Path, *, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace(
            "\\",
            "/",
        )
    except ValueError:
        return str(path).replace("\\", "/")


def _safe_slug(value: Any) -> str:
    text = str(value or "unknown_app").strip().lower()
    cleaned = "".join(
        character
        if character.isalnum() or character in "_.-"
        else "_"
        for character in text
    )
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned[:80] or "unknown_app"


def _normalized_bbox(value: Any) -> dict[str, int]:
    item = value if isinstance(value, dict) else {}
    return {
        "x": _int_or_zero(item.get("x")),
        "y": _int_or_zero(item.get("y")),
        "w": max(
            0,
            _int_or_zero(
                item.get("w") if "w" in item else item.get("width")
            ),
        ),
        "h": max(
            0,
            _int_or_zero(
                item.get("h") if "h" in item else item.get("height")
            ),
        ),
    }


def _normalized_point(value: Any) -> dict[str, int]:
    item = value if isinstance(value, dict) else {}
    return {
        "x": _int_or_zero(item.get("x")),
        "y": _int_or_zero(item.get("y")),
    }


def _point_inside_bbox(
    point: dict[str, int],
    bbox: dict[str, int],
) -> bool:
    return (
        bbox["x"] <= point["x"] <= bbox["x"] + bbox["w"]
        and bbox["y"] <= point["y"] <= bbox["y"] + bbox["h"]
    )


def _first_dict(*values: Any) -> dict[str, Any]:
    return next((value for value in values if isinstance(value, dict)), {})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
