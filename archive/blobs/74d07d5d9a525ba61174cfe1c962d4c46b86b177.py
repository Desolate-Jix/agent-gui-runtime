"""串行所有者上的只读表单状态观察；不执行 UIA 或原生输入动作。"""
from __future__ import annotations

import unicodedata
import math
import time
from pathlib import PureWindowsPath
from app.operation.screen_reading.uia_graph import CanonicalUIAGraph, UIAGraphError

from .native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
from .windows_text_field_reader import (
    _bound_rect, _explicit_true_call, _rect_valid, _relative_rect, _top_window_handle,
)


_CONTROL_TYPES = frozenset({
    "Button", "Calendar", "CheckBox", "ComboBox", "Edit", "Hyperlink", "Image", "ListItem",
    "List", "Menu", "MenuBar", "MenuItem", "ProgressBar", "RadioButton", "ScrollBar", "Slider",
    "Spinner", "StatusBar", "Tab", "TabItem", "Text", "ToolBar", "ToolTip", "Tree", "TreeItem",
    "Custom", "Group", "Thumb", "DataGrid", "DataItem", "Document", "SplitButton", "Window",
    "Pane", "Header", "HeaderItem", "Table", "TitleBar", "Separator", "SemanticZoom", "AppBar", "Other",
})
_readiness_clock = time.monotonic
_readiness_wait = time.sleep


def _safe_diagnostics(value, *, include_option=True, include_readiness=True):
    """只保留树结构计数与目标整数身份，绝不传播供应方名称、值或异常。"""
    if not isinstance(value, dict):
        return {}
    result = {}
    if value.get("scope") in {"window_control_view", "window_finite_children"}:
        result["scope"] = value["scope"]
    for key in ("window_handle", "process_id"):
        if type(value.get(key)) is int and value[key] > 0:
            result[key] = value[key]
    for key in ("node_count", "document_count", "match_count", "edge_count", "alias_count", "cycle_count"):
        if type(value.get(key)) is int and 0 <= value[key] <= 512:
            result[key] = value[key]
    if type(value.get("duplicate_count")) is int and 0 <= value["duplicate_count"] <= 1024:
        result["duplicate_count"] = value["duplicate_count"]
    counts = value.get("control_type_counts")
    if isinstance(counts, dict):
        result["control_type_counts"] = {key: count for key, count in counts.items()
            if key in _CONTROL_TYPES and type(count) is int and 0 <= count <= 512}
    for key in ("scan_started", "scan_complete", "graph_scan_complete", "provider_tree_valid"):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    if include_option and isinstance(value.get("option_scan"), dict):
        result["option_scan"] = _safe_diagnostics(value["option_scan"], include_option=False, include_readiness=False)
    for key in ("elapsed_ms", "initial_scan_ms", "budget_elapsed_ms"):
        elapsed = value.get(key)
        if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
            result[key] = elapsed
    ready = value.get("readiness")
    if include_readiness and isinstance(ready, dict):
        clean = _safe_diagnostics(ready, include_option=False, include_readiness=False)
        if ready.get("termination") in {"sampling", "ready", "target_missing", "ambiguous",
                "budget_exhausted", "identity_changed", "provider_failure"}:
            clean["termination"] = ready["termination"]
        if type(ready.get("samples")) is list:
            clean["samples"] = [_safe_diagnostics(sample, include_option=False, include_readiness=False)
                                for sample in ready["samples"][:16] if isinstance(sample, dict)]
        result["readiness"] = clean
    return result


class FormControlReadError(ValueError):
    """只暴露稳定原因码，避免供应方异常泄漏本地内容。"""

    def __init__(self, reason_code, *, diagnostics=None):
        if (not isinstance(reason_code, str) or len(reason_code) > 96
                or not reason_code.replace("_", "").isalnum()):
            reason_code = "form_control_unavailable"
        self.reason_code = reason_code
        self.diagnostics = _safe_diagnostics(diagnostics)
        super().__init__(reason_code)

    def to_reference(self):
        result = {"reason_code": self.reason_code}
        if self.diagnostics:
            result["diagnostics"] = _safe_diagnostics(self.diagnostics)
        return result


