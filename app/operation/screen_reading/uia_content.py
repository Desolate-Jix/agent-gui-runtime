"""只读 Windows UI Automation 内容读取，不执行任何界面输入或窗口变更。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping


_MAX_REGIONS = 80
_MAX_CHARS = 200_000
_CONTAINER_TYPES = {"Window", "Pane", "Document", "Group", "List", "ListItem", "DataGrid", "Tree", "Tab"}


class WindowsUIAContentReader:
    def __init__(self, desktop_factory: Callable[..., Any] | None = None) -> None:
        self._desktop_factory = desktop_factory or self._default_desktop

    def inspect_regions(self, bound: Any, max_regions: int = _MAX_REGIONS) -> dict[str, Any]:
        _limit(max_regions, "max_regions", 1, _MAX_REGIONS)
        root = self._root(bound)
        candidates = []
        wrappers, scan_truncated = self._enumerate(root)
        for wrapper in wrappers:
            item = self._candidate(wrapper, bound)
            if item is not None:
                candidates.append(item)
        candidates.sort(key=lambda item: (item["reference"]["fingerprint_sha256"], item["reference"]["bbox"]["y"], item["reference"]["bbox"]["x"]))
        truncated = scan_truncated or len(candidates) > max_regions
        return {"regions": [item for item in candidates[:max_regions]], "truncated": truncated}

    def read_region(self, bound: Any, reference: Mapping[str, Any], max_chars: int = _MAX_CHARS) -> dict[str, Any]:
        _limit(max_chars, "max_chars", 1, _MAX_CHARS)
        ref = _validate_reference(reference)
        root = self._root(bound)
        matches = []
        wrappers, scan_truncated = self._enumerate(root)
        if scan_truncated:
            raise ValueError("UIA region reference cannot be uniquely validated after truncated enumeration")
        for wrapper in wrappers:
            item = self._candidate(wrapper, bound)
            if item is not None and item["reference"] == ref:
                matches.append((wrapper, item))
        if len(matches) != 1:
            raise ValueError("UIA region reference is unknown, changed, or ambiguous")
        wrapper, item = matches[0]
        text = _text_pattern(wrapper, max_chars)
        if text is not None:
            value, was_truncated = _bounded_text(text, max_chars)
            return {"text": value, "provider": "windows_uia", "method": "text_pattern_document_range",
                    "truncated": was_truncated, "read_complete": not was_truncated,
                    "completion_basis": "uia_document_range", "region_reference": ref}
        value, was_truncated = _descendant_text(wrapper, max_chars)
        return {"text": value, "provider": "windows_uia", "method": "descendant_text",
                "truncated": was_truncated, "read_complete": False,
                "completion_basis": "descendant_inventory_not_proof_of_complete_content", "region_reference": ref}

    def _root(self, bound: Any) -> Any:
        handle = _bound_value(bound, "handle")
        if handle is None:
            raise ValueError("bound window handle is required")
        desktop = self._desktop_factory(backend="uia")
        specification = desktop.window(handle=handle)
        wrapper = specification.wrapper_object()
        actual_handle = _bound_value(wrapper, "handle")
        if actual_handle is not None and int(actual_handle) != int(handle):
            raise ValueError("UIA root HWND changed")
        expected_pid = _bound_value(bound, "process_id")
        actual_pid = _call(wrapper, "process_id") or _call(getattr(wrapper, "element_info", None), "process_id")
        if expected_pid is not None and actual_pid is not None and int(actual_pid) != int(expected_pid):
            raise ValueError("UIA root PID changed")
        return wrapper

    @staticmethod
    def _default_desktop(**kwargs: Any) -> Any:
        from pywinauto import Desktop
        return Desktop(**kwargs)

    def _enumerate(self, root: Any) -> tuple[list[Any], bool]:
        result, queue = [], [root]
        truncated = False
        while queue:
            if len(result) >= 4096:
                truncated = True
                break
            item = queue.pop(0)
            result.append(item)
            try:
                children = list(item.children())
            except Exception as exc:
                raise RuntimeError(f"UIA child enumeration failed: {exc}") from exc
            remaining = 4096 - len(result) - len(queue)
            if len(children) > max(0, remaining):
                queue.extend(children[:max(0, remaining)])
                truncated = True
            else:
                queue.extend(children)
        return result, truncated

    def _candidate(self, wrapper: Any, bound: Any) -> dict[str, Any] | None:
        rect = _rectangle(wrapper)
        if rect is None or rect["w"] <= 0 or rect["h"] <= 0:
            return None
        client = _client_rect(bound)
        screen = {"x": rect["x"], "y": rect["y"], "w": rect["w"], "h": rect["h"]}
        if not _intersects(screen, client):
            return None
        info = getattr(wrapper, "element_info", None)
        visible = _call(wrapper, "is_visible")
        if visible is False:
            return None
        control_type = _string(getattr(info, "control_type", None)) or _string(_call(wrapper, "friendly_class_name")) or ""
        has_text = _text_pattern_capable(wrapper)
        full_name = _string(getattr(info, "name", None)) or _string(_call(wrapper, "window_text")) or ""
        name = full_name[:200]
        if not has_text and control_type not in _CONTAINER_TYPES:
            return None
        runtime_id = getattr(info, "runtime_id", None)
        if callable(runtime_id):
            runtime_id = _safe(runtime_id)
        automation_id = _string(_call(info, "automation_id"))
        hwnd = _bound_value(wrapper, "handle") or _bound_value(bound, "handle")
        pid = _call(info, "process_id") or _call(wrapper, "process_id") or _bound_value(bound, "process_id")
        fingerprint = {"hwnd": hwnd, "pid": pid,
                       "runtime_id": _jsonable(runtime_id), "automation_id": automation_id,
                       "type": control_type, "bbox": screen, "name": full_name}
        digest = hashlib.sha256(_canonical(fingerprint).encode("utf-8")).hexdigest()
        reference = {**fingerprint, "fingerprint_sha256": digest}
        return {"region_id": "uia_" + digest[:24], "name": name, "control_type": control_type,
                "bbox": {"x": screen["x"] - client["x"], "y": screen["y"] - client["y"], "w": screen["w"], "h": screen["h"]},
                "reader": "uia_text_pattern" if has_text else "uia_descendant_text", "reference": reference}


def _text_pattern(wrapper: Any, limit: int) -> str | None:
    try:
        rng = wrapper.iface_text.DocumentRange
        if rng is None:
            raise RuntimeError("UIA TextPattern DocumentRange is unavailable")
        # Windows 提供者可能按 UTF-16 计数，保留补充平面字符的截断哨兵。
        value = rng.GetText(2 * (limit + 1))
        if not isinstance(value, str):
            raise RuntimeError("UIA TextPattern GetText returned non-string content")
        return value
    except Exception as exc:
        if _is_no_pattern(exc):
            return None
        raise RuntimeError(f"UIA TextPattern GetText failed: {exc}") from exc


def _text_pattern_capable(wrapper: Any) -> bool:
    try:
        iface = getattr(wrapper, "iface_text")
        if getattr(iface, "DocumentRange") is None:
            raise RuntimeError("UIA TextPattern DocumentRange is unavailable")
        return True
    except Exception as exc:
        if _is_no_pattern(exc):
            return False
        raise RuntimeError(f"UIA TextPattern discovery failed: {exc}") from exc


def _is_no_pattern(exc: Exception) -> bool:
    return exc.__class__.__name__ == "NoPatternInterfaceError" or isinstance(exc, AttributeError)


def _descendant_text(wrapper: Any, limit: int) -> tuple[str, bool]:
    values = []
    for item in _bounded_children(wrapper):
        info = getattr(item, "element_info", None)
        value = _string(getattr(info, "name", None)) or _string(_call(item, "window_text"))
        if value:
            values.append(value)
    return _bounded_text("\n".join(values), limit)


def _bounded_children(root: Any) -> list[Any]:
    result, queue = [], [root]
    while queue and len(result) < 4096:
        item = queue.pop(0)
        result.append(item)
        try:
            children = list(item.children())
            remaining = 4096 - len(result) - len(queue)
            queue.extend(children[:max(0, remaining)])
        except Exception as exc:
            raise RuntimeError(f"UIA child enumeration failed: {exc}") from exc
    return result


def _validate_reference(reference: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(reference, Mapping):
        raise ValueError("region reference must be a JSON object")
    ref = dict(reference)
    required = {"hwnd", "pid", "runtime_id", "automation_id", "type", "bbox", "name", "fingerprint_sha256"}
    if set(ref) != required or not isinstance(ref["bbox"], Mapping):
        raise ValueError("region reference has invalid fingerprint shape")
    if not isinstance(ref["fingerprint_sha256"], str) or len(ref["fingerprint_sha256"]) != 64:
        raise ValueError("region reference fingerprint_sha256 is invalid")
    fp = {k: ref[k] for k in required if k != "fingerprint_sha256"}
    if hashlib.sha256(_canonical(fp).encode("utf-8")).hexdigest() != ref["fingerprint_sha256"]:
        raise ValueError("region reference fingerprint hash mismatch")
    return ref


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _rectangle(wrapper: Any) -> dict[str, int] | None:
    try:
        r = wrapper.rectangle()
        return {"x": int(r.left), "y": int(r.top), "w": max(0, int(r.right) - int(r.left)), "h": max(0, int(r.bottom) - int(r.top))}
    except Exception:
        return None


def _client_rect(bound: Any) -> dict[str, int]:
    rect = _bound_value(bound, "rect")
    if rect is None:
        raise ValueError("bound window rectangle is required")
    return {"x": int(_bound_value(rect, "left")), "y": int(_bound_value(rect, "top")),
            "w": int(_bound_value(rect, "right") - _bound_value(rect, "left")), "h": int(_bound_value(rect, "bottom") - _bound_value(rect, "top"))}


def _intersects(a: Mapping[str, int], b: Mapping[str, int]) -> bool:
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


def _bounded_text(value: str, limit: int) -> tuple[str, bool]:
    return (value[:limit], len(value) > limit)


def _limit(value: Any, label: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")


def _bound_value(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _call(obj: Any, name: str) -> Any:
    try:
        value = getattr(obj, name)
        return value() if callable(value) else value
    except Exception:
        return None


def _safe(func: Any) -> Any:
    try:
        return func()
    except Exception:
        return None


def _safe_list(obj: Any, name: str) -> list[Any]:
    try:
        return list(getattr(obj, name)())
    except Exception:
        return []


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)
