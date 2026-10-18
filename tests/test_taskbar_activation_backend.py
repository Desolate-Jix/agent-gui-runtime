from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from app.agent.desktop_backend import (
    DesktopDispatchCommand,
    ExistingWindowsBackendAdapter,
    FreshExecutionSourceLineage,
    TaskbarExecutionSourceLineage,
    _mint_execution_authority,
)
from app.agent.scroll_parameters import ReviewedScrollParameters, ScrollDispatchParameters
from app.agent.taskbar_activation_guard import (
    TaskbarActivationExpectation,
    TaskbarActivationGuard,
)
from app.core.runtime_input_authority import runtime_backend_input_is_active


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


class _Reader:
    def __init__(self, evidence: dict | None = None) -> None:
        self.evidence = evidence or _evidence()

    def __call__(self) -> dict:
        return self.evidence

    def read_destination_foreground(self) -> dict:
        return {**self.evidence["destination"], "is_foreground": True}


def _guard() -> TaskbarActivationGuard:
    evidence = _evidence()
    return TaskbarActivationGuard(
        TaskbarActivationExpectation.from_dict(evidence),
        _Reader(evidence),
        clock=lambda: 100.0,
    )


def _command(guard: TaskbarActivationGuard | None = None) -> DesktopDispatchCommand:
    guard = guard or _guard()
    expectation = guard.expectation
    return DesktopDispatchCommand(
        semantic_action="taskbar_activate",
        capture_id=expectation.capture_id,
        candidate_id=expectation.candidate_id,
        click_point=expectation.window_point,
        target_window_handle=expectation.taskbar_handle,
        taskbar_guard=guard,
    )


def _authority(command: DesktopDispatchCommand, *, guard=None):
    taskbar_guard = command.taskbar_guard if guard is None else guard
    return _mint_execution_authority(
        session_id="session.taskbar",
        observation_id="observation.taskbar",
        intent_id="intent.taskbar",
        semantic_action=command.semantic_action,
        capture_id=command.capture_id,
        candidate_id=command.candidate_id,
        click_point=command.click_point,
        target_window_handle=command.target_window_handle,
        gate_decision_ref="gate.taskbar",
        taskbar_source_lineage=TaskbarExecutionSourceLineage(
            source_sha256=taskbar_guard.expectation.source_sha256,
            preview_sha256="b" * 64,
            confirmation_id="grounded-confirmation.taskbar",
            consume_content_sha256="c" * 64,
        ),
        taskbar_guard=taskbar_guard,
    )


def test_taskbar_command_requires_exact_guard_and_forbids_other_action_payloads() -> None:
    guard = _guard()
    with pytest.raises(ValueError, match="taskbar"):
        DesktopDispatchCommand(
            semantic_action="taskbar_activate",
            capture_id=guard.expectation.capture_id,
            candidate_id=guard.expectation.candidate_id,
            click_point=guard.expectation.window_point,
            target_window_handle=guard.expectation.taskbar_handle,
        )
    with pytest.raises(ValueError, match="taskbar"):
        DesktopDispatchCommand(
            semantic_action="open_detail",
            capture_id=guard.expectation.capture_id,
            candidate_id=guard.expectation.candidate_id,
            click_point=guard.expectation.window_point,
            target_window_handle=guard.expectation.taskbar_handle,
            taskbar_guard=guard,
        )
    with pytest.raises(ValueError, match="taskbar"):
        DesktopDispatchCommand(
            semantic_action="taskbar_activate",
            capture_id=guard.expectation.capture_id,
            candidate_id=guard.expectation.candidate_id,
            click_point=guard.expectation.window_point,
            target_window_handle=guard.expectation.taskbar_handle,
            taskbar_guard=guard,
            scroll=ScrollDispatchParameters(
                parameters=ReviewedScrollParameters(
                    "region", "vertical", "down", 1, "wheel_detent"
                ),
                target_bbox=(0, 0, 10, 10),
                viewport_size=(100, 100),
            ),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"capture_id": "other-capture"},
        {"candidate_id": "other-candidate"},
        {"click_point": (418, 20)},
        {"target_window_handle": 65981},
    ],
)
def test_taskbar_command_rejects_guard_identity_mismatch(changes: dict) -> None:
    guard = _guard()
    values = {
        "semantic_action": "taskbar_activate",
        "capture_id": guard.expectation.capture_id,
        "candidate_id": guard.expectation.candidate_id,
        "click_point": guard.expectation.window_point,
        "target_window_handle": guard.expectation.taskbar_handle,
        "taskbar_guard": guard,
    }
    values.update(changes)
    with pytest.raises(ValueError, match="taskbar"):
        DesktopDispatchCommand(**values)


