"""离线核对临时计划、原回执和夹具真值；不启动宿主、不调用模型、不读取密钥。"""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.execution.timeline import summarize_execution_timeline

_ID = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_EVIDENCE_DIRS = frozenset({"commands", "responses", "agent-commands", "captures", "runtime-output",
    "task-plan-decisions", "task-plan-verifications", "task-plan-reviews"})
_BINDING = ("source_kind", "run_id", "start_request_id", "plan_id", "plan_sha256", "owner_id",
    "target_identity", "session_directory")


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _json(raw):
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object,
        parse_float=_finite_float,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite_json")
    return number


def _dict(value):
    return value if type(value) is dict else {}


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _duration(start, end):
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if first.tzinfo is None or last.tzinfo is None:
            return None
        elapsed = (last - first).total_seconds() * 1000
        return elapsed if elapsed >= 0 else None
    except (TypeError, ValueError):
        return None


class _Reader:
    def __init__(self, root, report_path):
        self.root = root
        self.report_path = report_path
        self.inputs = {}

    def allowed(self, path):
        if not path.is_relative_to(self.root):
            return False
        if path == self.report_path:
            return True
        relative = path.relative_to(self.root).as_posix()
        if relative in {"client/calls.jsonl", "fixture/manifest.json", "fixture/closed.json",
                "fixture/oracle/records.json", "fixture/oracle/actions.jsonl"}:
            return True
        parts = path.relative_to(self.root).parts
        if len(parts) < 3 or parts[0] != "runtime" or not parts[1].startswith("session-"):
            return False
        if len(parts) == 3 and parts[2] == "report.json":
            return True
        return len(parts) >= 4 and parts[2] in _EVIDENCE_DIRS | {"task-plans", "task-plan-runners"}

    def bytes(self, path, errors, label):
        path = path.resolve()
        if not self.allowed(path):
            errors.append("evidence_reference_outside_scope")
            return None
        try:
            if path.stat().st_size > 32 * 1024 * 1024:
                errors.append(label + "_too_large")
                return None
            raw = path.read_bytes()
        except OSError:
            errors.append(label + "_missing")
            return None
        self.inputs[path.relative_to(self.root).as_posix()] = sha256(raw).hexdigest()
        return raw

    def object(self, path, errors, label):
        raw = self.bytes(path, errors, label)
        if raw is None:
            return {}
        try:
            value = _json(raw)
            if type(value) is not dict:
                raise ValueError("object_required")
            return value
        except (ValueError, UnicodeError):
            errors.append(label + "_invalid")
            return {}

    def lines(self, path, errors, label):
        raw = self.bytes(path, errors, label)
        if raw is None:
            return None
        try:
            values = [_json(line) for line in raw.splitlines() if line.strip()]
            if any(type(item) is not dict for item in values):
                raise ValueError("object_required")
            return values
        except (ValueError, UnicodeError):
            errors.append(label + "_invalid")
            return None


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _evidence(reader, session, references, errors):
    seen = set()
    if type(references) is not list or not references:
        errors.append("original_evidence_missing")
        return seen
    for item in references:
        item = _dict(item)
        name, digest = item.get("path"), item.get("sha256")
        if type(name) is not str or not name or type(digest) is not str or not _HASH.fullmatch(digest):
            errors.append("evidence_reference_invalid")
            continue
        relative = Path(name)
        path = (session / relative).resolve()
        if (relative.is_absolute() or PureWindowsPath(name).is_absolute() or ".." in relative.parts
                or not path.is_relative_to(session) or not relative.parts
                or relative.parts[0] not in _EVIDENCE_DIRS):
            errors.append("evidence_reference_outside_scope")
            continue
        if path in seen:
            errors.append("evidence_reference_duplicate")
            continue
        seen.add(path)
        raw = reader.bytes(path, errors, "original_evidence")
        if raw is not None and sha256(raw).hexdigest() != digest:
            errors.append("evidence_hash_changed")
    return seen


def _action_executed(result, terminal):
    claims = [item["action_executed"] for item in (result, terminal)
        if type(item.get("action_executed")) is bool]
    data = _dict(_dict(result.get("response")).get("data"))
    action = _dict(data.get("result", data))
    value = _dict(action.get("execution_path")).get("action_executed", action.get("action_executed"))
    if type(value) is bool:
        claims.append(value)
    return claims[0] if claims and all(item is claims[0] for item in claims) else None


