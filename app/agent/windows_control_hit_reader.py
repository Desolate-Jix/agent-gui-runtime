"""原生按钮双次直接命中，只读身份与 Invoke 能力，不执行或授予动作。"""
from __future__ import annotations

import math
import time
import unicodedata
from typing import Any

from .native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
from .windows_text_field_reader import (
    _bound_matches, _contains_point, _contains_rect, _desktop_factory,
    _explicit_true_call, _process_id, _rect_valid, _relative_rect, _top_window_handle,
    _require_writable_hit_patterns,
    TextFieldReadError,
)


class NativeControlHitError(ValueError):
    """错误只携带稳定原因码，不传播 UIA 内容或底层异常文本。"""

    def __init__(self, reason_code):
        if (not isinstance(reason_code, str) or len(reason_code) > 96
                or not reason_code.replace("_", "").isalnum()):
            reason_code = "native_control_hit_unavailable"
        self.reason_code = reason_code
        super().__init__(reason_code)

    def to_reference(self):
        return {"reason_code": self.reason_code}


class WindowsControlHitReader:
    def __init__(self, window_manager, *, native_identity_reader=None, desktop_factory=None, clock_ns=None):
        self._window_manager = window_manager
        self._native_identity_reader = native_identity_reader or WindowsNativeIdentityReader(window_manager=window_manager)
        self._desktop_factory = desktop_factory or _desktop_factory
        self._clock_ns = clock_ns or time.perf_counter_ns

    def observe_control_hit(self, *, window_handle, process_id, process_create_time, window_rect,
                            capture_id, control_id, point, expected_runtime_id, expected_control_type,
                            expected_bbox) -> dict[str, Any]:
        """截图绑定由所有者证明；本方法只验证当前同一可调用控件，不作风险放行。"""
        try:
            runtime, kind = _request(window_handle, process_id, process_create_time, window_rect,
                capture_id, control_id, point, expected_runtime_id, expected_control_type, expected_bbox)
            self._verify_binding(window_handle, process_id, process_create_time, window_rect)
            desktop = self._desktop_factory(backend="uia")
            descriptions = []
            for _ in range(2):
                # 直接命中错误即拒绝，不重试、不回溯父节点、不改变原点击点。
                raw = desktop.from_point(window_rect[0] + point[0], window_rect[1] + point[1])
                descriptions.append(_describe(raw, window_handle, process_id, window_rect,
                    point, expected_bbox, runtime, kind))
                self._verify_binding(window_handle, process_id, process_create_time, window_rect)
            if descriptions[0] != descriptions[1]:
                raise NativeControlHitError("native_control_hit_changed_during_observation")
            observed = self._clock_ns()
            if type(observed) is not int or observed <= 0:
                raise NativeControlHitError("native_control_hit_clock_invalid")
            return {"contract_version": "native_control_hit_v1", "provider": "windows_uia.from_point",
                "capture_id": capture_id, "control_id": control_id,
                "target": {"window_handle": window_handle, "process_id": process_id,
                    "process_create_time": float(process_create_time), "window_rect": list(window_rect)},
                **descriptions[0], "observed_at_ns": observed, "sample_count": 2,
                "pattern": "Invoke", "artifact_is_authorization": False, "action_executed": False}
        except NativeControlHitError:
            raise
        except Exception:
            raise NativeControlHitError("native_control_hit_provider_unavailable") from None

    def _verify_binding(self, handle, process_id, created, rect):
        bound = self._window_manager.get_bound_window()
        if not _bound_matches(bound, handle, process_id, rect):
            raise NativeControlHitError("native_control_hit_window_binding_changed")
        fact = validate_native_identity_fact(self._native_identity_reader.read_identity(handle),
            target_window_handle=handle, expected_process_id=process_id)
        if fact is None or fact["process_create_time"] != float(created):
            raise NativeControlHitError("native_control_hit_process_identity_changed")

    def observe_target_hit(self, *, window_handle, process_id, process_create_time, window_rect,
            capture_id, control_id, point, expected_runtime_id, expected_control_type, expected_bbox,
            expected_name, expected_container=None):
        """执行前两次直接命中原语义目标；不替代目标、不扫描树、不读取字段值。"""
        try:
            runtime, kind = _request(window_handle, process_id, process_create_time, window_rect,
                capture_id, control_id, point, expected_runtime_id, expected_control_type, expected_bbox,
                supported_types={"Button", "Hyperlink", "Edit", "ComboBox", "MenuItem", "TabItem"}, capture_id_limit=4096)
            if not isinstance(expected_name, str) or not expected_name.strip() or len(expected_name) > 512:
                raise NativeControlHitError("native_control_hit_request_invalid")
            container = _container_request(expected_container, window_rect, expected_bbox)
            self._verify_binding(window_handle, process_id, process_create_time, window_rect)
            desktop = self._desktop_factory(backend="uia")
            descriptions = []
            for _ in range(2):
                raw = desktop.from_point(window_rect[0] + point[0], window_rect[1] + point[1])
                description = _describe(raw, window_handle, process_id, window_rect,
                    point, expected_bbox, runtime, kind, require_invoke=False)
                if _name(description["accessible_name"]) != _name(expected_name):
                    raise NativeControlHitError("native_control_hit_target_name_changed")
                # 原 UIA 合同允许直接动作类型；字段仍须现场证明模式可写，不读取内容。
                if kind in {"Edit", "ComboBox"}:
                    _require_writable_hit_patterns(raw, kind)
                if container is not None:
                    description["container"] = _confirmed_container(raw, window_handle, process_id, window_rect, container)
                descriptions.append(description)
                self._verify_binding(window_handle, process_id, process_create_time, window_rect)
            if descriptions[0] != descriptions[1]:
                raise NativeControlHitError("native_control_hit_changed_during_observation")
            observed = self._clock_ns()
            if type(observed) is not int or observed <= 0:
                raise NativeControlHitError("native_control_hit_clock_invalid")
            return {"contract_version": "structured_target_hit_v1", "provider": "windows_uia.from_point",
                "capture_id": capture_id, "control_id": control_id,
                "target": {"window_handle": window_handle, "process_id": process_id,
                    "process_create_time": float(process_create_time), "window_rect": list(window_rect)},
                **descriptions[0], "observed_at_ns": observed, "sample_count": 2,
                "validation_scope": "current_control_identity_before_dispatch_not_atomic",
                "artifact_is_authorization": False, "action_executed": False}
        except NativeControlHitError:
            raise
        except TextFieldReadError as error:
            raise NativeControlHitError(error.reason_code) from None
        except Exception:
            raise NativeControlHitError("native_control_hit_provider_unavailable") from None


