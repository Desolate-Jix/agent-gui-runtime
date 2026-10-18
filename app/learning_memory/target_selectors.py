"""仅在当前捕获的完整可见列表中解析唯一行及行内动作。"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}_invalid")
    return value


def _identity(value):
    if (not isinstance(value, dict) or set(value) != {"handle", "process_id", "process_create_time"}
            or type(value["handle"]) is not int or value["handle"] <= 0
            or type(value["process_id"]) is not int or value["process_id"] <= 0
            or type(value["process_create_time"]) not in (int, float)
            or not isfinite(value["process_create_time"]) or value["process_create_time"] <= 0):
        raise ValueError("window_identity_invalid")
    return value


def _capture(value):
    if not isinstance(value, dict) or set(value) not in ({"capture_id", "window_identity", "image_size", "run_id"}, {"capture_id", "window_identity", "image_size", "run_id", "sha256"}):
        raise ValueError("capture_invalid")
    _text(value["capture_id"], "capture_id")
    _text(value["run_id"], "run_id")
    _identity(value["window_identity"])
    size = value["image_size"]
    if not isinstance(size, dict) or set(size) != {"width", "height"} or any(type(size[key]) is not int or size[key] <= 0 for key in ("width", "height")):
        raise ValueError("image_size_invalid")
    if "sha256" in value and (not isinstance(value["sha256"], str) or len(value["sha256"]) != 64 or any(char not in "0123456789abcdef" for char in value["sha256"])):
        raise ValueError("capture_sha256_invalid")
    return value


def _box(value, parent):
    if not isinstance(value, dict) or set(value) != {"x", "y", "w", "h"} or any(type(value[key]) is not int for key in value):
        raise ValueError("bbox_invalid")
    if value["x"] < 0 or value["y"] < 0 or value["w"] <= 0 or value["h"] <= 0:
        raise ValueError("bbox_invalid")
    if (value["x"] < parent["x"] or value["y"] < parent["y"]
            or value["x"] + value["w"] > parent["x"] + parent["w"]
            or value["y"] + value["h"] > parent["y"] + parent["h"]):
        raise ValueError("bbox_out_of_bounds")
    return value


def _bound(observation, capture):
    if observation.get("capture_id") != capture["capture_id"]:
        raise ValueError("capture_stale")
    if observation.get("window_identity") != capture["window_identity"]:
        raise ValueError("window_identity_mismatch")


def _scalar(value):
    if type(value) not in (str, int, float, bool):
        raise ValueError("constraint_value_invalid")
    return value


def _value(reference, bindings):
    if not isinstance(reference, dict):
        raise ValueError("constraint_reference_invalid")
    source = reference.get("source")
    if source == "constant" and set(reference) == {"source", "value"}:
        return _scalar(reference["value"])
    if source == "input" and set(reference) == {"source", "name"}:
        name = _text(reference["name"], "input_name")
        if name not in bindings["inputs"]:
            raise ValueError("missing_input")
        return _scalar(bindings["inputs"][name])
    if source == "output" and set(reference) == {"source", "step_id", "name"}:
        key = _text(reference["step_id"], "step_id") + "." + _text(reference["name"], "output_name")
        output = bindings["outputs"].get(key)
        if output is None:
            raise ValueError("missing_output")
        if not isinstance(output, dict) or set(output) != {"run_id", "value"} or output["run_id"] != bindings["run_id"]:
            raise ValueError("stale_output")
        return _scalar(output["value"])
    raise ValueError("constraint_reference_invalid")


def _action(action, row, capture):
    required = {"action_id", "row_id", "capture_id", "window_identity", "name", "control_type", "bbox"}
    if not isinstance(action, dict) or set(action) not in (required, required | {"automation_id"}):
        raise ValueError("row_action_invalid")
    for key in ("action_id", "name", "control_type"):
        _text(action[key], key)
    if "automation_id" in action:
        _text(action["automation_id"], "automation_id")
    if action["row_id"] != row["row_id"]:
        raise ValueError("row_action_mismatch")
    _bound(action, capture)
    _box(action["bbox"], row["bbox"])


def _row(row, container, capture):
    required = {"row_id", "container_id", "capture_id", "window_identity", "bbox", "properties", "actions"}
    if not isinstance(row, dict) or set(row) != required:
        raise ValueError("row_invalid")
    _text(row["row_id"], "row_id")
    if row["container_id"] != container["container_id"]:
        raise ValueError("row_container_mismatch")
    _bound(row, capture)
    _box(row["bbox"], container["bbox"])
    if not isinstance(row["properties"], dict) or len(row["properties"]) > 128:
        raise ValueError("row_properties_invalid")
    for key, value in row["properties"].items():
        _text(key, "property")
        _scalar(value)
    actions = row["actions"]
    if not isinstance(actions, list) or len(actions) > 64:
        raise ValueError("row_actions_invalid")
    ids = set()
    for action in actions:
        _action(action, row, capture)
        if action["action_id"] in ids:
            raise ValueError("row_action_duplicate")
        ids.add(action["action_id"])


def resolve_visible_row(*, container: dict, rows: list[dict], constraints: list[dict], bindings: dict, capture: dict) -> dict:
    """使用本次参数及完整当前列表筛出唯一行，不根据位置猜测。"""
    frame = _capture(capture)
    if not isinstance(container, dict) or set(container) != {"container_id", "capture_id", "window_identity", "bbox", "complete"}:
        raise ValueError("container_invalid")
    _text(container["container_id"], "container_id")
    _bound(container, frame)
    _box(container["bbox"], {"x": 0, "y": 0, "w": frame["image_size"]["width"], "h": frame["image_size"]["height"]})
    if container["complete"] is not True:
        raise ValueError("visible_list_incomplete")
    if not isinstance(rows, list) or len(rows) > 512:
        raise ValueError("rows_invalid")
    row_ids = set()
    for row in rows:
        _row(row, container, frame)
        if row["row_id"] in row_ids:
            raise ValueError("row_duplicate")
        row_ids.add(row["row_id"])
    if not isinstance(bindings, dict) or set(bindings) != {"run_id", "inputs", "outputs"} or bindings["run_id"] != frame["run_id"] or not isinstance(bindings["inputs"], dict) or not isinstance(bindings["outputs"], dict):
        raise ValueError("bindings_run_mismatch")
    if not isinstance(constraints, list) or not 1 <= len(constraints) <= 16:
        raise ValueError("constraints_invalid")
    resolved = []
    for constraint in constraints:
        if not isinstance(constraint, dict) or set(constraint) != {"property", "operator", "value"} or constraint["operator"] not in {"eq", "contains"}:
            raise ValueError("constraint_invalid")
        property_name = _text(constraint["property"], "property")
        expected = _value(constraint["value"], bindings)
        if constraint["operator"] == "contains" and not isinstance(expected, str):
            raise ValueError("constraint_contains_invalid")
        resolved.append((property_name, constraint["operator"], expected))
    matching = []
    for row in rows:
        properties = row["properties"]
        if all(name in properties and ((type(properties[name]) is type(expected) and properties[name] == expected) if operator == "eq" else (isinstance(properties[name], str) and expected in properties[name])) for name, operator, expected in resolved):
            matching.append(row)
    if not matching:
        raise ValueError("visible_row_missing")
    if len(matching) != 1:
        raise ValueError("visible_row_ambiguous")
    return deepcopy(matching[0])


def resolve_row_action(row: dict, action_selector: dict, capture: dict) -> dict:
    """将当前行内唯一控件转为现有候选几何形状，不执行输入。"""
    frame = _capture(capture)
    if not isinstance(row, dict) or set(row) != {"row_id", "container_id", "capture_id", "window_identity", "bbox", "properties", "actions"}:
        raise ValueError("row_invalid")
    _bound(row, frame)
    _box(row["bbox"], {"x": 0, "y": 0, "w": frame["image_size"]["width"], "h": frame["image_size"]["height"]})
    if not isinstance(row["actions"], list) or len(row["actions"]) > 64:
        raise ValueError("row_actions_invalid")
    if not isinstance(action_selector, dict) or set(action_selector) not in ({"name", "control_type"}, {"name", "control_type", "automation_id"}):
        raise ValueError("action_selector_invalid")
    for key, value in action_selector.items():
        _text(value, key)
    for action in row["actions"]:
        _action(action, row, frame)
    matches = [action for action in row["actions"] if all(action.get(key) == value for key, value in action_selector.items())]
    if not matches:
        raise ValueError("row_action_missing")
    if len(matches) != 1:
        raise ValueError("row_action_ambiguous")
    action = matches[0]
    box = deepcopy(action["bbox"])
    candidate = {"source": "memory_visible_row", "capture_id": frame["capture_id"],
                 "viewport_size": deepcopy(frame["image_size"]), "row_id": row["row_id"],
                 "action_id": action["action_id"], "bbox": box,
                 "click_point": {"x": box["x"] + box["w"] // 2, "y": box["y"] + box["h"] // 2},
                 "label": action["name"], "role": action["control_type"]}
    return {"status": "matched", "context_verified": True, "frame": deepcopy(frame), "candidate": candidate}


__all__ = ["resolve_visible_row", "resolve_row_action"]
