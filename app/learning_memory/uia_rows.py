"""把完整、同帧的 Windows UIA 树投影为唯一可见行候选。"""

from __future__ import annotations

from copy import deepcopy

from .target_selectors import resolve_row_action, resolve_visible_row


_ROWS = frozenset({"Group", "Pane", "ListItem", "DataItem"})


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _selector(value, *, name, allow_unnamed=False):
    required = {"control_type", "name"} if name else {"control_type"}
    if allow_unnamed and isinstance(value, dict) and "name" not in value:
        required = {"control_type", "automation_id"}
    if not isinstance(value, dict) or set(value) not in (required, required | {"automation_id"}):
        raise ValueError("visible_row_strategy_invalid")
    if any(not _text(value[key]) for key in required):
        raise ValueError("visible_row_strategy_invalid")
    if "automation_id" in value and not _text(value["automation_id"]):
        raise ValueError("visible_row_strategy_invalid")


def _reference(value):
    if not isinstance(value, dict):
        raise ValueError("visible_row_strategy_reference_invalid")
    source = value.get("source")
    if source == "constant" and set(value) == {"source", "value"} and type(value["value"]) in (str, int, float, bool):
        return
    if source == "input" and set(value) == {"source", "name"} and _text(value["name"]):
        return
    if source == "output" and set(value) == {"source", "step_id", "name"} and _text(value["step_id"]) and _text(value["name"]):
        return
    raise ValueError("visible_row_strategy_reference_invalid")


def validate_visible_row_strategy(strategy: dict) -> dict:
    """校验可持久化的有限语义规则，不保存现场 control_id。"""
    if not isinstance(strategy, dict) or set(strategy) != {"kind", "container", "row", "properties", "constraints", "action"} or strategy["kind"] != "visible_row":
        raise ValueError("visible_row_strategy_invalid")
    _selector(strategy["container"], name=True, allow_unnamed=True)
    _selector(strategy["row"], name=False)
    if strategy["row"]["control_type"] not in _ROWS:
        raise ValueError("visible_row_strategy_invalid")
    if not isinstance(strategy["action"], dict):
        raise ValueError("visible_row_strategy_invalid")
    if strategy["action"].get("source") in {"row", "row_name"}:
        if (set(strategy["action"]) != {"source", "control_type"}
                or not _text(strategy["action"].get("control_type"))
                or strategy["action"]["source"] == "row"
                and strategy["action"]["control_type"] != strategy["row"]["control_type"]):
            raise ValueError("visible_row_strategy_invalid")
    else:
        _selector(strategy["action"], name=True)
    properties = strategy["properties"]
    if not isinstance(properties, list) or not 1 <= len(properties) <= 16:
        raise ValueError("visible_row_strategy_invalid")
    names = set()
    for property_spec in properties:
        if isinstance(property_spec, dict) and property_spec.get("source") == "row":
            if (set(property_spec) != {"property", "source", "control_type", "read"}
                    or not _text(property_spec.get("property"))
                    or property_spec["control_type"] != strategy["row"]["control_type"]
                    or property_spec["read"] != "name" or property_spec["property"] in names):
                raise ValueError("visible_row_strategy_invalid")
            names.add(property_spec["property"])
            continue
        if (not isinstance(property_spec, dict) or set(property_spec) not in (
                {"property", "control_type", "read"}, {"property", "control_type", "automation_id", "read"})
                or not _text(property_spec.get("property")) or property_spec.get("control_type") != "Text"
                or property_spec.get("read") != "name"
                or "automation_id" in property_spec and not _text(property_spec["automation_id"])):
            raise ValueError("visible_row_strategy_invalid")
        if property_spec["property"] in names:
            raise ValueError("visible_row_strategy_invalid")
        names.add(property_spec["property"])
    constraints = strategy["constraints"]
    if not isinstance(constraints, list) or not 1 <= len(constraints) <= 16:
        raise ValueError("visible_row_strategy_invalid")
    for item in constraints:
        if (not isinstance(item, dict) or set(item) != {"property", "operator", "value"}
                or item["property"] not in names or item["operator"] not in {"eq", "contains"}):
            raise ValueError("visible_row_strategy_invalid")
        _reference(item["value"])
        if item["operator"] == "contains" and item["value"].get("source") == "constant" and not isinstance(item["value"]["value"], str):
            raise ValueError("visible_row_strategy_invalid")
    return deepcopy(strategy)