def read_form_control(coordinator, target, label, kind, *, expected_runtime_id=None):
    """普通调用者入口；COM 创建、读取及身份复验均在同一所有者线程。"""
    diagnostics = None
    try:
        if (not isinstance(target, dict)
                or any(type(target.get(key)) is not int or target[key] <= 0
                       for key in ("handle", "process_id"))
                or not isinstance(label, str) or not _name(label) or len(label) > 1024
                or kind not in ("dropdown", "checkbox", "radio")):
            raise FormControlReadError("form_control_request_invalid")
        expected = None if expected_runtime_id is None else _runtime_id(expected_runtime_id)
        handle, pid, normalized = target["handle"], target["process_id"], _name(label)
        diagnostics = {"scope": "window_finite_children", "window_handle": handle, "process_id": pid,
            "node_count": 0, "control_type_counts": {}, "document_count": 0, "match_count": 0,
            "scan_started": False, "scan_complete": False}
        return coordinator._owner.call(
            lambda: _read_on_owner(coordinator, handle, pid, normalized, kind, expected, diagnostics))
    except FormControlReadError as error:
        if diagnostics is not None:
            reason = error.reason_code
            if "readiness" in diagnostics:
                terminal = ("identity_changed" if any(token in reason for token in ("identity", "window", "runtime_id"))
                    else "ambiguous" if reason == "form_control_ambiguous"
                    else "target_missing" if reason == "form_control_not_found"
                    else "budget_exhausted" if reason == "form_control_not_ready" else "provider_failure")
                _finish_readiness(diagnostics, terminal)
            error.diagnostics = _safe_diagnostics(diagnostics)
        raise
    except Exception:
        if diagnostics is not None:
            _finish_readiness(diagnostics, "provider_failure")
        raise FormControlReadError("form_control_provider_unavailable", diagnostics=diagnostics) from None


def _uia_factory():
    from pywinauto import Desktop
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo
    from pywinauto.controls.uiawrapper import UIAWrapper

    return Desktop(backend="uia"), IUIA().iuia.ControlViewWalker, lambda raw: UIAWrapper(UIAElementInfo(raw))


def _name(value):
    return " ".join(unicodedata.normalize("NFC", value).split())


def _runtime_id(value):
    if (type(value) not in (list, tuple) or not 1 <= len(value) <= 64
            or any(type(item) is not int for item in value)):
        raise FormControlReadError("form_control_runtime_id_unavailable")
    return tuple(value)


def _window_snapshot(windows, native, handle, pid):
    bound = windows.get_bound_window()
    if (bound is None or getattr(bound, "handle", None) != handle
            or getattr(bound, "process_id", None) != pid):
        raise FormControlReadError("form_control_window_mismatch")
    rect = _bound_rect(getattr(bound, "rect", None))
    identity = validate_native_identity_fact(native.read_identity(handle),
        target_window_handle=handle, expected_process_id=pid)
    if not _rect_valid(rect) or identity is None:
        raise FormControlReadError("form_control_window_unavailable")
    return identity, rect


def _finite_children(root):
    # 复用主识别的有限数组入口，不通过兄弟游标补采或回退。
    from app.operation.screen_reading.uia_provider import _finite_uia_children
    return _finite_uia_children(root)


def _same_element(left, right):
    from pywinauto.uia_defines import IUIA
    return IUIA().iuia.CompareElements(left.element_info.element, right.element_info.element)


def _tree_identity(node):
    info = node.element_info
    element = info.element
    pid = info.process_id
    if type(pid) is not int or pid <= 0 or element.CurrentProcessId != pid:
        raise FormControlReadError("form_control_tree_identity_unavailable")
    return (_runtime_id(info.runtime_id), pid, info.control_type,
            getattr(element, "CurrentFrameworkId", None),
            getattr(element, "CurrentNativeWindowHandle", None), _top_window_handle(node))


def _tree_parent(node, walker, wrap):
    parent = walker.GetParentElement(node.element_info.element)
    return _runtime_id(wrap(parent).element_info.runtime_id) if parent else None


def _descendants(root, walker, wrap, *, limit, diagnostics=None):
    # FindAll 的子数组按索引推进；Chromium 归一化子树的父边用 ControlView 校验。
    diagnostic = {} if diagnostics is None else diagnostics
    diagnostic.update(graph_scan_complete=False, provider_tree_valid=True, edge_count=0,
                      alias_count=0, cycle_count=0)
    try:
        graph = CanonicalUIAGraph(root, identity=_tree_identity,
            parent=lambda node: _tree_parent(node, walker, wrap), compare=_same_element)
    except UIAGraphError as error:
        raise FormControlReadError("form_control_" + error.reason) from None
    root_id = graph.root_id
    frames = [(iter(_finite_children(root)), 1, root_id)]
    while frames:
        children, depth, expected_parent = frames[-1]
        try:
            node = next(children)
        except StopIteration:
            frames.pop()
            continue
        if diagnostic["edge_count"] >= limit:
            raise FormControlReadError("form_control_scan_limit")
        diagnostic["edge_count"] += 1
        try:
            alias = graph.visit(node, expected_parent=expected_parent, path={frame[2] for frame in frames})
        except UIAGraphError as error:
            raise FormControlReadError("form_control_" + error.reason) from None
        finally:
            diagnostic.update(provider_tree_valid=graph.provider_tree_valid,
                alias_count=graph.alias_count, cycle_count=graph.cycle_count)
        if alias:
            # 已证明为同一节点；其邻接数组只读一次，当前有限数组余项仍须全部访问。
            continue
        if depth > 64:
            raise FormControlReadError("form_control_scan_limit")
        runtime_id = _runtime_id(node.element_info.runtime_id)
        yield node
        frames.append((iter(_finite_children(node)), depth + 1, runtime_id))
    diagnostic["graph_scan_complete"] = True


