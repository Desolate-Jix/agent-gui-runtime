"""冻结任务、沿用原 Instant 连接采集，并从原始回执复算对照。"""
from __future__ import annotations

import argparse
import asyncio
import base64
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter_ns
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.learning_memory.benchmark_manifest import (
    digest, freeze_manifest, load_manifest, verify_candidate,
)
from app.learning_memory.benchmark_scoring import compare_runs
from app.learning_memory.benchmark_provenance import inspect_program, inspect_coverage
from app.learning_memory.measurement import load_events, summarize_run
from app.learning_memory.workflow_metrics import load_run_metrics
from app.learning_memory.workflow_program import _type, _variables
from scripts.learning_benchmark_client import LearningBenchmarkClient
from scripts.learning_benchmark_fixture import RecordDeskCaseDriver, evaluate_case


_COMPARISON_SOURCES = (
    "app/learning_memory/workflow_trial.py",
    "scripts/benchmark_learning_workflow.py", "app/learning_memory/measurement.py",
    "app/learning_memory/benchmark_manifest.py", "app/learning_memory/benchmark_provenance.py",
    "app/learning_memory/workflow_program.py", "app/learning_memory/receipt_adapter.py",
    "app/learning_memory/target_recipe.py", "app/learning_memory/workflow_verification.py",
    "app/learning_memory/image_verification.py",
    "app/learning_memory/workflow_execution_strategy.py",
    "app/desktop_review/external_mapping.py", "scripts/learning_benchmark_fixture.py",
    "scripts/learning_benchmark_cases.py",
)


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        stream.write("\n")


def _terminal(receipt):
    if not isinstance(receipt, dict) or receipt.get("status") in {None, "pending"}:
        return False
    result = receipt.get("result")
    if isinstance(result, dict) and result.get("contract_version") == "agent_command.v1":
        return result.get("status") in {"completed", "failed", "cancelled"}
    return True


def _succeeded(receipt):
    if not _terminal(receipt) or receipt.get("status") != "returned" or receipt.get("operation_succeeded") is False:
        return False
    result = receipt.get("result")
    if isinstance(result, dict):
        if result.get("contract_version") == "agent_command.v1":
            return result.get("status") == "completed"
        if result.get("status") in {"failed", "cancelled", "blocked", "pending", "running", "awaiting_grounding"}:
            return False
    return True


def _request_terminal(command, receipt):
    # 控制请求的返回与原执行命令终态分开结算，原命令仍须独立终态。
    if command.get("kind") in {"agent_command_status", "agent_command_continue", "agent_command_cancel", "grounding_status", "grounding_cancel"}:
        return isinstance(receipt, dict) and receipt.get("status") not in {None, "pending"}
    return _terminal(receipt)


def _remember(receipts, request_id, receipt):
    prior = receipts.get(request_id)
    if _terminal(prior):
        keys = ("status", "operation_succeeded", "result", "error")
        if digest({key: prior.get(key) for key in keys}) != digest({key: receipt.get(key) for key in keys}):
            raise ValueError("benchmark_terminal_receipt_changed")
    receipts[request_id] = deepcopy(receipt)


def _contains_target_memory(value):
    if isinstance(value, dict):
        return "target_memory" in value or any(_contains_target_memory(item) for item in value.values())
    return isinstance(value, list) and any(_contains_target_memory(item) for item in value)


def _route_strategy(route):
    return {"A": "ordinary", "B": "steps_only", "C": "learned"}[route]


def _route_policy(route, command):
    if route == "A" and command.get("kind") == "learning_workflow":
        raise ValueError("benchmark_route_A_workflow_forbidden")
    if route in {"A", "B"} and _contains_target_memory(command):
        raise ValueError("benchmark_route_target_memory_forbidden")


def _scoring_digest():
    from app.learning_memory import benchmark_scoring
    return hashlib.sha256(Path(benchmark_scoring.__file__).read_bytes()).hexdigest()


def _matches(receipt, rule):
    for condition in rule["all"]:
        value = receipt
        try:
            for key in condition["path"]:
                value = value[key]
        except (KeyError, IndexError, TypeError):
            return False
        if digest(value) != digest(condition["equals"]):
            return False
    return True


def _assessment(value):
    if not isinstance(value, dict) or set(value) != {"wrong_clicks", "recovery_count", "safe_rejection", "evidence"}:
        raise ValueError("benchmark_assessment_fields_invalid")
    if any(type(value[k]) is not int or value[k] < 0 for k in ("wrong_clicks", "recovery_count")):
        raise ValueError("benchmark_assessment_counts_invalid")
    if type(value["safe_rejection"]) is not bool or not isinstance(value["evidence"], dict) or not value["evidence"]:
        raise ValueError("benchmark_assessment_evidence_required")
    digest(value)
    return deepcopy(value)


def _c_binding(manifest, begin):
    if begin["route"] != "C":
        return None
    return next(case for case in manifest["cases"]
                if case["case_id"] == begin["case_id"]).get("c_workflow")


def _program_binding(manifest, begin):
    if begin["route"] not in {"B", "C"}:
        return None
    return next(case for case in manifest["cases"]
                if case["case_id"] == begin["case_id"]).get("c_workflow")


def _c_definition(binding, receipt, artifact_evidence=None):
    if not _succeeded(receipt) or not isinstance(receipt.get("result"), dict):
        raise ValueError("benchmark_c_definition_receipt_invalid")
    program = receipt["result"]
    if artifact_evidence is None:
        raw = Path(binding["artifact_path"]).read_bytes()
        artifact_evidence = {"sha256": hashlib.sha256(raw).hexdigest(), "text": raw.decode("utf-8")}
    if hashlib.sha256(artifact_evidence["text"].encode("utf-8")).hexdigest() != artifact_evidence["sha256"]:
        raise ValueError("benchmark_c_artifact_snapshot_changed")
    if digest(program) != digest(json.loads(artifact_evidence["text"].lstrip("\ufeff"))):
        raise ValueError("benchmark_c_definition_not_frozen")
    return {**inspect_program(binding, program), "artifact_evidence": deepcopy(artifact_evidence)}


def _frozen_workflow_inputs(case, definition=None):
    if definition is None:
        return deepcopy(case["inputs"])
    declarations = definition["program"]["definition"]["inputs"]
    _variables(declarations, "inputs")
    projected = {}
    for item in declarations:
        name = item["name"]
        if name not in case["inputs"]:
            if item["required"]:
                raise ValueError("benchmark_required_input_missing:" + name)
            continue
        value = case["inputs"][name]
        if not _type(value, item["type"]):
            raise ValueError("benchmark_input_type_invalid:" + name)
        projected[name] = deepcopy(value)
    return projected


def _c_trial(binding, begin, trial, case, definition):
    if (not isinstance(trial, dict) or not isinstance(trial.get("run_id"), str)
            or not trial["run_id"] or trial.get("execution_strategy") != _route_strategy(begin["route"])):
        raise ValueError("benchmark_c_trial_receipt_invalid")
    for key in ("workflow_id", "program_id", "project_snapshot_id", "start_step_id"):
        if trial.get(key) != binding[key]:
            raise ValueError("benchmark_c_trial_definition_mismatch")
    if digest(trial.get("inputs")) != digest(_frozen_workflow_inputs(case, definition)):
        raise ValueError("benchmark_c_trial_inputs_mismatch")


