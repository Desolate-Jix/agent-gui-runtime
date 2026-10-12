"""固定客户端仅在可注入的 MCP 边界离线验证，不启动宿主或模型。"""
import asyncio
from copy import deepcopy
import io
import json
from pathlib import Path

import pytest

from tests.test_learning_benchmark_client import FakeSDK, ToolResult, exhaust_initial_wait_budget
from tests.test_task_plan_client import COMMAND, Session, snapshot as plan_snapshot


RUN_ID = "trial-" + "a" * 64


def snapshot(**options):
    value = plan_snapshot(**options)
    value["run_id"] = RUN_ID
    if value.get("wait") is not None:
        value["wait"]["run_id"] = RUN_ID
    return value


def module():
    from scripts import execution_client
    return execution_client


def client(tmp_path, sdk, **options):
    return module().ExecutionClient(root=Path(__file__).resolve().parents[1],
        data_root=tmp_path / "data", model_directory=tmp_path / "model",
        transport_factory=sdk.transport, client_factory=sdk.client,
        params_factory=lambda **kwargs: kwargs, poll_interval=.001,
        ready_timeout=1, cleanup_timeout=1, **options)


class PlanSDK(FakeSDK):
    def __init__(self, states, *, pending_start=0):
        super().__init__()
        self.plan = Session(states, pending_start=pending_start)
        self.plan_active = False

    def client(self, read, write):
        session = super().client(read, write)
        original = session.call_tool

        async def call_tool(name, args):
            if name == "instant_run" and args["command"]["kind"] == "task_plan":
                self.plan_active = True
                self.calls.append((name, deepcopy(args)))
                return await self.plan.call_tool(name, args)
            if (name == "instant_result" and self.plan_active
                    or name == "instant_status" and self.plan_active and self.plan.states and not self.stopped):
                self.calls.append((name, deepcopy(args)))
                return await self.plan.call_tool(name, args)
            return await original(name, args)

        session.call_tool = call_tool
        return session


def test_one_connection_normalizes_commands_and_only_reads_pending_original_id(tmp_path):
    sdk = FakeSDK()

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            first = await opened.execute({"request_id": "discover-one",
                "command": {"kind": "discover", "handle": None}})
            second = await opened.execute({"request_id": "discover-two", "command": {"kind": "discover"}})
            assert first["original_request_id"] == "discover-one"
            assert second["original_request_id"] == "discover-two"

    asyncio.run(scenario())
    assert sdk.session_enters == sdk.session_exits == 1
    submits = [args for name, args in sdk.calls if name == "instant_run"]
    assert [args["request_id"] for args in submits] == ["discover-one", "discover-two"]
    assert all(args["command"] == {"kind": "discover"} for args in submits)
    assert [args["request_id"] for name, args in sdk.calls if name == "instant_result"] == [
        "discover-one", "discover-two"]
    assert not list(tmp_path.rglob("calls.jsonl"))


def test_repeating_original_command_reads_receipt_and_changed_content_is_rejected(tmp_path):
    sdk = exhaust_initial_wait_budget(FakeSDK())

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            request = {"request_id": "original", "command": {"kind": "discover"}, "total_timeout": .0005}
            pending = await opened.execute(request)
            assert pending["status"] == "pending" and pending["original_request_id"] == "original"
            recovered = await opened.execute(request)
            assert recovered["request_id"] == "original" and recovered["status"] == "returned"
            with pytest.raises(ValueError, match="request_id_conflict"):
                await opened.execute({"request_id": "original", "command": {"kind": "capture"}})

    asyncio.run(scenario())
    assert [name for name, _ in sdk.calls].count("instant_run") == 1
    assert [args["request_id"] for name, args in sdk.calls if name == "instant_result"] == ["original"]


