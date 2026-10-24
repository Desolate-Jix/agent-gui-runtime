"""Offline current-Agent sessions use real command/grounding contracts, no GUI."""
import asyncio
import base64
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.instant_mcp import InstantCommand
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from app.vision.recognition_source import ClientVisionCapabilities
from scripts.current_agent_client import CurrentAgentClient
from tests.test_learning_benchmark_client import FakeSDK, ToolResult


CAPS = {"image_transport": "supported", "current_vision": "supported"}
CLICK = {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "Next"}}


class CurrentSDK(FakeSDK):
    """Fake transport with the actual durable grounding/capture validator."""

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        directory.mkdir(parents=True)
        self.store = GroundingHandoffStore(directory, owner_id="one-client")
        self.workers = {}
        self.receipts = {}
        self.inputs = []
        self.captures = []
        self.pending_once = set()
        self.timeout_once = set()
        self.wrong_worker = False
        self.first_image_unavailable = False
        self.cancel_stays_running = False
        self.unknown_input = False
        self.continue_running = False
        self.drop_image = False
        self.after_read = None

    def _capture(self, command_id):
        frame = self.directory / (command_id + ".png")
        Image.new("RGB", (100, 80), (len(self.captures) % 255, 170, 245)).save(frame)
        capture = {"image_path": str(frame), "sha256": sha256(frame.read_bytes()).hexdigest(),
            "capture_id": "capture-" + command_id,
            "window_identity": {"handle": 12, "process_id": 34, "process_create_time": 1.0}}
        self.captures.append(deepcopy(capture))
        return capture

    def _response(self, receipt, *, images=True):
        value = deepcopy(receipt)
        result = value.get("result") or {}
        capture = (result.get("pending_grounding") or {}).get("capture")
        if capture is None and result.get("contract_version") == "grounding_handoff.v1":
            capture = result.get("capture")
        if capture is None:
            capture = (result.get("observation") or {}).get("capture")
        response = ToolResult(value)
        response.content = []
        if capture and images and not self.drop_image:
            data = Path(capture["image_path"]).read_bytes()
            value["image_delivery"] = [{"view": "after", "status": "included",
                "sha256": sha256(data).hexdigest(), "content_index": 0, "original_pixels": True}]
            response.content = [SimpleNamespace(type="image", mime_type="image/png",
                data=base64.b64encode(data).decode("ascii"))]
        return response

    def _receipt(self, request_id, result):
        return {"request_id": request_id, "status": "returned", "result": deepcopy(result),
                "operation_succeeded": None, "task_effect_verified": None}

    def _run(self, request_id, command):
        kind, request = command["kind"], command.get("request") or {}
        if kind == "step":
            capture = self._capture(request_id)
            pending = self.store.prepare("ag-" + request_id, goal=request["goal"], capture=capture,
                configuration=RecognitionSourceConfig(source="agent_current"),
                capabilities=ClientVisionCapabilities.model_validate(command["vision_capabilities"]))
            self.workers[request_id] = {"contract_version": "agent_command.v1", "command_id": request_id,
                "status": "awaiting_grounding", "pending_grounding": pending,
                "observation": {"status": "captured", "capture": pending["capture"]},
                "cancel_requested": False, "action_executed": False, "dispatch_attempts": []}
            return self._receipt(request_id, self.workers[request_id])
        if kind == "grounding_resolve":
            return self._receipt(request_id, self.store.resolve(request["grounding_request_id"], request["result"]))
        if kind in {"agent_command_continue", "agent_command_status", "agent_command_cancel"}:
            worker = self.workers[request["command_id"]]
            if kind == "agent_command_continue":
                assert worker["status"] == "awaiting_grounding"
                self.store.claim_execution(request["grounding_request_id"], request_id)
                self.inputs.append(request["command_id"])
                after_path = self.directory / ("after-" + request["command_id"] + ".png")
                Image.new("RGB", (100, 80), (240, len(self.inputs) % 255, 100)).save(after_path)
                after = {"image_path": str(after_path), "sha256": sha256(after_path.read_bytes()).hexdigest(),
                         "capture_id": "after-" + request["command_id"]}
                worker.update(status="running" if self.continue_running else "completed", pending_grounding=None,
                    action_executed=None if self.unknown_input else True,
                    observation={"status": "captured", "capture": after},
                    dispatch_attempts=[{"status": "unknown" if self.unknown_input else "returned"}])
            elif kind == "agent_command_cancel":
                worker.update(cancel_requested=True, pending_grounding=None)
            elif worker.get("cancel_requested") and not self.cancel_stays_running:
                worker.update(status="cancelled")
            elif worker["status"] == "running" and not self.cancel_stays_running:
                worker["status"] = "completed"
            value = deepcopy(worker)
            if self.wrong_worker:
                value["command_id"] = "wrong-command"
            return self._receipt(request_id, value)
        if kind == "select":
            return {"request_id": request_id, "status": "returned", "operation_succeeded": True,
                    "result": {"status": "focused", "window": {"handle": command["handle"], "process_id": command["process_id"]}}}
        return {"request_id": request_id, "status": "returned", "operation_succeeded": True}

    def client(self, read, write):
        session = super().client(read, write)
        fallback = session.call_tool

        async def call_tool(name, args):
            if name == "instant_run":
                self.calls.append((name, deepcopy(args)))
                command = InstantCommand.model_validate(args["command"]).command()
                value = self._run(args["request_id"], command)
                self.receipts[args["request_id"]] = deepcopy(value)
                if args["request_id"] in self.timeout_once:
                    self.timeout_once.remove(args["request_id"])
                    await asyncio.sleep(10)
                if args["request_id"] in self.pending_once:
                    self.pending_once.remove(args["request_id"])
                    return ToolResult({"request_id": args["request_id"], "status": "pending"})
                return self._response(value, images=not (
                    self.first_image_unavailable and command["kind"] == "step"))
            if name == "instant_result" and args["request_id"] in self.receipts:
                self.calls.append((name, deepcopy(args)))
                if self.after_read:
                    self.after_read(self.receipts[args["request_id"]])
                return self._response(self.receipts[args["request_id"]])
            return await fallback(name, args)

        session.call_tool = call_tool
        return session


