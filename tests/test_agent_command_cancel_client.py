"""Cancel identity regression through real dispatch, worker state and receipt projection.

Only MCP transport and desktop execution are replaced; no host or model is started.
"""
import asyncio
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.instant_mcp import InstantCommand, InstantSession, write_json
from app.vision.agent_command_jobs import AgentCommandJobs
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from scripts.learning_benchmark_client import BenchmarkCallError, LearningBenchmarkClient
from scripts.run_local_step_session import dispatch_agent_command, run_grounding_command


CAPS = {"image_transport": "supported", "current_vision": "supported"}
TARGET = {"handle": 100, "process_id": 200, "process_create_time": 1.5}


class _Coordinator:
    def __init__(self):
        self._owner = SimpleNamespace(call=lambda callback: callback())
        self.calls = []

    def execute_local_step(self, **kwargs):
        self.calls.append(kwargs)
        return {"phase": "returned", "response": {"success": True,
            "data": {"result": {"execution_path": {"action_executed": True}}}},
            "action_executed": True, "observation": {"status": "not_requested"}}


class _RuntimeSDK:
    def __init__(self, root, jobs, store):
        self.jobs, self.store = jobs, store
        self.session = InstantSession(root, root, recognition_source="agent_current")
        self.session.session = root
        self.session.status = lambda: {"host_alive": True}
        # This fixture runs a live worker without a host process.  Keep both
        # liveness entrypoints consistent so normal receipts do not enter the
        # dead-host recovery reader while the worker is publishing snapshots.
        self.session._host_alive = lambda: True
        for name in ("commands", "responses"):
            (root / name).mkdir(exist_ok=True)
        self.calls = []
        self.cancel_reply = "returned"
        self.reply_command_id = None
        self.reply_request_id = None

    async def call_tool(self, name, args):
        self.calls.append((name, deepcopy(args)))
        request_id = args["request_id"]
        if name == "instant_result":
            value = self.session.result(request_id)
        else:
            assert name == "instant_run"
            command = InstantCommand.model_validate(args["command"]).command()
            write_json(self.session.session / "commands" / (request_id + ".json"), command)
            try:
                if command["kind"] == "grounding_resolve":
                    result, _ = run_grounding_command(self.store, None, request_id, command)
                else:
                    result = dispatch_agent_command(self.jobs, request_id, command, TARGET)
            except ValueError as error:
                value = {"request_id": request_id, "status": "failed", "error": str(error)}
                return SimpleNamespace(structuredContent=value, isError=True)
            write_json(self.session.session / "responses" / (request_id + ".json"),
                {"command": command, "status": "returned", "result": result})
            value = self.session.result(request_id)
            if command["kind"] == "agent_command_cancel":
                if self.cancel_reply != "returned":
                    value = {"request_id": request_id, "status": self.cancel_reply,
                             "wait_expired": True}
                if self.reply_command_id is not None:
                    value["result"]["command_id"] = self.reply_command_id
                if self.reply_request_id is not None:
                    value["request_id"] = self.reply_request_id
        return SimpleNamespace(structuredContent=value, isError=False)


@pytest.fixture
def runtime(tmp_path):
    image = tmp_path / "before.png"
    Image.new("RGB", (100, 80), "white").save(image)
    capture = {"image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
               "window_identity": TARGET}
    store = GroundingHandoffStore(tmp_path, owner_id="cancel-client-test")
    coordinator = _Coordinator()
    jobs = AgentCommandJobs(coordinator, store, lambda: capture,
                            RecognitionSourceConfig(source="agent_current"))
    sdk = _RuntimeSDK(tmp_path, jobs, store)
    client = LearningBenchmarkClient(root=Path(__file__).resolve().parents[1],
        data_root=tmp_path, evidence_dir=tmp_path / "evidence", recognition_source="agent_current",
        allow_actions=True, poll_interval=.001)
    client._session = SimpleNamespace(call_tool=sdk.call_tool)
    yield client, sdk, coordinator
    jobs.close(timeout=2)


async def _start(client):
    receipt = await client.run("original-input", {"kind": "step",
        "operation": "execute_recognition_plan", "request": {"goal": "Search"},
        "vision_capabilities": CAPS}, total_timeout=2)
    assert receipt["client_state"] == "awaiting_grounding"
    return receipt["result"]["pending_grounding"]


def _cancel():
    return {"kind": "agent_command_cancel", "request": {"command_id": "original-input"}}


async def _terminal(client, prefix="final-status"):
    for index in range(100):
        result = await client.run(f"{prefix}-{index}", {"kind": "agent_command_status",
            "request": {"command_id": "original-input"}}, total_timeout=2)
        if result["client_state"] == "terminal":
            return result
        await asyncio.sleep(.005)
    pytest.fail("original worker did not reach terminal state")


def _found(pending):
    return {"schema_version": "grounding.v1", "request_id": pending["request_id"],
        "capture_id": pending["capture"]["capture_id"], "status": "found",
        "coordinate_space": "capture_image_pixels", "image_size": {"width": 100, "height": 80},
        "candidates": [{"id": "one", "label": "Search", "evidence_source": "agent_visual",
            "bbox": {"x": 10, "y": 20, "width": 50, "height": 20},
            "click_point": {"x": 35, "y": 30}}], "selected_candidate_id": "one"}


