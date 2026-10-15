"""真实定位提供者、组合输入和计划运行器共享取消事实；不接触桌面或外网。"""
from copy import deepcopy
from hashlib import sha256
import json
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.action_review import CANDIDATE_CONDITION
from app.execution.task_plan_admission import TaskPlanRuntime
from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from app.learning_memory.workflow_runtime import WorkflowRuntime
from app.vision.agent_command_jobs import AgentCommandJobs
from app.vision.external_grounding_api import ChatCompletionsGrounder
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from scripts.run_local_step_session import dispatch_agent_command
from tests.test_external_grounding_api import profile, reply, result


TARGET = {"handle": 11, "process_id": 22, "process_create_time": 33.0}
CONDITION = "The Google homepage is visible with its main search input."


def _plan():
    verification = {"kind": "agent_judgment", "decision_condition": CONDITION}
    return {"schema_version": "task_plan.v3", "title": "Open Google", "goal": "Open the Google homepage.",
        "inputs": {}, "steps": [{"step_id": "open_google", "action": {"kind": "input_sequence",
            "field_goal": "the browser address bar", "text": "https://www.google.com",
            "clear_existing": True, "submit_search": True}, "verification": verification}],
        "completion": {"step_id": "open_google", "verification": deepcopy(verification)}}


def _terminal(jobs, command_id):
    until = monotonic() + 3
    while monotonic() < until:
        value = jobs.get(command_id)
        if value["status"] in {"completed", "failed", "cancelled"}:
            jobs._jobs[command_id].thread.join(1)
            return value
        sleep(.005)
    pytest.fail("original job did not finish")


def test_cancel_during_real_grounder_preserves_zero_input_and_settles_original_plan(tmp_path, monkeypatch):
    for name in ("commands", "responses", "captures", "agent-commands"):
        (tmp_path / name).mkdir()
    image = tmp_path / "captures" / "fresh.png"
    Image.new("RGB", (100, 80), "white").save(image)
    capture = {"image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
        "capture_id": "fresh", "image_size": {"width": 100, "height": 80}, "window_identity": TARGET}
    monkeypatch.setenv("TEST_VISION_KEY", "synthetic-offline-only")
    monkeypatch.setenv("CANCEL_DECISION_TEST_KEY", "synthetic-offline-only")
    entered, release = Event(), Event()
    http_calls, native_calls, decision_calls = [], [], []

    def handle(request):
        http_calls.append(request)
        context = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        entered.set()
        assert release.wait(3)
        found = result()
        found.update(request_id=context["request_id"], capture_id=context["capture_id"])
        return httpx.Response(200, json=reply(found))

    def forbidden_decision(request):
        decision_calls.append(request)
        pytest.fail("cancelled grounding must not issue a Decision")

    def forbidden_native(**kwargs):
        native_calls.append(kwargs)
        pytest.fail("cancelled grounding must not dispatch native input")

    decision_client = httpx.Client(transport=httpx.MockTransport(forbidden_decision))
    decision = DecisionService(tmp_path, profile=DecisionProfile.model_validate({
        "contract_version": "decision_profile.v2", "mode": "auto", "decision_format": "choice",
        "ordinary_review": "on_reject", "api_key_env": "CANCEL_DECISION_TEST_KEY",
        "auto_conditions": [CANDIDATE_CONDITION, CONDITION]}),
        provider=OpenAIDecisionsProvider(api_key_env="CANCEL_DECISION_TEST_KEY", client=decision_client))
    co = SimpleNamespace(_owner=SimpleNamespace(call=lambda fn: fn()), _decision_service=decision,
        _memory_library_root=tmp_path / "unused-learning", execute_local_step=forbidden_native)
    store = GroundingHandoffStore(tmp_path, owner_id="cancel-owner")
    grounder = ChatCompletionsGrounder(profile(timeout_seconds=5), transport=httpx.MockTransport(handle))
    jobs = AgentCommandJobs(co, store, lambda: deepcopy(capture),
        RecognitionSourceConfig(source="external_api", api_profile="synthetic-profile.json"), api_grounder=grounder)
    reviewed = WorkflowRuntime(tmp_path, co, agent_jobs=jobs)
    runtime = TaskPlanRuntime(tmp_path, co, owner_id=store.owner_id, target_identity=lambda: deepcopy(TARGET),
        reviewed_runtime=reviewed, agent_jobs=jobs)
    try:
        admitted = runtime.control({"action": "start", "plan": _plan()}, "start-original")
        run_id, command_id = admitted["run_id"], admitted["active_command_id"]
        command = read_json_snapshot(tmp_path / "commands" / (command_id + ".json"))
        initial = dispatch_agent_command(jobs, command_id, command, {"handle": 11, "process_id": 22})
        original_receipt = {"status": "returned", "command": command, "result": initial}
        receipt_path = tmp_path / "responses" / (command_id + ".json")
        write_json_snapshot(receipt_path, original_receipt)
        assert entered.wait(2)
        frontier = jobs.get(command_id)
        ag_id = frontier["api_request"]["request_id"]
        assert frontier["api_request"]["phase"] == "requesting"
        assert frontier["action_executed"] is False and frontier["dispatch_attempts"] == []
        assert frontier["dispatch_in_progress"] is False
        cancelled = runtime.control({"action": "cancel", "run_id": run_id}, "cancel-original")
        assert cancelled["status"] == "cancel_requested"
        release.set()
        terminal = _terminal(jobs, command_id)
        assert len(terminal["recognition_calls"]) == 1 and len(http_calls) == 1
        call = terminal["recognition_calls"][0]
        assert call["request_id"] == ag_id
        assert call["provider"]["usage"]["total_tokens"] == 50
        assert call["attempt"]["usage"] == {"input_tokens": 30, "output_tokens": 20, "total_tokens": 50}
        assert native_calls == decision_calls == []
        final = runtime.tick(force=True)
        assert (final["runner_state"], terminal["action_executed"]) == ("cancelled", False)
        assert final["status"] == "cancelled" and final["pending"] is None
        assert terminal["status"] == "cancelled" and terminal["dispatch_attempts"] == []
        assert terminal["dispatch_in_progress"] is False and terminal["last_execution"] is None
        assert len(final["history"]) == 1
        row = final["history"][0]
        assert row["execution_request_id"] == command_id and row["verdict"] == "cancelled"
        assert row["action_executed"] is False and row["original_input_status"] == "failed"
        assert read_json_snapshot(receipt_path) == original_receipt
        for i in range(2):
            assert runtime.control({"action": "status", "run_id": run_id}, "status-" + str(i))["history"] == final["history"]
        next_run = runtime.control({"action": "start", "plan": _plan()}, "start-next")
        assert next_run["run_id"] != run_id and next_run["active_command_id"] != command_id
        assert len(http_calls) == 1 and native_calls == decision_calls == []
    finally:
        release.set()
        jobs.close()
        grounder.close()
        decision.close()
        decision_client.close()


