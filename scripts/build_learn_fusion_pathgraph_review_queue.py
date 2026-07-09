from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

QUEUE_NAME = "learn_fusion_pathgraph_review_queue.json"


def build_pathgraph_review_queue(
    *,
    fusion_status_path: str | Path,
    out_dir: str | Path,
    gate_diagnosis_path: str | Path | None = None,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    status_file = _resolve_path(fusion_status_path, root)
    diagnosis_file = _resolve_path(gate_diagnosis_path, root) if gate_diagnosis_path is not None else None
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    status = _read_json(status_file)
    diagnosis = _read_json(diagnosis_file) if diagnosis_file is not None else {}
    diagnosis_by_key = _diagnosis_by_key(diagnosis)
    queue_items = [
        _queue_item(item=item, diagnosis=diagnosis_by_key.get(_item_key(item)))
        for item in _list_of_dicts(status.get("items"))
    ]
    report = {
        "contract_version": "learn_fusion_pathgraph_review_queue_v1",
        "fusion_status_path": _relative_path(status_file, root),
        "gate_diagnosis_path": _relative_path(diagnosis_file, root) if diagnosis_file is not None else None,
        "summary": _summary(queue_items),
        "queue_items": queue_items,
        "display_only": True,
        "candidate_only": True,
        "not_accuracy": True,
        "not_pathgraph_promotion": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "final_submit_forbidden": True,
        "interpretation": (
            "Review queue derived from fused full-screen understanding. "
            "It prepares human PathGraph review inputs only and does not authorize Execute, clicks, fill, submit, or promotion."
        ),
    }
    queue_path = out / QUEUE_NAME
    queue_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "learn_fusion_pathgraph_review_queue_build_result_v1",
        "queue_path": str(queue_path.resolve()),
        "summary": report["summary"],
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _queue_item(*, item: dict[str, Any], diagnosis: dict[str, Any] | None) -> dict[str, Any]:
    review_bucket = _review_bucket(item=item, diagnosis=diagnosis)
    candidate_semantic_action = _candidate_semantic_action(item=item, review_bucket=review_bucket)
    return {
        "contract_version": "learn_fusion_pathgraph_review_queue_item_v1",
        "region_no": item.get("region_no"),
        "source_item_id": item.get("source_item_id"),
        "label": item.get("label"),
        "role": item.get("role"),
        "review_bucket": review_bucket,
        "candidate_semantic_action": candidate_semantic_action,
        "calibration_status": item.get("calibration_status"),
        "point_quality": item.get("point_quality"),
        "gate_safety": item.get("gate_safety"),
        "gate_diagnosis_classification": diagnosis.get("classification") if isinstance(diagnosis, dict) else None,
        "gate_diagnosis_proposed_fix": diagnosis.get("proposed_fix") if isinstance(diagnosis, dict) else None,
        "rough_bbox_hint": item.get("rough_bbox_hint") if isinstance(item.get("rough_bbox_hint"), dict) else None,
        "seed_click_point": item.get("seed_click_point") if isinstance(item.get("seed_click_point"), dict) else None,
        "vista_point": item.get("vista_point") if isinstance(item.get("vista_point"), dict) else None,
        "selected_click_point": item.get("selected_click_point") if isinstance(item.get("selected_click_point"), dict) else None,
        "trace_path": item.get("trace_path"),
        "recognition_plan_trace_path": item.get("recognition_plan_trace_path"),
        "overlay_path": item.get("overlay_path"),
        "real_clicks": int(item.get("real_clicks") or 0),
        "targeted_rerun_correction": item.get("targeted_rerun_correction")
        if isinstance(item.get("targeted_rerun_correction"), dict)
        else None,
        "required_next_evidence": _required_next_evidence(review_bucket),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "candidate_only": True,
    }


def _review_bucket(*, item: dict[str, Any], diagnosis: dict[str, Any] | None) -> str:
    if _text(item.get("calibration_status")) == "gate_rejected":
        if isinstance(diagnosis, dict) and _text(diagnosis.get("classification")) == "non_actionable_region_correctly_rejected":
            return "blocked_non_action"
        return "blocked_gate_rejected"
    if _text(item.get("point_quality")) == "vista_point_outside_seed_bbox":
        return "geometry_review_required"
    if _text(item.get("gate_safety")) != "passed_allowed_dry_run":
        return "blocked_gate_safety"
    if _is_open_detail_candidate(item):
        return "open_detail_candidate_review"
    if _text(item.get("role")) in {"button", "input", "toggle", "menu_item", "link"}:
        return "same_screen_action_review"
    return "needs_human_review"


def _is_open_detail_candidate(item: dict[str, Any]) -> bool:
    role = _text(item.get("role"))
    label = _text(item.get("label")).lower()
    has_targeted_rerun = isinstance(item.get("targeted_rerun_correction"), dict)
    return role == "card" and (has_targeted_rerun or "job listing card" in label)


def _candidate_semantic_action(*, item: dict[str, Any], review_bucket: str) -> str | None:
    if review_bucket == "open_detail_candidate_review":
        return "open_detail"
    role = _text(item.get("role"))
    if role == "input":
        return "fill_or_filter_field_review"
    if role in {"button", "toggle", "menu_item", "link"}:
        return "click_or_toggle_review"
    return None


def _required_next_evidence(review_bucket: str) -> list[str]:
    if review_bucket == "open_detail_candidate_review":
        return ["human_review_open_detail_candidate", "post_action_detail_observe_after_approved_no_dispatch"]
    if review_bucket == "same_screen_action_review":
        return ["human_review_action_semantics", "same_screenshot_ocr_uia_or_calibrated_support"]
    if review_bucket == "geometry_review_required":
        return ["manual_bbox_or_point_review", "rerun_locator_or_calibrated_support"]
    if review_bucket == "blocked_non_action":
        return ["keep_blocked_or_mark_as_page_structure_not_action"]
    if review_bucket.startswith("blocked_"):
        return ["inspect_gate_trace_before_pathgraph_review"]
    return ["human_review_required_before_pathgraph_candidate"]


def _summary(queue_items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    real_clicks = 0
    for item in queue_items:
        bucket = _text(item.get("review_bucket")) or "missing"
        counts[bucket] = counts.get(bucket, 0) + 1
        real_clicks += int(item.get("real_clicks") or 0)
    return {
        "attempted": len(queue_items),
        "open_detail_candidate_review": counts.get("open_detail_candidate_review", 0),
        "same_screen_action_review": counts.get("same_screen_action_review", 0),
        "geometry_review_required": counts.get("geometry_review_required", 0),
        "needs_human_review": counts.get("needs_human_review", 0),
        "blocked_non_action": counts.get("blocked_non_action", 0),
        "blocked_gate_rejected": counts.get("blocked_gate_rejected", 0),
        "blocked_gate_safety": counts.get("blocked_gate_safety", 0),
        "bucket_counts": dict(sorted(counts.items())),
        "real_clicks": real_clicks,
    }


def _diagnosis_by_key(diagnosis: dict[str, Any]) -> dict[tuple[int | None, str], dict[str, Any]]:
    result: dict[tuple[int | None, str], dict[str, Any]] = {}
    for case in _list_of_dicts(diagnosis.get("cases")):
        key = _item_key(case)
        if key[0] is not None or key[1]:
            result[key] = case
    return result


def _item_key(item: dict[str, Any]) -> tuple[int | None, str]:
    region_no = item.get("region_no")
    region_no = int(region_no) if isinstance(region_no, int) or str(region_no).isdigit() else None
    return region_no, _text(item.get("source_item_id"))


def _resolve_path(path: str | Path | None, root: Path) -> Path:
    if path is None:
        raise ValueError("path is required")
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
    parser = argparse.ArgumentParser(description="Build a review-only PathGraph preparation queue from fused understanding status.")
    parser.add_argument("--fusion-status", required=True, help="Path to learn_precise_understanding_fusion_status*.json")
    parser.add_argument("--gate-diagnosis", help="Optional path to learn_fusion_gate_rejection_diagnosis_report.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    build_pathgraph_review_queue(
        fusion_status_path=args.fusion_status,
        gate_diagnosis_path=args.gate_diagnosis,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
