from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import app.core.input_controller as input_module
from app.agent.desktop_backend import (
    DesktopDispatchCommand,
    ExistingWindowsBackendAdapter,
    _mint_execution_authority,
)
from app.agent.popup_click_guard import PopupClickGuard, PopupTargetSnapshot
from app.agent.scroll_parameters import ReviewedScrollParameters, ScrollDispatchParameters
from app.core.input_controller import InputController


def target() -> PopupTargetSnapshot:
    return PopupTargetSnapshot(
        parent_handle=100,
        popup_handle=200,
        process_id=42,
        process_create_time=1.0,
        executable_path="c:/test/app.exe",
        thread_id=7,
        parent_rect=(0, 0, 800, 600),
        popup_rect=(20, 100, 220, 140),
        combo_name="Workflow",
        item_name="New workflow",
        combo_runtime_id=(1, 2),
        item_runtime_id=(1, 3),
        item_bbox=(2, 2, 196, 20),
        click_point=(100, 12),
    )


def guarded_command(guard: PopupClickGuard) -> tuple[DesktopDispatchCommand, object]:
    command = DesktopDispatchCommand(
        semantic_action="open_detail",
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(100, 12),
        target_window_handle=200,
        popup_guard=guard,
    )
    authority = _mint_execution_authority(
        session_id="session",
        observation_id="observation",
        intent_id="intent",
        workflow_revision_hash="a" * 64,
        semantic_action=command.semantic_action,
        selection_sha256="b" * 64,
        capture_id=command.capture_id,
        candidate_id=command.candidate_id,
        click_point=command.click_point,
        target_window_handle=command.target_window_handle,
        gate_decision_ref="gate",
        popup_guard=guard,
    )
    return command, authority


def test_guarded_command_rejects_wrong_action_and_mismatched_popup_target() -> None:
    snapshot = target()
    guard = PopupClickGuard(snapshot, lambda: snapshot)
    with pytest.raises(ValueError, match="popup"):
        DesktopDispatchCommand(
            semantic_action="open_apply_flow", capture_id="capture", candidate_id="candidate",
            click_point=snapshot.click_point, target_window_handle=snapshot.popup_handle, popup_guard=guard,
        )
    with pytest.raises(ValueError, match="popup"):
        DesktopDispatchCommand(
            semantic_action="open_detail", capture_id="capture", candidate_id="candidate",
            click_point=(101, 12), target_window_handle=snapshot.popup_handle, popup_guard=guard,
        )
    with pytest.raises(ValueError, match="popup"):
        DesktopDispatchCommand(
            semantic_action="scroll_region", capture_id="capture", candidate_id="candidate",
            click_point=snapshot.click_point, target_window_handle=snapshot.popup_handle,
            scroll=ScrollDispatchParameters(
                parameters=ReviewedScrollParameters("region", "vertical", "down", 1, "wheel_detent"),
                target_bbox=(0, 0, 200, 40), viewport_size=(200, 40),
            ),
            popup_guard=guard,
        )


def test_backend_binds_guard_by_identity_and_forwards_it_once() -> None:
    snapshot = target()
    guard = PopupClickGuard(snapshot, lambda: snapshot)
    command, authority = guarded_command(guard)

    class SpyInput:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, PopupClickGuard | None]] = []

        def click_point(self, x: int, y: int, *, popup_guard=None):
            self.calls.append((x, y, popup_guard))
            return {"clicked": True}

    bound = SimpleNamespace(handle=200, process_id=42, rect=SimpleNamespace(left=20, top=100, right=220, bottom=140))
    spy = SpyInput()
    adapter = ExistingWindowsBackendAdapter(input_controller=spy, window_manager=SimpleNamespace(get_bound_window=lambda: bound))
    swapped = replace(command, popup_guard=PopupClickGuard(snapshot, lambda: snapshot))
    with pytest.raises(PermissionError, match="does not match"):
        adapter.dispatch(swapped, authority=authority)
    assert spy.calls == []
    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    assert spy.calls == [(100, 12, guard)]
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)