def _timing_projection(value):
    value = _dict(value)
    rows = value.get("steps") if type(value.get("steps")) is list else []
    return {"contract_version": value.get("contract_version"), "total_ms": _number(value.get("total_ms")),
        "scope": value.get("scope"), "inclusive": value.get("inclusive"), "nested_timings_additive": False,
        "steps": [{"name": row.get("name"), "elapsed_ms": _number(row.get("elapsed_ms")),
            "inclusive": row.get("inclusive"), "includes": row.get("includes"),
            "queue_wait_ms": _number(row.get("queue_wait_ms"))} for row in rows if type(row) is dict]}


def _runtime(reader, session, report):
    errors, commands, starts = [], {}, []
    for path in sorted((session / "commands").glob("*.json")):
        if not _id(path.stem):
            errors.append("command_id_invalid")
            continue
        command = reader.object(path, errors, "command")
        commands[path.stem] = command
        if command.get("kind") == "task_plan" and _dict(command.get("request")).get("action") == "start":
            starts.append(path.stem)
    start_id = starts[0] if len(starts) == 1 else None
    if start_id is None:
        errors.append("unique_original_start_missing")
    start = reader.object(session / "responses" / (start_id + ".json"), errors, "start_receipt") if start_id else {}
    initial = _dict(start.get("result"))
    run_id, plan_id = initial.get("run_id"), initial.get("plan_id")
    if not _id(run_id) or not _id(plan_id):
        errors.append("original_run_binding_missing")
        run_id = plan_id = None
    state = reader.object(session / "task-plans" / (run_id + ".json"), errors, "trial") if run_id else {}
    source = reader.object(session / "task-plans" / (plan_id + ".json"), errors, "source") if plan_id else {}
    runner = reader.object(session / "task-plan-runners" / (run_id + ".json"), errors, "runner") if run_id else {}
    host = reader.object(session / "report.json", errors, "host_report")
    plan = _dict(source.get("plan"))
    if ("request_id" in start and start["request_id"] != start_id or start.get("status") != "returned"
            or start.get("command") != commands.get(start_id)
            or _dict(commands.get(start_id, {}).get("request")).get("plan") != plan
            or report.get("plan") != plan):
        errors.append("original_start_command_mismatch")
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if (source.get("schema_version") != "task_plan_source.v1" or source.get("source_kind") != "caller_plan"
            or source.get("plan_id") != plan_id or source.get("plan_sha256") != sha256(canonical).hexdigest()):
        errors.append("pinned_plan_hash_mismatch")
    expected = {**{key: source.get(key) for key in _BINDING}, "run_id": run_id, "start_request_id": start_id}
    if (not expected.get("owner_id") or not expected.get("target_identity")
            or Path(str(expected.get("session_directory", ""))).resolve() != session):
        errors.append("original_scope_binding_missing")
    for name, value in (("start", initial), ("trial", state)):
        if (value.get("schema") != "task_plan_trial.v1"
                or any(value.get(key) != expected[key] for key in _BINDING)):
            errors.append(name + "_binding_mismatch")
    if (runner.get("schema") != "workflow_runner.v1" or runner.get("source_kind") != "caller_plan"
            or runner.get("run_id") != run_id or runner.get("start_request_id") != start_id):
        errors.append("runner_binding_mismatch")
    projection = _dict(host.get("task_plan_run"))
    if projection and any(projection.get(key) != expected[key] for key in _BINDING):
        errors.append("host_projection_binding_mismatch")
    client = _dict(report.get("result"))
    client_snapshot = _dict(client.get("result"))
    public_binding = _BINDING[:5]
    if client and (client.get("original_request_id") != start_id or not client_snapshot
            or any(client_snapshot.get(key) != expected[key] for key in public_binding)
            or any(key in client_snapshot and client_snapshot[key] != expected[key] for key in _BINDING[5:])):
        errors.append("client_projection_binding_mismatch")
    steps, history = plan.get("steps"), state.get("history")
    if type(steps) is not list or type(history) is not list or type(initial.get("history")) is not list:
        errors.append("history_shape_or_prefix_mismatch")
    steps = steps if type(steps) is list else []
    history = history if type(history) is list else []
    initial_history = initial.get("history") if type(initial.get("history")) is list else []
    if (not steps or len(history) > len(steps) or history[:len(initial_history)] != initial_history):
        errors.append("history_shape_or_prefix_mismatch")
    execution_bindings, receipt_times = {}, []
    for index, row in enumerate(history):
        row = _dict(row)
        execution = row.get("execution_request_id")
        step = _dict(steps[index]) if index < len(steps) else {}
        if (row.get("step_id") != step.get("step_id") or not _id(execution)
                or execution in execution_bindings):
            errors.append("original_step_binding_mismatch")
            continue
        execution_bindings[execution] = row.get("step_id")
        paths = _evidence(reader, session, row.get("evidence_refs"), errors)
        command_path, receipt_path = session / "commands" / (execution + ".json"), session / "responses" / (execution + ".json")
        if command_path.resolve() not in paths or receipt_path.resolve() not in paths:
            errors.append("original_command_or_receipt_reference_missing")
        command = commands.get(execution, {})
        raw = reader.object(receipt_path, errors, "original_receipt")
        if "request_id" in raw and raw["request_id"] != execution or raw.get("command") != command or not command:
            errors.append("original_receipt_binding_mismatch")
        if _dict(command.get("request")).get("goal") != _dict(step.get("action")).get("goal"):
            errors.append("original_action_goal_mismatch")
        if command.get("kind") != "step" or command.get("operation") != "execute_recognition_plan":
            errors.append("original_action_operation_unsupported")
        result, terminal = _dict(raw.get("result")), {}
        effective_status = raw.get("status")
        if result.get("contract_version") == "agent_command.v1":
            terminal_path = session / "agent-commands" / (execution + ".json")
            terminal = reader.object(terminal_path, errors, "original_terminal_receipt")
            if (result.get("command_id") != execution or terminal.get("command_id") != execution
                    or terminal.get("contract_version") != "agent_command.v1" or terminal_path.resolve() not in paths):
                errors.append("original_terminal_binding_mismatch")
            effective_status = "returned" if terminal.get("status") == "completed" else "failed"
            result = _dict(terminal.get("result"))
        executed = _action_executed(result, terminal)
        identity = _dict(result.get("target_identity"))
        if identity:
            identity = {"handle": identity.get("target_window_handle", identity.get("handle")),
                "process_id": identity.get("process_id"), "process_create_time": identity.get("process_create_time")}
        else:
            observation = _dict(_dict(terminal.get("observation")).get("capture")) if terminal else _dict(raw.get("observation"))
            identity = _dict(observation.get("window_identity"))
        if row.get("verdict") == "success" and identity != expected["target_identity"]:
            errors.append("original_input_target_binding_unproven")
        if (row.get("verdict") == "success" and (effective_status != "returned"
                or result.get("status") in {"pending", "running", "result_unknown", "failed", "cancelled"}
                or result.get("phase") in {"failed", "rejected", "result_unknown"}
                or result.get("phase") != "returned" and result.get("status") != "completed"
                or _dict(result.get("response")).get("success") is not True
                or executed is not True or row.get("action_executed") is not True
                or row.get("original_input_status") != "completed")):
            errors.append("original_input_completion_unproven")
        receipt_times.append({"execution_request_id": execution,
            "outer_receipt_wall_ms": _duration(raw.get("started_at"), raw.get("finished_at")),
            "reported_command_wall_ms": _number(raw.get("command_wall_ms")),
            "outer_receipt_is_async_admission": bool(terminal),
            "local_step_timings": _timing_projection(result.get("local_step_timings")),
            "invocation_timings": _timing_projection(result.get("invocation_timings"))})
    pending = _dict(state.get("pending"))
    if _id(pending.get("execution_request_id")):
        execution_bindings[pending["execution_request_id"]] = pending.get("step_id", state.get("current_step_id"))
    completed = (state.get("status") == "completed" and runner.get("runner_state") == "completed"
        and len(history) == len(steps) and bool(steps) and all(_dict(row).get("verdict") == "success" for row in history)
        and type(runner.get("steps_completed")) is int and runner["steps_completed"] == len(steps)
        and state.get("pending") is None and state.get("current_step_id") is None
        and runner.get("ticket") is None and runner.get("wait") is None)
    if (state.get("status") == "completed" or runner.get("runner_state") == "completed") and not completed:
        errors.append("completed_runner_inconsistent")
    public = {"original_request_id": start_id, "run_id": run_id, "plan_id": plan_id,
        "pinned_plan_sha256": source.get("plan_sha256"), "trial_status": state.get("status"),
        "runner_state": runner.get("runner_state"), "settled_steps": len(history), "planned_steps": len(steps),
        "runner_completed": completed if not errors else None, "errors": sorted(set(errors))}
    return public, {"plan": plan, "state": state, "host": host, "commands": commands,
        "start_id": start_id, "run_id": run_id, "bindings": execution_bindings, "receipt_times": receipt_times}