def client(tmp_path, sdk, **options):
    options.setdefault("client_vision_capabilities", CAPS)
    options.setdefault("allow_actions", True)
    return CurrentAgentClient(root=Path(__file__).resolve().parents[1], data_root=tmp_path / "data",
        transport_factory=sdk.transport, client_factory=sdk.client,
        params_factory=lambda **kwargs: kwargs, poll_interval=.001,
        ready_timeout=1, cleanup_timeout=1, **options)


def found(state, *, status="found"):
    return {"schema_version": "grounding.v1", "request_id": state["pending_grounding_request_id"],
        "capture_id": state["capture_id"], "status": status,
        "coordinate_space": "capture_image_pixels", "image_size": state["image_size"],
        "candidates": [{"id": "next", "label": "Next", "bbox": {"x": 10, "y": 20, "width": 40, "height": 30},
            "click_point": {"x": 30, "y": 40}, "evidence_source": "agent_visual"}] if status == "found" else [],
        "selected_candidate_id": "next" if status == "found" else None}


def verification(state):
    image = state["verification_image"]
    return {key: image[key] for key in ("request_id", "sha256", "capture_id") if key in image}


def test_twenty_steps_one_connection_fresh_images_and_explicit_verification(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")

    async def scenario():
        async with client(tmp_path, sdk, client_name="Codex") as opened:
            for index in range(20):
                prepared = await opened.execute({"action": "agent_prepare", "request_id": f"click-{index}", "command": CLICK})
                state = prepared["current_agent"]
                assert prepared["status"] == "awaiting_grounding"
                assert state["command_id"] == f"click-{index}"
                assert state["capture_id"] == f"capture-click-{index}"
                assert Path(state["original_image"]["image_path"]).read_bytes() == Path(sdk.captures[-1]["image_path"]).read_bytes()
                await opened.execute({"action": "agent_resolve", "request_id": f"resolve-{index}", "result": found(state)})
                continued = await opened.execute({"action": "agent_continue", "request_id": f"continue-{index}"})
                assert continued["status"] == "verification_required"
                assert continued["current_agent"]["runtime_status"] == "completed"
                assert continued["receipt"]["task_effect_verified"] is None
                with pytest.raises(ValueError, match="verification_or_terminal_required"):
                    await opened.agent_prepare(CLICK)
                verified = await opened.execute({"action": "agent_verify", "verdict": "success",
                    "evidence": verification(continued["current_agent"])})
                assert verified["current_agent"]["verification"]["source"] == "caller_judgment"
            completed = await opened.execute({"action": "agent_complete"})
            assert completed["status"] == "completed" and completed["current_agent"]["cleanup_verified"] is False
            with pytest.raises(ValueError, match="completed"):
                await opened.agent_prepare(CLICK)
            assert sdk.session_enters == 1
        assert opened.status["cleanup_verified"] is True

    asyncio.run(scenario())
    assert sdk.session_enters == sdk.session_exits == 1
    assert sdk.inputs == [f"click-{i}" for i in range(20)]
    assert len({capture["sha256"] for capture in sdk.captures}) == 20
    submissions = [args for name, args in sdk.calls if name == "instant_run"]
    assert len(submissions) == 60
    assert all(args["command"]["vision_capabilities"]["current_vision"] == "supported"
               for args in submissions if args["command"]["kind"] == "step")


@pytest.mark.parametrize("configuration", [{}, {"image_transport": "supported"},
    {"image_transport": "supported", "current_vision": "unsupported"}])
def test_missing_or_unsupported_capabilities_reject_before_capture(tmp_path, configuration):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk, client_vision_capabilities=configuration) as opened:
            assert opened.current_agent_state["missing_capabilities"]
            with pytest.raises(ValueError, match="vision_capability_required"):
                await opened.agent_prepare(CLICK)
    asyncio.run(scenario())
    assert sdk.captures == []


