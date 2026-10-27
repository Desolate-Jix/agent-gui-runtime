"""只读闭合调用方计划的原输入事实；不重建执行权限或推定任务成功。"""
import hashlib
import json
from pathlib import Path


_TERMINAL = {"completed", "failed", "cancelled"}


def _require(value, code):
    if not value:
        raise ValueError("session_input_task_plan_" + code)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def evidence_path(root, reference):
    """Validate an original, session-relative byte reference before cataloguing it."""
    _require(isinstance(reference, dict) and set(reference) == {"path", "sha256"}
        and isinstance(reference["path"], str) and bool(reference["path"])
        and isinstance(reference["sha256"], str) and len(reference["sha256"]) == 64
        and all(c in "0123456789abcdef" for c in reference["sha256"]), "evidence_invalid")
    relative = Path(reference["path"])
    path = (root / relative).resolve()
    _require(not relative.is_absolute() and path.is_relative_to(root) and path != root
        and path.is_file(), "evidence_path_invalid")
    return path.relative_to(root).as_posix()


def _review_bound(values, state, request, request_id):
    saved = values.get("task-plan-reviews/" + request_id + ".json")
    if saved == request:
        result = state["verification_results"].get(request_id)
        return isinstance(result, dict) and result.get("judged_by") == "agent"
    worker = values.get("agent-commands/" + request["execution_request_id"] + ".json", {})
    # Before-dispatch and field-value reviews remain evidence, never a new capability.
    for key, schema, stage in (("pre_action_review", "pre_action_review_packet.v1", "before"),
                               ("field_review", "field_review_packet.v1", "after")):
        record = worker.get(key)
        if not isinstance(record, dict) or record.get("review_request_id") != request_id:
            continue
        packet = record.get("packet") or {}
        return (record.get("review") == request and packet.get("schema") == schema
            and packet.get("packet_sha256") == _digest({k: v for k, v in packet.items() if k != "packet_sha256"})
            and all(packet.get(k) == request.get(k) for k in
                ("run_id", "step_id", "execution_request_id", "evidence_set_sha256", "assessment_round"))
            and packet.get("plan_sha256") == state["plan_sha256"]
            and request.get("review_packet_sha256") == packet["packet_sha256"]
            and request.get("evidence_sha256") == (packet.get(stage) or {}).get("sha256"))
    return False


def settle_api_grounding(path, values, results, validate_worker, bind_dispatch):
    """Bind the runtime's internal API ID to its one original plan-owned dispatch."""
    grounding = values[path]
    request_id, receipt = grounding.get("request_id"), grounding.get("execution_result")
    _require(grounding.get("contract_version") == "grounding_handoff.v1"
        and Path(path).stem == request_id and grounding.get("phase") == "completed"
        and type(grounding.get("input_attempted")) is bool
        and grounding.get("input_dispatched") is (None if grounding["input_attempted"] else False)
        and isinstance(receipt, dict) and receipt.get("contract_version") == "local_direct_step_v1"
        and receipt.get("operation") == "execute_recognition_plan"
        and receipt.get("local_input_scope_closed") is True
        and receipt.get("phase") in {"returned", "returned_observation_unavailable", "not_dispatched"}, "api_grounding_unsettled")
    def origin_bound(worker):
        if (worker.get("api_request") or {}).get("request_id") == request_id:
            return True
        calls = worker.get("recognition_calls")
        if not isinstance(calls, list):
            return False
        matching = [call for call in calls if isinstance(call, dict) and call.get("request_id") == request_id]
        capture_id = (grounding.get("capture") or {}).get("capture_id")
        return (len(matching) == 1 and isinstance(capture_id, str) and bool(capture_id)
            and matching[0].get("capture_id") == capture_id and matching[0].get("source") == "external_api")
    candidates = [(Path(p).stem, value) for p, value in values.items()
        if p.startswith("agent-commands/") and origin_bound(value)]
    _require(len(candidates) == 1, "api_grounding_origin_unproven")
    original_id, worker = candidates[0]
    owners = [trial for p, trial in values.items() if p.startswith("task-plans/trial-")
        and any(row.get("execution_request_id") == original_id for row in trial.get("history", []))]
    _require(len(owners) == 1 and grounding.get("owner_id") == owners[0].get("owner_id")
        and original_id in results and type(results[original_id].get("action_executed")) is bool,
        "api_grounding_origin_unproven")
    validate_worker(worker, original_id)
    command = values.get("commands/" + original_id + ".json")
    _require(isinstance(command, dict), "api_grounding_receipt_unproven")
    # A sequence's earlier focus is not its final typing receipt. The shared
    # binder requires every ordered batch receipt and the matching attempt index.
    index, action = bind_dispatch(worker, command, receipt)
    _require(type(action) is bool and (grounding["input_attempted"] or action is False), "api_grounding_action_unproven")
    if receipt["phase"] == "not_dispatched":
        from app.core.recognition_dispatch import local_receipt_zero_input_verified
        _require(action is False and grounding["input_attempted"] is False
            and local_receipt_zero_input_verified(receipt, "execute_recognition_plan"), "api_grounding_zero_input_unproven")
    return original_id, index


