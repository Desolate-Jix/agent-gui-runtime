"""局部步骤试运行的持久记录；只提出 Instant 命令，绝不派发输入。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _atomic_write_bytes
from .receipt_adapter import ExecutionReceiptPending, resolve_execution_receipt
from .workflow_program import WorkflowProgramService, _id, _type, _reference, _variables
from .workflow_execution_strategy import command_step, execution_strategy, validate_execution_strategy


_RUN = re.compile(r"trial-[0-9a-f]{64}\Z")


def _read(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError("workflow_trial_file_invalid") from error
    if not isinstance(value, dict):
        raise ValueError("workflow_trial_file_invalid")
    return value


def _write(path, value):
    _atomic_write_bytes(path, canonical_json_bytes(value) + b"\n")


def _resolve(ref, inputs, outputs):
    source = ref["source"]
    if source == "constant":
        return ref["value"]
    if source == "input":
        return inputs.get(ref["name"])
    key = ref["step_id"] + "." + ref["name"]
    if key not in outputs:
        raise ValueError("workflow_trial_upstream_output_missing:" + key)
    return outputs[key]


def _conditions(conditions, inputs, outputs, observations):
    for condition in conditions:
        left = condition["left"]
        if left["source"] == "observation":
            if left["name"] not in observations:
                return "unknown"
            value = observations[left["name"]]
        else:
            try:
                value = _resolve(left, inputs, outputs)
            except ValueError:
                return "missing_output"
        operator = condition["operator"]
        if operator == "agent_assertion":
            if type(value) is not bool:
                return "unknown"
            matched = value
        elif operator == "exists":
            matched = value is not None
        elif operator == "contains":
            matched = isinstance(value, str) and isinstance(condition["value"], str) and condition["value"] in value
        else:
            matched = value == condition["value"]
            if operator == "not_eq":
                matched = not matched
        if not matched:
            return "false"
    return "true"


def _command(step, inputs, outputs):
    action = step["action"]
    kind = action["kind"]
    verification = step.get('verification') or {}
    # 共同编译入口保留精确等待字段，所有票据消费者必须重编一致。
    wait = {'observation_wait_ms': 0} if (step.get('review_status') == 'reviewed'
        and verification.get('kind') == 'agent_judgment' and verification.get('image_check')) else {}
    if kind == "click":
        request = {"goal": action["goal"], "click_kind": action.get("click_kind", "single")}
        if 'selection_intent' in action:
            request['selection_intent'] = action['selection_intent']
        if "target_memory" in action:
            request["target_memory"] = deepcopy(action["target_memory"])
        return {"kind": "step", "operation": "execute_recognition_plan", "request": request, **wait}
    if kind == "input_sequence":
        text = _resolve(action["text"], inputs, outputs)
        if not isinstance(text, str) or not 1 <= len(text) <= 20000:
            raise ValueError("workflow_trial_input_text_missing_or_invalid")
        request = {"field_goal": action["field_goal"], "text": text,
            "clear_existing": action["clear_existing"], "submit_search": action["submit_search"]}
        if "target_memory" in action:
            request["target_memory"] = deepcopy(action["target_memory"])
        return {"kind": "input_sequence", "request": request, **wait}
    if kind == "read_text":
        return {"kind": "read_text", "max_chars": 10000}
    if kind == "scroll":
        return {"kind": "step", "operation": "scroll", "request": {"direction": action["direction"], "wheel_clicks": action["amount"]}, **wait}
    # 焦点键盘动作需要现场确定坐标；无坐标时不生成似是而非的命令。
    raise ValueError("workflow_trial_press_key_requires_live_target")


def _verified_observation(receipt, session):
    capture = receipt.get("observation")
    if not isinstance(capture, dict):
        capture = (receipt.get("result") or {}).get("capture")
    if not isinstance(capture, dict) or not isinstance(capture.get("image_path"), str) or not isinstance(capture.get("sha256"), str):
        raise ValueError("workflow_trial_read_observation_missing")
    path = Path(capture["image_path"])
    path = (path if path.is_absolute() else session / path).resolve()
    if not path.is_relative_to(session) or not path.is_file():
        raise ValueError("workflow_trial_read_observation_invalid")
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(raw).hexdigest() != capture["sha256"]:
        raise ValueError("workflow_trial_read_observation_invalid")
    return {"sha256": capture["sha256"], "image_path": str(path), "capture_id": capture.get("capture_id")}


def _selection_context(state, step, command, execution_request_id):
    from .selection_satisfaction import selection_requested
    if not selection_requested(command.get("request")):
        return None
    base = deepcopy(command)
    base.pop("vision_capabilities", None)
    if base != _command(step, state["inputs"], state["outputs"]):
        raise ValueError("workflow_trial_selection_command_mismatch")
    return {"run_id": state["run_id"], "step_id": step["step_id"],
            "execution_request_id": execution_request_id,
            "command_sha256": hashlib.sha256(canonical_json_bytes(command)).hexdigest(),
            "action": deepcopy(step["action"]), "inputs": deepcopy(state["inputs"]),
            "outputs": {key: {"run_id": state["run_id"], "value": deepcopy(value)}
                        for key, value in state["outputs"].items()}}


def _receipt_state(receipt, receipt_path, request_id, command, *, terminal_snapshot=None, expected_context=None):
    command_path = receipt_path.parent.parent / "commands" / (request_id + ".json")
    if not command_path.is_file() or _read(command_path) != command:
        raise ValueError("workflow_trial_dispatched_command_mismatch")
    if receipt.get("command") != command:
        raise ValueError("workflow_trial_receipt_command_mismatch")
    try:
        receipt, terminal = resolve_execution_receipt(receipt, receipt_path, request_id,
                                                       terminal_snapshot=terminal_snapshot)
    except ExecutionReceiptPending as error:
        raise ValueError("workflow_trial_receipt_not_terminal") from error
    if receipt.get("status") not in {"returned", "failed"}:
        raise ValueError("workflow_trial_receipt_not_returned")
    result = receipt.get("result")
    if not isinstance(result, dict):
        if result is None and receipt["status"] == "failed":
            return False, terminal, None
        raise ValueError("workflow_trial_receipt_result_missing")
    if result.get("contract_version") == "agent_command.v1":
        raise ValueError("workflow_trial_agent_command_terminal_result_invalid")
    status = result.get("status")
    if status in {"running", "awaiting_grounding", "pending", "result_unknown"}:
        raise ValueError("workflow_trial_receipt_not_terminal")
    if receipt["status"] == "failed" or (terminal is not None and terminal["status"] != "completed"):
        return False, terminal, None
    if result.get("success") is False or result.get("phase") in {"failed", "rejected", "result_unknown"} or (isinstance(result.get("response"), dict) and result["response"].get("success") is False):
        return False, terminal, None
    if command["kind"] == "read_text":
        if status not in {"agent_read_required", "text_observed", "no_text_detected"}:
            raise ValueError("workflow_trial_read_status_invalid")
        if status != "agent_read_required" and result.get("contract_version") != "captured_text_v1":
            raise ValueError("workflow_trial_read_contract_invalid")
        return True, terminal, _verified_observation(receipt, receipt_path.parent.parent.resolve())
    if status is None and result.get("phase") != "returned":
        raise ValueError("workflow_trial_receipt_terminal_unproven")
    api = result.get("response")
    if not isinstance(api, dict) and command["kind"] == "step" and command["operation"] == "execute_recognition_plan":
        raise ValueError("workflow_trial_input_result_unproven")
    if command["kind"] == "input_sequence":
        return status == "completed" and result.get("action_executed") is True, terminal, None
    if command["kind"] == "step" and command["operation"] == "execute_recognition_plan":
        from .selection_satisfaction import selection_requested, validate_selection_receipt
        if selection_requested(command.get("request")):
            actual = _actual_action_executed(result, terminal)
            if (type(actual) is not bool or not isinstance(expected_context, dict)
                    or expected_context.get("execution_request_id") != request_id
                    or not validate_selection_receipt(result, command["request"], command=command,
                        action_executed=actual, session_dir=receipt_path.parent.parent.resolve(),
                        expected_context=expected_context)):
                raise ValueError("workflow_trial_selection_receipt_unproven")
            return True, terminal, None
        action = (api.get("data") or {}).get("result", api.get("data") or {})
        executed = (action.get("execution_path") or {}).get("action_executed", action.get("action_executed"))
        return result.get("phase") == "returned" and api.get("success") is True and executed is True, terminal, None
    if command["kind"] == "step":
        action = (api.get("data") or {}).get("result", api.get("data") or {}) if isinstance(api, dict) else {}
        executed = (action.get("execution_path") or {}).get("action_executed", action.get("action_executed"))
        return result.get("phase") == "returned" and api.get("success") is True and executed is True, terminal, None
    return status in {"completed", "ok"} or result.get("success") is True, terminal, None


def _actual_action_executed(result, terminal=None):
    claims = []
    if isinstance(result, dict) and type(result.get("action_executed")) is bool:
        claims.append(result["action_executed"])
    if terminal is not None:
        original = _read(Path(terminal["path"]))
        if type(original.get("action_executed")) is bool:
            claims.append(original["action_executed"])
    response = result.get("response") if isinstance(result, dict) else None
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, dict):
            action = data.get("result", data)
            if isinstance(action, dict):
                path = action.get("execution_path")
                value = path.get("action_executed") if isinstance(path, dict) else action.get("action_executed")
                if type(value) is bool:
                    claims.append(value)
    steps = result.get("steps") if isinstance(result, dict) else None
    if isinstance(steps, list) and steps:
        values = [row.get("action_executed") for row in steps if isinstance(row, dict)]
        if any(value is True for value in values):
            claims.append(True)
        elif len(values) == len(steps) and all(value is False for value in values):
            claims.append(False)
    return claims[0] if claims and all(value is claims[0] for value in claims) else None


def _execution_identity(receipt):
    result = receipt.get("result") or {}
    identity = result.get("target_identity")
    if identity is None and result.get("steps"):
        identities = [row.get("receipt", {}).get("target_identity") for row in result["steps"]]
        if any(value is None or value != identities[0] for value in identities):
            raise ValueError("workflow_verification_execution_identity_changed")
        identity = identities[-1]
    if identity is not None:
        return {"handle": identity.get("target_window_handle"), "process_id": identity.get("process_id"),
                "process_create_time": identity.get("process_create_time")}
    return (receipt.get("observation") or {}).get("window_identity")


class TrialService:
    def __init__(self, library, session_dir):
        self.programs = WorkflowProgramService(library)
        self.session = Path(session_dir).resolve()
        self.root = self.session / "workflow-trials"

    def _path(self, run_id):
        return self.root / (_id(run_id, "run_id", _RUN) + ".json")

    def _load(self, run_id):
        value = _read(self._path(run_id))
        if value.get("run_id") != run_id:
            raise ValueError("workflow_trial_identity_mismatch")
        strategy = execution_strategy(value)
        pending = value.get("pending")
        if isinstance(pending, dict) and execution_strategy(pending) != strategy:
            raise ValueError("workflow_trial_execution_strategy_mismatch")
        if isinstance(pending, dict) and strategy == "steps_only":
            request = pending.get("suggested_command", {}).get("request") or {}
            action = pending.get("preview", {}).get("action") or {}
            if "target_memory" in request or "target_memory" in action:
                raise ValueError("workflow_trial_steps_only_target_memory_forbidden")
        return value

    def status(self, run_id):
        return deepcopy(self._load(run_id))

    def _receipt_context(self, state, pending):
        from .selection_satisfaction import selection_requested
        command = pending["suggested_command"]
        if not selection_requested(command.get("request")):
            return None
        program = self.programs.load(state["workflow_id"], state["program_id"])
        steps = [step for step in program["definition"]["steps"] if step["step_id"] == pending["step_id"]]
        if (len(steps) != 1 or pending.get("preview", {}).get("action") != steps[0]["action"]
                or state.get("current_step_id") != pending["step_id"]):
            raise ValueError("workflow_trial_selection_step_mismatch")
        return _selection_context(state, steps[0], command, pending["execution_request_id"])

    def import_recovery(self, claim_id, request_id, *, control_request_id=None):
        from .workflow_recovery_import import import_recovery_trial
        return import_recovery_trial(self, claim_id, request_id, control_request_id=control_request_id)

    def _remember_prepare(self, state, request_id, request_sha256, result):
        state.setdefault("prepare_requests", {})[request_id] = {
            "request_sha256": request_sha256, "result": deepcopy(result)}
        _write(self._path(state["run_id"]), state)
        return deepcopy(result)

    def _blocked(self, state, reason, request_id, request_sha256):
        state["status"] = "blocked"
        state["reason"] = reason
        state["blocked_request"] = {"request_id": request_id, "request_sha256": request_sha256}
        result = {"run_id": state["run_id"], "status": "blocked", "reason": reason,
                  "execution_strategy": execution_strategy(state),
                  "current_step_id": state["current_step_id"], "input_executed": False}
        return self._remember_prepare(state, request_id, request_sha256, result)

    def start(self, workflow_id, program_id, start_step_id, inputs, request_id, *, execution_strategy="learned"):
        _id(request_id, "request_id")
        from .workflow_recovery_import import ensure_session_takeover_ready
        ensure_session_takeover_ready(self.session)
        strategy = validate_execution_strategy(execution_strategy)
        index_path = self.root / "requests.json"
        index = _read(index_path) if index_path.exists() else {}
        request_values = [workflow_id, program_id, start_step_id, inputs]
        if strategy != "learned":
            request_values.append(strategy)
        request_hash = hashlib.sha256(canonical_json_bytes(request_values)).hexdigest()
        prior = index.get(request_id)
        if prior is not None:
            if prior["request_sha256"] != request_hash:
                raise ValueError("workflow_trial_idempotency_conflict")
            return self.status(prior["run_id"])
        for path in self.root.glob("trial-*.json"):
            existing = _read(path)
            if existing.get("pending") is not None:
                raise ValueError("workflow_trial_session_has_unresolved_execution:" + existing["run_id"])
        program = self.programs.load(workflow_id, program_id)
        if program["program_id"] is None:
            raise ValueError("workflow_trial_save_program_first")
        steps = {step["step_id"]: step for step in program["definition"]["steps"]}
        if start_step_id not in steps:
            raise ValueError("workflow_trial_start_step_unknown")
        declarations = program["definition"]["inputs"]
        if not isinstance(inputs, dict) or set(inputs) - {item["name"] for item in declarations}:
            raise ValueError("workflow_trial_inputs_invalid")
        for item in declarations:
            name = item["name"]
            if item["required"] and name not in inputs:
                raise ValueError("workflow_trial_required_input_missing:" + name)
            if name in inputs and not _type(inputs[name], item["type"]):
                raise ValueError("workflow_trial_input_type_invalid:" + name)
        run_id = "trial-" + hashlib.sha256(canonical_json_bytes([str(self.session), request_id, request_hash])).hexdigest()
        state = {"run_id": run_id, "workflow_id": workflow_id, "program_id": program_id,
                 "execution_strategy": strategy,
                 "project_snapshot_id": program["project_snapshot_id"], "start_step_id": start_step_id,
                 "current_step_id": start_step_id, "inputs": deepcopy(inputs), "outputs": {},
                 "status": "ready", "pending": None, "history": [], "requests": {}, "prepare_requests": {}}
        _write(self._path(run_id), state)
        index[request_id] = {"request_sha256": request_hash, "run_id": run_id}
        _write(index_path, index)
        return deepcopy(state)

    def prepare(self, run_id, request_id, observations=None, vision_capabilities=None):
        _id(request_id, "request_id")
        state = self._load(run_id)
        if state.get("recovery_settlement"):
            raise ValueError("workflow_trial_recovery_paused")
        from .workflow_recovery_import import validate_import_claim
        validate_import_claim(state, self.session)
        if not isinstance(observations, dict) and observations is not None:
            raise ValueError("workflow_trial_observations_invalid")
        if vision_capabilities is not None and not isinstance(vision_capabilities, dict):
            raise ValueError("workflow_trial_vision_capabilities_invalid")
        request_sha256 = hashlib.sha256(canonical_json_bytes([observations or {}, vision_capabilities])).hexdigest()
        prior = state.get("prepare_requests", {}).get(request_id)
        if prior is not None:
            if prior.get("request_sha256") != request_sha256:
                raise ValueError("workflow_trial_idempotency_conflict")
            return deepcopy(prior["result"])
        if state["pending"] is not None:
            result = {"run_id": run_id, "status": "pending", **deepcopy(state["pending"]), "input_executed": False}
            return self._remember_prepare(state, request_id, request_sha256, result)
        if state["status"] not in {"ready", "blocked"}:
            raise ValueError("workflow_trial_not_preparable")
        blocked_request = state.get("blocked_request")
        if isinstance(blocked_request, dict) and blocked_request.get("request_id") == request_id:
            if blocked_request.get("request_sha256") != request_sha256:
                raise ValueError("workflow_trial_idempotency_conflict")
            result = {"run_id": run_id, "status": "blocked", "reason": state["reason"],
                      "execution_strategy": execution_strategy(state),
                      "current_step_id": state["current_step_id"], "input_executed": False}
            return self._remember_prepare(state, request_id, request_sha256, result)
        program = self.programs.load(state["workflow_id"], state["program_id"])
        step = next(step for step in program["definition"]["steps"] if step["step_id"] == state["current_step_id"])
        condition = _conditions(step["preconditions"], state["inputs"], state["outputs"], observations or {})
        if condition != "true":
            return self._blocked(state, "precondition_" + condition, request_id, request_sha256)
        try:
            if execution_strategy(state) == "steps_only":
                from .workflow_target_bindings import _outputs
                _outputs(state, program)
            effective_step = command_step(self.programs.library, step, state)
            command = _command(effective_step, state["inputs"], state["outputs"])
        except ValueError as error:
            return self._blocked(state, str(error), request_id, request_sha256)
        if vision_capabilities is not None:
            if command["kind"] not in {"step", "input_sequence"}:
                raise ValueError("workflow_trial_vision_capabilities_not_supported_for_action")
            from app.vision.recognition_source import ClientVisionCapabilities
            command["vision_capabilities"] = ClientVisionCapabilities.model_validate(vision_capabilities).model_dump(exclude_none=True)
        ticket_id = "trial-exec-" + hashlib.sha256(canonical_json_bytes([run_id, step["step_id"], len(state["history"]), request_id])).hexdigest()[:32]
        strategy = execution_strategy(state)
        ticket = {"execution_request_id": ticket_id, "step_id": step["step_id"], "suggested_command": command,
                  "execution_strategy": strategy,
                  "preview": {"title": step["title"], "action": deepcopy(effective_step["action"]),
                              "execution_strategy": strategy, "program_review_status": step["review_status"],
                              "source_node_id": step["source_node_id"], "target_node_id": step["target_node_id"],
                              "provenance": step["provenance"],
                              "review_status": step["review_status"] if strategy == "learned" else "pending"},
                  "observations": deepcopy(observations or {})}
        state["pending"] = ticket
        state["status"] = "pending"
        state.pop("reason", None)
        state.pop("blocked_request", None)
        result = {"run_id": run_id, "status": "pending", **deepcopy(ticket), "input_executed": False}
        return self._remember_prepare(state, request_id, request_sha256, result)

    def review(self, run_id, request_id, execution_request_id, verdict, observations, outputs):
        return self._review(run_id, request_id, execution_request_id, verdict, observations, outputs)

    def record_failed_execution(self, run_id, request_id, execution_request_id):
        _id(request_id, "request_id")
        _id(execution_request_id, "execution_request_id")
        state = self._load(run_id)
        if request_id in state["requests"]:
            history = state.get("history") or []
            if (history and history[-1].get("execution_request_id") == execution_request_id
                    and history[-1].get("runtime_settlement_request_id") == request_id):
                return deepcopy(state)
            raise ValueError("workflow_trial_idempotency_conflict")
        pending = state.get("pending")
        if not isinstance(pending, dict) or pending.get("execution_request_id") != execution_request_id:
            raise ValueError("workflow_trial_pending_ticket_mismatch")
        receipt_path = self.session / "responses" / (execution_request_id + ".json")
        if not receipt_path.is_file():
            raise ValueError("workflow_trial_receipt_missing")
        receipt = _read(receipt_path)
        _, terminal, _ = _receipt_state(receipt, receipt_path, execution_request_id,
                                        pending["suggested_command"], expected_context=self._receipt_context(state, pending))
        if receipt.get("status") != "failed" and (terminal is None or terminal["status"] != "failed"):
            raise ValueError("workflow_trial_original_failure_required")
        effective, _ = resolve_execution_receipt(receipt, receipt_path, execution_request_id)
        original_error = receipt if receipt.get("status") == "failed" else _read(Path(terminal["path"]))
        runtime_result = {"source": "runtime", "verdict": "failure",
                          "reason": "original_execution_failed", "terminal_status": "failed",
                          "action_executed": _actual_action_executed(effective.get("result"), terminal),
                          "runtime_settlement_request_id": request_id,
                          "error_type": original_error.get("error_type"), "error": original_error.get("error")}
        return self._review(run_id, request_id, execution_request_id, "failure", {}, {},
                            verification_result=runtime_result)

    def record_cancelled_execution(self, run_id, request_id, execution_request_id):
        _id(request_id, "request_id")
        _id(execution_request_id, "execution_request_id")
        state = self._load(run_id)
        if request_id in state["requests"]:
            history = state.get("history") or []
            if (history and history[-1].get("execution_request_id") == execution_request_id
                    and history[-1].get("runtime_settlement_request_id") == request_id):
                return deepcopy(state)
            raise ValueError("workflow_trial_idempotency_conflict")
        if state["status"] != "cancel_requested":
            raise ValueError("workflow_trial_cancel_requested_required")
        pending = state.get("pending")
        if not isinstance(pending, dict) or pending.get("execution_request_id") != execution_request_id:
            raise ValueError("workflow_trial_pending_ticket_mismatch")
        receipt_path = self.session / "responses" / (execution_request_id + ".json")
        if not receipt_path.is_file():
            raise ValueError("workflow_trial_receipt_missing")
        receipt = _read(receipt_path)
        _, terminal, _ = _receipt_state(receipt, receipt_path, execution_request_id,
                                        pending["suggested_command"], expected_context=self._receipt_context(state, pending))
        effective, _ = resolve_execution_receipt(receipt, receipt_path, execution_request_id)
        if terminal is not None:
            terminal_status = terminal["status"]
        elif effective.get("status") == "failed" or effective.get("result", {}).get("status") == "failed":
            terminal_status = "failed"
        elif effective.get("result", {}).get("status") == "cancelled":
            terminal_status = "cancelled"
        elif effective.get("result", {}).get("status") == "completed" or effective.get("result", {}).get("phase") == "returned":
            terminal_status = "completed"
        else:
            raise ValueError("workflow_trial_receipt_not_terminal")
        action_executed = _actual_action_executed(effective.get("result"), terminal)
        runtime_result = {"source": "runtime", "verdict": "uncertain",
                          "reason": "cancel_requested_original_execution_terminal",
                          "terminal_status": terminal_status, "action_executed": action_executed,
                          "runtime_settlement_request_id": request_id,
                          "error_type": receipt.get("error_type"), "error": receipt.get("error")}
        return self._review(run_id, request_id, execution_request_id, "uncertain", {}, {},
                            verification_result=runtime_result)

    def record_verified_result(self, run_id, request_id, execution_request_id, result, *, decision_service=None):
        from .workflow_verification import verify_step
        _id(request_id, "request_id")
        _id(execution_request_id, "execution_request_id")
        if (not isinstance(result, dict) or set(result) != {"verdict", "source", "observations", "outputs", "evidence_refs", "reason"}
                or result.get("source") not in {"rule", "decision"} or not isinstance(result.get("observations"), dict)
                or not isinstance(result.get("outputs"), dict)):
            raise ValueError("workflow_verification_result_invalid")
        observations = result["observations"]
        values = observations.get("values", {})
        request_hash = hashlib.sha256(canonical_json_bytes(
            [execution_request_id, result["verdict"], values, result["outputs"], result])).hexdigest()
        state = self._load(run_id)
        if state.get("recovery_settlement"):
            raise ValueError("workflow_trial_recovery_paused")
        if execution_strategy(state) == "steps_only":
            raise ValueError("workflow_trial_steps_only_requires_agent_review")
        if request_id in state["requests"]:
            if state["requests"][request_id] != request_hash:
                raise ValueError("workflow_trial_idempotency_conflict")
            return deepcopy(state)
        pending = state["pending"]
        if not isinstance(pending, dict) or pending["execution_request_id"] != execution_request_id:
            raise ValueError("workflow_trial_pending_ticket_mismatch")
        if result["source"] == "decision" and state["status"] == "cancel_requested":
            return self.record_cancelled_execution(run_id, request_id, execution_request_id)
        evidence_ref = observations.get("evidence_ref")
        if not isinstance(evidence_ref, str):
            raise ValueError("workflow_verification_evidence_missing")
        evidence_path = (self.session / evidence_ref).resolve()
        if not evidence_path.is_relative_to(self.session / "workflow-observations"):
            raise ValueError("workflow_verification_evidence_outside_session")
        evidence = _read(evidence_path)
        if (evidence.get("contract_version") != "workflow_observation.v1"
                or evidence.get("observation") != observations):
            raise ValueError("workflow_verification_evidence_mismatch")
        receipt_path = self.session / "responses" / (execution_request_id + ".json")
        receipt = _read(receipt_path)
        if evidence.get("source_receipt_sha256") != hashlib.sha256(receipt_path.read_bytes()).hexdigest():
            raise ValueError("workflow_verification_receipt_changed")
        context = self._receipt_context(state, pending)
        dispatched, terminal, _ = _receipt_state(receipt, receipt_path, execution_request_id,
            pending["suggested_command"], expected_context=context)
        effective, _ = resolve_execution_receipt(receipt, receipt_path, execution_request_id)
        if evidence.get("terminal_receipt") != terminal:
            raise ValueError("workflow_verification_terminal_changed")
        normalized, frame = evidence.get("receipt"), evidence.get("frame")
        if not isinstance(normalized, dict) or not isinstance(frame, dict):
            raise ValueError("workflow_verification_evidence_invalid")
        _verified_observation({"observation": frame}, self.session)
        expected_ids = {"run_id": run_id, "step_id": pending["step_id"], "request_id": request_id,
                        "execution_request_id": execution_request_id}
        input_executed = False if pending["suggested_command"]["kind"] == "read_text" else _actual_action_executed(effective.get("result"), terminal)
        proof = effective["result"].get("row_selection_proof") if context is not None and dispatched else None
        if (any(normalized.get(key) != value for key, value in expected_ids.items())
                or normalized.get("window_identity") != _execution_identity(effective)
                or frame.get("window_identity") != normalized.get("window_identity")
                or normalized.get("post_capture_id") != frame.get("capture_id")
                or normalized.get("post_capture_sha256") != frame.get("sha256")
                or normalized.get("status") != ("completed" if dispatched else "failed")
                or normalized.get("action_executed") is not input_executed
                or normalized.get("row_selection_proof") != proof
                or (self.session / str(normalized.get("evidence_ref", ""))).resolve() != receipt_path):
            raise ValueError("workflow_verification_receipt_binding_mismatch")
        program = self.programs.load(state["workflow_id"], state["program_id"])
        step = next(step for step in program["definition"]["steps"] if step["step_id"] == pending["step_id"])
        outputs = {key: {"run_id": run_id, "value": value} for key, value in state["outputs"].items()}
        image_check = step.get("verification", {}).get("image_check")
        if image_check is not None:
            from .image_verification import load_reference_image, match_image_check
            try:
                reference_raw = load_reference_image(self.programs.library, image_check)
                proof = match_image_check(image_check, reference_raw, frame)
            except (OSError, ValueError) as error:
                raise ValueError("workflow_verification_image_evidence_unavailable") from error
            semantic_miss = result["source"] == "decision" and proof.get("reason") == "image_not_matched" and proof.get("matched") is False
            if (proof.get("matched") is not True and not semantic_miss) or proof != observations.get("values", {}).get("image_check"):
                raise ValueError("workflow_verification_image_proof_mismatch")
        if result["source"] == "decision":
            from .decision_verification import adopted_verification, decision_result_path
            saved = _read(decision_result_path(self.session, request_id))
            computed = adopted_verification(step, inputs=state["inputs"], outputs=outputs,
                envelope=evidence, decision=saved.get("result"), service=decision_service)
        else:
            computed = verify_step(step, inputs=state["inputs"], outputs=outputs, receipt=normalized, observation=observations)
        if computed != result:
            raise ValueError("workflow_verification_result_mismatch")
        return self._review(run_id, request_id, execution_request_id, computed["verdict"], values,
                            computed["outputs"], verification_result=computed)

    def _review(self, run_id, request_id, execution_request_id, verdict, observations, outputs, *, verification_result=None):
        _id(request_id, "request_id")
        _id(execution_request_id, "execution_request_id")
        state = self._load(run_id)
        if state.get("recovery_settlement"):
            raise ValueError("workflow_trial_recovery_paused")
        request_values = [execution_request_id, verdict, observations, outputs]
        if verification_result is not None:
            request_values.append(verification_result)
        request_hash = hashlib.sha256(canonical_json_bytes(request_values)).hexdigest()
        prior = state["requests"].get(request_id)
        if prior is not None:
            if prior != request_hash:
                raise ValueError("workflow_trial_idempotency_conflict")
            return deepcopy(state)
        pending = state["pending"]
        if not isinstance(pending, dict) or pending["execution_request_id"] != execution_request_id:
            raise ValueError("workflow_trial_pending_ticket_mismatch")
        if verdict not in {"success", "failure", "uncertain"} or not isinstance(observations, dict) or not isinstance(outputs, dict):
            raise ValueError("workflow_trial_review_invalid")
        receipt_path = self.session / "responses" / (execution_request_id + ".json")
        if not receipt_path.is_file():
            raise ValueError("workflow_trial_receipt_missing")
        receipt = _read(receipt_path)
        context = self._receipt_context(state, pending)
        dispatched, terminal, read_observation = _receipt_state(receipt, receipt_path, execution_request_id,
            pending["suggested_command"], expected_context=context)
        if verdict == "success" and not dispatched:
            raise ValueError("workflow_trial_input_not_succeeded")
        program = self.programs.load(state["workflow_id"], state["program_id"])
        step = next(step for step in program["definition"]["steps"] if step["step_id"] == pending["step_id"])
        declarations = {item["name"]: item["type"] for item in step["outputs"]}
        if set(outputs) - set(declarations) or any(not _type(value, declarations[name]) for name, value in outputs.items()):
            raise ValueError("workflow_trial_outputs_invalid")
        if verdict == "success" and set(outputs) != set(declarations):
            raise ValueError("workflow_trial_required_output_missing")
        condition = _conditions(step["success_conditions"], state["inputs"],
                                {**state["outputs"], **{step["step_id"] + "." + k: v for k, v in outputs.items()}}, observations)
        effective = verdict if verdict != "success" else "success" if condition == "true" else "failure" if condition == "false" else "uncertain"
        entry = {"step_id": step["step_id"], "execution_request_id": execution_request_id,
                 "review_request": {"request_id": request_id, "submitted_outputs": deepcopy(outputs)},
                 "execution_strategy": execution_strategy(state),
                 "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                 "terminal_receipt": terminal,
                 "input_route_succeeded": dispatched if read_observation is None else None,
                 "agent_verdict": verdict, "verdict": effective,
                 "condition_result": condition, "judged_by": "agent", "observations": deepcopy(observations),
                 "outputs": deepcopy(outputs) if effective == "success" else {}}
        if context is not None:
            original, _ = resolve_execution_receipt(receipt, receipt_path, execution_request_id)
            actual = _actual_action_executed(original.get("result"), terminal)
            entry.update(command_succeeded=dispatched, action_executed=actual,
                         input_route_succeeded=dispatched and actual is True)
            if dispatched:
                entry["selection_proof_sha256"] = original["result"]["row_selection_proof"]["sha256"]
        if read_observation is not None:
            entry["read_observation"] = read_observation
        if verification_result is not None:
            entry.pop("agent_verdict")
            source = verification_result.get("source")
            if source == "runtime":
                entry.update(runtime_verdict=verdict, judged_by="runtime",
                             action_executed=verification_result["action_executed"],
                             runtime_reason=verification_result["reason"],
                             runtime_settlement_request_id=verification_result["runtime_settlement_request_id"],
                             terminal_status=verification_result["terminal_status"])
                if verification_result["reason"] == "cancel_requested_original_execution_terminal":
                    entry["cancel_reason"] = verification_result["reason"]
                if verification_result.get("error_type") is not None:
                    entry["error_type"] = verification_result["error_type"]
                if verification_result.get("error") is not None:
                    entry["error"] = verification_result["error"]
            else:
                entry.update(judged_by="decision" if source == "decision" else "rule", verification=deepcopy(verification_result))
                entry["decision_verdict" if source == "decision" else "rule_verdict"] = verdict
        state["history"].append(entry)
        state["pending"] = None
        state["requests"][request_id] = request_hash
        cancelled = state["status"] == "cancel_requested"
        if effective == "success":
            state["outputs"].update({step["step_id"] + "." + k: v for k, v in outputs.items()})
            target = step["branches"]["success"]
            state["current_step_id"] = target
            state["status"] = "cancelled" if cancelled else "ready" if target else "completed"
        elif effective == "failure":
            target = step["branches"]["failure"]
            state["current_step_id"] = target
            state["status"] = "cancelled" if cancelled else "ready" if target else "failed"
        else:
            state["status"] = "cancelled" if cancelled else "paused_uncertain"
        _write(self._path(run_id), state)
        return deepcopy(state)

    def cancel(self, run_id, request_id):
        _id(request_id, "request_id")
        state = self._load(run_id)
        if state.get("recovery_settlement"):
            raise ValueError("workflow_trial_recovery_paused")
        from .workflow_recovery_import import validate_import_claim
        validate_import_claim(state, self.session)
        if state["status"] not in {"cancelled", "cancel_requested"}:
            state["status"] = "cancel_requested" if state["pending"] is not None else "cancelled"
            state["cancel_request_id"] = request_id
            _write(self._path(run_id), state)
        return deepcopy(state)


__all__ = ["TrialService"]
