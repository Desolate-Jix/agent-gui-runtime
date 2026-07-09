from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PREFLIGHT_NAME = "learn_fusion_pathgraph_preflight_plan.json"


def build_pathgraph_preflight_plan(
    *,
    queue_path: str | Path,
    out_dir: str | Path,
    calibration_batch_plan_path: str | Path | None = None,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    queue_file = _resolve_path(queue_path, root)
    batch_plan_file = _resolve_path(calibration_batch_plan_path, root) if calibration_batch_plan_path is not None else None
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    queue = _read_json(queue_file)
    batch_plan = _read_json(batch_plan_file) if batch_plan_file is not None else {}
    pending_calibration_batch = _pending_calibration_batch(batch_plan, batch_plan_file, root)
    queue_items = _list_of_dicts(queue.get("queue_items"))
    open_detail_items = [item for item in queue_items if _text(item.get("review_bucket")) == "open_detail_candidate_review"]
    same_screen_items = [item for item in queue_items if _text(item.get("review_bucket")) == "same_screen_action_review"]
    geometry_items = [item for item in queue_items if _text(item.get("review_bucket")) == "geometry_review_required"]
    non_action_items = [item for item in queue_items if _text(item.get("review_bucket")) == "blocked_non_action"]
    other_blocked_items = [
        item
        for item in queue_items
        if _text(item.get("review_bucket")).startswith("blocked_")
        and _text(item.get("review_bucket")) != "blocked_non_action"
    ]

    proposed_states = [{"state_id": "seek_results", "state_role": "results_list", "candidate_only": True}]
    if open_detail_items:
        proposed_states.append({"state_id": "model_detail_view", "state_role": "detail_view", "candidate_only": True})
    proposed_transitions = [_open_detail_transition(item=item, index=index) for index, item in enumerate(open_detail_items)]
    review_action_items = [_review_action_item(item=item) for item in same_screen_items]
    blocked_items = [_blocked_item(item=item) for item in [*geometry_items, *non_action_items, *other_blocked_items]]

    plan = {
        "contract_version": "learn_fusion_pathgraph_preflight_plan_v1",
        "queue_path": _relative_path(queue_file, root),
        "summary": {
            "queue_item_count": len(queue_items),
            "open_detail_transition_candidates": len(open_detail_items),
            "same_screen_action_candidates": len(same_screen_items),
            "geometry_blockers": len(geometry_items),
            "non_action_blockers": len(non_action_items),
            "other_blockers": len(other_blocked_items),
            "proposed_transition_count": len(proposed_transitions),
            "pending_calibration_ready_count": len(pending_calibration_batch.get("ready_region_numbers", [])),
            "pending_calibration_review_count": len(pending_calibration_batch.get("review_blocked_region_numbers", [])),
            "ready_for_runtime_pathgraph_promotion": False,
            "real_clicks": sum(int(item.get("real_clicks") or 0) for item in queue_items),
        },
        "pending_calibration_batch": pending_calibration_batch,
        "proposed_states": proposed_states,
        "proposed_transitions": proposed_transitions,
        "review_action_items": review_action_items,
        "blocked_items": blocked_items,
        "next_required_steps": _next_required_steps(
            has_open_detail=bool(open_detail_items),
            has_same_screen=bool(same_screen_items),
            has_geometry=bool(geometry_items),
            has_blockers=bool(non_action_items or other_blocked_items),
            has_pending_calibration=bool(pending_calibration_batch.get("ready_region_numbers")),
        ),
        "display_only": True,
        "candidate_only": True,
        "not_pathgraph_promotion": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "final_submit_forbidden": True,
        "interpretation": (
            "Preflight plan derived from a review-only fused-understanding queue. "
            "It proposes human-review PathGraph wiring only and does not produce a Runtime PathGraph."
        ),
    }
    plan_path = out / PREFLIGHT_NAME
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "learn_fusion_pathgraph_preflight_plan_build_result_v1",
        "preflight_plan_path": str(plan_path.resolve()),
        "calibration_batch_plan_path": _relative_path(batch_plan_file, root) if batch_plan_file is not None else None,
        "summary": plan["summary"],
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _open_detail_transition(*, item: dict[str, Any], index: int) -> dict[str, Any]:
    action_id = f"fusion_open_detail_region_{item.get('region_no') or index + 1}"
    return {
        "contract_version": "learn_fusion_pathgraph_preflight_transition_v1",
        "transition_id": f"preflight_transition_{action_id}",
        "action_template_id": action_id,
        "source_region_no": item.get("region_no"),
        "source_item_id": item.get("source_item_id"),
        "label": item.get("label"),
        "transition_type": "open_detail",
        "semantic_action": "open_detail",
        "from_state_id": "seek_results",
        "to_state_id": "model_detail_view",
        "target_surface": "detail_pane_or_detail_page",
        "requires_post_action_observe": True,
        "required_next_evidence": _list_of_text(item.get("required_next_evidence")),
        "rough_bbox_hint": item.get("rough_bbox_hint") if isinstance(item.get("rough_bbox_hint"), dict) else None,
        "selected_click_point": item.get("selected_click_point") if isinstance(item.get("selected_click_point"), dict) else None,
        "vista_point": item.get("vista_point") if isinstance(item.get("vista_point"), dict) else None,
        "seed_click_point": item.get("seed_click_point") if isinstance(item.get("seed_click_point"), dict) else None,
        "trace_path": item.get("trace_path"),
        "overlay_path": item.get("overlay_path"),
        "no_dispatch": True,
        "candidate_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _review_action_item(*, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "learn_fusion_pathgraph_preflight_action_review_item_v1",
        "region_no": item.get("region_no"),
        "source_item_id": item.get("source_item_id"),
        "label": item.get("label"),
        "role": item.get("role"),
        "review_bucket": item.get("review_bucket"),
        "candidate_semantic_action": item.get("candidate_semantic_action"),
        "required_next_evidence": _list_of_text(item.get("required_next_evidence")),
        "trace_path": item.get("trace_path"),
        "overlay_path": item.get("overlay_path"),
        "candidate_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _blocked_item(*, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "learn_fusion_pathgraph_preflight_blocked_item_v1",
        "region_no": item.get("region_no"),
        "source_item_id": item.get("source_item_id"),
        "label": item.get("label"),
        "role": item.get("role"),
        "review_bucket": item.get("review_bucket"),
        "gate_diagnosis_classification": item.get("gate_diagnosis_classification"),
        "required_next_evidence": _list_of_text(item.get("required_next_evidence")),
        "trace_path": item.get("trace_path"),
        "overlay_path": item.get("overlay_path"),
        "blocked_from_pathgraph_preflight": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _pending_calibration_batch(
    batch_plan: dict[str, Any],
    batch_plan_path: Path | None,
    root: Path,
) -> dict[str, Any]:
    if not isinstance(batch_plan, dict) or not batch_plan:
        return {
            "contract_version": "learn_fusion_pathgraph_pending_calibration_batch_v1",
            "source_batch_plan_path": None,
            "summary": {},
            "ready_region_numbers": [],
            "review_blocked_region_numbers": [],
            "run_command_preview": "",
            "command_executes_now": False,
            "display_only": True,
            "not_calibration_execution": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "interpretation": "No pending calibration batch plan attached.",
        }
    return {
        "contract_version": "learn_fusion_pathgraph_pending_calibration_batch_v1",
        "source_batch_plan_path": _relative_path(batch_plan_path, root) if batch_plan_path is not None else None,
        "summary": dict(batch_plan.get("summary") if isinstance(batch_plan.get("summary"), dict) else {}),
        "ready_region_numbers": _list_of_int(batch_plan.get("ready_region_numbers")),
        "review_blocked_region_numbers": _list_of_int(batch_plan.get("review_blocked_region_numbers")),
        "run_command_preview": _text(batch_plan.get("run_command_preview")),
        "command_executes_now": False,
        "display_only": True,
        "not_calibration_execution": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Pending calibration batch is a review-only prerequisite for improving PathGraph readiness; "
            "this plan does not start models, run dry-runs, click, fill, submit, or promote assets."
        ),
    }


def _next_required_steps(
    *,
    has_open_detail: bool,
    has_same_screen: bool,
    has_geometry: bool,
    has_blockers: bool,
    has_pending_calibration: bool,
) -> list[str]:
    steps: list[str] = []
    if has_pending_calibration:
        steps.append("run_pending_numbered_region_calibration_batch_before_pathgraph_promotion")
    if has_open_detail:
        steps.append("review_open_detail_transition_candidates_before_generating_pathgraph_candidate")
        steps.append("capture_or_attach_detail_observe_after_reviewed_open_detail_no_dispatch")
    if has_same_screen:
        steps.append("review_same_screen_actions_and_link_to_regions_before_candidate_generation")
    if has_geometry:
        steps.append("repair_geometry_or_collect_calibrated_support_before_pathgraph_wiring")
    if has_blockers:
        steps.append("keep_non_action_or_gate_blocked_items_out_of_pathgraph_actions")
    if not steps:
        steps.append("no_pathgraph_preflight_inputs_available")
    return steps


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


def _list_of_text(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _list_of_int(value: Any) -> list[int]:
    result: list[int] = []
    if not isinstance(value, list):
        return result
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a review-only PathGraph preflight plan from a fused-understanding queue.")
    parser.add_argument("--queue", required=True, help="Path to learn_fusion_pathgraph_review_queue.json")
    parser.add_argument("--calibration-batch-plan", help="Optional path to numbered_region_calibration_batch_plan.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    build_pathgraph_preflight_plan(
        queue_path=args.queue,
        calibration_batch_plan_path=args.calibration_batch_plan,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
