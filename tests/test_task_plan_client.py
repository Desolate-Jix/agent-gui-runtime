"""临时计划客户端只在替身 MCP 边界回读，不启动宿主或输入。"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

import scripts.learning_benchmark_client as module
from scripts.learning_benchmark_client import LearningBenchmarkClient
from app.core.instant_attachment_transport import InstantAdmissionError, InstantAttachmentTransport


RUN_ID = "workflow-run-" + "a" * 32
PLAN_ID = "task-plan-" + "b" * 64
TARGET = {"handle": 7, "pid": 9, "process_creation_time": 11.0}
COMMAND = {"kind": "task_plan", "request": {"action": "start", "plan": {
    "schema_version": "task_plan.v1", "title": "Open then inspect", "inputs": {},
    "steps": [{"step_id": step, "action": {"kind": "click", "goal": step},
               "verification": {"kind": "native_condition",
                                "condition": {"text": step, "control_type": "Text"}}}
              for step in ("first", "second")]}}}


def snapshot(*, completed=0, reason="execution_pending", command_id="input-first"):
    terminal = completed == 2
    step = "second" if completed else "first"
    history = [{"step_id": name, "execution_request_id": execution, "verdict": "success",
                "judged_by": "native_condition", "evidence_refs": {"after_sha256": "c" * 64}}
               for name, execution in (("first", "input-first"), ("second", "input-second"))[:completed]]
    wait = None if terminal else {"wait_id": "wait-" + step + "-" + reason,
        "reason": reason, "run_id": RUN_ID, "step_id": step, "command_id": command_id}
    return {"schema": "task_plan_trial.v1", "source_kind": "caller_plan",
        "run_id": RUN_ID, "plan_id": PLAN_ID, "plan_sha256": "d" * 64,
        "start_request_id": "original-start", "session_directory": "fresh-session", "owner_id": "owner",
        "target_identity": deepcopy(TARGET), "status": "completed" if terminal else "pending",
        "runner_state": "completed" if terminal else "waiting", "mode": "until_wait",
        "current_step_id": None if terminal else step,
        "active_command_id": None if terminal else command_id, "wait_reason": None if terminal else reason,
        "wait": wait, "pending": None if terminal else {"step_id": step,
            "execution_request_id": command_id, "suggested_command": {"text": "PRIVATE INPUT"}},
        "history": history, "inputs": {"secret": "PRIVATE INPUT"}, "prepare_requests": {"large": "map"},
        "metrics": {"source_kind": "caller_plan", "run_id": RUN_ID, "planned_steps": 2,
            "settled_steps": completed, "successful_steps": completed, "measurement_status": "not_collected"}}


def receipt(request_id, state):
    return {"request_id": request_id, "status": "returned", "operation_success_scope": "task_plan_control",
        "command_wall_ms": 4.25, "result": deepcopy(state)}


class Session:
    def __init__(self, states, *, pending_start=0, pending_status=0):
        self.states = list(states)
        self.calls = []
        self.pending_start = pending_start
        self.pending_status = pending_status
        self.pending_id = None
        self.pending_action = None

    async def call_tool(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name == "instant_run":
            action = args["command"]["request"]["action"]
            if ((action == "start" and self.pending_start) or
                    (action == "status" and self.pending_status)):
                self.pending_id = args["request_id"]
                self.pending_action = action
                value = {"request_id": self.pending_id, "status": "pending", "command_cancelled": False}
            else:
                value = receipt(args["request_id"], self.states.pop(0))
        elif name == "instant_result":
            assert args["request_id"] == self.pending_id
            if self.pending_action == "start":
                self.pending_start -= 1
                remaining = self.pending_start
            else:
                self.pending_status -= 1
                remaining = self.pending_status
            value = ({"request_id": args["request_id"], "status": "pending", "command_cancelled": False}
                     if remaining else
                     receipt(args["request_id"], self.states.pop(0)))
        elif name == "instant_status":
            if self.pending_status:
                self.pending_status -= 1
                state = None
            else:
                state = self.states.pop(0)
            value = {"phase": "ready", "host_alive": True, "task_plan_run": deepcopy(state)}
        else:
            raise AssertionError("unexpected tool: " + name)
        return type("ToolResult", (), {"structuredContent": value, "is_error": False})()


def client(tmp_path, session, *, allow_actions=True):
    opened = LearningBenchmarkClient(root=Path(__file__).resolve().parents[1],
        data_root=tmp_path / "data", evidence_dir=tmp_path / "evidence", allow_actions=allow_actions,
        poll_interval=.01)
    opened._session = session
    return opened


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        assert seconds > 0
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(module, "monotonic", clock.monotonic)
    monkeypatch.setattr(module.asyncio, "sleep", clock.sleep)
    return clock


def test_multistep_plan_follows_original_run_without_main_callback(tmp_path, clock):
    session = Session([snapshot(), snapshot(completed=1, command_id="input-second"), snapshot(completed=2)])
    events = []
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=events.append, total_timeout=1))
    assert result["client_state"] == "terminal" and result["result"]["status"] == "completed"
    assert result["original_request_id"] == "original-start" and result["run_id"] == RUN_ID
    assert [name for name, args in session.calls] == ["instant_run", "instant_status", "instant_status"]
    assert session.calls[0][1]["command"]["request"]["action"] == "start"
    assert result["current_status"]["run_id"] == RUN_ID and result["status_source"] == "instant_status"
    assert events == [] and clock.sleeps == []
    assert [ref["arguments"]["request_id"] for ref in result["execution_receipts"]] == ["input-first", "input-second"]
    assert "PRIVATE INPUT" not in str(result)


def test_ready_result_is_returned_without_fixed_client_sleep(tmp_path, clock):
    session = Session([snapshot(completed=2)])
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=None, total_timeout=1))
    assert result["client_state"] == "terminal" and clock.sleeps == []
    assert len(session.calls) == 1


def test_pending_polls_original_id_only(tmp_path, clock):
    session = Session([snapshot(), snapshot(completed=2)], pending_start=2, pending_status=2)
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=None, total_timeout=1))
    assert result["result"]["status"] == "completed"
    submits = [args for name, args in session.calls if name == "instant_run"]
    reads = [args["request_id"] for name, args in session.calls if name == "instant_result"]
    assert reads == ["original-start", "original-start"]
    assert len(submits) == 1 and len(clock.sleeps) == 4


def test_grounding_event_delivered_once_per_bound_wait_request(tmp_path, clock):
    state = snapshot(reason="grounding_required")
    state["wait"]["pending_grounding"] = {"contract_version": "grounding_handoff.v1",
        "request_id": "grounding-original", "phase": "awaiting_grounding", "goal": "Open first",
        "capture": {"capture_id": "capture-original", "image_path": "original.png", "sha256": "c" * 64,
            "image_size": [800, 600], "window_identity": deepcopy(TARGET), "capture_timings": {"total_ms": 8}},
        "output_schema": {"large": "schema"}, "requires_live_revalidation": True}
    session = Session([state, state, state])
    opened = client(tmp_path, session)
    events = []
    async def scenario():
        first = await opened.run_plan("original-start", COMMAND, event_callback=events.append, total_timeout=1)
        for request_id in ("status-one", "status-two"):
            await opened.run_plan(request_id, {"kind": "task_plan", "request": {"action": "status", "run_id": RUN_ID}},
                event_callback=events.append, total_timeout=1)
        return first
    result = asyncio.run(scenario())
    assert result["client_state"] == "grounding_required" and len(events) == 1
    event = events[0]
    assert event["wait_id"] == "wait-first-grounding_required" and event["command_id"] == "input-first"
    assert event["grounding"]["request_id"] == "grounding-original"
    assert event["grounding"]["capture"]["image_path"] == "original.png"
    assert event["grounding"]["capture"]["capture_timings"]["total_ms"] == 8
    assert event["images"][0] == {"tool": "instant_image", "arguments": {"request_id": "input-first", "view": "after"}}
    assert "PRIVATE INPUT" not in str(event) and "output_schema" not in str(event)
    assert all(args["command"]["request"]["action"] in {"start", "status"} for name, args in session.calls)


def test_new_grounding_request_on_same_wait_gets_its_own_event(tmp_path, clock):
    state = snapshot(reason="grounding_required")
    state["wait"]["pending_grounding"] = {"request_id": "grounding-first", "capture": {
        "capture_id": "capture-first", "image_path": "first.png", "sha256": "c" * 64}}
    changed = deepcopy(state)
    changed["wait"]["pending_grounding"].update(request_id="grounding-second", capture={
        "capture_id": "capture-second", "image_path": "second.png", "sha256": "e" * 64})
    session = Session([state, changed])
    opened = client(tmp_path, session)
    events = []
    async def scenario():
        await opened.run_plan("original-start", COMMAND, event_callback=events.append, total_timeout=1)
        return await opened.run_plan("status-one", {"kind": "task_plan", "request": {"action": "status", "run_id": RUN_ID}},
            event_callback=events.append, total_timeout=1)
    asyncio.run(scenario())
    assert [event["grounding"]["request_id"] for event in events] == ["grounding-first", "grounding-second"]


def test_async_callback_returns_handoff_without_implicit_continue(tmp_path, clock):
    session = Session([snapshot(reason="verification_required")])
    events = []
    async def callback(event):
        events.append(event)
        return {"action": "continue", "run_id": RUN_ID, "wait_id": event["wait_id"]}
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=callback, total_timeout=1))
    assert result["client_state"] == "verification_required" and len(events) == 1
    assert len(session.calls) == 1 and events[0]["timing"]["command_wall_ms"] == 4.25


def test_timeout_retains_latest_run_when_host_projection_has_not_refreshed(tmp_path, clock):
    state = snapshot(completed=1, command_id="input-second")
    session = Session([state], pending_status=100)
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=None, total_timeout=.025))
    queries = [args for name, args in session.calls if name == "instant_run"]
    assert result["client_state"] == "pending" and result["run_id"] == RUN_ID
    assert result["active_command_id"] == "input-second" and result["wait_id"] == "wait-second-execution_pending"
    assert result["current_status_request_id"] is None
    assert result["start_receipt"]["arguments"]["request_id"] == "original-start"
    assert result["next"] == {"tool": "instant_status", "arguments": {}}
    assert result["no_replay"] is True and result["automatic_retry_allowed"] is False
    assert not any(name == "instant_result" for name, args in session.calls)
    assert [args["command"]["request"]["action"] for args in queries] == ["start"]


@pytest.mark.parametrize("outer_status", ["result_unknown", "not_found"])
def test_unknown_original_receipt_never_retries_or_cancels(tmp_path, outer_status):
    session = Session([])
    async def unknown(name, args):
        session.calls.append((name, deepcopy(args)))
        return type("ToolResult", (), {"structuredContent": {"request_id": args["request_id"],
            "status": outer_status, "automatic_retry_allowed": False}, "is_error": False})()
    session.call_tool = unknown
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=None, total_timeout=1))
    assert result["client_state"] == "result_unknown" and result["status"] == outer_status
    assert result["original_request_id"] == "original-start"
    assert result["next"]["arguments"]["request_id"] == "original-start" and len(session.calls) == 1


def test_transport_timeout_keeps_submitted_original_without_replay(tmp_path):
    session = Session([])
    async def hung(name, args):
        session.calls.append((name, deepcopy(args)))
        await asyncio.Event().wait()
    session.call_tool = hung
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=None, total_timeout=.01))
    assert result["client_state"] == "pending" and result["status"] == "result_unknown"
    assert result["next"]["arguments"]["request_id"] == "original-start" and len(session.calls) == 1
    assert result["command_cancelled"] is False


def test_explicit_cancellation_returns_original_facts_without_future_input(tmp_path, clock):
    state = snapshot(completed=1, command_id="input-second")
    state.update(status="cancel_requested", runner_state="cancel_requested")
    cancelled = deepcopy(state)
    cancelled.update(status="cancelled", runner_state="cancelled", wait=None, wait_reason=None,
                     pending=None, active_command_id=None)
    session = Session([state, cancelled])
    result = asyncio.run(client(tmp_path, session).run_plan("cancel-control", {
        "kind": "task_plan", "request": {"action": "cancel", "run_id": RUN_ID}},
        event_callback=None, total_timeout=1))
    assert result["client_state"] == "terminal" and result["result"]["status"] == "cancelled"
    assert result["result"]["history"][0]["execution_request_id"] == "input-first"
    assert [args["command"]["request"]["action"] for name, args in session.calls if name == "instant_run"] == ["cancel"]
    assert session.calls[-1][0] == "instant_status"


@pytest.mark.parametrize("change", [
    {"run_id": "another-run"}, {"plan_id": "another-plan"}, {"plan_sha256": "e" * 64},
    {"target_identity": {"handle": 8, "pid": 9, "process_creation_time": 11.0}},
    {"source_kind": "reviewed_program"}, {"schema": "unknown.v1"},
    {"runner_state": "completed"},
])
def test_malformed_or_cross_run_status_never_claims_completion(tmp_path, clock, change):
    malformed = snapshot(completed=2)
    malformed.update(change)
    if change == {"runner_state": "completed"}:
        malformed["status"] = "pending"
    session = Session([snapshot(), malformed])
    with pytest.raises(ValueError, match="benchmark_task_plan"):
        asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
            event_callback=None, total_timeout=1))
    assert len(session.calls) == 2


def test_grounding_wait_cannot_switch_execution_identity(tmp_path):
    state = snapshot(reason="grounding_required")
    state["wait"]["command_id"] = "other-input"
    session = Session([state])
    with pytest.raises(ValueError, match="benchmark_task_plan"):
        asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
            event_callback=None, total_timeout=1))


def test_read_only_status_is_allowed_but_start_and_continue_remain_gated(tmp_path):
    session = Session([snapshot(completed=2)])
    opened = client(tmp_path, session, allow_actions=False)
    async def scenario():
        with pytest.raises(ValueError, match="read_only"):
            await opened.run_plan("original-start", COMMAND, event_callback=None, total_timeout=1)
        with pytest.raises(ValueError, match="read_only"):
            await opened.run_plan("continue-control", {"kind": "task_plan", "request": {
                "action": "continue", "run_id": RUN_ID, "wait_id": "original-wait"}},
                event_callback=None, total_timeout=1)
        return await opened.run_plan("status-read", {"kind": "task_plan", "request": {"action": "status", "run_id": RUN_ID}},
            event_callback=None, total_timeout=1)
    assert asyncio.run(scenario())["client_state"] == "terminal"
    assert len(session.calls) == 1


def test_unchanged_running_state_uses_bounded_waits_instead_of_busy_poll(tmp_path, clock):
    session = Session([snapshot()] * 10)
    events = []
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=events.append, total_timeout=.025))
    assert result["client_state"] == "pending" and len(events) == 1
    assert len(session.calls) == 4 and clock.sleeps == pytest.approx([.01, .01, .005])
    assert result["result"]["runner_state"] == "waiting" and result["wait_reason"] == "execution_pending"
    assert result["next"] == {"tool": "instant_status", "arguments": {}}


def test_zero_wait_budget_still_submits_once_and_retains_original_pending(tmp_path, clock):
    session = Session([snapshot()], pending_start=1)
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=None, total_timeout=0))
    assert result["client_state"] == "pending" and result["request_id"] == "original-start"
    assert result["next"]["arguments"]["request_id"] == "original-start"
    assert len(session.calls) == 1 and session.calls[0][1]["wait_ms"] == 0 and clock.sleeps == []


@pytest.mark.parametrize("change", [
    {"active_command_id": "unfinished-input"}, {"metrics": {"planned_steps": 2, "successful_steps": 1}},
])
def test_completion_cannot_keep_an_active_ticket_or_unverified_step(tmp_path, change):
    state = snapshot(completed=2)
    state.update(change)
    session = Session([state])
    with pytest.raises(ValueError, match="benchmark_task_plan"):
        asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
            event_callback=None, total_timeout=1))


def test_grounding_wait_requires_original_request_and_capture_before_callback(tmp_path):
    state = snapshot(reason="grounding_required")
    state["wait"]["pending_grounding"] = {"request_id": "grounding-original"}
    session = Session([state])
    events = []
    with pytest.raises(ValueError, match="benchmark_task_plan"):
        asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
            event_callback=events.append, total_timeout=1))
    assert events == []


def test_status_cannot_replace_original_ticket_before_settlement(tmp_path, clock):
    session = Session([snapshot(), snapshot(command_id="replacement-input")])
    with pytest.raises(ValueError, match="benchmark_task_plan"):
        asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
            event_callback=None, total_timeout=1))


def test_timeout_preserves_reported_cancellation_and_partial_facts(tmp_path, clock):
    session = Session([])
    async def pending(name, args):
        session.calls.append((name, deepcopy(args)))
        return type("ToolResult", (), {"structuredContent": {"request_id": args["request_id"],
            "status": "pending", "command_cancelled": True, "partial_execution": True}, "is_error": False})()
    session.call_tool = pending
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=None, total_timeout=0))
    assert result["client_state"] == "pending" and result["command_cancelled"] is True
    assert result["partial_execution"] is True and len(session.calls) == 1


def test_waiting_state_without_bound_wait_is_not_a_normal_poll(tmp_path):
    state = snapshot()
    state.update(wait=None, wait_reason=None)
    session = Session([state])
    with pytest.raises(ValueError, match="benchmark_task_plan"):
        asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
            event_callback=None, total_timeout=1))


def test_pending_control_preserves_requested_run_before_first_receipt(tmp_path, clock):
    session = Session([], pending_status=1)
    result = asyncio.run(client(tmp_path, session).run_plan("status-control", {
        "kind": "task_plan", "request": {"action": "status", "run_id": RUN_ID}},
        event_callback=None, total_timeout=0))
    assert result["run_id"] == RUN_ID and result["client_state"] == "pending"
    assert result["current_status_request_id"] == "status-control"
    assert result["next"]["arguments"]["request_id"] == "status-control"


def test_pending_control_retains_last_bound_plan_and_wait_on_same_connection(tmp_path, clock):
    session = Session([snapshot(reason="verification_required")], pending_status=1)
    opened = client(tmp_path, session)
    async def scenario():
        await opened.run_plan("original-start", COMMAND, event_callback=None, total_timeout=1)
        return await opened.run_plan("status-control", {"kind": "task_plan", "request": {"action": "status", "run_id": RUN_ID}},
            event_callback=None, total_timeout=0)
    result = asyncio.run(scenario())
    assert result["run_id"] == RUN_ID and result["plan_id"] == PLAN_ID and result["client_state"] == "pending"
    assert result["active_command_id"] == "input-first" and result["wait_id"] == "wait-first-verification_required"
    assert result["start_receipt"]["arguments"]["request_id"] == "original-start"


def test_runtime_error_projection_is_handoff_not_terminal_plan(tmp_path, clock):
    session = Session([snapshot()])
    original = session.call_tool
    async def failed_query(name, args):
        if name == "instant_status":
            session.calls.append((name, deepcopy(args)))
            return type("ToolResult", (), {"structuredContent": {"phase": "ready", "host_alive": True,
                "task_plan_run": snapshot(), "task_plan_runtime_error": {"error_type": "ValueError", "message": "status read failed"}},
                "is_error": False})()
        return await original(name, args)
    session.call_tool = failed_query
    events = []
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=events.append, total_timeout=1))
    assert result["client_state"] == "runtime_error" and len(events) == 1
    assert result["result"]["status"] == "pending" and result["active_command_id"] == "input-first"
    assert len(session.calls) == 2 and result["automatic_retry_allowed"] is False


def test_real_transport_pending_input_does_not_abort_plan_status_following(tmp_path, clock):
    transport = InstantAttachmentTransport(tmp_path, tmp_path / "runtime")
    transport.session = transport.data_root / ("session-" + "f" * 32)
    transport._host_alive = lambda: True
    for folder in ("commands", "responses"):
        (transport.session / folder).mkdir(parents=True)
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    write(transport.session / "report.json", {"phase": "ready", "task_plan_run": snapshot()})
    calls, rejections, events = [], [], []
    class AdmissionSession:
        async def call_tool(self, name, args):
            calls.append((name, deepcopy(args)))
            if name == "instant_run":
                try:
                    transport.submit(args["request_id"], args["command"])
                except InstantAdmissionError as error:
                    rejected = {"request_id": args["request_id"], "status": "state_rejected",
                        "accepted": False, "action_executed": False, "automatic_retry_allowed": False,
                        "error": {"code": error.code, "message": str(error)}, "next": error.next}
                    rejections.append(rejected)
                    return type("ToolResult", (), {"structuredContent": rejected, "is_error": True})()
                write(transport._path(args["request_id"], "responses"), receipt(args["request_id"], snapshot()))
                transport.submit("input-first", {"kind": "capture"})
                value = transport.result(args["request_id"])
            elif name == "instant_status":
                value = transport.status()
                write(transport.session / "report.json", {"phase": "ready", "task_plan_run": snapshot(completed=2)})
            elif name == "instant_result":
                value = transport.result(args["request_id"])
            else:
                raise AssertionError(name)
            return type("ToolResult", (), {"structuredContent": value, "is_error": False})()
    opened = client(tmp_path, AdmissionSession())
    result = asyncio.run(opened.run_plan("original-start", COMMAND, event_callback=events.append, total_timeout=1))
    assert result["client_state"] == "terminal" and result["result"]["status"] == "completed"
    assert events == []
    assert sum(name == "instant_run" and args["command"]["request"]["action"] == "start" for name, args in calls) == 1
    assert sum(name == "instant_status" for name, args in calls) >= 2
    assert set(path.stem for path in (transport.session / "commands").glob("*.json")) == {"original-start", "input-first"}


def test_real_runtime_transport_projection_completes_original_two_step_plan(tmp_path, clock, monkeypatch):
    from tests.test_task_plan_runner import complete_original, scene
    transport = InstantAttachmentTransport(tmp_path, tmp_path / "runtime")
    transport.session = transport.data_root / ("session-" + "f" * 32)
    transport._host_alive = lambda: True
    for folder in ("commands", "responses"):
        (transport.session / folder).mkdir(parents=True)
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    write(transport.session / "report.json", {"phase": "ready"})
    calls, originals, events = [], [], []
    class RuntimeSession:
        async def call_tool(self, name, args):
            calls.append((name, deepcopy(args)))
            if name == "instant_run":
                transport.submit(args["request_id"], args["command"])
                self.runtime = scene(transport.session, monkeypatch, source=args["command"]["request"]["plan"])
                write(transport._path(args["request_id"], "responses"), {
                    **receipt(args["request_id"], self.runtime.first), "command": deepcopy(args["command"])})
                write(transport.session / "report.json", {"phase": "ready", "task_plan_run": self.runtime.first})
                value = transport.result(args["request_id"])
            elif name == "instant_status":
                value = transport.status()
                if self.runtime.runtime.backend.status(self.runtime.run_id)["pending"] is not None:
                    original = complete_original(self.runtime, async_receipt=len(originals) == 1)
                    originals.append(original.command_id)
                    fresh = self.runtime.runtime.tick(force=True)
                    write(transport.session / "report.json", {"phase": "ready", "task_plan_run": fresh})
            else:
                raise AssertionError(name)
            return type("ToolResult", (), {"structuredContent": value, "is_error": False})()
    opened = client(tmp_path, RuntimeSession())
    result = asyncio.run(opened.run_plan("plan-start", COMMAND, event_callback=events.append, total_timeout=1))
    assert result["client_state"] == "terminal" and result["result"]["status"] == "completed" and events == []
    assert len(originals) == 2 and [row["execution_request_id"] for row in result["result"]["history"]] == originals
    assert [row["judged_by"] for row in result["result"]["history"]] == ["native_condition", "native_condition"]
    assert [name for name, args in calls] == ["instant_run", "instant_status", "instant_status", "instant_status"]
    assert set(path.stem for path in (transport.session / "commands").glob("*.json")) == {"plan-start", *originals}
    assert not (transport.session / "absent-learning").exists()


def test_dead_host_projection_never_claims_completed_plan(tmp_path, clock):
    session = Session([snapshot()])
    original = session.call_tool
    async def died(name, args):
        if name == "instant_status":
            session.calls.append((name, deepcopy(args)))
            return type("ToolResult", (), {"structuredContent": {"phase": "host_exited_without_cleanup_proof",
                "host_alive": False, "task_plan_run": snapshot(completed=2)}, "is_error": False})()
        return await original(name, args)
    session.call_tool = died
    events = []
    result = asyncio.run(client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=events.append, total_timeout=1))
    assert result["client_state"] == "result_unknown" and len(events) == 1
    assert result["host_status"]["host_alive"] is False and result["run_id"] == RUN_ID
    assert result["next"] == {"tool": "instant_status", "arguments": {}}


def test_initial_control_rejection_preserves_original_id_and_admission_hint(tmp_path):
    session = Session([])
    async def rejected(name, args):
        session.calls.append((name, deepcopy(args)))
        return type("ToolResult", (), {"structuredContent": {"request_id": args["request_id"],
            "status": "state_rejected", "accepted": False, "action_executed": False,
            "error": {"code": "command_pending", "message": "original input pending"},
            "next": {"tool": "instant_result", "arguments": {"request_id": "original-input"}}}, "is_error": True})()
    session.call_tool = rejected
    result = asyncio.run(client(tmp_path, session).run_plan("status-control", {
        "kind": "task_plan", "request": {"action": "status", "run_id": RUN_ID}},
        event_callback=None, total_timeout=1))
    assert result["client_state"] == "control_failed" and result["request_id"] == "status-control"
    assert result["accepted"] is False and result["action_executed"] is False
    assert result["run_id"] == RUN_ID and result["error"]["code"] == "command_pending"
    assert result["next"]["arguments"]["request_id"] == "original-input" and len(session.calls) == 1


def cancellation_wait_snapshot():
    state = snapshot(reason="verification_required")
    state.update(status="cancel_requested", runner_state="cancel_requested")
    return state


def cancelled_original_snapshot(state):
    final = deepcopy(state)
    final.update(status="cancelled", runner_state="cancelled", wait=None, wait_reason=None,
        pending=None, active_command_id=None, current_step_id=None)
    final["history"] = [{"step_id": "first", "execution_request_id": "input-first", "verdict": "cancelled",
        "action_executed": True, "original_input_status": "completed", "judged_by": "runtime"}]
    return final


@pytest.mark.parametrize("action", ["cancel", "status"])
def test_cancel_requested_original_verification_wait_is_not_a_new_handoff(tmp_path, clock, action):
    state = cancellation_wait_snapshot()
    session = Session([state, state, cancelled_original_snapshot(state)])
    events = []
    result = asyncio.run(client(tmp_path, session).run_plan("cancel-control", {
        "kind": "task_plan", "request": {"action": action, "run_id": RUN_ID}},
        event_callback=events.append, total_timeout=1))
    assert result["client_state"] == "terminal" and result["result"]["status"] == "cancelled"
    assert result["result"]["history"][0]["execution_request_id"] == "input-first"
    assert result["result"]["history"][0]["action_executed"] is True and events == []
    assert [name for name, args in session.calls] == ["instant_run", "instant_status", "instant_status"]
    assert [args["command"]["request"]["action"] for name, args in session.calls if name == "instant_run"] == [action]
    assert clock.sleeps == [.01]


def test_cancel_requested_timeout_preserves_original_wait_and_is_not_cancelled(tmp_path, clock):
    state = cancellation_wait_snapshot()
    session = Session([state] * 10)
    events = []
    result = asyncio.run(client(tmp_path, session).run_plan("cancel-control", {
        "kind": "task_plan", "request": {"action": "cancel", "run_id": RUN_ID}},
        event_callback=events.append, total_timeout=.025))
    assert result["client_state"] == "pending" and result["result"]["status"] == "cancel_requested"
    assert result["result"]["runner_state"] == "cancel_requested" and result["result"]["history"] == []
    assert result["active_command_id"] == "input-first" and result["wait_id"] == state["wait"]["wait_id"]
    assert result["command_cancelled"] is False and result["next"] == {"tool": "instant_status", "arguments": {}}
    assert len(events) == 1 and events[0]["client_state"] == "pending" and clock.sleeps
    assert sum(name == "instant_run" for name, args in session.calls) == 1


def reviewed_original_snapshot():
    value = snapshot(completed=1, reason="verification_required")
    value.update(status="ready", runner_state="waiting", pending=None, active_command_id="input-first")
    value["wait"] = snapshot(reason="verification_required")["wait"]
    value["history"][0].update(judged_by="agent", original_input_status="completed", verification_request_id="original-review")
    return value


@pytest.mark.parametrize("change", ["unknown_wait", "wrong_step", "wrong_execution", "not_agent", "unknown_input"])
def test_settled_review_cannot_replace_original_wait_or_history(tmp_path, change):
    reviewed = reviewed_original_snapshot()
    if change == "unknown_wait":
        reviewed["wait"]["wait_id"] = "different-wait"
    elif change == "wrong_step":
        reviewed["history"][-1]["step_id"] = "other-step"
    elif change == "wrong_execution":
        reviewed["history"][-1]["execution_request_id"] = "other-input"
    elif change == "not_agent":
        reviewed["history"][-1]["judged_by"] = "native_condition"
    else:
        reviewed["history"][-1]["original_input_status"] = "unknown"
    session = Session([snapshot(reason="verification_required"), reviewed])
    opened = client(tmp_path, session)
    async def exercise():
        await opened.run_plan("original-start", COMMAND, total_timeout=1)
        await opened.run_plan("status-control", {"kind": "task_plan", "request": {"action": "status", "run_id": RUN_ID}}, total_timeout=1)
    with pytest.raises(ValueError, match="benchmark_task_plan"):
        asyncio.run(exercise())
    assert len(session.calls) == 2


def test_settled_review_without_known_original_wait_is_rejected(tmp_path):
    session = Session([reviewed_original_snapshot()])
    with pytest.raises(ValueError, match="benchmark_task_plan"):
        asyncio.run(client(tmp_path, session).run_plan("status-control", {
            "kind": "task_plan", "request": {"action": "status", "run_id": RUN_ID}}, total_timeout=1))


@pytest.mark.parametrize("control_action", ["review_continue", "review_final", "review_failure", "cancel"])
def test_real_runtime_original_wait_control_never_replays_input(tmp_path, clock, monkeypatch, control_action):
    from tests.test_task_plan_runner import complete_original, scene
    from tests.test_task_plan_contract import plan as runtime_plan
    source = runtime_plan(count=1 if control_action == "review_final" else 2)
    source["steps"][0]["verification"] = {"kind": "agent_judgment"}
    transport = InstantAttachmentTransport(tmp_path, tmp_path / "runtime")
    transport.session = transport.data_root / ("session-" + "f" * 32)
    transport._host_alive = lambda: True
    transport.session.mkdir(parents=True)
    for folder in ("commands", "responses"):
        (transport.session / folder).mkdir()
    s = None
    calls, originals, events = [], [], []
    def publish(value):
        from app.core.json_snapshot import write_json_snapshot
        write_json_snapshot(transport.session / "report.json", {"phase": "ready", "task_plan_run": value})
    publish(None)
    class RuntimeControls:
        async def call_tool(self, name, args):
            nonlocal s
            from app.core.json_snapshot import write_json_snapshot
            calls.append((name, deepcopy(args)))
            if name == "instant_run":
                transport.submit(args["request_id"], args["command"])
                if args["command"]["request"]["action"] == "start":
                    s = scene(transport.session, monkeypatch, source=source)
                    state = s.first
                else:
                    state = s.runtime.control(args["command"]["request"], args["request_id"])
                write_json_snapshot(transport._path(args["request_id"], "responses"), {
                    **receipt(args["request_id"], state), "command": deepcopy(args["command"])})
                publish(state)
                value = transport.result(args["request_id"])
            elif name == "instant_status":
                value = transport.status()
                pending = s.runtime.backend.status(s.run_id)["pending"]
                if pending is not None and not (s.session / "responses" / (pending["execution_request_id"] + ".json")).is_file():
                    original = complete_original(s)
                    originals.append(original)
                fresh = s.runtime.tick(force=True)
                if fresh is not None:
                    publish(fresh)
            else:
                raise AssertionError(name)
            return type("ToolResult", (), {"structuredContent": value, "is_error": False})()
    opened = client(tmp_path, RuntimeControls())
    async def exercise():
        waiting = await opened.run_plan("plan-start", {"kind": "task_plan", "request": {"action": "start", "plan": source}},
            event_callback=events.append, total_timeout=1)
        assert waiting["client_state"] == "verification_required" and len(originals) == 1
        original_wait = waiting["wait_id"]
        original = originals[0]
        if control_action == "cancel":
            cancelled = await opened.run_plan("original-cancel", {"kind": "task_plan", "request": {
                "action": "cancel", "run_id": s.run_id}}, event_callback=events.append, total_timeout=1)
            assert cancelled["client_state"] == "terminal" and cancelled["result"]["status"] == "cancelled"
            for index in range(2):
                status = await opened.run_plan("cancelled-status-" + str(index), {"kind": "task_plan", "request": {
                    "action": "status", "run_id": s.run_id}}, event_callback=events.append, total_timeout=1)
                assert status["result"]["history"] == cancelled["result"]["history"] and len(originals) == 1
            return cancelled
        reviewed = await opened.run_plan("original-review", {"kind": "task_plan", "request": {
            "action": "review", "run_id": s.run_id, "execution_request_id": original.command_id,
            "step_id": "step-0", "verdict": "failure" if control_action == "review_failure" else "success", "reason": "explicit script review",
            "evidence_sha256": original.capture["sha256"]}}, event_callback=events.append, total_timeout=1)
        assert reviewed["client_state"] == "continue_required" and reviewed["wait_id"] == original_wait
        assert reviewed["active_command_id"] == original.command_id and len(originals) == 1 and len(events) == 1
        assert reviewed["result"]["history"][0]["execution_request_id"] == original.command_id
        continued = await opened.run_plan("original-continue", {"kind": "task_plan", "request": {
            "action": "continue", "run_id": s.run_id, "wait_id": original_wait}}, event_callback=events.append, total_timeout=1)
        return continued
    result = asyncio.run(exercise())
    if control_action == "cancel":
        assert result["result"]["runner_state"] == "cancelled" and len(originals) == 1 and len(events) == 1
        assert result["result"]["history"][0]["execution_request_id"] == originals[0].command_id
        assert result["result"]["history"][0]["action_executed"] is True
        assert result["result"]["history"][0]["original_input_status"] == "completed"
        assert s.runtime.runner.status(s.run_id)["pending"] is None
        assert [args["command"]["request"]["action"] for name, args in calls if name == "instant_run"] == ["start", "cancel", "status", "status"]
        assert not any(path.stem == "original-continue" for path in (transport.session / "commands").glob("*.json"))
        return
    assert result["client_state"] == "terminal" and result["result"]["runner_state"] == ("failed" if control_action == "review_failure" else "completed")
    assert len(originals) == (2 if control_action == "review_continue" else 1) and len(events) == 1
    assert [row["execution_request_id"] for row in result["result"]["history"]] == [o.command_id for o in originals]
    assert [row["judged_by"] for row in result["result"]["history"]] == (["agent", "native_condition"] if control_action == "review_continue" else ["agent"])
    assert [args["command"]["request"]["action"] for name, args in calls if name == "instant_run"] == ["start", "review", "continue"]
    assert set(path.stem for path in (transport.session / "commands").glob("*.json")) == {
        "plan-start", "original-review", "original-continue", *(o.command_id for o in originals)}
