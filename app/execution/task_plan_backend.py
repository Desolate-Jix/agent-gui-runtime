"""会话内调用方计划来源；仅准备和结算票据，输入仍由原运行器派发。"""

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import Lock, RLock
from uuid import uuid4

from .task_plan_contract import _identifier, resolve_action_text, validate_task_plan, validate_task_plan_target


_RUN = re.compile(r"trial-[0-9a-f]{64}\Z")
_PLAN = re.compile(r"task-plan-[0-9a-f]{64}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_LOCKS = {}
_LOCKS_GUARD = Lock()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("task_plan_duplicate_json_key")
        result[key] = value
    return result


def _read(path):
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("task_plan_nonfinite_json")))
    if not isinstance(value, dict):
        raise ValueError("task_plan_snapshot_invalid")
    return value


def _write(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(_canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class TaskPlanBackend:
    source_kind = "caller_plan"

    def __init__(self, session_dir, *, owner_id=None):
        self.session = Path(session_dir).resolve()
        self.root = self.session / "task-plans"
        if owner_id is not None and (not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 160):
            raise ValueError("task_plan_owner_invalid")
        self.owner_id = owner_id
        with _LOCKS_GUARD:
            self._mutex = _LOCKS.setdefault(str(self.root), RLock())

    @contextmanager
    def _locked(self):
        with self._mutex:
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.root.resolve().is_relative_to(self.session):
                raise ValueError("task_plan_backend_outside_session")
            with (self.root / "backend.lock").open("a+b") as stream:
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    except OSError as error:
                        raise ValueError("task_plan_backend_busy") from error
                    try:
                        yield
                    finally:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    try:
                        yield
                    finally:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _path(self, run_id):
        if not isinstance(run_id, str) or not _RUN.fullmatch(run_id):
            raise ValueError("task_plan_run_id_invalid")
        path = self.root / (run_id + ".json")
        if path.resolve().parent != self.root.resolve() or not path.resolve().is_relative_to(self.session):
            raise ValueError("task_plan_run_outside_session")
        return path

    def _source_path(self, plan_id):
        if not isinstance(plan_id, str) or not _PLAN.fullmatch(plan_id):
            raise ValueError("task_plan_id_invalid")
        path = self.root / (plan_id + ".json")
        if path.resolve().parent != self.root.resolve() or not path.resolve().is_relative_to(self.session):
            raise ValueError("task_plan_source_outside_session")
        return path

    def _require_owner(self, state=None, *, admit=False):
        if self.owner_id is None:
            raise ValueError("task_plan_read_only_owner")
        if state is not None and state.get("owner_id") != self.owner_id:
            raise ValueError("task_plan_owner_mismatch_read_only")
        if admit and (self.session / "closing.json").exists():
            raise ValueError("task_plan_session_closing")

    def _source(self, state):
        source = _read(self._source_path(state["plan_id"]))
        plan = validate_task_plan(source.get("plan"))
        target = validate_task_plan_target(source.get("target_identity"))
        expected_id = "task-plan-" + _digest([str(self.session), source.get("owner_id"), plan, target])
        if (source.get("schema_version") != "task_plan_source.v1"
                or source.get("source_kind") != self.source_kind
                or source.get("session_directory") != str(self.session)
                or source.get("plan_id") != expected_id or state.get("plan_id") != expected_id
                or source.get("plan_sha256") != _digest(plan)
                or state.get("plan_sha256") != source["plan_sha256"]
                or state.get("owner_id") != source.get("owner_id")
                or state.get("target_identity") != target or state.get("inputs") != plan["inputs"]):
            raise ValueError("task_plan_source_binding_mismatch")
        return source

    def _load(self, run_id):
        state = _read(self._path(run_id))
        if (state.get("schema") != "task_plan_trial.v1" or state.get("run_id") != run_id
                or state.get("source_kind") != self.source_kind
                or state.get("session_directory") != str(self.session)
                or state.get("outputs") != {} or not isinstance(state.get("history"), list)
                or state.get("status") not in {"ready", "pending", "cancel_requested", *_TERMINAL}
                or state.get("recovery_import") is not None or state.get("recovery_settlement") is not None):
            raise ValueError("task_plan_trial_binding_invalid")
        source = self._source(state)
        ids = [step["step_id"] for step in source["plan"]["steps"]]
        if state.get("current_step_id") is not None and state["current_step_id"] not in ids:
            raise ValueError("task_plan_current_step_invalid")
        self._validate_settlements(state, source)
        pending = state.get("pending")
        if pending is not None:
            if (not isinstance(pending, dict) or pending.get("step_id") != state.get("current_step_id")
                    or pending.get("source_kind") != self.source_kind):
                raise ValueError("task_plan_pending_ticket_mismatch")
            step = next(item for item in source["plan"]["steps"] if item["step_id"] == pending["step_id"])
            expected_id = self._execution_id(run_id, step["step_id"])
            command = self._command(step, state["inputs"], pending.get("vision_capabilities"))
            if (pending.get("execution_request_id") != expected_id or pending.get("suggested_command") != command
                    or pending.get("command_sha256") != _digest(command)
                    or pending.get("preview") != self._preview(state, step)):
                raise ValueError("task_plan_pending_command_mismatch")
        return state

    def _validate_settlements(self, state, source):
        history = state["history"]
        results, requests = state.get("verification_results"), state.get("verification_requests")
        prepares = state.get("prepare_requests")
        steps = source["plan"]["steps"]
        if not all(isinstance(value, dict) for value in (results, requests, prepares)) or len(history) > len(steps):
            raise ValueError("task_plan_settlement_binding_invalid")
        for index, row in enumerate(history):
            if not isinstance(row, dict):
                raise ValueError("task_plan_settlement_binding_invalid")
            request_id = row.get("verification_request_id")
            result = results.get(request_id) if isinstance(request_id, str) else None
            step = steps[index]
            execution_id = self._execution_id(state["run_id"], step["step_id"])
            tickets = [item.get("result") for item in prepares.values() if isinstance(item, dict)
                       and isinstance(item.get("result"), dict) and item["result"].get("execution_request_id") == execution_id]
            if not isinstance(result, dict) or not tickets:
                raise ValueError("task_plan_settlement_binding_invalid")
            result_hash = _digest(result)
            command_hash = _digest(self._command(step, state["inputs"], tickets[0].get("vision_capabilities")))
            expected = {"step_id": step["step_id"], "execution_request_id": execution_id,
                        "judged_by": result.get("judged_by"), "verification_request_id": request_id,
                        "verification_result_sha256": result_hash, "command_sha256": command_hash,
                        "evidence_refs": result.get("evidence_refs"),
                        **{key: result[key] for key in ("reason", "original_input_status", "action_executed") if key in result}}
            bindings = {"run_id": state["run_id"], "step_id": step["step_id"], "execution_request_id": execution_id,
                        "plan_id": state["plan_id"], "plan_sha256": state["plan_sha256"], "target_identity": state["target_identity"]}
            verdict = row.get("verdict")
            if (row != {**expected, "verdict": verdict} or requests.get(request_id) != result_hash
                    or any(result.get(key) != value for key, value in bindings.items())
                    or verdict not in {"success", "failure", "cancelled"}
                    or verdict != "cancelled" and verdict != result.get("verdict")
                    or verdict == "cancelled" and not (state.get("cancel_requests") or (self.session / "closing.json").exists())
                    or index < len(history) - 1 and verdict != "success"):
                raise ValueError("task_plan_settlement_binding_invalid")
        terminal_verdict = history[-1]["verdict"] if history else None
        expected_step = (history[-1]["step_id"] if terminal_verdict in {"failure", "cancelled"}
                         else steps[len(history)]["step_id"] if len(history) < len(steps) else None)
        if (state.get("current_step_id") != expected_step
                or state["status"] == "completed" and (len(history) != len(steps) or terminal_verdict != "success")
                or state["status"] == "failed" and terminal_verdict != "failure"
                or state["status"] in {"ready", "pending", "cancel_requested"} and terminal_verdict in {"failure", "cancelled"}
                or state["status"] in _TERMINAL and state.get("pending") is not None):
            raise ValueError("task_plan_settlement_binding_invalid")

    @staticmethod
    def _execution_id(run_id, step_id):
        return "trial-exec-" + _digest([run_id, step_id])[:32]

    @staticmethod
    def _command(step, inputs, vision_capabilities=None):
        action = step["action"]
        if action["kind"] == "click":
            command = {"kind": "step", "operation": "execute_recognition_plan",
                       "request": {"goal": action["goal"], "click_kind": action.get("click_kind", "single")}}
        elif action["kind"] == "input_sequence":
            command = {"kind": "input_sequence", "request": {
                "field_goal": action["field_goal"], "text": resolve_action_text(action["text"], inputs),
                "clear_existing": action["clear_existing"], "submit_search": action["submit_search"]}}
        else:
            command = {"kind": "read_text", "max_chars": 10000}
        if "target" in action:
            if action["kind"] == "click":
                command["request"]["metadata"] = {"task_plan_target": deepcopy(action["target"])}
            elif action["kind"] == "input_sequence":
                command["request"]["target"] = deepcopy(action["target"])
        if vision_capabilities is not None:
            if command["kind"] == "read_text":
                raise ValueError("task_plan_vision_capabilities_not_supported_for_read")
            from app.vision.recognition_source import ClientVisionCapabilities
            command["vision_capabilities"] = ClientVisionCapabilities.model_validate(vision_capabilities).model_dump(exclude_none=True)
        verification = step["verification"]
        if verification["kind"] == "native_condition":
            command.update(observation_condition=deepcopy(verification["condition"]), observation_wait_ms=2000)
        return command

    @staticmethod
    def _preview(state, step):
        return {"action": deepcopy(step["action"]), "verification": deepcopy(step["verification"]),
                "source_kind": "caller_plan", "plan_id": state["plan_id"],
                "plan_sha256": state["plan_sha256"], "target_identity": deepcopy(state["target_identity"])}

    def start(self, plan, target, request_id):
        plan = validate_task_plan(plan)
        target = validate_task_plan_target(target)
        _identifier(request_id, "request_id")
        self._require_owner(admit=True)
        run_id = "trial-" + _digest([str(self.session), request_id])
        request_hash = _digest([plan, target])
        with self._locked():
            path = self._path(run_id)
            if path.exists():
                state = self._load(run_id)
                self._require_owner(state)
                if state.get("start_request_id") != request_id or state.get("start_request_sha256") != request_hash:
                    raise ValueError("task_plan_start_idempotency_conflict")
                return deepcopy(state)
            for existing in self.root.glob("trial-*.json"):
                if self._load(existing.stem)["status"] not in _TERMINAL:
                    raise ValueError("task_plan_session_active")
            plan_id = "task-plan-" + _digest([str(self.session), self.owner_id, plan, target])
            source = {"schema_version": "task_plan_source.v1", "source_kind": self.source_kind,
                      "session_directory": str(self.session), "owner_id": self.owner_id,
                      "plan_id": plan_id, "plan_sha256": _digest(plan), "plan": plan, "target_identity": target}
            source_path = self._source_path(plan_id)
            if source_path.exists():
                if _read(source_path) != source:
                    raise ValueError("task_plan_immutable_source_conflict")
            else:
                with source_path.open("xb") as stream:
                    stream.write(_canonical(source) + b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            state = {"schema": "task_plan_trial.v1", "source_kind": self.source_kind,
                     "session_directory": str(self.session), "owner_id": self.owner_id,
                     "plan_id": plan_id, "plan_sha256": source["plan_sha256"], "run_id": run_id,
                     "start_request_id": request_id, "start_request_sha256": request_hash,
                     "target_identity": target, "inputs": deepcopy(plan["inputs"]), "outputs": {},
                     "current_step_id": plan["steps"][0]["step_id"], "status": "ready",
                     "pending": None, "history": [], "prepare_requests": {}, "verification_requests": {},
                     "cancel_requests": {}, "verification_results": {}}
            _write(path, state)
            return deepcopy(state)

    def status(self, run_id):
        return deepcopy(self._load(run_id))

    def pinned_step(self, run_id, step_id):
        state = self._load(run_id)
        matches = [step for step in self._source(state)["plan"]["steps"] if step["step_id"] == step_id]
        if len(matches) != 1:
            raise ValueError("task_plan_step_not_in_pinned_plan")
        return deepcopy(matches[0])

    def prepare(self, run_id, request_id, *, vision_capabilities=None):
        _identifier(request_id, "request_id")
        self._require_owner(admit=True)
        with self._locked():
            state = self._load(run_id)
            self._require_owner(state)
            request_hash = _digest(vision_capabilities)
            prior = state["prepare_requests"].get(request_id)
            if prior is not None:
                if prior["request_sha256"] != request_hash:
                    raise ValueError("task_plan_prepare_idempotency_conflict")
                return deepcopy(prior["result"])
            if state["status"] not in {"ready", "pending"}:
                raise ValueError("task_plan_not_preparable")
            if state["pending"] is None:
                step = self.pinned_step(run_id, state["current_step_id"])
                command = self._command(step, state["inputs"], vision_capabilities)
                state["pending"] = {"execution_request_id": self._execution_id(run_id, step["step_id"]),
                    "step_id": step["step_id"], "suggested_command": command, "command_sha256": _digest(command),
                    "source_kind": self.source_kind, "preview": self._preview(state, step),
                    "observations": {}, "vision_capabilities": deepcopy(vision_capabilities)}
                state["status"] = "pending"
            elif state["pending"]["vision_capabilities"] != vision_capabilities:
                raise ValueError("task_plan_pending_capabilities_mismatch")
            result = {"run_id": run_id, "status": "pending", **deepcopy(state["pending"]), "input_executed": False}
            state["prepare_requests"][request_id] = {"request_sha256": request_hash, "result": deepcopy(result)}
            _write(self._path(run_id), state)
            return result

    def cancel(self, run_id, request_id):
        _identifier(request_id, "request_id")
        self._require_owner()
        with self._locked():
            state = self._load(run_id)
            self._require_owner(state)
            if request_id in state["cancel_requests"] or state["status"] in _TERMINAL:
                return deepcopy(state)
            state["cancel_requests"][request_id] = True
            state["status"] = "cancel_requested" if state["pending"] is not None else "cancelled"
            _write(self._path(run_id), state)
            return deepcopy(state)

    def _evidence(self, state, pending, result, *, request_id, decision_service):
        refs = result["evidence_refs"]
        if not isinstance(refs, list) or not refs:
            raise ValueError("task_plan_verification_evidence_missing")
        seen = set()
        expected = self.session / "responses" / (pending["execution_request_id"] + ".json")
        original = None
        for ref in refs:
            if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                    or not isinstance(ref["path"], str) or not ref["path"]
                    or not isinstance(ref["sha256"], str) or not _HASH.fullmatch(ref["sha256"])):
                raise ValueError("task_plan_verification_evidence_invalid")
            relative = Path(ref["path"])
            path = (self.session / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(self.session) or path == self.session or path in seen:
                raise ValueError("task_plan_verification_evidence_outside_session")
            seen.add(path)
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != ref["sha256"]:
                raise ValueError("task_plan_verification_evidence_changed")
            if path == expected.resolve():
                original = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        if (not isinstance(original, dict) or original.get("command") != pending["suggested_command"]
                or original.get("status") not in {"returned", "failed"}):
            raise ValueError("task_plan_original_receipt_binding_mismatch")
        from app.learning_memory.receipt_adapter import resolve_execution_receipt
        from app.learning_memory.workflow_trial import (
            _actual_action_executed, _execution_identity, _receipt_state, _verified_observation,
        )
        from .decision_check import decision_frame
        from .task_plan_verification import _native_success

        command_path = self.session / "commands" / (pending["execution_request_id"] + ".json")
        if command_path.resolve() not in seen:
            raise ValueError("task_plan_verification_command_evidence_missing")
        succeeded, terminal, _ = _receipt_state(original, expected, pending["execution_request_id"], pending["suggested_command"])
        effective, resolved_terminal = resolve_execution_receipt(original, expected, pending["execution_request_id"])
        if terminal != resolved_terminal or terminal is not None and Path(terminal["path"]).resolve() not in seen:
            raise ValueError("task_plan_verification_terminal_evidence_mismatch")
        step = self.pinned_step(state["run_id"], pending["step_id"])
        actual = False if step["action"]["kind"] == "read_text" else _actual_action_executed(effective.get("result"), terminal)
        original_status = "completed" if succeeded else "failed" if actual is False else "unknown"
        if (result.get("original_input_status") != original_status or result.get("action_executed") is not actual
                or result["verdict"] == "success" and not succeeded):
            raise ValueError("task_plan_verification_original_input_mismatch")
        if not succeeded:
            if result["judged_by"] != "runtime" or result["verdict"] != ("failure" if actual is False else "uncertain"):
                raise ValueError("task_plan_verification_unproven_input")
            return
        identity = _execution_identity(effective)
        if identity != state["target_identity"]:
            raise ValueError("task_plan_verification_target_mismatch")
        observed = _verified_observation(effective, self.session)
        capture = effective.get("observation") or (effective.get("result") or {}).get("capture")
        frame = decision_frame({**capture, **observed}, identity, role="after")
        if Path(frame["image_path"]).resolve() not in seen:
            raise ValueError("task_plan_verification_image_evidence_missing")
        before = (effective.get("result") or {}).get("capture") or {}
        if step["action"]["kind"] != "read_text" and before.get("image_path"):
            before_path = Path(before["image_path"])
            before_path = (before_path if before_path.is_absolute() else self.session / before_path).resolve()
            if before_path == Path(frame["image_path"]).resolve():
                raise ValueError("task_plan_verification_post_action_capture_missing")
        judged_by = result["judged_by"]
        if judged_by == "native_condition":
            if (result["verdict"] != "success" or step["verification"]["kind"] != "native_condition"
                    or not _native_success(step["verification"], effective, frame)):
                raise ValueError("task_plan_verification_native_proof_invalid")
        elif judged_by == "decision":
            condition = step["verification"].get("decision_condition")
            decision_path = self.session / "task-plan-decisions" / (pending["execution_request_id"] + ".json")
            if not condition or decision_path.resolve() not in seen or decision_service is None:
                raise ValueError("task_plan_verification_decision_evidence_missing")
            saved = _read(decision_path)
            binding = {"request_id": "task-decision-" + sha256(pending["execution_request_id"].encode()).hexdigest()[:32],
                       "execution_request_id": pending["execution_request_id"], "condition": condition, "frames": [frame],
                       "mode": "execution", "phase": "after_action", "run_id": state["run_id"], "step_id": step["step_id"]}
            decision = saved.get("result")
            if (saved.get("binding") != binding or not isinstance(decision, dict)
                    or decision.get("adopted") is not True or decision.get("verdict") != result["verdict"]
                    or decision_service.validate_result(decision, **binding) is not True):
                raise ValueError("task_plan_verification_decision_authentication_invalid")
        elif judged_by == "agent":
            review_path = self.session / "task-plan-reviews" / (request_id + ".json")
            if review_path.resolve() not in seen:
                raise ValueError("task_plan_verification_agent_evidence_missing")
            review = _read(review_path)
            if any(review.get(key) != value for key, value in {
                "run_id": state["run_id"], "step_id": step["step_id"], "execution_request_id": pending["execution_request_id"],
                "verdict": result["verdict"], "reason": result.get("reason"), "evidence_sha256": frame["sha256"],
            }.items()):
                raise ValueError("task_plan_verification_agent_binding_invalid")
        elif result["verdict"] == "success":
            raise ValueError("task_plan_verification_success_provenance_invalid")

    def record_verified_result(self, run_id, request_id, execution_request_id, result, *, decision_service=None):
        """只接收宿主已验证的结果；再次绑定原票据与原文件，不自行语义判断。"""
        _identifier(request_id, "request_id")
        _identifier(execution_request_id, "execution_request_id")
        required = {"run_id", "step_id", "execution_request_id", "plan_id", "plan_sha256",
                    "target_identity", "verdict", "judged_by", "evidence_refs"}
        optional = {"reason", "original_input_status", "action_executed"}
        if (not isinstance(result, dict) or not required <= set(result) or set(result) - required - optional
                or result.get("verdict") not in {"success", "failure", "uncertain"}
                or result.get("judged_by") not in {"rule", "native_condition", "decision", "agent", "runtime"}
                or "reason" in result and (not isinstance(result["reason"], str) or len(result["reason"]) > 4000)
                or "action_executed" in result and result["action_executed"] is not None and type(result["action_executed"]) is not bool
                or "original_input_status" in result and result["original_input_status"] not in {"completed", "failed", "cancelled", "unknown"}):
            raise ValueError("task_plan_verification_result_invalid")
        if result["verdict"] == "success" and result.get("original_input_status", "completed") != "completed":
            raise ValueError("task_plan_unknown_or_partial_input_cannot_succeed")
        self._require_owner()
        result_hash = _digest(result)
        with self._locked():
            state = self._load(run_id)
            self._require_owner(state)
            prior = state["verification_requests"].get(request_id)
            if prior is not None:
                if prior != result_hash:
                    raise ValueError("task_plan_verification_idempotency_conflict")
                if result["verdict"] == "uncertain" and state["pending"] is not None:
                    return {**deepcopy(state), "status": "verification_required", "reason": result.get("reason", "uncertain")}
                return deepcopy(state)
            pending = state["pending"]
            bindings = {"run_id": run_id, "plan_id": state["plan_id"], "plan_sha256": state["plan_sha256"],
                        "target_identity": state["target_identity"], "execution_request_id": execution_request_id}
            if (not isinstance(pending, dict) or pending["execution_request_id"] != execution_request_id
                    or result.get("step_id") != pending["step_id"]
                    or any(result.get(key) != value for key, value in bindings.items())):
                raise ValueError("task_plan_verification_ticket_mismatch")
            self._evidence(state, pending, result, request_id=request_id, decision_service=decision_service)
            state["verification_requests"][request_id] = result_hash
            state["verification_results"][request_id] = deepcopy(result)
            if result["verdict"] == "uncertain":
                # 不确定不消耗原票据；明确 Agent 复核必须使用新的结算请求 ID。
                _write(self._path(run_id), state)
                return {**deepcopy(state), "status": "verification_required", "reason": result.get("reason", "uncertain")}
            verdict = "cancelled" if state["status"] == "cancel_requested" or (self.session / "closing.json").exists() else result["verdict"]
            state["history"].append({"step_id": pending["step_id"], "execution_request_id": execution_request_id,
                "verdict": verdict, "judged_by": result["judged_by"], "verification_request_id": request_id,
                "verification_result_sha256": result_hash, "command_sha256": pending["command_sha256"],
                "evidence_refs": deepcopy(result["evidence_refs"]),
                **{key: deepcopy(result[key]) for key in optional if key in result}})
            state["pending"] = None
            steps = self._source(state)["plan"]["steps"]
            index = next(i for i, step in enumerate(steps) if step["step_id"] == result["step_id"])
            if verdict == "success" and index + 1 < len(steps):
                state.update(status="ready", current_step_id=steps[index + 1]["step_id"])
            else:
                state["status"] = "completed" if verdict == "success" else "failed" if verdict == "failure" else "cancelled"
                if verdict == "success":
                    state["current_step_id"] = None
            _write(self._path(run_id), state)
            return deepcopy(state)

    def metrics(self, run_id, trial):
        state = self._load(run_id)
        if not isinstance(trial, dict) or trial.get("run_id") != run_id or trial.get("source_kind") != self.source_kind:
            raise ValueError("task_plan_metrics_trial_mismatch")
        return {"source_kind": self.source_kind, "run_id": run_id,
                "planned_steps": len(self._source(state)["plan"]["steps"]), "settled_steps": len(state["history"]),
                "successful_steps": sum(row["verdict"] == "success" for row in state["history"]),
                "measurement_status": "not_collected"}

    def validate_resume(self, run_id, state, *, revalidate_initial=False):
        """这里只核验冻结来源；现场窗口检查仍由宿主原 owner 完成。"""
        trial = self._load(run_id)
        self._require_owner(trial)
        if state is None:
            return
        if (not isinstance(state, dict) or state.get("run_id") != run_id
                or state.get("source_kind") != self.source_kind
                or state.get("recovery_import") is not None or state.get("recovery_settlement") is not None):
            raise ValueError("task_plan_runner_source_mismatch")
        for key in ("plan_id", "plan_sha256", "target_identity", "owner_id", "session_directory"):
            if key in state and state[key] != trial[key]:
                raise ValueError("task_plan_runner_binding_mismatch")
        ticket = state.get("ticket")
        if ticket is None:
            return
        if not isinstance(ticket, dict):
            raise ValueError("task_plan_runner_ticket_invalid")
        pending = trial.get("pending")
        if pending is not None:
            if (any(ticket.get(key) != pending.get(key) for key in ("step_id", "execution_request_id", "suggested_command"))
                    or ticket.get("command_sha256") != pending["command_sha256"]):
                raise ValueError("task_plan_runner_ticket_mismatch")
        else:
            history = trial["history"]
            if (not history or any(ticket.get(key) != history[-1].get(key) for key in
                                   ("step_id", "execution_request_id", "command_sha256"))):
                raise ValueError("task_plan_runner_settlement_mismatch")


__all__ = ["TaskPlanBackend"]