def _telemetry_scope(begin, request, trials, tickets):
    scope = request.get("scope")
    if not isinstance(scope, dict) or scope.get("kind") != "workflow":
        raise ValueError("benchmark_model_scope_invalid")
    bound = trials.get(scope.get("run_id"))
    if bound is None or bound["attempt_id"] != begin["attempt_id"]:
        raise ValueError("benchmark_model_scope_trial_mismatch")
    pairs = {(row.get("step_id"), row.get("execution_request_id"))
             for row in bound["trial"].get("history", []) if isinstance(row, dict)}
    pairs.update((ticket["step_id"], identity) for identity, ticket in tickets.items()
                 if ticket["attempt_id"] == begin["attempt_id"] and ticket["run_id"] == scope.get("run_id"))
    if (scope.get("step_id"), scope.get("execution_request_id")) not in pairs:
        raise ValueError("benchmark_model_scope_execution_mismatch")
    return scope["run_id"]


def _handoff_evidence(begin, tickets, evidence):
    if not isinstance(evidence, dict) or set(evidence) != {"ref", "text", "sha256"}:
        raise ValueError("benchmark_handoff_evidence_invalid")
    if hashlib.sha256(evidence["text"].encode("utf-8")).hexdigest() != evidence["sha256"]:
        raise ValueError("benchmark_handoff_snapshot_changed")
    job = json.loads(evidence["text"])
    parent = job.get("command_id")
    ticket = tickets.get(parent)
    if (ticket is None or ticket["attempt_id"] != begin["attempt_id"]
            or evidence["ref"] != "agent-commands/" + parent + ".json"
            or job.get("contract_version") != "agent_command.v1"
            or job.get("status") != "awaiting_grounding"
            or not isinstance(job.get("pending_grounding"), dict)
            or not isinstance(job["pending_grounding"].get("request_id"), str)):
        raise ValueError("benchmark_handoff_parent_mismatch")
    return parent, job["pending_grounding"]["request_id"]


def _current_handoff(begin, command, tickets, session):
    kind, request = command.get("kind"), command.get("request") or {}
    if kind not in {"agent_command_continue", "grounding_resolve", "grounding_status", "grounding_cancel"}:
        return None
    parents = [request.get("command_id")] if kind == "agent_command_continue" else list(tickets)
    matches = []
    session = Path(session).resolve()
    for parent in parents:
        ticket = tickets.get(parent)
        if ticket is None or ticket["attempt_id"] != begin["attempt_id"]:
            continue
        path = (session / "agent-commands" / (parent + ".json")).resolve()
        if not path.is_relative_to(session):
            raise ValueError("benchmark_handoff_path_invalid")
        if not path.is_file():
            continue
        raw = path.read_bytes()
        evidence = {"ref": "agent-commands/" + parent + ".json", "text": raw.decode("utf-8"),
                    "sha256": hashlib.sha256(raw).hexdigest()}
        try:
            found_parent, grounding = _handoff_evidence(begin, tickets, evidence)
        except ValueError:
            if kind == "agent_command_continue":
                raise
            continue
        if grounding == request.get("grounding_request_id") and found_parent == parent:
            matches.append(evidence)
    if len(matches) != 1:
        raise ValueError("benchmark_handoff_grounding_mismatch")
    return matches[0]


def _record_ticket(tickets, begin, run_id, result):
    ticket = result if isinstance(result.get("suggested_command"), dict) else result.get("pending")
    if not isinstance(ticket, dict) or not isinstance(ticket.get("suggested_command"), dict):
        return
    identity, step = ticket.get("execution_request_id"), ticket.get("step_id")
    if not isinstance(identity, str) or not identity or not isinstance(step, str) or not step:
        raise ValueError("benchmark_ticket_identity_invalid")
    value = {"attempt_id": begin["attempt_id"], "run_id": run_id, "step_id": step,
             "command": deepcopy(ticket["suggested_command"])}
    if identity in tickets and tickets[identity] != value:
        raise ValueError("benchmark_ticket_reused")
    tickets[identity] = value


def _internal_result_ticket(manifest, begin, request_id, definitions, tickets, trials):
    # 内部票据只允许读取本轮固定程序已经派发并返回的原命令。
    binding = _program_binding(manifest, begin)
    ticket = tickets.get(request_id)
    definition = definitions.get(begin["attempt_id"])
    if (binding is None or definition is None or ticket is None
            or ticket["attempt_id"] != begin["attempt_id"]):
        raise ValueError("benchmark_original_request_unknown")
    bound = trials.get(ticket["run_id"])
    if bound is None or bound["attempt_id"] != begin["attempt_id"]:
        raise ValueError("benchmark_internal_result_trial_mismatch")
    trial = bound["trial"]
    if trial.get("run_id") != ticket["run_id"] or ticket["step_id"] not in {
            step["step_id"] for step in definition["program"]["definition"]["steps"]}:
        raise ValueError("benchmark_internal_result_trial_mismatch")
    case = next(case for case in manifest["cases"] if case["case_id"] == begin["case_id"])
    _c_trial(binding, begin, trial, case, definition)
    pending = trial.get("pending")
    pending_match = (isinstance(pending, dict) and pending.get("execution_request_id") == request_id
                     and pending.get("step_id") == ticket["step_id"]
                     and digest(pending.get("suggested_command")) == digest(ticket["command"]))
    history_match = any(isinstance(row, dict) and row.get("execution_request_id") == request_id
                        and row.get("step_id") == ticket["step_id"] for row in trial.get("history", []))
    if not pending_match and not history_match:
        raise ValueError("benchmark_internal_result_ticket_mismatch")
    _route_policy(begin["route"], ticket["command"])
    if (not isinstance(request_id, str) or not request_id or any(char in request_id for char in "/\\:")
            or request_id in {".", ".."}):
        raise ValueError("benchmark_internal_result_path_invalid")
    return ticket


def _internal_result_source(manifest, begin, request_id, definitions, tickets, trials, evidence):
    ticket = _internal_result_ticket(manifest, begin, request_id, definitions, tickets, trials)
    if not isinstance(evidence, dict) or set(evidence) != {"command", "response"}:
        raise ValueError("benchmark_internal_result_evidence_invalid")
    values = {}
    for name, folder in (("command", "commands"), ("response", "responses")):
        snapshot = evidence[name]
        if (not isinstance(snapshot, dict) or set(snapshot) != {"ref", "text", "sha256"}
                or snapshot["ref"] != folder + "/" + request_id + ".json"
                or hashlib.sha256(snapshot["text"].encode("utf-8")).hexdigest() != snapshot["sha256"]):
            raise ValueError("benchmark_internal_result_snapshot_changed")
        values[name] = json.loads(snapshot["text"])
    response = values["response"]
    if digest(values["command"]) != digest(ticket["command"]):
        raise ValueError("benchmark_internal_result_command_mismatch")
    result = response.get("result") if isinstance(response, dict) else None
    # 外层原回执可读不代表动作终态，异步工作者仍须按原身份另行结算。
    agent_envelope = isinstance(result, dict) and result.get("contract_version") == "agent_command.v1"
    readable = (result.get("command_id") == request_id and result.get("status") in {
        "running", "awaiting_grounding", "completed", "failed", "cancelled"}) if agent_envelope else _terminal(response)
    if (not isinstance(response, dict) or response.get("status") != "returned" or not readable
            or digest(response.get("command")) != digest(ticket["command"])
            or any(key in response and response[key] != request_id for key in ("request_id", "command_id"))
            or (isinstance(response.get("result"), dict) and "command_id" in response["result"]
                and response["result"]["command_id"] != request_id)):
        raise ValueError("benchmark_internal_result_response_mismatch")
    return {"attempt_id": begin["attempt_id"], "request_id": request_id,
            "ticket": deepcopy(ticket), "evidence": deepcopy(evidence)}


