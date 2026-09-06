"""选择结果的审核投影；所有输出均为只读、非授权证据。"""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
import math
from typing import Any
from app.learn.hybrid.omni_candidates import validate_current_capture_bundle
from app.learn.hybrid.qwen_binding import validate_sealed_omni_inventory
from app.learn.hybrid.refinement_policy import decide_refinement
from app.learn.hybrid.selection_refinement import resolve_selection_refinement
from app.learn.hybrid.target_selection import parse_gui_actor_selection
from app.learn.recognition.uei.canonical import canonical_json_bytes

_NON_AUTHORIZING = {"artifact_is_authorization": False, "execute_binding_enabled": False, "final_submit_forbidden": True, "real_action_requires_gate": True, "authorization_scope": "display_and_review_only"}

def project_selection_review(*, capture_bundle: dict, omni_inventory: dict, gui_actor_selection_input: dict, target_text: str, refinement_policy: dict, selection: dict, refinement: dict, execution_origin: str = "replay", vista_refinement_input: dict | None = None) -> dict:
    """使用独立受信 raw/policy 重算审核父证据。"""
    if execution_origin not in {"replay", "actual_model"}: raise ValueError("selection review execution_origin is invalid")
    bundle = validate_current_capture_bundle(capture_bundle)
    inventory = validate_sealed_omni_inventory(omni_inventory)
    capture = bundle["capture_identity"]
    if capture != inventory["capture_identity"]: raise ValueError("selection review capture identity mismatch")
    expected_selection = parse_gui_actor_selection(deepcopy(gui_actor_selection_input), capture_bundle=bundle, omni_inventory=omni_inventory, target_text=target_text)
    if canonical_json_bytes(expected_selection) != canonical_json_bytes(selection): raise ValueError("selection review selection evidence mismatch")
    expected_refinement = resolve_selection_refinement(selection=expected_selection, policy=deepcopy(refinement_policy), inventory=inventory, vista_refinement_input=vista_refinement_input)
    if canonical_json_bytes(expected_refinement) != canonical_json_bytes(refinement): raise ValueError("selection review refinement evidence mismatch")
    return {"contract_version": "hybrid_selection_review_v1", "execution_origin": execution_origin, "screen_facts": {"execution_origin": execution_origin, "capture_id": capture["capture_id"], "capture_lineage_ref": deepcopy(capture["capture_lineage_ref"]), "displayed_image": {"sha256": capture["screenshot_sha256"], "image_size": deepcopy(capture["image_size"])}, "coordinate_space": capture["capture_coordinate_space"], "warnings": ["semantic_evidence_missing"]}, "parent_refs": deepcopy(expected_selection["parent_refs"]), "selection": deepcopy(expected_selection), "refinement": deepcopy(expected_refinement), "candidates": [_candidate_projection(candidate, expected_selection, expected_refinement) for candidate in inventory["candidates"]], "review_decisions": [], "learning_state": "needs_semantic_review", **_NON_AUTHORIZING}

def apply_selection_review_decisions(projection: dict, *, decisions: list[dict], capture_bundle: dict, omni_inventory: dict, gui_actor_selection_input: dict, target_text: str, refinement_policy: dict, vista_refinement_input: dict | None = None) -> dict:
    """从受信父证据重建并重放 ledger 后才允许追加人工修订。"""
    if not isinstance(projection, Mapping) or projection.get("contract_version") != "hybrid_selection_review_v1" or not isinstance(decisions, list): raise ValueError("selection review projection or decisions are invalid")
    expected_selection = parse_gui_actor_selection(deepcopy(gui_actor_selection_input), capture_bundle=deepcopy(capture_bundle), omni_inventory=deepcopy(omni_inventory), target_text=target_text)
    expected_refinement = resolve_selection_refinement(selection=expected_selection, policy=deepcopy(refinement_policy), inventory=omni_inventory, vista_refinement_input=vista_refinement_input)
    origin = projection.get("execution_origin")
    baseline = project_selection_review(capture_bundle=deepcopy(capture_bundle), omni_inventory=deepcopy(omni_inventory), gui_actor_selection_input=deepcopy(gui_actor_selection_input), target_text=target_text, refinement_policy=deepcopy(refinement_policy), selection=expected_selection, refinement=expected_refinement, execution_origin=origin, vista_refinement_input=vista_refinement_input)
    stored = projection.get("review_decisions")
    if not isinstance(stored, list): raise ValueError("selection review decision ledger is invalid")
    replayed = _apply_decisions_unchecked(baseline, [_unrecorded_decision(value) for value in stored])
    if canonical_json_bytes(replayed) != canonical_json_bytes(projection): raise ValueError("selection review projection differs from trusted replay")
    return _apply_decisions_unchecked(replayed, decisions)