def settle_task_plan_inputs(root, values, raw, input_result):
    """Return control settlements only after every persisted plan and dispatch is terminal.

    Called by inspect_session_input_terminal inside its unchanged-catalog check. The
    backend's read-only loader authenticates source and history structure; original
    receipts, byte references and queue inputs independently prove input settlement.
    """
    from app.execution.task_plan_admission import validate_task_plan_request
    from app.execution.task_plan_backend import TaskPlanBackend
    from app.core.input_sequence_partial import original_input_status
    from app.learning_memory.receipt_adapter import resolve_execution_receipt
    from app.learning_memory.workflow_trial import _actual_action_executed, _receipt_state

    controls = {Path(path).stem: value for path, value in values.items()
                if path.startswith("commands/") and value.get("kind") == "task_plan"}
    results, rejected = {}, set()
    _require(all(path.count("/") == 1 for path in values if path.startswith("task-plan-controls/")),
        "control_receipt_layout")
    receipts = {Path(path).stem: value for path, value in values.items()
        if path.startswith("task-plan-controls/")}
    receipt_owners = set()
    for request_id, receipt in receipts.items():
        path = "task-plan-controls/" + request_id + ".json"
        command = controls.get(request_id)
        response = values.get("responses/" + request_id + ".json")
        expected = {"schema": "task_plan_control_receipt.v1", "session_directory": str(root),
            "owner_id": receipt.get("owner_id"), "request_id": request_id,
            "command_sha256": _digest(command)}
        _require(path in values and isinstance(command, dict) and isinstance(response, dict)
            and response.get("command") == command and isinstance(receipt.get("owner_id"), str)
            and bool(receipt["owner_id"].strip()) and len(receipt["owner_id"]) <= 160
            and all(receipt.get(key) == value for key, value in expected.items())
            and type(receipt.get("input_dispatch_started")) is bool, "control_receipt_binding")
        receipt_owners.add(receipt["owner_id"])
        if receipt.get("phase") == "returned":
            _require(receipt == {**expected, "phase": "returned",
                "input_dispatch_started": receipt["input_dispatch_started"]}
                and response.get("status") == "returned", "control_receipt_unsettled")
            continue
        _require(receipt == {**expected, "phase": "rejected_before_dispatch", "input_dispatch_started": False,
                "error_type": response.get("error_type"), "error_sha256": _digest(response.get("error"))}
            and response.get("status") == "failed" and isinstance(response.get("error_type"), str)
            and isinstance(response.get("error"), str) and response.get("automatic_retry_allowed") is False
            and response.get("result") == {"contract_version": "task_plan_control_rejection.v1",
                "request_id": request_id, "status": "rejected_before_dispatch", "input_attempted": False,
                "action_executed": False, "record": {"path": path, "sha256": hashlib.sha256(raw[path]).hexdigest()}}
            and (response.get("result") or {}).get("input_attempted") is False
            and (response.get("result") or {}).get("action_executed") is False
            and "agent-commands/" + request_id + ".json" not in values
            and response.get("observation") is None, "control_rejection_unproven")
        results[request_id] = {"kind": "task_plan", "terminal_status": "not_dispatched", "action_executed": False}
        rejected.add(request_id)
    _require(len(receipt_owners) <= 1, "control_owner_mismatch")
    artifacts = {path: value for path, value in values.items()
                 if path.startswith(("task-plans/", "task-plan-runners/"))}
    if not controls and not artifacts and not receipts:
        return {}
    if not artifacts:
        _require(set(controls) == rejected, "runner_missing")
        return results
    backend = TaskPlanBackend(root)
    states, runners, sources = {}, {}, set()
    for path, value in artifacts.items():
        _require(path.count("/") == 1, "layout_invalid")
        if path.startswith("task-plans/trial-"):
            run_id = Path(path).stem
            state = backend.status(run_id)
            _require(state == value and state.get("status") in _TERMINAL
                and state.get("pending") is None, "unsettled")
            source = backend._source(state)
            sources.add("task-plans/" + state["plan_id"] + ".json")
            states[run_id] = state
        elif path.startswith("task-plan-runners/trial-"):
            _require(value.get("schema") == "workflow_runner.v1" and value.get("source_kind") == "caller_plan"
                and value.get("run_id") == Path(path).stem, "runner_binding")
            runners[Path(path).stem] = value
        elif path == "task-plans/successor-admissions.json":
            _require(value == backend._lineage() and isinstance(value.get("requests"), dict)
                and all(isinstance(row, dict) and row.get("status") == "committed"
                    for row in value["requests"].values()), "lineage_unsettled")
        elif path == "task-plan-runners/active.json":
            _require(value.get("schema") == "workflow_runner.v1" and value.get("source_kind") == "caller_plan", "runner_binding")
        else:
            _require(path.startswith("task-plans/task-plan-"), "artifact_unknown")
    _require(states and set(states) == set(runners), "runner_missing")
    _require(not receipt_owners or all(state["owner_id"] in receipt_owners for state in states.values()),
        "control_owner_mismatch")
    for request_id in rejected:
        request = controls[request_id].get("request")
        if (isinstance(request, dict) and request.get("action") == "observe"
                and all(isinstance(request.get(key), str) for key in
                    ("run_id", "execution_request_id", "observation_request_id"))):
            state = states.get(request.get("run_id"), {})
            observations = state.get("manual_observations", {})
            _require(isinstance(observations, dict), "control_observation_unsettled")
            entries = observations.get(request.get("execution_request_id"), {})
            _require(isinstance(entries, dict) and isinstance(entries.get("requests", {}), dict),
                "control_observation_unsettled")
            _require(request.get("observation_request_id") not in entries.get("requests", {}),
                "control_observation_unsettled")
        _require(all(request_id not in state.get(key, {}) for state in states.values()
            for key in ("verification_results", "verification_requests", "cancel_requests", "prepare_requests",
                "intervention_resumes")) and all(request_id not in runner.get(key, {}) for runner in runners.values()
                for key in ("control_requests", "resume_requests", "intervention_resume_requests"))
            and all(request_id not in {state.get("start_request_id"), state.get("start_transport_request_id")}
                for state in states.values()), "control_rejection_conflict")
    _require({p for p in artifacts if p.startswith("task-plans/task-plan-")} == sources, "source_orphan")
    active = artifacts.get("task-plan-runners/active.json")
    _require(active is not None and active.get("run_id") in states, "active_binding")
    actions = {}
    for run_id, state in states.items():
        source, runner = backend._source(state), runners[run_id]
        start_id = state.get("start_transport_request_id") or state["start_request_id"]
        start = controls.get(start_id)
        _require(isinstance(start, dict) and start.get("request", {}).get("action") == "start"
            and start["request"].get("plan") == source["plan"], "start_binding")
        request = validate_task_plan_request(start["request"])
        _require(run_id == "trial-" + _digest([str(root), state["start_request_id"]])
            and runner.get("start_request_id") == state["start_request_id"]
            and runner.get("runner_state") == state["status"]
            and runner.get("ticket") is None and runner.get("wait") is None
            and runner.get("verification_wait") is None
            and runner.get("current_step_id") == state["current_step_id"]
            and type(runner.get("steps_completed")) is int
            and runner["steps_completed"] == len(state["history"])
            and runner.get("seen_steps") == [row["step_id"] for row in state["history"]], "runner_unsettled")
        start_binding = [source["plan"], state["target_identity"]]
        if state.get("successor") is not None:
            _require(request.get("successor") == state["successor"], "start_binding")
            start_binding.append(state["successor"])
        if state.get("recovery_policy", "legacy") != "legacy":
            start_binding.append({"recovery_policy": state["recovery_policy"]})
        _require(state.get("start_request_sha256") == _digest(start_binding), "start_binding")
        _require(state["status"] != "cancelled" or state["cancel_requests"]
            or isinstance(values.get("closing.json"), dict), "cancel_origin_unproven")
        expected_start = {"action": "run", "run_id": run_id, "mode": runner.get("mode")}
        if request.get("vision_capabilities") is not None:
            expected_start["vision_capabilities"] = request["vision_capabilities"]
        _require(runner.get("mode") == "until_wait"
            and runner.get("vision_capabilities") == request.get("vision_capabilities")
            and runner.get("control_requests", {}).get(state["start_request_id"]) == {
                "schema": "workflow_runner_control.v1",
                "command_sha256": _digest({"kind": "task_plan", "request": expected_start})}, "start_origin_unproven")
        actions[run_id] = False
        for row in state["history"]:
            execution_id = row["execution_request_id"]
            original = input_result(execution_id)
            _require(isinstance(original, dict) and original.get("terminal_status") in
                {"returned", "completed", "failed", "cancelled", "interrupted", "not_dispatched"}, "input_unsettled")
            command = values.get("commands/" + execution_id + ".json")
            response = values.get("responses/" + execution_id + ".json")
            _require(isinstance(command, dict) and _digest(command) == row["command_sha256"]
                and isinstance(response, dict) and response.get("command") == command, "input_binding")
            succeeded, terminal, _ = _receipt_state(response, root / "responses" / (execution_id + ".json"), execution_id, command)
            effective, resolved = resolve_execution_receipt(response, root / "responses" / (execution_id + ".json"), execution_id)
            actual = False if command["kind"] == "read_text" else _actual_action_executed(effective.get("result"), terminal)
            status = original_input_status(effective, command, succeeded=succeeded,
                action_executed=actual, target_identity=state["target_identity"])
            _require(terminal == resolved and type(actual) is bool and status in {"completed", "failed", "cancelled"}
                and row.get("action_executed") is actual and row.get("original_input_status") == status
                and (command["kind"] == "read_text" or original.get("action_executed") is actual), "input_unknown")
            if terminal is not None and actual:
                worker = values["agent-commands/" + execution_id + ".json"]
                _require(any(attempt.get("action_executed") is True for attempt in worker["dispatch_attempts"]),
                    "dispatch_evidence_missing")
            actions[run_id] = actions[run_id] or actual
            refs = row.get("evidence_refs")
            _require(isinstance(refs, list) and refs, "evidence_missing")
            seen = set()
            for ref in refs:
                path = evidence_path(root, ref)
                _require(path not in seen and path in raw and hashlib.sha256(raw[path]).hexdigest() == ref["sha256"], "evidence_changed")
                seen.add(path)
            required = {"commands/" + execution_id + ".json", "responses/" + execution_id + ".json"}
            if terminal is not None:
                required.add("agent-commands/" + execution_id + ".json")
            _require(required <= seen, "evidence_missing")
        cancel_id = runner.get("cancel_request_id")
        _require(cancel_id is None or state["cancel_requests"].get(cancel_id) is True
            and controls.get(cancel_id) == {"kind": "task_plan", "request": {"action": "cancel", "run_id": run_id}}, "cancel_binding")

    for request_id, command in controls.items():
        if request_id in rejected:
            continue
        _require(set(command) == {"kind", "request"}, "control_invalid")
        request = validate_task_plan_request(command["request"])
        response = values.get("responses/" + request_id + ".json")
        _require(isinstance(response, dict) and response.get("command") == command, "response_missing")
        action = request["action"]
        if action == "start":
            matches = [s for s in states.values() if (s.get("start_transport_request_id") or s["start_request_id"]) == request_id]
            _require(len(matches) == 1, "start_binding")
            run_id = matches[0]["run_id"]
        else:
            run_id = request["run_id"]
        _require(run_id in states, "control_binding")
        state, runner = states[run_id], runners[run_id]
        snapshot = response.get("result")
        _require(response.get("status") == "returned" and isinstance(snapshot, dict)
            and all(snapshot.get(k) == state[k] for k in
                ("run_id", "plan_id", "plan_sha256", "owner_id", "session_directory", "target_identity"))
            and snapshot.get("source_kind") == "caller_plan"
            and isinstance(snapshot.get("history"), list)
            and snapshot["history"] == state["history"][:len(snapshot["history"])], "response_binding")
        if action == "observe":
            from .task_plan_observation_terminal import settle_task_plan_observe
            results[request_id] = settle_task_plan_observe(root, values, raw, state, runner,
                request_id, request, snapshot)
            continue
        if action == "continue":
            _require(runner.get("resume_requests", {}).get(request_id) == request["wait_id"]
                and runner.get("control_requests", {}).get(request_id) == {
                    "schema": "workflow_runner_control.v1", "command_sha256": _digest(command)}, "continue_binding")
        elif action == "review":
            _require(_review_bound(values, state, request, request_id), "review_binding")
        elif action == "cancel":
            recorded = runner.get("cancel_request_id") == request_id and state["cancel_requests"].get(request_id) is True
            terminal_noop = (runner.get("cancel_request_id") is None and request_id not in state["cancel_requests"]
                and snapshot.get("status") == state["status"] and snapshot.get("runner_state") == state["status"]
                and snapshot["history"] == state["history"] and snapshot.get("pending") is None
                and snapshot.get("active_command_id") is None and snapshot.get("wait") is None)
            _require(recorded or terminal_noop, "cancel_binding")
            if terminal_noop:
                results[request_id] = {"kind": "task_plan", "terminal_status": state["status"],
                    "action_executed": False, "run_id": run_id}
                continue
        else:
            _require(action in {"start", "status"}, "control_unsupported")
        results[request_id] = {"kind": "task_plan", "terminal_status": state["status"],
            "action_executed": actions[run_id], "run_id": run_id}
    return results