def _controller_with_popup(monkeypatch, *, reader, after_move=None, forbid_focus=True):
    controller = InputController()
    events: list[str] = []
    bound = SimpleNamespace(
        handle=200, process_id=42, title="popup",
        rect=SimpleNamespace(left=20, top=100, right=220, bottom=140),
    )
    snapshot = target()
    guard = PopupClickGuard(snapshot, reader)
    state = SimpleNamespace(foreground=100, cursor=(0, 0))
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(
        controller, "_resolve_window_and_screen_point",
        lambda **kwargs: {"window_x": 100, "window_y": 12, "screen_x": 120, "screen_y": 112},
    )
    monkeypatch.setattr(input_module, "win32gui", SimpleNamespace(GetForegroundWindow=lambda: state.foreground))
    monkeypatch.setattr(input_module, "win32api", SimpleNamespace(GetCursorPos=lambda: state.cursor))
    if forbid_focus:
        monkeypatch.setattr(controller, "_focus_window", lambda handle: (_ for _ in ()).throw(AssertionError("popup must not be focused")))
    else:
        monkeypatch.setattr(controller, "_focus_window", lambda handle: True)

    def move(x, y):
        events.append("move")
        state.cursor = (x, y)
        if after_move is not None:
            after_move()

    monkeypatch.setattr(controller, "_send_move", move)
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        input_module.window_manager, "validate_bound_point_visibility",
        lambda **kwargs: {"allowed": True, "hit_window": {"root_handle": 200}},
    )
    monkeypatch.setattr(controller, "mouse_down", lambda button: events.append("down") or {"state": "down"})
    monkeypatch.setattr(controller, "mouse_up", lambda button: events.append("up") or {"state": "up"})
    monkeypatch.setattr(input_module.window_manager, "get_bound_window", lambda: bound)
    return controller, guard, events, state


def test_popup_click_accepts_parent_foreground_without_focusing_popup(monkeypatch) -> None:
    snapshot = target()
    reads: list[str] = []
    controller, guard, events, _ = _controller_with_popup(monkeypatch, reader=lambda: reads.append("read") or snapshot)

    result = controller.click_point(100, 12, popup_guard=guard, settle_ms=0, hold_ms=0)

    assert result["clicked"] is True
    assert result["foreground_before"] == 100
    assert events == ["move", "down", "up"]
    assert reads == ["read", "read"]


def test_parent_foreground_is_not_accepted_for_ordinary_click(monkeypatch) -> None:
    snapshot = target()
    controller, _, events, _ = _controller_with_popup(monkeypatch, reader=lambda: snapshot, forbid_focus=False)

    with pytest.raises(RuntimeError, match="Bound window changed"):
        controller.click_point(100, 12, settle_ms=0, hold_ms=0)
    assert events == ["move"]


def test_popup_drift_before_move_or_mouse_down_denies_without_down(monkeypatch) -> None:
    snapshot = target()
    stale = replace(snapshot, item_name="Other item")
    controller, guard, events, _ = _controller_with_popup(monkeypatch, reader=lambda: stale)
    with pytest.raises(ValueError, match="popup"):
        controller.click_point(100, 12, popup_guard=guard, settle_ms=0, hold_ms=0)
    assert events == []

    reads = [snapshot, stale]
    controller, guard, events, _ = _controller_with_popup(monkeypatch, reader=lambda: reads.pop(0))
    with pytest.raises(ValueError, match="popup"):
        controller.click_point(100, 12, popup_guard=guard, settle_ms=0, hold_ms=0)
    assert events == ["move"]


def test_popup_requires_exact_popup_root_from_normal_visibility_check(monkeypatch) -> None:
    snapshot = target()
    controller, guard, events, _ = _controller_with_popup(monkeypatch, reader=lambda: snapshot)
    monkeypatch.setattr(
        input_module.window_manager,
        "validate_bound_point_visibility",
        lambda **kwargs: {"allowed": True, "hit_window": {"root_handle": 999}},
    )

    with pytest.raises(input_module.TargetPointOccludedError, match="exact_popup_root"):
        controller.click_point(100, 12, popup_guard=guard, settle_ms=0, hold_ms=0)
    assert events == ["move"]


def test_popup_click_retains_release_attempt_when_mouse_down_fails(monkeypatch) -> None:
    snapshot = target()
    controller, guard, events, _ = _controller_with_popup(monkeypatch, reader=lambda: snapshot)

    def failing_down(button):
        events.append("down")
        raise RuntimeError("down failed")

    monkeypatch.setattr(controller, "mouse_down", failing_down)
    with pytest.raises(RuntimeError, match="down failed"):
        controller.click_point(100, 12, popup_guard=guard, settle_ms=0, hold_ms=0)
    assert events == ["move", "down", "up"]