def _native_jobs(tmp_path, coordinator):
    # 桌面模块只在测试主线程导入；工作线程仅使用下面的合成边界。
    from app.execution import local_direct_step  # noqa: F401
    image = tmp_path / "fresh.png"
    Image.new("RGB", (100, 80), "white").save(image)
    capture = {"image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
        "window_identity": {"handle": 1, "process_id": 2, "process_create_time": 100.0}}
    coordinator._owner = SimpleNamespace(call=lambda fn: fn())
    return AgentCommandJobs(coordinator, GroundingHandoffStore(tmp_path, owner_id="prefix-owner"),
        lambda: deepcopy(capture), RecognitionSourceConfig(source="agent_current"))


def _resume_sequence(jobs):
    from tests.test_agent_command_jobs import _found, _wait
    jobs.start("prefix-job", {"kind": "input_sequence", "request": {
        "field_goal": "Search", "text": "maps", "submit_search": True}},
        {"handle": 1, "process_id": 2}, {"image_transport": "supported", "current_vision": "supported"})
    pending = _wait(jobs, "prefix-job", "awaiting_grounding")["pending_grounding"]
    jobs.store.resolve(pending["request_id"], _found(pending))
    jobs.resume("prefix-job", pending["request_id"], "prefix-execution")
    return _terminal(jobs, "prefix-job")


