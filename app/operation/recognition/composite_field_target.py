"""明确聚焦范围内解析本帧复合字段；不提供输入许可或普通点击兜底。"""
from collections.abc import Mapping
from pathlib import Path

from .control_target import uia_control_is_action_identity


EVIDENCE_KEY = "current_composite_field_target"


def _box(value):
    return (isinstance(value, Mapping) and set(value) == {"x", "y", "w", "h"}
            and all(type(value[key]) is int for key in value)
            and min(value["x"], value["y"]) >= 0 and min(value["w"], value["h"]) > 0)


def _inside(box, point):
    return (_box(box) and box["x"] <= point["x"] < box["x"] + box["w"]
            and box["y"] <= point["y"] < box["y"] + box["h"])


def _contains(outer, inner):
    return (_box(outer) and _box(inner) and outer["x"] <= inner["x"] and outer["y"] <= inner["y"]
            and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
            and inner["y"] + inner["h"] <= outer["y"] + outer["h"])


def _overlaps(a, b):
    return (_box(a) and _box(b) and max(a["x"], b["x"]) < min(a["x"]+a["w"], b["x"]+b["w"])
            and max(a["y"], b["y"]) < min(a["y"]+a["h"], b["y"]+b["h"]))


def _identity(control, controls):
    rid, control_id = control.get("runtime_id"), control.get("control_id")
    return (isinstance(control_id, str) and bool(control_id.strip())
            and isinstance(rid, (list, tuple)) and 1 <= len(rid) <= 64
            and all(type(value) is int for value in rid)
            and sum(item.get("control_id") == control_id for item in controls) == 1
            and sum(isinstance(item.get("runtime_id"), (list, tuple))
                    and tuple(item["runtime_id"]) == tuple(rid) for item in controls) == 1)


def _project(control):
    return {key: (list(control[key]) if key == "runtime_id" else dict(control[key]) if key == "bbox"
                  else control[key]) for key in ("control_id", "runtime_id", "control_type", "bbox")}


def resolve_composite_field_target(fast_inventory, *, image_path, image_size, point):
    """只处理原点落父框且未落子框的情况；其余准确字段原路径不变。"""
    from app.core.local_text_focus import has_local_text_focus, bind_composite_local_focus_target

    if not has_local_text_focus():
        return None, None
    raw = fast_inventory.get("raw_uia_snapshot") or {}
    controls = raw.get("controls")
    if (not isinstance(controls, list) or not all(isinstance(item, Mapping) for item in controls)
            or not isinstance(point, dict) or set(point) != {"x", "y"}
            or any(type(value) is not int for value in point.values())):
        return None, None
    parents = [control for control in controls if control.get("control_type") == "ComboBox"
               and _inside(control.get("bbox"), point)]
    if not parents:
        return None, None
    error = "composite_field_current_identity_unconfirmed"
    reading = fast_inventory.get("screen_reading") or {}
    if (len(parents) != 1 or raw.get("status") != "ok" or raw.get("scan_complete") is not True
            or raw.get("truncated") is not False or raw.get("scan_scope", "bound_window") != "bound_window"
            or fast_inventory.get("uia_scan_complete") is not True
            or fast_inventory.get("uia_scan_truncated") is not False
            or reading.get("image_size") != image_size or not reading.get("image_path")
            or Path(reading["image_path"]).resolve() != Path(image_path).resolve()):
        return None, error
    parent = parents[0]
    children = [control for control in controls if control.get("control_type") == "Edit"
                and isinstance(control.get("ancestor_control_ids"), list)
                and parent.get("control_id") in control["ancestor_control_ids"]]
    if len(children) != 1:
        return None, error
    child = children[0]
    if _inside(child.get("bbox"), point):
        return None, None
    viewport = dict(x=0, y=0, w=image_size.get("width"), h=image_size.get("height"))
    for control in (parent, child):
        if (not _identity(control, controls) or control.get("visible") is not True
                or control.get("enabled") is not True
                or any(control.get(key) not in (None, False) for key in
                       ("is_read_only", "read_only", "readonly", "is_password", "is_protected", "protected"))
                or not _contains(viewport, control.get("bbox"))):
            return None, error
    if (not _contains(parent["bbox"], child["bbox"])
            or not isinstance(child.get("patterns"), list)
            or not all(isinstance(pattern, str) for pattern in child["patterns"])
            or child["control_id"] in child["ancestor_control_ids"]
            or not all(isinstance(ancestor, str) and ancestor for ancestor in child["ancestor_control_ids"])
            or len(set(child["ancestor_control_ids"])) != len(child["ancestor_control_ids"])
            or not set(child["patterns"]) & {"Value", "Text"}):
        return None, error
    box = child["bbox"]
    selected_point = dict(x=box["x"] + box["w"] // 2, y=box["y"] + box["h"] // 2)
    ancestors = child.get("ancestor_control_ids") or []
    for other in controls:
        if other is child or other is parent or other.get("visible") is False:
            continue
        kind = str(other.get("control_type") or "").casefold()
        if (other.get("control_id") in ancestors and kind in {"pane", "group", "document", "window"}
                and not uia_control_is_action_identity(other)):
            continue
        if (uia_control_is_action_identity(other) or kind in {"edit", "combobox"}) and (
                _inside(other.get("bbox"), point) or _overlaps(other.get("bbox"), box)):
            return None, "composite_field_current_target_ambiguous"
    projected = dict(parent=_project(parent), child=_project(child), raw_model_point=dict(point), point=selected_point)
    # 当前能力验证真正可写的子框及原生父关系，不能从清单模式名推断可写。
    binding = bind_composite_local_focus_target(projected, image_path=image_path,
        image_size=image_size, source_window=raw.get("window"))
    return {**projected, **binding, "control": child}, None