def _oracle(reader, root, runtime, report):
    errors = []
    manifest = reader.object(root / "fixture" / "manifest.json", errors, "fixture_manifest")
    identity = _dict(runtime["state"].get("target_identity"))
    if manifest.get("pid") != identity.get("process_id") or manifest.get("window_handle") != identity.get("handle"):
        errors.append("fixture_target_binding_mismatch")
    records = reader.object(root / "fixture" / "oracle" / "records.json", errors, "fixture_records")
    actions = reader.lines(root / "fixture" / "oracle" / "actions.jsonl", errors, "fixture_actions")
    rows = records.get("records")
    if records.get("schema") != "learning_fixture_oracle.v1" or type(rows) is not list:
        errors.append("fixture_records_schema_invalid")
        rows = []
    expected = []
    for step in runtime["plan"].get("steps", []):
        condition = _dict(_dict(step).get("verification")).get("decision_condition")
        matches = [row for row in rows if type(row) is dict and type(row.get("id")) is str
            and type(row.get("detail")) is str and condition ==
            f"The current record detail area visibly shows exactly ID: {row['id']} | Detail: {row['detail']}."
            and _dict(_dict(step).get("action")).get("kind") == "click"]
        if len(matches) != 1:
            errors.append("fixture_condition_unsupported_or_ambiguous")
        else:
            expected.append({"record_id": matches[0]["id"], "actual_detail": f"ID: {matches[0]['id']} | Detail: {matches[0]['detail']}"})
    opens = []
    if actions is not None:
        for index, row in enumerate(actions):
            if row.get("schema") != "learning_fixture_action.v1" or row.get("event_index") != index + 1:
                errors.append("fixture_event_order_invalid")
            if (_duration(report.get("started_at"), row.get("at")) is None
                    or _duration(row.get("at"), report.get("ended_at")) is None):
                errors.append("fixture_event_time_unbound")
            if row.get("action") == "open_detail":
                opens.append({key: row.get(key) for key in ("record_id", "actual_detail")})
            elif row.get("action") != "fixture_closed":
                errors.append("fixture_action_unsupported")
    correct = opens == expected if expected and actions is not None and not errors else None
    return {"exact_order_and_detail_correct": correct, "expected_order": [row["record_id"] for row in expected],
        "actual_order": [row["record_id"] for row in opens], "opened_detail_count": len(opens),
        "truth_source": "fixture/oracle/records.json+actions.jsonl+pinned_plan", "errors": sorted(set(errors))}


