"""仅解释已绑定的原生焦点和值观察，不授予输入权限。"""
import base64
from hashlib import sha256
from io import BytesIO
import math
import re

from PIL import Image, UnidentifiedImageError


FOCUS_CONDITION = ("The specified ordinary readable text field visibly has keyboard focus, is enabled and editable, "
    "and is not a password or masked field.")
NATIVE_FOCUS_INTRO = ("Evaluate the screenshot together with the supplied runtime observations. The focus_value_snapshot is a read-only native observation: the currently keyboard-focused writable, enabled, non-password field was read twice consistently, belongs to the bound window and contains the original click point. This is evidence of focus, not task success or permission. Inspect the image to check that this same field matches the requested field goal and has no visible contradictory obstacle.")
NATIVE_FOCUS_QUESTION = ("Given the bound native focus observation, is that focused field the visible intended input target described by action.field.field_goal, with no visible contradiction to entering the specified text? Do not require a blinking caret to be visible when native focus is observed. Reject a wrong target, mismatching location or obstructing popup. Do not require typing or navigation to have already occurred.")


def _text(value, maximum=256):
    return type(value) is str and bool(value.strip()) and len(value) <= maximum


def _rect(value):
    return (type(value) is list and len(value) == 4 and all(type(n) is int for n in value)
        and value[2] > 0 and value[3] > 0)


def _created(value):
    try:
        return type(value) in (int, float) and value > 0 and math.isfinite(value)
    except OverflowError:
        return False


