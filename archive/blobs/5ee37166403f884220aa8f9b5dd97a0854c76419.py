"""只读 UIA 文本字段快照；不执行聚焦、点击、键盘或剪贴板操作。"""
from __future__ import annotations

import math
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from .native_identity import validate_native_identity_fact
from .text_field_evidence import TextFieldIdentity, TextFieldSnapshot

# UI Automation 文档定义的 TextPattern IsReadOnly 属性和端点值。
UIA_IS_READONLY_ATTRIBUTE_ID = 40015
TEXT_ENDPOINT_START = 0
TEXT_ENDPOINT_END = 1
_RESOLVE_CONTROL_TYPES = frozenset({"Edit", "Document", "ComboBox", "Window", "Pane", "Group", "Text",
    "Button", "Hyperlink", "Menu", "MenuBar", "MenuItem", "List", "ListItem", "DataGrid", "DataItem",
    "Custom", "ToolBar", "Tab", "TabItem", "Tree", "TreeItem", "CheckBox", "RadioButton", "other"})


class TextFieldReadError(ValueError):
    """不携带控件文本、COM 消息或其它本地原值的读取失败。"""

    def __init__(self, reason_code: str, *, diagnostic: dict[str, Any] | None = None) -> None:
        code = str(reason_code)
        if not code.replace("_", "").isalnum() or len(code) > 96:
            code = "text_field_unavailable"
        self.reason_code = code
        self.diagnostic = _safe_read_diagnostic(diagnostic)
        super().__init__(code)

    def to_reference(self) -> dict[str, Any]:
        diagnostic = _safe_read_diagnostic(self.diagnostic)
        return {"reason_code": self.reason_code, **({"diagnostic": diagnostic} if diagnostic else {})}


def _safe_read_diagnostic(value):
    """只投影有限枚举和状态，不允许异常原文、字段名称或 COM 对象进入回执。"""
    if not isinstance(value, dict):
        return {}
    enums = {
        "phase": {"resolve_field", "describe_target", "keyboard_focus", "read_text"},
        "check": {"control_type", "visible", "enabled", "element", "password", "value_readonly", "text_readonly",
                  "value_pattern_missing", "text_pattern_missing"},
        "control_type": {"Edit", "Document", "ComboBox", "other"},
        "attribute_type": {"bool", "int", "other"},
        "deadline_stage": {"before_sample", "after_match", "before_wait", "attempt_limit", "exhausted"},
    }
    result = {key: value[key] for key, allowed in enums.items()
              if type(value.get(key)) is str and value[key] in allowed}
    if type(value.get("read_index")) is int and value["read_index"] in (1, 2):
        result["read_index"] = value["read_index"]
    if type(value.get("attribute_state")) in (bool, int) and value["attribute_state"] in (0, 1):
        result["attribute_state"] = value["attribute_state"]
    if type(value.get("attempt")) is int and 1 <= value["attempt"] <= 11:
        result["attempt"] = value["attempt"]
    if (type(value.get("elapsed_ms")) in (int, float) and math.isfinite(value["elapsed_ms"])
            and value["elapsed_ms"] >= 0):
        result["elapsed_ms"] = value["elapsed_ms"]
    if type(value.get("matched")) is bool:
        result["matched"] = value["matched"]
    visits = value.get("resolve_visits")
    if (type(visits) is list and 1 <= len(visits) <= 5 and all(
            type(item) is dict and type(item.get("control_type")) is str
            and item["control_type"] in _RESOLVE_CONTROL_TYPES
            and type(item.get("depth")) is int and item["depth"] == index
            and type(item.get("is_root")) is bool for index, item in enumerate(visits))):
        result["resolve_visits"] = [{key: item[key] for key in ("control_type", "depth", "is_root")} for item in visits]
    return result