def _orchestration(reader, root, report, runtime):
    errors = []
    calls = reader.lines(root / "client" / "calls.jsonl", errors, "client_journal")
    calls = calls or []
    starts = [index for index, call in enumerate(calls)
        if call.get("tool") == "instant_run" and call.get("request_id") == runtime["start_id"]]
    if len(starts) != 1:
        errors.append("journal_start_count_not_one")
    segment = calls[starts[0] + 1:] if starts else []
    end = next((index for index, call in enumerate(segment) if call.get("tool") == "instant_stop"), len(segment))
    segment = segment[:end]
    polls = 0
    for call in segment:
        tool, request = call.get("tool"), call.get("request_id")
        if tool == "instant_status" and request is None:
            polls += 1
        elif tool == "instant_result" and request == runtime["start_id"]:
            polls += 1
        else:
            errors.append("journal_intermediate_control_or_unbound_call")
    events = report.get("events")
    callback_count = len(events) if type(events) is list else None
    if callback_count is None:
        errors.append("callback_record_missing")
    elif callback_count:
        errors.append("recorded_handoff_callback")
    return {"client_adapter_pattern_supported": not errors, "original_start_submissions": len(starts),
        "readonly_polls": polls, "recorded_callbacks": callback_count, "intermediate_main_calls": None,
        "main_activity_status": "unknown_no_independent_main_trace",
        "scope": "recorded_client_journal_and_report_callbacks_only", "errors": sorted(set(errors))}, calls


