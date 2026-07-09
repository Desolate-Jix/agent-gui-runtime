from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.draft_review import load_learning_draft_review


REPORT_NAME = "learn_precise_understanding_candidate.json"


def build_learn_precise_understanding_candidate(
    *,
    source_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    source_file = _resolve_path(source_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    review = load_learning_draft_review(_relative_path(source_file, root), project_root=root)
    preview = _dict(review.get("screen_understanding_preview"))
    candidate_review = _dict(review.get("pathgraph_candidate_review"))
    evidence_integrity = _dict(preview.get("evidence_integrity"))
    calibration_report_path = _source_calibration_report_path(evidence_integrity, root)
    calibration_report = _read_json(calibration_report_path) if calibration_report_path else {}
    fusion = _dict(calibration_report.get("fused_precise_understanding"))
    fusion_items = _list_of_dicts(fusion.get("items"))
    backlog_items = _list_of_dicts(preview.get("calibration_backlog_items"))
    ready_regions = {int(item) for item in _list(preview.get("calibration_batch_ready_region_numbers")) if _int_or_none(item)}
    review_blocked_regions = {
        int(item) for item in _list(preview.get("calibration_batch_review_blocked_region_numbers")) if _int_or_none(item)
    }
    items = _candidate_items(
        fusion_items=fusion_items,
        backlog_items=backlog_items,
        ready_regions=ready_regions,
        review_blocked_regions=review_blocked_regions,
    )
    summary = _summary(items=items, preview=preview, calibration_report=calibration_report)
    readiness_status = _readiness_status(summary, calibration_report_path=calibration_report_path)
    output_path = out / REPORT_NAME
    payload = {
        "contract_version": "learn_precise_understanding_candidate_v1",
        "source_path": _relative_path(source_file, root),
        "source_calibration_report_path": _relative_path(calibration_report_path, root) if calibration_report_path else "",
        "source_calibration_report_status": "loaded" if calibration_report_path else "source_calibration_report_missing",
        "pathgraph_candidate_path": candidate_review.get("pathgraph_candidate_path"),
        "screenshot_path": _text(calibration_report.get("screenshot_path"), fusion.get("screenshot_path")),
        "full_screen_understanding_overlay_path": preview.get("full_screen_understanding_overlay_path"),
        "compiled_overlay_path": preview.get("compiled_overlay_path"),
        "readiness_status": readiness_status,
        "summary": summary,
        "items": items,
        "pathgraph_preparation": {
            "status": "blocked_pending_calibration" if summary["pending_calibration_count"] else readiness_status,
            "candidate_review_ready_count": summary["pathgraph_candidate_review_ready_count"],
            "blocked_count": summary["blocked_from_pathgraph_count"],
            "pending_calibration_count": summary["pending_calibration_count"],
            "review_blocked_count": summary["review_blocked_count"],
            "runtime_pathgraph_promotion": False,
            "interpretation": "human PathGraph preparation only; not Runtime PathGraph promotion",
        },
        "evidence_integrity": evidence_integrity,
        "safety": {
            "display_only": True,
            "model_started": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "not_accuracy": True,
        "not_e2e_success": True,
        "interpretation": (
            "Offline precise-understanding candidate compiled from full-screen understanding, calibration backlog, "
            "and existing Execute dry-run evidence. It is for Learning Mode review and future PathGraph preparation only; "
            "it does not start models, click, fill, submit, authorize Execute, or promote Runtime PathGraph."
        ),
    }
    payload["report_path"] = str(output_path.resolve())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def _candidate_items(
    *,
    fusion_items: list[dict[str, Any]],
    backlog_items: list[dict[str, Any]],
    ready_regions: set[int],
    review_blocked_regions: set[int],
) -> list[dict[str, Any]]:
    fusion_by_region = {_int_or_none(item.get("region_no")): item for item in fusion_items if _int_or_none(item.get("region_no"))}
    backlog_by_region = {_int_or_none(item.get("region_no")): item for item in backlog_items if _int_or_none(item.get("region_no"))}
    region_numbers = sorted({*fusion_by_region.keys(), *backlog_by_region.keys()})
    results = []
    for region_no in region_numbers:
        fusion_item = _dict(fusion_by_region.get(region_no))
        backlog_item = _dict(backlog_by_region.get(region_no))
        status = _calibration_state(region_no, fusion_item, ready_regions, review_blocked_regions)
        promotion_policy = _dict(fusion_item.get("promotion_policy"))
        results.append(
            {
                "region_no": region_no,
                "source_item_id": _text(fusion_item.get("source_item_id"), backlog_item.get("source_item_id")),
                "label": _text(fusion_item.get("label"), backlog_item.get("label")),
                "role": _text(fusion_item.get("role"), backlog_item.get("role")),
                "calibration_state": status,
                "calibration_status": fusion_item.get("calibration_status"),
                "failure_category": fusion_item.get("failure_category"),
                "point_quality": fusion_item.get("point_quality"),
                "gate_safety": fusion_item.get("gate_safety"),
                "rough_bbox_hint": _dict(fusion_item.get("rough_bbox_hint")) or _dict(backlog_item.get("rough_bbox_hint")),
                "candidate_point": _dict(fusion_item.get("vista_point"))
                or _dict(fusion_item.get("selected_click_point"))
                or _dict(fusion_item.get("seed_click_point")),
                "pathgraph_candidate_review_state": _pathgraph_candidate_state(
                    status=status,
                    promotion_policy=promotion_policy,
                    region_no=region_no,
                    ready_regions=ready_regions,
                    review_blocked_regions=review_blocked_regions,
                ),
                "required_next_step": _required_next_step(status=status, backlog_item=backlog_item, promotion_policy=promotion_policy),
                "trace_path": fusion_item.get("trace_path"),
                "recognition_plan_trace_path": fusion_item.get("recognition_plan_trace_path"),
                "overlay_path": fusion_item.get("overlay_path"),
                "prompt": backlog_item.get("prompt"),
                "real_clicks": int(fusion_item.get("real_clicks") or 0),
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return results


def _calibration_state(
    region_no: int,
    fusion_item: dict[str, Any],
    ready_regions: set[int],
    review_blocked_regions: set[int],
) -> str:
    if region_no in review_blocked_regions:
        return "review_before_calibration"
    if region_no in ready_regions:
        return "pending_execute_dry_run_calibration"
    if not fusion_item:
        return "missing_region_evidence"
    if _text(fusion_item.get("gate_safety")) == "passed_rejected":
        return "calibrated_safe_intercept_review_required"
    if (
        _text(fusion_item.get("point_quality")) == "vista_point_inside_seed_bbox"
        and _text(fusion_item.get("gate_safety")) == "passed_allowed_dry_run"
    ):
        return "calibrated_review_only"
    return "calibrated_needs_review"


def _pathgraph_candidate_state(
    *,
    status: str,
    promotion_policy: dict[str, Any],
    region_no: int,
    ready_regions: set[int],
    review_blocked_regions: set[int],
) -> str:
    if region_no in ready_regions:
        return "blocked_pending_execute_dry_run_calibration"
    if region_no in review_blocked_regions:
        return "blocked_manual_review_before_calibration"
    if promotion_policy.get("promotable_to_pathgraph_candidate_review") is True:
        return "candidate_for_human_pathgraph_review"
    reason = _text(promotion_policy.get("block_reason")) or status
    return f"blocked:{reason}"


def _required_next_step(*, status: str, backlog_item: dict[str, Any], promotion_policy: dict[str, Any]) -> str:
    if status == "pending_execute_dry_run_calibration":
        return _text(backlog_item.get("required_next_step")) or "run_execute_dry_run_calibration_for_numbered_region"
    if status == "review_before_calibration":
        return "human_review_before_execute_dry_run_calibration"
    if promotion_policy.get("promotable_to_pathgraph_candidate_review") is True:
        return "human_pathgraph_candidate_review"
    return "resolve_blocker_before_pathgraph_review"


def _summary(*, items: list[dict[str, Any]], preview: dict[str, Any], calibration_report: dict[str, Any]) -> dict[str, Any]:
    states = [_text(item.get("calibration_state")) for item in items]
    pathgraph_states = [_text(item.get("pathgraph_candidate_review_state")) for item in items]
    return {
        "total_regions": len(items),
        "source_report_attempted": int(_dict(calibration_report.get("summary")).get("attempted") or 0),
        "calibration_coverage_rate": _dict(preview.get("precise_understanding_readiness_summary")).get(
            "calibration_coverage_rate"
        ),
        "calibrated_review_only_count": sum(1 for state in states if state.startswith("calibrated_")),
        "pending_calibration_count": states.count("pending_execute_dry_run_calibration"),
        "review_blocked_count": states.count("review_before_calibration"),
        "safe_intercept_review_count": states.count("calibrated_safe_intercept_review_required"),
        "pathgraph_candidate_review_ready_count": pathgraph_states.count("candidate_for_human_pathgraph_review"),
        "blocked_from_pathgraph_count": sum(1 for state in pathgraph_states if state.startswith("blocked")),
        "real_clicks": sum(int(item.get("real_clicks") or 0) for item in items),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _readiness_status(summary: dict[str, Any], *, calibration_report_path: Path | None) -> str:
    if calibration_report_path is None:
        return "blocked_missing_source_calibration_report"
    if summary["pending_calibration_count"]:
        return "needs_pending_calibration"
    if summary["review_blocked_count"]:
        return "blocked_manual_review_before_calibration"
    if summary["pathgraph_candidate_review_ready_count"]:
        return "ready_for_human_pathgraph_candidate_review"
    return "blocked_from_pathgraph_candidate_review"


def _source_calibration_report_path(evidence_integrity: dict[str, Any], root: Path) -> Path | None:
    source = _dict(evidence_integrity.get("source_calibration_report"))
    for key in ("path", "declared_path"):
        value = source.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = _resolve_path(value, root)
        if path.exists():
            return path
    return None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an offline precise-understanding candidate for Learning Mode.")
    parser.add_argument("--source", required=True, help="Learning draft review source or pathgraph_candidate.json.")
    parser.add_argument("--out", required=True, help="Output directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    args = parser.parse_args()
    build_learn_precise_understanding_candidate(source_path=args.source, out_dir=args.out, json_stdout=args.json)


if __name__ == "__main__":
    main()