def _request(handle, pid, created, window, capture_id, control_id, point, runtime, kind, bbox,
             *, supported_types=frozenset({"Button", "Hyperlink"}), capture_id_limit=256):
    kinds = {value.casefold(): value for value in supported_types}
    if (type(handle) is not int or handle <= 0 or type(pid) is not int or pid <= 0
            or type(created) not in (int, float) or not math.isfinite(created) or created <= 0
            or any(not isinstance(value, str) or not value or len(value) > limit
                for value, limit in ((capture_id, capture_id_limit), (control_id, 256)))
            or not _rect_valid(window) or not _rect_valid(bbox)
            or type(point) is not tuple or len(point) != 2 or any(type(value) is not int for value in point)
            or not _contains_rect((0, 0, window[2], window[3]), bbox)
            or not _contains_point(bbox, point)
            or type(runtime) not in (list, tuple) or not 1 <= len(runtime) <= 64
            or any(type(value) is not int for value in runtime)
            or not isinstance(kind, str) or kind.casefold() not in kinds):
        raise NativeControlHitError("native_control_hit_request_invalid")
    return tuple(runtime), kinds[kind.casefold()]


def _describe(raw, handle, pid, window, point, bbox, runtime, kind, *, require_invoke=True):
    info = getattr(raw, "element_info", None)
    element = getattr(info, "element", None)
    actual_runtime = getattr(info, "runtime_id", None)
    actual_name = getattr(info, "name", None)
    if (info is None or element is None or _top_window_handle(raw) != handle
            or _process_id(info, element) != pid
            or type(getattr(element, "CurrentProcessId", None)) is not int
            or element.CurrentProcessId != pid):
        raise NativeControlHitError("native_control_hit_window_or_process_changed")
    if (getattr(info, "control_type", None) != kind
            or type(actual_runtime) not in (list, tuple) or any(type(value) is not int for value in actual_runtime)
            or tuple(actual_runtime) != runtime or _relative_rect(getattr(info, "rectangle", None), window) != bbox
            or not isinstance(actual_name, str)):
        raise NativeControlHitError("native_control_hit_target_identity_changed")
    if not _explicit_true_call(raw, "is_visible") or not _explicit_true_call(raw, "is_enabled"):
        raise NativeControlHitError("native_control_hit_target_unavailable")
    if require_invoke and not getattr(raw, "iface_invoke", None):
        raise NativeControlHitError("native_control_hit_invoke_pattern_unavailable")
    return {"accessible_name": actual_name, "runtime_id": list(runtime), "control_type": kind,
        "bbox": dict(zip(("x", "y", "w", "h"), bbox)), "point": dict(zip(("x", "y"), point))}


