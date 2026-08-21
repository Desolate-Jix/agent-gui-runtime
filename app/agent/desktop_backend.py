"""W4 内部桌面执行 seam；不属于公开 Agent/Runtime Contract。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class DesktopDispatchCommand:
    semantic_action: str
    capture_id: str
    candidate_id: str
    click_point: tuple[float, float]
    target_window_handle: int

    def __post_init__(self) -> None:
        if not self.semantic_action or not self.capture_id or not self.candidate_id:
            raise ValueError("dispatch command requires semantic and current target identity")
        if len(self.click_point) != 2:
            raise ValueError("dispatch command requires one click point")
        if type(self.target_window_handle) is not int or self.target_window_handle <= 0:
            raise ValueError("dispatch command requires a positive server target window handle")


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


class _ExecutionAuthority:
    __slots__ = (
        "session_id",
        "observation_id",
        "intent_id",
        "selection_sha256",
        "capture_id",
        "candidate_id",
        "click_point",
        "target_window_handle",
        "gate_decision_ref",
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
        selection_sha256: str,
        capture_id: str,
        candidate_id: str,
        click_point: tuple[float, float],
        target_window_handle: int,
        gate_decision_ref: str,
    ) -> None:
        if mint_key is not _AUTHORITY_MINT_KEY:
            raise PermissionError("execution authority is controller-internal")
        self.session_id = session_id
        self.observation_id = observation_id
        self.intent_id = intent_id
        self.selection_sha256 = selection_sha256
        self.capture_id = capture_id
        self.candidate_id = candidate_id
        self.click_point = click_point
        self.target_window_handle = target_window_handle
        self.gate_decision_ref = gate_decision_ref
        self._consumed = False
        self._lock = Lock()

    def consume(self) -> None:
        with self._lock:
            if self._consumed:
                raise PermissionError("execution authority already consumed")
            self._consumed = True

    def __reduce__(self) -> object:
        raise TypeError("execution authority cannot be serialized")


def _mint_execution_authority(
    *,
    session_id: str,
    observation_id: str,
    intent_id: str,
    selection_sha256: str,
    capture_id: str,
    candidate_id: str,
    click_point: tuple[float, float],
    target_window_handle: int,
    gate_decision_ref: str,
) -> _ExecutionAuthority:
    return _ExecutionAuthority(
        _AUTHORITY_MINT_KEY,
        session_id=session_id,
        observation_id=observation_id,
        intent_id=intent_id,
        selection_sha256=selection_sha256,
        capture_id=capture_id,
        candidate_id=candidate_id,
        click_point=click_point,
        target_window_handle=target_window_handle,
        gate_decision_ref=gate_decision_ref,
    )


def _consume_authority(
    authority: object,
    command: DesktopDispatchCommand,
) -> _ExecutionAuthority:
    if not isinstance(authority, _ExecutionAuthority):
        raise PermissionError("valid execution authority is required")
    if (
        authority.capture_id != command.capture_id
        or authority.candidate_id != command.candidate_id
        or authority.click_point != command.click_point
        or authority.target_window_handle != command.target_window_handle
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
    ) -> None:
        if input_controller is None:
            from app.core.input_controller import InputController

            input_controller = InputController()
        if window_manager is None:
            from app.core.window_manager import window_manager as active_window_manager

            window_manager = active_window_manager
        self._input_controller = input_controller
        self._window_manager = window_manager

    def dispatch(
        self,
        command: DesktopDispatchCommand,
        *,
        authority: object,
    ) -> BackendDispatchReceipt:
        _consume_authority(authority, command)
        receipt_ref = f"backend-receipt:{uuid4().hex}"
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
        try:
            from app.core.input_controller import _runtime_backend_input_scope

            with _runtime_backend_input_scope():
                result = self._input_controller.click_point(
                    int(command.click_point[0]),
                    int(command.click_point[1]),
                )
        except Exception:
            return BackendDispatchReceipt(
                receipt_ref=receipt_ref,
                status="indeterminate",
                reason_code="backend_result_lost",
            )
        if not isinstance(result, dict) or result.get("clicked") is not True:
            return BackendDispatchReceipt(
                receipt_ref=receipt_ref,
                status="not_started",
                reason_code="backend_failed",
            )
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
]
