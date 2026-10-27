"""Prove completed read-only observations from their original durable artifacts."""
from hashlib import sha256
from math import isfinite
from pathlib import Path


def _require(value):
    if not value:
        raise ValueError("session_input_task_plan_observe_unproven")


def settle_task_plan_observe(root, values, raw, state, runner, request_id, request, snapshot):
    """Settle only an exact terminal capture/rejection; never infer input from a plan.

    The caller has already proved the terminal plan, original dispatches, response
    identity/history prefix and unchanged session catalog. This check binds the
    logical observation to the old/new packets and the final original-step history.
    """
    from app.execution.task_plan_backend import TaskPlanBackend
    from app.execution.task_plan_admission import validate_task_plan_request
    from app.execution.task_plan_observation import ObservationLedger
    from app.execution.task_plan_observation_evidence import project_packet
    from app.execution.task_plan_review import digest, validate_packet
    from app.execution.decision_check import decision_frame
    from app.learning_memory.receipt_adapter import resolve_execution_receipt
    from app.learning_memory.workflow_trial import _execution_identity, _verified_observation
    from .task_plan_input_terminal import evidence_path

    def referenced(ref):
        path = evidence_path(root, ref)
        _require(path in raw and sha256(raw[path]).hexdigest() == ref["sha256"])
        return path

    execution_id = request["execution_request_id"]
    _require(request["action"] == "observe" and request["run_id"] == state["run_id"]
        and request_id not in runner.get("control_requests", {})
        and request_id not in runner.get("resume_requests", {}))
    history = [row for row in state["history"] if row["execution_request_id"] == execution_id]
    _require(len(history) == 1 and history[0]["step_id"] == request["step_id"]
        and history[0].get("original_input_status") == "completed"
        and history[0].get("action_executed") is True)
    results = [value for value in state["verification_results"].values()
        if value.get("execution_request_id") == execution_id and value.get("review_packet")]
    _require(results and all(row["review_packet"] == results[0]["review_packet"] for row in results))
    base = results[0]["review_packet"]
    validate_packet(base, state, root)
    _require(base.get("step_id") == request["step_id"] and base.get("original_input_status") == "completed"
        and base.get("action_executed") is True)
    response_path = "responses/" + execution_id + ".json"
    effective, _ = resolve_execution_receipt(values[response_path], root / response_path, execution_id)
    capture = effective.get("observation") or (effective.get("result") or {}).get("capture")
    original_frame = decision_frame({**capture, **_verified_observation(effective, root)},
        state["target_identity"], role="after")
    _require(_execution_identity(effective) == state["target_identity"] and base["after"] == original_frame)
    original_refs = {"commands/" + execution_id + ".json", response_path,
        Path(original_frame["image_path"]).resolve().relative_to(root).as_posix()}
    _require(original_refs <= {referenced(ref) for ref in base["evidence_refs"]})

    entries = state.get("manual_observations", {}).get(execution_id)
    _require(isinstance(entries, dict) and set(entries) == {"requests", "revisions"}
        and isinstance(entries["requests"], dict) and bool(entries["requests"])
        and isinstance(entries["revisions"], list))
    ledger = ObservationLedger(TaskPlanBackend(root), execution_id)
    events = ledger.read()
    _require(not events or ledger.finished() is not None)
    automatic = sum(event["event"] == "capture_claimed" for event in events)
    _require(automatic + len(entries["requests"]) <= 2)
    previous, expected_artifacts, revisions = base, set(), []
    ordered = sorted(entries["requests"].items(), key=lambda item: item[1]["capture_budget"]["used"])
    for index, (logical_id, saved) in enumerate(ordered, automatic + 1):
        observed_request = saved.get("request")
        _require(validate_task_plan_request(observed_request) == observed_request)
        budget = {"limit": 2, "used": index, "remaining": 2 - index}
        _require(isinstance(observed_request, dict) and observed_request.get("action") == "observe"
            and observed_request.get("observation_request_id") == logical_id
            and saved.get("request_sha256") == digest(observed_request)
            and saved.get("capture_budget") == budget
            and all(type(value) is int for value in saved["capture_budget"].values())
            and type(saved.get("started_ns")) is int and saved["started_ns"] >= 0
            and saved.get("status") in {"captured", "rejected"}
            and all(observed_request.get(key) == previous.get(key) for key in
                ("run_id", "step_id", "execution_request_id", "wait_id", "evidence_set_sha256", "assessment_round"))
            and observed_request.get("review_packet_sha256") == previous["packet_sha256"])
        result = saved.get("result")
        _require(isinstance(result, dict) and result.get("read_only") is True
            and result.get("authorizes_action") is False and result.get("automatic_retry_allowed") is False)
        common = {"schema": "task_plan_manual_observation_result.v1", "observation_request_id": logical_id,
            "run_id": state["run_id"], "execution_request_id": execution_id, "status": saved["status"],
            "read_only": True, "authorizes_action": False, "automatic_retry_allowed": False,
            "manual_observation_budget": budget}
        artifact_root = "task-plan-manual-observations/" + execution_id + "/"
        record_path = artifact_root + "capture-" + digest(observed_request) + ".json"
        observation_id = "task-manual-" + digest([state["run_id"], execution_id, logical_id])[:32]
        image_path = "task-plan-observations/" + observation_id + ".png"
        if saved["status"] == "rejected":
            _require(set(saved) == {"request", "request_sha256", "status", "started_ns", "capture_budget", "result"}
                and isinstance(result.get("reason"), str) and result["reason"].startswith("task_plan_")
                and isinstance(result.get("error_type"), str) and bool(result["error_type"])
                and result == {**common, "reason": result["reason"], "error_type": result["error_type"]}
                and record_path not in values and not (root / image_path).exists())
            continue
        _require(set(saved) == {"request", "request_sha256", "status", "started_ns", "capture_budget", "result", "record_ref"}
            and referenced(saved["record_ref"]) == record_path)
        record = values[record_path]
        _require(record.get("schema") == "task_plan_manual_observation_record.v1"
            and record.get("request") == observed_request and record.get("capture_budget") == budget
            and type(record.get("elapsed_ns")) is int and 0 <= record["elapsed_ns"] < 12_000_000_000
            and type(record.get("capture_elapsed_ms")) in {int, float}
            and isfinite(record["capture_elapsed_ms"]) and 0 <= record["capture_elapsed_ms"] < 12_000
            and referenced(record["image_ref"]) == image_path)
        matches = [item for item in entries["revisions"] if item.get("record_ref") == saved["record_ref"]]
        _require(len(matches) == 1)
        revision = matches[0]
        _require(set(revision) == {"record_ref", "packet_ref", "previous_packet_ref"})
        old_path, new_path = referenced(revision["previous_packet_ref"]), referenced(revision["packet_ref"])
        packet = values[new_path]
        _require(old_path == artifact_root + "packet-" + previous["packet_sha256"] + ".json"
            and values[old_path] == previous
            and new_path == artifact_root + "packet-" + packet["packet_sha256"] + ".json"
            and isinstance(record["frame"].get("capture_id"), str) and bool(record["frame"]["capture_id"])
            and record["frame"]["capture_id"] != original_frame["capture_id"]
            and record["frame"]["capture_id"] != (previous.get("latest_observation") or {}).get("capture_id")
            and result == {**common, "reason": "task_plan_manual_observation_requires_review",
                "packet_sha256": packet["packet_sha256"], "frame": record["frame"], "record_ref": saved["record_ref"]})
        expected_artifacts.update((record_path, old_path, new_path))
        revisions.append(revision)
        previous = packet
    _require(revisions == entries["revisions"]
        and {path for path in values if path.startswith("task-plan-manual-observations/" + execution_id + "/")}
            == expected_artifacts
        and project_packet(state, base, root) == previous)
    validate_packet(previous, state, root)
    history_paths = {referenced(ref) for ref in history[0]["evidence_refs"]}
    _require(original_refs <= history_paths and (not revisions
        or all(ref in history[0]["evidence_refs"] for ref in previous["evidence_refs"])))

    saved = entries["requests"].get(request["observation_request_id"])
    _require(isinstance(saved, dict) and saved["request"] == request
        and snapshot.get("manual_observation") == saved["result"])
    snapshot_entries = snapshot.get("manual_observations", {}).get(execution_id)
    _require(isinstance(snapshot_entries, dict)
        and snapshot_entries.get("requests", {}).get(request["observation_request_id"]) == saved
        and all(entries["requests"].get(key) == value for key, value in snapshot_entries["requests"].items())
        and snapshot_entries.get("revisions") == entries["revisions"][:len(snapshot_entries.get("revisions", []))]
        and all(state["verification_results"].get(key) == value for key, value in
            snapshot.get("verification_results", {}).items()))
    packet = snapshot.get("review_packet")
    if packet is not None:
        validate_packet(packet, snapshot, root)
        _require(packet == project_packet(snapshot, base, root)
            and snapshot.get("runner_state") == "waiting"
            and snapshot.get("wait_reason") == "verification_required"
            and (snapshot.get("pending") or {}).get("execution_request_id") == execution_id
            and all((snapshot.get("wait") or {}).get(key) == value for key, value in {
                "wait_id": packet["wait_id"], "run_id": state["run_id"], "step_id": request["step_id"],
                "command_id": execution_id, "reason": "verification_required"}.items()))
    else:
        _require(snapshot.get("pending") is None and snapshot["history"] == state["history"]
            and snapshot.get("status") == state["status"])
    return {"kind": "task_plan", "terminal_status": state["status"],
        "action_executed": False, "run_id": state["run_id"]}