def _unrecorded_decision(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping): raise ValueError("selection review stored decision is invalid")
    result = deepcopy(dict(value)); result.pop("decision_index", None); result.pop("source", None); return result

def _apply_decisions_unchecked(projection: dict, decisions: list[dict]) -> dict:
    result = deepcopy(dict(projection)); candidates, ledger = result.get("candidates"), result.get("review_decisions")
    if not isinstance(candidates, list) or not isinstance(ledger, list): raise ValueError("selection review decision ledger is invalid")
    by_id = {item.get("candidate_id"): item for item in candidates if isinstance(item, dict)}
    if len(by_id) != len(candidates): raise ValueError("selection review candidate identities are invalid")
    existing = {item.get("decision_id") for item in ledger if isinstance(item, dict)}
    image_size = result["screen_facts"]["displayed_image"]["image_size"]; width, height = image_size["width"], image_size["height"]
    for value in decisions:
        decision = _validated_decision(value, width=width, height=height)
        if decision["decision_id"] in existing: raise ValueError("duplicate selection review decision_id")
        candidate = by_id.get(decision["candidate_id"])
        if candidate is None: raise ValueError("unknown selection review candidate")
        existing.add(decision["decision_id"]); recorded = {**decision, "decision_index": len(ledger) + 1, "source": "human_review"}; candidate["review_decisions"].append(deepcopy(recorded))
        if decision["decision_type"] == "rebox": candidate["reviewed_geometry"] = {"bbox": deepcopy(decision["bbox"]), "coordinate_space": "capture_pixel_xyxy", "source": "human_rebox", "revision": len(candidate["review_decisions"])}
        else: candidate["reviewed_semantics"] = {**deepcopy(decision["semantics"]), "status": "human_supplied", "provider_id": None, "revision": len(candidate["review_decisions"])}
        ledger.append(recorded)
    return result

def _candidate_projection(candidate: Mapping[str, Any], selection: Mapping[str, Any], refinement: Mapping[str, Any]) -> dict[str, Any]:
    selected = candidate["candidate_id"] == selection.get("candidate_id")
    return {"candidate_id": candidate["candidate_id"], "model_proposal": {"bbox_original": deepcopy(candidate["bbox_original"]), "coordinate_space": candidate["coordinate_space"], "omni_candidate": deepcopy(dict(candidate)), "selection": deepcopy(selection["model_proposal"]) if selected else None}, "selection": deepcopy(selection) if selected else None, "refinement": deepcopy(refinement) if selected else {"status": "not_requested", "reason": "candidate_not_selected"}, "reviewed_geometry": {"bbox": deepcopy(candidate["bbox_original"]), "coordinate_space": candidate["coordinate_space"], "source": "model_original", "revision": 0}, "reviewed_semantics": {"status": "missing", "role": None, "label": None, "description": None, "provider_id": None}, "warnings": (["selected_candidate", "missing_semantics"] if selected else ["missing_semantics"]), "review_decisions": [], **_NON_AUTHORIZING}

def _validated_decision(value: object, *, width: int, height: int) -> dict[str, Any]:
    if not isinstance(value, Mapping): raise ValueError("selection review decision is invalid")
    decision = deepcopy(dict(value)); kind = decision.get("decision_type"); expected = {"rebox": {"decision_id", "decision_type", "candidate_id", "bbox"}, "semantic_edit": {"decision_id", "decision_type", "candidate_id", "semantics"}}.get(kind)
    if expected is None or set(decision) != expected or not isinstance(decision.get("decision_id"), str) or not decision["decision_id"].startswith("decision/") or not isinstance(decision.get("candidate_id"), str): raise ValueError("selection review decision is invalid")
    if kind == "rebox":
        bbox = decision["bbox"]
        if not isinstance(bbox, list) or len(bbox) != 4 or any(isinstance(edge, bool) or not isinstance(edge, (int, float)) or not math.isfinite(float(edge)) for edge in bbox) or not (0 <= bbox[0] < bbox[2] <= width and 0 <= bbox[1] < bbox[3] <= height): raise ValueError("selection review bbox is invalid")
    else:
        semantics = decision["semantics"]
        if not isinstance(semantics, Mapping) or set(semantics) != {"role", "label", "description"} or not all(isinstance(semantics[key], str) for key in semantics) or not semantics["role"].strip() or not semantics["label"].strip(): raise ValueError("selection review semantics are invalid")
        decision["semantics"] = {key: semantics[key].strip() for key in ("role", "label", "description")}
    return decision
__all__ = ["apply_selection_review_decisions", "project_selection_review"]
