from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.window_manager import BoundWindow, window_manager

UIA_PROVIDER_ID = "windows_uia"
UIA_PROVIDER_VERSION = "windows_uia_provider_v1"


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
            "expected_fields": ["control_type", "name", "automation_id", "bounding_rectangle", "enabled", "patterns"],
            "merge_keys": ["bbox_overlap", "role_guess", "label_or_name", "window_process"],
        }

    def snapshot_bound_window(self, *, max_controls: int = 250) -> dict[str, Any]:
        bound = window_manager.get_bound_window()
        if bound is None:
            return self._unavailable("no_bound_window", "Bind a target window before collecting UIA controls.")
        return self.snapshot_window(bound, max_controls=max_controls)

    def snapshot_window(self, bound: BoundWindow, *, max_controls: int = 250) -> dict[str, Any]:
        try:
            from pywinauto import Desktop

            root = Desktop(backend="uia").window(handle=bound.handle)
            wrappers = [root, *root.descendants()[: max(0, max_controls - 1)]]
            controls = []
            for index, wrapper in enumerate(wrappers):
                control = self._control_from_wrapper(wrapper, bound=bound, index=index)
                if control is not None:
                    controls.append(control.to_dict())
            return {
                "provider": self.provider_id,
                "provider_version": self.version,
                "status": "ok",
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
        except Exception as exc:
            return self._unavailable("uia_scan_failed", str(exc))

    def _control_from_wrapper(self, wrapper: Any, *, bound: BoundWindow, index: int) -> UIAControl | None:
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
            return None

        bbox = UIABBox(
            x=screen_bbox.x - int(bound.rect.left),
            y=screen_bbox.y - int(bound.rect.top),
            w=screen_bbox.w,
            h=screen_bbox.h,
        )
        info = getattr(wrapper, "element_info", None)
        name = _first_text(
            _safe_call(getattr(wrapper, "window_text", None)),
            getattr(info, "name", None),
            getattr(info, "rich_text", None),
        )
        control_type = _first_text(
            getattr(info, "control_type", None),
            _safe_call(getattr(wrapper, "friendly_class_name", None)),
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


def _patterns(wrapper: Any) -> tuple[str, ...]:
    candidates = {
        "Invoke": ["invoke", "iface_invoke"],
        "Value": ["get_value", "set_value", "iface_value"],
        "Text": ["texts", "iface_text"],
        "Selection": ["select", "iface_selection_item", "iface_selection"],
        "ExpandCollapse": ["expand", "collapse", "iface_expand_collapse"],
        "Toggle": ["toggle", "iface_toggle"],
    }
    found: list[str] = []
    for pattern, attrs in candidates.items():
        if any(_has_safe_attr(wrapper, attr) for attr in attrs):
            found.append(pattern)
    return tuple(found)


def _has_safe_attr(wrapper: Any, attr: str) -> bool:
    try:
        getattr(wrapper, attr)
    except Exception:
        return False
    return True


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
