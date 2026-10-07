"""宿主在短库锁之外读取原生结果，再按原回执记账。"""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_workflow_verified_trial import setup_run
from tests.test_workflow_trial import services


@pytest.mark.parametrize("available", [True, False])
def test_runtime_verification_reads_once_and_never_dispatches(services, monkeypatch, available):
    trials, run, ticket, _, envelope = setup_run(services)
    library = services[0].library
    held = []
    @contextmanager
    def workspace(root):
        held.append(True)
        try: yield library
        finally: held.pop()
    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    calls = []
    def observe(coordinator, **kwargs):
        assert not held
        calls.append(kwargs)
        return {"status": "ok" if available else "unavailable", "reason": None if available else "uia_unavailable",
                "frame": deepcopy(envelope["frame"]), "scope_id": "current-query", "source": "uia_value",
                "complete": available, "values": {"field_value": "new"} if available else {}, "evidence": {}}
    monkeypatch.setattr("app.learning_memory.verification_observation.read_step_observation", observe)
    def no_input(**kwargs): raise AssertionError("verification dispatched input")
    co = SimpleNamespace(_memory_library_root=library._workspace_root,
                         _owner=SimpleNamespace(call=lambda f: f()), execute_local_step=no_input)
    from app.learning_memory.runtime_verification import verify_trial_step
    request = {"action": "verify", "run_id": run["run_id"], "execution_request_id": ticket["execution_request_id"]}
    result = verify_trial_step(co, session_dir=trials.session, request=request, request_id="verify-native")
    assert len(calls) == 1
    assert result["status"] == ("ready" if available else "paused_uncertain")
    assert result["outputs"] == ({"search.result_title": "new"} if available else {})
    assert result["history"][0]["judged_by"] == "rule"
    assert verify_trial_step(co, session_dir=trials.session, request=request, request_id="verify-native") == result
    assert len(calls) == 1
    from app.learning_memory.measurement import load_events, summarize_run
    events = load_events(trials.session, run["run_id"])
    assert len(events) == 1
    assert events[0]["source"] == "native_observation"
    assert events[0]["status"] == ("success" if available else "waiting")
    assert events[0]["ended_ns"] >= events[0]["started_ns"] > 0
    assert summarize_run(events)["model_calls"]["total"] == 0


def test_verification_cannot_rebind_during_another_input_step(services, monkeypatch):
    trials, run, ticket, _, envelope = setup_run(services)
    library = services[0].library
    @contextmanager
    def workspace(root):
        yield library
    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    calls = []
    monkeypatch.setattr("app.learning_memory.verification_observation.read_step_observation",
                        lambda *args, **kwargs: calls.append(True))
    co = SimpleNamespace(_memory_library_root=library._workspace_root,
                         _owner=SimpleNamespace(call=lambda f: f()))
    from app.core.local_input_policy import _local_operator_step_scope
    from app.learning_memory.runtime_verification import verify_trial_step
    with _local_operator_step_scope(), pytest.raises(PermissionError, match="another local step"):
        verify_trial_step(co, session_dir=trials.session, request={"action": "verify",
            "run_id": run["run_id"], "execution_request_id": ticket["execution_request_id"]},
            request_id="verify-busy")
    assert calls == []