def test_inputs_require_explicit_permission_and_invalid_commands_never_reach_transport(tmp_path):
    sdk = FakeSDK()

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            with pytest.raises(ValueError, match="read_only"):
                await opened.execute({"request_id": "select-denied",
                    "command": {"kind": "select", "handle": 7, "process_id": 9}})
            with pytest.raises(ValueError):
                await opened.execute({"request_id": "invalid",
                    "command": {"kind": "select", "handle": 7}})
            assert (await opened.execute({"request_id": "allowed-read",
                "command": {"kind": "discover"}}))["status"] == "returned"

    asyncio.run(scenario())
    assert not any(args.get("request_id") in {"select-denied", "invalid"} for _, args in sdk.calls)


def test_run_plan_continues_original_run_without_submitting_more_actions(tmp_path):
    sdk = PlanSDK([snapshot(), snapshot(completed=1, command_id="input-second"), snapshot(completed=2)],
        pending_start=2)

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.execute({"request_id": "original-start", "command": COMMAND, "total_timeout": 1})

    result = asyncio.run(scenario())
    assert result["client_state"] == "terminal" and result["run_id"] == RUN_ID
    assert result["original_request_id"] == result["start_request_id"] == "original-start"
    assert [name for name, _ in sdk.calls].count("instant_run") == 1
    assert [args["request_id"] for name, args in sdk.calls if name == "instant_result"] == [
        "original-start", "original-start"]
    assert sdk.session_enters == sdk.session_exits == 1


def test_review_and_continue_preserve_original_step_and_wait_binding(tmp_path):
    awaiting = snapshot(reason="verification_required")
    settled = deepcopy(awaiting)
    settled.update(status="ready", pending=None)
    settled["history"] = [{"step_id": "first", "execution_request_id": "input-first", "verdict": "success",
        "judged_by": "agent", "reason": "Verified original evidence", "original_input_status": "completed",
        "verification_request_id": "review-one"}]
    completed = snapshot(completed=2)
    completed["history"][0] = deepcopy(settled["history"][0])
    sdk = PlanSDK([awaiting, settled, completed])
    wait_id = awaiting["wait"]["wait_id"]

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            pending = await opened.execute({"request_id": "original-start", "command": COMMAND})
            assert pending["client_state"] == "verification_required"
            assert pending["active_command_id"] == "input-first" and pending["wait_id"] == wait_id
            review = await opened.execute({"request_id": "review-one", "command": {"kind": "task_plan",
                "request": {"action": "review", "run_id": RUN_ID, "execution_request_id": "input-first",
                    "step_id": "first", "verdict": "success", "reason": "Verified original evidence",
                    "evidence_sha256": "e" * 64}}})
            assert review["client_state"] == "continue_required" and review["wait_id"] == wait_id
            return await opened.execute({"request_id": "continue-one", "command": {"kind": "task_plan",
                "request": {"action": "continue", "run_id": RUN_ID, "wait_id": wait_id}}})

    result = asyncio.run(scenario())
    assert result["client_state"] == "terminal" and result["start_request_id"] == "original-start"
    submitted = [args for name, args in sdk.calls if name == "instant_run"]
    assert [args["request_id"] for args in submitted] == ["original-start", "review-one", "continue-one"]
    assert submitted[-1]["command"]["request"]["wait_id"] == wait_id


