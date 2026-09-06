"""顺序调用真实模型并接入既有审核存储；不提供动作授权。"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
from app.learn.hybrid.gui_actor_current_source import GuiActorCurrentSourceError, run_gui_actor_once
from app.learn.hybrid.omni_discovery import run_hybrid_omni_discovery
from app.learn.hybrid.selection_persistence import persist_selection_review_trial
from app.learn.hybrid.refinement_policy import decide_refinement, MODES_POLICY_VERSION, EDGE_TRIGGER_VERSION, EDGE_MARGIN_RATIO
from app.learn.hybrid.selection_refinement import build_selection_roi_request, prepare_selection_roi
from app.learn.hybrid.target_selection import parse_gui_actor_selection
from app.learn.hybrid.vista_current_source import run_vista_once, VistaCurrentSourceError
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.omniparser_shadow_adapter import (
    PROVIDER_ID, PROFILE_ID, PROVIDER_VERSION, TrustedOmniParserConfiguration,
)
from app.learn.recognition.uei.store import UEIObjectStore
from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task, validate_actual_execution


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def selection_geometry_trigger(*, selection: dict, inventory: dict) -> dict:
    """冻结的边距启发式，不利用 gold、模型分数或语义置信度。"""
    record = {"contract_version": EDGE_TRIGGER_VERSION, "threshold_ratio": EDGE_MARGIN_RATIO,
              "triggered": False, "minimum_edge_margin_ratio": None, "source_score_used": False,
              "capture_sha256": selection["capture"]["image_sha256"], "candidate_id": selection["candidate_id"],
              "reason": "no_unique_selection", "parent_refs": deepcopy(selection["parent_refs"])}
    if selection["selection_status"] != "selected":
        return record
    candidate = next(c for c in inventory["candidates"] if c["candidate_id"] == selection["candidate_id"])
    x1, y1, x2, y2 = candidate["bbox_original"]
    x, y = selection["model_proposal"]["canonical_capture_pixel_point"]
    margin = min((x-x1)/(x2-x1), (x2-x)/(x2-x1), (y-y1)/(y2-y1), (y2-y)/(y2-y1))
    return {**record, "minimum_edge_margin_ratio": margin, "triggered": margin <= EDGE_MARGIN_RATIO,
            "reason": "point_within_ten_percent_border" if margin <= EDGE_MARGIN_RATIO else "point_inside_inner_eighty_percent",
            "candidate_bbox_original": deepcopy(candidate["bbox_original"])}


def _omni_parents(root: Path, bundle: dict) -> dict:
    """封存实际调用所需注册信息，不制造识别结果。"""
    store = UEIObjectStore(root=root / "artifacts/uei-shadow-store")
    token = bundle["capture_identity"]["capture_id"].replace("/", "-")
    values = {
        "request_ref": {
            "contract_version": "screen_parse_request_v1", "request_id": "request/selection-omni/" + token,
            "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
            "requested_profiles": [{"provider_id": PROVIDER_ID, "profile_id": PROFILE_ID, "mode": "Shadow"}],
            "privacy_policy": "restricted", "requester_id": "server",
        },
        "registration_ref": {
            "contract_version": "trusted_provider_registration_v1", "registration_id": "registration/selection/omniparser/v2",
            "provider_id": PROVIDER_ID, "profile_ids": [PROFILE_ID], "enabled": True,
            "allowed_modes": ["Shadow"], "allowed_privacy_policies": ["restricted"],
            "egress_policy": "local_only", "wire_payload_policy": "restricted_store_only",
            "safe_payload_limits": {"max_json_bytes": 1048576, "max_depth": 16, "max_array_items": 10000,
                "max_object_properties": 64, "max_string_chars": 4096,
                "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"]},
            "required_conformance_suite": "uei-v1-static-projection",
        },
        "manifest_ref": {
            "contract_version": "provider_manifest_v1", "manifest_id": "manifest/selection/omniparser/v2",
            "provider_id": PROVIDER_ID, "provider_version": PROVIDER_VERSION,
            "profiles": [{"profile_id": PROFILE_ID, "operation": "screen_parse",
                "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1",
                "declared_output_kinds": ["element", "icon"],
                "supported_coordinate_spaces": ["capture_pixel_xyxy"], "supports_capture_artifact": True,
                "privacy_capabilities": ["restricted"], "mode_allowlist": ["Shadow"]}],
        },
    }
    return {key: store.put(seal_immutable(value)) for key, value in values.items()}


def run_actual_selection(*, project_root: str | Path, run_id: str, workflow_revision: int,
                         capture_bundle_ref: dict, image_path: str | Path, target_text: str,
                         omni_configuration: TrustedOmniParserConfiguration,
                         artifact_root: str | Path, out_dir: str | Path,
                         refinement_mode: str = "conditional") -> dict[str, Any]:
    """仅服务器内部入口可持有运行结果；客户端不能提供 actual proof。"""
    started = time.monotonic()
    if refinement_mode not in {"never", "conditional", "always"}:
        raise ValueError("actual selection refinement_mode is invalid")
    root = Path(project_root).resolve()
    image = (root / image_path).resolve()
    output = (root / out_dir).resolve()
    if not image.is_relative_to(root) or not output.is_relative_to(root):
        raise ValueError("actual selection paths escaped project root")
    if not isinstance(target_text, str) or not target_text.strip():
        raise ValueError("actual selection target_text is required")
    bundle = load_and_verify_hybrid_capture_bundle(
        project_root=root, bundle_ref=capture_bundle_ref,
        expected_run_id=run_id, expected_workflow_revision=workflow_revision,
    )
    bundle = {**bundle, "bundle_ref": deepcopy(capture_bundle_ref)}
    if sha256(image.read_bytes()).hexdigest() != bundle["capture_identity"]["screenshot_sha256"]:
        raise ValueError("actual selection image SHA mismatch")
    output.mkdir(parents=True, exist_ok=False)
    payload = {"project_root": str(root), "run_id": run_id, "workflow_revision": workflow_revision,
               "hybrid_capture_bundle_ref": deepcopy(capture_bundle_ref),
               "capture_image_path": image.relative_to(root).as_posix(), **_omni_parents(root, bundle)}
    _json(output / "request.json", {**payload, "target_text": target_text, "execution_origin": "actual_model", "refinement_mode": refinement_mode})
    omni = run_hybrid_omni_discovery(payload, configuration=omni_configuration)
    _json(output / "omni-result.json", omni)
    result = {"contract_version": "hybrid_selection_actual_run_v1", "execution_origin": "actual_model",
              "outcome": "safe_stopped", "trial_path": None, "artifact_is_authorization": False,
              "execute_binding_enabled": False, "final_submit_forbidden": True,
              "refinement_mode": refinement_mode, "canonical_capture_pixel_point": None,
              "original_capture_pixel_point": None, "refinement_trigger": None}
    if omni.get("outcome") != "completed" or omni.get("cleanup_status") != "clean":
        result["reason"] = "omni_failed_or_cleanup_unverified"
        _json(output / "result.json", result)
        return result
    # Omni 已退出后才启动选择模型，不能用旧报告代替本次调用。
    try:
        actor = run_gui_actor_once(project_root=root, image_path=image, target_text=target_text,
                                   artifact_root=Path(artifact_root), out_dir=output / "gui-actor")
    except (GuiActorCurrentSourceError, OSError) as error:
        result["reason"] = "gui_actor_failed: " + str(error)
        result["gui_actor_failure_artifact"] = "gui-actor/failure-result.json" if (output / "gui-actor/failure-result.json").is_file() else None
        _json(output / "result.json", result)
        return result
    native = {name: deepcopy(actor[name]) for name in (
        "raw_output_utf8", "native_output_ref", "provider_id", "native_profile", "source_score", "image_sha256",
    )}
    native["capture_id"] = bundle["capture_identity"]["capture_id"]
    selection_payload = {
        "learning_pipeline_mode": "hybrid_v1_2", "execution_origin": "actual_model",
        "gui_actor_provider_state": "actual_ready", "run_id": run_id, "workflow_revision": workflow_revision,
        "capture_bundle": bundle, "capture_image_path": payload["capture_image_path"],
        "omni_inventory": omni["inventory"], "target_text": target_text, "gui_actor_selection_input": native,
        "refinement_policy": {"policy_version": MODES_POLICY_VERSION, "mode": refinement_mode, "geometric_trigger": False},
    }
    vista = None
    try:
        # 清理与来源验证必须先于下一个模型启动，不能靠后续保存发现重叠进程。
        validate_actual_execution(selection_payload, actor)
        selection = parse_gui_actor_selection(native, capture_bundle=bundle, omni_inventory=omni["inventory"], target_text=target_text)
        trigger = selection_geometry_trigger(selection=selection, inventory=omni["inventory"])
        selection_payload["refinement_policy"]["geometric_trigger"] = trigger["triggered"]
        result["refinement_trigger"] = trigger
        result["original_capture_pixel_point"] = deepcopy(selection["model_proposal"]["canonical_capture_pixel_point"])
        _json(output / "refinement-policy.json", {"policy": selection_payload["refinement_policy"], "trigger": trigger})
        if decide_refinement(selection=selection, policy=selection_payload["refinement_policy"])["status"] == "requested":
            request = build_selection_roi_request(selection=selection, inventory=omni["inventory"])
            roi_path = output / "vista-roi.png"
            roi_sha = prepare_selection_roi(request=request, image_path=image, output_path=roi_path)
            vista = run_vista_once(project_root=root, image_path=roi_path, target_text=target_text, out_dir=output / "vista")
            selection_payload["vista_refinement_input"] = {
                "contract_version": "hybrid_selection_vista_input_v1", "request": request,
                "roi_image_sha256": roi_sha, "provider_result": vista,
            }
        response = run_hybrid_selection_task(selection_payload, actual_execution=actor, refinement_execution=vista)
    except (VistaCurrentSourceError, ValueError, OSError) as error:
        result["reason"] = "selection_or_refinement_failed: " + str(error)
        result["vista_failure_artifact"] = "vista/failure-result.json" if (output / "vista/failure-result.json").is_file() else None
        result["end_to_end_seconds"] = time.monotonic() - started
        _json(output / "result.json", result)
        return result
    _json(output / "selection-result.json", response)
    if response.get("outcome") != "completed":
        result["reason"] = response.get("reason", "selection_not_completed")
    else:
        trial = persist_selection_review_trial(project_root=root, payload=selection_payload,
                                               response=response, actual_execution=actor, refinement_execution=vista)
        refinement = response["refinement"]
        point = (refinement["provider_result"]["canonical_capture_pixel_point"] if refinement["status"] == "validated"
                 else result["original_capture_pixel_point"] if refinement["status"] == "skipped" and response["selection"]["selection_status"] == "selected" else None)
        result.update(outcome="completed", trial_path=trial,
                      selection_status=response["selection"]["selection_status"],
                      refinement_status=response["refinement"]["status"],
                      learning_state=response["review_projection"]["learning_state"], canonical_capture_pixel_point=deepcopy(point))
    result["end_to_end_seconds"] = time.monotonic() - started
    _json(output / "result.json", result)
    return result