def _cleanup(reader, root, host):
    errors = []
    manifest = reader.object(root / "fixture" / "manifest.json", errors, "fixture_manifest")
    closed = reader.object(root / "fixture" / "closed.json", errors, "fixture_closed")
    fixture = None
    if manifest and closed:
        if closed.get("pid") != manifest.get("pid"):
            errors.append("fixture_cleanup_pid_mismatch")
        elif closed.get("status") == "closed" and closed.get("exit_code") == 0:
            fixture = True
        elif closed.get("exit_code") is not None:
            fixture = False
    host_complete = None
    if type(host.get("cleanup_errors")) is list and host["cleanup_errors"]:
        host_complete = False
    elif (host.get("phase") == "stopped" and host.get("host_phase") == "stopped"
            and host.get("sampler_stopped") is True and host.get("cleanup_errors") == []
            and host.get("finished_at")):
        host_complete = True
    complete = False if fixture is False or host_complete is False else True if fixture is True and host_complete is True else None
    return {"complete": complete, "host_persisted_cleanup_complete": host_complete,
        "fixture_persisted_cleanup_complete": fixture, "current_process_liveness": "unknown_offline",
        "errors": sorted(set(errors))}


def _decision(reader, session, runtime):
    errors, ledger = [], {}
    declared_path = session / "judgments" / "decisions.sqlite3"
    db_path = declared_path.resolve()
    ledger_available, metadata_digest = False, None
    if db_path.is_file() and db_path == declared_path and db_path.is_relative_to(session):
        try:
            with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
                db.execute("PRAGMA query_only=ON")
                rows = db.execute("SELECT request_id, request_sha256, scope, dispatched, result_blob IS NOT NULL FROM dispatches").fetchall()
            if any(not _id(request) or type(digest) is not str or not _HASH.fullmatch(digest)
                    or type(scope) is not str or type(dispatched) is not int or dispatched not in {0, 1}
                    or has_result not in {0, 1} for request, digest, scope, dispatched, has_result in rows):
                errors.append("decision_ledger_rows_invalid")
            else:
                metadata_digest = sha256(json.dumps(sorted(rows), separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
                for request_id, digest, scope, dispatched, has_result in rows:
                    if scope == "execution":
                        ledger[request_id] = {"sha256": digest, "dispatched": dispatched, "has_result": bool(has_result)}
                ledger_available = True
        except sqlite3.Error:
            errors.append("decision_ledger_invalid")
    elif db_path.is_file():
        errors.append("evidence_reference_outside_scope")
    else:
        errors.append("decision_ledger_missing")
    originals, measurements = {}, {}
    for path in sorted((session / "task-plan-decisions").glob("*.json")):
        artifact = reader.object(path, errors, "decision_artifact")
        binding, result = _dict(artifact.get("binding")), _dict(artifact.get("result"))
        if binding.get("run_id") != runtime["run_id"]:
            errors.append("decision_artifact_other_or_missing_run")
            continue
        request = binding.get("request_id")
        if (not _id(request) or result.get("request_id") != request
                or binding.get("execution_request_id") not in runtime["bindings"]
                or runtime["bindings"].get(binding.get("execution_request_id")) != binding.get("step_id")
                or any(result.get(key) != binding.get(key) for key in ("run_id", "step_id", "execution_request_id"))
                or request not in ledger or ledger[request]["sha256"] != result.get("request_sha256")):
            errors.append("decision_original_binding_mismatch")
            continue
        if request in originals and originals[request] != result:
            errors.append("decision_original_result_conflict")
            originals[request] = {}
        else:
            originals[request] = result
            measurement = _dict(artifact.get("measurement"))
            if request in measurements and measurements[request] != measurement:
                errors.append("decision_original_measurement_conflict")
                measurements[request] = {}
            else:
                measurements[request] = measurement
    responses = [result for request, result in originals.items() if result.get("source") == "openai_decisions"
        and result.get("status") in {"completed", "refused"} and type(result.get("provider_request_id")) is str
        and result["provider_request_id"] and ledger[request]["dispatched"] == 1 and ledger[request]["has_result"]]
    if len({item["provider_request_id"] for item in responses}) != len(responses):
        errors.append("decision_provider_response_identity_reused")
        responses = []
    markers = sum(item["dispatched"] == 1 for item in ledger.values()) if ledger_available else None
    unresolved = markers - len(responses) if markers is not None else None
    usage = None
    if responses and not unresolved and not errors:
        usages = [_dict(item.get("usage")) for item in responses]
        keys = ("input_tokens", "output_tokens", "total_tokens")
        if all(all(type(item.get(key)) is int and item[key] >= 0 for key in keys)
                and item["total_tokens"] == item["input_tokens"] + item["output_tokens"] for item in usages):
            usage = {key: sum(item[key] for item in usages) for key in keys}
    spans, latencies = [], []
    for request, result in sorted(originals.items()):
        measurement = measurements.get(request, {})
        latencies.append({"request_id": request, "execution_request_id": result.get("execution_request_id"),
            **{key: _number(result.get(key)) for key in ("elapsed_ms", "http_elapsed_ms", "server_processing_ms")},
            "measurement_wall_ms": (measurement["ended_ns"] - measurement["started_ns"]) / 1_000_000
                if type(measurement.get("started_ns")) is int and type(measurement.get("ended_ns")) is int
                and 0 <= measurement["started_ns"] <= measurement["ended_ns"] < 2 ** 63 else None})
        spans.append({"kind": "span", "layer": "decision", "clock_id": "host-monotonic",
            **{key: measurement[key] for key in ("started_ns", "ended_ns") if key in measurement}})
    timeline = summarize_execution_timeline(spans)
    return {"ledger_status": "readonly_metadata_available" if ledger_available else "unknown",
        "ledger_metadata_sha256": metadata_digest,
        "ledger_scope": "whole_session_execution", "session_dispatch_markers": markers,
        "bound_original_results": len(originals), "confirmed_provider_responses": len(responses),
        "unresolved_session_dispatch_markers": unresolved, "actual_paid_post_count": None,
        "paid_post_count_status": "unknown_dispatch_precedes_provider_call_and_no_billing_ledger",
        "confirmed_provider_response_lower_bound": len(responses), "token_usage": usage,
        "token_usage_status": "complete_bound_raw_usage" if usage else "unknown_or_incomplete",
        "main_model_tokens": None, "main_model_tokens_status": "unknown_no_main_usage_trace",
        "latencies": latencies, "measured_span_union_ms": timeline["measured_span_union_ms"],
        "measurement_clock": "single_host_monotonic", "nested_timings_additive": False,
        "encrypted_payloads_read": False, "errors": sorted(set(errors))}


def _source_freeze(report, source_root):
    manifest = _dict(report.get("source_sha256"))
    errors, mismatches, checked = [], [], 0
    matches = None
    if source_root is not None and manifest:
        source_root = Path(source_root).resolve()
        for name, digest in manifest.items():
            relative = PureWindowsPath(name)
            path = source_root.joinpath(*relative.parts).resolve()
            if (relative.is_absolute() or ".." in relative.parts or not relative.parts
                    or relative.parts[0] not in {"app", "scripts"} or relative.suffix != ".py"
                    or not path.is_relative_to(source_root) or path.relative_to(source_root).parts[0] not in {"app", "scripts"}):
                errors.append("source_reference_outside_scope")
                continue
            if type(digest) is not str or not _HASH.fullmatch(digest):
                errors.append("source_manifest_hash_invalid")
                continue
            try:
                actual = sha256(path.read_bytes()).hexdigest()
                checked += 1
                if actual != digest:
                    mismatches.append(relative.as_posix())
            except OSError:
                errors.append("source_file_missing")
        matches = not errors and not mismatches and checked == len(manifest)
    return {"manifest_file_count": len(manifest), "checked_source_files": checked,
        "manifest_sha256": sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest() if manifest else None,
        "current_source_matches_manifest": matches, "current_source_check_scope": "explicit_source_root_app_scripts_python_only",
        "during_run_unchanged": report.get("source_unchanged_during_run")
            if type(report.get("source_unchanged_during_run")) is bool else None,
        "during_run_unchanged_status": "reported_by_acceptance_driver",
        "mismatched_source_files": mismatches, "errors": sorted(set(errors))}


def score_execution_report(report_path: Path, *, source_root: Path | None = None) -> dict:
    """只读当前目录的维护证据；未知用 null 表示，不认可汇总报告的成功或零介入旗标。"""
    report_path = Path(report_path).resolve()
    root, errors = report_path.parent, []
    reader = _Reader(root, report_path)
    report = reader.object(report_path, errors, "acceptance_report")
    session = Path(str(report.get("session_directory", ""))).resolve()
    if (not session.is_relative_to(root / "runtime") or session.parent != root / "runtime"
            or not session.name.startswith("session-") or not session.is_dir()):
        errors.append("session_outside_acceptance_root_or_missing")
        runtime = {"runner_completed": None, "errors": list(errors)}
        context = {"plan": {}, "state": {}, "host": {}, "commands": {}, "start_id": None,
            "run_id": None, "bindings": {}, "receipt_times": []}
    else:
        runtime, context = _runtime(reader, session, report)
    oracle = _oracle(reader, root, context, report)
    orchestration, calls = _orchestration(reader, root, report, context)
    cleanup = _cleanup(reader, root, context["host"])
    decision = _decision(reader, session, context) if not errors else {"actual_paid_post_count": None,
        "token_usage": None, "main_model_tokens": None, "errors": ["session_unavailable"]}
    success = None
    outcome = "incomplete_or_unknown"
    if runtime.get("runner_completed") is True and oracle["exact_order_and_detail_correct"] is not None:
        success = oracle["exact_order_and_detail_correct"]
        outcome = "verified_success" if success else "false_success"
    elif not runtime.get("errors") and context["state"].get("status") in {"failed", "cancelled"}:
        success = False
        outcome = "cancelled" if context["state"]["status"] == "cancelled" else "refused_or_failed"
    complete = False if success is False or cleanup["complete"] is False else True if success is True and cleanup["complete"] is True else None
    events = report.get("timeline_events")
    timeline = summarize_execution_timeline(events if type(events) is list else [])
    journal_times = [_number(item.get("elapsed_ms")) for item in calls]
    return {"schema": "execution_plan_benchmark.v1", "mode": "readonly_offline",
        "report_path": str(report_path), "outcome": outcome, "task_success": success,
        "complete_with_cleanup": complete, "runtime": runtime, "oracle": oracle,
        "source_freeze": _source_freeze(report, source_root),
        "orchestration": orchestration, "cleanup": cleanup, "decision": decision,
        "timing": {"acceptance_wall_ms": _duration(report.get("started_at"), report.get("ended_at")),
            "reported_plan_wall_ms": _number(report.get("plan_wall_ms")),
            "plan_wall_source": "runner_report_only_no_independent_start_end_clock",
            "original_receipts": context["receipt_times"], "timeline": timeline,
            "timeline_source": "reported_timeline_events" if type(events) is list else "unknown_missing_events",
            "nested_timings_additive": False, "client_journal_elapsed_sum_ms":
                sum(journal_times) if calls and all(item is not None for item in journal_times) else None,
            "client_journal_elapsed_sum_is_action_duration": False},
        "comparison": {"status": "unknown_no_comparable_ab_baseline", "median_improvement_percent": None,
            "main_token_reduction_percent": None, "paid_cost_reduction_percent": None},
        "evidence": {"read_files_sha256": reader.inputs, "sqlite_read_columns":
            ["request_id", "request_sha256", "scope", "dispatched", "result_blob IS NOT NULL"],
            "errors": errors, "profile_or_key_files_read": False, "evidence_mutated": False},
        "limitations": ["Client journal and recorded callbacks do not prove independent Main activity.",
            "Dispatch markers precede provider calls and cannot prove paid POST or billing totals.",
            "Persisted cleanup does not establish current process liveness.",
            "Oracle supports this fixture's exact open_detail conditions only; missing evidence stays unknown.",
            "No matched A/B baseline or Main token trace is supplied."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="Acceptance root report.json")
    parser.add_argument("--source-root", type=Path, help="Optional maintained Python source root for frozen SHA comparison")
    args = parser.parse_args(argv)
    print(json.dumps(score_execution_report(args.report, source_root=args.source_root), ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
