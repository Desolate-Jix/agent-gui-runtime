"""学习票据只经既有输入路由传到 owner；测试不操作桌面。"""

from contextlib import contextmanager
from copy import deepcopy
from threading import Condition
from types import SimpleNamespace

import pytest

from app.desktop_review import input_sequence
from app.desktop_review.local_direct_step import LocalDirectStepMixin
from app.vision.agent_command_jobs import _CoordinatorProxy, _Job
from scripts.run_local_step_session import dispatch_agent_command, run_step_command


CONTEXT = {"event_id": "outer-1", "command_sha256": "a" * 64}
TARGET = {"handle": 1, "process_id": 2}


def test_plain_and_learning_step_only_pass_context_when_ticket_exists():
    calls = []
    co = SimpleNamespace(execute_local_step=lambda **kwargs: calls.append(kwargs) or {})
    command = {"kind": "step", "operation": "press_key", "request": {"key": "Enter"}}
    run_step_command(co, TARGET, command)
    assert "learning_context" not in calls[-1]
    run_step_command(co, TARGET, command, learning_context=CONTEXT)
    assert calls[-1]["learning_context"] == CONTEXT


def test_input_sequence_focus_uses_outer_context_and_plain_command_has_none(monkeypatch):
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return {"phase": "returned", "capture": {"sha256": "b" * 64},
                "response": {"success": True, "data": {"result": {"action_executed": True,
                    "selected_click_point": {"x": 1, "y": 2}}}},
                "observation": {"status": "captured", "capture": {"sha256": "c" * 64}}}

    def stop_read(*_args, **_kwargs):
        raise ValueError("stop_after_focus")

    monkeypatch.setattr(input_sequence, "_read_field", stop_read)
    co = SimpleNamespace(execute_local_step=execute)
    request = {"field_goal": "Search", "text": "q", "submit_search": False}
    input_sequence.run_input_sequence(co, TARGET, request, learning_context=CONTEXT)
    assert calls[0]["operation"] == "execute_recognition_plan"
    assert calls[0]["learning_context"] == CONTEXT
    calls.clear()
    input_sequence.run_input_sequence(co, TARGET, request)
    assert "learning_context" not in calls[0]


def test_agent_dispatch_freezes_ticket_and_later_plain_job_has_no_context():
    calls = []
    jobs = SimpleNamespace(start=lambda *args, **kwargs: calls.append((args, kwargs)) or {"status": "running"})
    command = {"kind": "step", "operation": "execute_recognition_plan",
               "request": {"goal": "Target"}, "vision_capabilities": {}}
    dispatch_agent_command(jobs, "outer-1", command, TARGET, learning_context=CONTEXT)
    assert calls[-1][1]["learning_context"] == CONTEXT
    dispatch_agent_command(jobs, "outer-2", command, TARGET)
    assert "learning_context" not in calls[-1][1]

    receipt = {"phase": "returned", "response": {"success": True}, "observation": {}}
    inputs = []
    manager = SimpleNamespace(_condition=Condition(), _snapshots={"outer-1": {"action_executed": False}},
        coordinator=SimpleNamespace(execute_local_step=lambda **kwargs: inputs.append(deepcopy(kwargs)) or receipt),
        _update=lambda *_args, **_kwargs: None,
        _begin_dispatch=lambda *_args: 0, _record_unknown=lambda *_args: None,
        _record_receipt=lambda *_args: None)
    source = dict(CONTEXT)
    job = _Job(manager, "outer-1", command, TARGET, None, learning_context=source)
    source["event_id"] = "mutated"
    _CoordinatorProxy(job).execute_local_step(operation="type_text", request={"text": "q"},
        learning_context={"event_id": "injected", "command_sha256": "bad"})
    assert inputs[-1]["learning_context"] == CONTEXT
    manager._snapshots["outer-2"] = {"action_executed": False}
    plain = _Job(manager, "outer-2", command, TARGET, None)
    _CoordinatorProxy(plain).execute_local_step(operation="type_text", request={"text": "q"})
    assert "learning_context" not in inputs[-1]


def test_owner_scope_wraps_original_route_only_for_learning(monkeypatch):
    from app.learning_memory import learning_observation_capture as capture
    entered = []

    @contextmanager
    def scope(coordinator, context):
        entered.append((coordinator, deepcopy(context), "enter"))
        try:
            yield
        finally:
            entered.append((coordinator, deepcopy(context), "exit"))

    monkeypatch.setattr(capture, "learning_capture_scope", scope)

    class Coordinator(LocalDirectStepMixin):
        def _perform_local_step_on_owner(self, *_args):
            entered.append((self, None, "route"))
            return {"phase": "returned"}

    co = Coordinator()
    co._execute_local_step_on_owner(1, 2, "press_key", {"key": "Enter"},
        timing_context={}, learning_context=CONTEXT)
    assert [row[2] for row in entered] == ["enter", "route", "exit"]
    entered.clear()
    co._execute_local_step_on_owner(1, 2, "press_key", {"key": "Enter"}, timing_context={})
    assert [row[2] for row in entered] == ["route"]


def test_owner_failure_clears_real_learning_scope_before_plain_call(monkeypatch):
    from app.learning_memory import learning_observation_capture as capture
    observations = []

    def unexpected_capture(*_args, **_kwargs):
        pytest.fail("plain call must not capture learning evidence")

    monkeypatch.setattr(capture, "capture_memory_observation", unexpected_capture)

    class Coordinator(LocalDirectStepMixin):
        def _perform_local_step_on_owner(self, *_args):
            observations.append(capture.learning_capture_active())
            if len(observations) == 1:
                assert capture.observe_learning_target(image_path=None, candidate=None,
                    click_point=None)["event_id"] == CONTEXT["event_id"]
                raise RuntimeError("owner_route_failed")
            assert capture.observe_learning_target(image_path="current.png", candidate={},
                click_point={}) is None
            return {"phase": "returned"}

    co = Coordinator()
    assert capture.learning_capture_active() is False
    with pytest.raises(RuntimeError, match="owner_route_failed"):
        co._execute_local_step_on_owner(1, 2, "press_key", {"key": "Enter"},
            timing_context={}, learning_context=CONTEXT)
    assert capture.learning_capture_active() is False
    assert co._execute_local_step_on_owner(1, 2, "press_key", {"key": "Enter"},
        timing_context={})["phase"] == "returned"
    assert observations == [True, False]
    assert capture.learning_capture_active() is False
