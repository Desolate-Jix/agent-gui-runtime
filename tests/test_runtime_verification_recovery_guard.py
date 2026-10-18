"""直接核验入口不能在原结算后观察或写入。"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from app.learning_memory.runtime_verification import verify_trial_step

from tests.test_workflow_trial import services
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_recovery_control_guard import settled_scene


@pytest.mark.parametrize("request_id", ["verify-direct-after-settle", "settle-original"])
def test_direct_verification_rejects_persisted_settlement_before_all_effects(settled_scene, monkeypatch, request_id):
    scene, recovery, preview = settled_scene
    _, trials, run, session, ticket, _, _ = scene
    before = {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*") if p.is_file()}
    calls = []
    @contextmanager
    def workspace(root):
        yield trials.programs.library
    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    def forbidden(name):
        def operation(*args, **kwargs):
            calls.append(name)
            raise AssertionError("settled direct verification reached " + name)
        return operation
    for name, target in [("observation", "app.learning_memory.verification_observation.read_step_observation"),
                         ("artifact", "app.learning_memory.runtime_verification._write_immutable"),
                         ("metrics", "app.learning_memory.runtime_verification.record_rule_observation")]:
        monkeypatch.setattr(target, forbidden(name))
    coordinator = SimpleNamespace(_memory_library_root=trials.programs.library._workspace_root,
                                  _owner=SimpleNamespace(call=forbidden("owner")))
    with pytest.raises(ValueError, match="^workflow_runtime_recovery_paused$"):
        verify_trial_step(coordinator, session_dir=session, request={"action": "verify", "run_id": run["run_id"],
            "execution_request_id": ticket["execution_request_id"]}, request_id=request_id)
    assert calls == []
    assert before == {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*") if p.is_file()}
    assert recovery.preview(run["run_id"]) == preview


@pytest.mark.parametrize("original_id", [False, True])
def test_direct_prepare_rejects_before_pending_or_prior_write(settled_scene, original_id):
    scene, recovery, preview = settled_scene
    _, trials, run, session, _, _, _ = scene
    state = trials.status(run["run_id"])
    request_id = next(iter(state["prepare_requests"])) if original_id else "prepare-after-settle"
    prior = state["prepare_requests"].get(request_id)
    before = {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="^workflow_trial_recovery_paused$"):
        trials.prepare(run["run_id"], request_id)
    assert prior is not None if original_id else True
    assert trials.status(run["run_id"]) == state
    assert before == {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*") if p.is_file()}
    assert recovery.preview(run["run_id"]) == preview
