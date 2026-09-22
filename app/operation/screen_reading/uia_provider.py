from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Iterator, Mapping

from app.core.window_manager import BoundWindow, window_manager
from app.operation.screen_reading.uia_graph import CanonicalUIAGraph, UIAGraphError

UIA_PROVIDER_ID = "windows_uia"
UIA_PROVIDER_VERSION = "windows_uia_provider_v1"
DEFAULT_UIA_MAX_CONTROLS = 1000
HARD_UIA_MAX_CONTROLS = 4000


class _FiniteUIAChildren:
    def __init__(self, array, wrap):
        self.array, self.wrap = array, wrap
        self.length = int(array.Length)
        if self.length < 0:
            raise ValueError("Negative UIA children array length")

    def __len__(self):
        return self.length

    def __getitem__(self, index):
        if not 0 <= index < self.length:
            raise IndexError(index)
        return self.wrap(self.array.GetElement(index))


def _finite_uia_children(wrapper):
    """直接读取有限子元素数组；不使用会吞 COM 异常的 children 包装或兄弟游标。"""
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo

    api = IUIA()
    array = wrapper.element_info.element.FindAll(api.tree_scope["children"], api.true_condition)
    return _FiniteUIAChildren(array, lambda element: wrapper.backend.generic_wrapper_class(UIAElementInfo(element)))


def _bounded_uia_walk(root, *, budget, prune_documents=False):
    """按读取次数限额遍历；仅归一化已证实别名，真实冲突和异常仍不完整。"""
    budget = max(1, int(budget))
    wrappers, errors, frames, seen = [], [], [], set()
    current, path, expected_parent = root, frozenset(), None
    try:
        graph = CanonicalUIAGraph(root)
    except Exception:
        graph = None
        errors.append({"reason": "runtime_identity_unavailable" if _runtime_id_key(root) is None
                       else "tree_identity_unavailable", "index": 0})
    visited = 0
    excluded = 0
    while current is not None:
        visited += 1
        key = _runtime_id_key(current)
        duplicate = key is not None and key in seen
        alias = False
        if graph is not None and visited > 1:
            try:
                alias = graph.visit(current, expected_parent=expected_parent,
                    path={tuple(value for _, value in item) for item in path})
            except Exception as exc:
                errors.append({"reason": exc.reason if isinstance(exc, UIAGraphError)
                               else "tree_identity_unavailable", "index": visited - 1})
        if not alias:
            wrappers.append(current)
        if key is None:
            errors.append({"reason": "runtime_identity_unavailable", "index": len(wrappers) - 1})
        elif duplicate and not alias:
            errors.append({"reason": "ancestor_cycle" if key in path else "duplicate_runtime_id",
                           "index": len(wrappers) - 1, "runtime_id": list(_public_runtime_id(current.element_info) or [])})
        if key is not None:
            seen.add(key)
        document = prune_documents and str(getattr(current.element_info, "control_type", "")).casefold() == "document"
        excluded += int(document and not alias)
        if visited == budget:
            break
        if not duplicate and not document:
            try:
                children = _finite_uia_children(current)
                frames.append([children, 0, path | {key} if key is not None else path,
                               _public_runtime_id(current.element_info)])
            except Exception as exc:
                errors.append({"reason": "children_enumeration_failed", "index": len(wrappers) - 1,
                               "message": str(exc), "winerror": getattr(exc, "winerror", None)})
        current = None
        while frames:
            children, index, child_path, parent_id = frames[-1]
            try:
                if index >= len(children):
                    frames.pop()
                    continue
                frames[-1][1] += 1
                current, path, expected_parent = children[index], child_path, parent_id
                break
            except Exception as exc:
                frames.pop()
                errors.append({"reason": "children_enumeration_failed", "child_index": index,
                               "message": str(exc), "winerror": getattr(exc, "winerror", None)})
    truncated = visited == budget
    return {"wrappers": wrappers, "scan_visited_count": visited,
            "scan_complete": not truncated and not errors, "truncated": truncated,
            "graph_scan_complete": not truncated and not errors,
            "provider_tree_valid": bool(graph and graph.provider_tree_valid and not errors),
            "alias_count": graph.alias_count if graph else 0,
            "cycle_count": graph.cycle_count if graph else 0,
            "truncation_reason": "control_budget_reached" if truncated else None,
            "traversal_errors": errors, "excluded_document_count": excluded}


