from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, replace
from itertools import islice
from typing import Any, Iterator, Mapping

from app.core.window_manager import BoundWindow, window_manager

UIA_PROVIDER_ID = "windows_uia"
UIA_PROVIDER_VERSION = "windows_uia_provider_v1"
DEFAULT_UIA_MAX_CONTROLS = 1000
HARD_UIA_MAX_CONTROLS = 4000

_PINNED_UIA_SNAPSHOT: ContextVar[dict[str, Any] | None] = ContextVar(
    "pinned_uia_snapshot",
    default=None,
)


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
            # 先固定根 wrapper，再按深度优先顺序只拉取预算内控件，避免全树枚举后截断。
            wrappers = [root, *islice(root.iter_descendants(), control_budget - 1)]
            # 到达预算即保守标为截断，不额外读取可能阻塞的下一个节点来猜完整性。
            truncated = len(wrappers) == control_budget
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
                "scan_visited_count": len(wrappers),
                "scan_complete": not truncated,
                "truncated": truncated,
                "truncation_reason": "control_budget_reached" if truncated else None,
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
            return snapshot
        except Exception as exc:
            return self._unavailable("uia_scan_failed", str(exc))

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
            wrappers = [wrapper, *islice(wrapper.iter_descendants(), budget - 1)]
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
                     "scan_budget": budget, "scan_visited_count": len(wrappers),
                     "scan_complete": len(wrappers) < budget, "truncated": len(wrappers) == budget,
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
                    and win32gui.GetAncestor(handle, 3) == bound.handle
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
                wrappers = [root, *islice(root.iter_descendants(), 127)]
                if len(wrappers) == 128:
                    scopes.append({"status": "unavailable", "reason": "owned_popup_scan_incomplete", "scan_complete": False})
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
            parent = _safe_call(getattr(current, "parent", None))
            if parent is None:
                break
            parent_key = _runtime_id_key(parent)
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
