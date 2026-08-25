from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.model_server import _profile_for_qwen_model_lease, profile_for_stage
from app.learn.hierarchy_draft import build_hierarchy_learning_draft
from app.learn.recognition.review_finalization import finalize_reviewed_stage2_for_calibration
from app.learn.recognition.two_stage import _fusion_boxes, summarize_stage2_calibration_partition
from app.learn.ui_hierarchy import build_ui_hierarchy_graph
from scripts.run_learning_overlay_model_review_probe import run_probe
from scripts.run_learning_review_repair_closure import run_closure


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_panel_learning_model_review_repair(
    *,
    two_stage_report_path: Path,
    screenshot_path: Path,
    composite_overlay_path: Path,
    model_profile_id: str,
    timeout_seconds: float,
    managed_model_lease: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """调用统一复核、修复和最终编号闭环，供面板与测试共同使用。"""

    source_report_path = _resolve_existing(two_stage_report_path)
    screenshot = _resolve_existing(screenshot_path)
    composite_overlay = _resolve_existing(composite_overlay_path)
    profile = (
        _profile_for_qwen_model_lease(managed_model_lease)
        if managed_model_lease is not None
        else profile_for_stage("observe", model_profile_id)
    )
    endpoint = str(profile.get("endpoint") or "").strip()
    model_name = str(profile.get("model_name") or profile.get("model_id") or "").strip()
    if not endpoint or not model_name:
        raise ValueError(f"model profile lacks endpoint or model name: {model_profile_id}")

    source_report = _read_json(source_report_path)
    source_stage2 = _extract_stage2(source_report)
    run_dir = _panel_run_dir(source_report_path, screenshot)
    review_dir = run_dir / "model_review"
    review_report = run_probe(
        stage2_json_path=source_report_path,
        out_dir=review_dir,
        overlay_path=composite_overlay,
        screenshot_path=screenshot,
        endpoint=endpoint,
        model_name=model_name,
        timeout_seconds=timeout_seconds,
        managed_model_lease=managed_model_lease,
    )
    closure_path = run_dir / "repair_closure" / "learning_review_repair_closure_report.json"
    closure = run_closure(
        stage2_source_path=source_report_path,
        validated_patch_path=Path(review_report["validated_review_patch_path"]),
        screenshot_path=str(screenshot),
        out_path=closure_path,
    )
    final_workflow = closure.get("final_workflow") if isinstance(closure.get("final_workflow"), dict) else {}
    recomposed_stage2 = (
        final_workflow.get("recomposed_stage2")
        if isinstance(final_workflow.get("recomposed_stage2"), dict)
        else {}
    )
    replacement_gate = (
        final_workflow.get("replacement_integrity_gate")
        if isinstance(final_workflow.get("replacement_integrity_gate"), dict)
        else {"passed": False, "failure_categories": ["replacement_integrity_gate_missing"]}
    )
    finalization = finalize_reviewed_stage2_for_calibration(
        source_stage2=source_stage2,
        recomposed_stage2=recomposed_stage2,
        screenshot_path=screenshot,
        expected_capture_sha256=str(review_report.get("input_capture_sha256") or ""),
        workflow_state=str(final_workflow.get("workflow_state") or closure.get("workflow_state") or ""),
        replacement_integrity_gate=replacement_gate,
        repair_pending_count=int(final_workflow.get("repair_pending_count") or 0),
    )
    final_overlay_path = str(closure.get("final_repaired_overlay_path") or "").strip()
    final_stage2_report_path = run_dir / "final_stage2_for_calibration.json"
    final_stage2_report = _final_stage2_report(
        source_report=source_report,
        finalized_stage2=finalization["finalized_stage2"],
        screenshot_path=screenshot,
        final_overlay_path=final_overlay_path,
        finalization=finalization,
        model_review_report_path=Path(review_report["report_path"]),
        closure_report_path=closure_path,
    )
    _write_json(final_stage2_report_path, final_stage2_report)

    calibration_permission = bool(finalization["calibration_permission"])
    final_partition = summarize_stage2_calibration_partition(finalization["finalized_stage2"])
    result = {
        "contract_version": "panel_learning_model_review_repair_result_v1",
        "status": "ready_for_calibration" if calibration_permission else "safe_stop",
        "calibration_permission": calibration_permission,
        "two_stage_report_path": str(source_report_path),
        "model_review_report_path": str(Path(review_report["report_path"]).resolve()),
        "repair_closure_report_path": str(closure_path.resolve()),
        "final_stage2_report_path": str(final_stage2_report_path.resolve()),
        "final_repaired_overlay_path": final_overlay_path,
        "source_graph_revision": finalization["source_graph_revision"],
        "reviewed_graph_revision": finalization["reviewed_graph_revision"],
        "final_numbering_revision": finalization["final_numbering_revision"],
        "final_calibration_candidate_count": int(final_partition.get("calibration_candidate_count") or 0),
        "final_calibration_child_evidence_count": int(
            final_partition.get("calibration_child_evidence_count") or 0
        ),
        "integrity_gate": finalization["integrity_gate"],
        "three_image_evidence": {
            "original": str(screenshot),
            "before_review_fusion": str(composite_overlay),
            "final_repaired_fusion": final_overlay_path,
        },
        "model_provenance": {
            "source_type": review_report.get("source_type"),
            "actual_model_call": review_report.get("actual_model_call") is True,
            "profile_id": model_profile_id,
            "model_name": model_name,
            "endpoint": endpoint,
            "prompt_version": review_report.get("prompt_version"),
            "schema_version": review_report.get("schema_version"),
            "parser_version": review_report.get("parser_version"),
        },
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "real_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
    }
    result_path = run_dir / "panel_learning_model_review_repair_result.json"
    result["result_path"] = str(result_path.resolve())
    _write_json(result_path, result)
    return result


def _final_stage2_report(
    *,
    source_report: dict[str, Any],
    finalized_stage2: dict[str, Any],
    screenshot_path: Path,
    final_overlay_path: str,
    finalization: dict[str, Any],
    model_review_report_path: Path,
    closure_report_path: Path,
) -> dict[str, Any]:
    report = dict(source_report)
    report["contract_version"] = "panel_learning_final_stage2_for_calibration_v1"
    report["artifact_type"] = "learn_reviewed_final_stage2"
    report["stage2_numbering"] = finalized_stage2
    report["source_image_path"] = str(screenshot_path)
    structure_regions = _final_structure_regions(report, finalized_stage2)
    with Image.open(screenshot_path) as source_image:
        screen_width, screen_height = source_image.size
    fusion = _fusion_boxes(structure_regions, finalized_stage2.get("regions") or [])
    fusion["compiled_overlay_path"] = final_overlay_path
    fusion["full_screen_understanding_overlay_path"] = final_overlay_path
    fusion["source"] = "model_review_repair_finalization"
    report["fusion"] = fusion
    ui_hierarchy = build_ui_hierarchy_graph(
        structure_regions=structure_regions,
        numbered_regions=finalized_stage2.get("regions") or [],
        screen_size={"width": screen_width, "height": screen_height},
    )
    learning_draft = build_hierarchy_learning_draft(
        ui_hierarchy=ui_hierarchy,
        source_image_path=str(screenshot_path),
        compiled_overlay_path=final_overlay_path,
    )
    report["ui_hierarchy"] = ui_hierarchy
    report["learning_draft"] = learning_draft
    report["page_details"] = learning_draft["page_details"]
    report["model_review_repair"] = {
        "model_review_report_path": str(model_review_report_path.resolve()),
        "repair_closure_report_path": str(closure_report_path.resolve()),
        "source_graph_revision": finalization["source_graph_revision"],
        "reviewed_graph_revision": finalization["reviewed_graph_revision"],
        "final_numbering_revision": finalization["final_numbering_revision"],
        "integrity_gate": finalization["integrity_gate"],
        "calibration_permission": finalization["calibration_permission"],
    }
    report["display_only"] = True
    report["execute_binding_enabled"] = False
    report["artifact_is_authorization"] = False
    report["runtime_path_graph"] = False
    report["promotion_allowed"] = False
    report["real_clicks"] = 0
    report["live_safe_fill_attempted"] = 0
    report["final_submit_forbidden"] = True
    return report


def _final_structure_regions(
    source_report: dict[str, Any],
    finalized_stage2: dict[str, Any],
) -> list[dict[str, Any]]:
    localization = source_report.get("stage1_region_localization")
    if isinstance(localization, dict) and isinstance(localization.get("regions"), list):
        regions = [value for value in localization["regions"] if isinstance(value, dict)]
        if regions:
            return regions
    return [
        {
            "region_no": index,
            "region_id": str(region.get("region_id") or f"reviewed_region_{index}"),
            "label": str(region.get("label") or f"Reviewed region {index}"),
            "bbox": dict(region.get("bbox") or {}),
            "coordinate_validation": {
                "status": "reviewed_stage2_geometry",
                "evidence": "finalized reviewed Stage2 fallback structure",
            },
        }
        for index, region in enumerate(finalized_stage2.get("regions") or [], start=1)
        if isinstance(region, dict) and isinstance(region.get("bbox"), dict)
    ]


def _panel_run_dir(source_report_path: Path, screenshot_path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    millis = int((time.time() % 1) * 1000)
    stem = _safe_slug(screenshot_path.stem)[:40] or "screen"
    out_dir = PROJECT_ROOT / "artifacts" / "learning-runs" / f"panel_review_{timestamp}-{millis:03d}_{stem}"
    out_dir.mkdir(parents=True, exist_ok=False)
    return out_dir


def _resolve_existing(path: Path) -> Path:
    resolved = path if path.is_absolute() else PROJECT_ROOT / path
    resolved = resolved.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"required review artifact does not exist: {resolved}")
    return resolved


def _extract_stage2(source: dict[str, Any]) -> dict[str, Any]:
    two_stage = source.get("two_stage_understanding")
    if isinstance(two_stage, dict) and isinstance(two_stage.get("stage2_numbering"), dict):
        return two_stage["stage2_numbering"]
    if isinstance(source.get("stage2_numbering"), dict):
        return source["stage2_numbering"]
    if isinstance(source.get("regions"), list):
        return source
    raise ValueError("two-stage report does not contain stage2_numbering")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value).strip("-_")