def _current_internal_result(manifest, begin, request_id, definitions, tickets, trials, session):
    _internal_result_ticket(manifest, begin, request_id, definitions, tickets, trials)
    evidence = {}
    session = Path(session).resolve()
    for name, folder in (("command", "commands"), ("response", "responses")):
        ref = folder + "/" + request_id + ".json"
        path = (session / ref).resolve()
        if not path.is_relative_to(session) or not path.is_file():
            raise ValueError("benchmark_internal_result_dispatch_missing")
        raw = path.read_bytes()
        evidence[name] = {"ref": ref, "text": raw.decode("utf-8"), "sha256": hashlib.sha256(raw).hexdigest()}
    return _internal_result_source(manifest, begin, request_id, definitions, tickets, trials, evidence)


def _internal_result_receipt(source, receipt):
    original = json.loads(source["evidence"]["response"]["text"])
    # 原公开回执隐藏输入命令及嵌套 request，磁盘原件仍须严格匹配票据。
    command = original.pop("command")
    if isinstance(original.get("result"), dict):
        original["result"].pop("request", None)
    if receipt.get("request_id") != source["request_id"] or any(
            key not in receipt or digest(receipt[key]) != digest(value) for key, value in original.items()) or (
            "command" in receipt and digest(receipt["command"]) != digest(command)):
        raise ValueError("benchmark_internal_result_receipt_mismatch")


def _agent_parent(begin, command, request_id, result, requests, tickets):
    parent = ((command.get("request") or {}).get("command_id")
              if command.get("kind") in {"agent_command_status", "agent_command_continue", "agent_command_cancel"}
              else request_id)
    source = requests.get(parent) or tickets.get(parent)
    if result.get("command_id") != parent or source is None or source["attempt_id"] != begin["attempt_id"]:
        raise ValueError("benchmark_agent_command_identity_mismatch")
    return parent


def _c_guard(binding, begin, command, request_id, definitions, tickets, handoff=None, trials=None):
    kind, request = command.get("kind"), command.get("request", {})
    if not isinstance(request, dict):
        raise ValueError("benchmark_workflow_request_invalid")
    if binding is None:
        return
    if kind == "learning_workflow":
        action = request.get("action")
        if action == "record_model_call":
            _telemetry_scope(begin, request, trials or {}, tickets)
            return
        if action in {"read", "start"}:
            for key in ("workflow_id", "program_id"):
                if request.get(key) != binding[key]:
                    raise ValueError("benchmark_c_command_definition_mismatch")
            if action == "start":
                if request.get("start_step_id") != binding["start_step_id"]:
                    raise ValueError("benchmark_c_entry_mismatch")
                if begin["attempt_id"] not in definitions:
                    raise ValueError("benchmark_c_definition_read_required")
        elif action not in {"prepare", "run", "continue", "review", "verify", "status", "cancel"}:
            raise ValueError("benchmark_c_workflow_action_not_frozen")
        return
    ticket = tickets.get(request_id)
    if (ticket is not None and ticket["attempt_id"] == begin["attempt_id"]
            and ticket["command"] == command):
        return
    if kind in {"capture", "select"}:
        return
    if kind in {"agent_command_status", "agent_command_cancel"} and (request.get("command_id") in tickets
            and tickets[request["command_id"]]["attempt_id"] == begin["attempt_id"]):
        return
    if kind in {"agent_command_continue", "grounding_resolve", "grounding_status", "grounding_cancel"} and handoff is not None:
        parent, grounding = _handoff_evidence(begin, tickets, handoff)
        if (request.get("grounding_request_id") == grounding
                and (kind != "agent_command_continue" or request.get("command_id") == parent)):
            return
    raise ValueError("benchmark_c_command_not_bound_to_trial")


def _reconciliation(command):
    return (command.get("kind") in {"agent_command_status", "agent_command_cancel", "grounding_status", "grounding_cancel"}
            or command.get("kind") == "learning_workflow" and
            (command.get("request") or {}).get("action") in {"status", "cancel"})


def _row(manifest, begin, finish, receipt):
    case = next(item for item in manifest["cases"] if item["case_id"] == begin["case_id"])
    assessment = _assessment(finish["assessment"])
    elapsed = finish["ended_ns"] - begin["started_ns"]
    if elapsed < 0:
        raise ValueError("benchmark_clock_invalid")
    timed_out = elapsed >= case["timeout_seconds"] * 1_000_000_000
    evaluated_receipt = deepcopy(receipt)
    if "fixture_prepared" in begin:
        verdict = evaluate_case(case, begin["fixture_prepared"], finish["fixture_observed"])
        assessment["wrong_clicks"] = max(assessment["wrong_clicks"], verdict["observed_wrong_clicks"])
        if isinstance(evaluated_receipt, dict):
            result = evaluated_receipt.get("result")
            if not isinstance(result, dict):
                result = {}
            evaluated_receipt["result"] = {**result, "case_verdict": verdict}
    completed = (_succeeded(receipt) and _matches(evaluated_receipt, case["success_rule"])
                 and not timed_out and not finish["unresolved_requests"] and not case["is_negative"])
    if _program_binding(manifest, begin) is not None:
        result = (receipt or {}).get("result") or {}
        completed = completed and result.get("status") == "completed"
    if assessment["safe_rejection"] and not case["is_negative"]:
        raise ValueError("benchmark_positive_cannot_be_safe_rejection")
    if assessment["safe_rejection"] and (not _terminal(receipt) or timed_out
            or finish["unresolved_requests"] or not _matches(receipt, case["success_rule"])):
        raise ValueError("benchmark_safe_rejection_unverified")
    measurement = finish.get("measurement", {})
    events = measurement.get("events", [])
    return {"schema": "workflow_benchmark_run.v1", "purpose": manifest.get("purpose", "formal"),
        "run_id": measurement.get("run_id") or begin["attempt_id"],
        "route": begin["route"], "case_id": case["case_id"], "task_family": case["task_family"],
        **manifest["model"], "variation": case["variation"], "cold_or_warm": case["cold_or_warm"],
        "attempt_index": begin["attempt_index"], "is_negative": case["is_negative"],
        "first_attempt_success": completed and begin["attempt_index"] == 1
            and not assessment["wrong_clicks"] and not assessment["recovery_count"],
        "completed": completed, "safe_rejection": assessment["safe_rejection"],
        "wrong_clicks": assessment["wrong_clicks"], "recovery_count": assessment["recovery_count"],
        "elapsed_ns": elapsed, "timed_out": timed_out, "events": events,
        "telemetry": {"planning": False, "grounding": False, "verification": False}}


