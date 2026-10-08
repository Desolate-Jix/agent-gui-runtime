"""有限语义目标只绑定门控入口刚采集的完整原生树。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import unicodedata

from PIL import Image


CONTROL_TYPES = frozenset({"Button", "Hyperlink", "Edit", "ComboBox", "MenuItem", "TabItem"})
CONTAINER_TYPES = frozenset({"Window", "Pane", "Group", "Custom", "ToolBar", "Menu", "Tab"})


def validate_task_plan_control_target(value, *, for_input=False):
    if (not isinstance(value, dict) or not {"name", "control_type"} <= set(value)
            or set(value) - {"name", "control_type", "container"}):
        raise ValueError("task_plan_target_fields_invalid")
    def semantic(item, types):
        if (not isinstance(item, dict) or set(item) != {"name", "control_type"}
                or not isinstance(item["name"], str) or not item["name"].strip()
                or len(item["name"]) > 512 or not isinstance(item["control_type"], str)
                or item["control_type"] not in types):
            raise ValueError("task_plan_target_semantics_invalid")
    semantic({key: value[key] for key in ("name", "control_type")},
             {"Edit", "ComboBox"} if for_input else CONTROL_TYPES)
    if "container" in value:
        semantic(value["container"], CONTAINER_TYPES)
    return deepcopy(value)


def _name(value):
    return unicodedata.normalize("NFC", value).strip().casefold() if isinstance(value, str) else ""


def _box(value):
    return (isinstance(value, dict) and all(type(value.get(key)) is int for key in ("x", "y", "w", "h"))
            and value["w"] > 0 and value["h"] > 0)


def bind_task_plan_capture(metadata, *, live_capture, before, current, identity=None):
    """清除调用方绑定，只从门控入口的当前截图和窗口事实重建。"""
    metadata = deepcopy(metadata or {})
    metadata.pop("task_plan_capture", None)
    if metadata.get("task_plan_target") is None:
        return metadata
    metadata["task_plan_target"] = validate_task_plan_control_target(metadata["task_plan_target"])
    if (not isinstance(before, dict) or not isinstance(current, dict)
            or any(type(before.get(key)) is not int or before[key] <= 0
                   or current.get(key) != before[key] for key in ("handle", "process_id"))
            or current.get("rect") != before.get("rect")):
        raise ValueError("task_plan_target_window_mismatch")
    rect = before.get("rect") or {}
    screen_rect = {"x": rect.get("left"), "y": rect.get("top"), "w": rect.get("width"), "h": rect.get("height")}
    if (not _box(screen_rect) or not isinstance(live_capture, dict) or live_capture.get("roi") is not None
            or live_capture.get("window_size") != {"width": screen_rect["w"], "height": screen_rect["h"]}):
        raise ValueError("task_plan_target_live_full_capture_required")
    try:
        path = Path(live_capture["image_path"]).resolve(strict=True)
        digest = sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as image:
            if image.size != (screen_rect["w"], screen_rect["h"]):
                raise ValueError("image viewport mismatch")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError("task_plan_target_capture_changed") from error
    window_identity = {key: before[key] for key in ("handle", "process_id")}
    if isinstance(identity, dict) and identity.get("process_create_time") is not None:
        window_identity["process_create_time"] = identity["process_create_time"]
    metadata["task_plan_capture"] = {"capture_id": str(path), "image_path": str(path), "sha256": digest,
        "image_size": {"width": screen_rect["w"], "height": screen_rect["h"]},
        "window_identity": window_identity, "screen_rect": screen_rect}
    return metadata


def validate_task_plan_dispatch_capture(capture, *, current, image_path):
    """输入前检查当前窗口和原文件；不重复扫描整棵 UIA 树。"""
    if not isinstance(capture, dict) or not isinstance(current, dict):
        raise ValueError("task_plan_target_capture_unavailable")
    identity = capture.get("window_identity") or {}
    rect = current.get("rect") or {}
    if (any(current.get(key) != identity.get(key) for key in ("handle", "process_id"))
            or capture.get("screen_rect") != {"x": rect.get("left"), "y": rect.get("top"),
                                            "w": rect.get("width"), "h": rect.get("height")}):
        raise ValueError("task_plan_target_window_mismatch")
    try:
        path = Path(image_path).resolve(strict=True)
        if path != Path(capture["image_path"]).resolve(strict=True) or sha256(path.read_bytes()).hexdigest() != capture["sha256"]:
            raise ValueError("image changed")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError("task_plan_target_capture_changed") from error
    return {"status": "matched", "capture_id": capture["capture_id"], "source": "windows_uia"}


def validate_task_plan_dispatch_target(target, *, resolution, capture, point, window_manager, identity):
    """沿本次选择的原身份做最终只读命中；不是新的授权或原子输入证明。"""
    from app.agent.windows_control_hit_reader import WindowsControlHitReader
    target = validate_task_plan_control_target(target)
    if (not isinstance(resolution, dict) or resolution.get("status") != "matched"
            or resolution.get("target") != target or not isinstance(capture, dict)
            or resolution.get("capture_id") != capture.get("capture_id")
            or resolution.get("screenshot_sha256") != capture.get("sha256")
            or resolution.get("window_identity") != capture.get("window_identity")
            or not isinstance(identity, dict)
            or identity.get("target_window_handle") != capture["window_identity"].get("handle")
            or identity.get("process_id") != capture["window_identity"].get("process_id")
            or identity.get("process_create_time") != capture["window_identity"].get("process_create_time")
            or not isinstance(point, dict) or set(point) != {"x", "y"}
            or any(type(point[key]) is not int for key in point)):
        raise ValueError("task_plan_target_dispatch_binding_invalid")
    box, rect = resolution.get("bbox"), capture.get("screen_rect")
    if not _box(box) or not _box(rect):
        raise ValueError("task_plan_target_geometry_invalid")
    container = resolution.get("container_binding")
    if "container" in target:
        if (not isinstance(container, dict) or container.get("name") != target["container"]["name"]
                or container.get("control_type") != target["container"]["control_type"]
                or not _box(container.get("bbox"))):
            raise ValueError("task_plan_target_dispatch_container_invalid")
        container = {**container, "bbox": tuple(container["bbox"][key] for key in ("x", "y", "w", "h"))}
    elif container is not None:
        raise ValueError("task_plan_target_dispatch_container_invalid")
    observation = WindowsControlHitReader(window_manager=window_manager).observe_target_hit(
        window_handle=identity["target_window_handle"], process_id=identity["process_id"],
        process_create_time=identity["process_create_time"], window_rect=tuple(rect[k] for k in ("x", "y", "w", "h")),
        capture_id=capture["capture_id"], control_id=resolution["control_id"],
        point=(point["x"], point["y"]), expected_runtime_id=resolution["runtime_id"],
        expected_control_type=target["control_type"], expected_name=target["name"],
        expected_bbox=tuple(box[k] for k in ("x", "y", "w", "h")), expected_container=container)
    return {"status": "matched", **observation}


def task_plan_visual_goal(goal, target):
    target = validate_task_plan_control_target(target)
    return (goal + "\nThe following structured target is mandatory: "
        + json.dumps(target, ensure_ascii=False, sort_keys=True)
        + ". Match its exact name, control_type and ancestor container; do not choose a substitute. "
        "If you cannot uniquely locate this target, refuse.")


def validate_task_plan_visual_selection(target, *, capture, snapshot, action, bbox, point):
    """模型只能在仍符合显式语义的本次控件内消除歧义。"""
    if (not isinstance(action, dict) or action.get("source") != "windows_uia.controls"
            or not isinstance(action.get("source_id"), str)):
        raise ValueError("task_plan_target_visual_semantics_unconfirmed")
    value = resolve_current_uia_target(target, capture=capture, snapshot=snapshot,
        _visual_control_id=action["source_id"])
    if (value["status"] != "matched" or action.get("bbox") != value["bbox"] or bbox != value["bbox"]
            or not isinstance(point, dict) or any(type(point.get(key)) is not int for key in ("x", "y"))
            or not value["bbox"]["x"] <= point["x"] < value["bbox"]["x"] + value["bbox"]["w"]
            or not value["bbox"]["y"] <= point["y"] < value["bbox"]["y"] + value["bbox"]["h"]):
        raise ValueError("task_plan_target_visual_semantics_unconfirmed")
    return {**value, "click_point": dict(point), "selection_source": "vista_point_v1"}


def resolve_current_uia_target(target, *, capture, snapshot, _visual_control_id=None):
    """缺失和歧义可继续视觉；采集、身份或几何错误必须显式阻止。"""
    target = validate_task_plan_control_target(target)
    if not isinstance(capture, dict) or not isinstance(snapshot, dict):
        raise ValueError("task_plan_target_capture_unavailable")
    if snapshot.get("provider") != "windows_uia" or snapshot.get("status") != "ok":
        raise ValueError("task_plan_target_uia_provider_failed")
    if (snapshot.get("scan_scope", "bound_window") != "bound_window"
            or snapshot.get("scan_complete") is not True or snapshot.get("truncated") is not False
            or snapshot.get("provider_tree_valid") is not True):
        raise ValueError("task_plan_target_uia_incomplete")
    window, identity = snapshot.get("window"), capture.get("window_identity")
    if (not isinstance(window, dict) or not isinstance(identity, dict)
            or any(type(identity.get(key)) is not int or identity[key] <= 0
                   or window.get(key) != identity[key] for key in ("handle", "process_id"))
            or (window.get("process_create_time") is not None
                and window["process_create_time"] != identity.get("process_create_time"))):
        raise ValueError("task_plan_target_window_mismatch")
    size, rect = capture.get("image_size"), capture.get("screen_rect")
    if (not isinstance(size, dict) or set(size) != {"width", "height"}
            or any(type(size[key]) is not int or size[key] <= 0 for key in size)
            or not _box(rect) or rect["w"] != size["width"] or rect["h"] != size["height"]
            or window.get("bbox") != {"x": 0, "y": 0, "w": size["width"], "h": size["height"]}):
        raise ValueError("task_plan_target_viewport_mismatch")
    try:
        path = Path(capture["image_path"]).resolve(strict=True)
        if not isinstance(capture.get("capture_id"), str) or not capture["capture_id"]:
            raise ValueError("capture identity missing")
        if sha256(path.read_bytes()).hexdigest() != capture.get("sha256"):
            raise ValueError("capture content changed")
        with Image.open(path) as image:
            if image.size != (size["width"], size["height"]):
                raise ValueError("capture size changed")
        if ((snapshot.get("capture_id") is not None and snapshot["capture_id"] != capture["capture_id"])
                or (snapshot.get("screenshot_sha256") is not None
                    and snapshot["screenshot_sha256"] != capture["sha256"])):
            raise ValueError("snapshot capture changed")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError("task_plan_target_capture_changed") from error
    controls = snapshot.get("controls")
    if not isinstance(controls, list) or not all(isinstance(item, dict) for item in controls):
        raise ValueError("task_plan_target_uia_identity_invalid")
    identifiers = [item.get("control_id") for item in controls]
    if (any(not isinstance(item, str) or not item for item in identifiers)
            or len(set(identifiers)) != len(identifiers)):
        raise ValueError("task_plan_target_uia_identity_invalid")
    identifier_set = set(identifiers)
    for item in controls:
        ancestors = item.get("ancestor_control_ids")
        if (item.get("provider") != "windows_uia" or not isinstance(ancestors, list)
                or any(not isinstance(value, str) or value not in identifier_set or value == item["control_id"]
                       for value in ancestors) or len(set(ancestors)) != len(ancestors)):
            raise ValueError("task_plan_target_uia_identity_invalid")
    by_id = {item["control_id"]: item for item in controls}
    if any(item["control_id"] in by_id[ancestor]["ancestor_control_ids"]
           for item in controls for ancestor in item["ancestor_control_ids"]):
        raise ValueError("task_plan_target_uia_identity_invalid")
    def matches(item, semantic):
        return item.get("control_type") == semantic["control_type"] and _name(item.get("name")) == _name(semantic["name"])
    result = {"source": "windows_uia", "target": target, "capture_id": capture["capture_id"],
              "screenshot_sha256": capture["sha256"], "viewport_size": deepcopy(size),
              "window_identity": deepcopy(identity), "freshness": "current_capture"}
    container = None
    visual_control = by_id.get(_visual_control_id) if _visual_control_id is not None else None
    if _visual_control_id is not None and visual_control is None:
        return {**result, "status": "miss", "match_count": 0}
    if "container" in target:
        parents = [item for item in controls if matches(item, target["container"])
            and (visual_control is None or item["control_id"] in visual_control["ancestor_control_ids"])]
        if len(parents) != 1:
            return {**result, "status": "ambiguous" if parents else "miss", "match_count": len(parents)}
        container = parents[0]
    matches_ = [item for item in controls if matches(item, target)
                and (_visual_control_id is None or item["control_id"] == _visual_control_id)
                and (container is None or container["control_id"] in item["ancestor_control_ids"])]
    if len(matches_) != 1:
        return {**result, "status": "ambiguous" if matches_ else "miss", "match_count": len(matches_)}
    selected = matches_[0]
    for item in (selected, container) if container is not None else (selected,):
        bbox = item.get("bbox")
        if (not _box(bbox) or bbox["x"] < 0 or bbox["y"] < 0
                or bbox["x"] + bbox["w"] > size["width"] or bbox["y"] + bbox["h"] > size["height"]):
            raise ValueError("task_plan_target_geometry_invalid")
        if item.get("screen_bbox") != {**bbox, "x": bbox["x"] + rect["x"], "y": bbox["y"] + rect["y"]}:
            raise ValueError("task_plan_target_coordinate_mismatch")
        if item.get("visible") is not True or item.get("enabled") is not True:
            raise ValueError("task_plan_target_control_unavailable")
    box = selected["bbox"]
    if container is not None:
        parent = container["bbox"]
        if (box["x"] < parent["x"] or box["y"] < parent["y"]
                or box["x"] + box["w"] > parent["x"] + parent["w"]
                or box["y"] + box["h"] > parent["y"] + parent["h"]):
            raise ValueError("task_plan_target_geometry_invalid")
    runtime_id = selected.get("runtime_id")
    if (not isinstance(runtime_id, (list, tuple)) or not runtime_id
            or any(type(value) is not int for value in runtime_id)
            or sum(item.get("runtime_id") == runtime_id for item in controls) != 1):
        raise ValueError("task_plan_target_uia_identity_invalid")
    container_binding = None
    if container is not None:
        parent_runtime = container.get("runtime_id")
        if (type(parent_runtime) not in (list, tuple) or not parent_runtime
                or any(type(value) is not int for value in parent_runtime)
                or sum(item.get("runtime_id") == parent_runtime for item in controls) != 1):
            raise ValueError("task_plan_target_uia_identity_invalid")
        container_binding = {"runtime_id": list(parent_runtime), "control_type": target["container"]["control_type"],
            "name": target["container"]["name"], "bbox": deepcopy(container["bbox"])}
    if target["control_type"] in {"Edit", "ComboBox"}:
        from app.operation.recognition.control_target import uia_control_has_text_entry_patterns
        if (not uia_control_has_text_entry_patterns(selected)
                or any(selected.get(key) is True for key in ("is_read_only", "read_only", "readonly",
                         "is_password", "is_protected", "protected"))):
            raise ValueError("task_plan_target_field_not_writable")
    return {**result, "status": "matched", "match_count": 1, "control_id": selected["control_id"],
            "runtime_id": list(runtime_id), "bbox": deepcopy(box),
            **({"container_binding": container_binding} if container_binding is not None else {}),
            "click_point": {"x": box["x"] + box["w"] // 2, "y": box["y"] + box["h"] // 2}}