def _name(value):
    return unicodedata.normalize("NFC", value).strip().casefold() if isinstance(value, str) else ""


def _container_request(value, window, target_bbox):
    if value is None:
        return None
    if (type(value) is not dict or set(value) != {"runtime_id", "control_type", "name", "bbox"}
            or type(value["runtime_id"]) not in (tuple, list) or not 1 <= len(value["runtime_id"]) <= 64
            or any(type(part) is not int for part in value["runtime_id"])
            or value["control_type"] not in {"Window", "Pane", "Group", "Custom", "ToolBar", "Menu", "Tab"}
            or not isinstance(value["name"], str) or not value["name"].strip() or len(value["name"]) > 512
            or not _rect_valid(value["bbox"]) or not _contains_rect((0, 0, window[2], window[3]), value["bbox"])
            or not _contains_rect(value["bbox"], target_bbox)):
        raise NativeControlHitError("native_control_hit_container_invalid")
    return {**value, "runtime_id": tuple(value["runtime_id"])}


def _confirmed_container(raw, handle, pid, window, expected):
    """只认原 RID 的实际祖先；遇最近原生窗口即止，不追 owner 或语义替代。"""
    current = raw
    seen = {tuple(raw.element_info.runtime_id)}
    for _ in range(32):
        current = current.parent()
        if current is None:
            break
        info = current.element_info
        if _process_id(info, getattr(info, "element", None)) != pid:
            raise NativeControlHitError("native_control_hit_container_changed")
        runtime = getattr(info, "runtime_id", None)
        if type(runtime) not in (tuple, list) or not runtime or any(type(part) is not int for part in runtime):
            raise NativeControlHitError("native_control_hit_container_changed")
        key = tuple(runtime)
        if key in seen:
            raise NativeControlHitError("native_control_hit_container_changed")
        seen.add(key)
        if key == expected["runtime_id"]:
            if (getattr(info, "control_type", None) != expected["control_type"]
                    or _name(getattr(info, "name", None)) != _name(expected["name"])
                    or _relative_rect(getattr(info, "rectangle", None), window) != expected["bbox"]
                    or not _explicit_true_call(current, "is_visible") or not _explicit_true_call(current, "is_enabled")):
                raise NativeControlHitError("native_control_hit_container_changed")
            return {"runtime_id": list(key), "control_type": expected["control_type"],
                "bbox": list(expected["bbox"]), "name": expected["name"]}
        native = getattr(info, "handle", getattr(current, "handle", 0))
        if native not in (None, 0):
            if _top_window_handle(current) != handle:
                raise NativeControlHitError("native_control_hit_container_changed")
            if native == handle:
                break
    raise NativeControlHitError("native_control_hit_container_changed")


__all__ = ["NativeControlHitError", "WindowsControlHitReader"]
