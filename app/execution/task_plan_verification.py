"""核验临时计划的原命令回执；不补执行、不重截图、不推断未知输入。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.learning_memory.receipt_adapter import resolve_execution_receipt
from app.learning_memory.workflow_trial import (
    _actual_action_executed, _execution_identity, _receipt_state, _verified_observation,
)
from .decision_check import decision_frame, service_enabled
from .task_plan_contract import _identifier


def _reference(session, path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(session):
        raise ValueError("task_plan_evidence_outside_session")
    return {"path": path.relative_to(session).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}


def _unchanged(session, references):
    for item in references:
        if _reference(session, session / item["path"]) != item:
            raise ValueError("task_plan_original_evidence_changed")


def _save_once(path, value):
    if path.is_file():
        if read_json_snapshot(path) != value:
            raise ValueError("task_plan_verification_artifact_conflict")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_snapshot(path, value)


def _native_success(rule, effective, frame):
    result = effective["result"]
    if effective["command"]["kind"] == "input_sequence":
        steps = result.get("steps") or []
        if not steps or steps[-1].get("name") != "search":
            return False
        observation = (steps[-1].get("receipt") or {}).get("observation") or {}
    else:
        observation = result.get("observation") or {}
    proof = observation.get("condition") or {}
    if (proof.get("status") != "condition_met" or proof.get("source") != "uia_exact_name"
            or proof.get("expected") != rule["condition"]
            or proof.get("after_sha256") != frame["sha256"]
            or (observation.get("capture") or {}).get("sha256") != frame["sha256"]
            or proof.get("after_capture_rechecked") is not True):
        return False
    samples = proof.get("samples")
    if not isinstance(samples, list) or len(samples) < 3:
        return False
    if not ((proof.get("baseline") or {}).get("status") == "absent"
            or any(item.get("status") == "absent" for item in samples[:-3])):
        return False
    recent = samples[-3:]
    keys = [(s.get("runtime_id"), s.get("bbox"), s.get("target_window_handle"), s.get("process_id")) for s in recent]
    identity = frame["window_identity"]
    if (any(s.get("status") != "matched" for s in recent) or not keys[0][0] or not keys[0][1]
            or any(k != keys[0] for k in keys)
            or keys[0][2:] != (identity["handle"], identity["process_id"])):
        return False
    times = [s.get("elapsed_ms") for s in recent]
    return (all(type(t) in (int, float) for t in times)
            and times[1] - times[0] >= 99 and times[2] >= times[1])


def verify_task_plan_step(backend, *, session_dir, run_id, request_id, execution_id,
                          decision_service=None, review=None):
    session = Path(session_dir).resolve()
    _identifier(request_id, "request_id")
    _identifier(execution_id, "execution_request_id")
    backend.validate_resume(run_id, None)
    state = backend.status(run_id)
    review_path = session / "task-plan-reviews" / (request_id + ".json")
    prior = state.get("verification_results", {}).get(request_id)
    if prior is not None:
        if prior.get("execution_request_id") != execution_id:
            raise ValueError("task_plan_verification_idempotency_conflict")
        if review is not None and (not review_path.is_file() or read_json_snapshot(review_path) != review
                or prior.get("judged_by") != "agent" or prior.get("step_id") != review["step_id"]
                or prior.get("verdict") != review["verdict"] or prior.get("reason") != review["reason"]):
            raise ValueError("task_plan_review_idempotency_conflict")
        if review is None and prior.get("judged_by") == "agent":
            raise ValueError("task_plan_review_idempotency_conflict")
        _unchanged(session, prior["evidence_refs"])
        return backend.record_verified_result(run_id, request_id, execution_id, prior, decision_service=decision_service)
    pending = state.get("pending")
    if pending is None or pending["execution_request_id"] != execution_id:
        raise ValueError("task_plan_pending_ticket_mismatch")
    step = backend.pinned_step(run_id, pending["step_id"])
    receipt_path = session / "responses" / (execution_id + ".json")
    receipt = read_json_snapshot(receipt_path)
    references = [_reference(session, receipt_path),
                  _reference(session, session / "commands" / (execution_id + ".json"))]
    succeeded, terminal, _ = _receipt_state(receipt, receipt_path, execution_id, pending["suggested_command"])
    effective, resolved_terminal = resolve_execution_receipt(receipt, receipt_path, execution_id)
    if terminal != resolved_terminal:
        raise ValueError("task_plan_terminal_receipt_changed")
    if terminal is not None:
        references.append(_reference(session, terminal["path"]))
    actual = False if step["action"]["kind"] == "read_text" else _actual_action_executed(effective.get("result"), terminal)
    result = {"run_id": run_id, "step_id": step["step_id"], "execution_request_id": execution_id,
              "plan_id": state["plan_id"], "plan_sha256": state["plan_sha256"],
              "target_identity": deepcopy(state["target_identity"]), "verdict": "uncertain",
              "judged_by": "runtime", "evidence_refs": references,
              "reason": "original_input_not_verified", "action_executed": actual,
              "original_input_status": "completed" if succeeded else "failed" if actual is False else "unknown"}
    # 已知失败只停止；部分输入或未知副作用保留原票据，不能当作成功或零输入。
    if not succeeded:
        if review is not None:
            raise ValueError("task_plan_review_original_input_unverified")
        if actual is False:
            result.update(verdict="failure", reason="original_input_failed")
        _unchanged(session, references)
        return backend.record_verified_result(run_id, request_id, execution_id, result, decision_service=decision_service)
    identity = _execution_identity(effective)
    if identity != state["target_identity"]:
        raise ValueError("task_plan_execution_target_mismatch")
    observed = _verified_observation(effective, session)
    capture = effective.get("observation") or (effective.get("result") or {}).get("capture")
    frame = decision_frame({**capture, **observed}, identity, role="after")
    references.append(_reference(session, frame["image_path"]))
    # 后图只能来自原命令；有前图时还必须排除把前图改名当作后图。
    before = (effective.get("result") or {}).get("capture") or {}
    if step["action"]["kind"] != "read_text" and before.get("image_path"):
        before_path = Path(before["image_path"])
        before_path = (before_path if before_path.is_absolute() else session / before_path).resolve()
        if before_path == Path(frame["image_path"]).resolve():
            raise ValueError("task_plan_post_action_capture_missing")
    if review is not None:
        if (review["step_id"] != step["step_id"] or review["evidence_sha256"] != frame["sha256"]
                or state["status"] == "cancel_requested"):
            raise ValueError("task_plan_review_binding_mismatch")
        _save_once(review_path, review)
        references.append(_reference(session, review_path))
        result.update(verdict=review["verdict"], judged_by="agent", reason=review["reason"])
    elif state["status"] == "cancel_requested":
        result.update(verdict="failure", reason="cancel_requested_original_execution_terminal")
    elif step["verification"]["kind"] == "native_condition":
        if _native_success(step["verification"], effective, frame):
            result.update(verdict="success", judged_by="native_condition", reason="declared_native_condition_met")
        else:
            result.update(reason="native_condition_requires_agent_review")
    else:
        condition = step["verification"].get("decision_condition")
        result.update(reason="agent_judgment_required")
        if condition and service_enabled(decision_service) and not (session / "closing.json").exists():
            binding = {"request_id": "task-decision-" + sha256(execution_id.encode()).hexdigest()[:32],
                       "execution_request_id": execution_id, "condition": condition, "frames": [frame],
                       "mode": "execution", "phase": "after_action", "run_id": run_id, "step_id": step["step_id"]}
            decision_path = session / "task-plan-decisions" / (execution_id + ".json")
            if decision_path.is_file():
                saved = read_json_snapshot(decision_path)
                if saved["binding"] != binding:
                    raise ValueError("task_plan_decision_binding_changed")
                decision = saved["result"]
            else:
                started = perf_counter_ns()
                decision = decision_service.evaluate(**binding)
                _save_once(decision_path, {"binding": binding, "result": decision,
                    "measurement": {"started_ns": started, "ended_ns": perf_counter_ns()}})
            references.append(_reference(session, decision_path))
            if (isinstance(decision, dict) and decision.get("adopted") is True
                    and decision.get("verdict") in {"success", "failure"}
                    and decision_service.validate_result(decision, **binding)):
                result.update(verdict=decision["verdict"], judged_by="decision", reason="authenticated_decision")
            else:
                result.update(reason="decision_requires_agent_review")
    _unchanged(session, references)
    current = backend.status(run_id)
    if current.get("pending") != pending or current["status"] != state["status"]:
        raise ValueError("task_plan_changed_during_verification")
    if (session / "closing.json").exists() and current["status"] != "cancel_requested":
        result.update(verdict="uncertain", judged_by="runtime", reason="session_closing")
    artifact = session / "task-plan-verifications" / (request_id + ".json")
    _save_once(artifact, {"schema": "task_plan_verification.v1", "frame": frame, "result": result})
    references.append(_reference(session, artifact))
    return backend.record_verified_result(run_id, request_id, execution_id, result, decision_service=decision_service)


__all__ = ["verify_task_plan_step"]
