"""把已持久化的工作流观察和 API 尝试投影为局部计量事件。"""

from pathlib import Path
from collections import defaultdict
from hashlib import sha256
import json

from app.core.json_snapshot import read_json_snapshot
from .measurement import _run_id, load_events, record_event, summarize_run
from .workflow_program import _id


_COVERAGE = {"planning": "unobserved", "grounding": "partial",
             "verification": "partial", "overall": "partial"}


def _identity(value, label):
    try:
        return _id(value, label)
    except (TypeError, ValueError) as error:
        raise ValueError(f"workflow_metrics_{label}_invalid") from error


def _interval(value):
    if not isinstance(value, dict) or set(value) != {"started_ns", "ended_ns"}:
        raise ValueError("workflow_metrics_interval_invalid")
    start, end = value["started_ns"], value["ended_ns"]
    if type(start) is not int or type(end) is not int or start < 0 or end < start:
        raise ValueError("workflow_metrics_interval_invalid")
    return start, end


def _evidence_ref(value, expected):
    # 仅接收本次请求的固定会话相对路径，不将外部路径写入计量账本。
    if not isinstance(value, str) or value.replace("\\", "/") != expected:
        raise ValueError("workflow_metrics_evidence_ref_invalid")
    return expected


def record_rule_observation(session_dir: Path, envelope: dict, verdict: str) -> None:
    """记录一次有真实读取时钟的原生验证；旧观察不补造时长。"""
    if not isinstance(envelope, dict):
        raise ValueError("workflow_metrics_envelope_invalid")
    if "measurement" not in envelope:
        return
    if not isinstance(verdict, str) or verdict not in {"success", "failure", "uncertain"}:
        raise ValueError("workflow_metrics_verdict_invalid")
    start, end = _interval(envelope["measurement"])
    receipt, observation = envelope.get("receipt"), envelope.get("observation")
    if not isinstance(receipt, dict) or not isinstance(observation, dict):
        raise ValueError("workflow_metrics_evidence_invalid")
    run_id = _identity(receipt.get("run_id"), "run_id")
    step_id = _identity(receipt.get("step_id"), "step_id")
    request_id = _identity(receipt.get("request_id"), "request_id")
    execution_id = _identity(receipt.get("execution_request_id"), "execution_request_id")
    refs = [
        _evidence_ref(receipt.get("evidence_ref"), f"responses/{execution_id}.json"),
        _evidence_ref(observation.get("evidence_ref"), f"workflow-observations/{request_id}.json"),
    ]
    record_event(session_dir, {"schema": "workflow_measurement.v1", "event_id": "verify-" + request_id,
        "run_id": run_id, "step_id": step_id, "request_id": request_id,
        "phase": "verification", "source": "native_observation",
        "started_ns": start, "ended_ns": end,
        "status": {"success": "success", "failure": "failure", "uncertain": "waiting"}[verdict],
        "usage": None, "evidence_refs": refs})


def record_api_attempt(session_dir: Path, *, run_id: str, step_id: str,
                       execution_request_id: str, grounding_request_id: str, attempt: dict) -> None:
    """仅记录外部 API 边界实际给出的时钟与用量。"""
    run_id = _identity(run_id, "run_id")
    step_id = _identity(step_id, "step_id")
    execution_id = _identity(execution_request_id, "execution_request_id")
    grounding_id = _identity(grounding_request_id, "grounding_request_id")
    if not isinstance(attempt, dict) or set(attempt) != {"started_ns", "ended_ns", "status", "usage"}:
        raise ValueError("workflow_metrics_api_attempt_invalid")
    start, end = _interval({"started_ns": attempt["started_ns"], "ended_ns": attempt["ended_ns"]})
    if not isinstance(attempt["status"], str) or attempt["status"] not in {"success", "failure", "timeout"}:
        raise ValueError("workflow_metrics_api_status_invalid")
    record_event(session_dir, {"schema": "workflow_measurement.v1", "event_id": "api-" + grounding_id,
        "run_id": run_id, "step_id": step_id, "request_id": grounding_id,
        "phase": "grounding", "source": "external_api",
        "started_ns": start, "ended_ns": end, "status": attempt["status"],
        "usage": attempt["usage"], "evidence_refs": [f"agent-commands/{execution_id}.json"]})