def test_capabilities_do_not_authorize_input_and_unsafe_low_level_routes_are_blocked(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=False) as opened:
            with pytest.raises(ValueError, match="read_only"):
                await opened.agent_prepare(CLICK)
            with pytest.raises(ValueError, match="read_only"):
                await opened.execute({"request_id": "select", "command": {"kind": "select", "handle": 12, "process_id": 34}})
            for command in [
                {"kind": "grounding_execute", "request": {"grounding_request_id": "other"}},
                {"kind": "agent_command_continue", "request": {"command_id": "other", "grounding_request_id": "ag-other"}},
                {"kind": "step", "operation": "press_key", "request": {"key": "Enter", "x": 1, "y": 1}},
                {"kind": "input_sequence", "request": {"field_goal": "Search", "text": "x"}},
            ]:
                with pytest.raises(ValueError, match="unsupported"):
                    await opened.execute({"tool": "instant_submit", "arguments": {"request_id": "denied", "command": command}})
    asyncio.run(scenario())
    assert not [args for name, args in sdk.calls if name == "instant_run"]


@pytest.mark.parametrize("change", [{"request_id": "wrong"}, {"capture_id": "wrong"},
    {"image_size": {"width": 99, "height": 80}}])
def test_wrong_grounding_request_capture_and_size_never_dispatch(tmp_path, change):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            prepared = await opened.agent_prepare(CLICK, "original")
            result = found(prepared["current_agent"])
            result.update(change)
            with pytest.raises(ValueError, match="does not match"):
                await opened.agent_resolve(result)
    asyncio.run(scenario())
    assert sdk.inputs == []
    assert len([args for name, args in sdk.calls if name == "instant_run"]) == 1


