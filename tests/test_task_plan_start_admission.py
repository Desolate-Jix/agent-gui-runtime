"""拒绝新计划前不得持久化幽灵 ready；审核仍须原 wait 明确继续。"""
import pytest

from tests.test_task_plan_adaptive_review import adaptive_plan, OfflineAssessment, review_request
from tests.test_task_plan_contract import plan
from tests.test_task_plan_runner import scene, complete_original


def _snapshots(session):
    return {p.relative_to(session).as_posix(): p.read_bytes()
        for directory in ("task-plans", "task-plan-runners") for p in (session / directory).glob("*.json")}


@pytest.mark.parametrize("verdict,terminal", [("failure", "failed"), ("success", "completed")])
def test_rejected_start_after_terminal_review_creates_no_trial_and_next_start_recovers(tmp_path, monkeypatch, verdict, terminal):
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(count=1), decision=OfflineAssessment())
    original = complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    request = review_request(s, waiting, original)
    request.update(verdict=verdict, reason="The original evidence was inspected.")
    reviewed = s.runtime.control(request, "review-terminal")
    assert reviewed["status"] == terminal and reviewed["runner_state"] == "waiting"
    assert reviewed["wait"] == waiting["wait"]
    before = _snapshots(tmp_path)
    with pytest.raises(ValueError, match="^workflow_runner_session_active$"):
        s.runtime.control({"action": "start", "plan": plan(count=1)}, "rejected-before-continue")
    assert _snapshots(tmp_path) == before
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    continued = s.runtime.control({"action": "continue", "run_id": s.run_id,
        "wait_id": waiting["wait"]["wait_id"]}, "continue-terminal")
    assert continued["status"] == terminal and continued["runner_state"] == terminal
    assert continued["active_command_id"] is None and continued["wait_reason"] is None
    child = s.runtime.control({"action": "start", "plan": plan(count=1)}, "new-after-continue")
    assert child["run_id"] != s.run_id and child["wait_reason"] == "execution_pending"
    assert len(list(tmp_path.glob("commands/*.json"))) == 2


def test_old_start_replay_keeps_persisted_identity_while_another_plan_is_active(tmp_path, monkeypatch):
    first_plan = plan(count=1)
    s = scene(tmp_path, monkeypatch, source=first_plan)
    complete_original(s)
    assert s.runtime.tick(force=True)["runner_state"] == "completed"
    current = s.runtime.control({"action": "start", "plan": plan(count=1)}, "second-plan")
    active = s.runtime.runner._active_run()
    before = _snapshots(tmp_path)
    replayed = s.runtime.control({"action": "start", "plan": first_plan}, "plan-start")
    assert replayed["run_id"] == s.run_id and replayed["runner_state"] == "completed"
    assert s.runtime.runner._active_run() == active == current["run_id"]
    assert _snapshots(tmp_path) == before and len(list(tmp_path.glob("commands/*.json"))) == 2


def test_runner_lock_rejection_cannot_leave_a_new_ready_trial(tmp_path, monkeypatch):
    from contextlib import contextmanager
    s = scene(tmp_path, monkeypatch, source=plan(count=1))
    complete_original(s)
    assert s.runtime.tick(force=True)["runner_state"] == "completed"
    before = _snapshots(tmp_path)
    @contextmanager
    def busy(path):
        raise ValueError("workflow_runner_busy")
        yield
    monkeypatch.setattr("app.learning_memory.workflow_runner._exclusive", busy)
    with pytest.raises(ValueError, match="^workflow_runner_busy$"):
        s.runtime.control({"action": "start", "plan": plan(count=1)}, "runner-busy-start")
    assert _snapshots(tmp_path) == before
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