def test_jsonl_pending_read_error_recovery_and_finish_share_one_connection(tmp_path, monkeypatch):
    sdk = exhaust_initial_wait_budget(FakeSDK())
    monkeypatch.setenv("EXECUTION_CLIENT_SECRET", "ENVIRONMENT_ONLY_SENTINEL")
    profile = tmp_path / "profile-not-read.json"
    messages = [
        {"request_id": "pending-one", "command": {"kind": "discover"}, "total_timeout": .0005},
        {"tool": "instant_result", "arguments": {"request_id": "pending-one", "detail": "full", "images": "none"}},
        {"request_id": "forbidden", "command": {"kind": "select", "handle": 7, "process_id": 9}},
        {"action": "finish"},
        {"request_id": "after-finish", "command": {"kind": "discover"}},
    ]
    incoming = io.StringIO("\n" + "\n".join(json.dumps(row) for row in messages) + "\n")
    outgoing = io.StringIO()
    exit_code = asyncio.run(module().serve_jsonl(client(tmp_path, sdk, decision_profile=profile),
        input_stream=incoming, output_stream=outgoing))
    rows = [json.loads(row) for row in outgoing.getvalue().splitlines()]
    assert exit_code == 0
    assert [row["event"] for row in rows] == ["ready", "result", "result", "error", "finished"]
    assert rows[0]["models_prepared"] is False and rows[0]["model_state"] == "cold"
    assert rows[1]["response"]["request_id"] == rows[2]["response"]["request_id"] == "pending-one"
    assert rows[1]["response"]["status"] == "pending" and rows[2]["response"]["status"] == "returned"
    assert rows[-1]["cleanup_verified"] is True
    assert "ENVIRONMENT_ONLY_SENTINEL" not in outgoing.getvalue() and not profile.exists()
    assert sdk.params["env"]["EXECUTION_CLIENT_SECRET"] == "ENVIRONMENT_ONLY_SENTINEL"
    arguments = sdk.params["args"]
    assert arguments[arguments.index("--recognition-source") + 1] == "local"
    assert arguments[arguments.index("--decision-profile") + 1] == str(profile.resolve())
    assert sdk.session_enters == sdk.session_exits == 1
    assert not any(args.get("request_id") in {"forbidden", "after-finish"} for _, args in sdk.calls)
    assert [name for name, _ in sdk.calls].count("instant_stop") == 1
    assert not any(args.get("command", {}).get("kind") == "close_launched_window" for _, args in sdk.calls)


def test_eof_and_invalid_json_close_host_and_never_echo_untrusted_error_text(tmp_path):
    sdk = FakeSDK()
    outgoing = io.StringIO()
    exit_code = asyncio.run(module().serve_jsonl(client(tmp_path, sdk),
        input_stream=io.StringIO('{"PRIVATE-INVALID-PAYLOAD"\n'), output_stream=outgoing))
    rows = [json.loads(row) for row in outgoing.getvalue().splitlines()]
    assert exit_code == 0 and [row["event"] for row in rows] == ["ready", "error", "finished"]
    assert "PRIVATE-INVALID-PAYLOAD" not in outgoing.getvalue()
    assert sdk.session_enters == sdk.session_exits == 1
    assert [name for name, _ in sdk.calls].count("instant_stop") == 1


def test_rejected_start_never_stops_existing_host(tmp_path):
    class RejectedSDK(FakeSDK):
        def client(self, read, write):
            session = super().client(read, write)
            original = session.call_tool

            async def call_tool(name, args):
                if name == "instant_start":
                    self.calls.append((name, args))
                    return ToolResult({"status": "start_rejected", "host_launch_attempted": False,
                        "error": {"code": "previous_session_not_resolved"}}, error=True)
                return await original(name, args)

            session.call_tool = call_tool
            return session

    sdk = RejectedSDK()
    outgoing = io.StringIO()
    exit_code = asyncio.run(module().serve_jsonl(client(tmp_path, sdk),
        input_stream=io.StringIO('{"action":"finish"}\n'), output_stream=outgoing))
    assert exit_code == 1
    assert json.loads(outgoing.getvalue())["event"] == "error"
    assert not any(name == "instant_stop" for name, _ in sdk.calls)
    assert sdk.session_enters == sdk.session_exits == 1


class PreparationSDK(FakeSDK):
    def __init__(self, *, succeeded=True):
        super().__init__()
        self.preparation_id = None
        self.preparation_succeeded = succeeded

    def client(self, read, write):
        session = super().client(read, write)
        original = session.call_tool

        async def call_tool(name, args):
            if name == "instant_run" and args["command"] == {"kind": "prepare_models"}:
                self.calls.append((name, args))
                self.preparation_id = args["request_id"]
                return ToolResult({"request_id": self.preparation_id, "status": "pending"})
            if name == "instant_result" and args["request_id"] == self.preparation_id:
                self.calls.append((name, args))
                return ToolResult({"request_id": self.preparation_id, "status": "returned",
                    "operation_succeeded": self.preparation_succeeded,
                    "result": {"status": "ready" if self.preparation_succeeded else "failed"}})
            return await original(name, args)

        session.call_tool = call_tool
        return session