def _matches(control, selector):
    return (control.get("visible") is True and control.get("enabled") is True
            and control.get("control_type") == selector["control_type"]
            and ("name" not in selector or control.get("name") == selector["name"])
            and ("automation_id" not in selector or control.get("automation_id") == selector["automation_id"]))


def _row_action_matches(control, selector, row):
    # 命名子区按当前父行名称匹配，不保存学习样例名称。
    return (_matches(control, selector)
            and (selector.get("source") != "row_name"
                 or _text(row.get("name")) and control.get("name") == row["name"]))


def _inside(box, parent):
    return (isinstance(box, dict) and set(box) == {"x", "y", "w", "h"}
            and all(type(box[key]) is int for key in box)
            and box["w"] > 0 and box["h"] > 0
            and box["x"] >= parent["x"] and box["y"] >= parent["y"]
            and box["x"] + box["w"] <= parent["x"] + parent["w"]
            and box["y"] + box["h"] <= parent["y"] + parent["h"])


def _bound_snapshot(snapshot, capture):
    if not isinstance(snapshot, dict) or not isinstance(capture, dict):
        raise ValueError("uia_snapshot_invalid")
    if (snapshot.get("provider") != "windows_uia" or snapshot.get("status") != "ok"
            or snapshot.get("scan_scope", "bound_window") != "bound_window"
            or snapshot.get("scan_complete") is not True or snapshot.get("truncated") is not False
            or snapshot.get("provider_tree_valid") is not True):
        raise ValueError("uia_snapshot_incomplete")
    if snapshot.get("capture_id") != capture.get("capture_id") or snapshot.get("window_identity") != capture.get("window_identity"):
        raise ValueError("uia_snapshot_capture_stale")
    identity = capture["window_identity"]
    window = snapshot.get("window")
    if not isinstance(window, dict) or window.get("handle") != identity.get("handle") or window.get("process_id") != identity.get("process_id"):
        raise ValueError("uia_snapshot_window_mismatch")
    size = capture.get("image_size")
    if not isinstance(size, dict) or set(size) != {"width", "height"} or any(type(size[key]) is not int or size[key] <= 0 for key in size):
        raise ValueError("uia_capture_size_invalid")
    controls = snapshot.get("controls")
    if not isinstance(controls, list) or not 1 <= len(controls) <= 4000:
        raise ValueError("uia_controls_missing_or_unbounded")
    ids = set()
    for control in controls:
        if not isinstance(control, dict) or not _text(control.get("control_id")):
            raise ValueError("uia_control_id_invalid")
        if control["control_id"] in ids:
            raise ValueError("uia_control_id_duplicate")
        ids.add(control["control_id"])
        chain = control.get("ancestor_control_ids")
        if not isinstance(chain, list) or any(not _text(item) for item in chain) or len(chain) != len(set(chain)) or control["control_id"] in chain:
            raise ValueError("uia_ancestor_chain_invalid")
    return controls, {"x": 0, "y": 0, "w": size["width"], "h": size["height"]}


