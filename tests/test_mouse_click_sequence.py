from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.core.input_controller as input_module
from app.core.input_controller import InputController


def _prepared(monkeypatch):
    controller = InputController()
    bound = SimpleNamespace(handle=7, title="Browser", process_id=11,
                            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600))
    events = []
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_resolve_window_and_screen_point",
                        lambda **kwargs: {"window_x": 10, "window_y": 20, "screen_x": 110, "screen_y": 120})
    monkeypatch.setattr(input_module.win32gui, "GetForegroundWindow", lambda: 7)
    monkeypatch.setattr(input_module.win32api, "GetCursorPos", lambda: (110, 120))
    monkeypatch.setattr(controller, "_focus_window", lambda handle: events.append(("focus", handle)) or True)
    monkeypatch.setattr(controller, "_send_move", lambda x, y: events.append(("move", x, y)))
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(input_module.window_manager, "get_bound_window", lambda: bound)
    monkeypatch.setattr(input_module.window_manager, "validate_bound_point_visibility",
                        lambda **kwargs: {"allowed": True, "hit_window": {"root_handle": 7}})
    monkeypatch.setattr(controller, "mouse_down", lambda button: events.append(("down", button)) or {"state": "down"})
    monkeypatch.setattr(controller, "mouse_up", lambda button: events.append(("up", button)) or {"state": "up"})
    return controller, bound, events


def test_click_count_rejects_bool_and_values_other_than_one_or_two(monkeypatch):
    controller = InputController()
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    for value in (True, False, 0, 3, 1.0, "2"):
        with pytest.raises(ValueError):
            controller.click_point(1, 2, click_count=value)


def test_double_click_uses_one_focus_and_move_and_two_press_release_sequences(monkeypatch):
    controller, _, events = _prepared(monkeypatch)
    monkeypatch.setattr(input_module.ctypes.windll.user32, "GetDoubleClickTime", lambda: 500)

    result = controller.click_point(10, 20, click_count=2, settle_ms=0, hold_ms=60)

    assert result["clicked"] is True
    assert result["click_count"] == 2
    assert len(result["click_events"]) == 2
    assert [event[0] for event in events].count("focus") == 1
    assert [event[0] for event in events].count("move") == 1
    assert [event[0] for event in events].count("down") == 2
    assert [event[0] for event in events].count("up") == 2


def test_double_click_stops_before_second_press_when_bound_identity_changes(monkeypatch):
    controller, bound, events = _prepared(monkeypatch)
    monkeypatch.setattr(input_module.ctypes.windll.user32, "GetDoubleClickTime", lambda: 500)
    calls = {"count": 0}
    def changing_bound():
        calls["count"] += 1
        if calls["count"] >= 2:
            return SimpleNamespace(handle=99, title="Other", process_id=12, rect=bound.rect)
        return bound
    monkeypatch.setattr(input_module.window_manager, "get_bound_window", changing_bound)
    with pytest.raises(RuntimeError) as exc_info:
        controller.click_point(10, 20, click_count=2, settle_ms=0, hold_ms=0)
    assert [event[0] for event in events].count("down") == 1
    assert [event[0] for event in events].count("up") == 1
    assert getattr(exc_info.value, "completed_click_count", None) == 1
    assert "partial" in str(exc_info.value).lower() or "second" in str(exc_info.value).lower()


def test_double_click_reports_dispatch_interval_not_requested_sleep(monkeypatch):
    controller, _, _ = _prepared(monkeypatch)
    monkeypatch.setattr(input_module.ctypes.windll.user32, "GetDoubleClickTime", lambda: 500)
    times = iter((1_000_000_000, 1_650_000_000))
    monkeypatch.setattr(controller, "mouse_down", lambda button: {
        "state": "down", "dispatched_monotonic_ns": next(times)})
    result = controller.click_point(10, 20, click_count=2, settle_ms=0, hold_ms=60)
    assert result["double_click_dispatch_interval_ms"] == 650
    assert result["double_click_within_system_interval"] is False