def test_explicit_preparation_uses_same_connection_once_before_ready_without_input_permission(tmp_path):
    sdk = PreparationSDK()
    outgoing = io.StringIO()
    exit_code = asyncio.run(module().serve_jsonl(client(tmp_path, sdk, prepare_models=True),
        input_stream=io.StringIO('{"request_id":"read-one","command":{"kind":"discover"}}\n'
            '{"action":"finish"}\n'), output_stream=outgoing))
    rows = [json.loads(row) for row in outgoing.getvalue().splitlines()]
    assert exit_code == 0 and [row["event"] for row in rows] == ["ready", "result", "finished"]
    assert rows[0]["models_prepared"] is True and rows[0]["model_state"] == "prepared"
    assert rows[0]["preparation_request_id"] == sdk.preparation_id
    assert rows[0]["actions_enabled"] is False
    assert [args["command"]["kind"] for name, args in sdk.calls if name == "instant_run"] == [
        "prepare_models", "discover"]
    assert sdk.session_enters == sdk.session_exits == 1


def test_preparation_failure_never_claims_ready_and_still_cleans_owned_host(tmp_path):
    sdk = PreparationSDK(succeeded=False)
    outgoing = io.StringIO()
    exit_code = asyncio.run(module().serve_jsonl(client(tmp_path, sdk, prepare_models=True),
        input_stream=io.StringIO('{"action":"finish"}\n'), output_stream=outgoing))
    row = json.loads(outgoing.getvalue())
    assert exit_code == 1 and row["event"] == "error" and row["request_id"] == sdk.preparation_id
    assert [name for name, _ in sdk.calls].count("instant_stop") == 1
    assert sdk.session_enters == sdk.session_exits == 1


def test_cli_options_reach_single_injected_client(tmp_path):
    sdk = PreparationSDK()
    incoming, outgoing = io.StringIO('{"action":"finish"}\n'), io.StringIO()
    options = {}

    def factory(**kwargs):
        options.update(kwargs)
        return module().ExecutionClient(**kwargs, transport_factory=sdk.transport,
            client_factory=sdk.client, params_factory=lambda **kw: kw,
            poll_interval=.001, ready_timeout=1, cleanup_timeout=1)

    exit_code = module().main(["--root", str(Path(__file__).resolve().parents[1]),
        "--data-dir", str(tmp_path / "data"), "--model-directory", str(tmp_path / "model"),
        "--decision-profile", str(tmp_path / "not-read.json"), "--allow-actions", "--prepare-models"],
        input_stream=incoming, output_stream=outgoing, client_factory=factory)
    assert exit_code == 0
    assert options["recognition_source"] == "local"
    assert options["allow_actions"] is options["prepare_models"] is True
    assert options["decision_profile"] == tmp_path / "not-read.json"
    assert sdk.session_enters == sdk.session_exits == 1


def test_luna_preset_uses_external_api_without_local_model_or_preparation(tmp_path):
    sdk = FakeSDK()
    options, outgoing = {}, io.StringIO()
    root = Path(__file__).resolve().parents[1]

    def factory(**kwargs):
        options.update(kwargs)
        return module().ExecutionClient(**kwargs, transport_factory=sdk.transport,
            client_factory=sdk.client, params_factory=lambda **kw: kw, poll_interval=.001)

    result = module().main(["--root", str(root), "--data-dir", str(tmp_path / "data"), "--luna-api"],
        input_stream=io.StringIO('{"action":"finish"}\n'), output_stream=outgoing, client_factory=factory)
    assert result == 0
    assert options["recognition_source"] == "external_api"
    assert options["api_profile"] == root / "configs/vision-api-openai-luna.example.json"
    assert options["model_directory"] is None and options["prepare_models"] is False
    assert "--model-directory" not in sdk.params["args"]
    assert not any(args.get("command", {}).get("kind") == "prepare_models" for _, args in sdk.calls)
    ready = json.loads(outgoing.getvalue().splitlines()[0])
    assert ready["model_state"] == "not_required" and ready["actions_enabled"] is False