class BenchmarkCollection:
    """单调用者采集；中断保留原意图，绝不据此自动重交输入。"""

    def __init__(self, *, manifest_path: Path, root: Path, directory: Path, client, fixture_driver=None):
        self.root = Path(root).resolve()
        self.manifest = load_manifest(manifest_path)
        verify_candidate(self.manifest, root=self.root)
        if client.recognition_source != self.manifest["model"]["source"]:
            raise ValueError("benchmark_model_source_mismatch")
        self.client = client
        self.fixture_driver = fixture_driver
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        _write_new(self.directory / "manifest.json", self.manifest)
        self._tail = self.manifest["manifest_sha256"]
        self._sequence = 0
        self._active = None
        self._counts = Counter()
        self._requests = {}
        self._receipts = {}
        self._trials = {}
        self._definitions = {}
        self._tickets = {}
        self._append("opened", {"session_directory": client.session_directory,
            **({"workspace_data_root": str(client.data_root)}
               if getattr(client, "data_root", None) is not None else {}),
            "status": client.status, "started_ns": perf_counter_ns(),
            "model_configuration": "caller_declared_digest", "clock": "perf_counter_ns"})

    def next_case(self):
        for case in self.manifest["cases"]:
            for route in case["routes"]:
                if self._counts[(case["case_id"], route)] == 0:
                    return {"case_id": case["case_id"], "route": route,
                            "inputs": deepcopy(case["inputs"]), "cohort": case["cohort"]}
        return None

    def _append(self, kind, payload):
        row = {"sequence": self._sequence, "previous_sha256": self._tail,
               "kind": kind, "payload": payload}
        row["sha256"] = digest(row)
        with (self.directory / "journal.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._tail = row["sha256"]
        self._sequence += 1

    def begin(self, *, case_id, route):
        if self._active is not None:
            raise ValueError("benchmark_attempt_already_active")
        if any(not _request_terminal(value["command"], self._receipts.get(key))
               for key, value in self._requests.items()):
            raise ValueError("benchmark_previous_attempt_unresolved_stop_and_reconcile")
        verify_candidate(self.manifest, root=self.root)
        case = next((item for item in self.manifest["cases"] if item["case_id"] == case_id), None)
        if case is None or route not in case["routes"]:
            raise ValueError("benchmark_case_or_route_not_frozen")
        identity = (case_id, route)
        prepared = None
        if self.fixture_driver is not None:
            following = self.next_case()
            if not self._counts[identity] and (following is None or (following["case_id"], following["route"]) != identity):
                raise ValueError("benchmark_frozen_schedule_order_mismatch")
            self._append("fixture_prepare", {"case_id": case_id, "route": route,
                "started_ns": perf_counter_ns()})
            prepared = self.fixture_driver.prepare(case)
        begin = {"attempt_id": "benchmark-" + uuid4().hex, "case_id": case_id, "route": route,
                 "attempt_index": self._counts[identity] + 1, "started_ns": perf_counter_ns()}
        if prepared is not None:
            begin["fixture_prepared"] = deepcopy(prepared)
        self._append("begin", begin)
        self._counts[identity] += 1
        self._active = deepcopy(begin)
        return {**{key: value for key, value in begin.items() if key != "fixture_prepared"},
                "inputs": deepcopy(case["inputs"]), "timeout_seconds": case["timeout_seconds"],
                "route_policy": {"route": route, "execution_strategy": _route_strategy(route)}}

    async def call(self, tool, arguments):
        if self._active is None:
            raise ValueError("benchmark_attempt_required")
        verify_candidate(self.manifest, root=self.root)
        args = deepcopy(arguments)
        if not isinstance(args, dict):
            raise ValueError("benchmark_arguments_invalid")
        request_id = args.get("request_id")
        submitted = tool in {"instant_run", "instant_submit"}
        if submitted:
            if not isinstance(request_id, str) or not request_id or not isinstance(args.get("command"), dict):
                raise ValueError("benchmark_request_required")
            if request_id in self._requests:
                raise ValueError("benchmark_input_replay_forbidden_use_original_result")
            case = next(item for item in self.manifest["cases"] if item["case_id"] == self._active["case_id"])
            command = args["command"]
            request = command.get("request", {})
            route = self._active["route"]
            binding = _program_binding(self.manifest, self._active)
            if not isinstance(request, dict):
                raise ValueError("benchmark_workflow_request_invalid")
            handoff = _current_handoff(self._active, command, self._tickets,
                                       self.client.session_directory) if binding is not None else None
            _c_guard(binding, self._active, command, request_id, self._definitions, self._tickets,
                     handoff, self._trials)
            _route_policy(route, command)
            if command.get("kind") == "learning_workflow":
                if not isinstance(request, dict):
                    raise ValueError("benchmark_workflow_request_invalid")
                if request.get("action") == "start":
                    strategy = _route_strategy(route)
                    if "execution_strategy" in request and request["execution_strategy"] != strategy:
                        raise ValueError("benchmark_execution_strategy_conflict")
                    request["execution_strategy"] = strategy
                elif request.get("action") != "read" or binding is None:
                    trial_id = (_telemetry_scope(self._active, request, self._trials, self._tickets)
                                if request.get("action") == "record_model_call" else request.get("run_id"))
                    bound = self._trials.get(trial_id) if isinstance(trial_id, str) else None
                    if bound is None or bound["attempt_id"] != self._active["attempt_id"]:
                        raise ValueError("benchmark_trial_identity_mismatch")
            reconciliation = _reconciliation(command)
            remaining = case["timeout_seconds"] - (perf_counter_ns() - self._active["started_ns"]) / 1_000_000_000
            if remaining <= 0 and not reconciliation:
                raise ValueError("benchmark_deadline_exceeded_reconcile_original_request")
            if tool == "instant_run":
                requested_wait = args.get("wait_ms", 25000)
                if type(requested_wait) is not int or requested_wait < 0:
                    raise ValueError("benchmark_wait_ms_invalid")
                args["wait_ms"] = min(requested_wait, 25000, max(0, int(remaining * 1000)))
            if command.get("kind") == "learning_workflow" and request.get("action") == "start":
                expected_inputs = _frozen_workflow_inputs(case, self._definitions[self._active["attempt_id"]]
                                                         if binding is not None else None)
                if digest(request.get("inputs")) != digest(expected_inputs):
                    raise ValueError("benchmark_inputs_not_frozen")
                if any(item["attempt_id"] == self._active["attempt_id"] for item in self._trials.values()):
                    raise ValueError("benchmark_one_trial_per_attempt")
            if handoff is not None:
                self._append("workflow_handoff", {"attempt_id": self._active["attempt_id"],
                    "request_id": request_id, "command": deepcopy(command), "evidence": handoff})
        elif tool == "instant_result":
            if request_id not in self._requests:
                if args.get("detail", "full") != "full":
                    raise ValueError("benchmark_internal_result_full_receipt_required")
                source = _current_internal_result(self.manifest, self._active, request_id,
                    self._definitions, self._tickets, self._trials, self.client.session_directory)
                self._append("workflow_internal_result", source)
                self._requests[request_id] = {"attempt_id": self._active["attempt_id"],
                    "command": deepcopy(source["ticket"]["command"]), "internal_result": source}
            if "internal_result" in self._requests[request_id] and args.get("detail", "full") != "full":
                raise ValueError("benchmark_internal_result_full_receipt_required")
        elif tool not in {"instant_status", "instant_image"}:
            raise ValueError("benchmark_tool_invalid")
        attempt_id = self._active["attempt_id"]
        if request_id in self._requests and self._requests[request_id]["attempt_id"] != attempt_id:
            raise ValueError("benchmark_request_from_another_attempt")
        intent = {"attempt_id": attempt_id, "tool": tool, "arguments": args,
                  "started_ns": perf_counter_ns()}
        self._append("call", intent)
        if submitted:
            self._requests[request_id] = {"attempt_id": attempt_id, "command": deepcopy(args["command"])}
        try:
            receipt = await self.client.call(tool, args)
        except Exception as error:
            self._append("transport_error", {"attempt_id": attempt_id, "request_id": request_id,
                "type": type(error).__name__, "ended_ns": perf_counter_ns()})
            raise
        self._append("receipt", {"attempt_id": attempt_id, "tool": tool,
            "request_id": request_id, "receipt": receipt, "ended_ns": perf_counter_ns()})
        if tool in {"instant_run", "instant_submit", "instant_result"}:
            if receipt.get("request_id") != request_id:
                raise ValueError("benchmark_receipt_request_id_mismatch")
            if "internal_result" in self._requests[request_id]:
                _internal_result_receipt(self._requests[request_id]["internal_result"], receipt)
            result = receipt.get("result")
            command = self._requests[request_id]["command"]
            if isinstance(result, dict) and command.get("kind") == "learning_workflow":
                request = command.get("request") or {}
                trial_id = result.get("run_id")
                if isinstance(trial_id, str) and result.get("execution_strategy") != _route_strategy(self._active["route"]):
                    raise ValueError("benchmark_execution_strategy_receipt_mismatch")
                binding = _program_binding(self.manifest, self._active)
                if binding is not None:
                    if request.get("action") == "read":
                        definition = _c_definition(binding, receipt)
                        self._definitions[attempt_id] = definition
                        self._append("workflow_definition", {"attempt_id": attempt_id,
                            "request_id": request_id, "definition": definition})
                    elif (request.get("action") == "start" and _succeeded(receipt)
                          or isinstance(result.get("history"), list)):
                        case = next(case for case in self.manifest["cases"]
                                    if case["case_id"] == self._active["case_id"])
                        _c_trial(binding, self._active, result, case, self._definitions[attempt_id])
            _remember(self._receipts, request_id, receipt)
            if isinstance(result, dict) and command.get("kind") == "learning_workflow":
                request = command.get("request") or {}
                trial_id = result.get("run_id")
                if request.get("action") == "start" and isinstance(trial_id, str):
                    if trial_id in self._trials:
                        bound = self._trials[trial_id]
                        if bound["attempt_id"] != attempt_id or bound["start_request_id"] != request_id:
                            raise ValueError("benchmark_trial_reused")
                    else:
                        self._trials[trial_id] = {"attempt_id": attempt_id,
                                                  "start_request_id": request_id, "trial": deepcopy(result)}
                elif trial_id in self._trials:
                    if (request.get("run_id") != trial_id
                            or self._trials[trial_id]["attempt_id"] != attempt_id):
                        raise ValueError("benchmark_trial_identity_mismatch")
                    if isinstance(result.get("history"), list):
                        self._trials[trial_id]["trial"] = deepcopy(result)
                if trial_id in self._trials:
                    _record_ticket(self._tickets, self._active, trial_id, result)
            if isinstance(result, dict) and result.get("contract_version") == "agent_command.v1":
                command = self._requests[request_id]["command"]
                try:
                    original = _agent_parent(self._active, command, request_id, result, self._requests, self._tickets)
                except ValueError:
                    self._receipts.pop(request_id, None)
                    raise
                _remember(self._receipts, original, receipt)
        return receipt

    def _measurement(self):
        bound = [(key, value) for key, value in self._trials.items()
                 if value["attempt_id"] == self._active["attempt_id"]]
        if not bound:
            return {"status": "unbound", "run_id": None, "events": [], "evidence_files": []}
        run_id, value = bound[0]
        session = Path(self.client.session_directory).resolve()
        try:
            metrics = load_run_metrics(session, run_id, trial=value["trial"])
            if metrics.get("status") == "unavailable":
                return {"status": "unavailable", "run_id": run_id, "events": [],
                        "evidence_files": [], "error": metrics["error"]}
            events = load_events(session, run_id)
            files = []
            for ref in sorted({ref for event in events for ref in event["evidence_refs"]}):
                path = (session / ref).resolve()
                if not path.is_relative_to(session):
                    raise ValueError("benchmark_measurement_evidence_outside_session")
                raw = path.read_bytes()
                files.append({"ref": ref, "sha256": hashlib.sha256(raw).hexdigest(),
                              "text": raw.decode("utf-8")})
            return {"status": "partial", "run_id": run_id, "events": events,
                    "evidence_files": files, "metrics": metrics}
        except (OSError, ValueError) as error:
            return {"status": "unavailable", "run_id": run_id, "events": [],
                    "evidence_files": [], "error": {"type": type(error).__name__}}

    def finish(self, *, request_id, assessment):
        if self._active is None or request_id not in self._requests or self._requests[request_id]["attempt_id"] != self._active["attempt_id"]:
            raise ValueError("benchmark_finish_request_not_in_attempt")
        verify_candidate(self.manifest, root=self.root)
        binding = _program_binding(self.manifest, self._active)
        if binding is not None:
            command = self._requests[request_id]["command"]
            request = command.get("request") or {}
            if (command.get("kind") != "learning_workflow" or request.get("action") not in
                    {"run", "continue", "review", "verify", "status", "cancel"}
                    or request.get("run_id") not in self._trials):
                raise ValueError("benchmark_c_finish_bound_workflow_result_required")
        finish = {"attempt_id": self._active["attempt_id"], "request_id": request_id,
                  "assessment": _assessment(assessment), "ended_ns": perf_counter_ns(),
                  "unresolved_requests": [key for key, value in self._requests.items()
                    if value["attempt_id"] == self._active["attempt_id"]
                    and not _request_terminal(value["command"], self._receipts.get(key))]}
        finish["measurement"] = self._measurement()
        if self._active["route"] == "C":
            finish["workflow_provenance"] = self._provenance()
        if self.fixture_driver is not None:
            finish["fixture_observed"] = self.fixture_driver.observe(self._active["case_id"])
            finish["ended_ns"] = perf_counter_ns()
        row = _row(self.manifest, self._active, finish, self._receipts.get(request_id))
        self._append("finish", finish)
        self._active = None
        return row

    def _provenance(self):
        binding = _c_binding(self.manifest, self._active)
        definition = self._definitions.get(self._active["attempt_id"])
        if binding is None or definition is None:
            return {"status": "unbound", "definition": None, "trial": None,
                    "evidence_files": [], "coverage": None}
        trials = [item["trial"] for item in self._trials.values()
                  if item["attempt_id"] == self._active["attempt_id"]]
        trial = deepcopy(trials[0]) if trials else None
        snapshots, errors = [], []
        session = Path(self.client.session_directory).resolve()
        refs = set()
        for row in (trial or {}).get("history", []):
            execution_id = row.get("execution_request_id")
            if not isinstance(execution_id, str) or not execution_id:
                errors.append("execution_request_id_missing")
                continue
            refs.update(f"{folder}/{execution_id}.json" for folder in ("commands", "responses"))
            if row.get("terminal_receipt") is not None:
                refs.add(f"agent-commands/{execution_id}.json")
            refs.update((row.get("verification") or {}).get("evidence_refs", []))
        if any(not isinstance(ref, str) for ref in refs):
            errors.append("evidence_ref_invalid")
        image_paths = set()
        collected_paths = set()
        for ref in sorted(ref for ref in refs if isinstance(ref, str)):
            path = (session / ref.replace("\\", "/")).resolve()
            if not path.is_relative_to(session):
                errors.append("evidence_ref_outside_session")
                continue
            # 原引用字节不变，只按同会话内实际路径去重快照。
            if path in collected_paths:
                continue
            if not path.is_file():
                errors.append("evidence_missing:" + ref)
                continue
            try:
                raw = path.read_bytes()
                snapshots.append({"ref": path.relative_to(session).as_posix(),
                    "sha256": hashlib.sha256(raw).hexdigest(), "text": raw.decode("utf-8")})
                collected_paths.add(path)
                _image_paths(json.loads(raw.decode("utf-8")), image_paths)
            except (OSError, UnicodeError) as error:
                errors.append("evidence_unavailable:" + ref + ":" + type(error).__name__)
            except json.JSONDecodeError:
                errors.append("evidence_json_invalid:" + ref)
        for image_path in sorted(image_paths):
            path = (session / image_path).resolve()
            if not path.is_relative_to(session):
                errors.append("image_outside_session")
                continue
            if path in collected_paths:
                continue
            try:
                raw = path.read_bytes()
                snapshots.append({"ref": path.relative_to(session).as_posix(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "data_base64": base64.b64encode(raw).decode("ascii")})
                collected_paths.add(path)
            except OSError as error:
                errors.append("image_unavailable:" + path.relative_to(session).as_posix())
        image_checks = [step.get("verification", {}).get("image_check")
                        for step in definition["program"]["definition"]["steps"]]
        archived_references = set()
        for check in image_checks:
            if check is None:
                continue
            from app.learning_memory.image_verification import load_reference_image, validate_image_check
            from types import SimpleNamespace
            try:
                check = validate_image_check(check)
                data_root = getattr(self.client, "data_root", None)
                if data_root is None or not Path(data_root).is_absolute():
                    raise ValueError("benchmark_image_library_root_missing")
                library_root = Path(data_root).resolve() / "memory-library"
                raw = load_reference_image(SimpleNamespace(_artifact_root=library_root), check)
                ref = "library/desktop-review/evidence-objects/" + check["reference_sha256"] + ".png"
                if ref not in archived_references:
                    snapshots.append({"ref": ref, "sha256": hashlib.sha256(raw).hexdigest(),
                                      "data_base64": base64.b64encode(raw).decode("ascii")})
                    archived_references.add(ref)
            except (OSError, ValueError) as error:
                errors.append("image_reference_unavailable:" + type(error).__name__)
        coverage = inspect_coverage(binding, definition["program"], trial, snapshots)
        return {"status": "bound", "definition": deepcopy(definition), "trial": trial,
                "evidence_files": snapshots, "coverage": coverage, "collection_errors": errors}

    def closed(self, status, error=None):
        self._append("closed", {"status": status, "error_type": type(error).__name__ if error else None,
                                 "ended_ns": perf_counter_ns()})


def _image_paths(value, result):
    if isinstance(value, dict):
        if isinstance(value.get("image_path"), str):
            result.add(value["image_path"])
        for child in value.values():
            _image_paths(child, result)
    elif isinstance(value, list):
        for child in value:
            _image_paths(child, result)

def _journal(directory, manifest):
    previous = manifest["manifest_sha256"]
    rows = []
    for sequence, line in enumerate((directory / "journal.jsonl").read_text(encoding="utf-8").splitlines()):
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) != {"sequence", "previous_sha256", "kind", "payload", "sha256"}:
            raise ValueError("benchmark_journal_fields_invalid")
        unsigned = {key: value for key, value in row.items() if key != "sha256"}
        if row["sequence"] != sequence or row["previous_sha256"] != previous or digest(unsigned) != row["sha256"]:
            raise ValueError("benchmark_journal_integrity_invalid")
        previous = row["sha256"]
        rows.append(row)
    return rows


def compare_collection(directory):
    directory = Path(directory).resolve()
    manifest = load_manifest(directory / "manifest.json")
    if _scoring_digest() != manifest["scoring_sha256"]:
        raise ValueError("benchmark_scoring_source_changed")
    root = Path(__file__).resolve().parents[1]
    for relative in _COMPARISON_SOURCES:
        if manifest["source_files"].get(relative) != hashlib.sha256((root / relative).read_bytes()).hexdigest():
            raise ValueError("benchmark_scoring_dependency_changed")
    journal = _journal(directory, manifest)
    begins, finishes, receipts, requests = {}, {}, {}, {}
    definitions, trials, tickets, handoffs = {}, {}, {}, {}
    for event in journal:
        payload = event["payload"]
        if event["kind"] == "begin":
            if payload["attempt_id"] in begins:
                raise ValueError("benchmark_attempt_reused")
            begins[payload["attempt_id"]] = payload
        elif event["kind"] == "workflow_handoff":
            begin = begins.get(payload["attempt_id"])
            if begin is None:
                raise ValueError("benchmark_handoff_attempt_mismatch")
            _handoff_evidence(begin, tickets, payload["evidence"])
            if payload["request_id"] in handoffs:
                raise ValueError("benchmark_handoff_reused")
            handoffs[payload["request_id"]] = payload
        elif event["kind"] == "workflow_internal_result":
            begin = begins.get(payload["attempt_id"])
            if begin is None or payload["request_id"] in requests:
                raise ValueError("benchmark_internal_result_identity_mismatch")
            source = _internal_result_source(manifest, begin, payload["request_id"],
                definitions, tickets, trials, payload["evidence"])
            if digest(source) != digest(payload):
                raise ValueError("benchmark_internal_result_binding_changed")
            requests[payload["request_id"]] = {"attempt_id": begin["attempt_id"],
                "arguments": {"command": deepcopy(source["ticket"]["command"])}, "internal_result": source}
        elif event["kind"] == "call" and payload["tool"] == "instant_result":
            request_id = payload["arguments"].get("request_id")
            source = requests.get(request_id)
            if source is None or source["attempt_id"] != payload["attempt_id"]:
                raise ValueError("benchmark_original_request_unknown")
            if "internal_result" in source and payload["arguments"].get("detail", "full") != "full":
                raise ValueError("benchmark_internal_result_full_receipt_required")
        elif event["kind"] == "call" and payload["tool"] in {"instant_run", "instant_submit"}:
            begin = begins[payload["attempt_id"]]
            request_id = payload["arguments"]["request_id"]
            if request_id in requests or request_id in tickets:
                if request_id in tickets and request_id not in requests and tickets[request_id]["attempt_id"] == begin["attempt_id"]:
                    pass
                else:
                    raise ValueError("benchmark_request_reused")
            command = payload["arguments"]["command"]
            request = command.get("request") or {}
            _route_policy(begin["route"], command)
            handoff = handoffs.pop(request_id, None)
            if handoff is not None and (handoff["attempt_id"] != begin["attempt_id"] or handoff["command"] != command):
                raise ValueError("benchmark_handoff_call_mismatch")
            _c_guard(_program_binding(manifest, begin), begin, command,
                     request_id, definitions, tickets, handoff["evidence"] if handoff else None, trials)
            case = next(case for case in manifest["cases"] if case["case_id"] == begin["case_id"])
            if (payload["started_ns"] - begin["started_ns"] > case["timeout_seconds"] * 1_000_000_000
                    and not _reconciliation(command)):
                raise ValueError("benchmark_deadline_exceeded_reconcile_original_request")
            if command.get("kind") == "learning_workflow":
                case = next(case for case in manifest["cases"] if case["case_id"] == begin["case_id"])
                if request.get("action") == "start":
                    expected_inputs = _frozen_workflow_inputs(case, definitions[begin["attempt_id"]]
                        if _program_binding(manifest, begin) is not None else None)
                    if digest(request.get("inputs")) != digest(expected_inputs):
                        raise ValueError("benchmark_inputs_not_frozen")
                    if any(item["attempt_id"] == begin["attempt_id"] for item in trials.values()):
                        raise ValueError("benchmark_one_trial_per_attempt")
                    if request.get("execution_strategy") != _route_strategy(begin["route"]):
                        raise ValueError("benchmark_execution_strategy_conflict")
                elif request.get("action") != "read":
                    trial_id = (_telemetry_scope(begin, request, trials, tickets)
                                if request.get("action") == "record_model_call" else request.get("run_id"))
                    if trial_id not in trials or trials[trial_id]["attempt_id"] != begin["attempt_id"]:
                        raise ValueError("benchmark_trial_identity_mismatch")
            requests[request_id] = payload
        elif event["kind"] == "receipt" and payload["request_id"] in requests:
            request_id, receipt = payload["request_id"], payload["receipt"]
            if payload["attempt_id"] != requests[request_id]["attempt_id"]:
                raise ValueError("benchmark_receipt_attempt_mismatch")
            if receipt.get("request_id") != request_id:
                raise ValueError("benchmark_receipt_request_id_mismatch")
            if "internal_result" in requests[request_id]:
                if payload["tool"] != "instant_result":
                    raise ValueError("benchmark_internal_result_read_only_required")
                _internal_result_receipt(requests[request_id]["internal_result"], receipt)
            _remember(receipts, request_id, receipt)
            result = receipt.get("result")
            command = requests[request_id]["arguments"]["command"]
            request = command.get("request") or {}
            if isinstance(result, dict) and command.get("kind") == "learning_workflow":
                begin = begins[payload["attempt_id"]]
                binding = _program_binding(manifest, begin)
                trial_id = result.get("run_id")
                if binding is not None and isinstance(result.get("history"), list):
                    case = next(case for case in manifest["cases"] if case["case_id"] == begin["case_id"])
                    _c_trial(binding, begin, result, case, definitions[begin["attempt_id"]])
                if request.get("action") == "start" and isinstance(trial_id, str):
                    if binding is not None:
                        case = next(case for case in manifest["cases"] if case["case_id"] == begin["case_id"])
                        _c_trial(binding, begin, result, case, definitions[begin["attempt_id"]])
                    if trial_id in trials:
                        if (trials[trial_id]["attempt_id"] != begin["attempt_id"]
                                or trials[trial_id]["start_request_id"] != request_id):
                            raise ValueError("benchmark_trial_reused")
                    else:
                        if any(item["attempt_id"] == begin["attempt_id"] for item in trials.values()):
                            raise ValueError("benchmark_one_trial_per_attempt")
                        trials[trial_id] = {"attempt_id": begin["attempt_id"],
                            "start_request_id": request_id, "trial": deepcopy(result)}
                elif trial_id in trials and isinstance(result.get("history"), list):
                    if request.get("run_id") != trial_id or trials[trial_id]["attempt_id"] != begin["attempt_id"]:
                        raise ValueError("benchmark_trial_identity_mismatch")
                    trials[trial_id]["trial"] = deepcopy(result)
                if trial_id in trials:
                    _record_ticket(tickets, begin, trial_id, result)
            if isinstance(result, dict) and result.get("contract_version") == "agent_command.v1":
                command = requests[request_id]["arguments"]["command"]
                original = _agent_parent(begins[payload["attempt_id"]], command, request_id,
                                         result, requests, tickets)
                _remember(receipts, original, receipt)
        elif event["kind"] == "workflow_definition":
            begin = begins[payload["attempt_id"]]
            binding = _program_binding(manifest, begin)
            request_id = payload["request_id"]
            source = requests.get(request_id)
            if (binding is None or source is None or source["attempt_id"] != begin["attempt_id"]
                    or source["arguments"]["command"] != {"kind": "learning_workflow", "request": {
                        "action": "read", "workflow_id": binding["workflow_id"], "program_id": binding["program_id"]}}):
                raise ValueError("benchmark_c_definition_request_mismatch")
            evidence = payload["definition"]["artifact_evidence"]
            artifact = next(item for item in manifest["artifacts"] if item["kind"] == "workflow"
                            and Path(item["path"]).resolve() == Path(binding["artifact_path"]).resolve()
                            and item["version"] == binding["program_id"])
            if evidence["sha256"] != artifact["sha256"]:
                raise ValueError("benchmark_c_artifact_snapshot_not_frozen")
            definition = _c_definition(binding, receipts.get(request_id), evidence)
            if digest(definition) != digest(payload["definition"]):
                raise ValueError("benchmark_c_definition_snapshot_changed")
            definitions[begin["attempt_id"]] = definition
        elif event["kind"] == "finish":
            attempt = payload["attempt_id"]
            request_id = payload["request_id"]
            if attempt not in begins or attempt in finishes or requests.get(request_id, {}).get("attempt_id") != attempt:
                raise ValueError("benchmark_finish_identity_invalid")
            unresolved = [key for key, value in requests.items()
                          if value["attempt_id"] == attempt
                          and not _request_terminal(value["arguments"]["command"], receipts.get(key))]
            if payload["unresolved_requests"] != unresolved:
                raise ValueError("benchmark_unresolved_requests_snapshot_mismatch")
            finishes[attempt] = (payload, deepcopy(receipts.get(request_id)))
            if begins[attempt]["route"] in {"B", "C"}:
                binding = _program_binding(manifest, begins[attempt])
                provenance = payload.get("workflow_provenance", {"status": "unbound"})
                if binding is not None:
                    source = requests[request_id]["arguments"]["command"]
                    request = source.get("request") or {}
                    trial = trials.get(request.get("run_id"))
                    if (source.get("kind") != "learning_workflow" or request.get("action") not in
                            {"run", "continue", "review", "verify", "status", "cancel"} or trial is None
                            or trial["attempt_id"] != attempt):
                        raise ValueError("benchmark_c_finish_bound_workflow_result_required")
                    if begins[attempt]["route"] == "B":
                        continue
                    if (provenance.get("status") != "bound"
                            or provenance.get("definition") != definitions.get(attempt)
                            or provenance.get("trial") != trial["trial"]):
                        raise ValueError("benchmark_c_finish_provenance_mismatch")
                    coverage = inspect_coverage(binding, provenance["definition"]["program"],
                                                provenance["trial"], provenance["evidence_files"])
                    if digest(coverage) != digest(provenance["coverage"]):
                        raise ValueError("benchmark_c_coverage_snapshot_changed")
                elif provenance.get("status") != "unbound":
                    raise ValueError("benchmark_c_unbound_definition_claim")
    rows, excluded, measurements, observations, provenance_rows = [], [], [], [], []
    cases = {case["case_id"]: case for case in manifest["cases"]}
    for attempt, (finish, receipt) in finishes.items():
        begin = begins[attempt]
        measurement = finish.get("measurement", {})
        if measurement:
            summary = summarize_run(measurement["events"])
            if summary["run_id"] not in {None, measurement["run_id"]}:
                raise ValueError("benchmark_measurement_identity_mismatch")
            for snapshot in measurement["evidence_files"]:
                if hashlib.sha256(snapshot["text"].encode("utf-8")).hexdigest() != snapshot["sha256"]:
                    raise ValueError("benchmark_measurement_evidence_changed")
            measurements.append({"attempt_id": attempt, **measurement})
        row = _row(manifest, begin, finish, receipt)
        case = cases[begin["case_id"]]
        if begin["route"] == "C":
            provenance_rows.append({**finish.get("workflow_provenance", {"status": "unbound"}),
                "attempt_id": attempt, "case_id": begin["case_id"],
                "cohort": case["cohort"], "is_negative": case["is_negative"], "variation": case["variation"],
                })
        if "fixture_prepared" in begin:
            observations.append({"attempt_id": attempt, "verdict": evaluate_case(
                case, begin["fixture_prepared"], finish["fixture_observed"])})
        (rows if case["cohort"] == "scored" and case["variation"] != "recovery" else excluded).append(row)
    completed_slots = {(row["case_id"], row["route"]) for row in rows}
    required_slots = {(case["case_id"], route) for case in manifest["cases"]
                      if case["cohort"] == "scored" and case["variation"] != "recovery" for route in case["routes"]}
    limitations = ["caller_model_telemetry_unavailable", "outcome_errors_are_caller_observations",
                   "model_configuration_digest_is_caller_declared", "cold_warm_state_not_independently_verified",
                   "case_realization_and_route_semantics_not_independently_verified"]
    scored_c = [item for item in provenance_rows if item["cohort"] == "scored"
                and not item["is_negative"] and item["variation"] != "recovery"]
    if any(item["status"] == "unbound" for item in scored_c):
        limitations.append("c_route_definition_unbound")
    if any(item["status"] == "bound" and not item["coverage"]["eligible_for_full_rule_comparison"]
           for item in scored_c):
        limitations.append("c_route_coverage_unverified")
    if required_slots - completed_slots:
        limitations.append("planned_runs_missing")
    if begins.keys() - finishes.keys():
        limitations.append("unfinished_attempts")
    if any(item[0]["unresolved_requests"] for item in finishes.values()):
        limitations.append("unresolved_requests")
    if not journal or journal[-1]["kind"] != "closed" or journal[-1]["payload"]["status"].get("cleanup_verified") is not True:
        limitations.append("cleanup_unverified")
    comparison = compare_runs(rows, purpose=manifest.get("purpose", "formal"))
    return {"schema": "workflow_benchmark_collection_comparison.v1",
        "purpose": manifest.get("purpose", "formal"),
        "formal_quota_credit": comparison["formal_quota_credit"],
        "manifest_sha256": manifest["manifest_sha256"], "empirical_acceptance": False,
        "limitations": limitations, "comparison": comparison, "runs": rows,
        "excluded_learning_warmup_recovery": excluded,
        "measurement_snapshots": measurements,
        "workflow_provenance": provenance_rows,
        "c_route_contract": {"scope": "scored_positive_nonrecovery", "scored_attempts": len(scored_c),
            "bound_definitions": sum(item["status"] == "bound" for item in scored_c),
            "eligible_for_full_rule_comparison": bool(scored_c) and all(
                item["status"] == "bound" and item["coverage"]["eligible_for_full_rule_comparison"]
                for item in scored_c)},
        "case_observations": observations,
        "unfinished_attempts": [begins[key] for key in begins.keys() - finishes.keys()],
        "missing_planned_runs": [{"case_id": case, "route": route} for case, route in sorted(required_slots - completed_slots)],
        "evidence_scope": "original_mcp_receipts_and_frozen_rules_partial_telemetry"}


def export_comparison(result, output):
    output = Path(output)
    rows_path, report_path = output.with_name("runs.jsonl"), output.with_name("report.md")
    paths = (output, rows_path, report_path)
    if len(set(paths)) != 3:
        raise ValueError("benchmark_output_name_reserved")
    for path in paths:
        if path.exists():
            raise FileExistsError(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_new(output, result)
    with rows_path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in result["runs"]:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    lines = ["# 基准采集报告 / Benchmark collection report", "",
        "`empirical_acceptance=false`。此报告保留原回执与冻结规则，尚不能证明真实收益。 / Evidence remains partial; no empirical benefit is established.",
        "", "| 路线 / Route | 尝试 / Attempts | 首次成功率 / First success | 总模型调用 / Total calls |",
        "| --- | --- | --- | --- |"]
    if result.get("purpose", "formal") == "pilot":
        lines.insert(2, "`purpose=pilot`, `formal_quota_credit=0`, `pilot_not_formal_acceptance`.")
    for route, stats in result["comparison"]["routes"].items():
        rate = stats["first_attempt_success_rate"]
        calls = stats["model_calls"]["total"]
        lines.append(f"| {route} | {stats['attempts']} | {rate if rate is not None else 'unknown'} | {calls if calls is not None else 'unknown'} |")
    contract = result["c_route_contract"]
    lines.extend(["", "C 路线定义与规则资格 / C definition and rule qualification:", "",
        f"`scope={contract['scope']}`, `bound_definitions={contract['bound_definitions']}`, "
        f"`scored_attempts={contract['scored_attempts']}`, "
        f"`eligible_for_full_rule_comparison={str(contract['eligible_for_full_rule_comparison']).lower()}`.",
        "负向与恢复记录保留，完整模型计量仍未知。 / Negative and recovery records remain; full model telemetry is unknown."])
    lines.extend(["", "限制 / Limitations:", "", *["- " + item for item in result["limitations"]], "",
        "完整记录 / Full records: [comparison](" + output.name + "), [runs](runs.jsonl).", ""])
    with report_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))