def _walk_metadata(walk):
    return {key: value for key, value in walk.items() if key not in {"wrappers", "excluded_document_count"}}

_PINNED_UIA_SNAPSHOT: ContextVar[dict[str, Any] | None] = ContextVar(
    "pinned_uia_snapshot",
    default=None,
)


def browser_document_observation(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """只描述同帧正文树的可见证据，不把遍历结束或空树当作页面就绪。"""
    controls = [item for item in snapshot.get("controls", []) if isinstance(item, dict)]
    documents = {item.get("control_id") for item in controls
                 if item.get("control_type") == "Document" and item.get("control_id")}
    descendants = [item for item in controls
                   if item.get("control_type") != "Document"
                   and documents.intersection(item.get("ancestor_control_ids") or [])]
    process = str((snapshot.get("window") or {}).get("process_name")).casefold()
    if process not in {"msedge.exe", "chrome.exe", "chromium.exe"}:
        status = "not_applicable"
    elif snapshot.get("scan_scope", "bound_window") != "bound_window":
        status = "out_of_scope"
    elif snapshot.get("status") != "ok":
        status = "unavailable"
    elif descendants:
        status = "content_observed"
    elif snapshot.get("scan_complete") is not True or snapshot.get("truncated") is not False:
        status = "unknown_incomplete_scan"
    else:
        status = "document_without_observed_content" if documents else "no_document_observed"
    applicable = status not in {"not_applicable", "out_of_scope", "unavailable"}
    return {
        "contract_version": "browser_document_observation_v1", "status": status,
        "document_count": len(documents) if applicable else 0,
        "content_control_count": len(descendants) if applicable else 0,
        "scan_complete": snapshot.get("scan_complete"),
        "page_ready_verified": None, "automatic_retry_allowed": False,
        "next_action": "inspect_current_image_or_request_fresh_observation"
            if status in {"document_without_observed_content", "no_document_observed",
                          "unknown_incomplete_scan", "unavailable"} else None,
    }


@contextmanager
def pinned_uia_snapshot(snapshot: Mapping[str, Any]) -> Iterator[None]:
    token = _PINNED_UIA_SNAPSHOT.set(deepcopy(dict(snapshot)))
    try:
        yield
    finally:
        _PINNED_UIA_SNAPSHOT.reset(token)


@dataclass(frozen=True)
class UIABBox:
    x: int
    y: int
    w: int
    h: int

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class UIAControl:
    control_id: str
    name: str | None
    control_type: str | None
    automation_id: str | None
    class_name: str | None
    bbox: UIABBox
    screen_bbox: UIABBox
    enabled: bool | None
    visible: bool | None
    patterns: tuple[str, ...]
    runtime_id: tuple[int, ...] | None = None
    ancestor_control_ids: tuple[str, ...] = ()
    scroll_axes: dict[str, bool | None] | None = None
    native_client_geometry: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": UIA_PROVIDER_ID,
            "control_id": self.control_id,
            "name": self.name,
            "control_type": self.control_type,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "bbox": self.bbox.to_dict(),
            "screen_bbox": self.screen_bbox.to_dict(),
            "enabled": self.enabled,
            "visible": self.visible,
            "patterns": list(self.patterns),
            "runtime_id": list(self.runtime_id) if self.runtime_id is not None else None,
            "ancestor_control_ids": list(self.ancestor_control_ids),
            **({"scroll_axes": dict(self.scroll_axes)} if self.scroll_axes is not None else {}),
            **({"native_client_geometry": deepcopy(self.native_client_geometry)}
               if self.native_client_geometry is not None else {}),
        }