def record_agent_handoff(session_dir: Path, *, run_id: str, step_id: str,
                         execution_request_id: str, handoff: dict) -> None:
    """已结束的 Agent 交接只记等待，实际调用与用量仍由调用方提供。"""
    run_id = _identity(run_id, "run_id")
    step_id = _identity(step_id, "step_id")
    execution_id = _identity(execution_request_id, "execution_request_id")
    if (not isinstance(handoff, dict)
            or set(handoff) != {"request_id", "capture_id", "source", "wait"}
            or not isinstance(handoff["source"], str)
            or handoff["source"] not in {"agent_current", "agent_delegate"}):
        raise ValueError("workflow_metrics_agent_handoff_invalid")
    grounding_id = _identity(handoff["request_id"], "grounding_request_id")
    _identity(handoff["capture_id"], "capture_id")
    wait = handoff["wait"]
    if (not isinstance(wait, dict) or set(wait) != {"started_ns", "ended_ns", "status"}
            or not isinstance(wait["status"], str)
            or wait["status"] not in {"success", "failure", "cancelled", "timeout"}):
        raise ValueError("workflow_metrics_agent_wait_invalid")
    start, end = _interval({key: wait[key] for key in ("started_ns", "ended_ns")})
    record_event(session_dir, {"schema": "workflow_measurement.v1", "event_id": "handoff-" + grounding_id,
        "run_id": run_id, "step_id": step_id, "request_id": grounding_id,
        "phase": "wait", "source": handoff["source"], "started_ns": start, "ended_ns": end,
        "status": wait["status"], "usage": None,
        "evidence_refs": [f"agent-commands/{execution_id}.json"]})


def _receipt_file(session, folder, execution_id):
    path = session / folder / (execution_id + ".json")
    if path.resolve() != path:
        raise ValueError("workflow_metrics_receipt_path_invalid")
    return path


def _collect_recognition_metrics(session_dir, trial):
    session = Path(session_dir).resolve()
    rows = list(trial["history"])
    if trial.get("pending") is not None:
        rows.append(trial["pending"])
    for row in rows:
        execution_id = _identity(row.get("execution_request_id"), "execution_request_id")
        step_id = _identity(row.get("step_id"), "step_id")
        job_path = _receipt_file(session, "agent-commands", execution_id)
        if not job_path.is_file():
            continue
        job = read_json_snapshot(job_path)
        if (not isinstance(job, dict) or job.get("contract_version") != "agent_command.v1"
                or job.get("command_id") != execution_id):
            raise ValueError("workflow_metrics_async_identity_mismatch")
        calls = job.get("recognition_calls", [])
        if not isinstance(calls, list) or any(not isinstance(call, dict) for call in calls):
            raise ValueError("workflow_metrics_recognition_calls_invalid")
        calls = [call for call in calls if call.get("source") == "external_api" and call.get("attempt") is not None]
        handoffs = job.get("recognition_handoffs", [])
        if not isinstance(handoffs, list):
            raise ValueError("workflow_metrics_agent_handoffs_invalid")
        if not calls and not handoffs:
            continue
        command = read_json_snapshot(_receipt_file(session, "commands", execution_id))
        receipt = read_json_snapshot(_receipt_file(session, "responses", execution_id))
        initial = receipt.get("result") if isinstance(receipt, dict) else None
        if (not isinstance(command, dict) or not isinstance(initial, dict)
                or receipt.get("command") != command or initial.get("contract_version") != "agent_command.v1"
                or initial.get("command_id") != execution_id
                or "suggested_command" in row and row["suggested_command"] != command):
            raise ValueError("workflow_metrics_original_receipt_mismatch")
        for call in calls:
            record_api_attempt(session, run_id=trial["run_id"], step_id=step_id,
                execution_request_id=execution_id, grounding_request_id=call.get("request_id"),
                attempt=call["attempt"])
        for handoff in handoffs:
            record_agent_handoff(session, run_id=trial["run_id"], step_id=step_id,
                execution_request_id=execution_id, handoff=handoff)