def _describe(node, handle, pid, window):
    info = node.element_info
    element = info.element
    if (_top_window_handle(node) != handle or info.process_id != pid
            or getattr(element, "CurrentProcessId", None) != pid):
        raise FormControlReadError("form_control_window_mismatch")
    if not _explicit_true_call(node, "is_visible") or not _explicit_true_call(node, "is_enabled"):
        raise FormControlReadError("form_control_unavailable")
    password = getattr(element, "CurrentIsPassword", None)
    if type(password) not in (bool, int) or password != 0:
        raise FormControlReadError("form_control_password_protected")
    bbox = _relative_rect(info.rectangle, window)
    if bbox is None:
        raise FormControlReadError("form_control_geometry_unavailable")
    if not isinstance(info.name, str):
        raise FormControlReadError("form_control_label_unavailable")
    return {"runtime_id": list(_runtime_id(info.runtime_id)),
            "bbox": dict(zip(("x", "y", "w", "h"), bbox)),
            "label": _name(info.name), "control_type": info.control_type}


def _pattern_property(node, pattern, property_name):
    try:
        return getattr(getattr(node, pattern), property_name)
    except Exception:
        # 不支持或失效的只读模式表示未知，不据此推断空值或未选中。
        return None


def _checked(node, kind):
    value = (_pattern_property(node, "iface_toggle", "CurrentToggleState") if kind == "checkbox"
             else _pattern_property(node, "iface_selection_item", "CurrentIsSelected"))
    return bool(value) if type(value) in (bool, int) and value in (0, 1) else None


def _expanded(node):
    # 直接读取原始模式；包装器的缺模式回退会猜测 collapsed，不能作为切换依据。
    value = _pattern_property(node, "iface_expand_collapse", "CurrentExpandCollapseState")
    return bool(value) if type(value) is int and value in (0, 1) else None


def _native_owned_popups(handle, pid):
    """一次枚举当前 owned 顶层窗；只读身份和几何，不读取标题或按点击命中授权。"""
    try:
        import win32gui
        import win32process
        results = []

        def snapshot(hwnd):
            return {"handle": hwnd, "process_id": win32process.GetWindowThreadProcessId(hwnd)[1],
                "owner_handle": int(win32gui.GetWindow(hwnd, 4) or 0),
                "root_owner_handle": int(win32gui.GetAncestor(hwnd, 3) or 0),
                "class_name": win32gui.GetClassName(hwnd), "rect": list(win32gui.GetWindowRect(hwnd))}

        def collect(hwnd, _):
            if (hwnd == handle or not win32gui.IsWindowVisible(hwnd)
                    or win32gui.GetAncestor(hwnd, 3) != handle
                    or win32process.GetWindowThreadProcessId(hwnd)[1] != pid):
                return
            if len(results) >= 64:
                raise FormControlReadError("form_control_popup_scan_limit")
            before = snapshot(hwnd)
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd) or before != snapshot(hwnd):
                raise FormControlReadError("form_control_popup_changed")
            results.append(before)

        win32gui.EnumWindows(collect, None)
        return results
    except FormControlReadError:
        raise
    except Exception:
        raise FormControlReadError("form_control_popup_unavailable") from None