def bound_native_focus(payload):
    action = payload.get("action")
    if (payload.get("phase") != "after_action" or type(action) is not dict
            or action.get("operation") != "visual_field_check" or action.get("field_phase") != "focus"
            or action.get("focus_stage") != "after_click" or "focus_value_snapshot" not in action):
        return False
    try:
        snapshot, field, frames = action["focus_value_snapshot"], action["field"], payload["frames"]
        if (type(snapshot) is not dict or set(snapshot) != {"contract_version", "identity", "capture_id", "read_id",
                "observed_at_ns", "source", "value_sha256", "value_length", "selection"}
                or snapshot["contract_version"] != "text_field_snapshot_reference_v1"
                or snapshot["source"] not in {"uia_value", "uia_text"}
                or not _text(snapshot["read_id"]) or type(snapshot["observed_at_ns"]) is not int
                or snapshot["observed_at_ns"] <= 0 or not _text(snapshot["capture_id"], 200)
                or type(frames) is not list or len(frames) != 1 or type(frames[0]) is not dict
                or frames[0].get("role") != "after" or frames[0].get("capture_id") != snapshot["capture_id"]
                or payload.get("condition") != FOCUS_CONDITION):
            raise ValueError
        if (type(field) is not dict or set(field) != {"field_goal", "bbox", "click_point", "window_identity",
                "window_rect", "field_kind", "expected_text"} or not _text(field["field_goal"], 4000)
                or field["field_kind"] not in {"text", "search", "address_bar"}
                or not _text(field["expected_text"], 20000)):
            raise ValueError
        identity, bound, window = snapshot["identity"], field["window_identity"], field["window_rect"]
        if (type(identity) is not dict or set(identity) != {"target_field_id", "window_handle", "process_id",
                "process_create_time", "runtime_id", "window_rect", "control_bbox"}
                or identity["target_field_id"] != "visual-field" or type(bound) is not dict
                or set(bound) != {"handle", "process_id", "process_create_time"}
                or any(type(bound[k]) is not int or bound[k] <= 0 for k in ("handle", "process_id"))
                or any(type(identity[k]) is not int or identity[k] <= 0 for k in ("window_handle", "process_id"))
                or not _created(bound["process_create_time"]) or not _created(identity["process_create_time"])
                or (identity["window_handle"], identity["process_id"], identity["process_create_time"]) != (
                    bound["handle"], bound["process_id"], bound["process_create_time"])
                or not _rect(window) or not _rect(identity["window_rect"]) or identity["window_rect"] != window
                or type(identity["runtime_id"]) is not list or not 1 <= len(identity["runtime_id"]) <= 64
                or any(type(n) is not int for n in identity["runtime_id"])):
            raise ValueError
        box, native, point = field["bbox"], identity["control_bbox"], field["click_point"]
        if (type(box) is not dict or set(box) != {"x", "y", "w", "h"}
                or type(point) is not dict or set(point) != {"x", "y"}
                or any(type(n) is not int for n in point.values())):
            raise ValueError
        visual = [box[k] for k in ("x", "y", "w", "h")]
        for region in (visual, native):
            if (not _rect(region) or min(region[:2]) < 0 or region[0] + region[2] > window[2]
                    or region[1] + region[3] > window[3]
                    or not (region[0] <= point["x"] < region[0] + region[2]
                        and region[1] <= point["y"] < region[1] + region[3])):
                raise ValueError
        length, digest, selection = snapshot["value_length"], snapshot["value_sha256"], snapshot["selection"]
        if (type(length) is not int or not 0 <= length <= 32768 or type(digest) is not str
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or length == 0 and digest != sha256(b"").hexdigest()
                or selection is not None and (type(selection) is not list or len(selection) != 2
                    or any(type(n) is not int for n in selection) or not 0 <= selection[0] <= selection[1] <= length)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("decision_native_focus_evidence_invalid") from None
    return True


NATIVE_FIELD_FRESHNESS_INTRO = ("Evaluate both screenshots together with the bound native_before_snapshot and native_current_snapshot observations in field_freshness_context. These are read-only native facts: the same enabled, writable, non-password focused field was read consistently, with unchanged identity, geometry, value and selection. The reads correspond to their respective image captures. They establish native continuity, not visible target meaning, not task success and not permission. Inspect the two images and the declared changed_region for the exact supplied condition; reject visible contradictory changes or obstructions. Do not demand that a blinking caret be present in both images to establish native focus.")
NATIVE_FIELD_FRESHNESS_QUESTION = (
    "Given the two bound native reads, treat the unchanged native identity, value and selection of this same "
    "focused field as observed continuity facts. For field_phase=value, the native value SHA and length have "
    "also been verified against field.expected_text; do not repeat character-by-character OCR of small "
    "screenshot text to establish that exact value equality. Inspect changed_region and the current target's "
    "surroundings in the full original images for an obstruction, focus redirection, visible contradiction "
    "or change to the intended keyboard effect. Native continuity alone does not establish safe continuation. "
    "Refuse if the supplied evidence is insufficient. The exact freshness condition remains binding: ")


def bound_native_field_freshness(payload):
    from .visual_action_conditions import VISUAL_FIELD_FRESHNESS_CONDITION
    action = payload.get("action")
    if (type(action) is not dict or action.get("operation") != "visual_field_check"
            or action.get("focus_stage") != "before_keyboard_freshness"):
        return False
    try:
        context, frames, field = action["field_freshness_context"], payload["frames"], action["field"]
        if (payload.get("phase") != "after_action" or payload.get("condition") != VISUAL_FIELD_FRESHNESS_CONDITION
                or action.get("field_phase") not in {"focus", "value"}
                or type(context) is not dict or set(context) != {"schema", "changed_region", "original_condition",
                    "prior_request_sha256", "prior_assessment_sha256", "native_before_snapshot", "native_current_snapshot"}
                or context["schema"] != "visual_field_freshness.v1"
                or not _text(context["original_condition"], 4000)
                or any(type(context[k]) is not str or re.fullmatch(r"[0-9a-f]{64}", context[k]) is None
                    for k in ("prior_request_sha256", "prior_assessment_sha256"))
                or type(frames) is not list or len(frames) != 2
                or [f.get("role") for f in frames] != ["before", "after"]):
            raise ValueError
        before, current = context["native_before_snapshot"], context["native_current_snapshot"]
        for snapshot, frame in zip((before, current), frames):
            bound_native_focus({"phase": "after_action", "condition": FOCUS_CONDITION,
                "frames": [{**frame, "role": "after"}], "action": {"operation": "visual_field_check",
                    "field_phase": "focus", "focus_stage": "after_click", "field": field,
                    "focus_value_snapshot": snapshot}})
        if (any(before[k] != current[k] for k in ("identity", "source", "value_sha256", "value_length", "selection"))
                or before["read_id"] == current["read_id"] or before["observed_at_ns"] >= current["observed_at_ns"]):
            raise ValueError
        if action["field_phase"] == "value" and (current["value_length"] != len(field["expected_text"])
                or current["value_sha256"] != sha256(field["expected_text"].encode("utf-8")).hexdigest()):
            raise ValueError
        region, box = context["changed_region"], field["bbox"]
        if (type(region) is not dict or set(region) != {"x", "y", "w", "h"}
                or any(type(n) is not int for n in region.values()) or region["w"] <= 0 or region["h"] <= 0
                or region["x"] < box["x"] or region["y"] < box["y"]
                or region["x"] + region["w"] > box["x"] + box["w"]
                or region["y"] + region["h"] > box["y"] + box["h"]):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("decision_native_field_freshness_invalid") from None
    return True


NATIVE_VALUE_INTRO = (
    "Evaluate the screenshot together with the bound value_reading native observation. The same currently "
    "keyboard-focused, enabled, writable, non-password field was read twice consistently in this image capture. "
    "Its complete text exactly equals field.expected_text, expected_text and actual_text; the native value hash "
    "and length match that text, and the reading is bound to these exact image bytes, capture and target geometry. "
    "This establishes the native value and focus facts, not target meaning, not navigation success and not permission. "
    "Inspect the original image for the intended field, visible contradiction, clipping, masking or obstruction.")
NATIVE_VALUE_QUESTION = (
    "Given the bound native value and focus facts, does this same visible field match action.field.field_goal "
    "and satisfy the exact supplied condition? Use the native value observation for exact complete-text equality; "
    "do not require character-by-character OCR of small screenshot text to repeat that native read. "
    "Reject a wrong target, focus redirection, visible text mismatch, obstruction, hidden or clipped characters, "
    "masking or ambiguity. Native value equality alone does not establish safe continuation. "
    "The original condition remains binding: ")


def _native_value_frame_digest(frame, field):
    """仅解码已上传的有界静态 PNG；不读取 frame 中的任何文件路径。"""
    prefix, limit = "data:image/png;base64,", 20 * 1024 * 1024
    url = frame.get("data_url")
    if type(url) is not str or not url.startswith(prefix) or len(url) - len(prefix) > 4 * ((limit + 2) // 3):
        raise ValueError
    data = base64.b64decode(url[len(prefix):], validate=True)
    if not data or len(data) > limit:
        raise ValueError
    with Image.open(BytesIO(data)) as image:
        if (image.format != "PNG" or image.width * image.height > 40_000_000
                or image.size != tuple(field["window_rect"][2:])
                or getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1):
            raise ValueError
        image.verify()
    return sha256(data).hexdigest()


def bound_native_value(payload):
    action = payload.get("action")
    if (type(action) is not dict or action.get("operation") != "visual_field_check"
            or action.get("field_phase") != "value" or action.get("focus_stage") == "before_keyboard_freshness"):
        return False
    reading = action.get("value_reading")
    snapshot = reading.get("evidence") if type(reading) is dict else None
    if type(snapshot) is not dict or "contract_version" not in snapshot:
        return False
    from .visual_action_conditions import VISUAL_VALUE_CONDITION
    try:
        field, frames = action["field"], payload["frames"]
        if (payload.get("phase") != "after_action" or payload.get("condition") != VISUAL_VALUE_CONDITION
                or set(action) != {"operation", "field_phase", "field", "focus_stage", "focus_receipt_sha256",
                    "input_receipt_sha256", "expected_text", "actual_text", "value_reading"}
                or action["focus_stage"] is not None
                or set(reading) != {"text", "source", "frame_sha256", "capture_id", "bbox", "elapsed_ms", "evidence"}
                or type(frames) is not list or len(frames) != 1 or type(frames[0]) is not dict
                or frames[0].get("role") != "after"
                or any(type(action[k]) is not str or re.fullmatch(r"[0-9a-f]{64}", action[k]) is None
                    for k in ("focus_receipt_sha256", "input_receipt_sha256"))):
            raise ValueError
        bound_native_focus({"phase": "after_action", "condition": FOCUS_CONDITION, "frames": frames,
            "action": {"operation": "visual_field_check", "field_phase": "focus", "focus_stage": "after_click",
                "field": field, "focus_value_snapshot": snapshot}})
        expected = field["expected_text"]
        if (any(type(text) is not str or text != expected
                for text in (action["expected_text"], action["actual_text"], reading["text"]))
                or reading["source"] not in {"uia_value", "uia_text"} or snapshot["source"] != reading["source"]
                or reading["capture_id"] != frames[0]["capture_id"]
                or type(reading["bbox"]) is not dict or set(reading["bbox"]) != {"x", "y", "w", "h"}
                or any(type(n) is not int for n in reading["bbox"].values()) or reading["bbox"] != field["bbox"]
                or type(reading["elapsed_ms"]) not in (int, float) or not math.isfinite(reading["elapsed_ms"])
                or reading["elapsed_ms"] < 0
                or type(reading["frame_sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", reading["frame_sha256"]) is None
                or reading["frame_sha256"] != _native_value_frame_digest(frames[0], field)
                or snapshot["value_sha256"] != sha256(expected.encode("utf-8")).hexdigest()
                or snapshot["value_length"] != len(expected)):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError, UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise ValueError("decision_native_value_evidence_invalid") from None
    return True