async def _collect(args):
    manifest = load_manifest(args.manifest)
    verify_candidate(manifest, root=args.root)
    if args.recognition_source != manifest["model"]["source"]:
        raise ValueError("benchmark_model_source_mismatch")
    args.data_dir.mkdir(parents=True, exist_ok=False)
    workspace_data_root = getattr(args, "workspace_data_root", None) or args.data_dir / "runtime"
    client = LearningBenchmarkClient(root=args.root, data_root=workspace_data_root,
        evidence_dir=args.data_dir / "transport", recognition_source=args.recognition_source,
        model_directory=args.model_directory, delegate_profile=args.delegate_profile,
        api_profile=args.api_profile, allow_actions=args.allow_actions)
    collection = None
    error = None
    try:
        async with client:
            collection = BenchmarkCollection(manifest_path=args.manifest, root=args.root,
                directory=args.data_dir / "collection", client=client,
                fixture_driver=RecordDeskCaseDriver(args.fixture_root) if args.fixture_root else None)
            print(json.dumps({"status": "ready", "session_directory": client.session_directory,
                              "protocol": "next/begin/call/finish/stop"}), flush=True)
            while line := await asyncio.to_thread(sys.stdin.readline):
                message = json.loads(line)
                operation = message.pop("op")
                if operation == "stop":
                    break
                if operation == "next":
                    result = collection.next_case()
                elif operation == "begin":
                    result = collection.begin(**message)
                elif operation == "call":
                    result = await collection.call(**message)
                elif operation == "finish":
                    result = collection.finish(**message)
                else:
                    raise ValueError("benchmark_protocol_operation_invalid")
                print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)
    except BaseException as caught:
        error = caught
        raise
    finally:
        if collection is not None:
            collection.closed(client.status or {}, client.cleanup_error or error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("freeze", "baseline", "compare"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--workspace-data-root", type=Path,
                        help="Use an explicit existing learning workspace; evidence remains in the new data-dir.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--recognition-source", choices=("local", "agent_current", "agent_delegate", "external_api"))
    parser.add_argument("--model-directory", type=Path)
    parser.add_argument("--delegate-profile")
    parser.add_argument("--api-profile", type=Path)
    parser.add_argument("--fixture-root", type=Path,
                        help="Attach an already-running, fresh Record Desk fixture for frozen case reset and observation.")
    parser.add_argument("--allow-actions", action="store_true",
                        help="Enable the existing client action path; this does not replace runtime confirmation.")
    args = parser.parse_args(argv)
    if args.phase == "freeze":
        if args.spec is None or args.manifest is None:
            parser.error("freeze requires --spec and --manifest")
        result = freeze_manifest(_json(args.spec), root=args.root, destination=args.manifest)
        print(json.dumps({"manifest_sha256": result["manifest_sha256"]}))
    elif args.phase == "baseline":
        if args.manifest is None or args.data_dir is None or args.recognition_source is None:
            parser.error("baseline requires --manifest, --data-dir and --recognition-source")
        asyncio.run(_collect(args))
    else:
        if args.data_dir is None:
            parser.error("compare requires --data-dir")
        result = compare_collection(args.data_dir / "collection")
        if args.output:
            export_comparison(result, args.output)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
