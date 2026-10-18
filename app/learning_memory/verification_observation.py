"""在原生窗口中只读采集可绑定到当前截图的步骤观察。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

from app.agent.native_identity import WindowsNativeIdentityReader
from app.agent.windows_text_field_reader import TextFieldReadError, WindowsTextFieldReader

from .memory_observation import capture_memory_observation


_METHODS = frozenset({"visible_text", "uia_value", "presence"})


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _selector(value):
    if (not isinstance(value, dict) or "control_type" not in value
            or set(value) - {"control_type", "name", "automation_id"}
            or any(not _text(item) for item in value.values())):
        raise ValueError("verification_observation_selector_invalid")
    return deepcopy(value)


def _scope_id(selector):
    encoded = json.dumps(selector, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "verification-scope-" + sha256(encoded).hexdigest()


def _result(status, reason, method, scope_id, frame=None, *, values=None, evidence=None):
    return {"status": status, "reason": reason, "frame": deepcopy(frame) if frame is not None else None,
            "capture_id": frame.get("capture_id") if isinstance(frame, dict) else None,
            "capture_sha256": frame.get("sha256") if isinstance(frame, dict) else None,
            "window_identity": deepcopy(frame.get("window_identity")) if isinstance(frame, dict) else None,
            "scope_id": scope_id, "source": method, "complete": status == "ok",
            "values": deepcopy(values) if status == "ok" and values is not None else {},
            "evidence": deepcopy(evidence or {})}


def _snapshot(frame, observations):
    row = observations.get("uia") if isinstance(observations, dict) else None
    if not isinstance(row, dict) or row.get("status") != "ok":
        return None, row.get("reason", "uia_unavailable") if isinstance(row, dict) else "uia_unavailable"
    if row.get("capture_id") != frame.get("capture_id") or row.get("window_identity") != frame.get("window_identity"):
        raise ValueError("verification_observation_uia_binding_changed")
    snapshot = row.get("snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("status") != "ok":
        return None, "uia_unavailable"
    if (snapshot.get("provider") != "windows_uia" or snapshot.get("scan_scope", "bound_window") != "bound_window"
            or snapshot.get("scan_complete") is not True or snapshot.get("truncated") is not False
            or snapshot.get("provider_tree_valid") is not True):
        return None, "uia_incomplete"
    identity = frame.get("window_identity")
    window = snapshot.get("window")
    if (not isinstance(window, dict) or not isinstance(identity, dict)
            or window.get("handle") != identity.get("handle") or window.get("process_id") != identity.get("process_id")):
        raise ValueError("verification_observation_window_binding_changed")
    controls = snapshot.get("controls")
    if not isinstance(controls, list) or len(controls) > 4000:
        return None, "uia_controls_invalid"
    ids = []
    for item in controls:
        if not isinstance(item, dict) or not _text(item.get("control_id")):
            return None, "uia_controls_invalid"
        ids.append(item["control_id"])
    if len(set(ids)) != len(ids):
        return None, "uia_controls_duplicate"
    return snapshot, None


def _selected(snapshot, selector):
    candidates = [control for control in snapshot["controls"]
                  if control.get("visible") is True and control.get("enabled") is True
                  and all(control.get(key) == value for key, value in selector.items())]
    if len(candidates) > 1:
        return None, "control_ambiguous"
    if not candidates:
        return None, None
    return candidates[0], None


def _geometry_current(control, frame):
    if control is None:
        return True
    box = control.get("bbox")
    size = frame.get("image_size")
    return (isinstance(box, dict) and set(box) == {"x", "y", "w", "h"}
            and all(type(value) is int for value in box.values())
            and isinstance(size, dict) and type(size.get("width")) is int and type(size.get("height")) is int
            and box["x"] >= 0 and box["y"] >= 0 and box["w"] > 0 and box["h"] > 0
            and box["x"] + box["w"] <= size["width"] and box["y"] + box["h"] <= size["height"])


def _control_evidence(control):
    if control is None:
        return None
    return {key: deepcopy(control.get(key)) for key in
            ("control_id", "runtime_id", "bbox", "name", "control_type", "automation_id")}


def _changed_frame_fields(before, after):
    return [key for key in ("sha256", "image_size", "window_identity", "window_rect", "application")
            if before.get(key) != after.get(key)]


def _target_pixels(frame, box):
    raw = Path(frame["image_path"]).read_bytes()
    if sha256(raw).hexdigest() != frame["sha256"]:
        raise ValueError("capture_bytes_changed")
    with Image.open(BytesIO(raw)) as image:
        if (image.format != "PNG" or image.size !=
                (frame["image_size"]["width"], frame["image_size"]["height"])):
            raise ValueError("capture_image_mismatch")
        region = image.convert("RGBA").crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]))
        return sha256(region.tobytes()).hexdigest()


def _visual_stability(before, after, control):
    if before["sha256"] == after["sha256"] or control is None:
        return {"scope": "full_window", "matched": before["sha256"] == after["sha256"],
                "before_sha256": before["sha256"], "after_sha256": after["sha256"]}
    # 读取对象之外的光标或动画不使该对象失效；对象内像素仍须完全一致。
    evidence = {"scope": "selected_control", "bbox": deepcopy(control["bbox"]), "matched": False}
    try:
        evidence["before_sha256"] = _target_pixels(before, control["bbox"])
        evidence["after_sha256"] = _target_pixels(after, control["bbox"])
    except (OSError, ValueError) as error:
        evidence["reason"] = "capture_evidence_unavailable"
        evidence["detail"] = str(error)
        return evidence
    evidence["matched"] = evidence["before_sha256"] == evidence["after_sha256"]
    return evidence


def _stable_control(before, after):
    return _control_evidence(before) == _control_evidence(after)


def _read_control_value(coordinator, target, frame, control):
    if control.get("control_type") not in {"Edit", "ComboBox"}:
        return None, "uia_value_control_type_unsupported", None
    runtime_id = control.get("runtime_id")
    box = control.get("bbox")
    if (not isinstance(runtime_id, list) or not 1 <= len(runtime_id) <= 64
            or any(type(value) is not int for value in runtime_id)
            or not isinstance(box, dict) or set(box) != {"x", "y", "w", "h"}
            or any(type(value) is not int for value in box.values()) or box["w"] <= 0 or box["h"] <= 0):
        return None, "uia_value_control_identity_unavailable", None
    rect = frame["window_rect"]
    window = (rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
    manager = coordinator._windows()
    reader = WindowsTextFieldReader(window_manager=manager,
                                    native_identity_reader=WindowsNativeIdentityReader(window_manager=manager))
    try:
        result = reader.read_field(target_field_id=control["control_id"], capture_id=frame["capture_id"],
            target_window_handle=target["handle"], target_process_id=target["process_id"],
            process_create_time=frame["window_identity"]["process_create_time"],
            window_rect=window, target_bbox=tuple(box[key] for key in ("x", "y", "w", "h")),
            click_point=(box["x"] + box["w"] // 2, box["y"] + box["h"] // 2),
            require_keyboard_focus=False, expected_runtime_id=tuple(runtime_id),
            expected_control_type=control["control_type"])
    except TextFieldReadError as error:
        return None, error.reason_code, None
    identity = getattr(result, "identity", None)
    if (getattr(result, "capture_id", None) != frame["capture_id"]
            or getattr(result, "source", None) != "uia_value"
            or not isinstance(getattr(result, "value", None), str)
            or getattr(identity, "target_field_id", None) != control["control_id"]
            or getattr(identity, "runtime_id", None) != tuple(runtime_id)
            or getattr(identity, "control_bbox", None) != tuple(box[key] for key in ("x", "y", "w", "h"))
            or getattr(identity, "window_rect", None) != window
            or getattr(identity, "window_handle", None) != target["handle"]
            or getattr(identity, "process_id", None) != target["process_id"]
            or getattr(identity, "process_create_time", None) != frame["window_identity"]["process_create_time"]):
        return None, "uia_value_identity_or_source_mismatch", None
    reference = result.to_reference() if callable(getattr(result, "to_reference", None)) else None
    return result.value, None, reference


def _read_step_observation_once(coordinator, *, target: dict, selector: dict, method: str) -> dict:
    """夹住只读现场读取的前后截图，变化时拒绝复用旧证据。"""
    if (not isinstance(target, dict) or set(target) != {"handle", "process_id"}
            or any(type(target[key]) is not int or target[key] <= 0 for key in target)
            or method not in _METHODS):
        raise ValueError("verification_observation_request_invalid")
    rule = _selector(selector)
    scope_id = _scope_id(rule)
    recipe = {"scope": {"anchors": [{"kind": "uia"}]}, "strategies": []}
    first_frame, first_observations = capture_memory_observation(
        coordinator, target["handle"], target["process_id"], recipe=recipe)
    first_snapshot, reason = _snapshot(first_frame, first_observations)
    if first_snapshot is None:
        return _result("unavailable", reason, method, scope_id, first_frame)
    first_control, reason = _selected(first_snapshot, rule)
    if reason:
        return _result("unavailable", reason, method, scope_id, first_frame)
    if not _geometry_current(first_control, first_frame):
        return _result("unavailable", "control_bbox_invalid", method, scope_id, first_frame)
    if method != "presence" and first_control is None:
        return _result("unavailable", "control_missing", method, scope_id, first_frame)
    if method == "visible_text" and not _text(first_control.get("name")):
        return _result("unavailable", "control_name_unreadable", method, scope_id, first_frame)
    field_value = None
    field_reference = None
    if method == "uia_value":
        field_value, reason, field_reference = _read_control_value(coordinator, target, first_frame, first_control)
        if reason:
            return _result("unavailable", reason, method, scope_id, first_frame,
                           evidence={"selected_control": _control_evidence(first_control)})
    second_frame, second_observations = capture_memory_observation(
        coordinator, target["handle"], target["process_id"], recipe=recipe)
    evidence = {"before_capture_id": first_frame["capture_id"], "before_sha256": first_frame["sha256"],
                "after_capture_id": second_frame["capture_id"], "after_sha256": second_frame["sha256"],
                "selected_control": _control_evidence(first_control), "field_read_reference": field_reference,
                "before_uia_snapshot": deepcopy(first_snapshot)}
    changed = _changed_frame_fields(first_frame, second_frame)
    evidence.update({"before_frame": deepcopy(first_frame), "after_frame": deepcopy(second_frame),
                     "changed_frame_fields": changed})
    if any(key != "sha256" for key in changed):
        return _result("unavailable", "frame_changed_between_reads", method, scope_id, second_frame, evidence=evidence)
    second_snapshot, reason = _snapshot(second_frame, second_observations)
    if second_snapshot is None:
        return _result("unavailable", reason, method, scope_id, second_frame, evidence=evidence)
    evidence["after_uia_snapshot"] = deepcopy(second_snapshot)
    second_control, reason = _selected(second_snapshot, rule)
    if reason:
        return _result("unavailable", reason, method, scope_id, second_frame, evidence=evidence)
    if not _geometry_current(second_control, second_frame):
        return _result("unavailable", "control_bbox_invalid", method, scope_id, second_frame, evidence=evidence)
    if not _stable_control(first_control, second_control):
        return _result("unavailable", "target_changed_between_reads", method, scope_id, second_frame, evidence=evidence)
    evidence["visual_stability"] = _visual_stability(first_frame, second_frame, second_control)
    if not evidence["visual_stability"]["matched"]:
        return _result("unavailable", "frame_changed_between_reads", method, scope_id, second_frame, evidence=evidence)
    if method == "presence":
        values = {"target_present": second_control is not None}
    elif method == "visible_text":
        values = {"text": second_control["name"]}
    else:
        values = {"field_value": field_value}
    return _result("ok", None, method, scope_id, second_frame, values=values, evidence=evidence)


def read_step_observation(coordinator, *, target: dict, selector: dict, method: str) -> dict:
    """字段像素不稳定时最多完整夹读三次；保留失败，不重放输入。"""
    attempts = []
    for _ in range(3):
        result = _read_step_observation_once(coordinator, target=target, selector=selector, method=method)
        evidence = result["evidence"]
        if attempts:
            original = attempts[0]["evidence"]
            before = evidence.get("before_frame")
            anchor = original["before_frame"]
            reason = None
            if before is not None and any(before.get(key) != anchor.get(key) for key in
                                          ("image_size", "window_identity", "window_rect", "application")):
                reason = "frame_changed_between_observation_attempts"
            elif ("selected_control" in evidence
                  and evidence["selected_control"] != original["selected_control"]):
                reason = "target_changed_between_observation_attempts"
            if reason:
                result = _result("unavailable", reason, method, result["scope_id"], result["frame"], evidence=evidence)
        attempts.append(deepcopy(result))
        stability = evidence.get("visual_stability") or {}
        if not (method == "uia_value" and result["reason"] == "frame_changed_between_reads"
                and evidence.get("changed_frame_fields") == ["sha256"]
                and stability.get("matched") is False and "reason" not in stability):
            break
    if len(attempts) > 1:
        result["evidence"]["observation_attempts"] = attempts
        result["evidence"]["reacquired"] = True
    return result


__all__ = ["read_step_observation"]
