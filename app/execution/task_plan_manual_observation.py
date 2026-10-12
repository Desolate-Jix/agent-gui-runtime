"""显式观察先持久占位，原 backend 锁只保护预留和采用，不跨同步截图。"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter_ns

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from .task_plan_cancellation import assert_no_queued_plan_cancel
from .task_plan_contract import _identifier, validate_task_plan_target
from .task_plan_observation import ObservationLedger, _put
from .task_plan_observation_capture import capture_followup
from .task_plan_observation_evidence import (
    _entries, _extend, _revision, project_packet, read_ref as _read_ref, reference, validate_manual_packet,
)
from .task_plan_review import digest


def now_ns():
    return perf_counter_ns()


def assert_no_unsettled_capture(state, execution_id):
    if any(item.get("status") == "reserved" for item in _entries(state, execution_id)["requests"].values()):
        raise ValueError("task_plan_manual_capture_unsettled")


def _capture_budget(backend, state, execution_id):
    automatic = sum(event["event"] == "capture_claimed" for event in ObservationLedger(backend, execution_id).read())
    used = automatic + len(_entries(state, execution_id)["requests"])
    return {"limit": 2, "used": used, "remaining": max(0, 2 - used)}


def manual_observation_status(backend, state):
    pending = state.get("pending")
    if state.get("plan_schema_version") not in {"task_plan.v2", "task_plan.v3"} or not pending:
        return {}
    execution_id = pending["execution_request_id"]
    bases = [value.get("review_packet") for value in state.get("verification_results", {}).values()
        if value.get("execution_request_id") == execution_id and value.get("review_packet")]
    if not bases or bases[0].get("original_input_status") != "completed" or bases[0].get("action_executed") is not True:
        return {}
    budget = _capture_budget(backend, state, execution_id)
    unsettled = any(item.get("status") == "reserved" for item in _entries(state, execution_id)["requests"].values())
    controls = ["cancel"] if unsettled or state.get("status") == "cancel_requested" else ["review", *(
        ["observe"] if budget["remaining"] else []), "cancel"]
    return {"manual_observation_budget": budget, "allowed_controls": controls}


def _request(value):
    fields = {"action", "run_id", "step_id", "execution_request_id", "wait_id", "observation_request_id",
        "review_packet_sha256", "evidence_set_sha256", "assessment_round"}
    if not isinstance(value, dict) or set(value) != fields or value.get("action") != "observe":
        raise ValueError("task_plan_manual_request_invalid")
    for key in ("step_id", "execution_request_id", "wait_id", "observation_request_id"):
        _identifier(value[key], key)
    if type(value["assessment_round"]) is not int or value["assessment_round"] not in (0, 1, 2):
        raise ValueError("task_plan_manual_request_invalid")
    return deepcopy(value)


def _result(request, status, reason, **extra):
    return {"schema": "task_plan_manual_observation_result.v1", "observation_request_id": request["observation_request_id"],
        "run_id": request["run_id"], "execution_request_id": request["execution_request_id"],
        "status": status, "reason": reason, "read_only": True, "authorizes_action": False,
        "automatic_retry_allowed": False, **extra}


def _root_result(state, execution_id):
    matches = [(key, value) for key, value in state["verification_results"].items()
        if value.get("execution_request_id") == execution_id and value.get("review_packet")]
    if not matches:
        raise ValueError("task_plan_manual_review_packet_required")
    return matches[0]


def _guard(runtime, expected, packet, request, *, started=None):
    from .task_plan_review import pending_packet, validate_packet
    backend = runtime.backend
    current = backend._load(request["run_id"])
    backend._require_owner(current, admit=True)
    assert_no_queued_plan_cancel(backend.session, request["run_id"])
    source = backend._source(current)
    snapshot = runtime.runner.status(request["run_id"])
    if (source["plan"]["schema_version"] not in {"task_plan.v2", "task_plan.v3"} or current["status"] != "pending"
            or current.get("pending") != expected.get("pending")
            or snapshot.get("wait_reason") != "verification_required"
            or (snapshot.get("wait") or {}).get("wait_id") != request["wait_id"]
            or packet.get("original_input_status") != "completed" or packet.get("action_executed") is not True):
        raise ValueError("task_plan_manual_requires_verification_wait")
    current_packet = pending_packet(current)
    if (current_packet != packet or any(request[key] != packet[key] for key in
            ("run_id", "step_id", "execution_request_id", "wait_id", "evidence_set_sha256", "assessment_round"))
            or request["review_packet_sha256"] != packet["packet_sha256"]):
        raise ValueError("task_plan_manual_packet_binding_mismatch")
    validate_packet(packet, current, backend.session)
    key, original = _root_result(current, request["execution_request_id"])
    backend._evidence(current, current["pending"], original, request_id=key,
        decision_service=getattr(runtime.coordinator, "_decision_service", None))
    if validate_task_plan_target(runtime._target_identity()) != current["target_identity"]:
        raise ValueError("task_plan_manual_window_changed")
    latest = backend._load(request["run_id"])
    backend._require_owner(latest, admit=True)
    if latest["status"] != current["status"] or latest.get("pending") != current.get("pending"):
        raise ValueError("task_plan_manual_state_changed")
    validate_packet(packet, latest, backend.session)
    if started is not None and not 0 <= now_ns() - started < 12_000_000_000:
        raise ValueError("task_plan_manual_budget_expired")
    assert_no_queued_plan_cancel(backend.session, request["run_id"])
    return current


def _original_frame(backend, execution_id, packet):
    from app.learning_memory.receipt_adapter import resolve_execution_receipt
    from app.learning_memory.workflow_trial import _verified_observation
    path = backend.session / "responses" / (execution_id + ".json")
    effective, _ = resolve_execution_receipt(read_json_snapshot(path), path, execution_id)
    capture = effective.get("observation") or effective["result"].get("capture")
    return {**capture, **_verified_observation(effective, backend.session), **packet["after"]}


def _immutable(path, value):
    if path.exists():
        if read_json_snapshot(path) != value:
            raise ValueError("task_plan_manual_artifact_conflict")
    else:
        _put(path, value)


def observe_task_plan(runtime, request):
    from .decision_check import decision_frame
    from .task_plan_review import pending_packet
    request = _request(request)
    backend, execution_id = runtime.backend, request["execution_request_id"]
    with backend._locked():
        state = backend._load(request["run_id"])
        backend._require_owner(state)
        entries = _entries(state, execution_id)
        prior = entries["requests"].get(request["observation_request_id"])
        if prior is not None:
            if prior["request"] != request or prior["request_sha256"] != digest(request):
                raise ValueError("task_plan_manual_idempotency_conflict")
            if prior["status"] == "reserved":
                return _result(request, "unknown", "task_plan_manual_capture_unknown",
                    manual_observation_budget=deepcopy(prior["capture_budget"]))
            if entries["revisions"]:
                _, root = _root_result(state, execution_id)
                project_packet(state, root["review_packet"], backend.session)
            return deepcopy(prior["result"])
        packet = pending_packet(state)
        if packet is None:
            raise ValueError("task_plan_manual_review_packet_required")
        assert_no_unsettled_capture(state, execution_id)
        _guard(runtime, state, packet, request)
        ledger = ObservationLedger(backend, execution_id)
        events = ledger.read()
        if events and ledger.finished() is None:
            raise ValueError("task_plan_manual_automatic_observation_unsettled")
        if len(entries["requests"]) + sum(event["event"] == "capture_claimed" for event in events) >= 2:
            raise ValueError("task_plan_manual_attempt_limit")
        original_frame = _original_frame(backend, execution_id, packet)
        started = now_ns()
        state.setdefault("manual_observations", {})[execution_id] = entries
        entries["requests"][request["observation_request_id"]] = {
            "request": request, "request_sha256": digest(request), "status": "reserved", "started_ns": started}
        budget = _capture_budget(backend, state, execution_id)
        entries["requests"][request["observation_request_id"]]["capture_budget"] = budget
        write_json_snapshot(backend._path(state["run_id"]), state)

    def guard():
        with backend._locked():
            return _guard(runtime, state, packet, request, started=started)

    try:
        def cancelled():
            guard()
            return False
        captured = capture_followup(runtime.coordinator, session_dir=backend.session,
            target_identity=state["target_identity"], original_frame=original_frame,
            observation_id="task-manual-" + digest([state["run_id"], execution_id, request["observation_request_id"]])[:32],
            cancelled=cancelled, remaining_seconds=lambda: max(0, 12 - (now_ns() - started) / 1_000_000_000))
        with backend._locked():
            current = _guard(runtime, state, packet, request, started=started)
            frame = captured["frame"]
            if (set(frame) != {"capture_id", "image_path", "sha256", "window_identity", "role"}
                    or frame["role"] != "observation" or frame["window_identity"] != state["target_identity"]
                    or decision_frame(frame, state["target_identity"], role="observation") != frame):
                raise ValueError("task_plan_manual_capture_binding_invalid")
            known = [packet["after"]] + ([packet["latest_observation"]] if "latest_observation" in packet else [])
            known.extend(event["payload"]["frame"] for event in ledger.read() if event["event"] == "captured")
            if any(frame["capture_id"] == old["capture_id"] or Path(frame["image_path"]).samefile(old["image_path"])
                    for old in known):
                raise ValueError("task_plan_manual_capture_reused")
            root = backend.session / "task-plan-manual-observations" / execution_id
            if root.is_symlink() or root.parent.is_symlink() or not root.resolve().is_relative_to(backend.session):
                raise ValueError("task_plan_manual_artifact_outside_session")
            root.mkdir(parents=True, exist_ok=True)
            previous_path = root / ("packet-" + packet["packet_sha256"] + ".json")
            _immutable(previous_path, packet)
            previous_ref = reference(backend.session, previous_path)
            record = {"schema": "task_plan_manual_observation_record.v1", "request": request,
                "frame": deepcopy(frame), "image_ref": reference(backend.session, frame["image_path"]),
                "elapsed_ns": now_ns() - started, "capture_elapsed_ms": captured["capture_elapsed_ms"],
                "capture_budget": deepcopy(budget)}
            record_path = root / ("capture-" + digest(request) + ".json")
            _immutable(record_path, record)
            record_ref = reference(backend.session, record_path)
            revised = _revision(packet, record, record_ref, previous_ref)
            revised_path = root / ("packet-" + revised["packet_sha256"] + ".json")
            _immutable(revised_path, revised)
            result = _result(request, "captured", "task_plan_manual_observation_requires_review",
                packet_sha256=revised["packet_sha256"], frame=deepcopy(frame), record_ref=record_ref,
                manual_observation_budget=deepcopy(budget))
            current_entries = _entries(current, execution_id)
            current_entries["requests"][request["observation_request_id"]].update(
                status="captured", result=result, record_ref=record_ref)
            current_entries["revisions"].append({"record_ref": record_ref,
                "packet_ref": reference(backend.session, revised_path), "previous_packet_ref": previous_ref})
            _guard(runtime, state, packet, request, started=started)
            if reference(backend.session, frame["image_path"]) != record["image_ref"]:
                raise ValueError("task_plan_manual_capture_changed")
            assert_no_queued_plan_cancel(backend.session, request["run_id"])
            if not 0 <= now_ns() - started < 12_000_000_000:
                raise ValueError("task_plan_manual_budget_expired")
            write_json_snapshot(backend._path(state["run_id"]), current)
            return result
    except Exception as error:
        reason = getattr(error, "reason_code", None) or (str(error) if str(error).startswith("task_plan_")
            else "task_plan_manual_capture_failed")
        result = _result(request, "rejected", reason, error_type=type(error).__name__,
            manual_observation_budget=deepcopy(budget))
        with backend._locked():
            current = backend._load(state["run_id"])
            backend._require_owner(current)
            saved = _entries(current, execution_id)["requests"][request["observation_request_id"]]
            if saved["status"] != "reserved":
                raise ValueError("task_plan_manual_reservation_changed") from None
            saved.update(status="rejected", result=result)
            write_json_snapshot(backend._path(state["run_id"]), current)
        return result


__all__ = ["observe_task_plan", "validate_manual_packet", "manual_observation_status"]
