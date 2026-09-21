"""Hybrid v1.2 选择审核持久化；不可变、仅用于回放。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image

from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
from app.learn.hybrid.omni_candidates import validate_current_capture_bundle
from app.learn.hybrid.qwen_binding import validate_sealed_omni_inventory
from app.learn.hybrid.selection_review import apply_selection_review_decisions, project_selection_review
from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore
from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task

_STORE = ("artifacts", "uei-shadow-store")


def persist_selection_review_trial(*, project_root: str | Path, payload: dict, response: dict, actual_execution: dict | None = None, refinement_execution: dict | None = None) -> str:
    """验证 replay 输入后封存选择审核父证据，并返回确定性 trial 相对路径。"""
    root = Path(project_root).resolve()
    if not isinstance(payload, dict) or not isinstance(response, dict):
        raise ValueError("selection replay payload and response must be objects")
    origin = _require_payload_origin(payload, actual_execution)
    expected = run_hybrid_selection_task(deepcopy(payload), actual_execution=deepcopy(actual_execution), refinement_execution=deepcopy(refinement_execution))
    if canonical_json_bytes(expected) != canonical_json_bytes(response):
        raise ValueError("selection replay response differs from independently rerun worker")
    if response.get("outcome") != "completed" or not isinstance(response.get("review_projection"), dict):
        raise ValueError("selection replay did not produce a completed review projection")
    bundle = validate_current_capture_bundle(payload["capture_bundle"])
    inventory = validate_sealed_omni_inventory(payload["omni_inventory"])
    if bundle["capture_identity"] != inventory["capture_identity"]:
        raise ValueError("selection replay capture and inventory mismatch")
    run_id, revision = payload.get("run_id"), payload.get("workflow_revision")
    if not isinstance(run_id, str) or not run_id or not isinstance(revision, int) or isinstance(revision, bool):
        raise ValueError("selection replay requires server run_id and workflow_revision")
    verified = load_and_verify_hybrid_capture_bundle(project_root=root, bundle_ref=bundle["bundle_ref"], expected_run_id=run_id, expected_workflow_revision=revision)
    if verified["capture_identity"] != bundle["capture_identity"]:
        raise ValueError("selection replay capture bundle differs from stored parent")
    image_path = _image_under_root(root, payload.get("capture_image_path"))
    _verify_image(image_path, bundle["capture_identity"])
    envelope_ref = persist_selection_review_projection(
        project_root=root,
        parent_evidence=_parents(payload),
        projection=response["review_projection"], actual_execution=actual_execution,
    )
    trial = _trial(root=root, payload=payload, bundle=bundle, image_path=image_path, projection_ref=envelope_ref, execution_origin=origin)
    target = root / "artifacts" / "learning-runs" / "hybrid-selection-review" / f"trial_{_digest(trial)}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(trial)
    if target.exists() and target.read_bytes() != data:
        raise ValueError("selection trial deterministic path conflict")
    if not target.exists():
        target.write_bytes(data)
    return target.relative_to(root).as_posix()


def persist_selection_review_projection(*, project_root: str | Path, parent_evidence: dict, projection: dict, actual_execution: dict | None = None) -> dict[str, str]:
    """仅从可信父证据重放 ledger 后写入不可变 UEI 对象。"""
    root = Path(project_root).resolve()
    parents = _validated_parents(parent_evidence)
    origin = projection.get("execution_origin") if isinstance(projection, dict) else None
    proof = _validated_actual_execution(parents, actual_execution, origin)
    baseline = _rebuild(parents, execution_origin=origin)
    existing = projection.get("review_decisions") if isinstance(projection, dict) else None
    if not isinstance(existing, list):
        raise ValueError("selection review ledger missing")
    rebuilt = apply_selection_review_decisions(
        projection=deepcopy(projection), decisions=[], **parents,
    )
    # 重放完整记录后再次比较，避免存储未经验证的派生字段。
    if canonical_json_bytes(rebuilt) != canonical_json_bytes(projection):
        raise ValueError("selection review projection is not canonical trusted replay")
    identity = {"parents": parents, "projection": projection, "actual_execution": proof}
    envelope = seal_immutable({
        "contract_version": "hybrid_selection_review_record_v1",
        "projection_id": "hybrid-selection-review/" + _digest(identity),
        "parent_evidence": parents,
        "review_projection": deepcopy(projection),
        "capture_lineage_ref": deepcopy(baseline["screen_facts"]["capture_lineage_ref"]),
        "execution_origin": origin,
        "actual_execution": proof,
    })
    return UEIObjectStore(root=root.joinpath(*_STORE)).put(envelope)


def load_selection_review_projection(*, project_root: str | Path, projection_ref: dict[str, str], expected_capture_lineage_ref: dict[str, str] | None, displayed_source_sha256: str, displayed_source_size: dict[str, int]) -> dict[str, Any]:
    """从 UEI 父证据重新构建审核投影，拒绝嵌入式客户端投影。"""
    root = Path(project_root).resolve()
    envelope = UEIObjectStore(root=root.joinpath(*_STORE)).get(projection_ref, contract_version="hybrid_selection_review_record_v1")
    parents = _validated_parents(envelope["parent_evidence"])
    projection = envelope.get("review_projection")
    if not isinstance(projection, dict):
        raise ValueError("stored selection review projection missing")
    origin = envelope.get("execution_origin")
    _validated_actual_execution(parents, envelope.get("actual_execution"), origin)
    replayed = apply_selection_review_decisions(projection=projection, decisions=[], **parents)
    if canonical_json_bytes(replayed) != canonical_json_bytes(projection):
        raise ValueError("stored selection review projection replay mismatch")
    facts = projection.get("screen_facts", {})
    if (
        envelope["projection_id"] != "hybrid-selection-review/" + _digest({"parents": parents, "projection": projection, "actual_execution": envelope.get("actual_execution")})
        or envelope["capture_lineage_ref"] != facts.get("capture_lineage_ref")
        or envelope["execution_origin"] != projection.get("execution_origin")
    ):
        raise ValueError("selection review record identity mismatch")
    if expected_capture_lineage_ref is not None and facts.get("capture_lineage_ref") != expected_capture_lineage_ref:
        raise ValueError("selection review capture lineage mismatch")
    displayed = facts.get("displayed_image", {})
    if displayed.get("sha256") != displayed_source_sha256 or displayed.get("image_size") != displayed_source_size:
        raise ValueError("selection review displayed image mismatch")
    return {"projection": deepcopy(projection), "projection_ref": deepcopy(projection_ref), "regions": selection_review_regions(projection), "status": {"status": "projected", "reason": None}, "parent_evidence": parents, "actual_execution": deepcopy(envelope.get("actual_execution"))}


def validate_selection_trial_binding(*, project_root: Path, source_path: Path, payload: dict) -> None:
    """将审核修订绑定到原始不可变 trial，防止同截图替换目标。"""
    draft = payload.get("draft", payload)
    if not isinstance(draft, dict) or not isinstance(draft.get("hybrid_selection_review_projection_ref"), dict):
        return
    if payload.get("contract_version") == "learning_template_draft_v1":
        if source_path.name != f"trial_{_digest(payload)}.json":
            raise ValueError("selection trial identity mismatch")
        return
    if payload.get("contract_version") != "reviewed_template_candidate_v1":
        raise ValueError("selection review source contract is invalid")
    source = payload.get("source") or {}
    original = _image_under_root(project_root, source.get("original_draft_path"))
    raw = original.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source.get("sha256"):
        raise ValueError("selection original trial identity mismatch")
    original_payload = json.loads(raw.decode("utf-8-sig"))
    if original_payload.get("contract_version") != "learning_template_draft_v1":
        raise ValueError("selection original trial contract mismatch")
    validate_selection_trial_binding(project_root=project_root, source_path=original, payload=original_payload)
    store = UEIObjectStore(root=project_root.joinpath(*_STORE))
    parent = store.get(original_payload["hybrid_selection_review_projection_ref"], contract_version="hybrid_selection_review_record_v1")
    current = store.get(draft["hybrid_selection_review_projection_ref"], contract_version="hybrid_selection_review_record_v1")
    if canonical_json_bytes(parent["parent_evidence"]) != canonical_json_bytes(current["parent_evidence"]):
        raise ValueError("selection review changed original trial parents")


def selection_review_regions(projection: dict) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for item in projection.get("candidates", []):
        if not isinstance(item, dict):
            raise ValueError("selection review candidate invalid")
        bbox = item.get("reviewed_geometry", {}).get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("selection review geometry invalid")
        semantic = item.get("reviewed_semantics", {})
        regions.append({
            "region_id": str(item["candidate_id"]), "candidate_id": item["candidate_id"],
            "label": semantic.get("label") or "", "role": semantic.get("role") or "review_only",
            "kind": "hybrid_selection_review_candidate", "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2]-bbox[0], "h": bbox[3]-bbox[1]},
            "model_proposal": deepcopy(item.get("model_proposal")), "reviewed_geometry": deepcopy(item.get("reviewed_geometry")), "reviewed_semantics": deepcopy(semantic), "review_decisions": deepcopy(item.get("review_decisions", [])),
            "candidate_only": True, "review_only": True, "requires_human_review": True, "grounding_eligible": False,
            "artifact_is_authorization": False, "execute_binding_enabled": False, "final_submit_forbidden": True, "real_action_requires_gate": True,
        })
    return regions


def project_selection_learning(projection: dict) -> dict[str, Any]:
    """只把人工 role/label 作为学习语义；绝不制造状态或动作。"""
    selected = [item for item in projection.get("candidates", []) if isinstance(item, dict) and item.get("selection") is not None]
    missing = [] if selected else ["selection:candidate_id"]
    regions = []
    for item in selected:
        semantic = item.get("reviewed_semantics", {})
        if semantic.get("status") != "human_supplied" or not semantic.get("role") or not semantic.get("label"):
            missing.extend([f"{item.get('candidate_id')}:role", f"{item.get('candidate_id')}:label"])
            continue
        regions.append({"candidate_id": item["candidate_id"], "bbox": deepcopy(item["reviewed_geometry"]["bbox"]), "role": semantic["role"], "label": semantic["label"], "description": semantic.get("description", ""), "source": "human_review"})
    return {"contract_version": "hybrid_selection_learning_projection_v1", "learning_state": "compile_rejected" if missing else "ready_for_learning", "missing_fields": missing, "regions": regions, "state_semantics": "not_fabricated", "action_semantics": "not_fabricated", "artifact_is_authorization": False, "execute_binding_enabled": False, "final_submit_forbidden": True, "real_action_requires_gate": True}


def selection_review_diagnostics(projection: dict) -> dict[str, dict[str, Any]]:
    """从已验证投影派生旧消费者摘要；候选框数与具备学习语义的区域数分开。"""
    if projection.get("contract_version") != "hybrid_selection_review_v1":
        raise ValueError("selection diagnostics require hybrid_selection_review_v1")
    candidates = projection["candidates"]
    edited = [item for item in candidates if item["reviewed_geometry"]["source"] == "human_rebox"]
    passed = failed = unavailable = 0
    for item in edited:
        selection = item["model_proposal"].get("selection")
        point = selection.get("canonical_capture_pixel_point") if isinstance(selection, dict) else None
        if point is None:
            unavailable += 1
            continue
        x1, y1, x2, y2 = item["reviewed_geometry"]["bbox"]
        if x1 <= point[0] <= x2 and y1 <= point[1] <= y2:
            passed += 1
        else:
            failed += 1
    learning = project_selection_learning(projection)
    safety = {"artifact_is_authorization": False, "execute_binding_enabled": False}
    return {
        "manual_bbox_edit_summary": {
            "contract_version": "manual_bbox_edit_summary_v1", "edited_region_count": len(edited),
            "edited_action_count": 0, "edited_total": len(edited),
            "point_inside_bbox_passed": passed, "point_inside_bbox_failed": failed,
            "point_unavailable_count": unavailable, "invalid_geometry_count": 0,
            "point_evidence": "model_original_diagnostic_only", **safety,
        },
        "precise_understanding_summary": {
            "contract_version": "precise_understanding_summary_v1", "state_count": 0,
            "region_count": len(learning["regions"]), "bbox_region_count": len(learning["regions"]),
            "candidate_count": len(candidates), "region_count_scope": "semantically_reviewed_selected_candidates",
            "learning_state": learning["learning_state"], "action_template_count": 0,
            "action_click_point_count": 0, "open_detail_transition_hint_count": 0,
            "blocker_count": 0, "verification_rule_count": 0, "semantic_actions": [],
            "candidate_only": True, "final_submit_forbidden": True, **safety,
            "interpretation": "selection region semantics only; states/actions not supplied; not Execute authorization",
        },
    }


def _parents(payload: dict) -> dict[str, Any]:
    keys = ["capture_bundle", "omni_inventory", "gui_actor_selection_input", "target_text", "refinement_policy"]
    if "vista_refinement_input" in payload:
        keys.append("vista_refinement_input")
    return {key: deepcopy(payload[key]) for key in keys}

def _validated_parents(parents: dict) -> dict[str, Any]:
    required = {"capture_bundle", "omni_inventory", "gui_actor_selection_input", "target_text", "refinement_policy"}
    if not isinstance(parents, dict) or not required <= set(parents) or set(parents) - required - {"vista_refinement_input"}:
        raise ValueError("selection review parent evidence invalid")
    bundle = validate_current_capture_bundle(parents["capture_bundle"])
    inventory = validate_sealed_omni_inventory(parents["omni_inventory"])
    if bundle["capture_identity"] != inventory["capture_identity"] or not isinstance(parents["target_text"], str):
        raise ValueError("selection review parent evidence capture or target invalid")
    # 保留封存父对象原文，验证器的扩展视图不能替换它。
    return _parents(parents)

def _rebuild(parents: dict, *, execution_origin: str) -> dict:
    from app.learn.hybrid.target_selection import parse_gui_actor_selection
    from app.learn.hybrid.selection_refinement import resolve_selection_refinement
    selection = parse_gui_actor_selection(deepcopy(parents["gui_actor_selection_input"]), capture_bundle=parents["capture_bundle"], omni_inventory=parents["omni_inventory"], target_text=parents["target_text"])
    refinement = resolve_selection_refinement(selection=selection, policy=deepcopy(parents["refinement_policy"]), inventory=parents["omni_inventory"], vista_refinement_input=parents.get("vista_refinement_input"))
    return project_selection_review(**parents, selection=selection, refinement=refinement, execution_origin=execution_origin)

def _require_payload_origin(payload: dict, actual_execution: dict | None) -> str:
    origin = payload.get("execution_origin")
    if payload.get("learning_pipeline_mode") != "hybrid_v1_2" or origin not in {"replay", "actual_model"}:
        raise ValueError("selection persistence payload origin is invalid")
    if origin == "replay" and (payload.get("gui_actor_provider_state") != "replay_ready" or actual_execution is not None):
        raise ValueError("selection persistence accepts only replay-ready payloads")
    if origin == "actual_model":
        from app.learn.workflow_tasks.hybrid_selection import validate_actual_execution
        if actual_execution is None: raise ValueError("selection actual execution is required")
        validate_actual_execution(payload, actual_execution)
    if not isinstance(payload.get("capture_image_path"), str): raise ValueError("selection replay capture_image_path missing")
    return origin

def _validated_actual_execution(parents: dict, actual_execution: object, origin: object) -> dict | None:
    if origin == "replay":
        if actual_execution is not None: raise ValueError("selection replay record cannot carry actual proof")
        return None
    if origin != "actual_model" or not isinstance(actual_execution, dict): raise ValueError("selection actual proof missing")
    payload = {**parents, "learning_pipeline_mode": "hybrid_v1_2", "execution_origin": "actual_model", "gui_actor_provider_state": "actual_ready"}
    from app.learn.workflow_tasks.hybrid_selection import validate_actual_execution
    if parents.get("vista_refinement_input") is not None:
        from app.learn.hybrid.selection_refinement import validate_vista_actual_execution
        native = parents["vista_refinement_input"]["provider_result"]
        validate_vista_actual_execution(parents["vista_refinement_input"], native)
    return validate_actual_execution(payload, actual_execution)

def _image_under_root(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value: raise ValueError("selection capture image path invalid")
    path = (root / value).resolve()
    if root not in path.parents or not path.is_file(): raise ValueError("selection capture image must be project-root relative")
    return path

def _verify_image(path: Path, identity: dict) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != identity["screenshot_sha256"]: raise ValueError("selection capture image SHA mismatch")
    with Image.open(path) as image:
        if {"width": image.width, "height": image.height} != identity["image_size"]: raise ValueError("selection capture image dimensions mismatch")

def _trial(*, root: Path, payload: dict, bundle: dict, image_path: Path, projection_ref: dict, execution_origin: str) -> dict:
    return {"contract_version": "learning_template_draft_v1", "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]), "states": [], "regions": [], "action_templates": [], "page_details": {"screen": {"source_image_path": image_path.relative_to(root).as_posix(), "source_image_sha256": bundle["capture_identity"]["screenshot_sha256"]}}, "hybrid_selection_review_projection_ref": deepcopy(projection_ref), "managed_hybrid_selection_lineage": {"run_id": payload["run_id"], "workflow_revision": payload["workflow_revision"], "execution_origin": execution_origin, "learning_pipeline_mode": "hybrid_v1_2"}, "artifact_is_authorization": False, "execute_binding_enabled": False, "final_submit_forbidden": True, "real_action_requires_gate": True}
def _digest(value: object) -> str: return hashlib.sha256(canonical_json_bytes(value)).hexdigest()

__all__ = ["persist_selection_review_trial", "persist_selection_review_projection", "load_selection_review_projection", "selection_review_regions", "project_selection_learning"]
