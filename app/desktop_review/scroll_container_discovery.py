"""从同帧封存 UIA 投影只读滚动容器，不读取当前窗口或授予动作权限。"""

from hashlib import sha256
import re

from app.agent_link.contracts import AgentLinkError, canonical_hash


_KINDS = {"pane", "document", "group", "list", "datagrid", "tree"}


def discover_scroll_containers(packet, source_context):
    evidence = packet.evidence()
    capture = evidence["capture"]
    result = {
        "contract_version": "observed_scroll_containers_v1",
        "status": "unavailable", "reason": "source_context_unavailable",
        "capture_id": capture["capture_id"],
        "screenshot_sha256": capture["screenshot_sha256"],
        "uia_snapshot_sha256": evidence["uia"]["snapshot_sha256"],
        "containers": [], "artifact_is_authorization": False,
        "execute_binding_enabled": False, "action_executed": False,
    }
    try:
        tree = source_context(packet)
    except AgentLinkError:
        return result
    if (sha256(packet.png_bytes).hexdigest() != capture["screenshot_sha256"]
            or canonical_hash(tree) != evidence["uia"]["snapshot_sha256"]):
        return {**result, "reason": "source_context_binding_invalid"}
    if (tree.get("provider") != "windows_uia" or tree.get("status") != "ok"
            or tree.get("scan_complete") is not True or tree.get("truncated") is not False):
        return {**result, "reason": "source_context_incomplete"}
    controls = tree.get("controls")
    if not isinstance(controls, list) or tree.get("control_count") != len(controls):
        return {**result, "reason": "source_context_invalid"}
    ids = [item.get("control_id") for item in controls if isinstance(item, dict)]
    if (len(ids) != len(controls) or any(not isinstance(item, str) or not item for item in ids)
            or len(set(ids)) != len(ids)):
        return {**result, "reason": "source_context_invalid"}
    target, window = evidence["target"], tree.get("window", {})
    if (window.get("handle") != target["window_handle"]
            or window.get("process_id") != target["process_id"]):
        return {**result, "reason": "source_context_binding_invalid"}
    viewport = capture["viewport_size"]
    unknown_axes = False
    for control in controls:
        role = control.get("control_type")
        if (not isinstance(role, str) or role.replace(" ", "").casefold() not in _KINDS
                or control.get("visible") is not True or control.get("enabled") is not True):
            continue
        patterns = control.get("patterns")
        if not isinstance(patterns, list) or not {"Scroll", "ScrollPattern"}.intersection(patterns):
            continue
        axes = control.get("scroll_axes")
        if (not isinstance(axes, dict) or set(axes) != {"current_vertical", "current_horizontal"}
                or any(value is not True and value is not False and value is not None for value in axes.values())):
            unknown_axes = True
            continue
        confirmed = [axis for axis in ("vertical", "horizontal") if axes["current_" + axis] is True]
        if not confirmed:
            unknown_axes |= any(value is None for value in axes.values())
            continue
        box = control.get("bbox")
        if (not isinstance(box, dict) or set(box) != {"x", "y", "w", "h"}
                or any(type(value) is not int for value in box.values())
                or box["x"] < 0 or box["y"] < 0 or box["w"] <= 0 or box["h"] <= 0
                or box["x"] + box["w"] > viewport["width"]
                or box["y"] + box["h"] > viewport["height"]):
            continue
        ident = control["control_id"]
        if len(ident) > 256 or any(char in ident for char in ("/", "\\", "\x00")):
            continue
        name = control.get("name")
        # 名称是可访问性标签，不把值、路径或敏感输入内容投影到公共发现。
        if (not isinstance(name, str) or control.get("is_password") is True
                or control.get("sensitive") is True or "\x00" in name
                or re.search(r"(?:[A-Za-z]:[\\/]|\\\\|(?:token|password|secret)\s*[=:])", name, re.I)):
            name = ""
        result["containers"].append({"control_id": ident, "role": role, "name": name[:200],
                                     "bbox": dict(box), "scroll_axes": confirmed})
    if not result["containers"] and unknown_axes:
        return {**result, "reason": "scroll_axes_unavailable"}
    return {**result, "status": "available", "reason": "observed"}
