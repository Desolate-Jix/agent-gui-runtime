"""GUIActor 选择后的 VISTA ROI 协议；不依赖 Qwen，不产生动作授权。"""
from copy import deepcopy
from hashlib import sha256
from math import ceil, floor
from pathlib import Path
import re

from PIL import Image

from app.learn.hybrid.refinement_policy import decide_refinement
from app.learn.hybrid.vista_current_source import parse_vista_normalized_pair, VistaCurrentSourceError
from app.learn.recognition.uei.canonical import canonical_json_bytes


def build_selection_roi_request(*, selection: dict, inventory: dict) -> dict:
    """复用冻结基线的 enclosing crop，不扩框、不缩放、不改变原候选。"""
    if selection.get("selection_status") != "selected":
        raise ValueError("VISTA requires a uniquely selected candidate")
    candidates = [c for c in inventory["candidates"] if c["candidate_id"] == selection["candidate_id"] and c["active"]]
    if len(candidates) != 1:
        raise ValueError("VISTA selected candidate is not uniquely active")
    bbox = candidates[0]["bbox_original"]
    capture = selection["capture"]
    if inventory["capture_identity"]["capture_id"] != capture["capture_id"]:
        raise ValueError("VISTA candidate capture differs")
    return {
        "contract_version": "hybrid_selection_vista_request_v1",
        "candidate_id": selection["candidate_id"], "capture_id": capture["capture_id"],
        "capture_sha256": capture["image_sha256"], "image_size": deepcopy(capture["image_size"]),
        "target_sha256": sha256(selection["target_text"].encode("utf-8")).hexdigest(),
        "candidate_bbox_original": deepcopy(bbox),
        "roi_bbox": [floor(bbox[0]), floor(bbox[1]), ceil(bbox[2]), ceil(bbox[3])],
        "crop_policy": "capture_pixel_enclosing_crop_floor_ceil",
        "coordinate_space": "vista_normalized_0_1000_roi_to_capture_v1",
        "parent_refs": deepcopy(selection["parent_refs"]),
    }


def prepare_selection_roi(*, request: dict, image_path: Path, output_path: Path) -> str:
    """验证原图后生成确定性 ROI；返回实际 PNG 摘要。"""
    image_path, output_path = Path(image_path), Path(output_path)
    if sha256(image_path.read_bytes()).hexdigest() != request["capture_sha256"]:
        raise ValueError("VISTA ROI source image SHA differs")
    with Image.open(image_path) as image:
        if {"width": image.width, "height": image.height} != request["image_size"]:
            raise ValueError("VISTA ROI source image dimensions differ")
        roi = image.crop(tuple(request["roi_bbox"])).convert("RGB")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            raise ValueError("VISTA ROI output already exists")
        roi.save(output_path, format="PNG")
    return sha256(output_path.read_bytes()).hexdigest()


def resolve_selection_refinement(*, selection: dict, policy: dict, inventory: dict, vista_refinement_input: dict | None = None) -> dict:
    decision = decide_refinement(selection=selection, policy=policy)
    if vista_refinement_input is None:
        return decision
    if decision["status"] != "requested":
        raise ValueError("VISTA evidence supplied when refinement was not requested")
    value = vista_refinement_input
    if not isinstance(value, dict) or set(value) != {"contract_version", "request", "roi_image_sha256", "provider_result"} or value["contract_version"] != "hybrid_selection_vista_input_v1":
        raise ValueError("VISTA selection input is not closed")
    request = build_selection_roi_request(selection=selection, inventory=inventory)
    if canonical_json_bytes(value["request"]) != canonical_json_bytes(request):
        raise ValueError("VISTA request differs from selected capture parents")
    native = value["provider_result"]
    if not isinstance(native, dict) or native.get("contract_version") != "vista_current_source_result_v1" or native.get("provider_id") != "vista_4b" or native.get("source_score") is not None:
        raise ValueError("VISTA native provider contract differs")
    raw, ref = native.get("raw_output_utf8"), native.get("native_output_ref")
    if not isinstance(raw, str) or not isinstance(ref, dict) or not isinstance(ref.get("id"), str) or ref.get("sha256") != sha256(raw.encode("utf-8")).hexdigest():
        raise ValueError("VISTA native output SHA differs")
    image_sha = value["roi_image_sha256"]
    if not isinstance(image_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", image_sha) or native.get("roi_image_sha256") != image_sha:
        raise ValueError("VISTA native ROI image SHA differs")
    if native.get("target_sha256") != request["target_sha256"]:
        raise ValueError("VISTA native target SHA differs")
    point = None
    try:
        normalized = parse_vista_normalized_pair(raw)
        left, top, right, bottom = request["roi_bbox"]
        projected = [round(left + (right-left)*normalized[0]/1000), round(top + (bottom-top)*normalized[1]/1000)]
        x1, y1, x2, y2 = request["candidate_bbox_original"]
        if not (left < projected[0] < right and top < projected[1] < bottom and x1 < projected[0] < x2 and y1 < projected[1] < y2):
            raise VistaCurrentSourceError("VISTA point is not strictly inside original candidate and ROI")
        point, reason = projected, "validated_inside_original_candidate_and_roi"
    except VistaCurrentSourceError as error:
        reason = str(error)
    return {
        **decision, "status": "validated" if point is not None else "review_required", "reason": reason,
        "provider_result": {"provider_id": "vista_4b", "raw_output_utf8": raw, "native_output_ref": deepcopy(ref),
                            "request": request, "roi_image_sha256": image_sha,
                            "canonical_capture_pixel_point": point, "source_score": None,
                            "artifact_is_authorization": False, "execute_binding_enabled": False},
    }


def validate_vista_actual_execution(vista_input: dict, actual_execution: dict | None) -> None:
    """实际任务须有服务器持有的 runner 结果；记录加载时再验证其身份和清理。"""
    native = vista_input["provider_result"]
    if not isinstance(actual_execution, dict) or canonical_json_bytes(actual_execution) != canonical_json_bytes(native):
        raise ValueError("VISTA actual execution required or differs")
    receipt = native.get("current_source_receipt", {})
    cleanup = native.get("cleanup", {})
    if receipt.get("contract_version") != "vista_current_source_receipt_v1" or not receipt.get("code_identity"):
        raise ValueError("VISTA current-source identity missing")
    if cleanup.get("status") != "verified_exact_child_killed" or cleanup.get("owned_tree_exited") is not True or cleanup.get("listener_absent") is not True:
        raise ValueError("VISTA actual cleanup unverified")
    if native.get("execute_binding_enabled") is not False or native.get("artifact_is_authorization") is not False:
        raise ValueError("VISTA result must remain non-authorizing")
