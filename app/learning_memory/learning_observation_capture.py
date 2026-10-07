"""为学习事件记录真实派发前的当前目标证据。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from .memory_observation import capture_memory_observation


_CURRENT_SCOPE = ContextVar("learning_observation_scope", default=None)
_UNAVAILABLE_REASONS = frozenset({
    "memory_observation_window_binding_changed",
    "memory_observation_window_rect_invalid",
    "memory_observation_target_invalid",
    "memory_observation_native_identity_unavailable",
    "memory_observation_executable_invalid",
    "memory_observation_png_required",
    "memory_observation_viewport_changed",
    "memory_observation_full_capture_required",
    "memory_observation_identity_changed",
    "memory_observation_capture_changed",
})
_UIA_RECIPE = {"scope": {"anchors": [{"kind": "uia"}]}, "strategies": []}


@contextmanager
def learning_capture_scope(coordinator, context):
    """仅在原执行 owner 线程内关联当前学习事件。"""
    value = None
    if context is not None:
        if (not isinstance(context, dict)
                or not isinstance(context.get("event_id"), str) or not context["event_id"]
                or not isinstance(context.get("command_sha256"), str) or not context["command_sha256"]):
            raise ValueError("learning_observation_context_invalid")
        value = (coordinator, {"event_id": context["event_id"],
                               "command_sha256": context["command_sha256"]})
    token = _CURRENT_SCOPE.set(value)
    try:
        yield
    finally:
        _CURRENT_SCOPE.reset(token)


def learning_capture_active():
    return _CURRENT_SCOPE.get() is not None


def _unavailable(context, reason, *, frame=None, uia=None):
    value = {"contract_version": "learning_target_observation.v1",
        "event_id": context["event_id"], "command_sha256": context["command_sha256"],
        "observation_stage": "before", "status": "unavailable", "reason": reason}
    if frame is not None:
        value["frame"] = deepcopy(frame)
    if uia is not None:
        value["uia"] = deepcopy(uia)
    return value


def _bbox(candidate):
    value = candidate.get("bbox")
    if not isinstance(value, dict) and isinstance(candidate.get("element"), dict):
        value = candidate["element"].get("bbox")
    if not isinstance(value, dict):
        return None
    width = value.get("width", value.get("w"))
    height = value.get("height", value.get("h"))
    if (any(type(item) is not int for item in (value.get("x"), value.get("y"), width, height))
            or width <= 0 or height <= 0):
        return None
    return {"x": value["x"], "y": value["y"], "w": width, "h": height}


def observe_learning_target(*, image_path, candidate, click_point):
    """投影当前 API 原图上的已选候选，并只读采集同窗 UIA。"""
    scope = _CURRENT_SCOPE.get()
    if scope is None:
        return None
    coordinator, context = scope
    if not isinstance(candidate, dict):
        return _unavailable(context, "selected_candidate_unavailable")
    bbox = _bbox(candidate)
    if bbox is None:
        return _unavailable(context, "selected_candidate_bbox_unavailable")
    source = candidate.get("source")
    if not isinstance(source, str) or not source:
        return _unavailable(context, "candidate_source_unavailable")
    if (not isinstance(click_point, dict)
            or type(click_point.get("x")) is not int or type(click_point.get("y")) is not int):
        return _unavailable(context, "selected_click_point_unavailable")
    x, y = click_point["x"], click_point["y"]
    if not (bbox["x"] <= x < bbox["x"] + bbox["w"]
            and bbox["y"] <= y < bbox["y"] + bbox["h"]):
        return _unavailable(context, "selected_click_point_outside_candidate_bbox")
    if not isinstance(image_path, str) or not image_path:
        return _unavailable(context, "current_capture_path_unavailable")

    manager = coordinator._windows()
    bound = manager.get_bound_window()
    if bound is None:
        return _unavailable(context, "memory_observation_window_binding_changed")
    handle, pid = getattr(bound, "handle", None), getattr(bound, "process_id", None)
    try:
        frame, observations = capture_memory_observation(coordinator, handle, pid,
            image_path=image_path, recipe=deepcopy(_UIA_RECIPE))
    except ValueError as error:
        reason = str(error)
        if reason not in _UNAVAILABLE_REASONS:
            raise
        return _unavailable(context, reason)

    uia = observations.get("uia") if isinstance(observations, dict) else None
    if (not isinstance(frame, dict) or not isinstance(frame.get("window_identity"), dict)
            or not isinstance(frame.get("capture_id"), str) or not frame["capture_id"]):
        return _unavailable(context, "memory_observation_frame_incomplete", frame=frame, uia=uia)
    identity = frame["window_identity"]
    application = frame.get("application")
    if (type(identity.get("handle")) is not int or identity["handle"] != handle
            or type(identity.get("process_id")) is not int or identity["process_id"] != pid
            or type(identity.get("process_create_time")) not in (int, float)
            or not isinstance(application, dict)
            or not isinstance(application.get("executable_name"), str)
            or not application["executable_name"]):
        return _unavailable(context, "memory_observation_native_identity_unavailable", frame=frame, uia=uia)
    if (not isinstance(uia, dict) or uia.get("status") != "ok"
            or uia.get("capture_id") != frame["capture_id"]
            or uia.get("window_identity") != identity):
        reason = uia.get("reason", "uia_unavailable") if isinstance(uia, dict) else "uia_invalid"
        return _unavailable(context, reason, frame=frame, uia=uia)
    snapshot = uia.get("snapshot")
    if (not isinstance(snapshot, dict) or snapshot.get("status") != "ok"
            or snapshot.get("scan_complete") is not True or snapshot.get("truncated") is not False
            or snapshot.get("capture_id") != frame["capture_id"]
            or snapshot.get("window_identity") != identity):
        return _unavailable(context, "uia_incomplete", frame=frame, uia=uia)

    image_size = frame.get("image_size")
    if (not isinstance(image_size, dict) or type(image_size.get("width")) is not int
            or type(image_size.get("height")) is not int):
        return _unavailable(context, "memory_observation_image_size_unavailable", frame=frame, uia=uia)
    if (bbox["x"] < 0 or bbox["y"] < 0
            or bbox["x"] + bbox["w"] > image_size["width"]
            or bbox["y"] + bbox["h"] > image_size["height"]):
        return _unavailable(context, "selected_candidate_bbox_outside_current_frame", frame=frame, uia=uia)
    if not (0 <= x < image_size["width"] and 0 <= y < image_size["height"]):
        return _unavailable(context, "selected_click_point_outside_current_frame", frame=frame, uia=uia)
    return {"contract_version": "learning_target_observation.v1",
        "event_id": context["event_id"], "command_sha256": context["command_sha256"],
        "observation_stage": "before", "frame": deepcopy(frame), "uia": deepcopy(uia),
        "candidate": {"capture_id": frame["capture_id"], "viewport_size": deepcopy(image_size),
            "source": source, "bbox": bbox,
            "click_point": deepcopy(click_point), "freshness": "current_capture"}}


__all__ = ["learning_capture_active", "learning_capture_scope", "observe_learning_target"]