def _associate_option_popups(options, *, handle, pid, window, identity):
    popups = _native_owned_popups(handle, pid)
    for popup in popups:
        rect = popup.get("rect")
        if (any(type(popup.get(key)) is not int or popup[key] <= 0
                for key in ("handle", "process_id", "owner_handle", "root_owner_handle"))
                or popup["handle"] == handle or popup["process_id"] != pid or popup["root_owner_handle"] != handle
                or not isinstance(popup.get("class_name"), str) or not popup["class_name"]
                or type(rect) is not list or len(rect) != 4 or any(type(value) is not int for value in rect)
                or rect[2] <= rect[0] or rect[3] <= rect[1]):
            raise FormControlReadError("form_control_popup_unavailable")
    associated = []
    for option in options:
        box = option["bbox"]
        left, top = window[0] + box["x"], window[1] + box["y"]
        matches = [popup for popup in popups if popup["rect"][0] <= left
            and popup["rect"][1] <= top and left + box["w"] <= popup["rect"][2]
            and top + box["h"] <= popup["rect"][3]]
        if len(matches) > 1:
            raise FormControlReadError("form_control_popup_ambiguous")
        item = dict(option)
        if matches:
            created = identity.get("process_create_time")
            if type(created) not in (int, float) or not math.isfinite(created) or created <= 0:
                raise FormControlReadError("form_control_popup_unavailable")
            # 这是当前原生 owner 与选项几何的关联，不声称 popup 有该选项的 UIA 子树。
            item["native_popup"] = {**matches[0], "contract_version": "form_option_native_popup_v1",
                "association": "native_owner_and_geometry", "bound_process_create_time": created,
                "coordinate_space": "screen_pixels", "rect_format": "ltrb"}
        associated.append(item)
    return associated


def _dropdown(node, walker, wrap, handle, pid, window, diagnostics=None):
    options = []
    option_diagnostics = {}
    if diagnostics is not None:
        diagnostics["option_scan"] = option_diagnostics
    for item in _descendants(node, walker, wrap, limit=128, diagnostics=option_diagnostics):
        if item.element_info.control_type != "ListItem":
            continue
        if not _explicit_true_call(item, "is_visible") or not _explicit_true_call(item, "is_enabled"):
            continue
        before = _describe(item, handle, pid, window)
        selected = _checked(item, "radio")
        if before != _describe(item, handle, pid, window):
            raise FormControlReadError("form_control_identity_changed")
        options.append({key: before[key] for key in ("label", "bbox", "runtime_id")}
                       | {"selected": selected})
    value = _pattern_property(node, "iface_value", "CurrentValue")
    if not isinstance(value, str):
        value = None
        try:
            selection = node.iface_selection.GetCurrentSelection()
            if selection.Length == 1:
                selected = wrap(selection.GetElement(0))
                # 只使用已在本组合框子树验证过的项，绝不读取外部选择项内容。
                rid = list(_runtime_id(selected.element_info.runtime_id))
                owned = [option for option in options if option["runtime_id"] == rid]
                if len(owned) == 1:
                    value = owned[0]["label"]
        except Exception:
            value = None
    return value, options


def _scan_controls(root, walker, wrap, label, control_type, diagnostics):
    matches = []
    diagnostics.update(scan_started=True, scan_complete=False, node_count=0,
                       document_count=0, match_count=0, control_type_counts={})
    for node in _descendants(root, walker, wrap, limit=512, diagnostics=diagnostics):
        info = node.element_info
        actual_type = info.control_type
        diagnostic_type = actual_type if actual_type in _CONTROL_TYPES else "Other"
        diagnostics["node_count"] += 1
        counts = diagnostics["control_type_counts"]
        counts[diagnostic_type] = counts.get(diagnostic_type, 0) + 1
        diagnostics["document_count"] += int(diagnostic_type == "Document")
        if actual_type == control_type and isinstance(info.name, str) and _name(info.name) == label:
            matches.append(node)
            diagnostics["match_count"] += 1
    diagnostics["scan_complete"] = True
    return matches


def _finish_readiness(diagnostics, termination):
    if "readiness" in diagnostics:
        now = _readiness_clock()
        diagnostics["readiness"].update(termination=termination,
            elapsed_ms=round(max(0, now - diagnostics["_readiness_started"]) * 1000, 3),
            budget_elapsed_ms=round(max(0, now - diagnostics["_readiness_budget_started"]) * 1000, 3))


def _record_readiness_sample(diagnostics, started):
    sample = _safe_diagnostics(diagnostics, include_option=False, include_readiness=False)
    sample["elapsed_ms"] = round(max(0, _readiness_clock() - started) * 1000, 3)
    diagnostics["readiness"]["samples"].append(sample)


