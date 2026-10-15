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

from .task_plan_contract import _identifier, resolve_action_text, validate_task_plan, validate_task_plan_target, completion_snapshot, goal_completion_proof
from .task_plan_conditions import condition_snapshots, effective_plan_review_policy, semantic_binding, validate_source_conditions
from .task_plan_review import assessment_summary, make_packet, pending_packet, policy_snapshot, review_context, validate_packet, validate_review


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
        self._validated_plan_sha256 = None
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
        plan = source.get("plan")
        plan_sha256 = _digest(plan)
        # 只复用相同内容的结构校验；源文件、身份和条件绑定每次仍完整认证。
        if plan_sha256 != self._validated_plan_sha256:
            plan = validate_task_plan(plan)
            self._validated_plan_sha256 = plan_sha256
        target = validate_task_plan_target(source.get("target_identity"))
        identity = [str(self.session), source.get("owner_id"), plan, target]
        if source.get("successor") is not None:
            identity.append(source["successor"])
        policy = source.get("recovery_policy", "legacy")
        if policy not in {"legacy", "intervention_v1"}:
            raise ValueError("task_plan_recovery_policy_invalid")
        if policy != "legacy":
            identity.append({"recovery_policy": policy})
        expected_id = "task-plan-" + _digest(identity)
        if (source.get("schema_version") != "task_plan_source.v1"
                or source.get("source_kind") != self.source_kind
                or source.get("session_directory") != str(self.session)
                or source.get("plan_id") != expected_id or state.get("plan_id") != expected_id
                or source.get("plan_sha256") != plan_sha256
                or state.get("plan_sha256") != source["plan_sha256"]
                or state.get("owner_id") != source.get("owner_id")
                or state.get("recovery_policy", "legacy") != policy
                or state.get("successor") != source.get("successor")
                or state.get("start_transport_request_id") != source.get("start_transport_request_id")
                or state.get("lineage_generation", 0) != source.get("lineage_generation", 0)
                or state.get("target_identity") != target or state.get("inputs") != plan["inputs"]):
            raise ValueError("task_plan_source_binding_mismatch")
        completion = completion_snapshot(plan)
        if plan["schema_version"] == "task_plan.v3" and state.get("plan_schema_version") != "task_plan.v3":
            raise ValueError("task_plan_completion_version_binding_invalid")
        if completion is not None and (source.get("completion_snapshot") != completion
                or state.get("completion_snapshot_sha256") != _digest(completion)):
            raise ValueError("task_plan_completion_source_binding_invalid")
        if completion is None and ("completion_snapshot" in source or "completion_snapshot_sha256" in state):
            raise ValueError("task_plan_completion_source_binding_invalid")
        validate_source_conditions(source, state)
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
        self._validate_interventions(state, source)
        self._validate_settlements(state, source)
        pending = state.get("pending")
        if pending is not None:
            if (not isinstance(pending, dict) or pending.get("step_id") != state.get("current_step_id")
                    or pending.get("source_kind") != self.source_kind):
                raise ValueError("task_plan_pending_ticket_mismatch")
            step = next(item for item in source["plan"]["steps"] if item["step_id"] == pending["step_id"])
            expected_id = self._execution_id(run_id, step["step_id"], state.get("step_attempts", {}).get(step["step_id"], 0))
            command = self._bound_command(state, step, pending.get("vision_capabilities"), source=source)
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
        if any(requests.get(key) != _digest(value) for key, value in results.items()):
            raise ValueError("task_plan_verification_result_changed")
        for index, row in enumerate(history):
            if not isinstance(row, dict):
                raise ValueError("task_plan_settlement_binding_invalid")
            request_id = row.get("verification_request_id")
            result = results.get(request_id) if isinstance(request_id, str) else None
            step = steps[index]
            execution_id = self._execution_id(state["run_id"], step["step_id"], state.get("step_attempts", {}).get(step["step_id"], 0))
            tickets = [item.get("result") for item in prepares.values() if isinstance(item, dict)
                       and isinstance(item.get("result"), dict) and item["result"].get("execution_request_id") == execution_id]
            if not isinstance(result, dict) or not tickets:
                raise ValueError("task_plan_settlement_binding_invalid")
            result_hash = _digest(result)
            command_hash = _digest(self._bound_command(state, step, tickets[0].get("vision_capabilities"), source=source))
            expected = {"step_id": step["step_id"], "execution_request_id": execution_id,
                        "judged_by": result.get("judged_by"), "verification_request_id": request_id,
                        "verification_result_sha256": result_hash, "command_sha256": command_hash,
                        "evidence_refs": result.get("evidence_refs"),
                          **{key: result[key] for key in ("reason", "original_input_status", "action_executed", "observation", "video_playback", "goal_completion", "main_handoff") if key in result}}
            bindings = {"run_id": state["run_id"], "step_id": step["step_id"], "execution_request_id": execution_id,
                        "plan_id": state["plan_id"], "plan_sha256": state["plan_sha256"], "target_identity": state["target_identity"]}
            goal_proof = goal_completion_proof(source["plan"], result)
            if goal_proof is not None and result.get("original_input_status") == "completed" and (
                    result.get("goal_completion") != goal_proof
                    or row.get("verdict") == "success" and goal_proof["proof"] == "not_proven"):
                raise ValueError("task_plan_goal_completion_settlement_invalid")
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
    def _execution_id(run_id, step_id, attempt=0):
        return "trial-exec-" + _digest([run_id, step_id] + ([attempt] if attempt else []))[:32]

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
        elif verification["kind"] in ("video_playback", "dynamic_content"):
            command["observation_wait_ms"] = verification.get("render_grace_ms", 500)
        elif "render_grace_ms" in verification:
            # 仅显式语义加载合同提前采图；结果仍须 Decision 或原主会话审核。
            command["observation_wait_ms"] = verification["render_grace_ms"]
        return command

    def _bound_command(self, state, step, vision_capabilities=None, *, source=None):
        command = self._command(step, state["inputs"], vision_capabilities)
        plan = (self._source(state) if source is None else source)["plan"]
        if plan["schema_version"] == "task_plan.v3" and step["action"]["kind"] in {"click", "input_sequence"}:
            command["action_review"] = {"schema": "action_review_context.v1", "plan": deepcopy(plan),
                "step_id": step["step_id"], "run_id": state["run_id"],
                "attempt_id": self._execution_id(state["run_id"], step["step_id"],
                    state.get("step_attempts", {}).get(step["step_id"], 0)), "budget_ms": 60000}
            if step["action"]["kind"] == "input_sequence" and "target" not in step["action"]:
                command["field_evidence_mode"] = "visual"
        return command

    @staticmethod
    def _preview(state, step):
        return {"action": deepcopy(step["action"]), "verification": deepcopy(step["verification"]),
                "source_kind": "caller_plan", "plan_id": state["plan_id"],
                "plan_sha256": state["plan_sha256"], "target_identity": deepcopy(state["target_identity"])}

    def start(self, plan, target, request_id, *, recovery_policy=None):
        plan = validate_task_plan(plan)
        if recovery_policy is None:
            recovery_policy = "intervention_v1" if plan["schema_version"] == "task_plan.v3" else "legacy"
        target = validate_task_plan_target(target)
        _identifier(request_id, "request_id")
        self._require_owner(admit=True)
        with self._locked():
            return self._start_locked(plan, target, request_id, recovery_policy=recovery_policy)

    def _start_locked(self, plan, target, request_id, *, successor=None, transport_request_id=None, recovery_policy="legacy"):
        if recovery_policy not in {"legacy", "intervention_v1"}:
            raise ValueError("task_plan_recovery_policy_invalid")
        run_id = "trial-" + _digest([str(self.session), request_id])
        binding = [plan, target] + ([successor] if successor is not None else [])
        if recovery_policy != "legacy":
            binding.append({"recovery_policy": recovery_policy})
        request_hash = _digest(binding)
        path = self._path(run_id)
        if path.exists():
            state = self._load(run_id)
            self._require_owner(state)
            if state.get("start_request_id") != request_id or state.get("start_request_sha256") != request_hash:
                raise ValueError("task_plan_start_idempotency_conflict")
            return deepcopy(state)
        if any(value.get("status") == "reserved" and key != request_id
                for key, value in self._lineage()["requests"].items()):
            raise ValueError("task_plan_successor_admission_pending")
        for existing in self.root.glob("trial-*.json"):
            if self._load(existing.stem)["status"] not in _TERMINAL:
                raise ValueError("task_plan_session_active")
        identity = [str(self.session), self.owner_id, plan, target]
        if successor is not None:
            identity.append(successor)
        if recovery_policy != "legacy":
            identity.append({"recovery_policy": recovery_policy})
        plan_id = "task-plan-" + _digest(identity)
        source = {"schema_version": "task_plan_source.v1", "source_kind": self.source_kind,
            "session_directory": str(self.session), "owner_id": self.owner_id,
            "plan_id": plan_id, "plan_sha256": _digest(plan), "plan": plan, "target_identity": target}
        if recovery_policy != "legacy":
            source["recovery_policy"] = recovery_policy
        completion = completion_snapshot(plan)
        if completion is not None:
            source["completion_snapshot"] = completion
        snapshots = condition_snapshots(plan)
        if snapshots:
            source["condition_snapshots"] = snapshots
        if plan["schema_version"] in {"task_plan.v2", "task_plan.v3"}:
            source["lineage_generation"] = successor["lineage_generation"] + 1 if successor else 0
        if successor is not None:
            source["successor"] = deepcopy(successor)
            source["start_transport_request_id"] = transport_request_id
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
            "current_step_id": plan["steps"][0]["step_id"], "status": "ready", "pending": None,
            "history": [], "prepare_requests": {}, "verification_requests": {},
            "cancel_requests": {}, "verification_results": {}}
        if recovery_policy != "legacy":
            state.update(recovery_policy=recovery_policy, step_attempts={}, intervention_resumes={}, intervention_recovery=None)
        if completion is not None:
            state["completion_snapshot_sha256"] = _digest(completion)
        if snapshots:
            state["condition_snapshots_sha256"] = _digest(snapshots)
        if plan["schema_version"] in {"task_plan.v2", "task_plan.v3"}:
            state.update(plan_schema_version=plan["schema_version"], lineage_generation=source["lineage_generation"])
        if successor is not None:
            state.update(successor=deepcopy(successor), successor_of=successor["successor_of"],
                start_transport_request_id=transport_request_id)
        _write(path, state)
        return deepcopy(state)

    def prefix_sha256(self, run_id):
        return _digest(self._load(run_id)["history"])

    def _lineage(self):
        path = self.root / "successor-admissions.json"
        value = _read(path) if path.is_file() else {"schema": "task_plan_successors.v1", "requests": {}, "parents": {}}
        if (set(value) != {"schema", "requests", "parents"} or value["schema"] != "task_plan_successors.v1"
                or not isinstance(value["requests"], dict) or not isinstance(value["parents"], dict)):
            raise ValueError("task_plan_successor_admission_corrupt")
        return value

    def successor_lookup(self, plan, target, successor, *, vision_capabilities=None, recovery_policy=None):
        if recovery_policy is None:
            recovery_policy = "intervention_v1" if plan["schema_version"] == "task_plan.v3" else "legacy"
        self._require_owner()
        with self._locked():
            records = self._lineage()
            key = successor["successor_request_id"]
            prior = records["requests"].get(key)
            if prior is not None:
                if prior.get("binding_sha256") != _digest([self.owner_id, plan, target, successor, vision_capabilities]
                    + ([{"recovery_policy": recovery_policy}] if recovery_policy != "legacy" else [])):
                    raise ValueError("task_plan_successor_idempotency_conflict")
                path = self._path(prior["run_id"])
                if path.is_file():
                    state = self._load(prior["run_id"])
                    self._require_owner(state)
                    if (state.get("successor") != successor or state["plan_sha256"] != _digest(plan)
                            or state["target_identity"] != target
                            or state.get("start_transport_request_id") != prior.get("start_transport_request_id")):
                        raise ValueError("task_plan_successor_admission_corrupt")
                    return state
                return None
            if successor["successor_of"] in records["parents"]:
                raise ValueError("task_plan_successor_generation_consumed")
            return None

    def start_successor(self, plan, target, successor, *, transport_request_id, vision_capabilities=None, recovery_policy=None):
        plan = validate_task_plan(plan)
        if recovery_policy is None:
            recovery_policy = "intervention_v1" if plan["schema_version"] == "task_plan.v3" else "legacy"
        target = validate_task_plan_target(target)
        self._require_owner(admit=True)
        with self._locked():
            records = self._lineage()
            key, parent_id = successor["successor_request_id"], successor["successor_of"]
            binding_hash = _digest([self.owner_id, plan, target, successor, vision_capabilities]
                    + ([{"recovery_policy": recovery_policy}] if recovery_policy != "legacy" else []))
            prior = records["requests"].get(key)
            if prior is not None and prior.get("binding_sha256") != binding_hash:
                raise ValueError("task_plan_successor_idempotency_conflict")
            if prior is None and parent_id in records["parents"]:
                raise ValueError("task_plan_successor_generation_consumed")
            parent = self._load(parent_id)
            self._require_owner(parent)
            if parent["status"] not in _TERMINAL or parent.get("pending") is not None:
                raise ValueError("task_plan_successor_parent_not_terminal")
            if any(row.get("original_input_status") != "completed"
                    and not (row.get("original_input_status") in {"failed", "cancelled"}
                             and row.get("action_executed") is False) for row in parent["history"]):
                raise ValueError("task_plan_successor_parent_input_unknown")
            if (parent["plan_sha256"] != successor["parent_plan_sha256"]
                    or _digest(parent["history"]) != successor["prefix_sha256"]
                    or parent.get("lineage_generation", 0) != successor["lineage_generation"]
                    or parent["target_identity"] != target):
                raise ValueError("task_plan_successor_parent_binding_mismatch")
            original_steps = self._source(parent)["plan"]["steps"]
            def action_command(step, inputs):
                command = self._command(step, inputs)
                return {key: value for key, value in command.items()
                    if key not in {"observation_condition", "observation_wait_ms"}}
            completed_actions = [action_command(original_steps[index], parent["inputs"])
                for index, row in enumerate(parent["history"])
                if row.get("action_executed") is True and row.get("original_input_status") == "completed"]
            if any(action_command(step, plan["inputs"]) in completed_actions for step in plan["steps"]):
                raise ValueError("task_plan_successor_completed_input_replay_forbidden")
            if prior is None:
                run_id = "trial-" + _digest([str(self.session), key])
                if self._path(run_id).exists():
                    raise ValueError("task_plan_successor_run_id_conflict")
                records["requests"][key] = {"binding_sha256": binding_hash, "run_id": run_id,
                    "parent_run_id": parent_id, "lineage_generation": successor["lineage_generation"], "status": "reserved"}
                records["requests"][key]["start_transport_request_id"] = transport_request_id
                records["parents"][parent_id] = key
                _write(self.root / "successor-admissions.json", records)
            state = self._start_locked(plan, target, key, successor=successor,
                transport_request_id=records["requests"][key]["start_transport_request_id"], recovery_policy=recovery_policy)
            records["requests"][key]["status"] = "committed"
            _write(self.root / "successor-admissions.json", records)
            return state

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
                command = self._bound_command(state, step, vision_capabilities)
                state["pending"] = {"execution_request_id": self._execution_id(run_id, step["step_id"], state.get("step_attempts", {}).get(step["step_id"], 0)),
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

    def _evidence(self, state, pending, result, *, request_id, decision_service, target_identity=None):
        if state["status"] == "cancel_requested" and state.get("intervention_recovery"):
            from .task_plan_intervention import assert_recovery_settled
            assert_recovery_settled(self, state, allow_no_dispatch=True)
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
        from .decision_check import decision_frame, service_enabled
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
        from app.core.input_sequence_partial import original_input_status
        original_status = original_input_status(effective, pending["suggested_command"], succeeded=succeeded,
            action_executed=actual, target_identity=state["target_identity"])
        if (result.get("original_input_status") != original_status or result.get("action_executed") is not actual
                or result["verdict"] == "success" and not succeeded):
            raise ValueError("task_plan_verification_original_input_mismatch")
        if original_status != "completed":
            from .task_plan_review import field_main_handoff
            expected_handoff = field_main_handoff(state, effective, refs, session=self.session,
                service=decision_service, original_status=original_status)
            if result.get("main_handoff") != expected_handoff:
                raise ValueError("task_plan_field_handoff_content_mismatch")
            from .task_plan_intervention import zero_input_verified
            blocked = (state.get("recovery_policy") == "intervention_v1" and actual is False
                and result.get("reason") in {"blocked_before_dispatch", "repeated_obstruction"}
                and result["verdict"] == "uncertain" and result["judged_by"] == "runtime"
                and zero_input_verified(self, state, pending))
            if blocked:
                expected_packet = make_packet(self, state, step, result, None)
                if result.get("review_packet") != expected_packet:
                    raise ValueError("task_plan_intervention_packet_content_mismatch")
                return
            if result["judged_by"] != "runtime" or result["verdict"] != ("failure" if original_status == "failed" else "uncertain"):
                raise ValueError("task_plan_verification_unproven_input")
            return
        if "main_handoff" in result:
            raise ValueError("task_plan_field_handoff_content_mismatch")
        goal_proof = goal_completion_proof(self._source(state)["plan"], result)
        if goal_proof is not None and (result.get("goal_completion") != goal_proof
                or result["verdict"] == "success" and goal_proof["proof"] == "not_proven"):
            raise ValueError("task_plan_goal_completion_proof_required")
        identity = _execution_identity(effective)
        if identity != state["target_identity"]:
            raise ValueError("task_plan_verification_target_mismatch")
        observed = _verified_observation(effective, self.session)
        capture = effective.get("observation") or (effective.get("result") or {}).get("capture")
        frame = decision_frame({**capture, **observed}, identity, role="after")
        if Path(frame["image_path"]).resolve() not in seen:
            raise ValueError("task_plan_verification_image_evidence_missing")
        ledger = None
        if result.get("observation") is not None:
            from .task_plan_observation import validate_observation
            ledger = validate_observation(self, state, result["observation"], refs)
        video_ledger = None
        if result.get("video_playback") is not None:
            from .video_playback_verification import validate_video_playback
            video_ledger = validate_video_playback(self, state, result["video_playback"], refs, frame,
                service=decision_service, target_reader=target_identity,
                adopt=result["judged_by"] in {"video_playback", "decision"},
                original_frame={**deepcopy(capture), **deepcopy(observed), **deepcopy(frame)})
        if (step["verification"]["kind"] in ("video_playback", "dynamic_content")
                and result["judged_by"] in {"video_playback", "decision"} and video_ledger is None):
            raise ValueError("task_plan_video_proof_missing")
        if "review_packet" in result:
            packet = result["review_packet"]
            expected_packet = make_packet(self, state, step, result, frame,
                assessment=packet.get("assessment"), policy=packet.get("policy_snapshot"))
            if packet != expected_packet:
                raise ValueError("task_plan_review_packet_content_mismatch")
            evidence_ledger = video_ledger or ledger
            decision_path = (self.session / evidence_ledger.summary()["assessment_ref"]["path"] if evidence_ledger is not None
                and evidence_ledger.summary()["assessment_ref"] is not None else
                self.session / "task-plan-decisions" / (pending["execution_request_id"] + ".json"))
            if decision_path.resolve() in seen:
                saved = _read(decision_path)
                if packet["assessment"] != assessment_summary(saved["result"]) or packet["policy_snapshot"] != saved.get("policy_snapshot", {}):
                    raise ValueError("task_plan_review_packet_assessment_mismatch")
        before = (effective.get("result") or {}).get("capture") or {}
        if step["action"]["kind"] != "read_text" and before.get("image_path"):
            before_path = Path(before["image_path"])
            before_path = (before_path if before_path.is_absolute() else self.session / before_path).resolve()
            if before_path == Path(frame["image_path"]).resolve():
                raise ValueError("task_plan_verification_post_action_capture_missing")
        judged_by = result["judged_by"]
        if judged_by in {"native_condition", "decision"} and "condition_binding" in step["verification"]:
            semantic = semantic_binding(self._source(state)["plan"], step)
            if effective_plan_review_policy(step["verification"],
                    condition_snapshot=semantic["condition_snapshot"], host_policy=policy_snapshot(decision_service),
                    host_enabled=service_enabled(decision_service)) == "always_main":
                raise ValueError("task_plan_condition_always_main_requires_review")
        if judged_by == "video_playback":
            if (video_ledger is None or result["verdict"] != "success"
                    or video_ledger.summary()["schema"] != "video_playback_binding.v1"
                    or video_ledger.finished()["reason"] != "video_playback_confirmed"
                    or video_ledger.summary()["analysis"]["status"] != "playing"
                    or video_ledger.payloads("adoption_rejected")):
                raise ValueError("task_plan_video_local_proof_invalid")
        elif judged_by == "native_condition":
            if (result["verdict"] != "success" or step["verification"]["kind"] != "native_condition"
                    or not _native_success(step["verification"], effective, frame)):
                raise ValueError("task_plan_verification_native_proof_invalid")
        elif judged_by == "decision":
            source = self._source(state)
            semantic = semantic_binding(source["plan"], step)
            condition = semantic["condition"]
            if step["verification"]["kind"] == "native_condition":
                from .task_plan_native_condition import native_mismatch_eligible
                if (source["plan"]["schema_version"] not in {"task_plan.v2", "task_plan.v3"}
                        or not native_mismatch_eligible(step["verification"], effective, frame,
                            **({"condition_snapshot": semantic["condition_snapshot"]} if "condition_snapshot" in semantic else {}))):
                    raise ValueError("task_plan_verification_native_semantic_proof_invalid")
            evidence_ledger = video_ledger or ledger
            decision_path = (self.session / evidence_ledger.summary()["assessment_ref"]["path"] if evidence_ledger is not None
                and evidence_ledger.summary()["assessment_ref"] is not None else
                self.session / "task-plan-decisions" / (pending["execution_request_id"] + ".json"))
            if not condition or decision_path.resolve() not in seen or decision_service is None:
                raise ValueError("task_plan_verification_decision_evidence_missing")
            saved = _read(decision_path)
            binding = {"request_id": "task-decision-" + sha256(pending["execution_request_id"].encode()).hexdigest()[:32],
                       "execution_request_id": pending["execution_request_id"], **semantic, "frames": [frame],
                       "mode": "execution", "phase": "after_action", "run_id": state["run_id"], "step_id": step["step_id"]}
            if source["plan"]["schema_version"] in {"task_plan.v2", "task_plan.v3"}:
                binding["review_context"] = review_context(source["plan"], step,
                    source_id=state["plan_id"], source_sha256=state["plan_sha256"])
            if ledger is not None:
                from .task_plan_observation import validate_decision_adoption
                binding = validate_decision_adoption(self, state, ledger, frame, saved)
            if video_ledger is not None:
                from .video_playback_verification import validate_video_decision
                binding = validate_video_decision(self, state, video_ledger, frame, saved)
            if ledger is None and video_ledger is None:
                from .task_result_annotation import task_result_click_action, task_result_decision_binding
                binding = task_result_decision_binding(binding, task_result_click_action(step, effective, frame),
                    saved_binding=saved.get("binding"))
            decision = saved.get("result")
            if (saved.get("binding") != binding or not isinstance(decision, dict)
                    or decision.get("adopted") is not True or decision.get("verdict") != result["verdict"]
                    or "review_context" in binding and decision.get("disposition") != "continue"
                    or decision_service.validate_result(decision, **binding) is not True):
                raise ValueError("task_plan_verification_decision_authentication_invalid")
            if "condition_snapshot" in semantic:
                current = self._load(state["run_id"])
                rebuilt = semantic_binding(self._source(current)["plan"], self.pinned_step(
                    state["run_id"], pending["step_id"]))
                if (current != state or rebuilt != semantic
                        or any(binding.get(key) != value for key, value in rebuilt.items())):
                    raise ValueError("task_plan_condition_adoption_binding_invalid")
            if ledger is not None:
                validate_decision_adoption(self, state, ledger, frame, saved)
                from .task_plan_cancellation import assert_no_queued_plan_cancel
                assert_no_queued_plan_cancel(self.session, state["run_id"])
        elif judged_by == "agent":
            review_path = self.session / "task-plan-reviews" / (request_id + ".json")
            if review_path.resolve() not in seen:
                raise ValueError("task_plan_verification_agent_evidence_missing")
            review = _read(review_path)
            if self._source(state)["plan"]["schema_version"] in {"task_plan.v2", "task_plan.v3"}:
                packet = validate_review(review, state, self.session)
                if packet.get("schema") == "review_packet.v3" and any(ref not in refs for ref in packet["artifact_refs"]):
                    raise ValueError("task_plan_manual_settlement_evidence_missing")
            if any(review.get(key) != value for key, value in {
                "run_id": state["run_id"], "step_id": step["step_id"], "execution_request_id": pending["execution_request_id"],
                "verdict": result["verdict"], "reason": result.get("reason"), "evidence_sha256": frame["sha256"],
            }.items()):
                raise ValueError("task_plan_verification_agent_binding_invalid")
        elif result["verdict"] == "success":
            raise ValueError("task_plan_verification_success_provenance_invalid")
        return video_ledger or ledger

    def record_verified_result(self, run_id, request_id, execution_request_id, result, *, decision_service=None,
                               target_identity=None):
        """只接收宿主已验证的结果；再次绑定原票据与原文件，不自行语义判断。"""
        _identifier(request_id, "request_id")
        _identifier(execution_request_id, "execution_request_id")
        required = {"run_id", "step_id", "execution_request_id", "plan_id", "plan_sha256",
                    "target_identity", "verdict", "judged_by", "evidence_refs"}
        optional = {"reason", "original_input_status", "action_executed", "review_packet", "observation", "video_playback", "goal_completion", "main_handoff"}
        if (not isinstance(result, dict) or not required <= set(result) or set(result) - required - optional
                or result.get("verdict") not in {"success", "failure", "uncertain"}
                or result.get("judged_by") not in {"rule", "native_condition", "video_playback", "decision", "agent", "runtime"}
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
            ledger = self._evidence(state, pending, result, request_id=request_id, decision_service=decision_service,
                target_identity=target_identity)
            manual_packet = pending_packet(state) if result["judged_by"] == "agent" else None
            if manual_packet is not None and manual_packet.get("schema") == "review_packet.v3":
                if not callable(target_identity) or target_identity() != state["target_identity"]:
                    raise ValueError("task_plan_manual_window_changed")
                self._require_owner(state)
                if self._load(run_id) != state:
                    raise ValueError("task_plan_manual_state_changed")
                validate_packet(manual_packet, state, self.session)
            if "review_packet" in result:
                if result["verdict"] != "uncertain" or (self._source(state)["plan"]["schema_version"] not in {"task_plan.v2", "task_plan.v3"}
                        and state.get("recovery_policy") != "intervention_v1"):
                    raise ValueError("task_plan_review_packet_result_invalid")
                validate_packet(result["review_packet"], state, self.session)
            if "condition_snapshots_sha256" in state:
                self._require_owner(state)
                if self._load(run_id) != state:
                    raise ValueError("task_plan_condition_state_changed")
                self._source(state)
            state["verification_requests"][request_id] = result_hash
            state["verification_results"][request_id] = deepcopy(result)
            if result["verdict"] == "uncertain":
                # 不确定不消耗原票据；明确 Agent 复核必须使用新的结算请求 ID。
                _write(self._path(run_id), state)
                return {**deepcopy(state), "status": "verification_required", "reason": result.get("reason", "uncertain")}
            verdict = "cancelled" if state["status"] == "cancel_requested" or (self.session / "closing.json").exists() else result["verdict"]
            steps = self._source(state)["plan"]["steps"]
            index = next(i for i, step in enumerate(steps) if step["step_id"] == result["step_id"])
            from .task_plan_cancellation import assert_no_queued_plan_cancel
            # 所有新结算在最终证据校验后复核取消，不让无观察账本的判断绕过门禁。
            assert_no_queued_plan_cancel(self.session, state["run_id"])
            if ledger is not None and result["judged_by"] in {"decision", "video_playback"}:
                self._require_owner(state)
                if result.get("video_playback") is not None:
                    from .video_playback_verification import validate_video_playback
                    validate_video_playback(self, state, result["video_playback"], result["evidence_refs"],
                        ledger.header()["after"], service=decision_service, target_reader=target_identity, adopt=True)
                else:
                    from .task_plan_observation import assert_adoption_budget
                    assert_adoption_budget(ledger)
            if verdict == "cancelled" and state.get("intervention_recovery"):
                from .task_plan_intervention import assert_recovery_settled
                state["intervention_recovery"]["settlement"] = assert_recovery_settled(self, state, allow_no_dispatch=True)
            state["history"].append({"step_id": pending["step_id"], "execution_request_id": execution_request_id,
                "verdict": verdict, "judged_by": result["judged_by"], "verification_request_id": request_id,
                "verification_result_sha256": result_hash, "command_sha256": pending["command_sha256"],
                "evidence_refs": deepcopy(result["evidence_refs"]),
                **{key: deepcopy(result[key]) for key in optional if key in result}})
            state["pending"] = None
            if verdict == "success" and index + 1 < len(steps):
                state.update(status="ready", current_step_id=steps[index + 1]["step_id"])
            else:
                state["status"] = "completed" if verdict == "success" else "failed" if verdict == "failure" else "cancelled"
                if verdict == "success":
                    state["current_step_id"] = None
            _write(self._path(run_id), state)
            return deepcopy(state)

    def _validate_interventions(self, state, source):
        policy = source.get("recovery_policy", "legacy")
        attempts = state.get("step_attempts", {})
        resumes = state.get("intervention_resumes", {})
        permit = state.get("intervention_recovery")
        if policy == "legacy":
            if attempts or resumes or permit:
                raise ValueError("task_plan_legacy_intervention_invalid")
            return
        if not isinstance(attempts, dict) or not isinstance(resumes, dict):
            raise ValueError("task_plan_intervention_binding_invalid")
        expected = {}
        for request_id, row in resumes.items():
            if not isinstance(row, dict) or row.get("request_id") != request_id:
                raise ValueError("task_plan_intervention_resume_invalid")
            packet = row.get("packet")
            if not isinstance(packet, dict) or packet.get("step_id") in expected:
                raise ValueError("task_plan_intervention_attempt_invalid")
            validate_packet(packet, state, self.session)
            original = next((value for value in state["verification_results"].values()
                if value.get("review_packet") == packet), None)
            if (original is None or packet.get("reason") != "blocked_before_dispatch"
                    or original.get("action_executed") is not False
                    or row.get("request_sha256") != _digest(row.get("request"))):
                raise ValueError("task_plan_intervention_resume_evidence_invalid")
            recovery = row.get("recovery")
            settlement = row.get("recovery_settlement")
            if recovery is not None:
                from .task_plan_intervention import assert_recovery_settled
                recovered = assert_recovery_settled(self, {**state, "intervention_recovery": recovery})
                if settlement != recovered:
                    raise ValueError("task_plan_recovery_settlement_binding_invalid")
            elif settlement is not None:
                raise ValueError("task_plan_recovery_settlement_binding_invalid")
            expected[packet["step_id"]] = 1
        if attempts != expected:
            raise ValueError("task_plan_intervention_attempt_binding_invalid")
        if permit is not None:
            from .task_plan_intervention import recovery_command, assert_recovery_settled
            from app.core.instant_command_queue import _request_id
            _request_id(permit.get("recovery_request_id"))
            packet = permit.get("packet")
            validate_packet(packet, state, self.session)
            if (permit.get("request_sha256") != _digest(permit.get("request"))
                    or permit.get("command") != recovery_command(permit.get("command"))
                    or permit.get("command") != permit["request"].get("command")
                    or permit.get("recovery_request_id") != permit["request"].get("recovery_request_id")
                    or any(permit["request"].get(key) != packet.get(key) for key in
                        ("run_id", "wait_id", "step_id", "execution_request_id", "evidence_set_sha256", "assessment_round"))
                    or permit["request"].get("review_packet_sha256") != packet["packet_sha256"]
                    or type(permit.get("admitted", False)) is not bool
                    or permit.get("target_identity") != state["target_identity"]
                    or permit.get("cancel_generation") != len(state["cancel_requests"])
                    and state["status"] not in {"cancel_requested", "cancelled"}):
                raise ValueError("task_plan_recovery_permit_binding_invalid")
            if "settlement" in permit or state["status"] == "cancelled":
                if permit.get("settlement") != assert_recovery_settled(self, state, allow_no_dispatch=True):
                    raise ValueError("task_plan_recovery_settlement_binding_invalid")

    def record_pre_dispatch_block(self, run_id, request_id, execution_request_id, proof, assessment=None):
        state = self._load(run_id)
        pending = state.get("pending")
        from .task_plan_intervention import zero_input_verified
        if (state.get("recovery_policy") != "intervention_v1" or state["status"] != "pending"
                or not pending or pending["execution_request_id"] != execution_request_id
                or not zero_input_verified(self, state, pending)):
            raise ValueError("task_plan_intervention_zero_input_unproven")
        result = deepcopy(proof)
        result.update(verdict="uncertain", judged_by="runtime",
            reason="repeated_obstruction" if state.get("step_attempts", {}).get(pending["step_id"], 0) else "blocked_before_dispatch")
        step = self.pinned_step(run_id, pending["step_id"])
        result["review_packet"] = make_packet(self, state, step, result, None)
        return self.record_verified_result(run_id, request_id, execution_request_id, result)

    def resume_pre_dispatch(self, run_id, request_id, wait_id, review):
        from .task_plan_intervention import checked_block, assert_recovery_settled
        _identifier(request_id, "request_id")
        with self._locked():
            state = self._load(run_id)
            self._require_owner(state, admit=True)
            prior = state.get("intervention_resumes", {}).get(request_id)
            if prior is not None:
                if prior["request_sha256"] != _digest(review) or prior["packet"]["wait_id"] != wait_id:
                    raise ValueError("task_plan_intervention_resume_idempotency_conflict")
                return deepcopy(state)
            packet = checked_block(self, state, review)
            if packet["wait_id"] != wait_id:
                raise ValueError("task_plan_intervention_wait_binding_mismatch")
            recovery_settlement = assert_recovery_settled(self, state)
            from .task_plan_cancellation import assert_no_queued_plan_cancel
            assert_no_queued_plan_cancel(self.session, run_id)
            state["intervention_resumes"][request_id] = {"request_id": request_id,
                "request": deepcopy(review), "request_sha256": _digest(review), "packet": packet,
                "recovery": deepcopy(state.get("intervention_recovery")), "recovery_settlement": recovery_settlement}
            state["step_attempts"][packet["step_id"]] = 1
            state.update(status="ready", pending=None, intervention_recovery=None)
            _write(self._path(run_id), state)
            return deepcopy(state)

    def permit_recovery(self, run_id, request_id, request):
        from .task_plan_intervention import checked_block, recovery_command
        with self._locked():
            state = self._load(run_id)
            self._require_owner(state, admit=True)
            prior = state.get("intervention_recovery")
            if prior is not None:
                if prior["request_id"] != request_id or prior["request_sha256"] != _digest(request):
                    raise ValueError("task_plan_recovery_once_only")
                return deepcopy(prior)
            packet = checked_block(self, state, request)
            command = recovery_command(request["command"])
            permit = {"request_id": request_id, "request": deepcopy(request), "request_sha256": _digest(request),
                "packet": packet, "command": command, "recovery_request_id": request["recovery_request_id"],
                "target_identity": deepcopy(state["target_identity"]), "cancel_generation": len(state["cancel_requests"])}
            state["intervention_recovery"] = permit
            _write(self._path(run_id), state)
            return deepcopy(permit)

    def consume_recovery(self, run_id, request_id, command):
        from .task_plan_intervention import checked_block
        with self._locked():
            state = self._load(run_id)
            self._require_owner(state, admit=True)
            permit = state.get("intervention_recovery")
            if (not permit or permit["recovery_request_id"] != request_id or permit["command"] != command
                    or permit.get("admitted") is True):
                raise ValueError("task_plan_recovery_permit_consumed_or_invalid")
            checked_block(self, state, permit["request"])
            permit["admitted"] = True
            _write(self._path(run_id), state)

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
