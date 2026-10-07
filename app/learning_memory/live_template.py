"""将当前截图模板定位适配到原执行路由；不包含任何输入实现。"""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import hashlib
import re


_LIBRARY = ContextVar("execution_memory_library", default=None)


def validate_template_reference(value):
    if not isinstance(value, dict) or set(value) != {"template_id", "interface_key", "state_key"}:
        raise ValueError("template_memory requires template_id/interface_key/state_key only")
    for key, pattern in (("template_id", r"template-[0-9a-f]{64}"),
                         ("interface_key", r"[a-z0-9][a-z0-9_-]{0,79}"),
                         ("state_key", r"[a-z0-9][a-z0-9_-]{0,79}")):
        if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
            raise ValueError("invalid template_memory." + key)
    return value


@contextmanager
def template_library_scope(root):
    # 来源由本机宿主设置，不接受 Agent 传入磁盘目录。
    token = _LIBRARY.set(Path(root).resolve() if root is not None else None)
    try:
        yield
    finally:
        _LIBRARY.reset(token)


def plan_current_template(reference, image_path, live_capture):
    from .workspace import MemoryWorkspace
    from .templates import match_template_frame
    root = _LIBRARY.get()
    if root is None:
        raise ValueError("template memory requires a configured local execution host")
    validate_template_reference(reference)
    if not live_capture or Path(live_capture["image_path"]).resolve() != Path(image_path).resolve():
        raise ValueError("template execution requires the route's current live capture")
    path = Path(image_path).resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    frame = {**live_capture, "image_path": str(path), "sha256": digest}
    with MemoryWorkspace(root) as library:
        result = match_template_frame(library, {**reference, "frame_sha256": digest}, path, frame)
    result["frame_origin"] = "execution_route_live_capture"
    if result["status"] != "matched":
        return None, result
    candidate = result["candidate"]
    candidate["freshness"] = "current_route_capture"
    identity = reference["template_id"]
    point, bbox = candidate["click_point"], candidate["bbox"]
    # 这里只产生本次图上的候选；后续仍走原有选点、窗口验证、点击与后图回执。
    plan = {"contract_version": "memory_template_recognition_plan_v1", "image_path": str(path),
        "parse_result": {"vision_regions": {"image_size": result["viewport_size"]}},
        "candidate_result": {"recommended_candidate_id": identity, "candidates": [{
            "candidate_id": identity, "element_id": identity, "eligible": True,
            "score": candidate["score"], "refined_bbox": bbox, "bbox_refine_reason": "matched_template_target_offset",
            "text": result["label"], "element": {"element_id": identity, "bbox": bbox,
                                                    "text": result["label"], "role": "button"}}], "rejected": []},
        "narrow_search_result": {"results": [{"candidate_id": identity, "element_id": identity,
            "status": "grounded", "refined_click_point": point,
            "coordinate_source": "current_capture_template_match", "reasons": ["unique_local_template_match"]}]},
        "pre_click_decision": {"allowed": True, "selected_candidate_id": identity,
            "selected_click_point": point, "reasons": ["unique_local_template_match"],
            "validation_scope": "template_geometry_only"},
        "execution_path": {"vision_model_used": False, "action_executed": False,
            "coordinate_source": "current_capture_template_match"}, "template_matching": result}
    plan["recommended_target"] = plan["candidate_result"]["candidates"][0]
    return plan, result