def _find_control(windows, native, handle, pid, label, kind, identity, window, diagnostics, *, allow_readiness):
    started = _readiness_clock()
    budget_started = None
    root_signature = None
    chromium = False
    control_type = {"dropdown": "ComboBox", "checkbox": "CheckBox", "radio": "RadioButton"}[kind]
    for attempt in range(16):
        if attempt:
            if _readiness_clock() - budget_started >= 1.5:
                raise FormControlReadError("form_control_not_ready")
            if (identity, window) != _window_snapshot(windows, native, handle, pid):
                raise FormControlReadError("form_control_window_changed")
        desktop, walker, wrap = _uia_factory()
        root = desktop.window(handle=handle).wrapper_object()
        if _top_window_handle(root) != handle or root.element_info.process_id != pid:
            raise FormControlReadError("form_control_window_mismatch")
        element = root.element_info.element
        signature = (_tree_identity(root), getattr(element, "CurrentClassName", None))
        if root_signature is None:
            root_signature = signature
            chromium = (allow_readiness and PureWindowsPath(identity["executable_path"]).name in {"msedge.exe", "chrome.exe", "chromium.exe"}
                and signature[1] == "Chrome_WidgetWin_1"
                and getattr(element, "CurrentFrameworkId", None) in {"Chrome", "Win32"})
        elif signature != root_signature:
            raise FormControlReadError("form_control_identity_changed")
        try:
            matches = _scan_controls(root, walker, wrap, label, control_type, diagnostics)
        except Exception:
            if "readiness" in diagnostics:
                _record_readiness_sample(diagnostics, started)
            raise
        initial_empty_chromium = (chromium and not matches and diagnostics["document_count"] == 0)
        if initial_empty_chromium or "readiness" in diagnostics:
            if "readiness" not in diagnostics:
                # 首次完整空内容观察后才启动就绪预算；初始化与首扫描仍计入总耗时。
                budget_started = _readiness_clock()
                diagnostics["_readiness_started"] = started
                diagnostics["_readiness_budget_started"] = budget_started
                diagnostics["readiness"] = {"samples": [], "termination": "sampling",
                    "initial_scan_ms": round(max(0, budget_started - started) * 1000, 3)}
            _record_readiness_sample(diagnostics, started)
        if len(matches) == 1:
            _finish_readiness(diagnostics, "ready")
            return matches[0], walker, wrap
        if (identity, window) != _window_snapshot(windows, native, handle, pid):
            raise FormControlReadError("form_control_window_changed")
        if matches:
            raise FormControlReadError("form_control_ambiguous")
        if not initial_empty_chromium:
            raise FormControlReadError("form_control_not_found")
        remaining = 1.5 - (_readiness_clock() - budget_started)
        if remaining <= 0 or attempt == 15:
            raise FormControlReadError("form_control_not_ready")
        # 仅限制后续采样的启动，不抢占已进行的同步 COM；总次数含首次观察最多 16 次。
        _readiness_wait(min(.1, remaining))
    raise FormControlReadError("form_control_not_ready")


def _read_on_owner(coordinator, handle, pid, label, kind, expected, diagnostics):
    windows = coordinator._windows()
    native = WindowsNativeIdentityReader(window_manager=windows)
    identity, window = _window_snapshot(windows, native, handle, pid)
    node, walker, wrap = _find_control(windows, native, handle, pid, label, kind, identity, window, diagnostics,
                                     allow_readiness=expected is None)
    before = _describe(node, handle, pid, window)
    if expected is not None and tuple(before["runtime_id"]) != expected:
        raise FormControlReadError("form_control_identity_changed")
    value, checked, options = None, None, []
    if kind == "dropdown":
        expanded = _expanded(node)
        value, options = _dropdown(node, walker, wrap, handle, pid, window, diagnostics)
        if expanded is True and options:
            options = _associate_option_popups(options, handle=handle, pid=pid, window=window, identity=identity)
    else:
        checked = _checked(node, kind)
    if before != _describe(node, handle, pid, window):
        raise FormControlReadError("form_control_identity_changed")
    if (identity, window) != _window_snapshot(windows, native, handle, pid):
        raise FormControlReadError("form_control_window_changed")
    if kind == "dropdown" and _expanded(node) is not expanded:
        raise FormControlReadError("form_control_expansion_changed")
    result = {"source": "windows_uia", "runtime_id": before["runtime_id"], "bbox": before["bbox"],
            "window_identity": identity, "window_rect": list(window), "kind": kind,
            "label": before["label"], "value": value, "checked": checked, "options": options,
            "state_available": value is not None if kind == "dropdown" else checked is not None}
    if kind == "dropdown":
        result["expanded"] = expanded
    if "readiness" in diagnostics or diagnostics.get("alias_count") or diagnostics.get("option_scan", {}).get("alias_count"):
        result["diagnostics"] = _safe_diagnostics(diagnostics)
    return result


__all__ = ["FormControlReadError", "read_form_control"]
