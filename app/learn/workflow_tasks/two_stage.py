from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from app.core.runtime_artifacts import write_trace
from app.learn.recognition import (
    build_inventory_layout_graph,
    build_two_stage_screen_understanding,
    fusion_status_from_two_stage,
    model_grounding_evidence_status_from_two_stage,
)
from app.learn.recognition.trace_input import (
    observe_bundle_from_trace_result,
    stage1_inventory_from_trace_result,
)
from app.learn.surface_rule_registry import load_active_surface_rules
from app.learn.workflow_contracts import (
    LearningTaskFailure,
    LearningTaskResult,
    TwoStageUnderstandingTaskInput,
)
from app.learn.workflow_tasks.recognition import save_recognition_trial

ObserveBundleBuilder = Callable[..., dict[str, Any]]
InventoryBuilder = Callable[[dict[str, Any]], list[dict[str, Any]]]
LayoutBuilder = Callable[..., dict[str, Any]]
TwoStageBuilder = Callable[..., dict[str, Any]]
ReportStatusBuilder = Callable[[dict[str, Any]], dict[str, Any]]
SurfaceRulesLoader = Callable[..., list[dict[str, Any]]]
ReportSaver = Callable[..., str]
TraceWriter = Callable[..., str]


def run_two_stage_understanding_task(
    task_input: TwoStageUnderstandingTaskInput,
    *,
    project_root: Path,
    observe_bundle_builder: ObserveBundleBuilder = (
        observe_bundle_from_trace_result
    ),
    inventory_builder: InventoryBuilder = stage1_inventory_from_trace_result,
    layout_builder: LayoutBuilder = build_inventory_layout_graph,
    two_stage_builder: TwoStageBuilder = build_two_stage_screen_understanding,
    fusion_status_builder: ReportStatusBuilder = fusion_status_from_two_stage,
    grounding_evidence_builder: ReportStatusBuilder = (
        model_grounding_evidence_status_from_two_stage
    ),
    surface_rules_loader: SurfaceRulesLoader = load_active_surface_rules,
    report_saver: ReportSaver = save_recognition_trial,
    trace_writer: TraceWriter = write_trace,
) -> LearningTaskResult:
    """运行只读两阶段理解任务，不授予真实动作权限。"""

    root = project_root.resolve()
    try:
        observe_result, source_trace_path = _two_stage_observe_result(
            task_input,
            project_root=root,
        )
        bundle = observe_bundle_builder(
            observe_result,
            trace_path=source_trace_path,
        )
        bundle["app_name"] = task_input.app_name
        bundle["state_hint"] = task_input.state_hint
        source_image_override = _apply_source_image_override(
            bundle,
            task_input.source_image_path,
            project_root=root,
        )
        screen_inventory = inventory_builder(observe_result)
        layout_graph = layout_builder(
            screen_inventory,
            screen_size=bundle.get("screen_size"),
        )
        report = two_stage_builder(
            bundle=bundle,
            screen_inventory=screen_inventory,
            layout_graph=layout_graph,
            require_stage1_gate=task_input.require_stage1_gate,
            stage2_region_strategy=task_input.stage2_region_strategy,
            enable_ocr_content_recovery=True,
            active_surface_rules=surface_rules_loader(project_root=root),
        )
        report["source_trace_path"] = str(source_trace_path)
        report["source_image_override"] = source_image_override
        report["screen_inventory_count"] = len(screen_inventory)
        report["layout_graph_summary"] = {
            "node_count": layout_graph.get("node_count"),
            "zone_count": layout_graph.get("zone_count"),
            "zones": {
                zone_id: len(
                    zone.get("item_ids")
                    if isinstance(zone, dict)
                    and isinstance(zone.get("item_ids"), list)
                    else []
                )
                for zone_id, zone in (
                    layout_graph.get("zones")
                    if isinstance(layout_graph.get("zones"), dict)
                    else {}
                ).items()
            },
        }
        report["fusion_status"] = fusion_status_builder(report)
        report["model_grounding_evidence"] = grounding_evidence_builder(report)

        fusion = (
            report.get("fusion")
            if isinstance(report.get("fusion"), dict)
            else {}
        )
        stage1_gate = (
            report.get("stage1_gate")
            if isinstance(report.get("stage1_gate"), dict)
            else {}
        )
        review_boxes = (
            fusion.get("fused_review_boxes")
            if isinstance(fusion.get("fused_review_boxes"), list)
            else []
        )
        overlay_path = _text(
            fusion.get("compiled_overlay_path")
            or fusion.get("full_screen_understanding_overlay_path")
            or report.get("overlay_path")
        )
        stage2 = (
            report.get("stage2_numbering")
            if isinstance(report.get("stage2_numbering"), dict)
            else {}
        )
        numbered_regions = (
            stage2.get("regions")
            if isinstance(stage2.get("regions"), list)
            else []
        )
        learn_all_targets = {
            "status": (
                "two_stage_stage1_gate_passed"
                if stage1_gate.get("status") == "passed"
                else "blocked_before_stage2_numbering"
            ),
            "targets": [],
            "target_count": 0,
            "validated_count": 0,
            "invalid_count": 0,
            "review_boxes": review_boxes,
            "review_box_count": len(review_boxes),
            "overlay_path": overlay_path,
            "trace_path": "",
            "stage1_gate_status": stage1_gate.get("status"),
            "stage2_numbered_region_count": len(numbered_regions),
            "stage2_calibration_candidate_count": _int_or_zero(
                stage2.get("calibration_candidate_count")
            ),
        }
        saved_payload = {
            **report,
            "app_name": task_input.app_name,
            "state_hint": task_input.state_hint,
            "artifact_type": "learn_two_stage_understanding",
            "draft_only": True,
            "draft_graph_preview": True,
            "runtime_path_graph": False,
            "promotion_allowed": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks": 0,
            "live_safe_fill_attempted": 0,
            "final_submit_forbidden": True,
            "source_type": "panel_live_observe_two_stage_understanding",
            "observe_bundle": bundle,
            "source_image_override": source_image_override,
            "learn_all_targets": learn_all_targets,
        }
        report_path = report_saver(
            saved_payload,
            app_name=task_input.app_name,
            project_root=root,
        )
        trace_path = trace_writer(
            category="panel",
            operation="run-learning-two-stage-understanding",
            payload={
                "success": True,
                "request": task_input.model_dump(mode="json"),
                "result": {
                    "report_path": report_path,
                    "overlay_path": overlay_path,
                    "stage1_gate_status": stage1_gate.get("status"),
                    "stage1_source": report.get("stage1_source"),
                    "stage2_numbering_skipped": bool(
                        report.get("stage2_numbering_skipped")
                    ),
                    "review_box_count": len(review_boxes),
                    "real_clicks": 0,
                    "promotion_allowed": False,
                },
            },
            name_hint="learning_two_stage_understanding",
        )
        learn_all_targets["trace_path"] = trace_path
        payload = {
            "contract_version": (
                "panel_learning_two_stage_understanding_run_v1"
            ),
            "artifact_type": "learn_two_stage_understanding",
            "draft_only": True,
            "draft_graph_preview": True,
            "runtime_path_graph": False,
            "report_path": report_path,
            "trace_path": trace_path,
            "source_trace_path": str(source_trace_path),
            "source_image_override": source_image_override,
            "status": stage1_gate.get("status") or "unknown",
            "stage1_gate": stage1_gate,
            "stage1_gate_required": bool(task_input.require_stage1_gate),
            "stage1_source": report.get("stage1_source"),
            "stage2_numbering_skipped": bool(
                report.get("stage2_numbering_skipped")
            ),
            "fusion_status": report.get("fusion_status"),
            "model_grounding_evidence": report.get(
                "model_grounding_evidence"
            ),
            "coordinate_overlay_path": overlay_path,
            "full_screen_understanding_overlay_path": overlay_path,
            "image_path": (
                bundle.get("image_path") or bundle.get("source_image_path")
            ),
            "screen_size": bundle.get("screen_size") or {},
            "screen_summary": (
                (bundle.get("screen_reading") or {}).get("screen_summary")
                if isinstance(bundle.get("screen_reading"), dict)
                else ""
            ),
            "learn_all_targets": learn_all_targets,
            "summary": {
                "app_name": task_input.app_name,
                "state_hint": task_input.state_hint,
                "screen_inventory_count": len(screen_inventory),
                "stage2_numbered_item_count": _int_or_zero(
                    stage2.get("numbered_item_count")
                ),
                "stage2_calibration_candidate_count": _int_or_zero(
                    stage2.get("calibration_candidate_count")
                ),
                "review_box_count": len(review_boxes),
                "stage1_gate_status": stage1_gate.get("status"),
                "stage1_source": report.get("stage1_source"),
                "stage1_failure_categories": (
                    stage1_gate.get("failure_categories")
                    if isinstance(
                        stage1_gate.get("failure_categories"),
                        list,
                    )
                    else []
                ),
                "stage2_numbering_skipped": bool(
                    report.get("stage2_numbering_skipped")
                ),
                "overlay_path": overlay_path,
                "model_grounding_evidence_status": (
                    report.get("model_grounding_evidence", {}).get("status")
                    if isinstance(
                        report.get("model_grounding_evidence"),
                        dict,
                    )
                    else "unknown"
                ),
            },
            "promotion_allowed": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks": 0,
            "live_safe_fill_attempted": 0,
            "final_submit_forbidden": True,
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
                code="learning_two_stage_understanding_failed",
                details=str(exc),
            ),
        )