@pytest.mark.parametrize("conflict", [
    ["--recognition-source", "local"], ["--model-directory", "unused-model"],
    ["--api-profile", "other-profile.json"], ["--delegate-profile", "other"], ["--prepare-models"],
])
def test_luna_preset_rejects_conflicts_before_creating_client(tmp_path, conflict):
    outgoing = io.StringIO()
    result = module().main(["--data-dir", str(tmp_path), "--luna-api", *conflict],
        input_stream=io.StringIO(), output_stream=outgoing,
        client_factory=lambda **kwargs: pytest.fail("conflicting options created a client"))
    assert result == 1
    assert json.loads(outgoing.getvalue())["error"]["code"] == "execution_client_luna_api_conflict"


def test_external_api_explicit_model_preparation_is_rejected_before_transport(tmp_path):
    sdk = FakeSDK()
    with pytest.raises(ValueError, match="prepare_models_requires_local"):
        module().ExecutionClient(root=Path(__file__).resolve().parents[1], data_root=tmp_path,
            recognition_source="external_api", api_profile=tmp_path / "not-read.json", prepare_models=True,
            transport_factory=sdk.transport, client_factory=sdk.client)
    assert sdk.calls == [] and sdk.session_enters == 0


class VerboseSDK(FakeSDK):
    def client(self, read, write):
        session = super().client(read, write)
        original = session.call_tool

        async def call_tool(name, args):
            if name in {"instant_run", "instant_result"}:
                self.calls.append((name, deepcopy(args)))
                return ToolResult({"request_id": args["request_id"], "status": "returned",
                    "operation_succeeded": True, "result": {"contract_version": "input_sequence_v1",
                        "status": "completed", "input_check": {"status": "matched"},
                        "completed_steps": ["focus", "type", "check_input"], "steps": [],
                        "recognition_trace": "VERBOSE_DIAGNOSTIC_SENTINEL"}})
            return await original(name, args)

        session.call_tool = call_tool
        return session


def test_normal_output_is_compact_with_original_references_and_explicit_full_read(tmp_path):
    sdk = VerboseSDK()

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            command = {"kind": "input_sequence", "request": {"field_goal": "Address", "text": "example",
                "clear_existing": True, "submit_search": False}}
            compact = await opened.execute({"request_id": "original-input", "command": command})
            full = await opened.execute(compact["original_receipt"])
            return compact, full

    compact, full = asyncio.run(scenario())
    assert compact["receipt_detail"] == "compact" and compact["sequence"]["input_check"]["status"] == "matched"
    assert compact["original_request_id"] == "original-input"
    assert compact["original_receipt"] == {"tool": "instant_result", "arguments": {
        "request_id": "original-input", "detail": "full", "images": "none"}}
    assert compact["images"][0]["arguments"]["request_id"] == "original-input"
    assert "VERBOSE_DIAGNOSTIC_SENTINEL" not in json.dumps(compact)
    assert full["result"]["recognition_trace"] == "VERBOSE_DIAGNOSTIC_SENTINEL"
    assert [name for name, _ in sdk.calls].count("instant_run") == 1


def test_transport_failure_keeps_original_id_and_next_attempt_only_reads_receipt(tmp_path):
    class FailingSDK(FakeSDK):
        def client(self, read, write):
            session = super().client(read, write)
            original = session.call_tool

            async def call_tool(name, args):
                if name == "instant_run":
                    self.calls.append((name, deepcopy(args)))
                    raise OSError("connection interrupted after admission")
                return await original(name, args)

            session.call_tool = call_tool
            return session

    sdk = FailingSDK()

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            request = {"request_id": "original-unknown", "command": {"kind": "discover"}}
            with pytest.raises(OSError):
                await opened.execute(request)
            return await opened.execute(request)

    result = asyncio.run(scenario())
    assert result["original_request_id"] == "original-unknown"
    assert [name for name, _ in sdk.calls].count("instant_run") == 1
    assert [args["request_id"] for name, args in sdk.calls if name == "instant_result"] == ["original-unknown"]