class WindowsUIAProvider:
    provider_id = UIA_PROVIDER_ID
    version = UIA_PROVIDER_VERSION

    def describe_slot(self, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        status = str((snapshot or {}).get("status") or "not_scanned")
        return {
            "status": "connected",
            "provider": self.provider_id,
            "provider_version": self.version,
            "last_scan_status": status,
            "intended_use": "Windows desktop controls and browser chrome such as Back, Forward, Refresh, address bar, tabs, and window buttons.",
            "expected_fields": ["control_type", "name", "automation_id", "bounding_rectangle", "enabled", "patterns", "runtime_id"],
            "merge_keys": ["bbox_overlap", "role_guess", "label_or_name", "window_process"],
        }

    def snapshot_bound_window(self, *, max_controls: int = DEFAULT_UIA_MAX_CONTROLS) -> dict[str, Any]:
        pinned = _PINNED_UIA_SNAPSHOT.get()
        if pinned is not None:
            return deepcopy(pinned)
        bound = window_manager.get_bound_window()
        if bound is None:
            return self._unavailable("no_bound_window", "Bind a target window before collecting UIA controls.")
        return self.snapshot_window(bound, max_controls=max_controls)

    def snapshot_window(self, bound: BoundWindow, *, max_controls: int = DEFAULT_UIA_MAX_CONTROLS) -> dict[str, Any]:
        try:
            control_budget = max(1, min(int(max_controls), HARD_UIA_MAX_CONTROLS))
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
            root = desktop.window(handle=bound.handle).wrapper_object()
            walk = _bounded_uia_walk(root, budget=control_budget)
            wrappers = walk["wrappers"]
            observed: list[tuple[Any, UIAControl]] = []
            zero_area_structural_ids: set[int] = set()
            for index, wrapper in enumerate(wrappers):
                control = self._control_from_wrapper(wrapper, bound=bound, index=index,
                    zero_area_structural_ids=zero_area_structural_ids)
                if control is not None:
                    observed.append((wrapper, control))
            ancestors = _confirmed_ancestor_control_ids(observed, traversed_wrappers=wrappers,
                zero_area_structural_ids=zero_area_structural_ids)
            controls = [
                replace(control, ancestor_control_ids=ancestors.get(id(wrapper), ())).to_dict()
                for wrapper, control in observed
            ]
            snapshot = {
                "provider": self.provider_id,
                "provider_version": self.version,
                "status": "ok",
                "scan_budget": control_budget,
                **_walk_metadata(walk),
                "window": {
                    "handle": bound.handle,
                    "title": bound.title,
                    "process_id": bound.process_id,
                    "process_name": bound.process_name,
                    "bbox": {
                        "x": 0,
                        "y": 0,
                        "w": max(1, bound.rect.right - bound.rect.left),
                        "h": max(1, bound.rect.bottom - bound.rect.top),
                    },
                },
                "control_count": len(controls),
                "controls": controls,
            }
            try:
                popup_handles = self._owned_popup_handles(bound)
                snapshot["owned_popup_probe"] = {"status": "ok", "count": len(popup_handles)}
            except ImportError as exc:
                # UIA 快照与可选 Win32 浮窗补采分开报告，不能抹掉已取得的主树证据。
                popup_handles = []
                snapshot["owned_popup_probe"] = {"status": "unavailable", "reason": "win32_backend_unavailable", "message": str(exc)}
            scopes = self._popup_menu_scopes(popup_handles, desktop=desktop, bound=bound, window=snapshot["window"])
            main_scopes = self._complete_menu_scopes(observed, controls=controls, bound=bound, window=snapshot["window"])
            for scope in main_scopes:
                identity = (scope.get("controls") or [{}])[0].get("runtime_id")
                if not identity or not any(identity == (item.get("controls") or [{}])[0].get("runtime_id") for item in scopes):
                    scopes.append(scope)
            snapshot["menu_scopes"] = scopes
            if str(bound.process_name).casefold() in {"msedge.exe", "chrome.exe", "chromium.exe"}:
                snapshot["browser_chrome_scope"] = self._browser_chrome_scope(root, bound=bound, window=snapshot["window"])
                snapshot["browser_document_observation"] = browser_document_observation(snapshot)
            return snapshot
        except Exception as exc:
            return self._unavailable("uia_scan_failed", str(exc))

    def _browser_chrome_scope(self, root, *, bound, window):
        """独立有界遍历浏览器外壳；不下钻网页 Document，也不声称整页完整。"""
        budget = DEFAULT_UIA_MAX_CONTROLS
        try:
            walk = _bounded_uia_walk(root, budget=budget, prune_documents=True)
            wrappers = walk["wrappers"]
            observed = []
            zero_area_ids = set()
            documents = 0
            for index, wrapper in enumerate(wrappers):
                if str(wrapper.element_info.control_type).casefold() == "document":
                    documents += 1
                    continue
                control = self._control_from_wrapper(wrapper, bound=bound, index=index,
                    zero_area_structural_ids=zero_area_ids)
                if control is not None:
                    observed.append((wrapper, control))
            ancestors = _confirmed_ancestor_control_ids(observed, traversed_wrappers=wrappers,
                zero_area_structural_ids=zero_area_ids)
            controls = [replace(control, ancestor_control_ids=ancestors.get(id(wrapper), ())).to_dict()
                        for wrapper, control in observed]
            return {"provider": self.provider_id, "provider_version": self.version,
                    "status": "ok", "scan_scope": "browser_chrome", "scan_budget": budget,
                    **_walk_metadata(walk), "excluded_document_count": documents,
                    "window": deepcopy(window), "controls": controls, "control_count": len(controls)}
        except Exception as exc:
            return {"status": "unavailable", "scan_scope": "browser_chrome", "scan_complete": False,
                    "reason": "browser_chrome_scan_failed", "message": str(exc)}

    def _complete_menu_scopes(self, observed, *, controls, bound, window, root_is_owned_popup=False):
        """只补采当前树已证实归属的唯一可见菜单，不扩大全窗口扫描预算。"""
        by_id = {control["control_id"]: control for control in controls}
        root_id = observed[0][1].control_id if observed else None
        menus = [(wrapper, control) for wrapper, control in observed
                 if control.control_type == "Menu" and control.visible is True and control.enabled is True
                 and (root_id in by_id[control.control_id].get("ancestor_control_ids", [])
                      or root_is_owned_popup and control.control_id == root_id)]
        if len(menus) > 1:
            return [{"status": "unavailable", "reason": "multiple_visible_menus", "scan_complete": False}]
        if not menus:
            return []
        wrapper, original = menus[0]
        budget = 128
        try:
            walk = _bounded_uia_walk(wrapper, budget=budget)
            wrappers = walk["wrappers"]
            zero_ids = set()
            items = []
            for index, current in enumerate(wrappers):
                control = self._control_from_wrapper(current, bound=bound, index=index,
                    zero_area_structural_ids=zero_ids)
                if control is not None:
                    items.append((current, control))
            if (not items or items[0][1].runtime_id != original.runtime_id
                    or not original.runtime_id or items[0][1].bbox != original.bbox):
                return []
            ancestors = _confirmed_ancestor_control_ids(items, traversed_wrappers=wrappers,
                zero_area_structural_ids=zero_ids)
            scoped = [replace(control, ancestor_control_ids=ancestors.get(id(current), ())).to_dict()
                      for current, control in items]
            return [{"provider": self.provider_id, "provider_version": self.version, "status": "ok",
                     "scan_scope": "menu_subtree",
                     "source_menu_control_id": original.control_id,
                     "scan_budget": budget, **_walk_metadata(walk),
                     "window": dict(window), "control_count": len(scoped), "controls": scoped}]
        except Exception as exc:
            return [{"status": "unavailable", "scan_scope": "menu_subtree",
                     "reason": "menu_subtree_scan_failed", "message": str(exc), "scan_complete": False}]

    @staticmethod
    def _owned_popup_handles(bound):
        """按窗口归属找原生浮窗，避免菜单在长网页末尾而永远无法被预算内扫描发现。"""
        import win32gui
        import win32process
        if not win32gui.IsWindow(bound.handle):
            return []
        handles = []
        def collect(handle, _):
            if (handle != bound.handle and win32gui.IsWindowVisible(handle)
                    and window_manager._is_owned_popup(handle, bound.handle)
                    and win32process.GetWindowThreadProcessId(handle)[1] == bound.process_id):
                handles.append(handle)
        win32gui.EnumWindows(collect, None)
        return handles

    def _popup_menu_scopes(self, handles, *, desktop, bound, window):
        scopes = []
        if len(handles) > 4:
            return [{"status": "unavailable", "reason": "owned_popup_count_exceeds_budget", "scan_complete": False}]
        for handle in handles:
            try:
                root = desktop.window(handle=handle).wrapper_object()
                walk = _bounded_uia_walk(root, budget=128)
                wrappers = walk["wrappers"]
                if not walk["scan_complete"]:
                    scopes.append({"status": "unavailable", "reason": "owned_popup_scan_incomplete", **_walk_metadata(walk)})
                    continue
                zero_ids, observed = set(), []
                for index, wrapper in enumerate(wrappers):
                    control = self._control_from_wrapper(wrapper, bound=bound, index=index,
                        zero_area_structural_ids=zero_ids)
                    if control is not None:
                        observed.append((wrapper, control))
                ancestors = _confirmed_ancestor_control_ids(observed, traversed_wrappers=wrappers,
                    zero_area_structural_ids=zero_ids)
                controls = [replace(control, ancestor_control_ids=ancestors.get(id(wrapper), ())).to_dict()
                            for wrapper, control in observed]
                found = self._complete_menu_scopes(observed, controls=controls, bound=bound, window=window,
                    root_is_owned_popup=True)
                for scope in found:
                    scope["owned_popup_handle"] = handle
                scopes.extend(found)
            except Exception as exc:
                scopes.append({"status": "unavailable", "reason": "owned_popup_scan_failed",
                               "message": str(exc), "scan_complete": False})
        return scopes

    def _control_from_wrapper(self, wrapper: Any, *, bound: BoundWindow, index: int,
                              zero_area_structural_ids: set[int] | None = None) -> UIAControl | None:
        try:
            rect = wrapper.rectangle()
        except Exception:
            return None
        screen_bbox = UIABBox(
            x=int(rect.left),
            y=int(rect.top),
            w=max(0, int(rect.right) - int(rect.left)),
            h=max(0, int(rect.bottom) - int(rect.top)),
        )
        if screen_bbox.w <= 0 or screen_bbox.h <= 0:
            # 同一次成功读框确认的零面积结构节点仅保留拓扑，读取失败或负尺寸不能充当桥梁。
            info = getattr(wrapper, "element_info", None)
            kind = getattr(info, "control_type", None)
            if (zero_area_structural_ids is not None and isinstance(kind, str)
                    and kind.casefold() in {"group", "pane"}
                    and int(rect.right) >= int(rect.left) and int(rect.bottom) >= int(rect.top)):
                zero_area_structural_ids.add(id(wrapper))
            return None

        bbox = UIABBox(
            x=screen_bbox.x - int(bound.rect.left),
            y=screen_bbox.y - int(bound.rect.top),
            w=screen_bbox.w,
            h=screen_bbox.h,
        )
        info = getattr(wrapper, "element_info", None)
        control_type = _first_text(
            getattr(info, "control_type", None),
            _safe_call(getattr(wrapper, "friendly_class_name", None)),
        )
        # Edit 的 window_text 可能是当前值；有无障碍名称时不能用可变内容替代身份。
        name = _first_text(
            getattr(info, "name", None) if control_type == "Edit" else None,
            _safe_call(getattr(wrapper, "window_text", None)),
            getattr(info, "name", None),
            getattr(info, "rich_text", None),
        )
        automation_id = _first_text(getattr(info, "automation_id", None))
        class_name = _first_text(getattr(info, "class_name", None), _safe_call(getattr(wrapper, "class_name", None)))
        enabled = _safe_bool(getattr(wrapper, "is_enabled", None))
        visible = _safe_bool(getattr(wrapper, "is_visible", None))
        patterns = _patterns(wrapper)
        identity = automation_id or name or control_type or "control"

        return UIAControl(
            control_id=f"uia_{index}_{_slug(identity)}",
            name=name,
            control_type=control_type,
            automation_id=automation_id,
            class_name=class_name,
            bbox=bbox,
            screen_bbox=screen_bbox,
            enabled=enabled,
            visible=visible,
            patterns=patterns,
            runtime_id=_public_runtime_id(info),
            scroll_axes=_scroll_axes(wrapper) if "Scroll" in patterns else None,
            native_client_geometry=_native_edit_client_geometry(
                info, bound=bound, screen_bbox=screen_bbox, control_type=control_type,
            ) if str(control_type).casefold() in {"edit", "textbox"} else None,
        )

    def _unavailable(self, code: str, message: str) -> dict[str, Any]:
        return {
            "provider": self.provider_id,
            "provider_version": self.version,
            "status": "unavailable",
            "reason": code,
            "message": message,
            "control_count": 0,
            "controls": [],
        }



class _NativeEditGeometryBackend:
    @contextmanager
    def physical_pixels(self):
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        setter = user32.SetThreadDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = ctypes.c_void_p
        previous = setter(ctypes.c_void_p(-4))
        if not previous:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not setter(previous):
                raise ctypes.WinError(ctypes.get_last_error())

    def identity(self, handle):
        import win32gui
        import win32process
        from pywinauto.uia_element_info import UIAElementInfo

        return (win32gui.GetAncestor(handle, 2), win32process.GetWindowThreadProcessId(handle)[1],
                win32gui.GetClassName(handle), _public_runtime_id(UIAElementInfo(handle)))

    def client_rect(self, handle):
        import win32gui

        return win32gui.GetClientRect(handle)

    def to_screen(self, handle, point):
        import win32gui

        return win32gui.ClientToScreen(handle, point)


def _native_edit_geometry_backend():
    return _NativeEditGeometryBackend()


def _native_edit_client_geometry(info, *, bound, screen_bbox, control_type):
    """只为身份匹配的原生编辑 HWND 读取真实客户区，不从 UIA 大框猜测滚动条宽度。"""
    base = {"status": "unavailable", "source": "win32_edit_client_rect",
            "coordinate_space": "capture_image_pixels"}
    if str(control_type).casefold() not in {"edit", "textbox"}:
        return {**base, "status": "not_applicable", "reason": "not_edit_control"}
    try:
        # element_info.handle 是当前元素的 NativeWindowHandle，不使用 wrapper 的祖先回退。
        handle = getattr(info, "handle", None)
        if type(handle) is not int or handle <= 0:
            return {**base, "reason": "native_window_handle_unavailable"}
        base["native_window_handle"] = handle
        runtime_id = _public_runtime_id(info)
        if runtime_id is None:
            return {**base, "reason": "native_element_identity_unavailable"}
        backend = _native_edit_geometry_backend()
        with backend.physical_pixels():
            identity = backend.identity(handle)
            root, pid, native_class, native_runtime_id = identity
            if root != bound.handle:
                return {**base, "reason": "native_window_root_mismatch"}
            if bound.process_id is None or pid != bound.process_id:
                return {**base, "reason": "native_window_process_mismatch"}
            if native_runtime_id != runtime_id:
                return {**base, "reason": "native_element_identity_mismatch"}
            native_class = str(native_class).casefold()
            if native_class != "edit" and not native_class.startswith("richedit"):
                return {**base, "reason": "not_native_edit_class"}
            left, top, right, bottom = backend.client_rect(handle)
            x, y = backend.to_screen(handle, (left, top))
            x2, y2 = backend.to_screen(handle, (right, bottom))
            if x2 <= x or y2 <= y or right <= left or bottom <= top:
                return {**base, "reason": "invalid_client_geometry"}
            if (x < screen_bbox.x or y < screen_bbox.y
                    or x2 > screen_bbox.x + screen_bbox.w or y2 > screen_bbox.y + screen_bbox.h):
                return {**base, "reason": "client_geometry_outside_control"}
            if (x < bound.rect.left or y < bound.rect.top
                    or x2 > bound.rect.right or y2 > bound.rect.bottom):
                return {**base, "reason": "client_geometry_outside_capture"}
            if backend.identity(handle) != identity:
                return {**base, "reason": "native_element_identity_changed"}
        return {**base, "status": "ok", "reason": "current_native_edit_client_rect",
                "bbox": {"x": x - bound.rect.left, "y": y - bound.rect.top, "w": x2 - x, "h": y2 - y},
                "screen_bbox": {"x": x, "y": y, "w": x2 - x, "h": y2 - y}}
    except Exception as exc:
        # 可选 Win32 证据失败不抹掉 UIA 原始控件；保留原因给调用方判断。
        return {**base, "reason": "native_client_geometry_failed", "message": str(exc),
                "winerror": getattr(exc, "winerror", None)}


def _runtime_id_key(wrapper: Any) -> tuple[tuple[str, int | str], ...] | None:
    """只接受 UIA runtime_id 的简单稳定值，拒绝用几何或名称猜测父子关系。"""
    info = getattr(wrapper, "element_info", None)
    value = getattr(info, "runtime_id", None)
    if not isinstance(value, (tuple, list)) or not value:
        return None
    result: list[tuple[str, int | str]] = []
    for item in value:
        if type(item) not in {int, str}:
            return None
        result.append((type(item).__name__, item))
    return tuple(result)


def _public_runtime_id(info: Any) -> tuple[int, ...] | None:
    """只公开可与字段 reader 精确比较的 Windows UIA 整数身份。"""
    value = getattr(info, "runtime_id", None)
    if (not isinstance(value, (tuple, list)) or not 1 <= len(value) <= 64
            or any(type(item) is not int for item in value)):
        return None
    return tuple(value)


def _confirmed_ancestor_control_ids(
    observed: list[tuple[Any, UIAControl]],
    *, traversed_wrappers: list[Any] | None = None,
    zero_area_structural_ids: set[int] | None = None,
) -> dict[int, tuple[str, ...]]:
    """沿已遍历且身份唯一的真实父链，投影可输出祖先而不臆造零面积操作目标。"""
    by_runtime: dict[tuple[tuple[str, int | str], ...], tuple[Any, UIAControl | None]] = {}
    emitted = {id(wrapper): control for wrapper, control in observed}
    bridges = zero_area_structural_ids or set()
    duplicate_runtime: set[tuple[tuple[str, int | str], ...]] = set()
    for wrapper in traversed_wrappers if traversed_wrappers is not None else [item[0] for item in observed]:
        key = _runtime_id_key(wrapper)
        if key is None:
            continue
        if key in by_runtime:
            duplicate_runtime.add(key)
        else:
            by_runtime[key] = (wrapper, emitted.get(id(wrapper)))
    for key in duplicate_runtime:
        by_runtime.pop(key, None)

    # 共享祖先在同一次快照中只读一次 COM 父级；失败也保持本帧未知，不跨帧缓存。
    parent_keys = {}

    def parent_key_for(wrapper):
        token = id(wrapper)
        if token not in parent_keys:
            parent = _safe_call(getattr(wrapper, "parent", None))
            parent_keys[token] = _runtime_id_key(parent) if parent is not None else None
        return parent_keys[token]

    result: dict[int, tuple[str, ...]] = {}
    for wrapper, _control in observed:
        current = wrapper
        current_key = _runtime_id_key(current)
        if current_key is None or current_key not in by_runtime:
            result[id(wrapper)] = ()
            continue
        seen = {current_key}
        chain: list[str] = []
        valid = True
        while True:
            parent_key = parent_key_for(current)
            if parent_key is None or parent_key not in by_runtime:
                # 已确认的前缀仍可信；未采集的更高层不被臆造进快照。
                break
            if parent_key in seen:
                valid = False
                break
            seen.add(parent_key)
            resolved_parent, parent_control = by_runtime[parent_key]
            if parent_control is None:
                if id(resolved_parent) not in bridges:
                    break
            else:
                chain.append(parent_control.control_id)
            current = resolved_parent
        result[id(wrapper)] = tuple(chain) if valid else ()
    return result

def _patterns(wrapper: Any) -> tuple[str, ...]:
    # 包装类继承的 invoke/texts 等方法不代表该控件实现了 UIA pattern。
    candidates = {
        "Invoke": ["iface_invoke"],
        "Value": ["iface_value"],
        "Text": ["iface_text"],
        "Selection": ["iface_selection_item", "iface_selection"],
        "ExpandCollapse": ["iface_expand_collapse"],
        "Toggle": ["iface_toggle"],
        "Scroll": ["iface_scroll"],
    }
    found: list[str] = []
    for pattern, attrs in candidates.items():
        if any(_has_safe_attr(wrapper, attr) for attr in attrs):
            found.append(pattern)
    return tuple(found)


def _scroll_axes(wrapper: Any) -> dict[str, bool | None]:
    # COM BOOL 仅接受明确的 0/1 或 bool；读取失败保留未知，不能伪装成不可滚动。
    result = {}
    for axis, attr in (("vertical", "CurrentVerticallyScrollable"), ("horizontal", "CurrentHorizontallyScrollable")):
        value = _safe_call(lambda: getattr(wrapper.iface_scroll, attr))
        result["current_" + axis] = bool(value) if type(value) in (int, bool) and value in (0, 1) else None
    return result


def _has_safe_attr(wrapper: Any, attr: str) -> bool:
    try:
        return bool(getattr(wrapper, attr))
    except Exception:
        return False


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _safe_call(func: Any) -> Any:
    if func is None:
        return None
    if not callable(func):
        return func
    try:
        return func()
    except Exception:
        return None


def _safe_bool(func: Any) -> bool | None:
    value = _safe_call(func)
    if value is None:
        return None
    return bool(value)


def _slug(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "control"


uia_provider = WindowsUIAProvider()