def _two_stage_observe_result(
    task_input: TwoStageUnderstandingTaskInput,
    *,
    project_root: Path,
) -> tuple[dict[str, Any], Path]:
    if _text(task_input.trace_path):
        trace_path = _resolve_artifact_file(
            _text(task_input.trace_path),
            project_root=project_root,
        )
        trace = json.loads(trace_path.read_text(encoding="utf-8-sig"))
        result = (
            trace.get("result")
            if isinstance(trace, dict)
            and isinstance(trace.get("result"), dict)
            else trace
        )
        if not isinstance(result, dict):
            raise ValueError("trace does not contain a dict result")
        return result, trace_path

    result = (
        task_input.observe_result
        if isinstance(task_input.observe_result, dict)
        else {}
    )
    if isinstance(result.get("data"), dict):
        result = result["data"]
    if isinstance(result.get("result"), dict) and not result.get("image_path"):
        result = result["result"]
    if not result:
        raise ValueError("observe_result or trace_path is required")
    source_trace = _text(
        result.get("trace_path")
        or result.get("source_trace_path")
        or "panel_inline_observe_result.json"
    )
    return result, Path(source_trace)


def _apply_source_image_override(
    bundle: dict[str, Any],
    source_image_path: str | None,
    *,
    project_root: Path,
) -> dict[str, Any]:
    override_text = _text(source_image_path)
    if not override_text:
        return {"applied": False, "reason": "not_requested"}
    resolved = _resolve_artifact_file(
        override_text,
        project_root=project_root,
    )
    original_path = _text(
        bundle.get("image_path") or bundle.get("source_image_path")
    )
    bundle["image_path"] = str(resolved)
    bundle["source_image_path"] = str(resolved)
    try:
        with Image.open(resolved) as image:
            size = {"width": int(image.width), "height": int(image.height)}
            bundle["screen_size"] = size
            bundle["image_size"] = size
    except Exception as exc:
        return {
            "applied": True,
            "status": "image_size_unreadable",
            "reason": str(exc),
            "original_path": original_path,
            "path": str(resolved),
        }
    return {
        "applied": True,
        "status": "applied",
        "reason": "explicit_source_image_override",
        "original_path": original_path,
        "path": str(resolved),
    }


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


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