def test_cancel_before_next_input_preserves_real_completed_dispatch_prefix(tmp_path, monkeypatch):
    from app.execution import input_sequence as sequence
    from tests.test_input_sequence import Coordinator, snapshots
    co = Coordinator()
    snapshots(monkeypatch, [""])
    read = sequence._read_field
    jobs = _native_jobs(tmp_path, co)

    def cancel_after_read(*args, **kwargs):
        value = read(*args, **kwargs)
        jobs.cancel("prefix-job")
        return value

    monkeypatch.setattr(sequence, "_read_field", cancel_after_read)
    try:
        terminal = _resume_sequence(jobs)
        assert terminal["status"] == "cancelled" and terminal["result"] is None
        assert terminal["action_executed"] is True
        assert [row["status"] for row in terminal["dispatch_attempts"]] == ["returned"]
        assert terminal["dispatch_attempts"][0]["action_executed"] is True
        assert terminal["last_execution"]["receipt"] == terminal["progress"]["steps"][0]["receipt"]
        assert terminal["progress"]["completed_steps"] == ["focus"]
        assert terminal["progress"]["steps"][-1]["name"] == "type"
        assert terminal["dispatch_in_progress"] is False
        assert len(co.calls) == 1
        assert jobs.get("prefix-job") == terminal and len(co.calls) == 1
    finally:
        jobs.close()


def test_typed_cancel_after_dispatch_started_preserves_unknown_atomic_fact(tmp_path):
    from app.core.vision_admission_contract import AgentCommandCancelled
    from tests.test_input_sequence import Coordinator
    co = Coordinator()
    jobs = _native_jobs(tmp_path, co)

    def interrupted(**kwargs):
        co.calls.append(kwargs)
        jobs.cancel("prefix-job")
        raise AgentCommandCancelled("agent_command_cancelled")

    co.execute_local_step = interrupted
    try:
        terminal = _resume_sequence(jobs)
        assert terminal["status"] == "cancelled" and terminal["result"] is None
        assert terminal["action_executed"] is None
        assert terminal["dispatch_attempts"][0]["status"] == "unknown"
        assert terminal["dispatch_attempts"][0]["action_executed"] is None
        assert terminal["dispatch_in_progress"] is False and terminal["last_execution"] is None
        assert jobs.get("prefix-job") == terminal and len(co.calls) == 1
    finally:
        jobs.close()


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_same_message_and_false_attribute_do_not_prove_zero_input(tmp_path, error_type):
    from tests.test_input_sequence import Coordinator
    co = Coordinator()
    jobs = _native_jobs(tmp_path, co)

    def interrupted(**kwargs):
        co.calls.append(kwargs)
        jobs.cancel("prefix-job")
        error = error_type("agent_command_cancelled")
        error.action_executed = False
        raise error

    co.execute_local_step = interrupted
    try:
        terminal = _resume_sequence(jobs)
        assert terminal["status"] == "cancelled" and terminal["action_executed"] is None
        assert terminal["result"]["status"] == "interrupted"
        assert terminal["result"]["steps"][0]["status"] == "result_unknown"
        assert terminal["result"]["action_executed"] is None
        assert terminal["result"]["error"]["type"] == error_type.__name__
        assert terminal["dispatch_attempts"][0]["status"] == "unknown"
        assert jobs.get("prefix-job") == terminal and len(co.calls) == 1
    finally:
        jobs.close()


@pytest.mark.parametrize("field", [
    {"kind": "text", "field_goal": "Name", "text": "Ada"},
    {"kind": "date", "field_goal": "Date", "value": "2026-10-15", "format": "YYYY-MM-DD"},
    {"kind": "checkbox", "label": "Remember", "checked": True},
])
def test_form_fill_cancel_at_grounding_handoff_preserves_original_zero_dispatch(tmp_path, monkeypatch, field):
    from tests.test_agent_command_jobs import _wait
    from tests.test_form_fill import Coordinator, control, reader
    co = Coordinator()
    reader(monkeypatch, control())
    jobs = _native_jobs(tmp_path, co)
    try:
        jobs.start("form-cancel", {"kind": "form_fill", "request": {"fields": [field,
            {"kind": "text", "field_goal": "Next field", "text": "never"}]}},
            {"handle": 1, "process_id": 2}, {"image_transport": "supported", "current_vision": "supported"})
        waiting = _wait(jobs, "form-cancel", "awaiting_grounding")
        assert waiting["dispatch_attempts"] == [] and waiting["action_executed"] is False
        jobs.cancel("form-cancel")
        terminal = _terminal(jobs, "form-cancel")
        assert terminal["status"] == "cancelled" and terminal["result"] is None
        assert terminal["action_executed"] is False and terminal["dispatch_attempts"] == []
        assert terminal["dispatch_in_progress"] is False and terminal["last_execution"] is None
        assert len(terminal["progress"]["fields"]) == 1
        assert co.calls == [] and jobs.get("form-cancel") == terminal
    finally:
        jobs.close()
