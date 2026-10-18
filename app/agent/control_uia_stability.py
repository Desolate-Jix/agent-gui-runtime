"""共用的只读 UIA 上下文证明；仅允许独立远端工具栏叶名称变化。"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import hypot, isfinite

from app.agent.fresh_learning_action_contracts import payload_sha256


_CONTROL_KEYS = {"provider", "control_id", "name", "control_type", "automation_id", "class_name",
    "bbox", "screen_bbox", "enabled", "visible", "patterns", "runtime_id", "ancestor_control_ids"}
_SNAPSHOT_KEYS = {"provider", "provider_version", "status", "scan_budget", "scan_visited_count",
    "scan_complete", "truncated", "truncation_reason", "window", "control_count", "controls"}
_WINDOW_KEYS = {"handle", "process_id", "process_name", "title", "bbox"}
_CONTEXT_TYPES = {"Document", "Group", "Dialog"}
_BORDER = 8
_MIN_DISTANCE = 64


@dataclass(frozen=True, slots=True)
class ControlContextIdentity:
    window_handle: int
    process_id: int
    process_create_time: float
    runtime_id: tuple[int, ...]
    window_rect: tuple[int, int, int, int]
    control_bbox: tuple[int, int, int, int]

    def __post_init__(self):
        if (type(self.window_handle) is not int or self.window_handle <= 0
                or type(self.process_id) is not int or self.process_id <= 0
                or type(self.process_create_time) not in (float, int)
                or not isfinite(self.process_create_time) or self.process_create_time <= 0):
            raise ValueError("control context process identity is invalid")
        if (type(self.runtime_id) is not tuple or not 1 <= len(self.runtime_id) <= 64
                or any(type(item) is not int for item in self.runtime_id)):
            raise ValueError("control context runtime identity is unavailable")
        for rect in (self.window_rect, self.control_bbox):
            if (type(rect) is not tuple or len(rect) != 4
                    or any(type(item) is not int for item in rect) or min(rect[2:]) <= 0):
                raise ValueError("control context geometry is invalid")
        x, y, width, height = self.control_bbox
        if min(x, y) < 0 or x + width > self.window_rect[2] or y + height > self.window_rect[3]:
            raise ValueError("control context is outside the bound window")

    def to_reference(self):
        return {"window_handle": self.window_handle, "process_id": self.process_id,
            "process_create_time": self.process_create_time, "runtime_id": list(self.runtime_id),
            "window_rect": list(self.window_rect), "control_bbox": list(self.control_bbox)}


def _reject(reason):
    raise ValueError("control UIA stability: " + reason)


def _box(value):
    if (not isinstance(value, dict) or set(value) != {"x", "y", "w", "h"}
            or any(type(value[key]) is not int for key in value)
            or value["w"] <= 0 or value["h"] <= 0):
        _reject("invalid control geometry")
    return tuple(value[key] for key in ("x", "y", "w", "h"))


def _contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
        and inner[0]+inner[2] <= outer[0]+outer[2] and inner[1]+inner[3] <= outer[1]+outer[3])


def _distance(first, second):
    return hypot(max(first[0]-second[0]-second[2], second[0]-first[0]-first[2], 0),
                 max(first[1]-second[1]-second[3], second[1]-first[1]-first[3], 0))


def _overlaps(first, second):
    return (first[0] < second[0]+second[2] and second[0] < first[0]+first[2]
        and first[1] < second[1]+second[3] and second[1] < first[1]+first[3])


def _snapshot(evidence, uia, identity):
    if not isinstance(evidence, dict) or not isinstance(uia, dict):
        _reject("snapshot and evidence must be mappings")
    target, summary = evidence.get("target"), evidence.get("uia")
    application, capture = evidence.get("application"), evidence.get("capture")
    rect = dict(zip(("x", "y", "width", "height"), identity.window_rect))
    if (target != {"window_handle": identity.window_handle, "process_id": identity.process_id, "rect": rect}
            or not isinstance(application, dict) or application.get("process_create_time") != identity.process_create_time
            or not isinstance(capture, dict)
            or capture.get("viewport_size") != {"width": rect["width"], "height": rect["height"]}):
        _reject("field window or application binding changed")
    keys = {"provider", "provider_version", "status", "control_count", "snapshot_sha256"}
    if (not isinstance(summary, dict) or set(summary) != keys
            or uia.get("provider") != "windows_uia" or uia.get("status") != "ok"
            or not isinstance(uia.get("provider_version"), str) or not uia["provider_version"]
            or not isinstance(uia.get("controls"), list)
            or type(uia.get("control_count")) is not int or uia["control_count"] != len(uia["controls"])
            or any(uia.get(key) != summary[key] for key in keys - {"snapshot_sha256"})):
        _reject("snapshot summary binding is invalid")
    try:
        digest = payload_sha256(uia)
    except (TypeError, ValueError):
        _reject("snapshot is not canonical JSON")
    if digest != summary["snapshot_sha256"]:
        _reject("snapshot digest mismatch")
    window = uia.get("window")
    if (not isinstance(window, dict) or type(window.get("handle")) is not int
            or type(window.get("process_id")) is not int
            or window["handle"] != identity.window_handle or window["process_id"] != identity.process_id
            or _box(window.get("bbox")) not in ((0, 0, rect["width"], rect["height"]), identity.window_rect)):
        _reject("snapshot window binding is invalid")
    return digest


def _index(uia, identity, *, complete, navigation=False):
    controls = uia["controls"]
    indexed, runtime_ids = {}, set()
    if complete:
        if (set(uia) != _SNAPSHOT_KEYS or set(uia["window"]) != _WINDOW_KEYS
                or uia["scan_complete"] is not True or uia["truncated"] is not False
                or uia["truncation_reason"] is not None
                or type(uia["scan_budget"]) is not int or type(uia["scan_visited_count"]) is not int
                or not len(controls) <= uia["scan_visited_count"] < uia["scan_budget"]):
            _reject("changed trees require a complete known scan contract")
    for control in controls:
        if not isinstance(control, dict):
            _reject("invalid control")
        cid, runtime = control.get("control_id"), control.get("runtime_id")
        if not isinstance(cid, str) or not cid or cid in indexed:
            _reject("control identity is missing or duplicated")
        indexed[cid] = control
        if runtime is not None:
            if (type(runtime) is not list or not 1 <= len(runtime) <= 64
                    or any(type(number) is not int for number in runtime) or tuple(runtime) in runtime_ids):
                _reject("runtime identity is invalid or duplicated")
            runtime_ids.add(tuple(runtime))
        if complete:
            if (set(control) != _CONTROL_KEYS or runtime is None or control["provider"] != "windows_uia"
                    or not isinstance(control["control_type"], str) or not control["control_type"]
                    or any(control[key] is not None and not isinstance(control[key], str)
                           for key in ("name", "automation_id", "class_name"))
                    or any(control[key] is not None and type(control[key]) is not bool for key in ("enabled", "visible"))
                    or type(control["patterns"]) is not list or any(not isinstance(item, str) for item in control["patterns"])
                    or len(set(control["patterns"])) != len(control["patterns"])):
                _reject("changed trees require complete known control identities")
            box = _box(control["bbox"])
            if _box(control["screen_bbox"]) != (box[0]+identity.window_rect[0], box[1]+identity.window_rect[1], box[2], box[3]):
                _reject("control screen geometry is not bound to the window")
    for cid, control in indexed.items():
        chain = control.get("ancestor_control_ids")
        if chain is None and not complete:
            continue
        if (type(chain) is not list or any(not isinstance(item, str) or item not in indexed for item in chain)
                or cid in chain or len(set(chain)) != len(chain)):
            _reject("ancestor references are missing, cyclic or duplicated")
        for index, ancestor in enumerate(chain):
            known = indexed[ancestor].get("ancestor_control_ids")
            if (known is not None or complete) and known != chain[index+1:]:
                _reject("ancestor references are inconsistent")
    # 审核字段 ID 属于逻辑协议；当前 UIA 实例由唯一 runtime 与确切框绑定。
    fields = [control for control in controls if control.get("runtime_id") == list(identity.runtime_id)]
    if len(fields) != 1 or _box(fields[0].get("bbox")) != identity.control_bbox:
        _reject("selected field identity differs")
    field = fields[0]
    if navigation and (field.get("control_type") not in {"Button", "Hyperlink"}
            or field.get("enabled") is not True or field.get("visible") is not True
            or type(field.get("patterns")) is not list
            or any(not isinstance(item, str) for item in field["patterns"])
            or not set(field["patterns"]) & {"Invoke", "InvokePattern"}):
        _reject("navigation target is not an available invokable Button or Hyperlink")
    if complete:
        roots = [cid for cid, control in indexed.items() if not control["ancestor_control_ids"]]
        if (len(roots) != 1 or indexed[roots[0]]["control_type"] != "Window"
                or any(control["ancestor_control_ids"] and control["ancestor_control_ids"][-1] != roots[0]
                       for control in controls)
                or field["enabled"] is not True or field["visible"] is not True
                or not navigation and not set(field["patterns"]) & {"Value", "Text", "ValuePattern", "TextPattern"}):
            _reject("field or complete tree root is unavailable")
    return indexed, field


def _compare_uia_context(*, identity, original_evidence, original_uia,
                         current_evidence, current_uia, navigation=False) -> dict | None:
    """返回纯派生引用或严格相等的 None；不修改输入，也不生成执行授权。"""
    before_sha = _snapshot(original_evidence, original_uia, identity)
    after_sha = _snapshot(current_evidence, current_uia, identity)
    if original_evidence["application"] != current_evidence["application"]:
        _reject("application identity changed")
    same = before_sha == after_sha and original_uia == current_uia
    before, field = _index(original_uia, identity, complete=not same, navigation=navigation)
    _index(current_uia, identity, complete=not same, navigation=navigation)
    if same:
        return None
    if ({key:value for key,value in original_uia.items() if key != "controls"}
            != {key:value for key,value in current_uia.items() if key != "controls"}):
        _reject("snapshot structure changed")
    ancestors = field["ancestor_control_ids"]
    semantic_ancestors = {cid for cid in ancestors if before[cid]["control_type"] in _CONTEXT_TYPES}
    contexts = [cid for cid in ancestors if before[cid]["control_type"] in _CONTEXT_TYPES
                and _contains(_box(before[cid]["bbox"]), identity.control_bbox)]
    if not contexts:
        _reject("field context is unavailable")
    context_id = contexts[0]
    context_ids = {cid for cid, control in before.items()
        if cid == context_id or context_id in control["ancestor_control_ids"]}
    protected_ids = context_ids | set(ancestors) | {field["control_id"]}
    x, y, w, h = identity.control_bbox
    viewport = (0, 0, identity.window_rect[2], identity.window_rect[3])
    left, top = max(0, x-_BORDER), max(0, y-_BORDER)
    protected_box = (left, top, min(viewport[2], x+w+_BORDER)-left, min(viewport[3], y+h+_BORDER)-top)
    changes = []
    for index, (old, new) in enumerate(zip(original_uia["controls"], current_uia["controls"])):
        if old == new:
            continue
        cid = old["control_id"]
        if ({key:value for key,value in old.items() if key != "name"}
                != {key:value for key,value in new.items() if key != "name"}
                or cid in protected_ids or any(cid in item["ancestor_control_ids"] for item in before.values())
                or any(not isinstance(item["name"], str) or not item["name"].strip() for item in (old, new))):
            _reject("change is not an independent toolbar leaf name")
        toolbars = [before[aid] for aid in old["ancestor_control_ids"] if before[aid]["control_type"] == "ToolBar"]
        box = _box(old["bbox"])
        if (not toolbars or toolbars[0]["control_id"] in protected_ids
                # 最近 Group 不是外层表单边界；共享任一语义祖先仍属于同一上下文。
                or semantic_ancestors.intersection(toolbars[0]["ancestor_control_ids"])
                or not _contains(viewport, box) or _distance(box, protected_box) < _MIN_DISTANCE
                or not _contains(_box(toolbars[0]["bbox"]), box)
                # 距离约束作用于实际变化叶；横跨窗口的工具栏只要求不覆盖目标保护框。
                or _overlaps(_box(toolbars[0]["bbox"]), protected_box)):
            _reject("changed name is not outside the protected field context")
        changes.append({"index": index, "control_id": cid,
            "before_name_sha256": sha256(old["name"].encode("utf-8")).hexdigest(),
            "after_name_sha256": sha256(new["name"].encode("utf-8")).hexdigest()})
    if not changes:
        _reject("unclassified snapshot change")
    context_controls = [item for item in original_uia["controls"] if item["control_id"] in protected_ids]
    return {"before_uia_sha256": before_sha, "after_uia_sha256": after_sha,
        "identity_sha256": payload_sha256(identity.to_reference()), "context_root_id": context_id,
        "context_sha256": payload_sha256({"controls": context_controls}), "changes": changes}


def compare_navigation_uia_context(*, control_identity, original_evidence, original_uia,
                                   current_evidence, current_uia) -> dict | None:
    """导航仅产生可重算引用；不代替点、像素、风险或授权校验。"""
    if type(control_identity) is not ControlContextIdentity:
        raise TypeError("navigation UIA stability requires a typed control identity")
    identity = ControlContextIdentity(**{key: getattr(control_identity, key)
        for key in ControlContextIdentity.__dataclass_fields__})
    result = _compare_uia_context(identity=identity, original_evidence=original_evidence,
        original_uia=original_uia, current_evidence=current_evidence, current_uia=current_uia,
        navigation=True)
    if result is None:
        return None
    return {"contract_version": "navigation_uia_stability_reference_v1", "policy": "navigation_uia_context_v1",
        "control_identity_sha256": result.pop("identity_sha256"), **result}
