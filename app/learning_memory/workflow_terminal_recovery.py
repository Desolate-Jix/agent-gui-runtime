"""死宿主只结算原终态事实；不持有输入、核验或调度能力。"""
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import re

import psutil

from app.core.receipt_action import _receipt_action
from .workflow_program import _id
from .workflow_runner import _digest, _exclusive, _run_id
from .workflow_trial import _receipt_state, _write


_PREVIEW = "workflow_terminal_recovery_preview.v1"
_SETTLEMENT = "workflow_terminal_recovery_settlement.v1"


def _snapshot(path):
    raw = path.read_bytes()
    def reject_constant(value):
        raise ValueError("workflow_recovery_json_invalid")
    value = json.loads(raw.decode("utf-8-sig"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("workflow_recovery_json_invalid")
    return value, sha256(raw).hexdigest()


def _action_claims(value):
    claims = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"action_executed", "previous_action_executed", "pressed"}:
                if child is not None and type(child) is not bool:
                    raise ValueError("workflow_recovery_action_fact_invalid")
                claims.append(child)
            elif isinstance(child, (dict, list)):
                claims.extend(_action_claims(child))
    elif isinstance(value, list):
        for child in value:
            claims.extend(_action_claims(child))
    return claims


class WorkflowTerminalRecovery:
    def __init__(self, trials, *, host_identity, runner_pid):
        if (not isinstance(host_identity, dict) or set(host_identity) != {"pid", "created"}
                or type(host_identity["pid"]) is not int or host_identity["pid"] <= 0
                or type(host_identity["created"]) not in {int, float}
                or not math.isfinite(host_identity["created"]) or host_identity["created"] <= 0
                or type(runner_pid) is not int or runner_pid <= 0):
            raise ValueError("workflow_recovery_host_identity_invalid")
        self.trials = trials
        self.session = trials.session
        self.host_identity = deepcopy(host_identity)
        self.runner_pid = runner_pid
        self.runner_root = self.session / "workflow-runners"

    def _inactive(self, original_pointer=None):
        pointer = original_pointer
        if pointer is None:
            pointer, _ = _snapshot(self.session.parent / "latest-session.json")
        report, _ = _snapshot(self.session / "report.json")
        if (pointer.get("name") != self.session.name
                or pointer.get("host_identity") != self.host_identity
                or report.get("runner_pid") != self.runner_pid):
            raise ValueError("workflow_recovery_host_binding_changed")
        for pid, created in ((self.host_identity["pid"], self.host_identity["created"]),
                             (self.runner_pid, None)):
            try:
                process = psutil.Process(pid)
                alive = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                if alive and (created is None or process.create_time() == created):
                    raise ValueError("workflow_recovery_process_still_running")
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except psutil.AccessDenied as error:
                raise ValueError("workflow_recovery_process_unverifiable") from error
        # 只证明原执行进程不在运行；不冒充窗口、模型或其它资源已清理。
        return {"host_identity": deepcopy(self.host_identity), "runner_pid": self.runner_pid,
                "host_not_running": True, "runner_not_running": True,
                "resources_cleanup_verified": False}

    def _inspect(self, run_id, *, original_pointer=None):
        _run_id(run_id)
        inactive = self._inactive(original_pointer)
        trial = self.trials.status(run_id)
        state, runner_hash = _snapshot(self.runner_root / (run_id + ".json"))
        active, _ = _snapshot(self.runner_root / "active.json")
        ticket, pending = state.get("ticket"), trial.get("pending")
        if (state.get("schema") != "workflow_runner.v1" or state.get("run_id") != run_id
                or active != {"schema": "workflow_runner.v1", "run_id": run_id}
                or not isinstance(ticket, dict) or not isinstance(pending, dict)
                or any(ticket.get(key) != pending.get(key) for key in
                       ("execution_request_id", "step_id", "suggested_command"))
                or trial.get("current_step_id") != pending.get("step_id")
                or state.get("current_step_id") != pending.get("step_id")
                or state.get("runner_state") in {"completed", "failed", "cancelled"}):
            raise ValueError("workflow_recovery_original_ticket_mismatch")
        program = self.trials.programs.load(trial["workflow_id"], trial["program_id"])
        if (program.get("program_id") != trial["program_id"]
                or len([step for step in program["definition"]["steps"]
                        if step["step_id"] == pending["step_id"]]) != 1):
            raise ValueError("workflow_recovery_pinned_program_mismatch")
        eid = _id(pending["execution_request_id"], "execution_request_id")
        command, command_hash = _snapshot(self.session / "commands" / (eid + ".json"))
        receipt_path = self.session / "responses" / (eid + ".json")
        acceptance, acceptance_hash = _snapshot(receipt_path)
        worker, worker_hash = _snapshot(self.session / "agent-commands" / (eid + ".json"))
        accepted = acceptance.get("result")
        if (command != pending["suggested_command"] or ticket.get("command_sha256") != _digest(command)
                or acceptance.get("command") != command or acceptance.get("status") != "returned"
                or not isinstance(accepted, dict) or accepted.get("contract_version") != "agent_command.v1"
                or accepted.get("command_id") != eid or worker.get("contract_version") != "agent_command.v1"
                or worker.get("command_id") != eid):
            raise ValueError("workflow_recovery_original_receipt_mismatch")
        if worker.get("status") not in {"completed", "failed", "cancelled"}:
            raise ValueError("workflow_recovery_not_terminal")
        for item in (accepted, worker):
            if item.get("action_executed") is not None and type(item["action_executed"]) is not bool:
                raise ValueError("workflow_recovery_action_fact_invalid")
        attempts = worker.get("dispatch_attempts", [])
        if not isinstance(attempts, list) or any(not isinstance(row, dict) for row in attempts):
            raise ValueError("workflow_recovery_dispatch_evidence_invalid")
        if worker.get("dispatch_in_progress") or any(row.get("status") != "returned"
                or row.get("action_executed") is None for row in attempts):
            raise ValueError("workflow_recovery_dispatch_not_terminal")
        if any(type(row.get("index")) is not int or row["index"] != index
               or not isinstance(row.get("operation"), str) or not row["operation"].strip()
               or type(row.get("action_executed")) is not bool
               for index, row in enumerate(attempts, 1)):
            raise ValueError("workflow_recovery_dispatch_evidence_invalid")
        if attempts:
            last = worker.get("last_execution")
            if (not isinstance(last, dict) or type(last.get("attempt_index")) is not int
                    or last["attempt_index"] != len(attempts)
                    or last.get("operation") != attempts[-1]["operation"]
                    or not isinstance(last.get("receipt"), dict)
                    or _receipt_action(last["receipt"], last["operation"]) is not attempts[-1]["action_executed"]):
                raise ValueError("workflow_recovery_dispatch_evidence_invalid")
        # 哈希与事实都来自同一次原字节读取，后续不重新打开 worker。
        context = self.trials._receipt_context(trial, pending)
        dispatched, _, _ = _receipt_state(acceptance, receipt_path, eid, command, terminal_snapshot=worker,
                                         expected_context=context)
        claims = _action_claims(accepted) + _action_claims(worker)
        action = True if any(value is True for value in claims) else (
            False if worker.get("action_executed") is False else None)
        return {"contract_version": _PREVIEW, "run_id": run_id,
                "workflow_id": trial["workflow_id"], "program_id": trial["program_id"],
                "program_sha256": program["content_sha256"], "step_id": pending["step_id"],
                "trial_state_sha256": _digest({key: value for key, value in trial.items()
                                               if key != "recovery_settlement"}),
                "execution_request_id": eid, "command_sha256": command_hash,
                "acceptance_receipt_sha256": acceptance_hash, "worker_terminal_sha256": worker_hash,
                "terminal_status": worker["status"], "action_executed": action,
                "input_route_succeeded": dispatched and action is True if context is not None else dispatched,
                **({"command_succeeded": dispatched} if context is not None else {}), "task_effect_verified": None,
                "automatic_retry_allowed": False, "inactive_processes": inactive,
                **({"runner_state_sha256": runner_hash} if "control_requests" in state else {})}

    def preview(self, run_id):
        return self._inspect(run_id)

    def status(self, run_id):
        return self._status(run_id)

    def _status(self, run_id, *, original_pointer=None):
        state = self.trials.status(_run_id(run_id))
        settlement = state.get("recovery_settlement")
        if settlement is None:
            return None
        if not isinstance(settlement, dict):
            raise ValueError("workflow_recovery_settlement_invalid")
        request_id = _id(settlement.get("request_id"), "request_id")
        preview = self._inspect(run_id, original_pointer=original_pointer)
        expected = {**preview, "contract_version": _SETTLEMENT,
                    "request_id": request_id, "status": "recovery_paused"}
        if settlement != expected:
            raise ValueError("workflow_recovery_settlement_invalid")
        return state

    def status_admitted(self, run_id, admission_record_path):
        from app.desktop_review.external_mapping import canonical_json_bytes
        from app.execution.session_resources import decode_session_resources
        try:
            path = Path(admission_record_path).resolve()
            if (path.parent != self.session.parent / "recovery-admissions"
                    or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}\.json", path.name)):
                raise ValueError("workflow_recovery_admission_path_invalid")
            record, record_hash = _snapshot(path)
            required = {"contract_version", "request_id", "preview_sha256", "preview", "new_session_name", "phase", "new_host_identity"}
            if (set(record) != required or record["contract_version"] != "session_epoch_admission.v1"
                    or record["request_id"] != path.stem or record["phase"] not in {"host_created", "pointer_published", "ready"}):
                raise ValueError("workflow_recovery_admission_invalid")
            preview = record["preview"]
            if (not isinstance(preview, dict) or set(preview) != {"contract_version", "source_session", "original_pointer_raw_utf8", "resource_proof", "input_proof", "preview_sha256"}
                    or preview["contract_version"] != "session_epoch_admission_preview.v1"
                    or not isinstance(record["preview_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", record["preview_sha256"])
                    or preview["preview_sha256"] != record["preview_sha256"]
                    or sha256(canonical_json_bytes({k: v for k, v in preview.items() if k != "preview_sha256"})).hexdigest() != record["preview_sha256"]
                    or not Path(preview["source_session"]).is_absolute() or Path(preview["source_session"]).resolve() != self.session
                    or not re.fullmatch(r"session-[0-9a-f]{32}", self.session.name)):
                raise ValueError("workflow_recovery_admission_preview_invalid")
            pointer = json.loads(preview["original_pointer_raw_utf8"])
            proof = preview["resource_proof"]
            if (not isinstance(pointer, dict) or pointer.get("name") != self.session.name
                    or pointer.get("host_identity") != self.host_identity or proof.get("contract_version") != "session_resource_cleanup.v1"
                    or proof.get("resources_cleanup_verified") is not True
                    or preview["input_proof"].get("contract_version") != "session_input_terminal.v1"
                    or preview["input_proof"].get("input_terminal_settlement_verified") is not True):
                raise ValueError("workflow_recovery_admission_binding_invalid")
            new_name, host = record["new_session_name"], record["new_host_identity"]
            if (not isinstance(new_name, str) or not re.fullmatch(r"session-[0-9a-f]{32}", new_name) or new_name == self.session.name
                    or not isinstance(host, dict) or set(host) != {"pid", "created"} or type(host["pid"]) is not int or host["pid"] <= 0
                    or type(host["created"]) not in {int, float} or not math.isfinite(host["created"]) or host["created"] <= 0):
                raise ValueError("workflow_recovery_admission_identity_invalid")
            paths = {"record": path, "pointer": self.session.parent / "latest-session.json", "report": self.session / "report.json", "resources": self.session / "session-resources.json"}
            before = {key: value.read_bytes() for key, value in paths.items()}
            if sha256(before["record"]).hexdigest() != record_hash:
                raise ValueError("workflow_recovery_admission_changed")
            expected_pointer = {"name": new_name, "host_identity": host, **{key: pointer.get(key) for key in ("recognition_source", "delegate_profile", "api_profile")}}
            def validate():
                if json.loads(before["pointer"]) != expected_pointer:
                    raise ValueError("workflow_recovery_admission_pointer_invalid")
                process = psutil.Process(host["pid"])
                if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE or process.create_time() != host["created"]:
                    raise ValueError("workflow_recovery_admission_host_inactive")
                hashes = proof["original_snapshots"]
                if (hashes["pointer"] != sha256(preview["original_pointer_raw_utf8"].encode("utf-8")).hexdigest()
                        or any(hashes[key] != sha256(before[key]).hexdigest() for key in ("report", "resources"))):
                    raise ValueError("workflow_recovery_admission_snapshot_invalid")
                journal = decode_session_resources(self.session, before["resources"])
                if (journal["host_identity"] != self.host_identity or journal["runner_identity"]["pid"] != self.runner_pid
                        or journal["runner_identity"] != proof.get("runner_identity") or proof.get("host_identity") != self.host_identity
                        or proof.get("session_name") != self.session.name or journal["recognition_source"] != pointer.get("recognition_source")
                        or proof.get("recognition_source") != journal["recognition_source"] or json.loads(before["report"]).get("runner_pid") != self.runner_pid):
                    raise ValueError("workflow_recovery_admission_binding_invalid")
            validate()
            state = self._status(run_id, original_pointer=pointer)
            if any(value.read_bytes() != before[key] for key, value in paths.items()):
                raise ValueError("workflow_recovery_admission_changed")
            validate()
            return state
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, psutil.Error) as error:
            if isinstance(error, ValueError) and str(error).startswith("workflow_recovery_"):
                raise
            raise ValueError("workflow_recovery_admission_invalid") from error

    def status_archived(self, run_id, admission_record_path, successor_admission_paths):
        """归档链仅证明只读来源，不能结算、恢复或授予新输入。"""
        from app.execution.session_admission_ancestry import inspect_admission_ancestry
        from app.execution.session_input_terminal import _catalog
        try:
            before = inspect_admission_ancestry(self.session, admission_record_path, successor_admission_paths)
            source = _catalog(self.session)
            pointer = before["original_pointer"]
            if pointer["host_identity"] != self.host_identity:
                raise ValueError("workflow_recovery_admission_binding_invalid")
            state = self._status(run_id, original_pointer=pointer)
            after = inspect_admission_ancestry(self.session, admission_record_path, successor_admission_paths)
            if after != before or _catalog(self.session) != source:
                raise ValueError("workflow_recovery_admission_changed")
            if self._status(run_id, original_pointer=pointer) != state:
                raise ValueError("workflow_recovery_admission_changed")
            if (inspect_admission_ancestry(self.session, admission_record_path, successor_admission_paths) != before
                    or _catalog(self.session) != source):
                raise ValueError("workflow_recovery_admission_changed")
            return state
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, psutil.Error) as error:
            if isinstance(error, ValueError) and str(error).startswith("workflow_recovery_"):
                raise
            raise ValueError("workflow_recovery_admission_invalid") from error

    def settle(self, preview, request_id):
        _id(request_id, "request_id")
        if not isinstance(preview, dict) or preview.get("contract_version") != _PREVIEW:
            raise ValueError("workflow_recovery_preview_invalid")
        run_id = _run_id(preview.get("run_id"))
        with _exclusive(self.runner_root / "active.lock"):
            current = self._inspect(run_id)
            if current != preview:
                raise ValueError("workflow_recovery_preview_changed")
            state = self.trials.status(run_id)
            settlement = {"contract_version": _SETTLEMENT, "request_id": request_id,
                          "status": "recovery_paused", **deepcopy(preview)}
            settlement["contract_version"] = _SETTLEMENT
            prior = state.get("recovery_settlement")
            if prior is not None:
                if prior != settlement:
                    raise ValueError("workflow_recovery_settlement_conflict")
                return state
            # 一个原子账本提交：不清原票据、不增历史、不生成 finished_at 或分支输出。
            state["recovery_settlement"] = settlement
            if self._inspect(run_id) != preview:
                raise ValueError("workflow_recovery_preview_changed")
            _write(self.trials._path(run_id), state)
            return deepcopy(state)


__all__ = ["WorkflowTerminalRecovery"]
