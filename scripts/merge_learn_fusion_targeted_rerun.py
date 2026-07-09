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

CORRECTED_STATUS_NAME = "learn_precise_understanding_fusion_status_corrected.json"
MERGE_REPORT_NAME = "learn_fusion_targeted_rerun_merge_result.json"


def merge_targeted_rerun_into_fusion_status(
    *,
    base_status_path: str | Path,
    rerun_report_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    base_path = _resolve_path(base_status_path, root)
    rerun_path = _resolve_path(rerun_report_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    base = _read_json(base_path)
    rerun = _read_json(rerun_path)
    corrected = deepcopy(base)
    rerun_items = _rerun_items_by_key(rerun)
    updated_region_numbers: list[int] = []
    updated_source_item_ids: list[str] = []

    items = _list_of_dicts(corrected.get("items"))
    corrected_items: list[dict[str, Any]] = []
    for item in items:
        key = _item_key(item)
        rerun_item = rerun_items.get(key)
        if rerun_item is None:
            corrected_items.append(item)
            continue
        updated = _merge_item(base_item=item, rerun_item=rerun_item, rerun_report_path=rerun_path, root=root)
        corrected_items.append(updated)
        if isinstance(updated.get("region_no"), int):
            updated_region_numbers.append(updated["region_no"])
        source_item_id = _text(updated.get("source_item_id"))
        if source_item_id:
            updated_source_item_ids.append(source_item_id)

    corrected["items"] = corrected_items
    corrected["source_report_path"] = _relative_path(rerun_path, root)
    for field in (
        "screenshot_path",
        "full_screen_understanding_overlay_path",
        "compiled_overlay_path",
    ):
        if rerun.get(field):
            corrected[field] = deepcopy(rerun[field])
    pending_after_merge = _remove_updated_regions_from_pending_calibration(
        corrected,
        updated_region_numbers=updated_region_numbers,
    )
    _recompute_status_fields(corrected)
    corrected["precise_understanding_readiness_summary"] = _precise_understanding_readiness_summary(
        corrected,
        pending=pending_after_merge,
    )
    corrected["targeted_rerun_correction"] = {
        "contract_version": "learn_fusion_targeted_rerun_correction_v1",
        "base_status_path": _relative_path(base_path, root),
        "rerun_report_path": _relative_path(rerun_path, root),
        "updated_item_count": len(updated_region_numbers),
        "updated_region_numbers": updated_region_numbers,
        "updated_source_item_ids": updated_source_item_ids,
        "pending_ready_region_numbers_after_merge": pending_after_merge["ready_region_numbers"],
        "pending_review_blocked_region_numbers_after_merge": pending_after_merge["review_blocked_region_numbers"],
        "correction_scope": "matching_region_no_and_source_item_id_only",
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Corrects full-screen fusion status with existing targeted dry-run evidence. "
            "It does not run a model, click, or authorize PathGraph promotion."
        ),
    }
    corrected["execute_binding_enabled"] = False
    corrected["artifact_is_authorization"] = False
    corrected["display_only"] = True

    corrected_path = out / CORRECTED_STATUS_NAME
    corrected_path.write_text(json.dumps(corrected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "learn_fusion_targeted_rerun_merge_result_v1",
        "base_status_path": _relative_path(base_path, root),
        "rerun_report_path": _relative_path(rerun_path, root),
        "corrected_status_path": str(corrected_path.resolve()),
        "updated_item_count": len(updated_region_numbers),
        "updated_region_numbers": updated_region_numbers,
        "summary": corrected.get("summary"),
        "calibration_status_counts": corrected.get("calibration_status_counts"),
        "gate_safety_counts": corrected.get("gate_safety_counts"),
        "point_quality_counts": corrected.get("point_quality_counts"),
        "precise_understanding_readiness_summary": corrected.get("precise_understanding_readiness_summary"),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    report_path = out / MERGE_REPORT_NAME
    result["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _rerun_items_by_key(rerun: dict[str, Any]) -> dict[tuple[int | None, str], dict[str, Any]]:
    fusion = rerun.get("fused_precise_understanding") if isinstance(rerun.get("fused_precise_understanding"), dict) else {}
    result: dict[tuple[int | None, str], dict[str, Any]] = {}
    for item in _list_of_dicts(fusion.get("items")):
        key = _item_key(item)
        if key[0] is not None or key[1]:
            result[key] = item
    return result


def _merge_item(*, base_item: dict[str, Any], rerun_item: dict[str, Any], rerun_report_path: Path, root: Path) -> dict[str, Any]:
    updated = deepcopy(base_item)
    previous = {
        "previous_calibration_status": base_item.get("calibration_status"),
        "previous_gate_safety": base_item.get("gate_safety"),
        "previous_point_quality": base_item.get("point_quality"),
        "previous_trace_path": base_item.get("trace_path"),
    }
    for key in (
        "label",
        "role",
        "evidence_level",
        "rough_bbox_hint",
        "seed_click_point",
        "vista_point",
        "selected_click_point",
        "calibration_status",
        "failure_category",
        "point_quality",
        "gate_safety",
        "promotion_policy",
        "trace_path",
        "recognition_plan_trace_path",
        "overlay_path",
        "real_clicks",
    ):
        if key in rerun_item:
            updated[key] = deepcopy(rerun_item[key])
    updated["targeted_rerun_correction"] = {
        "contract_version": "learn_fusion_item_targeted_rerun_correction_v1",
        **previous,
        "rerun_report_path": _relative_path(rerun_report_path, root),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    updated["execute_binding_enabled"] = False
    updated["artifact_is_authorization"] = False
    return updated


def _recompute_status_fields(status: dict[str, Any]) -> None:
    items = _list_of_dicts(status.get("items"))
    previous_summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    pending = _pending_calibration_state(status)
    promotable = [
        item
        for item in items
        if isinstance(item.get("promotion_policy"), dict)
        and item["promotion_policy"].get("promotable_to_pathgraph_candidate_review") is True
    ]
    safe_intercepts = [item for item in items if _text(item.get("calibration_status")) == "gate_rejected"]
    needs_review = [item for item in items if _text(item.get("calibration_status")) == "needs_human_review"]
    failed = [item for item in items if _text(item.get("calibration_status")) == "failed"]
    has_coverage_context = _has_coverage_context(status, previous_summary=previous_summary, pending=pending)
    total = (
        _int_value(previous_summary.get("total_locator_cards"), previous_summary.get("attempted"), len(items))
        if has_coverage_context
        else 0
    )
    uncalibrated = len(pending["ready_region_numbers"]) + len(pending["review_blocked_region_numbers"])
    calibrated = max(total - uncalibrated, 0) if total else _int_value(previous_summary.get("calibrated_cases"), 0)
    summary = {
        "attempted": len(items),
        "promotable_to_pathgraph_candidate_review": len(promotable),
        "needs_human_review": len(needs_review),
        "safe_intercepts": len(safe_intercepts),
        "failed": len(failed),
        "real_clicks": sum(int(item.get("real_clicks") or 0) for item in items),
    }
    if total:
        summary["total_locator_cards"] = total
        summary["calibrated_cases"] = calibrated
        summary["uncalibrated_locator_cards"] = uncalibrated
        summary["calibration_coverage_rate"] = round(calibrated / total, 4)
    status["summary"] = summary
    status["calibration_status_counts"] = _field_counts(items, "calibration_status")
    status["gate_safety_counts"] = _field_counts(items, "gate_safety")
    status["point_quality_counts"] = _field_counts(items, "point_quality")
    status["block_reason_counts"] = _block_reason_counts(items)
    display = status.get("display_readiness") if isinstance(status.get("display_readiness"), dict) else {}
    display["item_count"] = len(items)
    status["display_readiness"] = display
    pathgraph = status.get("pathgraph_preparation") if isinstance(status.get("pathgraph_preparation"), dict) else {}
    pathgraph["status"] = _pathgraph_status(items=items, promotable_items=promotable)
    pathgraph["promotable_item_count"] = len(promotable)
    pathgraph["blocked_item_count"] = len(items) - len(promotable)
    status["pathgraph_preparation"] = pathgraph


def _remove_updated_regions_from_pending_calibration(
    status: dict[str, Any],
    *,
    updated_region_numbers: list[int],
) -> dict[str, Any]:
    updated = set(updated_region_numbers)
    if not updated:
        return _pending_calibration_state(status)

    backlog = status.get("calibration_backlog") if isinstance(status.get("calibration_backlog"), dict) else {}
    if backlog:
        items = [item for item in _list_of_dicts(backlog.get("items")) if _region_no(item) not in updated]
        backlog["items"] = items
        _update_backlog_summary(backlog)
        backlog["display_only"] = True
        backlog["execute_binding_enabled"] = False
        backlog["artifact_is_authorization"] = False
        status["calibration_backlog"] = backlog

    batch = status.get("calibration_batch_plan") if isinstance(status.get("calibration_batch_plan"), dict) else {}
    if batch:
        _remove_regions_from_batch_plan(batch, updated_regions=updated)
        status["calibration_batch_plan"] = batch

    preflight = status.get("pathgraph_preflight_plan") if isinstance(status.get("pathgraph_preflight_plan"), dict) else {}
    if preflight:
        pending_batch = (
            preflight.get("pending_calibration_batch")
            if isinstance(preflight.get("pending_calibration_batch"), dict)
            else {}
        )
        if pending_batch:
            _remove_regions_from_batch_plan(pending_batch, updated_regions=updated)
            preflight["pending_calibration_batch"] = pending_batch
        pending_state = _pending_calibration_state({"pathgraph_preflight_plan": preflight})
        summary = preflight.get("summary") if isinstance(preflight.get("summary"), dict) else {}
        summary["pending_calibration_ready_count"] = len(pending_state["ready_region_numbers"])
        summary["pending_calibration_review_count"] = len(pending_state["review_blocked_region_numbers"])
        summary["ready_for_runtime_pathgraph_promotion"] = False
        preflight["summary"] = summary
        preflight["execute_binding_enabled"] = False
        preflight["artifact_is_authorization"] = False
        status["pathgraph_preflight_plan"] = preflight

    return _pending_calibration_state(status)


def _remove_regions_from_batch_plan(batch: dict[str, Any], *, updated_regions: set[int]) -> None:
    batch["ready_region_numbers"] = [item for item in _list_of_int(batch.get("ready_region_numbers")) if item not in updated_regions]
    batch["review_blocked_region_numbers"] = [
        item for item in _list_of_int(batch.get("review_blocked_region_numbers")) if item not in updated_regions
    ]
    if "ready_items" in batch:
        batch["ready_items"] = [item for item in _list_of_dicts(batch.get("ready_items")) if _region_no(item) not in updated_regions]
    if "review_blocked_items" in batch:
        batch["review_blocked_items"] = [
            item for item in _list_of_dicts(batch.get("review_blocked_items")) if _region_no(item) not in updated_regions
        ]
    summary = batch.get("summary") if isinstance(batch.get("summary"), dict) else {}
    summary["ready_for_execute_dry_run"] = len(batch["ready_region_numbers"])
    summary["review_before_calibration"] = len(batch["review_blocked_region_numbers"])
    summary["real_clicks"] = int(summary.get("real_clicks") or 0)
    summary["display_only"] = True
    summary["execute_binding_enabled"] = False
    batch["summary"] = summary
    batch["command_executes_now"] = False
    batch["execute_binding_enabled"] = False
    batch["artifact_is_authorization"] = False
    if updated_regions:
        batch["run_command_preview_stale_after_merge"] = True


def _update_backlog_summary(backlog: dict[str, Any]) -> None:
    items = _list_of_dicts(backlog.get("items"))
    ready = [item for item in items if item.get("ready_for_execute_dry_run") is True]
    review = [item for item in items if item.get("ready_for_execute_dry_run") is not True]
    summary = backlog.get("summary") if isinstance(backlog.get("summary"), dict) else {}
    summary["uncalibrated_locator_cards"] = len(items)
    summary["ready_for_execute_dry_run"] = len(ready)
    summary["review_before_calibration"] = len(review)
    summary["display_only"] = True
    summary["execute_binding_enabled"] = False
    backlog["summary"] = summary


def _pending_calibration_state(status: dict[str, Any]) -> dict[str, list[int]]:
    preflight = status.get("pathgraph_preflight_plan") if isinstance(status.get("pathgraph_preflight_plan"), dict) else {}
    pending_batch = (
        preflight.get("pending_calibration_batch")
        if isinstance(preflight.get("pending_calibration_batch"), dict)
        else {}
    )
    batch = status.get("calibration_batch_plan") if isinstance(status.get("calibration_batch_plan"), dict) else {}
    backlog = status.get("calibration_backlog") if isinstance(status.get("calibration_backlog"), dict) else {}
    source = pending_batch if pending_batch else batch
    ready = _list_of_int(source.get("ready_region_numbers"))
    review = _list_of_int(source.get("review_blocked_region_numbers"))
    if not ready and not review and backlog:
        for item in _list_of_dicts(backlog.get("items")):
            region = _region_no(item)
            if region <= 0:
                continue
            if item.get("ready_for_execute_dry_run") is True:
                ready.append(region)
            else:
                review.append(region)
    return {
        "ready_region_numbers": sorted(set(ready)),
        "review_blocked_region_numbers": sorted(set(review)),
    }


def _precise_understanding_readiness_summary(status: dict[str, Any], *, pending: dict[str, list[int]]) -> dict[str, Any]:
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    pathgraph = status.get("pathgraph_preparation") if isinstance(status.get("pathgraph_preparation"), dict) else {}
    total = _int_value(summary.get("total_locator_cards"), 0)
    calibrated = _int_value(summary.get("calibrated_cases"), 0)
    uncalibrated = _int_value(summary.get("uncalibrated_locator_cards"), 0)
    pending_ready_count = len(pending["ready_region_numbers"])
    pending_review_count = len(pending["review_blocked_region_numbers"])
    readiness_status = (
        "needs_pending_calibration"
        if pending_ready_count or pending_review_count
        else "ready_for_manual_runtime_promotion_review"
        if pathgraph.get("ready_for_runtime_pathgraph_promotion") is True
        else "not_covered"
        if not total
        else "needs_pathgraph_review"
    )
    return {
        "contract_version": "precise_understanding_readiness_summary_v1",
        "readiness_status": readiness_status,
        "total_locator_cards": total,
        "calibrated_cases": calibrated,
        "uncalibrated_locator_cards": uncalibrated,
        "calibration_coverage_rate": round(calibrated / total, 4) if total else "not_covered",
        "pending_calibration_ready_count": pending_ready_count,
        "pending_calibration_review_count": pending_review_count,
        "pathgraph_status": _text(pathgraph.get("status")) or "missing",
        "ready_for_runtime_pathgraph_promotion": pathgraph.get("ready_for_runtime_pathgraph_promotion") is True,
        "display_only": True,
        "not_accuracy": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _pathgraph_status(*, items: list[dict[str, Any]], promotable_items: list[dict[str, Any]]) -> str:
    if not items:
        return "not_covered"
    if promotable_items and len(promotable_items) < len(items):
        return "partially_ready_for_human_review"
    if promotable_items:
        return "ready_for_human_review"
    return "blocked_from_pathgraph_candidate_review"


def _has_coverage_context(
    status: dict[str, Any],
    *,
    previous_summary: dict[str, Any],
    pending: dict[str, list[int]],
) -> bool:
    if any(key in previous_summary for key in ("total_locator_cards", "calibrated_cases", "uncalibrated_locator_cards")):
        return True
    if pending["ready_region_numbers"] or pending["review_blocked_region_numbers"]:
        return True
    if isinstance(status.get("calibration_backlog"), dict):
        return True
    if isinstance(status.get("calibration_batch_plan"), dict):
        return True
    preflight = status.get("pathgraph_preflight_plan") if isinstance(status.get("pathgraph_preflight_plan"), dict) else {}
    return isinstance(preflight.get("pending_calibration_batch"), dict)


def _block_reason_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        policy = item.get("promotion_policy") if isinstance(item.get("promotion_policy"), dict) else {}
        if policy.get("promotable_to_pathgraph_candidate_review") is True:
            continue
        reason = _text(policy.get("block_reason")) or "missing_promotion_policy"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _field_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = _text(item.get(key)) or "missing"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _item_key(item: dict[str, Any]) -> tuple[int | None, str]:
    region_no = item.get("region_no")
    region_no = int(region_no) if isinstance(region_no, int) or str(region_no).isdigit() else None
    return region_no, _text(item.get("source_item_id"))


def _region_no(item: dict[str, Any]) -> int:
    try:
        return int(item.get("region_no") or 0)
    except (TypeError, ValueError):
        return 0


def _list_of_int(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _int_value(*values: Any) -> int:
    for value in values:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


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


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge targeted numbered-region rerun evidence into a fusion status report.")
    parser.add_argument("--base-status", required=True, help="Path to base learn_precise_understanding_fusion_status_report.json")
    parser.add_argument("--rerun-report", required=True, help="Path to targeted numbered_region_calibration_report.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    merge_targeted_rerun_into_fusion_status(
        base_status_path=args.base_status,
        rerun_report_path=args.rerun_report,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
