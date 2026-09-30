"""显式只读结束条件；不把 UIA 命中、画面静止或等待结束当任务成功。"""
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConditionObservationError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason_code = reason


class ObservationCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=500)
    control_type: Literal["Text", "Hyperlink", "Button", "Document"]

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("observation condition text must not be blank")
        return value


def validate_condition(value, wait_ms):
    if value is None:
        return None
    condition = ObservationCondition.model_validate(value).model_dump()
    if wait_ms <= 0:
        raise ValueError("observation_condition requires a positive observation wait budget")
    return condition


class UIATextConditionProbe:
    def __init__(self, condition, manager, reader, identity):
        self.condition, self.manager, self.reader, self.identity = condition, manager, reader, identity

    def __call__(self):
        from app.agent.native_identity import validate_native_identity_fact
        expected = self.identity
        handle, pid = expected["target_window_handle"], expected["process_id"]

        def bound_identity():
            fact = validate_native_identity_fact(self.reader.read_identity(handle),
                target_window_handle=handle, expected_process_id=pid)
            keys = ("target_window_handle", "process_id", "process_create_time", "executable_path")
            if fact is None or any(fact.get(k) != expected.get(k) for k in keys):
                raise ConditionObservationError("observation_condition_identity_changed")
            bound = self.manager.bind_window_by_handle(handle)
            if bound.handle != handle or bound.process_id != pid:
                raise ConditionObservationError("observation_condition_identity_changed")
            r = bound.rect
            return (r.left, r.top, r.right, r.bottom)

        rect = bound_identity()
        try:
            result = self._find(rect)
        except Exception as error:
            # 只读探测失败显式回报，不影响已派发输入，不泄露原始异常文本。
            result = {"status": "unavailable", "error_type": type(error).__name__,
                      "reason": "uia_condition_read_failed"}
        if bound_identity() != rect:
            raise ConditionObservationError("observation_condition_geometry_changed")
        return {**result, "source": "uia_exact_name", "target_window_handle": handle,
                "process_id": pid}

    def _find(self, rect):
        from pywinauto.uia_defines import IUIA
        api = IUIA()
        native = api.iuia
        dll = api.UIA_dll
        condition = native.CreateAndCondition(
            native.CreatePropertyCondition(dll.UIA_NamePropertyId, self.condition["text"]),
            native.CreatePropertyCondition(dll.UIA_ControlTypePropertyId,
                api.known_control_types[self.condition["control_type"]]))
        root = native.ElementFromHandle(self.identity["target_window_handle"])
        # 由系统按精确名称/类型过滤后返回有限数组，不遍历或缓存整个正文树。
        matches = root.FindAll(api.tree_scope["descendants"], condition)
        count = int(matches.Length)
        if count > 64:
            return {"status": "ambiguous", "reason": "too_many_exact_matches"}
        candidates = []
        for index in range(count):
            element = matches.GetElement(index)
            if (element.CurrentIsOffscreen or element.CurrentName != self.condition["text"]
                    or element.CurrentControlType != api.known_control_types[self.condition["control_type"]]):
                continue
            r = element.CurrentBoundingRectangle
            if not (rect[0] <= r.left < r.right <= rect[2] and rect[1] <= r.top < r.bottom <= rect[3]):
                continue
            runtime_id = list(element.GetRuntimeId())
            if not runtime_id:
                return {"status": "unavailable", "reason": "uia_runtime_identity_missing"}
            candidates.append({"runtime_id": runtime_id,
                "bbox": [r.left - rect[0], r.top - rect[1], r.right - r.left, r.bottom - r.top]})
            if len(candidates) > 1:
                return {"status": "ambiguous", "reason": "multiple_visible_exact_matches"}
        return {"status": "matched", **candidates[0]} if candidates else {"status": "absent"}


def observe_until_condition(probe, capture, baseline, *, timeout_ms, cancel, clock=perf_counter):
    started = clock()
    deadline = started + timeout_ms / 1000
    samples = []
    saw_absence = baseline.get("status") == "absent"
    previous, previous_at = None, None
    capture_ms = 0.0

    def check_cancel():
        if getattr(cancel, "is_set", lambda: False)():
            raise ConditionObservationError("observation_condition_cancelled")

    def capture_frame():
        nonlocal capture_ms
        check_cancel()
        at = clock()
        frame = capture()
        capture_ms += (clock() - at) * 1000
        return frame

    def read():
        check_cancel()
        value = probe()
        check_cancel()
        samples.append({"elapsed_ms": round((clock() - started) * 1000, 3), **value})
        return value

    def key(value):
        if value.get("status") != "matched":
            return None
        return (value.get("runtime_id"), value.get("bbox"), value.get("target_window_handle"),
                value.get("process_id"))

    def finish(frame, status, rechecked):
        return frame, {"status": status, "source": "uia_exact_name", "baseline": baseline,
            "samples": samples, "elapsed_ms": round((clock() - started) * 1000, 3),
            "timeout_ms": timeout_ms, "after_sha256": frame["sha256"],
            "deadline_scope": "polling_budget_not_io_timeout", "deadline_exceeded": clock() > deadline,
            "capture_elapsed_ms": round(capture_ms, 3),
            "after_capture_rechecked": rechecked, "task_effect_verified": None,
            "render_completion_verified": False, "automatic_retry_allowed": False}

    while clock() < deadline:
        value = read()
        at = clock()
        saw_absence |= value.get("status") == "absent"
        current = key(value)
        if (at < deadline and saw_absence and current is not None and current == previous
                and previous_at is not None and at - previous_at >= .099):
            frame = capture_frame()
            rechecked = read()
            if clock() < deadline and key(rechecked) == current:
                return finish(frame, "condition_met", True)
            previous = None
        else:
            previous, previous_at = current, at
        remaining = deadline - clock()
        if remaining <= 0:
            break
        if cancel.wait(min(.1, remaining)):
            raise ConditionObservationError("observation_condition_cancelled")
    check_cancel()
    # 超时仍提供当前原图，但不能把最后一次偶然命中补记为条件成功。
    frame = capture_frame()
    check_cancel()
    return finish(frame, "timed_out", False)