def _collect_verification_waits(session_dir, trial):
    session = Path(session_dir).resolve()
    run_id = trial["run_id"]
    path = _receipt_file(session, "workflow-runners", run_id)
    counts = {"measured": 0, "unmeasured": 0, "pending": 0}
    if not path.is_file():
        return counts
    state = read_json_snapshot(path)
    if (not isinstance(state, dict) or state.get("schema") != "workflow_runner.v1"
            or state.get("run_id") != run_id):
        raise ValueError("workflow_metrics_runner_identity_invalid")
    closed = state.get("verification_waits", [])
    pending = state.get("verification_wait")
    if not isinstance(closed, list) or pending is not None and not isinstance(pending, dict):
        raise ValueError("workflow_metrics_verification_waits_invalid")
    rows = list(trial["history"])
    if trial.get("pending") is not None:
        rows.append(trial["pending"])
    seen, events = set(), []
    for wait, is_pending in [(item, False) for item in closed] + ([(pending, True)] if pending is not None else []):
        if not isinstance(wait, dict):
            raise ValueError("workflow_metrics_verification_wait_invalid")
        execution_id = _identity(wait.get("execution_request_id"), "execution_request_id")
        step_id = _identity(wait.get("step_id"), "step_id")
        matches = [row for row in rows if isinstance(row, dict)
                   and row.get("execution_request_id") == execution_id and row.get("step_id") == step_id]
        if len(matches) != 1 or execution_id in seen:
            raise ValueError("workflow_metrics_verification_ticket_mismatch")
        seen.add(execution_id)
        row = matches[0]
        command = read_json_snapshot(_receipt_file(session, "commands", execution_id))
        receipt_path = _receipt_file(session, "responses", execution_id)
        receipt = read_json_snapshot(receipt_path)
        digest = sha256(json.dumps(command, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if (not isinstance(command, dict) or digest != wait.get("command_sha256")
                or not isinstance(receipt, dict) or receipt.get("command") != command
                or "suggested_command" in row and row["suggested_command"] != command
                or "receipt_sha256" in row and row["receipt_sha256"] != sha256(receipt_path.read_bytes()).hexdigest()):
            raise ValueError("workflow_metrics_verification_receipt_mismatch")
        if (not isinstance(wait.get("clock_id"), str) or not wait["clock_id"]
                or type(wait.get("started_ns")) is not int or wait["started_ns"] < 0):
            raise ValueError("workflow_metrics_verification_clock_invalid")
        if is_pending:
            counts["pending"] += 1
            continue
        if (not isinstance(wait.get("status"), str)
                or wait["status"] not in {"success", "failure", "waiting", "cancelled"}):
            raise ValueError("workflow_metrics_verification_status_invalid")
        if wait.get("measurement") is None:
            if wait.get("unmeasured_reason") != "clock_changed":
                raise ValueError("workflow_metrics_verification_unmeasured_invalid")
            counts["unmeasured"] += 1
            continue
        start, end = _interval(wait["measurement"])
        if start != wait["started_ns"] or "unmeasured_reason" in wait:
            raise ValueError("workflow_metrics_verification_clock_invalid")
        events.append({"schema": "workflow_measurement.v1", "event_id": "review-wait-" + execution_id,
            "run_id": run_id, "step_id": step_id, "request_id": execution_id,
            "phase": "wait", "source": "workflow_verification_wait", "started_ns": start, "ended_ns": end,
            "status": wait["status"], "usage": None,
            "evidence_refs": [f"workflow-runners/{run_id}.json", f"responses/{execution_id}.json"]})
        counts["measured"] += 1
    for event in events:
        record_event(session, event)
    return counts


def load_run_metrics(session_dir: Path, run_id: str, *, trial: dict | None = None) -> dict:
    """日志不可读时保留执行状态，且不把未知指标改记为零。"""
    _run_id(run_id)
    if trial is not None and (not isinstance(trial, dict) or trial.get("run_id") != run_id
                              or not isinstance(trial.get("history"), list)):
        raise ValueError("workflow_metrics_trial_identity_invalid")
    result = {"coverage": dict(_COVERAGE), "total_model_calls": None, "total_usage": None}
    if trial is not None:
        try:
            # 从原票据和历史取证，人工先审核完成也不能漏记实际 API 尝试。
            _collect_recognition_metrics(session_dir, trial)
            result["verification_waits"] = _collect_verification_waits(session_dir, trial)
        except (ValueError, OSError) as error:
            return {**result, "status": "unavailable", "observed": None,
                    "error": {"code": "measurement_source_unavailable", "type": type(error).__name__}}
    try:
        events = load_events(session_dir, run_id)
        observed = summarize_run(events)
        grouped = defaultdict(list)
        for event in events:
            grouped[event["step_id"]].append(event)
        by_step = {step_id: summarize_run(rows) for step_id, rows in grouped.items()}
    except ValueError as error:
        return {**result, "status": "unavailable", "observed": None,
                "error": {"code": "measurement_log_invalid", "type": type(error).__name__}}
    except OSError as error:
        return {**result, "status": "unavailable", "observed": None,
                "error": {"code": "measurement_log_io_error", "type": type(error).__name__}}
    from .caller_model_calls import load_call_summary
    reported = load_call_summary(session_dir, {"kind": "workflow", "run_id": run_id})
    if reported is not None:
        result["caller_reported"] = reported
    return {**result, "observed": observed, "by_step": by_step}


__all__ = ["record_rule_observation", "record_api_attempt", "record_agent_handoff", "load_run_metrics"]