def test_backend_binds_taskbar_guard_identity_and_skips_bound_window() -> None:
    command = _command()
    authority = _authority(command)
    calls: list[TaskbarActivationGuard] = []

    class SpyInput:
        def activate_taskbar_item(self, *, guard):
            assert runtime_backend_input_is_active() is True
            calls.append(guard)
            expected = guard.expectation
            return {
                "clicked": True,
                "activation_verified": True,
                "taskbar_handle": expected.taskbar_handle,
                "destination_handle": expected.destination_handle,
                "window_point": {"x": expected.window_point[0], "y": expected.window_point[1]},
                "screen_point": {"x": expected.screen_point[0], "y": expected.screen_point[1]},
                "capture_id": expected.capture_id,
                "candidate_id": expected.candidate_id,
                "source_sha256": expected.source_sha256,
            }

    windows = SimpleNamespace(
        get_bound_window=lambda: (_ for _ in ()).throw(
            AssertionError("taskbar activation must not require an ordinary bound window")
        )
    )
    adapter = ExistingWindowsBackendAdapter(input_controller=SpyInput(), window_manager=windows)
    swapped = _command(_guard())
    with pytest.raises(PermissionError, match="does not match"):
        adapter.dispatch(swapped, authority=authority)
    assert calls == []
    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    assert calls == [command.taskbar_guard]
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)


def test_taskbar_authority_rejects_reviewed_provenance() -> None:
    command = _command()
    with pytest.raises(ValueError, match="taskbar"):
        _mint_execution_authority(
            session_id="session.taskbar",
            observation_id="observation.taskbar",
            intent_id="intent.taskbar",
            workflow_revision_hash="b" * 64,
            semantic_action=command.semantic_action,
            selection_sha256="c" * 64,
            capture_id=command.capture_id,
            candidate_id=command.candidate_id,
            click_point=command.click_point,
            target_window_handle=command.target_window_handle,
            gate_decision_ref="gate.taskbar",
            taskbar_guard=command.taskbar_guard,
        )


def test_taskbar_authority_rejects_fresh_learning_provenance() -> None:
    command = _command()
    with pytest.raises(ValueError, match="taskbar"):
        _mint_execution_authority(
            session_id="session.taskbar",
            observation_id="observation.taskbar",
            intent_id="intent.taskbar",
            semantic_action=command.semantic_action,
            capture_id=command.capture_id,
            candidate_id=command.candidate_id,
            click_point=command.click_point,
            target_window_handle=command.target_window_handle,
            gate_decision_ref="gate.taskbar",
            source_lineage=FreshExecutionSourceLineage(
                source_sha256="a" * 64,
                approved_preview_sha256="b" * 64,
                fresh_preview_sha256="c" * 64,
                confirmation_id="grounded-confirmation.taskbar",
                consume_content_sha256="d" * 64,
            ),
            action_evidence_sha256="c" * 64,
            taskbar_guard=command.taskbar_guard,
        )


def test_taskbar_authority_rejects_source_lineage_not_bound_to_guard() -> None:
    command = _command()
    with pytest.raises(ValueError, match="source lineage"):
        _mint_execution_authority(
            session_id="session.taskbar",
            observation_id="observation.taskbar",
            intent_id="intent.taskbar",
            semantic_action=command.semantic_action,
            capture_id=command.capture_id,
            candidate_id=command.candidate_id,
            click_point=command.click_point,
            target_window_handle=command.target_window_handle,
            gate_decision_ref="gate.taskbar",
            taskbar_source_lineage=TaskbarExecutionSourceLineage(
                source_sha256="d" * 64,
                preview_sha256="b" * 64,
                confirmation_id="grounded-confirmation.taskbar",
                consume_content_sha256="c" * 64,
            ),
            taskbar_guard=command.taskbar_guard,
        )


@pytest.mark.parametrize(
    "bad_result",
    [
        {"activation_verified": False},
        {"destination_handle": 70002},
        {"taskbar_handle": 65981},
        {"screen_point": {"x": 420, "y": 1060}},
        {"candidate_id": "other-candidate"},
    ],
)
def test_backend_reports_unknown_after_click_without_retry(bad_result: dict) -> None:
    command = _command()
    calls = 0

    class SpyInput:
        def activate_taskbar_item(self, *, guard):
            nonlocal calls
            calls += 1
            expected = guard.expectation
            result = {
                "clicked": True,
                "activation_verified": True,
                "taskbar_handle": expected.taskbar_handle,
                "destination_handle": expected.destination_handle,
                "window_point": {"x": expected.window_point[0], "y": expected.window_point[1]},
                "screen_point": {"x": expected.screen_point[0], "y": expected.screen_point[1]},
                "capture_id": expected.capture_id,
                "candidate_id": expected.candidate_id,
                "source_sha256": expected.source_sha256,
            }
            result.update(bad_result)
            return result

    adapter = ExistingWindowsBackendAdapter(
        input_controller=SpyInput(),
        window_manager=SimpleNamespace(get_bound_window=lambda: None),
    )
    receipt = adapter.dispatch(command, authority=_authority(command))
    assert receipt.status == "indeterminate"
    assert receipt.reason_code == "backend_result_lost"
    assert calls == 1
