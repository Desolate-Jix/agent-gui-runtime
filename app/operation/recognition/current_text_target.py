"""只从同帧完整 UIA 树中取唯一命名文本字段的中心。"""
from collections.abc import Mapping
from pathlib import Path
import unicodedata

from .control_target import uia_control_has_text_entry_patterns, uia_form_label


def _label(value):
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold().rstrip(":：").rstrip()


def _box(value):
    return (isinstance(value, Mapping)
            and all(type(value.get(key)) is int for key in ("x", "y", "w", "h"))
            and value["w"] > 0 and value["h"] > 0)


def _text_type(control):
    return str(control.get("control_type") or "").casefold().replace(" ", "") in {
        "edit", "textbox", "combobox"}


def current_text_primary_point(fast_inventory, *, candidate, image_path, image_size, literal_label):
    """证据不齐或同名文本控件不唯一时拒绝产生坐标。"""
    if not isinstance(fast_inventory, Mapping) or fast_inventory.get("status") != "ready":
        return None
    if not _label(literal_label) or not isinstance(image_size, Mapping):
        return None
    width, height = image_size.get("width"), image_size.get("height")
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        return None
    reading = fast_inventory.get("screen_reading") or {}
    raw = fast_inventory.get("raw_uia_snapshot") or {}
    layer = (reading.get("source_layers") or {}).get("windows_uia") or {}
    if (not reading.get("image_path") or Path(reading["image_path"]) != Path(image_path)
            or reading.get("image_size") != image_size
            or fast_inventory.get("uia_scan_complete") is not True
            or fast_inventory.get("uia_scan_truncated") is not False):
        return None
    for snapshot in (raw, layer):
        if (snapshot.get("status") != "ok" or snapshot.get("scan_complete") is not True
                or snapshot.get("truncated") is not False
                or snapshot.get("scan_scope", "bound_window") != "bound_window"
                or not isinstance(snapshot.get("controls"), list)):
            return None
    controls = raw["controls"]
    if not all(isinstance(control, Mapping) for control in controls):
        return None
    matches = [control for control in controls if _text_type(control)
               and _label(literal_label) in {_label(control.get("name")), _label(uia_form_label(control))}]
    if len(matches) != 1:
        return None
    control = matches[0]
    # 快速层会过滤原始树；只要求选中项未经改写且恰好保留一次。
    if sum(item == control for item in layer["controls"] if isinstance(item, Mapping)) != 1:
        return None
    box = control.get("bbox")
    control_id = control.get("control_id")
    rid = control.get("runtime_id")
    if (not uia_control_has_text_entry_patterns(control)
            or control.get("visible") is not True or control.get("enabled") is not True
            or any(control.get(key) is True for key in ("is_read_only", "read_only", "readonly",
                                                        "is_password", "is_protected", "protected"))
            or not isinstance(control_id, str) or not control_id.strip()
            or not isinstance(rid, (list, tuple)) or not rid
            or not _box(box) or box["x"] < 0 or box["y"] < 0
            or box["x"] + box["w"] > width or box["y"] + box["h"] > height
            or sum(item.get("control_id") == control_id for item in controls) != 1):
        return None
    if (getattr(candidate, "role", None) not in {"input", "combobox"}
            or getattr(candidate, "eligible", None) is not True):
        return None
    element = getattr(candidate, "element", None)
    policy = getattr(element, "interaction_policy", None)
    evidence = getattr(element, "evidence", None)
    action = evidence.get("screen_inventory_action") if isinstance(evidence, Mapping) else None
    element_box = getattr(element, "bbox", None)
    if (getattr(policy, "allowed", None) is not True or not isinstance(action, Mapping)
            or action.get("source") != "windows_uia.controls"
            or action.get("source_id") != control_id or action.get("bbox") != box
            or not callable(getattr(element_box, "to_dict", None))
            or element_box.to_dict() != box):
        return None
    return {"point": {"x": box["x"] + box["w"] // 2, "y": box["y"] + box["h"] // 2},
            "bbox": dict(box), "control_id": control_id, "runtime_id": list(rid),
            "coordinate_source": "current_uia_named_text_center"}
