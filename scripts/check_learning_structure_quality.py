from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STAGE1_NEAR_FULL_PARTITION_RATIO = 0.98
DEFAULT_CASES = [
    {
        "case_id": "applemusic",
        "trial_result_path": "artifacts/learning-runs/panel_20260710-211655-075_applemusic/trial_result.json",
    },
    {
        "case_id": "qq",
        "trial_result_path": "artifacts/learning-runs/panel_20260710-211658-310_qq/trial_result.json",
    },
    {
        "case_id": "python_org",
        "trial_result_path": "artifacts/learning-runs/panel_20260710-211701-968_python_org/trial_result.json",
    },
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _resolve(path: str | Path, root: Path = ROOT) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _relative(path: str | Path, root: Path = ROOT) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(candidate)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    x = _int(value.get("x"))
    y = _int(value.get("y"))
    w = _int(value.get("w"))
    h = _int(value.get("h"))
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _screen_size(payload: dict[str, Any]) -> dict[str, int]:
    audit = _dict(_dict(payload.get("stage1_gate")).get("audit"))
    screen = _dict(audit.get("screen_size"))
    width = _int(screen.get("width"))
    height = _int(screen.get("height"))
    return {"width": width, "height": height}


def _rect_union_area(rects: list[dict[str, int]]) -> int:
    events: list[tuple[int, int, int, int]] = []
    for rect in rects:
        x1 = rect["x"]
        x2 = rect["x"] + rect["w"]
        y1 = rect["y"]
        y2 = rect["y"] + rect["h"]
        events.append((x1, 1, y1, y2))
        events.append((x2, -1, y1, y2))
    events.sort()
    active: list[tuple[int, int]] = []
    prev_x: int | None = None
    area = 0
    for x, kind, y1, y2 in events:
        if prev_x is not None and x > prev_x and active:
            area += (x - prev_x) * _covered_y(active)
        if kind == 1:
            active.append((y1, y2))
        else:
            try:
                active.remove((y1, y2))
            except ValueError:
                pass
        prev_x = x
    return area


def _covered_y(intervals: list[tuple[int, int]]) -> int:
    merged = 0
    current_start: int | None = None
    current_end: int | None = None
    for start, end in sorted(intervals):
        if current_start is None:
            current_start = start
            current_end = end
            continue
        if current_end is not None and start <= current_end:
            current_end = max(current_end, end)
        else:
            merged += max(0, (current_end or 0) - current_start)
            current_start = start
            current_end = end
    if current_start is not None and current_end is not None:
        merged += max(0, current_end - current_start)
    return merged


def _stage1_coverage_ratio(payload: dict[str, Any]) -> float | str:
    screen = _screen_size(payload)
    width = screen["width"]
    height = screen["height"]
    if width <= 0 or height <= 0:
        return "not_available"
    regions = _list(_dict(payload.get("stage1_region_localization")).get("regions"))
    rects: list[dict[str, int]] = []
    for region in regions:
        bbox = _bbox(_dict(region).get("bbox"))
        if not bbox:
            continue
        x1 = max(0, bbox["x"])
        y1 = max(0, bbox["y"])
        x2 = min(width, bbox["x"] + bbox["w"])
        y2 = min(height, bbox["y"] + bbox["h"])
        if x2 > x1 and y2 > y1:
            rects.append({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1})
    if not rects:
        return 0.0
    return round(_rect_union_area(rects) / float(width * height), 4)


def check_learning_structure_quality_case(case: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "").strip() or "unnamed_case"
    path_value = case.get("trial_result_path") or case.get("source_path") or ""
    trial_path = _resolve(path_value, root)
    result: dict[str, Any] = {
        "case_id": case_id,
        "trial_result_path": _relative(trial_path, root),
        "attempted": True,
        "passed": False,
        "errors": [],
    }
    if not trial_path.exists():
        result["errors"].append("trial_result_missing")
        result["quality_status"] = "invalid_missing_evidence"
        return result
    try:
        payload = _read_json(trial_path)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"json_read_failed:{type(exc).__name__}:{exc}")
        result["quality_status"] = "invalid_json"
        return result

    stage1_gate = _dict(payload.get("stage1_gate"))
    stage1 = _dict(payload.get("stage1_region_localization"))
    stage2 = _dict(payload.get("stage2_numbering"))
    fusion = _dict(payload.get("fusion"))
    boundary = _dict(fusion.get("region_content_boundary_summary"))
    learn_targets = _dict(payload.get("learn_all_targets"))
    model_grounding = _dict(payload.get("model_grounding_evidence"))
    coverage_ratio = _stage1_coverage_ratio(payload)
    coverage_ok = isinstance(coverage_ratio, float) and coverage_ratio >= 0.75
    near_full_partition_ok = (
        isinstance(coverage_ratio, float) and coverage_ratio >= STAGE1_NEAR_FULL_PARTITION_RATIO
    )
    boundary_passed = (
        boundary.get("boundary_contract_status") == "passed"
        and _int(boundary.get("missing_parent_child_count")) == 0
        and _int(boundary.get("outside_parent_after_clip_count")) == 0
        and _int(boundary.get("sibling_non_parent_overlap_count")) == 0
    )
    target_count = _int(learn_targets.get("target_count"))
    model_grounding_attempts = _int(model_grounding.get("model_grounding_attempted_count"))
    runtime_ready = bool(target_count > 0 and model_grounding_attempts > 0 and boundary_passed)
    checks = {
        "stage1_gate_passed": stage1_gate.get("status") == "passed",
        "stage1_regions_present": len(_list(stage1.get("regions"))) > 0,
        "stage1_screen_coverage_minimum": coverage_ok,
        "stage1_partition_near_full_coverage": near_full_partition_ok,
        "stage2_numbered_items_present": _int(stage2.get("numbered_item_count")) > 0,
        "fused_review_boxes_present": _int(fusion.get("fused_review_box_count")) > 0,
        "boundary_contract_passed": boundary_passed,
        "runtime_not_promoted_without_grounding": runtime_ready is False or target_count > 0,
    }
    failed_checks = [name for name, ok in checks.items() if not ok]
    if (
        not checks["stage1_gate_passed"]
        or not checks["stage1_regions_present"]
        or not checks["stage1_screen_coverage_minimum"]
        or not checks["stage1_partition_near_full_coverage"]
    ):
        quality_status = "blocked_structure_repair"
    elif not checks["stage2_numbered_items_present"] or not checks["fused_review_boxes_present"]:
        quality_status = "blocked_structure_repair"
    elif not boundary_passed:
        quality_status = "stress_only_needs_review"
    else:
        quality_status = "display_review_candidate"
    result.update(
        {
            "passed": quality_status == "display_review_candidate",
            "quality_status": quality_status,
            "failed_checks": failed_checks,
            "checks": checks,
            "runtime_pathgraph_ready": runtime_ready,
            "structure_metrics": {
                "stage1_region_count": len(_list(stage1.get("regions"))),
                "stage1_screen_coverage_ratio": coverage_ratio,
                "stage1_near_full_partition_required_ratio": STAGE1_NEAR_FULL_PARTITION_RATIO,
                "stage2_region_count": _int(stage2.get("region_count")),
                "stage2_numbered_item_count": _int(stage2.get("numbered_item_count")),
                "fused_review_box_count": _int(fusion.get("fused_review_box_count")),
                "missing_parent_child_count": _int(boundary.get("missing_parent_child_count")),
                "clipped_fused_child_count": _int(boundary.get("clipped_fused_child_count")),
                "outside_parent_after_clip_count": _int(boundary.get("outside_parent_after_clip_count")),
                "sibling_non_parent_overlap_count": _int(boundary.get("sibling_non_parent_overlap_count")),
                "target_count": target_count,
                "model_grounding_attempted_count": model_grounding_attempts,
            },
            "safety_boundary": {
                "display_review_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "runtime_pathgraph_promotion": runtime_ready,
                "live_clicks": 0,
                "live_fills": 0,
                "live_submits": 0,
            },
            "interpretation": (
                "display/review structure quality only; passing does not prove model accuracy, "
                "point grounding, Execute authorization, or live PathGraph readiness"
            ),
        }
    )
    return result


