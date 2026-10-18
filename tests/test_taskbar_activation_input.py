from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

import app.core.input_controller as input_module
from app.agent.taskbar_activation_guard import (
    TaskbarActivationExpectation,
    TaskbarActivationGuard,
)
from app.core.input_controller import InputController


def _evidence() -> dict:
    value = {
        "schema": "taskbar_activation_evidence_v1",
        "capture_id": "desktop-capture.current",
        "captured_at_monotonic": 100.0,
        "running_window_count": 1,
        "matched_button_count": 1,
        "taskbar": {
            "handle": 65980,
            "class_name": "Shell_TrayWnd",
            "pid": 14028,
            "exe": r"C:\Windows\explorer.exe",
            "create_time": 10.0,
            "screen_rect": {"left": 0, "top": 1040, "width": 2412, "height": 40},
        },
        "destination": {
            "handle": 70001,
            "pid": 501,
            "exe": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "create_time": 20.0,
            "title": "Edge",
        },
        "selected_button": {
            "control_type": "Button",
            "runtime_id": [42, 66094, 4, -2147483647, 66094, -4, 2],
            "control_id": "taskbar-edge",
            "toolbar_control_id": "task-list",
            "toolbar_handle": 66094,
            "toolbar_class_name": "MSTaskListWClass",
            "ancestor_control_ids": ["taskbar-root", "task-list"],
            "bbox": {"x": 339, "y": 0, "w": 161, "h": 40},
            "screen_bbox": {"x": 339, "y": 1040, "w": 161, "h": 40},
            "enabled": True,
            "visible": True,
            "patterns": ["Invoke"],
            "point_visibility": {
                "kind": "taskbar_button",
                "hit_handle": 65980,
                "hit_root_handle": 65980,
                "owner_handle": 65980,
            },
        },
        "window_point": [419, 20],
        "screen_point": [419, 1060],
        "desktop_rect": {"left": 0, "top": 0, "width": 2412, "height": 1080},
        "image_path": "desktop.png", "image_sha256": "a" * 64,
        "source_foreground": {"handle": 3345510, "pid": 600, "exe": r"C:\source.exe", "create_time": 30.0},
    }
    candidate = {
        key: value[key]
        for key in ("taskbar", "destination", "selected_button", "window_point", "screen_point")
    }
    value["candidate_id"] = _digest(candidate)
    value["source_sha256"] = _digest(value)
    return value


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _rehash(value: dict) -> dict:
    value.pop("source_sha256", None)
    value["candidate_id"] = _digest(
        {
            key: value[key]
            for key in ("taskbar", "destination", "selected_button", "window_point", "screen_point")
        }
    )
    value["source_sha256"] = _digest(value)
    return value


class _Reader:
    def __init__(self, snapshots: list[dict], *, destination_matches: bool = True) -> None:
        self.snapshots = snapshots
        self.reads = 0
        self.destination_reads = 0
        self.destination_matches = destination_matches

    def __call__(self) -> dict:
        index = min(self.reads, len(self.snapshots) - 1)
        self.reads += 1
        return self.snapshots[index]

    def read_destination_foreground(self) -> dict:
        self.destination_reads += 1
        destination = self.snapshots[0]["destination"]
        if not self.destination_matches:
            destination = {**destination, "handle": destination["handle"] + 1}
        return {**destination, "is_foreground": True}


def _guard(reader: _Reader, expectation: dict | None = None) -> TaskbarActivationGuard:
    return TaskbarActivationGuard(
        TaskbarActivationExpectation.from_dict(expectation or reader.snapshots[0]),
        reader,
        clock=lambda: 100.0,
    )


