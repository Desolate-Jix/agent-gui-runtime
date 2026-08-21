from __future__ import annotations

import json

import pytest


class _BoundWindow:
    handle = 4242


class _WindowManager:
    def __init__(self, handle: int | None = 4242) -> None:
        self._handle = handle

    def get_bound_window(self):
        if self._handle is None:
            return None
        bound = _BoundWindow()
        bound.handle = self._handle
        return bound


def test_fake_backend_rejects_dispatch_without_internal_authority() -> None:
    from app.agent.desktop_backend import DesktopDispatchCommand, DeterministicFakeBackend

    backend = DeterministicFakeBackend()
    command = DesktopDispatchCommand(
        semantic_action="open_detail",
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
    )

    with pytest.raises(PermissionError, match="execution authority"):
        backend.dispatch(command, authority=None)

    assert backend.dispatch_count == 0


def test_fake_backend_consumes_private_authority_exactly_once() -> None:
    from app.agent.desktop_backend import (
        DesktopDispatchCommand,
        DeterministicFakeBackend,
        _mint_execution_authority,
    )

    backend = DeterministicFakeBackend()
    command = DesktopDispatchCommand(
        semantic_action="open_detail",
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
    )
    authority = _mint_execution_authority(
        session_id="session-1",
        observation_id="observation-1",
        intent_id="intent-1",
        selection_sha256="a" * 64,
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
        gate_decision_ref="gate:current",
    )

    first = backend.dispatch(command, authority=authority)
    assert first.status == "dispatched"
    assert backend.dispatch_count == 1
    with pytest.raises(PermissionError, match="already consumed"):
        backend.dispatch(command, authority=authority)
    assert backend.dispatch_count == 1


def test_internal_authority_is_not_json_serializable() -> None:
    from app.agent.desktop_backend import _mint_execution_authority

    authority = _mint_execution_authority(
        session_id="session-1",
        observation_id="observation-1",
        intent_id="intent-1",
        selection_sha256="a" * 64,
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
        gate_decision_ref="gate:current",
    )

    with pytest.raises(TypeError):
        json.dumps(authority)


def test_fake_backend_rejects_command_not_bound_to_authority() -> None:
    from app.agent.desktop_backend import (
        DesktopDispatchCommand,
        DeterministicFakeBackend,
        _mint_execution_authority,
    )

    backend = DeterministicFakeBackend()
    authority = _mint_execution_authority(
        session_id="session-1",
        observation_id="observation-1",
        intent_id="intent-1",
        selection_sha256="a" * 64,
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
        gate_decision_ref="gate:current",
    )
    forged = DesktopDispatchCommand(
        semantic_action="open_detail",
        capture_id="capture-current",
        candidate_id="candidate-forged",
        click_point=(1.0, 2.0),
        target_window_handle=9999,
    )

    with pytest.raises(PermissionError, match="does not match"):
        backend.dispatch(forged, authority=authority)

    assert backend.attempt_count == 0
    assert backend.dispatch_count == 0


def test_fake_backend_failure_confirms_no_dispatch() -> None:
    from app.agent.desktop_backend import (
        DesktopDispatchCommand,
        DeterministicFakeBackend,
        _mint_execution_authority,
    )

    backend = DeterministicFakeBackend(fail=True)
    command = DesktopDispatchCommand(
        semantic_action="open_detail",
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
    )
    authority = _mint_execution_authority(
        session_id="session-1",
        observation_id="observation-1",
        intent_id="intent-1",
        selection_sha256="a" * 64,
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
        gate_decision_ref="gate:current",
    )

    receipt = backend.dispatch(command, authority=authority)

    assert receipt.status == "not_started"
    assert receipt.reason_code == "backend_failed"
    assert backend.dispatch_count == 0
    assert backend.attempt_count == 1


def test_windows_backend_adapter_calls_existing_input_controller_once() -> None:
    from app.agent.desktop_backend import (
        DesktopDispatchCommand,
        ExistingWindowsBackendAdapter,
        _mint_execution_authority,
    )

    class SpyInputController:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []
            self.runtime_scopes: list[bool] = []

        def click_point(self, x: int, y: int) -> dict[str, object]:
            from app.core.runtime_input_authority import runtime_backend_input_is_active

            self.calls.append((x, y))
            self.runtime_scopes.append(runtime_backend_input_is_active())
            return {"clicked": True}

    input_controller = SpyInputController()
    backend = ExistingWindowsBackendAdapter(
        input_controller=input_controller,
        window_manager=_WindowManager(),
    )
    command = DesktopDispatchCommand(
        semantic_action="open_detail",
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
    )
    authority = _mint_execution_authority(
        session_id="session-1",
        observation_id="observation-1",
        intent_id="intent-1",
        selection_sha256="a" * 64,
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
        gate_decision_ref="gate:current",
    )

    receipt = backend.dispatch(command, authority=authority)

    assert receipt.status == "dispatched"
    assert input_controller.calls == [(220, 240)]
    assert input_controller.runtime_scopes == [True]


def test_windows_backend_exception_is_indeterminate_not_safe_to_retry() -> None:
    from app.agent.desktop_backend import (
        DesktopDispatchCommand,
        ExistingWindowsBackendAdapter,
        _mint_execution_authority,
    )

    class FailingInputController:
        def __init__(self) -> None:
            self.calls = 0

        def click_point(self, x: int, y: int) -> dict[str, object]:
            self.calls += 1
            raise RuntimeError("SendInput response lost")

    input_controller = FailingInputController()
    backend = ExistingWindowsBackendAdapter(
        input_controller=input_controller,
        window_manager=_WindowManager(),
    )
    command = DesktopDispatchCommand(
        semantic_action="open_detail",
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
    )
    authority = _mint_execution_authority(
        session_id="session-1",
        observation_id="observation-1",
        intent_id="intent-1",
        selection_sha256="a" * 64,
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
        gate_decision_ref="gate:current",
    )

    receipt = backend.dispatch(command, authority=authority)

    assert receipt.status == "indeterminate"
    assert receipt.reason_code == "backend_result_lost"
    assert input_controller.calls == 1


def test_windows_backend_rechecks_server_bound_window_before_input() -> None:
    from app.agent.desktop_backend import (
        DesktopDispatchCommand,
        ExistingWindowsBackendAdapter,
        _mint_execution_authority,
    )

    class SpyInputController:
        def __init__(self) -> None:
            self.calls = 0

        def click_point(self, x: int, y: int) -> dict[str, object]:
            self.calls += 1
            return {"clicked": True}

    input_controller = SpyInputController()
    backend = ExistingWindowsBackendAdapter(
        input_controller=input_controller,
        window_manager=_WindowManager(handle=9999),
    )
    command = DesktopDispatchCommand(
        semantic_action="open_detail",
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
    )
    authority = _mint_execution_authority(
        session_id="session-1",
        observation_id="observation-1",
        intent_id="intent-1",
        selection_sha256="a" * 64,
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(220.0, 240.0),
        target_window_handle=4242,
        gate_decision_ref="gate:current",
    )

    receipt = backend.dispatch(command, authority=authority)

    assert receipt.status == "not_started"
    assert receipt.reason_code == "backend_failed"
    assert input_controller.calls == 0
