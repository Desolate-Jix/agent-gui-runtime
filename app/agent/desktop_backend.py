"""W4 内部桌面执行 seam；不属于公开 Agent/Runtime Contract。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import Lock
import time
from typing import Any, Callable, Literal, Protocol
from uuid import uuid4

from app.agent.scroll_parameters import ScrollDispatchParameters
from app.agent.popup_click_guard import PopupClickGuard
from app.agent.taskbar_activation_guard import TaskbarActivationGuard
from app.agent.text_input_guard import TextInputGuard
from app.agent.text_parameters import TextDispatchParameters
from app.core.observation_policy import resolve_render_grace_ms


def _validate_target_bbox(bbox, click_point) -> None:
    if bbox is None:
        return
    if (type(bbox) is not tuple or len(bbox) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in bbox)
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in click_point)):
        raise ValueError("dispatch target bbox must be an immutable finite rectangle")
    x, y, width, height = bbox
    if (x < 0 or y < 0 or width <= 0 or height <= 0
            or not (x <= click_point[0] < x + width and y <= click_point[1] < y + height)):
        raise ValueError("dispatch target bbox must contain the current click point")


@dataclass(frozen=True, slots=True)
class DesktopDispatchCommand:
    semantic_action: str
    capture_id: str
    candidate_id: str
    click_point: tuple[float, float]
    target_window_handle: int
    scroll: ScrollDispatchParameters | None = None
    text_input: TextDispatchParameters | None = None
    text_guard: TextInputGuard | None = None
    popup_guard: PopupClickGuard | None = None
    taskbar_guard: TaskbarActivationGuard | None = None
    target_bbox: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        if not self.semantic_action or not self.capture_id or not self.candidate_id:
            raise ValueError("dispatch command requires semantic and current target identity")
        if len(self.click_point) != 2:
            raise ValueError("dispatch command requires one click point")
        _validate_target_bbox(self.target_bbox, self.click_point)
        if type(self.target_window_handle) is not int or self.target_window_handle <= 0:
            raise ValueError("dispatch command requires a positive server target window handle")
        if self.semantic_action == "taskbar_activate":
            if type(self.taskbar_guard) is not TaskbarActivationGuard:
                raise ValueError("taskbar activation requires a typed guard")
            if any(
                value is not None
                for value in (self.scroll, self.text_input, self.text_guard, self.popup_guard)
            ):
                raise ValueError("taskbar activation cannot carry another action payload")
            expectation = self.taskbar_guard.expectation
            if (
                self.capture_id != expectation.capture_id
                or self.candidate_id != expectation.candidate_id
            ):
                raise ValueError("taskbar activation command identity does not match guard")
            self.taskbar_guard.validate_command(
                window_handle=self.target_window_handle,
                click_point=self.click_point,
            )
        elif self.taskbar_guard is not None:
            raise ValueError("non-taskbar dispatch cannot carry taskbar guard")
        if self.semantic_action == "scroll_region":
            if type(self.scroll) is not ScrollDispatchParameters:
                raise ValueError("scroll dispatch requires current typed parameters")
            self.scroll.validate_point(self.click_point)
        elif self.scroll is not None:
            raise ValueError("non-scroll dispatch cannot carry scroll parameters")
        if self.semantic_action == "fill_field":
            if type(self.text_input) is not TextDispatchParameters:
                raise ValueError("text dispatch requires current typed parameters")
            self.text_input.validate_point(self.click_point)
        elif self.text_input is not None:
            raise ValueError("non-text dispatch cannot carry text parameters")
        if self.text_guard is not None:
            if type(self.text_guard) is not TextInputGuard:
                raise ValueError("text dispatch guard must be typed")
            if self.semantic_action != "fill_field" or self.text_input is None:
                raise ValueError("non-text dispatch cannot carry text guard")
            if self.text_guard.expectation.parameters != self.text_input.parameters:
                raise ValueError("text dispatch guard does not match text parameters")
            identity = self.text_guard.expectation.before.identity
            if identity.window_handle != self.target_window_handle:
                raise ValueError("text dispatch guard does not match target window")
            left, top, width, height = identity.control_bbox
            x, y = self.click_point
            if not (left <= x < left + width and top <= y < top + height):
                raise ValueError("text dispatch guard does not match target point")
        if self.popup_guard is not None:
            if type(self.popup_guard) is not PopupClickGuard:
                raise ValueError("popup dispatch guard must be typed")
            if self.semantic_action != "open_detail" or self.scroll is not None or self.text_input is not None:
                raise ValueError("only ordinary open_detail dispatch can carry popup guard")
            self.popup_guard.validate_command(
                window_handle=self.target_window_handle,
                click_point=self.click_point,
            )


@dataclass(frozen=True, slots=True)
class BackendDispatchReceipt:
    receipt_ref: str
    status: Literal["dispatched", "not_started", "indeterminate"]
    reason_code: Literal["none", "backend_failed", "backend_result_lost"]


class DesktopBackend(Protocol):
    def dispatch(
        self,
        command: DesktopDispatchCommand,
        *,
        authority: object,
    ) -> BackendDispatchReceipt: ...


_AUTHORITY_MINT_KEY = object()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _authority_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class FreshExecutionSourceLineage:
    """首次学习派发的显式来源链；不冒充已审核工作流。"""

    source_sha256: str
    approved_preview_sha256: str
    fresh_preview_sha256: str
    confirmation_id: str
    consume_content_sha256: str

    def __post_init__(self) -> None:
        for label, value in (
            ("fresh source digest", self.source_sha256),
            ("approved preview digest", self.approved_preview_sha256),
            ("fresh preview digest", self.fresh_preview_sha256),
            ("fresh consume digest", self.consume_content_sha256),
        ):
            _authority_sha256(value, label)
        if self.approved_preview_sha256 == self.fresh_preview_sha256:
            raise ValueError("fresh execution lineage requires a new preview")
        if (
            not isinstance(self.confirmation_id, str)
            or _STABLE_ID.fullmatch(self.confirmation_id) is None
        ):
            raise ValueError("fresh execution confirmation identity is invalid")


@dataclass(frozen=True, slots=True)
class TaskbarExecutionSourceLineage:
    """任务栏派发的独立来源链，不冒充审核工作流或首次学习。"""

    source_sha256: str
    preview_sha256: str
    confirmation_id: str
    consume_content_sha256: str

    def __post_init__(self) -> None:
        for label, value in (
            ("taskbar source digest", self.source_sha256),
            ("taskbar preview digest", self.preview_sha256),
            ("taskbar consume digest", self.consume_content_sha256),
        ):
            _authority_sha256(value, label)
        if (
            not isinstance(self.confirmation_id, str)
            or _STABLE_ID.fullmatch(self.confirmation_id) is None
        ):
            raise ValueError("taskbar execution confirmation identity is invalid")


class _ExecutionAuthority:
    __slots__ = (
        "session_id",
        "observation_id",
        "intent_id",
        "workflow_revision_hash",
        "source_lineage",
        "taskbar_source_lineage",
        "semantic_action",
        "selection_sha256",
        "action_evidence_sha256",
        "capture_id",
        "candidate_id",
        "click_point",
        "target_bbox",
        "target_window_handle",
        "gate_decision_ref",
        "scroll",
        "text_input",
        "text_guard",
        "popup_guard",
        "taskbar_guard",
        "_consumed",
        "_lock",
    )

    def __init__(
        self,
        mint_key: object,
        *,
        session_id: str,
        observation_id: str,
        intent_id: str,
        workflow_revision_hash: str | None = None,
        semantic_action: str,
        selection_sha256: str | None = None,
        capture_id: str,
        candidate_id: str,
        click_point: tuple[float, float],
        target_window_handle: int,
        gate_decision_ref: str,
        source_lineage: FreshExecutionSourceLineage | None = None,
        taskbar_source_lineage: TaskbarExecutionSourceLineage | None = None,
        action_evidence_sha256: str | None = None,
        scroll: ScrollDispatchParameters | None = None,
        text_input: TextDispatchParameters | None = None,
        text_guard: TextInputGuard | None = None,
        popup_guard: PopupClickGuard | None = None,
        taskbar_guard: TaskbarActivationGuard | None = None,
        target_bbox: tuple[float, float, float, float] | None = None,
    ) -> None:
        if mint_key is not _AUTHORITY_MINT_KEY:
            raise PermissionError("execution authority is controller-internal")
        _validate_target_bbox(target_bbox, click_point)
        reviewed_family = workflow_revision_hash is not None or selection_sha256 is not None
        fresh_family = source_lineage is not None or action_evidence_sha256 is not None
        taskbar_family = taskbar_source_lineage is not None
        if sum((reviewed_family, fresh_family, taskbar_family)) != 1:
            raise ValueError("execution authority requires exactly one source family")
        if reviewed_family:
            if workflow_revision_hash is None or selection_sha256 is None:
                raise ValueError("reviewed execution authority lineage is incomplete")
            _authority_sha256(workflow_revision_hash, "workflow revision hash")
            _authority_sha256(selection_sha256, "selection digest")
        elif fresh_family:
            if type(source_lineage) is not FreshExecutionSourceLineage:
                raise TypeError("fresh execution authority requires typed source lineage")
            evidence_digest = _authority_sha256(
                action_evidence_sha256, "fresh action evidence digest"
            )
            if evidence_digest != source_lineage.fresh_preview_sha256:
                raise ValueError("fresh action evidence does not match current preview")
        else:
            if type(taskbar_source_lineage) is not TaskbarExecutionSourceLineage:
                raise TypeError("taskbar execution authority requires typed source lineage")
            if semantic_action != "taskbar_activate":
                raise ValueError("taskbar source lineage requires taskbar activation")
            if type(taskbar_guard) is not TaskbarActivationGuard:
                raise TypeError("taskbar execution authority requires typed guard")
            if taskbar_source_lineage.source_sha256 != taskbar_guard.expectation.source_sha256:
                raise ValueError("taskbar source lineage does not match guard")
        if semantic_action == "taskbar_activate" and not taskbar_family:
            raise ValueError("taskbar activation requires independent taskbar source lineage")
        if semantic_action != "taskbar_activate" and taskbar_guard is not None:
            raise ValueError("non-taskbar authority cannot carry taskbar guard")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "observation_id", observation_id)
        object.__setattr__(self, "intent_id", intent_id)
        object.__setattr__(self, "workflow_revision_hash", workflow_revision_hash)
        object.__setattr__(self, "source_lineage", source_lineage)
        object.__setattr__(self, "taskbar_source_lineage", taskbar_source_lineage)
        object.__setattr__(self, "semantic_action", semantic_action)
        object.__setattr__(self, "selection_sha256", selection_sha256)
        object.__setattr__(self, "action_evidence_sha256", action_evidence_sha256)
        object.__setattr__(self, "capture_id", capture_id)
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "click_point", click_point)
        object.__setattr__(self, "target_bbox", target_bbox)
        object.__setattr__(self, "target_window_handle", target_window_handle)
        object.__setattr__(self, "gate_decision_ref", gate_decision_ref)
        object.__setattr__(self, "scroll", scroll)
        object.__setattr__(self, "text_input", text_input)
        object.__setattr__(self, "text_guard", text_guard)
        object.__setattr__(self, "popup_guard", popup_guard)
        object.__setattr__(self, "taskbar_guard", taskbar_guard)
        object.__setattr__(self, "_consumed", False)
        object.__setattr__(self, "_lock", Lock())

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("execution authority snapshot is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("execution authority snapshot is immutable")

    def consume(self) -> None:
        with self._lock:
            if self._consumed:
                raise PermissionError("execution authority already consumed")
            # 仅消费方法可在锁内改变一次性状态，调用方不能重置或替换绑定。
            object.__setattr__(self, "_consumed", True)

    def __reduce__(self) -> object:
        raise TypeError("execution authority cannot be serialized")


def _mint_execution_authority(
    *,
    session_id: str,
    observation_id: str,
    intent_id: str,
    workflow_revision_hash: str | None = None,
    semantic_action: str,
    selection_sha256: str | None = None,
    capture_id: str,
    candidate_id: str,
    click_point: tuple[float, float],
    target_window_handle: int,
    gate_decision_ref: str,
    source_lineage: FreshExecutionSourceLineage | None = None,
    taskbar_source_lineage: TaskbarExecutionSourceLineage | None = None,
    action_evidence_sha256: str | None = None,
    scroll: ScrollDispatchParameters | None = None,
    text_input: TextDispatchParameters | None = None,
    text_guard: TextInputGuard | None = None,
    popup_guard: PopupClickGuard | None = None,
    taskbar_guard: TaskbarActivationGuard | None = None,
    target_bbox: tuple[float, float, float, float] | None = None,
) -> _ExecutionAuthority:
    return _ExecutionAuthority(
        _AUTHORITY_MINT_KEY,
        session_id=session_id,
        observation_id=observation_id,
        intent_id=intent_id,
        workflow_revision_hash=workflow_revision_hash,
        source_lineage=source_lineage,
        taskbar_source_lineage=taskbar_source_lineage,
        semantic_action=semantic_action,
        selection_sha256=selection_sha256,
        action_evidence_sha256=action_evidence_sha256,
        capture_id=capture_id,
        candidate_id=candidate_id,
        click_point=click_point,
        target_window_handle=target_window_handle,
        gate_decision_ref=gate_decision_ref,
        scroll=scroll,
        text_input=text_input,
        text_guard=text_guard,
        popup_guard=popup_guard,
        taskbar_guard=taskbar_guard,
        target_bbox=target_bbox,
    )


def _consume_authority(
    authority: object,
    command: DesktopDispatchCommand,
) -> _ExecutionAuthority:
    if not isinstance(authority, _ExecutionAuthority):
        raise PermissionError("valid execution authority is required")
    if (
        authority.semantic_action != command.semantic_action
        or authority.capture_id != command.capture_id
        or authority.candidate_id != command.candidate_id
        or authority.click_point != command.click_point
        or authority.target_bbox != command.target_bbox
        or authority.target_window_handle != command.target_window_handle
        or authority.scroll != command.scroll
        or authority.text_input != command.text_input
        or authority.text_guard is not command.text_guard
        or authority.popup_guard is not command.popup_guard
        or authority.taskbar_guard is not command.taskbar_guard
    ):
        raise PermissionError("dispatch command does not match execution authority")
    authority.consume()
    return authority


class DeterministicFakeBackend:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.dispatch_count = 0
        self.attempt_count = 0
        self.commands: list[DesktopDispatchCommand] = []

    def dispatch(
        self,
        command: DesktopDispatchCommand,
        *,
        authority: object,
    ) -> BackendDispatchReceipt:
        _consume_authority(authority, command)
        self.attempt_count += 1
        receipt_ref = f"backend-receipt:{uuid4().hex}"
        if self._fail:
            return BackendDispatchReceipt(
                receipt_ref=receipt_ref,
                status="not_started",
                reason_code="backend_failed",
            )
        self.commands.append(command)
        self.dispatch_count += 1
        return BackendDispatchReceipt(
            receipt_ref=receipt_ref,
            status="dispatched",
            reason_code="none",
        )


class ExistingWindowsBackendAdapter:
    def __init__(
        self,
        *,
        input_controller: Any | None = None,
        window_manager: Any | None = None,
        post_dispatch_settle_seconds: float | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if post_dispatch_settle_seconds is not None and (
            isinstance(post_dispatch_settle_seconds, bool)
            or not isinstance(post_dispatch_settle_seconds, (int, float))
            or not math.isfinite(float(post_dispatch_settle_seconds))
            or float(post_dispatch_settle_seconds) < 0
        ):
            raise ValueError("post_dispatch_settle_seconds must be finite and nonnegative")
        if sleeper is not None and not callable(sleeper):
            raise TypeError("sleeper must be callable")
        if input_controller is None:
            from app.core.input_controller import InputController

            input_controller = InputController()
        if window_manager is None:
            from app.core.window_manager import window_manager as active_window_manager

            window_manager = active_window_manager
        self._input_controller = input_controller
        self._window_manager = window_manager
        self._post_dispatch_settle_seconds = (None if post_dispatch_settle_seconds is None
                                              else float(post_dispatch_settle_seconds))
        self._sleeper = sleeper or time.sleep

    def dispatch(
        self,
        command: DesktopDispatchCommand,
        *,
        authority: object,
    ) -> BackendDispatchReceipt:
        _consume_authority(authority, command)
        receipt_ref = f"backend-receipt:{uuid4().hex}"
        if command.taskbar_guard is None:
            try:
                bound = self._window_manager.get_bound_window()
            except Exception:
                bound = None
            if bound is None or int(bound.handle) != command.target_window_handle:
                return BackendDispatchReceipt(
                    receipt_ref=receipt_ref,
                    status="not_started",
                    reason_code="backend_failed",
                )
        else:
            bound = None
        spatial = command.scroll if command.scroll is not None else command.text_input
        if spatial is not None:
            rect = getattr(bound, "rect", None)
            if rect is None or (rect.right - rect.left, rect.bottom - rect.top) != spatial.viewport_size:
                return BackendDispatchReceipt(receipt_ref=receipt_ref, status="not_started", reason_code="backend_failed")
        try:
            from app.core.runtime_input_authority import _runtime_backend_input_scope

            with _runtime_backend_input_scope():
                if command.taskbar_guard is not None:
                    result = self._input_controller.activate_taskbar_item(
                        guard=command.taskbar_guard,
                    )
                elif command.scroll is not None:
                    parameters = command.scroll.parameters
                    result = self._input_controller.scroll_window(
                        direction=parameters.direction, wheel_clicks=parameters.wheel_clicks,
                        x=int(command.click_point[0]), y=int(command.click_point[1]),
                    )
                elif command.text_input is not None:
                    parameters = command.text_input.parameters
                    guarded = command.text_guard is not None
                    click_before_typing = parameters.reviewed.clear_existing if guarded else True
                    type_text_kwargs = {
                        "text": parameters.text,
                        "x": int(command.click_point[0]),
                        "y": int(command.click_point[1]),
                        "click_before_typing": click_before_typing,
                        "clear_existing": parameters.reviewed.clear_existing,
                        "submit": False,
                        "restore_clipboard": True,
                    }
                    if guarded:
                        type_text_kwargs["field_guard"] = command.text_guard
                    result = self._input_controller.type_text(**type_text_kwargs)
                else:
                    click_kwargs: dict[str, Any] = {}
                    if command.target_bbox is not None:
                        click_kwargs["target_bbox"] = command.target_bbox
                    if command.popup_guard is not None:
                        click_kwargs["popup_guard"] = command.popup_guard
                    result = self._input_controller.click_point(
                        int(command.click_point[0]),
                        int(command.click_point[1]),
                        **click_kwargs,
                    )
        except Exception:
            return BackendDispatchReceipt(
                receipt_ref=receipt_ref,
                status="indeterminate",
                reason_code="backend_result_lost",
            )
        if command.taskbar_guard is not None:
            expectation = command.taskbar_guard.expectation
            expected_window_point = {
                "x": expectation.window_point[0], "y": expectation.window_point[1]
            }
            expected_screen_point = {
                "x": expectation.screen_point[0], "y": expectation.screen_point[1]
            }
            if (
                not isinstance(result, dict)
                or result.get("clicked") is not True
                or result.get("activation_verified") is not True
                or result.get("taskbar_handle") != expectation.taskbar_handle
                or result.get("destination_handle") != expectation.destination_handle
                or result.get("window_point") != expected_window_point
                or result.get("screen_point") != expected_screen_point
                or result.get("capture_id") != expectation.capture_id
                or result.get("candidate_id") != expectation.candidate_id
                or result.get("source_sha256") != expectation.source_sha256
            ):
                return BackendDispatchReceipt(
                    receipt_ref=receipt_ref,
                    status="indeterminate",
                    reason_code="backend_result_lost",
                )
        elif command.scroll is not None:
            parameters = command.scroll.parameters
            expected_delta = 120 * parameters.wheel_clicks * (1 if parameters.direction == "up" else -1)
            if not isinstance(result, dict) or result.get("scrolled") is not True or result.get("direction") != parameters.direction or type(result.get("wheel_clicks")) is not int or result.get("wheel_clicks") != parameters.wheel_clicks or type(result.get("wheel_delta")) is not int or result.get("wheel_delta") != expected_delta or result.get("window_handle") != command.target_window_handle:
                return BackendDispatchReceipt(receipt_ref=receipt_ref, status="indeterminate", reason_code="backend_result_lost")
        elif command.text_input is not None:
            parameters = command.text_input.parameters
            if (
                not isinstance(result, dict) or result.get("typed") is not True
                or type(result.get("window_handle")) is not int or result.get("window_handle") != command.target_window_handle
                or type(result.get("text_length")) is not int or result.get("text_length") != len(parameters.text)
                or result.get("click_before_typing") is not (parameters.reviewed.clear_existing if command.text_guard is not None else True)
                or result.get("clear_existing") is not parameters.reviewed.clear_existing
                or result.get("submit") is not False or result.get("restore_clipboard") is not True
                or result.get("clipboard_restore_status") != "restored"
                or result.get("clipboard_verified_before_paste") is not True
            ):
                return BackendDispatchReceipt(receipt_ref=receipt_ref, status="indeterminate", reason_code="backend_result_lost")
        elif not isinstance(result, dict) or result.get("clicked") is not True:
            return BackendDispatchReceipt(
                receipt_ref=receipt_ref,
                status="not_started",
                reason_code="backend_failed",
            )
        # 正式 fresh/reviewed 路径共享动作后宽限；显式旧配置（包括零）保持原义。
        settle_seconds = (resolve_render_grace_ms(command.semantic_action) / 1000
            if self._post_dispatch_settle_seconds is None else self._post_dispatch_settle_seconds)
        if settle_seconds > 0:
            self._sleeper(settle_seconds)
        return BackendDispatchReceipt(
            receipt_ref=receipt_ref,
            status="dispatched",
            reason_code="none",
        )


__all__ = [
    "BackendDispatchReceipt",
    "DesktopBackend",
    "DesktopDispatchCommand",
    "DeterministicFakeBackend",
    "ExistingWindowsBackendAdapter",
    "FreshExecutionSourceLineage",
    "TaskbarExecutionSourceLineage",
]