def test_cancel_waiting_worker_preserves_outer_and_original_identity(runtime):
    client, sdk, coordinator = runtime
    async def scenario():
        pending = await _start(client)
        receipt = await client.run("cancel-control", _cancel(), total_timeout=2)
        assert receipt["original_request_id"] == receipt["request_id"] == "cancel-control"
        assert receipt["current_status_request_id"] == "cancel-control"
        assert receipt["command_id"] == receipt["result"]["command_id"] == "original-input"
        assert receipt["result"]["cancel_requested"] is True
        final = await _terminal(client)
        assert final["result"]["status"] == "cancelled"
        assert final["result"]["action_executed"] is False
        assert sdk.store.get(pending["request_id"])["phase"] == "cancelled"
        with pytest.raises(BenchmarkCallError):
            await client.run("late-continue", {"kind": "agent_command_continue", "request": {
                "command_id": "original-input", "grounding_request_id": pending["request_id"]}})
    asyncio.run(scenario())
    assert coordinator.calls == []
    assert len([args for _, args in sdk.calls if args.get("command") == _cancel()]) == 1


@pytest.mark.parametrize("field,value,reason", [
    ("reply_command_id", "other-worker", "agent_command_identity_mismatch"),
    ("reply_request_id", "other-control", "receipt_request_id_mismatch"),
])
def test_cancel_rejects_misbound_receipt(runtime, field, value, reason):
    client, sdk, coordinator = runtime
    async def scenario():
        await _start(client)
        setattr(sdk, field, value)
        with pytest.raises(ValueError, match=reason):
            await client.run("cancel-control", _cancel(), total_timeout=2)
    asyncio.run(scenario())
    assert coordinator.calls == []


@pytest.mark.parametrize("status", ["pending", "result_unknown"])
def test_cancel_pending_or_unknown_reads_original_transport_without_replaying(runtime, status):
    client, sdk, coordinator = runtime
    async def scenario():
        await _start(client)
        sdk.cancel_reply = status
        receipt = await client.run("cancel-control", _cancel(), total_timeout=2)
        if status == "result_unknown":
            assert receipt["client_state"] == "pending" and receipt["no_replay"] is True
            assert receipt["automatic_retry_allowed"] is False
            assert receipt["command_id"] == "original-input"
            assert receipt["next"] == {"tool": "instant_result", "arguments": {
                "request_id": "cancel-control", "detail": "full", "images": "none"}}
            await client.call(receipt["next"]["tool"], receipt["next"]["arguments"])
        assert (await _terminal(client))["result"]["status"] == "cancelled"
    asyncio.run(scenario())
    assert [args["request_id"] for name, args in sdk.calls if name == "instant_result"] == ["cancel-control"]
    assert len([args for _, args in sdk.calls if args.get("command") == _cancel()]) == 1
    assert coordinator.calls == []


@pytest.mark.parametrize("field", ["request_id", "capture_id"])
def test_cancel_fix_keeps_grounding_identity_rejection(runtime, field):
    client, sdk, coordinator = runtime
    async def scenario():
        pending = await _start(client)
        payload = _found(pending)
        payload[field] = "other-evidence"
        with pytest.raises(BenchmarkCallError) as error:
            await client.run("wrong-resolve", {"kind": "grounding_resolve", "request": {
                "grounding_request_id": pending["request_id"], "result": payload}})
        assert "grounding_invalid" in error.value.response["error"]
        assert sdk.store.get(pending["request_id"])["phase"] == "awaiting_grounding"
        await client.run("cancel-control", _cancel(), total_timeout=2)
        assert (await _terminal(client))["result"]["status"] == "cancelled"
    asyncio.run(scenario())
    assert coordinator.calls == []


def test_cancel_completed_worker_does_not_replay_or_rewrite_outcome(runtime):
    client, sdk, coordinator = runtime
    async def scenario():
        pending = await _start(client)
        await client.run("resolve-control", {"kind": "grounding_resolve", "request": {
            "grounding_request_id": pending["request_id"], "result": _found(pending)}})
        await client.run("continue-control", {"kind": "agent_command_continue", "request": {
            "command_id": "original-input", "grounding_request_id": pending["request_id"]}}, total_timeout=2)
        assert (await _terminal(client))["result"]["status"] == "completed"
        receipt = await client.run("cancel-control", _cancel(), total_timeout=2)
        assert receipt["command_id"] == "original-input"
        assert receipt["client_state"] == "terminal"
        assert receipt["result"]["status"] == "completed"
        assert receipt["result"]["action_executed"] is True
        assert receipt["result"]["cancel_requested"] is False
    asyncio.run(scenario())
    assert len(coordinator.calls) == 1


def test_cancel_keeps_explicit_action_gate(runtime):
    client, sdk, _ = runtime
    client.allow_actions = False
    with pytest.raises(ValueError, match="benchmark_client_read_only"):
        asyncio.run(client.run("cancel-control", _cancel()))
    assert sdk.calls == []