def run_learning_structure_quality_check(
    cases: list[dict[str, Any]] | None = None,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    selected_cases = cases or DEFAULT_CASES
    results = [check_learning_structure_quality_case(case, root=root) for case in selected_cases]
    status_counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("quality_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    runtime_ready = sum(1 for item in results if item.get("runtime_pathgraph_ready") is True)
    return {
        "contract_version": "learning_structure_quality_check_v1",
        "generated_at": _now(),
        "summary": {
            "attempted": len(results),
            "passed_display_review_candidate": status_counts.get("display_review_candidate", 0),
            "display_review_candidate": status_counts.get("display_review_candidate", 0),
            "stress_only_needs_review": status_counts.get("stress_only_needs_review", 0),
            "blocked_structure_repair": status_counts.get("blocked_structure_repair", 0),
            "invalid_cases": sum(1 for item in results if str(item.get("quality_status") or "").startswith("invalid")),
            "runtime_pathgraph_ready": runtime_ready,
            "interpretation": (
                "Structure-quality gate for Learning Mode review artifacts. A display-review pass is not "
                "recognition accuracy, model grounding, Execute authorization, or Runtime PathGraph readiness."
            ),
        },
        "cases": results,
        "safety_boundary": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": runtime_ready > 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Learning Mode Stage1/Stage2 display structure quality.")
    parser.add_argument("--out", default="", help="Optional JSON report path.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()
    report = run_learning_structure_quality_check()
    if args.out:
        out_path = _resolve(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json or not args.out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