def test_jsonl_transport_error_returns_original_reference_without_echoing_request(tmp_path):
    class InterruptedSDK(FakeSDK):
        def client(self, read, write):
            session = super().client(read, write)
            original = session.call_tool

            async def call_tool(name, args):
                if name == "instant_run":
                    self.calls.append((name, deepcopy(args)))
                    raise OSError("PRIVATE_TRANSPORT_MESSAGE")
                return await original(name, args)

            session.call_tool = call_tool
            return session

    sdk, outgoing = InterruptedSDK(), io.StringIO()
    result = asyncio.run(module().serve_jsonl(client(tmp_path, sdk), input_stream=io.StringIO(
        '{"request_id":"original-transport","command":{"kind":"discover"}}\n'
        '{"tool":"instant_result","arguments":{"request_id":"original-transport"}}\n'
        '{"action":"finish"}\n'), output_stream=outgoing))
    rows = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert result == 0 and [row["event"] for row in rows] == ["ready", "error", "result", "finished"]
    assert rows[1]["request_id"] == "original-transport"
    assert rows[1]["original_receipt"]["arguments"]["request_id"] == "original-transport"
    assert rows[1]["automatic_retry_allowed"] is False
    assert "PRIVATE_TRANSPORT_MESSAGE" not in outgoing.getvalue()
    assert [name for name, _ in sdk.calls].count("instant_run") == 1


def test_compact_plan_keeps_review_packet_and_evidence_hashes_unchanged():
    packet = {"packet_sha256": "a" * 64, "evidence_set_sha256": "b" * 64,
        "assessment_round": 1, "latest_observation": {"sha256": "c" * 64}}
    result = {"request_id": "original-plan", "original_request_id": "original-plan",
        "client_state": "review_required", "execution_receipts": [], "images": [],
        "result": {"plan_sha256": "d" * 64, "prefix_sha256": "e" * 64, "review_packet": packet}}
    compact = module().ExecutionClient._compact_response(result)
    assert compact["result"] == result["result"] and compact["client_state"] == "review_required"
    compact["result"]["review_packet"]["latest_observation"]["sha256"] = "changed"
    assert packet["latest_observation"]["sha256"] == "c" * 64


def test_missing_request_id_error_does_not_close_session_or_reuse_previous_identity(tmp_path):
    sdk, outgoing = FakeSDK(), io.StringIO()
    result = asyncio.run(module().serve_jsonl(client(tmp_path, sdk), input_stream=io.StringIO(
        '{"request_id":"valid-first","command":{"kind":"discover"}}\n'
        '{"command":{"kind":"discover"}}\n'
        '{"request_id":"valid-after","command":{"kind":"discover"}}\n'
        '{"action":"finish"}\n'), output_stream=outgoing))
    rows = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert result == 0 and [row["event"] for row in rows] == ["ready", "result", "error", "result", "finished"]
    assert "request_id" not in rows[2] and "original_receipt" not in rows[2]
    assert rows[3]["response"]["original_request_id"] == "valid-after"
    assert sdk.session_enters == sdk.session_exits == 1


def test_compact_partial_projection_keeps_known_original_without_inventing_current_receipt():
    compact = module().ExecutionClient._compact_response({"original_request_id": "original-pending",
        "status": "result_unknown", "client_state": "pending", "no_replay": True})
    assert compact["original_receipt"]["arguments"]["request_id"] == "original-pending"
    assert compact["full_receipt"] == compact["original_receipt"]
    assert "current_receipt" not in compact
    assert compact["no_replay"] is True
