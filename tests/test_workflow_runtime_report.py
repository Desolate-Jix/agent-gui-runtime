"""宿主报告只在运行时确实成功推进后清理旧错误。"""
from copy import deepcopy

import pytest


class Runtime:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def control(self, request, request_id):
        self.calls.append((request, request_id))
        if self.error is not None:
            raise self.error
        return deepcopy(self.result)


def _report():
    return {"workflow_run": {"runner_state": "waiting"},
            "workflow_runtime_error": {"error_type": "DesktopReviewError", "message": "old lock error"}}


@pytest.mark.parametrize("action", ["run", "continue"])
def test_successful_control_clears_stale_error_and_updates_run(action):
    from scripts.run_local_step_session import record_workflow_control
    report = _report()
    runtime = Runtime({"runner_state": "completed", "run_id": "trial-current"})
    result = record_workflow_control(report, runtime, {"action": action}, "control-original")
    assert result == {"runner_state": "completed", "run_id": "trial-current"}
    assert report["workflow_run"] == result
    assert "workflow_runtime_error" not in report
    assert runtime.calls == [({"action": action}, "control-original")]


@pytest.mark.parametrize("action", ["status", "cancel", "verify"])
def test_read_or_nonprogress_control_preserves_prior_error(action):
    from scripts.run_local_step_session import record_workflow_control
    report = _report()
    error = deepcopy(report["workflow_runtime_error"])
    runtime = Runtime({"runner_state": "waiting", "run_id": "trial-current"})
    record_workflow_control(report, runtime, {"action": action}, "control-original")
    assert report["workflow_runtime_error"] == error


def test_failed_control_does_not_clear_error_or_replace_run():
    from scripts.run_local_step_session import record_workflow_control
    report = _report()
    original = deepcopy(report)
    runtime = Runtime(error=ValueError("control failed"))
    with pytest.raises(ValueError, match="control failed"):
        record_workflow_control(report, runtime, {"action": "continue"}, "control-original")
    assert report == original


def test_successful_tick_snapshot_clears_stale_error():
    from scripts.run_local_step_session import record_workflow_snapshot
    report = _report()
    snapshot = {"runner_state": "completed", "run_id": "trial-current"}
    record_workflow_snapshot(report, snapshot, clear_error=True)
    assert report["workflow_run"] == snapshot
    assert "workflow_runtime_error" not in report
