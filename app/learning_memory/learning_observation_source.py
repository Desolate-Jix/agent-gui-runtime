"""按原事件封存动作前观察，重开时只读取不可变证据。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _write_immutable
from .target_recipe import _scope
from .target_resolution import _frame_valid, _uia_snapshot


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")
_FIELDS = {"contract_version", "event_id", "command_sha256", "observation_stage",
           "frame", "uia", "candidate"}


def validate_learning_observation(event, observation):
    if (not isinstance(event, dict) or not isinstance(observation, dict)
            or set(observation) != _FIELDS
            or observation.get("contract_version") != "learning_target_observation.v1"
            or observation.get("observation_stage") != "before"
            or not isinstance(observation.get("event_id"), str)
            or not _ID.fullmatch(observation["event_id"])
            or observation["event_id"] != event.get("request_id")
            or not isinstance(observation.get("command_sha256"), str)
            or not _SHA.fullmatch(observation["command_sha256"])
            or observation["command_sha256"] != event.get("command_sha256")):
        raise ValueError("learning_observation_event_binding_invalid")
    frame = observation["frame"]
    before = event.get("before")
    if (not isinstance(before, dict) or before.get("status") != "referenced"
            or not _frame_valid(frame)
            or before.get("capture_id") != frame["capture_id"]
            or before.get("sha256") != frame["sha256"]
            or before.get("window_size", before.get("image_size")) != frame["image_size"]):
        raise ValueError("learning_observation_before_capture_invalid")
    for name in ("window_identity", "application", "window_rect"):
        if name in before and before[name] != frame.get(name):
            raise ValueError("learning_observation_before_identity_invalid")
    try:
        _scope({"task_id": "memory-local", "interface_key": "observation", "state_key": "before",
                "application": frame.get("application")})
    except ValueError as error:
        raise ValueError("learning_observation_application_invalid") from error
    rect = frame.get("window_rect")
    size = frame["image_size"]
    if (not isinstance(rect, list) or len(rect) != 4 or any(type(value) is not int for value in rect)
            or rect[2] - rect[0] != size["width"] or rect[3] - rect[1] != size["height"]):
        raise ValueError("learning_observation_window_rect_invalid")
    snapshot, error = _uia_snapshot({"uia": observation["uia"]}, frame)
    if error or len(snapshot["controls"]) > 10000:
        raise ValueError("learning_observation_" + (error or "uia_unbounded"))
    if ("capture_id" in snapshot and snapshot["capture_id"] != frame["capture_id"]
            or "window_identity" in snapshot and snapshot["window_identity"] != frame["window_identity"]):
        raise ValueError("learning_observation_uia_binding_changed")
    candidate = observation["candidate"]
    if (not isinstance(candidate, dict) or candidate.get("capture_id") != frame["capture_id"]
            or candidate.get("viewport_size") != size
            or not isinstance(candidate.get("source"), str) or not candidate["source"].strip()
            or candidate.get("freshness") not in {"current_capture", "current_route_capture", "dispatch_capture_revalidated"}):
        raise ValueError("learning_observation_candidate_binding_invalid")
    bbox, point = candidate.get("bbox"), candidate.get("click_point")
    if (not isinstance(bbox, dict) or set(bbox) != {"x", "y", "w", "h"}
            or any(type(value) is not int for value in bbox.values())
            or not (0 <= bbox["x"] < bbox["x"] + bbox["w"] <= size["width"])
            or not (0 <= bbox["y"] < bbox["y"] + bbox["h"] <= size["height"])
            or not isinstance(point, dict) or set(point) != {"x", "y"}
            or any(type(value) is not int for value in point.values())
            or not (bbox["x"] <= point["x"] < bbox["x"] + bbox["w"])
            or not (bbox["y"] <= point["y"] < bbox["y"] + bbox["h"])):
        raise ValueError("learning_observation_candidate_geometry_invalid")
    try:
        raw = Path(frame["image_path"]).read_bytes()
    except OSError as error:
        raise ValueError("learning_observation_image_unavailable") from error
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or sha256(raw).hexdigest() != frame["sha256"]:
        raise ValueError("learning_observation_image_changed")
    return deepcopy(observation)


def _image_path(digest):
    return f"desktop-review/evidence-objects/{digest}.png"


def learning_observation_reference(observation):
    value = deepcopy(observation)
    value["frame"]["image_path"] = _image_path(value["frame"]["sha256"])
    return {"kind": "learning_target_observation", "sha256": sha256(canonical_json_bytes(value)).hexdigest()}


def archive_learning_observation(library, *, event: dict, observation: dict) -> dict:
    value = validate_learning_observation(event, observation)
    reference = learning_observation_reference(value)
    if event.get("target_observation", reference) != reference:
        raise ValueError("learning_observation_event_reference_changed")
    raw = Path(value["frame"]["image_path"]).read_bytes()
    if sha256(raw).hexdigest() != value["frame"]["sha256"]:
        raise ValueError("learning_observation_image_changed_during_archive")
    image = _image_path(value["frame"]["sha256"])
    # 归档不依赖原会话路径；截图和观察各按内容摘要存一份。
    value["frame"]["image_path"] = image
    payload = canonical_json_bytes(value)
    digest = sha256(payload).hexdigest()
    _write_immutable(library._artifact_root / image, raw)
    _write_immutable(library._artifact_root / "desktop-review/learning-observations" / (digest + ".json"),
                     payload + b"\n")
    return reference


def load_learning_observation(library, reference: dict) -> dict:
    if (not isinstance(reference, dict) or set(reference) != {"kind", "sha256"}
            or reference.get("kind") != "learning_target_observation"
            or not isinstance(reference.get("sha256"), str) or not _SHA.fullmatch(reference["sha256"])):
        raise ValueError("learning_observation_reference_invalid")
    path = library._artifact_file(
        f"desktop-review/learning-observations/{reference['sha256']}.json", "学习动作前观察")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError("learning_observation_archive_unreadable") from error
    if sha256(canonical_json_bytes(value)).hexdigest() != reference["sha256"]:
        raise ValueError("learning_observation_archive_changed")
    frame = value.get("frame") if isinstance(value, dict) else None
    if (not isinstance(frame, dict) or not isinstance(frame.get("sha256"), str)
            or not _SHA.fullmatch(frame["sha256"]) or frame.get("image_path") != _image_path(frame["sha256"])):
        raise ValueError("learning_observation_archive_image_invalid")
    frame["image_path"] = str(library._artifact_file(frame["image_path"], "学习动作前原图"))
    event = {"request_id": value.get("event_id"), "command_sha256": value.get("command_sha256"),
             "before": {**deepcopy(frame), "status": "referenced", "window_size": frame["image_size"]}}
    return validate_learning_observation(event, value)


__all__ = ["validate_learning_observation", "learning_observation_reference",
           "archive_learning_observation", "load_learning_observation"]
