"""Explicit current-Agent handoff on one ExecutionClient connection.

The caller reads original images, supplies grounding, and verifies the outcome.
This adapter never invokes a model or grants input permission.  The first
version deliberately admits only ordinary recognition clicks as input.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
from time import monotonic
from uuid import uuid4

from scripts.execution_client import ExecutionClient
from scripts.learning_benchmark_client import BenchmarkCallError


@dataclass
class CurrentAgentState:
    phase: str = "idle"
    command_id: str | None = None
    current_request_id: str | None = None
    pending_request_id: str | None = None
    pending_operation: str | None = None
    runtime_status: str | None = None
    runtime_terminal: bool = False
    action_executed: bool | None = None
    pending_grounding_request_id: str | None = None
    capture_id: str | None = None
    image_size: dict | None = None
    grounding_capture: dict | None = None
    image_delivery: list = field(default_factory=list)
    original_image: dict | None = None
    verification_image: dict | None = None
    verification_request_id: str | None = None
    selected_target: dict | None = None
    resolved_status: str | None = None
    cancel_requested: bool = False
    verification: dict | None = None
    completed: bool = False


class CurrentAgentClient(ExecutionClient):
    """Persistent, serial click/grounding/verification session for its caller."""

    def __init__(self, *, root: Path, data_root: Path, client_name="current-agent",
                 client_vision_capabilities: dict | None = None, **options):
        from app.vision.recognition_source import ClientVisionCapabilities

        if (not isinstance(client_name, str) or not client_name or client_name != client_name.strip()
                or len(client_name) > 128
                or any(ord(character) < 32 or ord(character) == 127 for character in client_name)):
            raise ValueError("current_agent_client_name_invalid")
        if options.get("administrator", False) is True:
            # UAC's worker rebuilds its own environment.  The first adapter
            # cannot prove ambient Decision profiles stay disabled there.
            raise ValueError("current_agent_administrator_unsupported")
        if options.get("recognition_source") not in {None, "agent_current"}:
            raise ValueError("current_agent_recognition_source_conflict")
        if any(options.get(key) is not None for key in
               ("api_profile", "decision_profile", "delegate_profile", "model_directory")):
            raise ValueError("current_agent_model_configuration_forbidden")
        if options.get("prepare_models", False) is not False:
            raise ValueError("current_agent_prepare_models_forbidden")
        if client_vision_capabilities is not None and not isinstance(client_vision_capabilities, dict):
            raise ValueError("current_agent_capabilities_invalid")
        try:
            capabilities = ClientVisionCapabilities.model_validate(client_vision_capabilities or {})
        except ValueError:
            raise ValueError("current_agent_capabilities_invalid") from None
        options["recognition_source"] = "agent_current"
        super().__init__(root=root, data_root=data_root, **options)
        parameter_factory = self._params_factory

        def current_agent_parameters(**parameters):
            # InstantSession and DecisionService otherwise adopt this ambient
            # profile even when no --decision-profile argument was supplied.
            environment = dict(parameters.get("env") or {})
            for name in tuple(environment):
                if name.upper() == "AGENT_GUI_DECISION_PROFILE":
                    environment.pop(name)
            parameters["env"] = environment
            if parameter_factory is not None:
                return parameter_factory(**parameters)
            from mcp import StdioServerParameters
            return StdioServerParameters(**parameters)

        self._params_factory = current_agent_parameters
        self.client_name = client_name
        self._capabilities = capabilities.model_dump()
        self._agent_state = CurrentAgentState()
        self._agent_lock = asyncio.Lock()
        self._requests = {}
        self._click_commands = {}
        self._resolved_result = None
        self._last_receipt = None

    @property
    def current_agent_state(self):
        value = asdict(self._agent_state)
        value.update(mode="current_agent", client_name=self.client_name,
            recognition_source="agent_current", vision_capabilities=deepcopy(self._capabilities),
            missing_capabilities=[key for key in ("image_transport", "current_vision")
                                  if self._capabilities[key] != "supported"],
            actions_enabled=self.allow_actions, automatic_retry_allowed=False,
            connection_active=self._session is not None,
            capability_status="eligible" if all(self._capabilities[key] == "supported"
                for key in ("image_transport", "current_vision")) else "unavailable",
            cleanup_verified=(self.status or {}).get("cleanup_verified") is True)
        return value

    def _response(self, receipt=None):
        value = {"status": self._agent_state.phase, "current_agent": self.current_agent_state,
                 "automatic_retry_allowed": False}
        if receipt is not None:
            value["receipt"] = self._compact_response(receipt)
        return value

    @staticmethod
    def _request_id(value, prefix):
        from app.core.instant_attachment_transport import _validate_request_id
        value = prefix + "-" + uuid4().hex if value is None else value
        _validate_request_id(value)
        return value

    @staticmethod
    def _timeout(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("current_agent_timeout_invalid")
        return value

    def _require_new_input(self):
        state = self._agent_state
        if state.completed:
            raise ValueError("current_agent_completed")
        if state.cancel_requested:
            raise ValueError("current_agent_cancelled")
        if state.pending_request_id or state.phase not in {"idle", "verified"}:
            raise ValueError("current_agent_verification_or_terminal_required")

    def _click_command(self, request_id, command):
        if not isinstance(command, dict):
            raise ValueError("current_agent_click_command_required")
        command = deepcopy(command)
        if (command.get("kind") != "step" or command.get("operation") != "execute_recognition_plan"
                or set(command) - {"kind", "operation", "request", "vision_capabilities"}
                or not isinstance(command.get("request"), dict)
                or set(command["request"]) - {"goal", "click_kind"}):
            raise ValueError("current_agent_command_unsupported")
        if "vision_capabilities" in command and command["vision_capabilities"] != self._capabilities:
            # Partial declarations are accepted only when they mean the frozen capabilities.
            from app.vision.recognition_source import ClientVisionCapabilities
            if ClientVisionCapabilities.model_validate(command["vision_capabilities"]).model_dump() != self._capabilities:
                raise ValueError("current_agent_capabilities_conflict")
        missing = [key for key in ("image_transport", "current_vision")
                   if self._capabilities[key] != "supported"]
        if missing:
            raise ValueError("current_agent_vision_capability_required")
        command["vision_capabilities"] = deepcopy(self._capabilities)
        return self._normalize_command(request_id, command)

    def _unknown(self, request_id, purpose):
        self._agent_state.phase = "result_unknown"
        self._agent_state.pending_request_id = request_id
        self._agent_state.pending_operation = purpose

    def _new_outer_id(self, request_id, purpose, total_timeout):
        self._timeout(total_timeout)
        request_id = self._request_id(request_id, "current-" + purpose)
        if request_id in self._requests:
            raise ValueError("current_agent_outer_request_id_reused")
        return request_id

    async def _send(self, purpose, command, request_id=None, *, total_timeout=30):
        total_timeout = self._timeout(total_timeout)
        request_id = self._new_outer_id(request_id, purpose, total_timeout)
        command = self._normalize_command(request_id, command)
        # Reserve before transmission.  Any transport failure must be read, never replayed.
        self._requests[request_id] = {"purpose": purpose, "command": deepcopy(command),
                                      "resume_phase": self._agent_state.phase}
        self._agent_state.current_request_id = request_id
        self._agent_state.pending_request_id = request_id
        self._agent_state.pending_operation = purpose
        try:
            receipt = await asyncio.wait_for(super().call("instant_run", {
                "request_id": request_id, "command": command,
                "wait_ms": min(int(total_timeout * 1000), 25000),
                "detail": "full", "images": "after"}), timeout=total_timeout)
            self._consume(receipt, request_id, purpose)
            return receipt
        except BenchmarkCallError as error:
            receipt = error.response or {}
            self._last_receipt = deepcopy(receipt)
            if receipt.get("accepted") is False and receipt.get("action_executed") is False:
                state = self._agent_state
                state.pending_request_id = state.pending_operation = None
                if purpose == "prepare":
                    state.runtime_terminal, state.runtime_status, state.phase = True, "rejected", "verification_required"
                    state.action_executed = False
            else:
                self._unknown(request_id, purpose)
            raise
        except TimeoutError:
            self._unknown(request_id, purpose)
            return {"request_id": request_id, "status": "result_unknown", "wait_expired": True,
                    "automatic_retry_allowed": False, "no_replay": True}
        except BaseException:
            self._unknown(request_id, purpose)
            raise

    @staticmethod
    def _verify_image(row, capture=None, image_size=None):
        from PIL import Image
        if (not isinstance(row, dict) or row.get("status") != "saved"
                or row.get("original_pixels") is not True or not isinstance(row.get("image_path"), str)):
            raise ValueError("current_agent_original_image_required")
        pixels = Path(row["image_path"]).read_bytes()
        digest = sha256(pixels).hexdigest()
        if digest != row.get("sha256") or capture is not None and digest != capture.get("sha256"):
            raise ValueError("current_agent_image_hash_mismatch")
        with Image.open(BytesIO(pixels)) as image:
            if image.format != "PNG":
                raise ValueError("current_agent_original_image_required")
            if image_size and {"width": image.width, "height": image.height} != image_size:
                raise ValueError("current_agent_image_size_mismatch")
            image.verify()

    def _bind_grounding(self, pending, delivery):
        state = self._agent_state
        if not isinstance(pending, dict) or not isinstance(pending.get("request_id"), str):
            raise ValueError("current_agent_grounding_binding_invalid")
        capture = pending.get("capture")
        if (not isinstance(capture, dict) or not isinstance(capture.get("capture_id"), str)
                or not isinstance(capture.get("sha256"), str)
                or not isinstance(capture.get("image_size"), dict)
                or any(type(capture["image_size"].get(key)) is not int or capture["image_size"][key] <= 0
                       for key in ("width", "height"))):
            raise ValueError("current_agent_grounding_capture_invalid")
        binding = deepcopy(capture)
        if state.pending_grounding_request_id == pending["request_id"]:
            if state.grounding_capture != binding:
                raise ValueError("current_agent_grounding_capture_changed")
        else:
            if state.pending_grounding_request_id is not None:
                raise ValueError("current_agent_grounding_request_changed")
            state.resolved_status = None
            self._resolved_result = None
            state.original_image = None
        state.pending_grounding_request_id = pending["request_id"]
        state.capture_id = capture["capture_id"]
        state.image_size = deepcopy(capture["image_size"])
        state.grounding_capture = binding
        identity = capture.get("window_identity")
        if isinstance(identity, dict):
            if state.selected_target and any(state.selected_target.get(key) != identity.get(key)
                                             for key in ("handle", "process_id")):
                raise ValueError("current_agent_selected_target_mismatch")
            state.selected_target = deepcopy(identity)
        for row in delivery:
            if row.get("status") != "saved" or row.get("sha256") != capture["sha256"]:
                continue
            self._verify_image(row, capture, state.image_size)
            state.original_image = deepcopy(row)
        state.image_delivery = deepcopy(delivery)

    def _bind_verification_image(self, receipt, result, request_id):
        state = self._agent_state
        observation = result.get("observation") or receipt.get("observation") or {}
        capture = observation.get("capture") or observation
        if not isinstance(capture, dict) or not isinstance(capture.get("sha256"), str):
            return
        for row in receipt.get("image_delivery", []):
            if row.get("view") != "after" or row.get("status") != "saved" or row.get("sha256") != capture["sha256"]:
                continue
            self._verify_image(row, capture, capture.get("image_size"))
            state.verification_image = {**deepcopy(row), "request_id": request_id}
            if capture.get("capture_id") is not None:
                state.verification_image["capture_id"] = capture["capture_id"]
            state.verification_request_id = request_id

    def _consume(self, receipt, request_id, purpose):
        state = self._agent_state
        if receipt.get("request_id") != request_id:
            raise ValueError("current_agent_receipt_request_id_mismatch")
        self._last_receipt = deepcopy(receipt)
        if receipt.get("status") in {"pending", "result_unknown", "not_found"}:
            state.phase = "result_unknown" if receipt["status"] != "pending" else "pending"
            return
        state.pending_request_id = state.pending_operation = None
        if purpose == "setup":
            command = self._requests[request_id]["command"]
            if command["kind"] == "select" and receipt.get("operation_succeeded") is True:
                window = (receipt.get("result") or {}).get("window")
                if not isinstance(window, dict) or any(window.get(key) != command[key]
                                                       for key in ("handle", "process_id")):
                    raise ValueError("current_agent_selected_target_mismatch")
                state.selected_target = deepcopy(window)
            state.phase = self._requests[request_id]["resume_phase"]
            return
        result = receipt.get("result")
        if purpose == "resolve":
            if (not isinstance(result, dict) or result.get("contract_version") != "grounding_handoff.v1"
                    or result.get("request_id") != state.pending_grounding_request_id):
                raise ValueError("current_agent_resolve_binding_invalid")
            self._bind_grounding(result, receipt.get("image_delivery", []))
            state.resolved_status = result.get("phase")
            state.phase = "grounding_ready" if state.resolved_status == "grounding_ready" else "grounding_rejected"
            return
        if (not isinstance(result, dict) or result.get("contract_version") != "agent_command.v1"
                or result.get("command_id") != state.command_id):
            raise ValueError("current_agent_command_identity_mismatch")
        if receipt.get("worker_status") == "result_unknown":
            self._unknown(request_id, purpose)
            return
        previous_status = state.runtime_status
        state.runtime_status = result.get("status")
        state.cancel_requested = state.cancel_requested or result.get("cancel_requested") is True
        state.action_executed = result.get("action_executed")
        state.image_delivery = deepcopy(receipt.get("image_delivery", []))
        if state.runtime_status in {"completed", "failed", "cancelled"}:
            state.runtime_terminal = True
            self._bind_verification_image(receipt, result, request_id)
            state.pending_grounding_request_id = None
            unknown = state.action_executed is None or any(
                row.get("status") == "unknown" for row in result.get("dispatch_attempts", []))
            if unknown:
                state.phase = "result_unknown"
            elif state.verification and previous_status == state.runtime_status:
                state.phase = "verified" if state.verification["verdict"] != "uncertain" else "verification_required"
            elif state.runtime_status == "cancelled" and state.action_executed is False:
                state.phase = "cancelled"
            else:
                state.phase = "verification_required"
        elif state.cancel_requested:
            # cancel_requested can still carry awaiting_grounding with pending=None.
            state.phase = "cancelling"
        elif state.runtime_status == "awaiting_grounding":
            self._bind_grounding(result.get("pending_grounding"), receipt.get("image_delivery", []))
            state.phase = ("grounding_ready" if state.resolved_status == "grounding_ready" else
                           "grounding_rejected" if state.resolved_status else
                           "awaiting_grounding" if state.original_image else "image_required")
        elif state.runtime_status == "running":
            state.phase = "running"
            state.pending_grounding_request_id = None
        elif state.runtime_status in {"awaiting_field_review", "awaiting_pre_action_review"}:
            state.phase = "review_required"
        else:
            raise ValueError("current_agent_worker_status_invalid")

    async def _read_pending(self, *, total_timeout=30):
        state = self._agent_state
        request_id, purpose = state.pending_request_id, state.pending_operation
        try:
            receipt = await asyncio.wait_for(super().call("instant_result", {
                "request_id": request_id, "detail": "full", "images": "after"}),
                timeout=self._timeout(total_timeout))
            self._consume(receipt, request_id, purpose)
            return receipt
        except TimeoutError:
            self._unknown(request_id, purpose)
            return {"request_id": request_id, "status": "result_unknown", "no_replay": True}
        except BaseException:
            self._unknown(request_id, purpose)
            raise

    async def _agent_status_locked(self, request_id=None, *, total_timeout=30):
        self._timeout(total_timeout)
        state = self._agent_state
        if state.completed:
            return self._response()
        if state.pending_request_id:
            if request_id is not None and request_id != state.pending_request_id:
                raise ValueError("current_agent_pending_receipt_id_required")
            return self._response(await self._read_pending(total_timeout=total_timeout))
        if state.command_id is None:
            if request_id is not None:
                self._request_id(request_id, "current-status")
            return self._response()
        receipt = await self._send("status", {"kind": "agent_command_status",
            "request": {"command_id": state.command_id}}, request_id, total_timeout=total_timeout)
        return self._response(receipt)

    async def agent_prepare(self, command, request_id=None, *, total_timeout=30):
        async with self._agent_lock:
            self._timeout(total_timeout)
            request_id = self._request_id(request_id, "current-command")
            command = self._click_command(request_id, command)
            if request_id in self._click_commands:
                if self._click_commands[request_id] != command:
                    raise ValueError("current_agent_request_id_conflict")
                if request_id != self._agent_state.command_id:
                    raise ValueError("current_agent_historical_command_no_replay")
                return await self._agent_status_locked(total_timeout=total_timeout)
            self._require_new_input()
            self._check_command("instant_run", {"request_id": request_id, "command": command})
            if request_id in self._requests:
                raise ValueError("current_agent_outer_request_id_reused")
            target = self._agent_state.selected_target
            self._agent_state = CurrentAgentState(command_id=request_id, selected_target=deepcopy(target), phase="preparing")
            self._resolved_result = None
            self._click_commands[request_id] = deepcopy(command)
            receipt = await self._send("prepare", command, request_id, total_timeout=total_timeout)
            # Original admission receipts can lack a deliverable image.  A new
            # read-only worker query obtains the same capture; never recapture it.
            if self._agent_state.phase == "image_required":
                return await self._agent_status_locked(total_timeout=total_timeout)
            return self._response(receipt)

    async def agent_resolve(self, result, request_id=None, *, total_timeout=30):
        from app.vision.grounding_contract import validate_grounding_result
        async with self._agent_lock:
            self._timeout(total_timeout)
            state = self._agent_state
            if state.cancel_requested or state.completed or state.pending_request_id:
                raise ValueError("current_agent_not_awaiting_grounding")
            if state.phase not in {"awaiting_grounding", "grounding_ready", "grounding_rejected"} or state.original_image is None:
                raise ValueError("current_agent_original_image_required")
            validated = validate_grounding_result(result,
                request_id=state.pending_grounding_request_id, capture_id=state.capture_id,
                image_size=(state.image_size["width"], state.image_size["height"])).model_dump()
            if any(row["evidence_source"] != "agent_visual" for row in validated["candidates"]):
                raise ValueError("current_agent_grounding_source_invalid")
            if self._resolved_result is not None:
                if self._resolved_result != validated:
                    raise ValueError("current_agent_grounding_result_conflict")
                return self._response(self._last_receipt)
            request_id = self._new_outer_id(request_id, "resolve", total_timeout)
            self._verify_image(state.original_image, state.grounding_capture, state.image_size)
            self._resolved_result = deepcopy(validated)
            receipt = await self._send("resolve", {"kind": "grounding_resolve", "request": {
                "grounding_request_id": state.pending_grounding_request_id, "result": validated}},
                request_id, total_timeout=total_timeout)
            return self._response(receipt)

    async def agent_continue(self, request_id=None, *, total_timeout=30):
        async with self._agent_lock:
            state = self._agent_state
            if state.completed or state.cancel_requested or state.pending_request_id or state.phase != "grounding_ready":
                raise ValueError("current_agent_continue_not_ready")
            self._verify_image(state.original_image, state.grounding_capture, state.image_size)
            receipt = await self._send("continue", {"kind": "agent_command_continue", "request": {
                "command_id": state.command_id, "grounding_request_id": state.pending_grounding_request_id}},
                request_id, total_timeout=total_timeout)
            return self._response(receipt)

    async def agent_status(self, request_id=None, *, total_timeout=30):
        async with self._agent_lock:
            return await self._agent_status_locked(request_id, total_timeout=total_timeout)

    async def agent_cancel(self, request_id=None, *, total_timeout=30):
        async with self._agent_lock:
            state = self._agent_state
            if state.completed:
                raise ValueError("current_agent_completed")
            deadline = monotonic() + self._timeout(total_timeout)
            if state.pending_request_id:
                await self._read_pending(total_timeout=max(.001, deadline - monotonic()))
                if state.pending_request_id:
                    # Do not enqueue cancellation behind a receipt of unknown identity.
                    return self._response(self._last_receipt)
            if state.command_id is None:
                state.phase, state.cancel_requested = "cancelled", True
                return self._response()
            cancel_already_requested = state.cancel_requested
            if not state.runtime_terminal and not cancel_already_requested:
                request_id = self._new_outer_id(request_id, "cancel", max(.001, deadline - monotonic()))
            state.cancel_requested = True
            if not state.runtime_terminal and not cancel_already_requested:
                await self._send("cancel", {"kind": "agent_command_cancel", "request": {
                    "command_id": state.command_id}}, request_id,
                    total_timeout=max(.001, deadline - monotonic()))
            while not state.runtime_terminal and monotonic() < deadline:
                if state.phase == "result_unknown":
                    break
                await asyncio.sleep(min(self.poll_interval, max(0, deadline - monotonic())))
                if monotonic() >= deadline:
                    break
                await self._agent_status_locked(total_timeout=max(.001, deadline - monotonic()))
            return self._response(self._last_receipt)

    async def agent_verify(self, verdict, evidence=None):
        async with self._agent_lock:
            state = self._agent_state
            if not isinstance(verdict, str) or verdict not in {"success", "failure", "uncertain"}:
                raise ValueError("current_agent_verdict_invalid")
            if state.completed or not state.runtime_terminal or state.phase == "result_unknown":
                raise ValueError("current_agent_terminal_receipt_required")
            try:
                evidence = json.loads(json.dumps(evidence, ensure_ascii=False, allow_nan=False))
            except (ValueError, TypeError):
                raise ValueError("current_agent_verification_evidence_invalid") from None
            if verdict == "success" and (state.runtime_status != "completed" or state.action_executed is not True):
                raise ValueError("current_agent_success_requires_completed_input")
            if verdict != "uncertain" and state.action_executed is True:
                image = state.verification_image
                if image is None:
                    raise ValueError("current_agent_verification_image_required")
                if (not isinstance(evidence, dict)
                        or evidence.get("request_id") != state.verification_request_id
                        or evidence.get("sha256") != image["sha256"]
                        or evidence.get("capture_id") != image.get("capture_id")):
                    raise ValueError("current_agent_verification_binding_invalid")
                self._verify_image(image)
            state.verification = {"source": "caller_judgment", "command_id": state.command_id,
                                  "verdict": verdict, "evidence": evidence}
            state.phase = "verification_required" if verdict == "uncertain" else "verified"
            return self._response()

    async def agent_complete(self):
        async with self._agent_lock:
            state = self._agent_state
            if state.completed:
                return self._response()
            if state.pending_request_id or state.phase not in {"idle", "verified", "cancelled"}:
                raise ValueError("current_agent_completion_requires_verified_terminal")
            state.completed, state.phase = True, "completed"
            return self._response()

    async def call(self, name: str, args: dict | None = None):
        """Keep the legacy read/setup transport without an input escape hatch."""
        args = deepcopy(args) if args is not None else {}
        if not isinstance(args, dict):
            raise ValueError("current_agent_arguments_invalid")
        if name in {"instant_run", "instant_submit"}:
            if not {"request_id", "command"} <= set(args) or set(args) - {"request_id", "command", "wait_ms", "detail", "images"}:
                raise ValueError("current_agent_arguments_invalid")
            if not isinstance(args["command"], dict) or args["command"].get("kind") not in {"step", "discover", "capture", "read_text", "select"}:
                raise ValueError("current_agent_command_unsupported")
            wait_ms = args.get("wait_ms", 30000)
            if type(wait_ms) is not int or not 0 < wait_ms <= 120000:
                raise ValueError("current_agent_wait_ms_invalid")
            if args.get("detail", "compact") not in {"compact", "full"} or args.get("images", "after") not in {"none", "after", "both"}:
                raise ValueError("current_agent_arguments_invalid")
            command = self._normalize_command(args["request_id"], args["command"])
            if command["kind"] == "step":
                return await self.agent_prepare(command, args["request_id"], total_timeout=wait_ms / 1000)
            if command["kind"] not in {"discover", "capture", "read_text", "select"}:
                raise ValueError("current_agent_command_unsupported")
            async with self._agent_lock:
                if self._agent_state.completed:
                    raise ValueError("current_agent_completed")
                if command["kind"] == "select":
                    self._require_new_input()
                if self._agent_state.pending_request_id:
                    raise ValueError("current_agent_pending_receipt_required")
                self._check_command("instant_run", {"request_id": args["request_id"], "command": command})
                return await self._send("setup", command, args["request_id"], total_timeout=wait_ms / 1000)
        if name not in {"instant_status", "instant_result", "instant_image"}:
            raise ValueError("current_agent_tool_unsupported")
        async with self._agent_lock:
            # Raw reads cannot release the adapter's verification gate.  Use
            # agent_status to adopt an in-flight receipt into the state object.
            return await super().call(name, args)

    async def run(self, request_id, command, *, total_timeout=120):
        self._timeout(total_timeout)
        return await self.call("instant_run", {"request_id": request_id, "command": command,
            "wait_ms": max(1, min(120000, int(total_timeout * 1000)))})

    async def run_plan(self, *args, **kwargs):
        raise ValueError("current_agent_command_unsupported")

    async def execute(self, message: dict):
        if not isinstance(message, dict):
            raise ValueError("current_agent_message_invalid")
        if "action" not in message:
            if "tool" in message:
                if set(message) != {"tool", "arguments"}:
                    raise ValueError("current_agent_tool_message_invalid")
                return await self.call(message["tool"], message["arguments"])
            if not {"request_id", "command"} <= set(message) or set(message) - {"request_id", "command", "total_timeout", "detail"}:
                raise ValueError("current_agent_message_invalid")
            return await self.run(message["request_id"], message["command"], total_timeout=message.get("total_timeout", 120))
        action = message["action"]
        allowed = {
            "agent_prepare": {"command", "request_id", "total_timeout"},
            "agent_resolve": {"result", "request_id", "total_timeout"},
            "agent_continue": {"request_id", "total_timeout"},
            "agent_status": {"request_id", "total_timeout"},
            "agent_cancel": {"request_id", "total_timeout"},
            "agent_verify": {"verdict", "evidence"}, "agent_complete": set(),
        }
        if not isinstance(action, str) or action not in allowed or set(message) - {"action"} - allowed[action]:
            raise ValueError("current_agent_action_invalid")
        arguments = {key: value for key, value in message.items() if key != "action"}
        required = {"agent_prepare": "command", "agent_resolve": "result", "agent_verify": "verdict"}.get(action)
        if required and required not in arguments:
            raise ValueError("current_agent_action_arguments_invalid")
        return await getattr(self, action)(**arguments)


__all__ = ["CurrentAgentClient", "CurrentAgentState"]