def test_pending_and_transport_timeout_read_original_receipt_without_resubmit(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    sdk.pending_once.add("original")
    sdk.timeout_once.add("resolve-original")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            assert (await opened.agent_prepare(CLICK, "original"))["status"] == "pending"
            prepared = await opened.agent_prepare(CLICK, "original")
            assert prepared["status"] == "awaiting_grounding"
            with pytest.raises(ValueError, match="request_id_conflict"):
                await opened.agent_prepare({**CLICK, "request": {"goal": "Other"}}, "original")
            unknown = await opened.agent_resolve(found(prepared["current_agent"]), "resolve-original", total_timeout=.01)
            assert unknown["status"] == "result_unknown"
            with pytest.raises(ValueError, match="not_ready"):
                await opened.agent_continue()
            ready = await opened.agent_status()
            assert ready["status"] == "grounding_ready"
            await opened.agent_continue("continue-original")
    asyncio.run(scenario())
    sent = [args["request_id"] for name, args in sdk.calls if name == "instant_run"]
    assert sent == ["original", "resolve-original", "continue-original"]
    assert [args["request_id"] for name, args in sdk.calls if name == "instant_result"] == ["original", "resolve-original"]
    assert sdk.inputs == ["original"]


def test_cancel_awaiting_grounding_keeps_original_identity_until_real_terminal(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            await opened.agent_prepare(CLICK, "original")
            cancelled = await opened.agent_cancel("cancel-outer")
            assert cancelled["status"] == "cancelled"
            assert cancelled["current_agent"]["runtime_terminal"] is True
            assert cancelled["current_agent"]["command_id"] == "original"
            assert cancelled["current_agent"]["action_executed"] is False
            with pytest.raises(ValueError, match="cancelled"):
                await opened.agent_prepare(CLICK)
            assert (await opened.agent_complete())["status"] == "completed"
    asyncio.run(scenario())
    controls = [args for name, args in sdk.calls if name == "instant_run" and args["command"]["kind"] != "step"]
    assert controls[0]["request_id"] == "cancel-outer"
    assert all(args["command"]["request"]["command_id"] == "original" for args in controls)
    assert len({args["request_id"] for args in controls}) == len(controls)
    assert sdk.inputs == []


def test_cancellation_wait_expiry_does_not_claim_cancelled(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    sdk.cancel_stays_running = True
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            await opened.agent_prepare(CLICK, "original")
            cancelling = await opened.agent_cancel("cancel-outer", total_timeout=.01)
            assert cancelling["status"] == "cancelling"
            assert cancelling["current_agent"]["runtime_terminal"] is False
            with pytest.raises(ValueError, match="completion_requires"):
                await opened.agent_complete()
            with pytest.raises(ValueError, match="not_ready"):
                await opened.agent_continue()
    asyncio.run(scenario())
    assert sdk.inputs == []


def test_unknown_input_and_wrong_worker_cannot_be_verified_or_replayed(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    sdk.unknown_input = True
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            prepared = await opened.agent_prepare(CLICK, "original")
            await opened.agent_resolve(found(prepared["current_agent"]))
            assert (await opened.agent_continue())["status"] == "result_unknown"
            with pytest.raises(ValueError, match="terminal_receipt_required"):
                await opened.agent_verify("success")
            with pytest.raises(ValueError, match="completion_requires"):
                await opened.agent_complete()
            with pytest.raises(ValueError, match="verification_or_terminal_required"):
                await opened.agent_prepare(CLICK)
            sdk.wrong_worker = True
            with pytest.raises(ValueError, match="command_identity_mismatch"):
                await opened.agent_status()
            assert opened.current_agent_state["phase"] == "result_unknown"
    asyncio.run(scenario())
    assert sdk.inputs == ["original"]


def test_absent_target_cannot_continue_and_cancel_is_explicit(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            state = (await opened.agent_prepare(CLICK, "original"))["current_agent"]
            result = await opened.agent_resolve(found(state, status="absent"))
            assert result["status"] == "grounding_rejected"
            with pytest.raises(ValueError, match="not_ready"):
                await opened.agent_continue()
            await opened.agent_cancel()
    asyncio.run(scenario())
    assert sdk.inputs == []


def test_original_admission_image_missing_queries_worker_and_keeps_original_pixels(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    sdk.first_image_unavailable = True
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            result = await opened.agent_prepare(CLICK, "original")
            assert result["status"] == "awaiting_grounding"
            assert result["current_agent"]["original_image"]["sha256"] == sdk.captures[0]["sha256"]
    asyncio.run(scenario())
    commands = [args["command"] for name, args in sdk.calls if name == "instant_run"]
    assert [command["kind"] for command in commands] == ["step", "agent_command_status"]
    assert len(sdk.captures) == 1


@pytest.mark.parametrize("options", [{"recognition_source": "external_api"},
    {"model_directory": Path("model")}, {"prepare_models": True},
    {"api_profile": Path("api.json")}, {"decision_profile": Path("decision.json")},
    {"delegate_profile": "other-agent"}])
def test_mode_never_accepts_other_model_configuration(tmp_path, options):
    with pytest.raises(ValueError, match="current_agent_"):
        CurrentAgentClient(root=tmp_path, data_root=tmp_path / "data", **options)


def test_no_implicit_external_models_and_state_is_a_detached_snapshot(tmp_path, monkeypatch):
    import socket
    import subprocess
    def forbidden(*args, **kwargs):
        pytest.fail("Current-Agent adapter must not start another client or connect to a model")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            snapshot = opened.current_agent_state
            snapshot["vision_capabilities"]["current_vision"] = "unsupported"
            assert opened.current_agent_state["vision_capabilities"]["current_vision"] == "supported"
            await opened.agent_prepare(CLICK, "original")
            assert "--recognition-source" in sdk.params["args"]
            assert sdk.params["args"][sdk.params["args"].index("--recognition-source") + 1] == "agent_current"
            assert not any("profile" in argument or "model-directory" in argument for argument in sdk.params["args"])
    asyncio.run(scenario())


def test_concurrent_prepare_resolve_and_continue_dispatch_only_once(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            results = await asyncio.gather(opened.agent_prepare(CLICK, "original"),
                opened.agent_prepare(CLICK, "competing"), return_exceptions=True)
            assert sum(isinstance(result, ValueError) for result in results) == 1
            state = opened.current_agent_state
            resolved = await asyncio.gather(opened.agent_resolve(found(state)), opened.agent_resolve(found(state)))
            assert all(result["status"] == "grounding_ready" for result in resolved)
            results = await asyncio.gather(opened.agent_continue(), opened.agent_continue(), return_exceptions=True)
            assert sum(isinstance(result, ValueError) for result in results) == 1
    asyncio.run(scenario())
    kinds = [args["command"]["kind"] for name, args in sdk.calls if name == "instant_run"]
    assert kinds == ["step", "grounding_resolve", "agent_command_continue"]
    assert sdk.inputs == ["original"]


def test_invalid_timeout_and_reused_ids_do_not_poison_unsent_state(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            before = opened.current_agent_state
            with pytest.raises(ValueError, match="timeout_invalid"):
                await opened.agent_prepare(CLICK, "not-sent", total_timeout=0)
            assert opened.current_agent_state == before
            prepared = await opened.agent_prepare(CLICK, "original")
            result = found(prepared["current_agent"])
            with pytest.raises(ValueError, match="timeout_invalid"):
                await opened.agent_resolve(result, "not-sent", total_timeout=0)
            with pytest.raises(ValueError, match="outer_request_id_reused"):
                await opened.agent_resolve(result, "original")
            assert opened.current_agent_state["phase"] == "awaiting_grounding"
            await opened.agent_resolve(result, "resolve")
            with pytest.raises(ValueError, match="outer_request_id_reused"):
                await opened.agent_cancel("resolve")
            assert opened.current_agent_state["cancel_requested"] is False
            assert (await opened.agent_cancel("cancel"))["status"] == "cancelled"
    asyncio.run(scenario())
    assert [args["request_id"] for name, args in sdk.calls if name == "instant_run"][:3] == ["original", "resolve", "cancel"]


def test_pending_read_only_observation_never_releases_verification_gate(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            prepared = await opened.agent_prepare(CLICK, "original")
            await opened.agent_resolve(found(prepared["current_agent"]))
            await opened.agent_continue()
            sdk.pending_once.add("observe")
            observed = await opened.call("instant_run", {"request_id": "observe", "command": {"kind": "capture"}})
            assert observed["status"] == "pending"
            assert opened.current_agent_state["phase"] == "pending"
            adopted = await opened.agent_status()
            assert adopted["status"] == "verification_required"
            with pytest.raises(ValueError, match="verification_or_terminal_required"):
                await opened.agent_prepare(CLICK)
            await opened.agent_verify("success", verification(opened.current_agent_state))
    asyncio.run(scenario())
    assert sdk.inputs == ["original"]


def test_local_original_image_tamper_blocks_resolve_and_continue(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            prepared = await opened.agent_prepare(CLICK, "original")
            state = prepared["current_agent"]
            image = Path(state["original_image"]["image_path"])
            original = image.read_bytes()
            Image.new("RGB", (100, 80), "red").save(image)
            with pytest.raises(ValueError, match="image_hash_mismatch"):
                await opened.agent_resolve(found(state))
            image.write_bytes(original)
            await opened.agent_resolve(found(state))
            Image.new("RGB", (100, 80), "red").save(image)
            with pytest.raises(ValueError, match="image_hash_mismatch"):
                await opened.agent_continue()
    asyncio.run(scenario())
    assert sdk.inputs == []


def test_verification_requires_this_terminal_after_image_and_uncertain_stays_blocked(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            prepared = await opened.agent_prepare(CLICK, "original")
            await opened.agent_resolve(found(prepared["current_agent"]))
            state = (await opened.agent_continue("continued"))["current_agent"]
            assert state["verification_image"]["sha256"] != state["original_image"]["sha256"]
            for payload in [None, {}, {**verification(state), "request_id": "wrong"},
                            {**verification(state), "capture_id": "wrong"},
                            {**verification(state), "sha256": state["original_image"]["sha256"]}]:
                with pytest.raises(ValueError, match="verification_binding_invalid"):
                    await opened.agent_verify("success", payload)
            uncertain = await opened.agent_verify("uncertain")
            assert uncertain["status"] == "verification_required"
            with pytest.raises(ValueError, match="verification_or_terminal_required"):
                await opened.agent_prepare(CLICK)
            image = Path(state["verification_image"]["image_path"])
            pixels = image.read_bytes()
            Image.new("RGB", (100, 80), "red").save(image)
            with pytest.raises(ValueError, match="image_hash_mismatch"):
                await opened.agent_verify("success", verification(state))
            image.write_bytes(pixels)
            assert (await opened.agent_verify("failure", verification(state)))["status"] == "verified"
    asyncio.run(scenario())


def test_missing_terminal_after_must_be_read_before_success_and_rejected_input_cannot_succeed(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            state = (await opened.agent_prepare(CLICK, "original"))["current_agent"]
            await opened.agent_resolve(found(state))
            sdk.drop_image = True
            await opened.agent_continue()
            assert opened.current_agent_state["verification_image"] is None
            with pytest.raises(ValueError, match="verification_image_required"):
                await opened.agent_verify("success", {})
            sdk.drop_image = False
            state = (await opened.agent_status())["current_agent"]
            await opened.agent_verify("success", verification(state))
            await opened.agent_prepare(CLICK, "second")
            sdk.workers["second"].update(status="failed", pending_grounding=None, action_executed=False)
            await opened.agent_status()
            with pytest.raises(ValueError, match="success_requires_completed_input"):
                await opened.agent_verify("success", {})
            assert (await opened.agent_verify("failure"))["status"] == "verified"
    asyncio.run(scenario())


def test_ambient_decision_profile_is_removed_only_from_current_session_environment(tmp_path, monkeypatch):
    import os
    from unittest.mock import patch
    from app.instant_mcp import InstantSession
    monkeypatch.setenv("AGENT_GUI_DECISION_PROFILE", str(tmp_path / "external.json"))
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            assert "AGENT_GUI_DECISION_PROFILE" not in sdk.params["env"]
            assert os.environ["AGENT_GUI_DECISION_PROFILE"].endswith("external.json")
            with patch.dict(os.environ, sdk.params["env"], clear=True):
                session = InstantSession(opened.root, opened.data_root, recognition_source="agent_current")
                assert session.decision_profile is None
    asyncio.run(scenario())


def test_selected_window_binding_and_cancel_after_action_block_later_input(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            await opened.execute({"request_id": "select", "command": {"kind": "select", "handle": 12, "process_id": 34}})
            assert opened.current_agent_state["selected_target"] == {"handle": 12, "process_id": 34}
            prepared = await opened.agent_prepare(CLICK, "original")
            await opened.agent_resolve(found(prepared["current_agent"]))
            terminal = await opened.agent_continue()
            cancelled = await opened.agent_cancel()
            assert cancelled["current_agent"]["runtime_status"] == "completed"
            assert cancelled["current_agent"]["cancel_requested"] is True
            await opened.agent_verify("failure", verification(terminal["current_agent"]))
            with pytest.raises(ValueError, match="cancelled"):
                await opened.agent_prepare(CLICK)
            await opened.agent_complete()
    asyncio.run(scenario())
    assert sdk.inputs == ["original"]


def test_declared_capture_size_must_match_original_png_before_grounding(tmp_path, monkeypatch):
    sdk = CurrentSDK(tmp_path / "runtime")
    original_run = sdk._run
    def wrong_size(request_id, command):
        result = original_run(request_id, command)
        if command["kind"] == "step":
            result["result"]["pending_grounding"]["capture"]["image_size"]["width"] = 99
        return result
    monkeypatch.setattr(sdk, "_run", wrong_size)
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            with pytest.raises(ValueError, match="image_size_mismatch"):
                await opened.agent_prepare(CLICK, "original")
            assert opened.current_agent_state["phase"] == "result_unknown"
    asyncio.run(scenario())
    assert sdk.inputs == []


def test_current_agent_administrator_is_rejected_before_connection(tmp_path):
    sdk = CurrentSDK(tmp_path / "runtime")
    with pytest.raises(ValueError, match="^current_agent_administrator_unsupported$"):
        client(tmp_path, sdk, administrator=True)
    assert sdk.calls == []
    assert sdk.session_enters == 0


@pytest.mark.parametrize("name", ["", " Codex", "Codex ", "Code\nx", "Code\tx", "Code\x00x", "Code\x7fx", "x" * 129, None])
def test_sdk_client_name_rejects_outer_whitespace_and_control_characters(tmp_path, name):
    with pytest.raises(ValueError, match="^current_agent_client_name_invalid$"):
        CurrentAgentClient(root=tmp_path, data_root=tmp_path / "data", client_name=name)