def _controller(monkeypatch, reader: _Reader, *, expectation: dict | None = None):
    controller = InputController()
    events: list[str] = []
    cursor = SimpleNamespace(value=(0, 0))
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(
        controller,
        "_focus_window",
        lambda *_: (_ for _ in ()).throw(AssertionError("taskbar must not be focused")),
    )
    monkeypatch.setattr(
        controller,
        "_require_bound_window",
        lambda: (_ for _ in ()).throw(AssertionError("taskbar must not be ordinarily bound")),
    )
    monkeypatch.setattr(input_module, "win32api", SimpleNamespace(GetCursorPos=lambda: cursor.value))

    def move(x, y):
        events.append("move")
        cursor.value = (x, y)

    monkeypatch.setattr(controller, "_send_move", move)
    monkeypatch.setattr(controller, "mouse_down", lambda button: events.append("down") or {"state": "down"})
    monkeypatch.setattr(controller, "mouse_up", lambda button: events.append("up") or {"state": "up"})
    monkeypatch.setattr(input_module, "TASKBAR_ACTIVATION_VERIFY_TIMEOUT_SECONDS", 0.0, raising=False)
    monkeypatch.setattr(input_module.time, "sleep", lambda _seconds: None)
    return controller, _guard(reader, expectation), events, cursor


def test_taskbar_input_revalidates_before_move_and_mouse_down_without_focus(monkeypatch) -> None:
    evidence = _evidence()
    reader = _Reader([evidence, evidence])
    controller, guard, events, _ = _controller(monkeypatch, reader)

    result = controller.activate_taskbar_item(guard=guard)

    assert events == ["move", "down", "up"]
    assert reader.reads == 2
    assert reader.destination_reads == 1
    assert result["clicked"] is True
    assert result["activation_verified"] is True
    assert result["taskbar_handle"] == 65980
    assert result["destination_handle"] == 70001
    assert result["window_point"] == {"x": 419, "y": 20}
    assert result["screen_point"] == {"x": 419, "y": 1060}


def test_taskbar_input_rejects_drift_before_move_or_down(monkeypatch) -> None:
    evidence = _evidence()
    drifted = deepcopy(evidence)
    drifted["selected_button"] = {**drifted["selected_button"], "runtime_id": [9, 9]}
    _rehash(drifted)

    reader = _Reader([drifted])
    controller, guard, events, _ = _controller(monkeypatch, reader, expectation=evidence)
    with pytest.raises(ValueError, match="drifted"):
        controller.activate_taskbar_item(guard=guard)
    assert events == []

    reader = _Reader([evidence, drifted])
    controller, guard, events, _ = _controller(monkeypatch, reader)
    with pytest.raises(ValueError, match="drifted"):
        controller.activate_taskbar_item(guard=guard)
    assert events == ["move"]


def test_taskbar_input_rejects_cursor_drift_before_down(monkeypatch) -> None:
    evidence = _evidence()
    reader = _Reader([evidence, evidence])
    controller, guard, events, cursor = _controller(monkeypatch, reader)
    original = controller._send_move

    def move_then_drift(x, y):
        original(x, y)
        cursor.value = (x + 1, y)

    monkeypatch.setattr(controller, "_send_move", move_then_drift)
    with pytest.raises(RuntimeError, match="cursor"):
        controller.activate_taskbar_item(guard=guard)
    assert events == ["move"]


def test_taskbar_input_attempts_release_when_mouse_down_fails(monkeypatch) -> None:
    evidence = _evidence()
    reader = _Reader([evidence, evidence])
    controller, guard, events, _ = _controller(monkeypatch, reader)

    def fail_down(_button):
        events.append("down")
        raise RuntimeError("down failed")

    monkeypatch.setattr(controller, "mouse_down", fail_down)
    with pytest.raises(RuntimeError, match="down failed"):
        controller.activate_taskbar_item(guard=guard)
    assert events == ["move", "down", "up"]


def test_taskbar_input_separates_click_from_unverified_activation_without_retry(monkeypatch) -> None:
    evidence = _evidence()
    reader = _Reader([evidence, evidence], destination_matches=False)
    controller, guard, events, _ = _controller(monkeypatch, reader)

    result = controller.activate_taskbar_item(guard=guard)

    assert events == ["move", "down", "up"]
    assert reader.destination_reads == 1
    assert result["clicked"] is True
    assert result["activation_verified"] is False