def resolve_uia_row(snapshot: dict, strategy: dict, *, capture: dict, bindings: dict) -> dict:
    """只从同帧完整树构建当前行，交有限选择器生成候选。"""
    rule = validate_visible_row_strategy(strategy)
    controls, viewport = _bound_snapshot(snapshot, capture)
    containers = [item for item in controls if _matches(item, rule["container"])]
    if not containers:
        raise ValueError("uia_container_missing")
    if len(containers) != 1:
        raise ValueError("uia_container_ambiguous")
    parent = containers[0]
    if not _inside(parent.get("bbox"), viewport):
        raise ValueError("uia_container_bbox_invalid")
    container_id = parent["control_id"]
    candidates = [item for item in controls if container_id in item["ancestor_control_ids"] and _matches(item, rule["row"])]
    if len(candidates) > 512:
        raise ValueError("uia_rows_unbounded")
    row_ids = {item["control_id"] for item in candidates}
    for item in candidates:
        if row_ids.intersection(item["ancestor_control_ids"]):
            raise ValueError("uia_multiple_row_ancestors")
        if not _inside(item.get("bbox"), parent["bbox"]):
            raise ValueError("uia_row_bbox_invalid")
    projected = []
    for item in candidates:
        row_id = item["control_id"]
        descendants = []
        for child in controls:
            chain = child["ancestor_control_ids"]
            if row_id not in chain:
                continue
            owners = row_ids.intersection(chain)
            if len(owners) != 1 or container_id not in chain:
                raise ValueError("uia_multiple_row_ancestors")
            descendants.append(child)
        properties = {}
        for spec in rule["properties"]:
            matches = [item] if spec.get("source") == "row" else [child for child in descendants if _matches(child, spec)]
            if not matches:
                raise ValueError("uia_property_missing")
            if len(matches) != 1:
                raise ValueError("uia_property_ambiguous")
            child = matches[0]
            if not _inside(child.get("bbox"), item["bbox"]):
                raise ValueError("uia_property_bbox_invalid")
            if not _text(child.get("name")):
                raise ValueError("uia_property_value_missing")
            properties[spec["property"]] = child["name"]
        actions = []
        for child in ([item] if rule["action"].get("source") == "row" else descendants):
            if not _row_action_matches(child, rule["action"], item):
                continue
            if not _inside(child.get("bbox"), item["bbox"]):
                raise ValueError("uia_action_bbox_invalid")
            actions.append({"action_id": child["control_id"], "row_id": row_id,
                            "capture_id": capture["capture_id"], "window_identity": deepcopy(capture["window_identity"]),
                            "name": child["name"], "control_type": child["control_type"],
                            **({"automation_id": child["automation_id"]} if _text(child.get("automation_id")) else {}),
                            "bbox": deepcopy(child["bbox"])})
        projected.append({"row_id": row_id, "container_id": container_id,
                          "capture_id": capture["capture_id"], "window_identity": deepcopy(capture["window_identity"]),
                          "bbox": deepcopy(item["bbox"]), "properties": properties, "actions": actions})
    finite_capture = {key: deepcopy(capture[key]) for key in ("capture_id", "window_identity", "image_size", "run_id")}
    if "sha256" in capture:
        finite_capture["sha256"] = capture["sha256"]
    container = {"container_id": container_id, "capture_id": capture["capture_id"],
                 "window_identity": deepcopy(capture["window_identity"]), "bbox": deepcopy(parent["bbox"]), "complete": True}
    selected = resolve_visible_row(container=container, rows=projected, constraints=rule["constraints"],
                                   bindings=bindings, capture=finite_capture)
    action_selector = rule["action"]
    if action_selector.get("source") in {"row", "row_name"}:
        if not selected["actions"]:
            raise ValueError("row_action_missing")
        # 唯一行已由当前帧约束选定，自身动作不再用样例名称锁定。
        action_selector = {"control_type": selected["actions"][0]["control_type"],
                           "name": selected["actions"][0]["name"]}
    result = resolve_row_action(selected, action_selector, finite_capture)
    result["evidence"] = {"container_control_id": container_id, "row_control_id": selected["row_id"],
                          "action_control_id": result["candidate"]["action_id"],
                          "snapshot_capture_id": capture["capture_id"], "provider_tree_valid": True}
    return result


__all__ = ["validate_visible_row_strategy", "resolve_uia_row"]