def _read_stage_call(phase, read_index, function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except TextFieldReadError as error:
        error.diagnostic = _safe_read_diagnostic({**error.diagnostic, "phase": phase, "read_index": read_index})
        raise
    except Exception:
        raise TextFieldReadError("text_field_provider_unavailable",
            diagnostic={"phase": phase, "read_index": read_index}) from None


def _not_writable(check, control_type, attribute=None):
    return TextFieldReadError("text_field_target_not_writable", diagnostic={
        "check": check, "control_type": control_type if control_type in {"Edit", "Document", "ComboBox"} else "other",
        "attribute_type": "bool" if type(attribute) is bool else "int" if type(attribute) is int else "other",
        "attribute_state": attribute})


def _hit_timeout(stage, attempt, elapsed, matched):
    return TextFieldReadError("text_field_hit_not_ready", diagnostic={"deadline_stage": stage,
        "attempt": attempt + 1, "elapsed_ms": round(elapsed * 1000, 3), "matched": matched})


class WindowsTextFieldReader:
    """将一次屏幕门控的字段读取绑定到当前 Windows UIA 身份。"""

    def __init__(
        self,
        *,
        window_manager: Any,
        native_identity_reader: Any,
        desktop_factory: Callable[..., Any] | None = None,
        clock_ns: Callable[[], int] | None = None,
        read_id_factory: Callable[[], str] | None = None,
        readiness_clock: Callable[[], float] | None = None,
        readiness_wait: Callable[[float], None] | None = None,
    ) -> None:
        self._window_manager = window_manager
        self._native_identity_reader = native_identity_reader
        self._desktop_factory = desktop_factory or _desktop_factory
        self._clock_ns = clock_ns or time.perf_counter_ns
        self._read_id_factory = read_id_factory or (lambda: uuid.uuid4().hex)
        self._readiness_clock = readiness_clock or time.monotonic
        self._readiness_wait = readiness_wait or time.sleep

    def observe_field_hit(
        self, *, target_field_id: str, capture_id: str, target_window_handle: int,
        target_process_id: int, process_create_time: float,
        window_rect: tuple[int, int, int, int], target_bbox: tuple[int, int, int, int],
        click_point: tuple[int, int], expected_runtime_id: tuple[int, ...],
        expected_control_type: str,
    ) -> dict[str, Any]:
        """两次现场命中证明精确字段身份；不读取内容，不证明截图新鲜或授予操作。"""
        try:
            _validate_request(target_field_id, capture_id, target_window_handle, target_process_id,
                              process_create_time, window_rect, target_bbox, click_point)
            expected = _expected_field_identity(expected_runtime_id, expected_control_type)
            if expected is None:
                raise TextFieldReadError("text_field_expected_identity_invalid")
            self._verify_binding(target_window_handle, target_process_id, process_create_time, window_rect)
            desktop = self._desktop_factory(backend="uia")
            x, y = window_rect[0] + click_point[0], window_rect[1] + click_point[1]
            descriptions = []
            for initial in (True, False):
                wrapper = self._bound_field_hit(desktop, x, y, target_window_handle,
                    target_process_id, process_create_time, window_rect, target_bbox,
                    expected, allow_readiness=initial, require_direct_hit=True)
                description = self._describe_target(wrapper, target_window_handle,
                    target_process_id, window_rect, target_bbox, click_point)
                _require_writable_hit_patterns(wrapper, description["control_type"])
                descriptions.append(description)
                self._verify_binding(target_window_handle, target_process_id, process_create_time, window_rect)
            if descriptions[0] != descriptions[1]:
                raise TextFieldReadError("text_field_expected_identity_changed")
            return {
                "contract_version": "windows_field_hit_observation_v1",
                "provider": "windows_uia.from_point", "capture_id": capture_id,
                "target_field_id": target_field_id,
                "target": {"window_handle": target_window_handle, "process_id": target_process_id,
                    "process_create_time": process_create_time, "window_rect": list(window_rect)},
                "runtime_id": list(expected[0]), "control_type": expected[1],
                "bbox": dict(zip(("x", "y", "w", "h"), target_bbox)),
                "point": dict(zip(("x", "y"), click_point)),
                "observed_at_ns": self._clock_ns(), "sample_count": 2,
                "artifact_is_authorization": False, "action_executed": False,
            }
        except TextFieldReadError:
            raise
        except Exception:
            raise TextFieldReadError("text_field_hit_provider_unavailable") from None

    def read_field(
        self,
        *,
        target_field_id: str,
        capture_id: str,
        target_window_handle: int,
        target_process_id: int,
        process_create_time: float,
        window_rect: tuple[int, int, int, int],
        target_bbox: tuple[int, int, int, int],
        click_point: tuple[int, int],
        require_keyboard_focus: bool = False,
        expected_runtime_id: tuple[int, ...] | None = None,
        expected_control_type: str | None = None,
        allow_post_input_geometry_rebind: bool = False,
    ) -> TextFieldSnapshot:
        """公开边界：供应方异常绝不携带本地值或 COM 错误离开读取器。"""
        try:
            return self._read_field_impl(
                target_field_id=target_field_id,
                capture_id=capture_id,
                target_window_handle=target_window_handle,
                target_process_id=target_process_id,
                process_create_time=process_create_time,
                window_rect=window_rect,
                target_bbox=target_bbox,
                click_point=click_point,
                require_keyboard_focus=require_keyboard_focus,
                expected_runtime_id=expected_runtime_id,
                expected_control_type=expected_control_type,
                allow_post_input_geometry_rebind=allow_post_input_geometry_rebind,
            )
        except TextFieldReadError:
            raise
        except Exception:
            raise TextFieldReadError("text_field_provider_unavailable") from None

    def _read_field_impl(
        self,
        *,
        target_field_id: str,
        capture_id: str,
        target_window_handle: int,
        target_process_id: int,
        process_create_time: float,
        window_rect: tuple[int, int, int, int],
        target_bbox: tuple[int, int, int, int],
        click_point: tuple[int, int],
        require_keyboard_focus: bool = False,
        expected_runtime_id: tuple[int, ...] | None = None,
        expected_control_type: str | None = None,
        allow_post_input_geometry_rebind: bool = False,
    ) -> TextFieldSnapshot:
        if type(require_keyboard_focus) is not bool:
            raise TextFieldReadError("text_field_focus_requirement_invalid")
        _validate_request(target_field_id, capture_id, target_window_handle, target_process_id,
                          process_create_time, window_rect, target_bbox, click_point)
        expected = _expected_field_identity(expected_runtime_id, expected_control_type)
        if (type(allow_post_input_geometry_rebind) is not bool
                or allow_post_input_geometry_rebind and (expected is None or not require_keyboard_focus)):
            raise TextFieldReadError("text_field_post_input_binding_invalid")
        # 执行后仅从原点读值；新框不能用作输入前定位或授权任何新点击。
        read_target_bbox = (*click_point, 1, 1) if allow_post_input_geometry_rebind else target_bbox
        self._verify_binding(target_window_handle, target_process_id, process_create_time, window_rect)
        try:
            desktop = self._desktop_factory(backend="uia")
        except Exception:
            raise TextFieldReadError("text_field_uia_unavailable") from None
        screen_x, screen_y = window_rect[0] + click_point[0], window_rect[1] + click_point[1]
        if expected is None:
            wrapper = _read_stage_call("resolve_field", 1, lambda: self._resolve_field(
                self._from_point(desktop, screen_x, screen_y), target_window_handle))
        else:
            wrapper = _read_stage_call("resolve_field", 1, self._bound_field_hit, desktop, screen_x, screen_y,
                target_window_handle, target_process_id, process_create_time,
                window_rect, target_bbox, expected, allow_readiness=True,
                allow_geometry_rebind=allow_post_input_geometry_rebind)
        before = _read_stage_call("describe_target", 1, self._describe_target, wrapper, target_window_handle, target_process_id, window_rect,
                                       read_target_bbox, click_point)
        if require_keyboard_focus and not _has_keyboard_focus(wrapper):
            raise TextFieldReadError("text_field_keyboard_focus_unavailable", diagnostic={"phase": "keyboard_focus", "read_index": 1})
        try:
            value, source, selection = _read_stage_call("read_text", 1, self._read_text, wrapper, before["control_type"])
        except TextFieldReadError as error:
            if error.reason_code == "text_field_target_not_writable":
                _log_hit_geometry(wrapper, before, window_rect, target_bbox, click_point)
            raise
        self._verify_binding(target_window_handle, target_process_id, process_create_time, window_rect)
        # 重新从屏幕点获取，防止读取期间 UIA 代理或命中元素漂移。
        if expected is None:
            after_wrapper = _read_stage_call("resolve_field", 2, lambda: self._resolve_field(
                self._from_point(desktop, screen_x, screen_y), target_window_handle))
        else:
            after_wrapper = _read_stage_call("resolve_field", 2, self._bound_field_hit, desktop, screen_x, screen_y,
                target_window_handle, target_process_id, process_create_time,
                window_rect, target_bbox, expected, allow_readiness=False,
                allow_geometry_rebind=allow_post_input_geometry_rebind)
        after = _read_stage_call("describe_target", 2, self._describe_target, after_wrapper, target_window_handle, target_process_id, window_rect,
                                      read_target_bbox, click_point)
        if require_keyboard_focus and not _has_keyboard_focus(after_wrapper):
            raise TextFieldReadError("text_field_keyboard_focus_unavailable", diagnostic={"phase": "keyboard_focus", "read_index": 2})
        after_value, after_source, after_selection = _read_stage_call("read_text", 2, self._read_text, after_wrapper, after["control_type"])
        self._verify_binding(target_window_handle, target_process_id, process_create_time, window_rect)
        if before != after or value != after_value or source != after_source or selection != after_selection:
            raise TextFieldReadError("text_field_changed_during_read")
        try:
            observed_at_ns = self._clock_ns()
            read_id = self._read_id_factory()
        except Exception:
            raise TextFieldReadError("text_field_read_metadata_unavailable") from None
        if type(observed_at_ns) is not int or observed_at_ns <= 0 or not isinstance(read_id, str) or not read_id:
            raise TextFieldReadError("text_field_read_metadata_unavailable")
        try:
            identity = TextFieldIdentity(
                target_field_id=target_field_id,
                window_handle=target_window_handle,
                process_id=target_process_id,
                process_create_time=float(process_create_time),
                runtime_id=before["runtime_id"],
                window_rect=window_rect,
                control_bbox=before["control_bbox"],
            )
            return TextFieldSnapshot(identity, capture_id, read_id, observed_at_ns, source, value, selection)
        except Exception:
            raise TextFieldReadError("text_field_snapshot_unavailable") from None

    def _verify_binding(self, handle: int, process_id: int, created: float, rect: tuple[int, int, int, int]) -> None:
        try:
            bound = self._window_manager.get_bound_window()
            fact = self._native_identity_reader.read_identity(handle)
        except Exception:
            raise TextFieldReadError("text_field_identity_unavailable") from None
        if not _bound_matches(bound, handle, process_id, rect):
            raise TextFieldReadError("text_field_window_binding_changed")
        fact = validate_native_identity_fact(
            fact,
            target_window_handle=handle,
            expected_process_id=process_id,
        )
        if fact is None or float(fact["process_create_time"]) != float(created):
            raise TextFieldReadError("text_field_process_identity_changed")

    @staticmethod
    def _from_point(desktop: Any, x: int, y: int) -> Any:
        try:
            return desktop.from_point(x, y)
        except Exception:
            raise TextFieldReadError("text_field_target_unavailable") from None

    def _bound_field_hit(self, desktop, x, y, handle, process_id, created,
                         window_rect, target_bbox, expected, *, allow_readiness, require_direct_hit=False,
                         allow_geometry_rebind=False):
        """只在读前等待粗命中收敛；原点、字段身份固定，不重试输入。"""
        started = self._readiness_clock()
        for attempt in range(11):
            self._verify_binding(handle, process_id, created, window_rect)
            elapsed = self._readiness_clock() - started
            # 首次必要采样不被同步身份读取耗时吞掉；预算只限制后续采样启动。
            if attempt and elapsed >= .25:
                raise _hit_timeout("before_sample", attempt, elapsed, False)
            raw = self._from_point(desktop, x, y)
            if _top_window_handle(raw) != handle:
                raise TextFieldReadError("text_field_window_or_process_changed")
            raw_info = getattr(raw, "element_info", None)
            if _process_id(raw_info, getattr(raw_info, "element", None)) != process_id:
                raise TextFieldReadError("text_field_window_or_process_changed")
            try:
                # 命中证明不把字段内按钮提升为父字段；普通字段读取保留原子元素解析。
                field = (raw if str(getattr(raw_info, "control_type", "")) == expected[1] else None
                    ) if require_direct_hit else self._resolve_field(raw, handle)
            except TextFieldReadError as error:
                if error.reason_code != "text_field_target_not_writable":
                    raise
                field = None
            if field is not None:
                info = getattr(field, "element_info", None)
                runtime_id = getattr(info, "runtime_id", None)
                identity_matches = (type(runtime_id) in (tuple, list) and tuple(runtime_id) == expected[0]
                    and str(getattr(info, "control_type", "")) == expected[1])
                geometry_matches = False
                if identity_matches:
                    current_bbox = _relative_rect(getattr(info, "rectangle", None), window_rect)
                    geometry_matches = (current_bbox is not None
                        and _contains_point(current_bbox, (x-window_rect[0], y-window_rect[1]))
                        if allow_geometry_rebind else current_bbox == target_bbox)
                if identity_matches and geometry_matches:
                    self._verify_binding(handle, process_id, created, window_rect)
                    elapsed = self._readiness_clock() - started
                    # 同步调用不能被墙钟中断；已经完成且身份、几何与窗口复验通过的样本有效。
                    if attempt:
                        logging.getLogger(__name__).info("text_field_hit_ready attempts=%d elapsed_ms=%.3f",
                            attempt + 1, elapsed * 1000)
                    return field
                if str(getattr(info, "control_type", "")) in {"Edit", "ComboBox"}:
                    raise TextFieldReadError("text_field_expected_identity_changed")
            # 几何包围仅允许再做只读采样，绝不作为目标匹配证据。
            raw_bbox = _relative_rect(getattr(raw_info, "rectangle", None), window_rect)
            coarse = (str(getattr(raw_info, "control_type", "")) in {"Document", "Group", "Pane"}
                and raw_bbox is not None and raw_bbox != target_bbox and _contains_rect(raw_bbox, target_bbox)
                and _explicit_true_call(raw, "is_visible") and _explicit_true_call(raw, "is_enabled"))
            # 首次命中可能只是框内占位文字；只准继续只读采样，绝不把文字当成字段。
            placeholder = (str(getattr(raw_info, "control_type", "")) == "Text"
                and raw_bbox is not None and _contains_rect(target_bbox, raw_bbox)
                and _contains_point(raw_bbox, (x - window_rect[0], y - window_rect[1]))
                and _explicit_true_call(raw, "is_visible") and _explicit_true_call(raw, "is_enabled"))
            if not allow_readiness or not (coarse or placeholder):
                raise TextFieldReadError("text_field_expected_identity_changed")
            self._verify_binding(handle, process_id, created, window_rect)
            elapsed = self._readiness_clock() - started
            remaining = .25 - elapsed
            if attempt == 10 or remaining <= 0:
                raise _hit_timeout("attempt_limit" if attempt == 10 else "before_wait", attempt, elapsed, False)
            self._readiness_wait(min(.025, remaining))
        raise _hit_timeout("exhausted", attempt, elapsed, False)

    def _describe_target(self, wrapper: Any, handle: int, process_id: int,
                         window_rect: tuple[int, int, int, int], target_bbox: tuple[int, int, int, int],
                         click_point: tuple[int, int]) -> dict[str, Any]:
        info = getattr(wrapper, "element_info", None)
        control_type = str(getattr(info, "control_type", ""))
        if control_type not in {"Edit", "Document", "ComboBox"}:
            raise _not_writable("control_type", control_type)
        state_reader = _explicit_true_call if control_type == "ComboBox" else _bool_call
        if not state_reader(wrapper, "is_visible"):
            raise _not_writable("visible", control_type)
        if not state_reader(wrapper, "is_enabled"):
            raise _not_writable("enabled", control_type)
        element = getattr(info, "element", None)
        if element is None:
            raise _not_writable("element", control_type)
        password = getattr(element, "CurrentIsPassword", None)
        if ((control_type == "ComboBox" and not _explicit_uia_false(password))
                or (control_type != "ComboBox" and bool(password))):
            raise _not_writable("password", control_type, password)
        runtime_id = getattr(info, "runtime_id", None)
        if type(runtime_id) not in (tuple, list) or not runtime_id or any(type(item) is not int for item in runtime_id):
            raise TextFieldReadError("text_field_runtime_id_unavailable")
        control_bbox = _relative_rect(getattr(info, "rectangle", None), window_rect)
        if control_bbox is None or not _contains_rect(control_bbox, target_bbox) or not _contains_point(control_bbox, click_point):
            raise TextFieldReadError("text_field_geometry_changed")
        if _top_window_handle(wrapper) != handle or _process_id(info, element) != process_id:
            raise TextFieldReadError("text_field_window_or_process_changed")
        description = {"runtime_id": tuple(runtime_id), "control_bbox": control_bbox, "control_type": control_type}
        if control_type == "ComboBox":
            description["provider_identity"] = tuple(getattr(element, key, None) for key in
                ("CurrentFrameworkId", "CurrentAriaRole", "CurrentName"))
        return description

    @staticmethod
    def _resolve_field(wrapper: Any, expected_handle: int) -> Any:
        """从命中子元素向上最多四级，只在该顶层窗口内解析字段。"""
        try:
            root = wrapper.top_level_parent()
            root_info = getattr(root, "element_info", None)
            root_handle = int(getattr(root_info, "handle", getattr(root, "handle", 0)) or 0)
        except Exception:
            raise TextFieldReadError("text_field_window_or_process_changed") from None
        if root_handle != expected_handle:
            raise TextFieldReadError("text_field_window_or_process_changed")
        current = wrapper
        visits = []
        for depth in range(5):
            control_type = str(getattr(getattr(current, "element_info", None), "control_type", ""))
            is_root = current is root
            # 只记录既有路径已取出的类型与对象比较，不额外读取 UIA 或继续遍历。
            visits.append({"control_type": control_type if control_type in _RESOLVE_CONTROL_TYPES else "other",
                           "depth": depth, "is_root": is_root})
            if control_type in {"Edit", "Document", "ComboBox"}:
                return current
            if is_root or depth == 4:
                break
            try:
                parent = current.parent()
            except Exception:
                break
            if parent is None or parent is current:
                break
            current = parent
        raise TextFieldReadError("text_field_target_not_writable", diagnostic={"resolve_visits": visits})

    def _read_text(self, wrapper: Any, control_type: str) -> tuple[str, str, tuple[int, int] | None]:
        no_pattern = _no_pattern_exception()
        value: str | None = None
        text: str | None = None
        text_pattern: Any | None = None
        value_readonly: Any = None
        text_readonly: Any = None
        require_value_and_text = control_type == "ComboBox"
        if control_type in {"Edit", "ComboBox"}:
            try:
                value_pattern = wrapper.iface_value
                value_readonly = value_pattern.CurrentIsReadOnly
                if ((require_value_and_text and not _explicit_uia_false(value_readonly))
                        or (not require_value_and_text and bool(value_readonly))):
                    _log_readonly_rejection(control_type, "value", value_readonly)
                    raise _not_writable("value_readonly", control_type, value_readonly)
                value = _require_text(value_pattern.CurrentValue)
            except no_pattern:
                if require_value_and_text:
                    raise _not_writable("value_pattern_missing", control_type) from None
            except TextFieldReadError:
                raise
            except Exception:
                raise TextFieldReadError("text_field_value_unavailable") from None
        try:
            text_pattern = wrapper.iface_text
            text_readonly = text_pattern.DocumentRange.GetAttributeValue(UIA_IS_READONLY_ATTRIBUTE_ID)
            if ((require_value_and_text and not _explicit_uia_false(text_readonly))
                    or (not require_value_and_text and bool(text_readonly))):
                _log_readonly_rejection(control_type, "text", text_readonly)
                raise _not_writable("text_readonly", control_type, text_readonly)
            text = _require_text(text_pattern.DocumentRange.GetText(-1))
        except no_pattern:
            if require_value_and_text:
                raise _not_writable("text_pattern_missing", control_type) from None
            text_pattern = None
        except TextFieldReadError:
            raise
        except Exception:
            raise TextFieldReadError("text_field_text_unavailable") from None
        if value is None and text is None:
            raise TextFieldReadError("text_field_value_pattern_unavailable")
        # 值与名称偶然相等，也不能把名称流或单对象范围当作内容选区。
        object_range = (control_type in {"Edit", "ComboBox"} and text_pattern is not None
            and text == '\ufffc' and _chromium_object_text_range(wrapper, text_pattern, text))
        if object_range and (value is None or not _explicit_uia_false(value_readonly)
                or not _explicit_uia_false(text_readonly)):
            raise TextFieldReadError("text_field_value_pattern_unavailable")
        non_content_range = object_range or (control_type == "ComboBox" and text_pattern is not None
            and text is not None and _chromium_name_text_range(wrapper, text_pattern, text))
        if value is not None and text is not None and value != text:
            if not non_content_range:
                raise TextFieldReadError("text_field_value_patterns_disagree")
        if value is not None:
            source = "uia_value"
            result = value
        else:
            source = "uia_text"
            result = text  # type: ignore[assignment]
        # 非内容范围不能推断插入位置或追加后的值。
        selection = _selection(text_pattern) if text_pattern is not None and not non_content_range else None
        return result, source, selection


def _require_writable_hit_patterns(wrapper, control_type):
    """只读模式属性，不调用 CurrentValue、GetText 或选区接口。"""
    element = getattr(getattr(wrapper, "element_info", None), "element", None)
    if not _explicit_uia_false(getattr(element, "CurrentIsPassword", None)):
        raise TextFieldReadError("text_field_target_not_writable")
    no_pattern = _no_pattern_exception()
    available = set()
    for kind in (("value", "text") if control_type != "Document" else ("text",)):
        try:
            if kind == "value":
                readonly = wrapper.iface_value.CurrentIsReadOnly
            else:
                readonly = wrapper.iface_text.DocumentRange.GetAttributeValue(UIA_IS_READONLY_ATTRIBUTE_ID)
            if not _explicit_uia_false(readonly):
                raise TextFieldReadError("text_field_target_not_writable")
            available.add(kind)
        except no_pattern:
            continue
    if not available or (control_type == "ComboBox" and available != {"value", "text"}):
        raise TextFieldReadError("text_field_target_not_writable")


def _expected_field_identity(runtime_id, control_type):
    if runtime_id is None and control_type is None:
        return None
    if (type(runtime_id) not in (tuple, list) or not 1 <= len(runtime_id) <= 64
            or any(type(item) is not int for item in runtime_id) or not isinstance(control_type, str)):
        raise TextFieldReadError("text_field_expected_identity_invalid")
    normalized = {"edit":"Edit", "document":"Document", "combobox":"ComboBox", "combo box":"ComboBox"}.get(control_type.casefold())
    if normalized is None:
        raise TextFieldReadError("text_field_expected_identity_invalid")
    return tuple(runtime_id), normalized


def _log_readonly_rejection(control_type: str, pattern: str, attribute: Any) -> None:
    # 只记录白名单状态，禁止属性原文、对象 repr 或字段内容进入日志。
    kind = type(attribute)
    metadata = {
        "control_type": control_type if control_type in {"Edit", "Document", "ComboBox"} else "unknown",
        "pattern": pattern if pattern in {"value", "text"} else "unknown",
        "attribute_type": "bool" if kind is bool else "int" if kind is int else "other",
        "readonly": attribute if kind in (bool, int) and attribute in (0, 1) else None,
    }
    logging.getLogger(__name__).warning("text_field_readonly_rejection %s", metadata)


def _log_hit_geometry(wrapper, target, window_rect, target_bbox, point):
    # 不记录名称、原文或 COM 对象；几何取自已通过校验的本次读取。
    metadata = {"window_rect": window_rect, "expected_bbox": target_bbox,
        "hit_bbox": target["control_bbox"], "point": point, "parents": []}
    try:
        current = wrapper
        for _ in range(2):
            current = current.parent()
            if current is None:
                break
            kind = current.element_info.control_type
            metadata["parents"].append(kind if kind in {
                "Edit", "Document", "ComboBox", "Pane", "Window", "Group", "Custom"
            } else "other")
    except Exception:
        metadata["parent_state"] = "unavailable"
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        metadata["thread_dpi_awareness"] = user32.GetAwarenessFromDpiAwarenessContext(
            user32.GetThreadDpiAwarenessContext())
    except (AttributeError, OSError):
        metadata["thread_dpi_awareness"] = "unavailable"
    logging.getLogger(__name__).warning("text_field_hit_geometry %s", metadata)


def _chromium_name_text_range(wrapper, pattern, text):
    """仅识别同一 Chromium ComboBox 的名称型范围；其他冲突与未知供应方仍拒绝。"""
    try:
        info = wrapper.element_info
        element = info.element
        if (element.CurrentFrameworkId != "Chrome" or element.CurrentAriaRole != "combobox"
                or not text or element.CurrentName != text):
            return False
        enclosing = pattern.DocumentRange.GetEnclosingElement()
        return (enclosing is not None and tuple(enclosing.GetRuntimeId()) == tuple(info.runtime_id)
                and enclosing.CurrentProcessId == element.CurrentProcessId
                and enclosing.CurrentFrameworkId == "Chrome" and enclosing.CurrentAriaRole == "combobox"
                and enclosing.CurrentName == text)
    except Exception:
        # 缺少范围所有者或 COM 属性时不进入语义分支，交由原模式冲突错误拒绝。
        return False


def _chromium_object_text_range(wrapper, pattern, text):
    """同字段的单个对象标记不是值文本或选区；真实值仍必须由可写 ValuePattern 双读确认。"""
    if text != '\ufffc':
        return False
    try:
        info = wrapper.element_info
        element = info.element
        expected_role = {"Edit": "textbox", "ComboBox": "combobox"}.get(info.control_type)
        enclosing = pattern.DocumentRange.GetEnclosingElement()
        children = pattern.DocumentRange.GetChildren()
        return (expected_role is not None and element.CurrentFrameworkId == 'Chrome'
                and element.CurrentAriaRole == expected_role
                and enclosing is not None and children is not None and children.Length == 0
                and tuple(enclosing.GetRuntimeId()) == tuple(info.runtime_id)
                and enclosing.CurrentProcessId == element.CurrentProcessId
                and enclosing.CurrentFrameworkId == 'Chrome' and enclosing.CurrentAriaRole == expected_role
                and enclosing.CurrentName == element.CurrentName)
    except Exception:
        return False


def _desktop_factory(*, backend: str) -> Any:
    from pywinauto import Desktop
    return Desktop(backend=backend)


def _has_keyboard_focus(wrapper: Any) -> bool:
    # COM BOOL 可能返回整数 0/1；未知值不能按普通 truthiness 放行。
    value = getattr(wrapper.element_info.element, "CurrentHasKeyboardFocus", None)
    return type(value) in (bool, int) and value == 1


def _no_pattern_exception() -> type[Exception]:
    from pywinauto.uia_defines import NoPatternInterfaceError
    return NoPatternInterfaceError


def _selection(text_pattern: Any) -> tuple[int, int] | None:
    no_pattern = _no_pattern_exception()
    try:
        ranges = text_pattern.GetSelection()
        if ranges is None:
            raise TextFieldReadError("text_field_selection_unavailable")
        length = int(ranges.Length)
    except no_pattern:
        return None
    except TextFieldReadError:
        raise
    except Exception:
        raise TextFieldReadError("text_field_selection_unavailable") from None
    if length != 1:
        raise TextFieldReadError("text_field_selection_ambiguous")
    try:
        selected = ranges.GetElement(0)
        document = text_pattern.DocumentRange
        start_range = document.Clone()
        start_range.MoveEndpointByRange(TEXT_ENDPOINT_END, selected, TEXT_ENDPOINT_START)
        end_range = document.Clone()
        end_range.MoveEndpointByRange(TEXT_ENDPOINT_END, selected, TEXT_ENDPOINT_END)
        start, end = len(_require_text(start_range.GetText(-1))), len(_require_text(end_range.GetText(-1)))
    except Exception:
        raise TextFieldReadError("text_field_selection_unavailable") from None
    if start > end:
        raise TextFieldReadError("text_field_selection_invalid")
    return start, end


def _validate_request(field_id: str, capture_id: str, handle: int, pid: int, created: float,
                      window: tuple[int, int, int, int], bbox: tuple[int, int, int, int], point: tuple[int, int]) -> None:
    if (not isinstance(field_id, str) or not field_id or len(field_id) > 256
            or not isinstance(capture_id, str) or not capture_id or len(capture_id) > 256
            or type(handle) is not int or handle <= 0 or type(pid) is not int or pid <= 0
            or not isinstance(created, (float, int)) or isinstance(created, bool) or not math.isfinite(float(created)) or created <= 0
            or not _rect_valid(window) or not _rect_valid(bbox) or type(point) is not tuple or len(point) != 2
            or any(type(value) is not int for value in point) or not _contains_rect((0, 0, window[2], window[3]), bbox)
            or not _contains_point((0, 0, window[2], window[3]), point) or not _contains_point(bbox, point)):
        raise TextFieldReadError("text_field_read_request_invalid")


def _rect_valid(rect: object) -> bool:
    return type(rect) is tuple and len(rect) == 4 and all(type(item) is int for item in rect) and rect[2] > 0 and rect[3] > 0


def _bound_matches(bound: Any, handle: int, process_id: int, expected: tuple[int, int, int, int]) -> bool:
    if bound is None or int(getattr(bound, "handle", 0)) != handle or getattr(bound, "process_id", None) != process_id:
        return False
    actual = _bound_rect(getattr(bound, "rect", None))
    return actual == expected


def _bound_rect(rect: Any) -> tuple[int, int, int, int] | None:
    try:
        return int(rect.left), int(rect.top), int(rect.right) - int(rect.left), int(rect.bottom) - int(rect.top)
    except Exception:
        return None


def _relative_rect(rect: Any, window: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    try:
        left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:
        return None
    result = (left - window[0], top - window[1], right - left, bottom - top)
    return result if _rect_valid(result) and _contains_rect((0, 0, window[2], window[3]), result) else None


def _contains_rect(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[0] + inner[2] <= outer[0] + outer[2] and inner[1] + inner[3] <= outer[1] + outer[3]


def _contains_point(rect: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    return rect[0] <= point[0] < rect[0] + rect[2] and rect[1] <= point[1] < rect[1] + rect[3]


def _bool_call(wrapper: Any, name: str) -> bool:
    try:
        return bool(getattr(wrapper, name)())
    except Exception:
        return False


def _explicit_true_call(wrapper: Any, name: str) -> bool:
    try:
        value = getattr(wrapper, name)()
    except Exception:
        return False
    return type(value) in (bool, int) and value == 1


def _explicit_uia_false(value: Any) -> bool:
    return type(value) in (bool, int) and value == 0


def _process_id(info: Any, element: Any) -> int | None:
    for source in (info, element):
        value = getattr(source, "process_id", getattr(source, "CurrentProcessId", None))
        if type(value) is int and value > 0:
            return value
    return None


def _top_window_handle(wrapper: Any) -> int | None:
    try:
        root = wrapper.top_level_parent()
        info = getattr(root, "element_info", None)
        value = getattr(info, "handle", getattr(root, "handle", 0))
        return value if type(value) is int and value > 0 else None
    except Exception:
        return None


def _require_text(value: Any) -> str:
    if not isinstance(value, str):
        raise TextFieldReadError("text_field_value_unavailable")
    return value


__all__ = ["TextFieldReadError", "WindowsTextFieldReader"]
