from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PROPOSAL_NAME = "learn_fusion_review_patch_proposal.json"


def build_review_patch_proposal(
    *,
    preflight_plan_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    plan_file = _resolve_path(preflight_plan_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    plan = _read_json(plan_file)
    patch = _review_patch_from_preflight(plan)
    proposal = {
        "contract_version": "learn_fusion_review_patch_proposal_v1",
        "preflight_plan_path": _relative_path(plan_file, root),
        "summary": {
            "state_additions": len(patch["state_additions"]),
            "region_additions": len(patch["region_additions"]),
            "action_template_additions": len(patch["action_template_additions"]),
            "transition_additions": len(patch["transition_additions"]),
            "blockers": len(patch["blockers"]),
            "verification_rules": len(patch["verification_rules"]),
            "review_status": patch["review_status"],
            "ready_for_runtime_pathgraph_promotion": False,
        },
        "review_patch": patch,
        "display_only": True,
        "candidate_only": True,
        "not_pathgraph_promotion": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Review patch proposal for a human reviewer. It may be passed to save_reviewed_template_candidate "
            "after review, but it does not itself write a reviewed candidate or authorize execution."
        ),
    }
    proposal_path = out / PROPOSAL_NAME
    proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "learn_fusion_review_patch_proposal_build_result_v1",
        "proposal_path": str(proposal_path.resolve()),
        "summary": proposal["summary"],
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _review_patch_from_preflight(plan: dict[str, Any]) -> dict[str, Any]:
    transitions = _list_of_dicts(plan.get("proposed_transitions"))
    detail_state_ids = {
        _text(item.get("to_state_id"))
        for item in transitions
        if _text(item.get("to_state_id")) and _text(item.get("transition_type")) == "open_detail"
    }
    states = [
        _review_only_item(item)
        for item in _list_of_dicts(plan.get("proposed_states"))
        if _text(item.get("state_id")) in detail_state_ids
    ]
    actions = [_action_addition_from_transition(item) for item in transitions]
    transition_additions = [_transition_addition(item) for item in transitions]
    return {
        "review_status": "needs_human_review",
        "source_after_review": "assisted_generation",
        "state_additions": states,
        "region_additions": _region_additions_from_transitions(transitions),
        "action_template_additions": actions,
        "transition_additions": transition_additions,
        "blockers": _blockers_from_plan(plan),
        "verification_rules": _verification_rules_from_transitions(transitions),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
    }


def _action_addition_from_transition(transition: dict[str, Any]) -> dict[str, Any]:
    item = {
        "action_template_id": transition.get("action_template_id"),
        "label": transition.get("label") or "Open detail candidate",
        "semantic_action": transition.get("semantic_action") or "open_detail",
        "action_type": "click",
        "target_entity": transition.get("source_item_id") or transition.get("source_region_no"),
        "source_region_no": transition.get("source_region_no"),
        "source_item_id": transition.get("source_item_id"),
        "transition_hint": {
            "contract_version": "learn_open_detail_transition_hint_v1",
            "transition_type": "open_detail",
            "expected_next_state_role": "detail_view",
            "target_surface": transition.get("target_surface") or "detail_pane_or_detail_page",
            "requires_post_action_observe": True,
            "candidate_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
    }
    return _review_only_item(item)


def _region_additions_from_transitions(transitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for transition in transitions:
        region_id = _text(transition.get("source_item_id")) or f"fusion_region_{transition.get('source_region_no')}"
        bbox = transition.get("rough_bbox_hint")
        if not region_id or region_id in seen or not isinstance(bbox, dict):
            continue
        region = {
            "region_id": region_id,
            "label": transition.get("label") or region_id,
            "role": "card",
            "semantic_role": "open_detail_source",
            "bbox": bbox,
            "click_point": transition.get("selected_click_point")
            if isinstance(transition.get("selected_click_point"), dict)
            else transition.get("vista_point"),
            "source_region_no": transition.get("source_region_no"),
            "source_item_id": transition.get("source_item_id"),
        }
        regions.append(_review_only_item(region))
        seen.add(region_id)
    return regions


def _transition_addition(transition: dict[str, Any]) -> dict[str, Any]:
    item = {
        "transition_id": transition.get("transition_id"),
        "transition_type": transition.get("transition_type") or "open_detail",
        "from_state_id": transition.get("from_state_id") or "seek_results",
        "to_state_id": transition.get("to_state_id") or "model_detail_view",
        "action_template_id": transition.get("action_template_id"),
        "target_surface": transition.get("target_surface") or "detail_pane_or_detail_page",
        "requires_post_action_observe": True,
    }
    return _review_only_item(item)


def _blockers_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in _list_of_dicts(plan.get("blocked_items")):
        blockers.append(
            _review_only_item(
                {
                    "blocker_id": f"preflight_block_region_{item.get('region_no') or item.get('source_item_id')}",
                    "label": item.get("label") or "Blocked before PathGraph wiring",
                    "reason": item.get("review_bucket") or "blocked_before_pathgraph_wiring",
                    "linked_region_no": item.get("region_no"),
                    "linked_source_item_id": item.get("source_item_id"),
                }
            )
        )
    return blockers


def _verification_rules_from_transitions(transitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for transition in transitions:
        action_id = _text(transition.get("action_template_id"))
        if not action_id:
            continue
        rules.append(
            _review_only_item(
                {
                    "rule_id": f"verify_detail_observe_after_{action_id}",
                    "label": "Re-observe detail surface after reviewed open_detail candidate",
                    "linked_action_template_id": action_id,
                    "expected_next_state_role": "detail_view",
                    "requires_post_action_observe": True,
                }
            )
        )
    return rules


def _review_only_item(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    result["candidate_only"] = True
    result["artifact_is_authorization"] = False
    result["execute_binding_enabled"] = False
    result["final_submit_forbidden"] = True
    result["real_action_requires_gate"] = True
    result["requires_human_review"] = True
    return result


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
    parser = argparse.ArgumentParser(description="Build a review-patch proposal from a PathGraph preflight plan.")
    parser.add_argument("--preflight-plan", required=True, help="Path to learn_fusion_pathgraph_preflight_plan.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    build_review_patch_proposal(preflight_plan_path=args.preflight_plan, out_dir=args.out, json_stdout=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
