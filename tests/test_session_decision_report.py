"""宿主真实发布循环使用当前判断账本；桌面、进程采样和网络均为合成边界。"""
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from app.core import decision_configuration
from app.core import process_sampler
from app.core.json_snapshot import read_json_snapshot
from app.desktop_review import host, single_step_coordinator
from app.learning_memory import event_store
from app.judgment import DecisionService
from scripts import run_local_step_session as runner
from tests.test_adaptive_decision_policy import context
from tests.test_decision_choice import choice_reply, runtime
from tests.test_decision_service import arguments
from tests.test_luna_choice_review_provider import response_body


@pytest.mark.parametrize("scenario,used,unknown", [
    ("known6", 6, 0), ("ordinary", 2, 0), ("unknown", 1, 1), ("close_error", 1, 0), ("off", 0, 0),
])
def test_host_reports_current_budget_during_commands_and_after_close(tmp_path, monkeypatch, scenario, used, unknown):
    out = tmp_path / "session"
    reports, evaluations, calls, resources = [], [], [], []
    state = {}
    original_write = runner.write

    def create(session_dir, **kwargs):
        def handle(request):
            calls.append(request.url.path)
            return httpx.Response(200, json=response_body() if request.url.path == "/v1/responses"
                else choice_reply("condition_not_met" if scenario == "ordinary" else "condition_met"))
        service, _, client = runtime(session_dir, monkeypatch, handler=handle,
            profile={"request_cap": max(1, used), "ordinary_review": "on_reject",
                "mode": "off" if scenario == "off" else "auto"})
        decision_configuration.freeze_decision_profile(service)
        state.update(service=service, client=client)
        if scenario == "unknown":
            def interrupted(payload):
                raise KeyboardInterrupt()
            monkeypatch.setattr(service._provider, "judge", interrupted)
        if scenario == "close_error":
            def broken_close():
                raise OSError("synthetic close failure")
            monkeypatch.setattr(service._provider, "close", broken_close)
        return service

    def publish(path, payload):
        original_write(path, payload)
        if path.name == "report.json":
            reports.append(deepcopy(payload))
            if len(reports) == 1:
                original_write(out / "commands" / "01-discover.json", {"kind": "discover"})
                original_write(out / "commands" / "99-close.json", {"kind": "close"})

    class Coordinator:
        def __init__(self, *args, **kwargs):
            pass

        def set_automatic_safety_interception(self, value):
            assert value is False

        def set_keep_models_loaded(self, value):
            assert value is True

        def discover_applications(self):
            service = state["service"]
            for index in range(6 if scenario == "known6" else 1):
                args = arguments(out, request_id="report-judge-" + str(index), review_context=context())
                if scenario == "unknown":
                    with pytest.raises(KeyboardInterrupt):
                        service.evaluate(**args)
                else:
                    result = service.evaluate(**args)
                    if scenario != "off":
                        assert service.validate_result(result, **args)
                    evaluations.append((args, deepcopy(result)))
            if scenario != "off":
                limited = service.evaluate(**arguments(out, request_id="after-cap", review_context=context()))
                assert limited["status"] == "limited" and not limited["adopted"]
            return {"applications": []}

        def shutdown(self):
            assert state["service"].status()["closed"] is True
            resources.append("coordinator_closed")

    class Learning:
        def __init__(self, *args):
            pass

        def prepare(self, *args):
            return None

        def snapshot(self):
            return {"status": "disabled", "recording_enabled": False}

        status = snapshot

        def close(self):
            resources.append("learning_closed")

    fake_host = SimpleNamespace(facade=object(), start=lambda: None,
        close=lambda: resources.append("host_closed"), status=lambda: {"phase": "stopped"})
    monkeypatch.setattr(host, "DesktopReviewHost", lambda *args: fake_host)
    monkeypatch.setattr(single_step_coordinator, "NativeSingleStepCoordinator", Coordinator)
    monkeypatch.setattr(process_sampler, "ProcessSampler", lambda *args, **kwargs: SimpleNamespace(snapshot=lambda: {}))
    monkeypatch.setattr(event_store, "LearningEventStore", Learning)
    monkeypatch.setattr(decision_configuration, "create_session_decision_service", create)
    monkeypatch.setattr(runner, "write", publish)
    monkeypatch.setattr(runner, "initialize_session_resources", lambda *args, **kwargs: SimpleNamespace(mark_ready=lambda: None))
    import sys
    monkeypatch.setattr(sys, "argv", ["host", "--output", str(out), "--local-no-learning",
        "--recognition-source", "agent_current"])
    try:
        runner.main()
        final = read_json_snapshot(out / "report.json")
        live = next(row for row in reports if row["completed_commands"]
            and row["completed_commands"][-1]["name"] == "01-discover.json")
        assert reports[0]["decision_service"]["used"] == 0
        assert (live["decision_service"]["used"], live["decision_service"]["unknown_dispatches"]) == (used, unknown)
        assert live["decision_service"]["closed"] is False
        assert final["decision_service"] == state["service"].status()
        assert final["decision_service"]["closed"] is True
        assert final["decision_service"]["used"] == used
        assert final["decision_service"]["remaining"] == max(1, used) - used
        assert final["decision_service"]["unknown_dispatches"] == unknown
        assert final["phase"] == "stopped" and final["sampler_stopped"] is True
        assert resources == ["learning_closed", "coordinator_closed", "host_closed"]
        assert len(calls) == (0 if scenario in {"unknown", "off"} else used)
        reopened = DecisionService(out, profile=state["service"].profile)
        try:
            for args, original in evaluations:
                if scenario != "off":
                    assert reopened.validate_result(original, **args)
        finally:
            reopened.close()
        assert final["cleanup_errors"] == ([{"operation": "decision_service_close", "error_type": "OSError"}]
            if scenario == "close_error" else [])
    finally:
        if "client" in state:
            state["client"].close()
