"""只核对原输入终态，不授予宿主或工作流接管权限。"""
import hashlib
import json
from pathlib import Path

from app.core.receipt_action import _receipt_action


_FOLDERS = ("commands", "responses", "agent-commands", "grounding", "sequence-progress", "workflow-trials", "workflow-runners", "workflow-observations")
_CONTROLS = {"agent_command_status", "agent_command_continue", "agent_command_cancel"}
_READ_ONLY = {"discover", "launch", "select", "maximize", "capture", "read_text", "prepare_models", "release_models", "close_launched_window", "desktop_capture", "grounding_prepare", "grounding_resolve", "grounding_status", "grounding_cancel", "close", "learning_start", "learning_status", "learning_stop", "learning_recover", "learning_event", "learning_review", "learning_projection", "learning_import", "learning_library", "learning_memory", "learning_save_interface", "learning_commit", "learning_project", "learning_reuse", "learning_adopt_source", "learning_template", "learning_feedback", "learning_workflow"}


def _require(value, code="unproven"):
    if not value:
        raise ValueError("session_input_" + code)


def _catalog(root):
    result, total = {}, 0
    for folder in _FOLDERS:
        base = root / folder
        if not base.exists():
            continue
        _require(base.is_dir() and base.resolve().is_relative_to(root), "path_invalid")
        for path in base.rglob("*.json"):
            _require(path.is_file() and path.resolve().is_relative_to(root), "path_invalid")
            _require(len(result) < 4096, "catalog_limit")
            _require(total + path.stat().st_size <= 64 * 1024 * 1024, "catalog_limit")
            raw = path.read_bytes()
            total += len(raw)
            _require(len(raw) <= 64 * 1024 * 1024 and total <= 64 * 1024 * 1024, "catalog_limit")
            result[path.relative_to(root).as_posix()] = raw
    for name in ("session-resources.json", "report.json"):
        path = root / name
        if path.exists():
            _require(path.is_file() and path.resolve().is_relative_to(root), "path_invalid")
            raw = path.read_bytes()
            total += len(raw)
            _require(len(result) < 4096 and total <= 64 * 1024 * 1024, "catalog_limit")
            result[name] = raw
    def frame(value):
        nonlocal total
        _require(isinstance(value, dict) and isinstance(value.get("image_path"), str)
                 and isinstance(value.get("sha256"), str) and len(value["sha256"]) == 64
                 and all(character in "0123456789abcdef" for character in value["sha256"]), "image_reference_invalid")
        path = Path(value["image_path"])
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        _require(path.is_relative_to(root) and path.suffix.lower() == ".png", "image_path_invalid")
        relative = path.relative_to(root).as_posix()
        if relative not in result:
            _require(len(result) < 4096 and total + path.stat().st_size <= 64 * 1024 * 1024, "catalog_limit")
            data = path.read_bytes()
            total += len(data)
            _require(total <= 64 * 1024 * 1024, "catalog_limit")
            result[relative] = data
        data = result[relative]
        _require(data.startswith(b"\x89PNG\r\n\x1a\n") and hashlib.sha256(data).hexdigest() == value["sha256"], "image_evidence_invalid")
    def native_frames(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"before_frame", "after_frame", "frame"} and child is not None:
                    frame(child)
                elif isinstance(child, (dict, list)):
                    native_frames(child)
        elif isinstance(value, list):
            for child in value:
                native_frames(child)
    # 只闭合原业务引用，不扫描截图缓存或学习资产。
    for relative, raw in list(result.items()):
        value = _json(raw)
        if relative.startswith(("responses/", "agent-commands/")):
            # 原选择证明的两张图闭合到同一目录清单，不扫描截图缓存。
            def selection_frames(item):
                if isinstance(item, dict):
                    proof = item.get("row_selection_proof")
                    if isinstance(proof, dict) and proof.get("contract_version") == "row_selection_effect.v1":
                        for stage in ("before", "after"):
                            frame((proof.get(stage) or {}).get("frame"))
                    for child in item.values():
                        selection_frames(child)
                elif isinstance(item, list):
                    for child in item:
                        selection_frames(child)
            selection_frames(value)
        if relative.startswith("workflow-observations/") and value.get("contract_version") == "workflow_observation.v1":
            frame(value.get("frame"))
            native_frames(value.get("native_evidence"))
        elif relative.startswith("workflow-trials/"):
            for entry in value.get("history", []):
                if isinstance(entry, dict) and entry.get("read_observation") is not None:
                    frame(entry["read_observation"])
        elif relative.startswith("responses/") and (value.get("command") or {}).get("kind") == "read_text":
            capture = value.get("observation")
            if not isinstance(capture, dict):
                capture = (value.get("result") or {}).get("capture")
            if capture is not None:
                frame(capture)
    return result


def _json(raw):
    value = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("session_input_json_invalid")))
    _require(isinstance(value, dict), "json_invalid")
    return value


def _worker(worker, eid):
    _require(worker.get("contract_version") == "agent_command.v1" and worker.get("command_id") == eid, "worker_binding")
    _require(worker.get("status") in {"completed", "failed", "cancelled"}, "worker_not_terminal")
    _require(type(worker.get("action_executed")) is bool and worker.get("dispatch_in_progress") is False, "dispatch_unknown")
    attempts = worker.get("dispatch_attempts")
    _require(isinstance(attempts, list), "dispatch_invalid")
    for index, row in enumerate(attempts, 1):
        _require(isinstance(row, dict) and type(row.get("index")) is int and row["index"] == index
                 and isinstance(row.get("operation"), str) and bool(row["operation"].strip())
                 and row.get("status") == "returned" and type(row.get("action_executed")) is bool, "dispatch_unknown")
    if attempts:
        last = worker.get("last_execution")
        _require(isinstance(last, dict) and type(last.get("attempt_index")) is int and last["attempt_index"] == len(attempts)
                 and last.get("operation") == attempts[-1]["operation"] and isinstance(last.get("receipt"), dict)
                 and _receipt_action(last["receipt"], last["operation"]) is attempts[-1]["action_executed"], "dispatch_receipt_invalid")
    _require(not any(row["action_executed"] is True for row in attempts) or worker["action_executed"] is True, "action_downgraded")
    return worker["status"], worker["action_executed"]


def _batch(result, kind):
    _require(result.get("contract_version") == ("input_sequence_v1" if kind == "input_sequence" else "form_fill_v1")
             and result.get("status") in {"completed", "interrupted"} and type(result.get("action_executed")) is bool, "batch_unknown")
    rows = result.get("steps") if kind == "input_sequence" else result.get("fields")
    _require(isinstance(rows, list), "batch_invalid")
    steps = rows if kind == "input_sequence" else []
    if kind == "form_fill":
        for field in rows:
            _require(isinstance(field, dict) and isinstance(field.get("steps"), list), "batch_invalid")
            steps.extend(field["steps"])
    for row in steps:
        _require(isinstance(row, dict) and type(row.get("action_executed")) is bool
                 and row.get("status") == "returned" and isinstance(row.get("receipt"), dict)
                 and row["receipt"].get("phase") == "returned"
                 and _receipt_action(row["receipt"], row.get("operation", "execute_recognition_plan")) is row["action_executed"], "batch_unknown")
    _require(not any(row["action_executed"] is True for row in steps) or result["action_executed"] is True, "action_downgraded")
    return result["status"], result["action_executed"]


def _continued_grounding_action(worker, command, receipt):
    attempts = worker["dispatch_attempts"]
    last = worker.get("last_execution")
    if len(attempts) == 1:
        _require(last["operation"] == "execute_recognition_plan" and last["receipt"] == receipt,
                 "grounding_continue_terminal_unproven")
        return 1, attempts[0]["action_executed"]
    # 批次只有完整、有序且唯一的原回执才能证明较早派发；缺失时仍拒绝。
    kind, batch = command.get("kind"), worker.get("result")
    _require(kind in {"input_sequence", "form_fill"} and isinstance(batch, dict),
             "grounding_continue_terminal_unproven")
    _, action = _batch(batch, kind)
    _require(action is worker["action_executed"], "grounding_continue_action_unproven")
    rows = batch["steps"] if kind == "input_sequence" else [
        row for field in batch["fields"] for row in field["steps"]]
    _require(len(rows) == len(attempts) and bool(rows), "grounding_continue_terminal_unproven")
    hashes = [hashlib.sha256(json.dumps(row["receipt"], ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest() for row in rows]
    _require(len(set(hashes)) == len(rows), "grounding_continue_terminal_unproven")
    native_ids = [row["receipt"].get("step_id") for row in rows]
    _require(all(isinstance(identity, str) and identity.strip() for identity in native_ids)
             and len(set(native_ids)) == len(rows), "grounding_continue_terminal_unproven")
    for row, attempt in zip(rows, attempts):
        _require(row.get("operation") == attempt["operation"]
                 and row["receipt"].get("contract_version") == "local_direct_step_v1"
                 and row["receipt"].get("operation") == row["operation"]
                 and row["action_executed"] is attempt["action_executed"], "grounding_continue_terminal_unproven")
    _require(last["receipt"] == rows[-1]["receipt"], "grounding_continue_terminal_unproven")
    matched = [(index, row) for index, row in enumerate(rows, 1)
               if row["operation"] == "execute_recognition_plan" and row["receipt"] == receipt]
    _require(len(matched) == 1, "grounding_continue_terminal_unproven")
    return matched[0][0], matched[0][1]["action_executed"]


def inspect_session_input_terminal(session_dir, library_root, *, admission_record_path=None, current_workflow_control=None):
    root = Path(session_dir).resolve()
    _require(Path(library_root).resolve() == root.parent / "memory-library", "library_binding")
    try:
        raw = _catalog(root)
        values = {path: _json(data) for path, data in raw.items() if path.endswith(".json")}
        commands = {Path(path).stem: value for path, value in values.items() if path.startswith("commands/")}
        current_id = None
        if current_workflow_control is not None:
            binding = current_workflow_control
            _require(isinstance(binding, dict) and set(binding) == {"request_id", "command_sha256"}, "current_control_invalid")
            current_id = binding["request_id"]
            _require(isinstance(current_id, str) and current_id in commands, "current_control_invalid")
            current = commands[current_id]
            _require(current.get("kind") == "learning_workflow"
                     and (current.get("request") or {}).get("action") in {"takeover_preview", "takeover_commit"}
                     and binding["command_sha256"] == hashlib.sha256(raw["commands/" + current_id + ".json"]).hexdigest(),
                     "current_control_invalid")
            from app.learning_memory.workflow_control import validate_request
            validate_request(current["request"])
        _require(all(path.count("/") == 1 for path in values if path.startswith(("commands/", "responses/", "agent-commands/"))), "catalog_layout")
        results, deferred_controls = {}, {}
        def input_result(eid):
            if eid in results:
                return results[eid]
            _require(eid in commands, "command_missing")
            command = commands[eid]
            kind = command.get("kind")
            response = values.get("responses/" + eid + ".json")
            if response is None and eid == current_id:
                results[eid] = {"kind": kind, "terminal_status": "current_takeover_control", "action_executed": None}
                return results[eid]
            if response is None and kind == "close":
                results[eid] = {"kind": kind, "terminal_status": "owner_exited_without_close_response", "action_executed": None}
                return results[eid]
            if (response is None and kind == "learning_workflow" and isinstance(command.get("request"), dict)
                    and command["request"].get("action") in {"run", "continue"}):
                from app.learning_memory.workflow_control import validate_request
                validate_request(command["request"])
                deferred_controls[eid] = command
                return None
            _require(isinstance(response, dict) and response.get("command") == command
                     and response.get("status") in {"returned", "failed"}, "response_unproven")
            result = response.get("result") or {}
            _require(isinstance(result, dict), "result_invalid")

            if result.get("contract_version") == "vision_admission_rejection.v1":
                from app.execution.session_resources import decode_session_resources
                from app.vision.recognition_source import RecognitionSourceConfig, ClientVisionCapabilities, resolve_recognition_route
                from app.core.vision_admission_contract import AgentCommandVisionAdmissionError
                _require(kind in {"step", "input_sequence", "form_fill"}
                         and (kind != "step" or command.get("operation") == "execute_recognition_plan")
                         and response.get("status") == "failed"
                         and response.get("error_type") == "AgentCommandVisionAdmissionError"
                         and "agent-commands/" + eid + ".json" not in values,
                         "vision_admission_unproven")
                _require("session-resources.json" in raw and "report.json" in values,
                         "vision_admission_source_missing")
                journal = decode_session_resources(root, raw["session-resources.json"])
                report = values["report.json"]
                _require({"recognition_source", "delegate_profile", "api_profile"} <= set(report),
                         "vision_admission_source_missing")
                configuration = RecognitionSourceConfig.model_validate({
                    "source": journal["recognition_source"],
                    "delegate_profile": report["delegate_profile"], "api_profile": report["api_profile"]})
                _require(report["recognition_source"] == configuration.source,
                         "vision_admission_source_mismatch")
                capabilities = ClientVisionCapabilities.model_validate(command.get("vision_capabilities") or {})
                route = resolve_recognition_route(configuration, capabilities)
                _require(route.status == "unavailable" and response.get("error") == route.code,
                         "vision_admission_route_available")
                expected = AgentCommandVisionAdmissionError(eid, command, configuration, capabilities, route.code).before_dispatch_result(eid)
                _require(result == expected and result.get("input_attempted") is False
                         and result.get("action_executed") is False, "vision_admission_unproven")
                # capability_unknown 的有效 memory 引用仍走原例外，不能伪造拒绝。
                if route.code == "capability_unknown" and kind in {"step", "input_sequence"}:
                    from app.learning_memory.target_recipe import validate_target_reference
                    try:
                        validate_target_reference((command.get("request") or {}).get("target_memory"))
                    except ValueError:
                        pass
                    else:
                        _require(False, "vision_admission_memory_exception")
                results[eid] = {"kind": kind, "terminal_status": "failed", "action_executed": False}
                return results[eid]
            if (response.get("error_type") == "AgentCommandAdmissionError"
                    or response.get("error") == "agent_command_in_progress: continue, inspect or cancel the original command"):
                _require(result.get("contract_version") == "input_admission_rejection.v1",
                         "admission_rejection_unproven")
            if result.get("contract_version") == "input_admission_rejection.v1":
                # 只接受真实前派发门控的专用回执；普通失败和旧字符串错误仍是未知。
                from app.execution.agent_command_admission import requires_idle_agent
                _require(kind in (_READ_ONLY | {"step", "desktop_click", "input_sequence", "form_fill", "grounding_execute"})
                         and requires_idle_agent(kind, command)
                         and response.get("status") == "failed"
                         and response.get("error_type") == "AgentCommandAdmissionError"
                         and response.get("error") == "agent_command_in_progress: continue, inspect or cancel the original command"
                         and result == {"contract_version": "input_admission_rejection.v1", "command_id": eid,
                             "status": "rejected_before_dispatch", "reason": "agent_command_in_progress",
                             "input_attempted": False, "action_executed": False}
                         and result.get("input_attempted") is False and result.get("action_executed") is False
                         and "agent-commands/" + eid + ".json" not in values, "admission_rejection_unproven")
                results[eid] = {"kind": kind, "terminal_status": "failed", "action_executed": False}
                return results[eid]
            if kind in _CONTROLS:
                request = command.get("request") or {}
                original = request.get("command_id")
                if kind == "agent_command_status" and response.get("error") == "command_unknown":
                    # 查询缺席只指 worker；原队列命令仍须独立核对终态。
                    from app.vision.agent_command_contract import AgentCommandReference
                    reference = AgentCommandReference.model_validate(request)
                    _require(set(command) == {"kind", "request"}
                             and reference.command_id != eid
                             and "agent-commands/" + reference.command_id + ".json" not in values
                             and response.get("status") == "failed"
                             and response.get("error_type") == "AgentCommandError"
                             and response.get("automatic_retry_allowed") is False
                             and response.get("result") is None and response.get("observation") is None
                             and response.get("action_executed") is None, "control_binding")
                    if reference.command_id in commands:
                        _require(commands[reference.command_id].get("kind") not in _CONTROLS, "control_binding")
                        original_result = input_result(reference.command_id)
                        _require(isinstance(original_result, dict)
                                 and reference.command_id not in deferred_controls
                                 and original_result.get("terminal_status") in {"returned", "failed", "completed", "cancelled"},
                                 "control_binding")
                    results[eid] = {"kind": kind, "terminal_status": "unknown_command_readonly",
                                    "action_executed": None, "referenced_command_id": reference.command_id}
                    return results[eid]
                _require(isinstance(original, str) and original != eid and original in commands
                         and commands[original].get("kind") not in _CONTROLS
                         and result.get("contract_version") == "agent_command.v1" and result.get("command_id") == original, "control_binding")
                input_result(original)
                return None
            if result.get("contract_version") == "agent_command.v1":
                _require(kind in {"step", "desktop_click", "input_sequence", "form_fill"}
                         and result.get("command_id") == eid, "acceptance_binding")
                worker = values.get("agent-commands/" + eid + ".json")
                _require(isinstance(worker, dict), "worker_missing")
                status, action = _worker(worker, eid)
                _require(result.get("action_executed") is not True or action is True, "action_downgraded")
            elif kind in {"step", "desktop_click"}:
                operation = command.get("operation") if kind == "step" else "execute_recognition_plan"
                action = _receipt_action(result, operation)
                data = (result.get("response") or {}).get("data") or {}
                rejected_scroll = (operation == "scroll" and result.get("operation") == "scroll"
                    and result.get("contract_version") == "local_direct_step_v1"
                    and result.get("phase") == "not_dispatched"
                    and result.get("response", {}).get("success") is False
                    and (result.get("response", {}).get("error") or {}).get("code") == "scroll_precondition_rejected"
                    and data.get("dispatch_status") == "not_dispatched" and data.get("scrolled") is False
                    and data.get("input_started") is False
                    and (data.get("precondition_decision") or {}).get("decision") == "REJECT"
                    and action in (None, False))
                if rejected_scroll:
                    # 完整前置拒绝证明无输入，不将旧未知回执降级为未派发。
                    status, action = "not_dispatched", False
                    results[eid] = {"kind": kind, "terminal_status": status, "action_executed": action}
                    return results[eid]
                _require(result.get("phase") == "returned" and type(action) is bool, "synchronous_unknown")
                status = "completed" if response["status"] == "returned" else "failed"
            elif kind in {"input_sequence", "form_fill"}:
                status, action = _batch(result, kind)
            elif kind == "grounding_execute":
                request = command.get("request") or {}
                state = values.get("grounding/" + str(request.get("grounding_request_id")) + ".json")
                action = _receipt_action(result, "execute_recognition_plan")
                _require(isinstance(state, dict) and state.get("contract_version") == "grounding_handoff.v1"
                         and state.get("request_id") == request.get("grounding_request_id") and state.get("execution_id") == eid
                         and state.get("phase") == "completed" and state.get("execution_result") == result
                         and type(state.get("input_attempted")) is bool
                         and (result.get("phase") == "returned"
                              or result.get("phase") == "returned_observation_unavailable"
                              and result.get("contract_version") == "local_direct_step_v1"
                              and result.get("operation") == "execute_recognition_plan") and type(action) is bool
                         and state.get("input_dispatched") is (None if state["input_attempted"] else False)
                         and (state["input_attempted"] or action is False), "grounding_unknown")
                status = "completed"
            else:
                _require(kind in _READ_ONLY, "kind_unknown")
                status, action = response["status"], None
            results[eid] = {"kind": kind, "terminal_status": status, "action_executed": action}
            return results[eid]
        for eid in commands:
            input_result(eid)
        grounded_dispatches = set()
        for path in values:
            if path.startswith("responses/"):
                _require(Path(path).stem in commands, "orphan_response")
            if path.startswith("sequence-progress/"):
                _require(Path(path).stem in commands and commands[Path(path).stem].get("kind") in {"input_sequence", "form_fill"}, "orphan_progress")
            if path.startswith("grounding/") and values[path].get("execution_id") is not None:
                eid = values[path]["execution_id"]
                _require(isinstance(eid, str) and eid in commands
                         and (commands[eid].get("request") or {}).get("grounding_request_id") == values[path].get("request_id"), "orphan_grounding_execution")
                if commands[eid].get("kind") == "agent_command_continue":
                    grounding = values[path]
                    original_id = commands[eid]["request"].get("command_id")
                    worker = values.get("agent-commands/" + str(original_id) + ".json")
                    response = values.get("responses/" + eid + ".json")
                    _require(isinstance(response, dict) and response.get("status") == "returned"
                             and response.get("command") == commands[eid]
                             and isinstance(response.get("result"), dict)
                             and response["result"].get("contract_version") == "agent_command.v1"
                             and response["result"].get("command_id") == original_id
                             and isinstance(worker, dict) and original_id in results,
                             "grounding_continue_binding")
                    _worker(worker, original_id)
                    receipt = grounding.get("execution_result")
                    _require(grounding.get("contract_version") == "grounding_handoff.v1"
                             and Path(path).stem == grounding.get("request_id")
                             and grounding.get("phase") == "completed"
                             and type(grounding.get("input_attempted")) is bool
                             and grounding.get("input_dispatched") is (None if grounding["input_attempted"] else False)
                             and isinstance(receipt, dict) and (receipt.get("phase") == "returned"
                                 or receipt.get("phase") == "returned_observation_unavailable"
                                 and receipt.get("contract_version") == "local_direct_step_v1"
                                 and receipt.get("operation") == "execute_recognition_plan")
                             and bool(worker["dispatch_attempts"]),
                             "grounding_continue_terminal_unproven")
                    attempt_index, dispatch_action = _continued_grounding_action(worker, commands[original_id], receipt)
                    dispatch_identity = (original_id, attempt_index)
                    _require(dispatch_identity not in grounded_dispatches, "grounding_dispatch_claim_duplicate")
                    grounded_dispatches.add(dispatch_identity)
                    action = _receipt_action(receipt, "execute_recognition_plan")
                    _require(type(action) is bool
                             and action is dispatch_action
                             and (grounding["input_attempted"] or action is False),
                             "grounding_continue_action_unproven")
                else:
                    _require(commands[eid].get("kind") == "grounding_execute", "orphan_grounding_execution")
            if path.startswith("agent-commands/"):
                eid = Path(path).stem
                _require(eid in commands and (values.get("responses/" + eid + ".json", {}).get("result") or {}).get("contract_version") == "agent_command.v1", "orphan_worker")
                _worker(values[path], eid)
        settlements, settled_trials = {}, {}
        trials = {Path(path).stem: value for path, value in values.items() if path.startswith("workflow-trials/trial-") and path.count("/") == 1}
        for path, runner in values.items():
            if path.startswith("workflow-runners/") and isinstance(runner.get("ticket"), dict):
                trial = trials.get(runner.get("run_id"))
                _require(isinstance(trial, dict) and isinstance(trial.get("pending"), dict)
                         and all(runner["ticket"].get(key) == trial["pending"].get(key) for key in ("execution_request_id", "step_id", "suggested_command")), "runner_ticket_binding")
        for run, trial in trials.items():
            _require(trial.get("run_id") == run, "trial_binding")
        if any(trial.get("pending") is not None for trial in trials.values()):
            from app.learning_memory.workspace import MemoryWorkspace
            from app.learning_memory.workflow_trial import TrialService
            from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
            library = Path(library_root).resolve()
            lock = library / "desktop-review" / ".owner.lock"
            _require(lock.is_file() and lock.stat().st_size > 0 and lock.resolve().is_relative_to(library), "library_unavailable")
            if admission_record_path is None:
                pointer = _json((root.parent / "latest-session.json").read_bytes())
            else:
                record_path = Path(admission_record_path).resolve()
                _require(record_path.parent == root.parent / "recovery-admissions", "admission_path_invalid")
                record = _json(record_path.read_bytes())
                pointer = _json(record["preview"]["original_pointer_raw_utf8"].encode("utf-8"))
            report = _json((root / "report.json").read_bytes())
            with MemoryWorkspace(library) as workspace:
                service = WorkflowTerminalRecovery(TrialService(workspace, root), host_identity=pointer.get("host_identity"), runner_pid=report.get("runner_pid"))
                for run, trial in trials.items():
                    _require(trial.get("run_id") == run, "trial_binding")
                    if trial.get("pending") is not None:
                        state = service.status(run) if admission_record_path is None else service.status_admitted(run, admission_record_path)
                        _require(state is not None, "workflow_unsettled")
                        settled_trials[run] = state
                        settlements[run] = hashlib.sha256(json.dumps(state["recovery_settlement"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        # 缺外层响应只凭原接受来源与固定结算闭合，不推定业务成功。
        for eid, command in deferred_controls.items():
            request = command["request"]
            run = request["run_id"]
            _require(run in settled_trials, "workflow_control_unsettled")
            runner_path = "workflow-runners/" + run + ".json"
            runner = values.get(runner_path)
            settlement = settled_trials[run]["recovery_settlement"]
            _require(isinstance(runner, dict) and runner.get("run_id") == run
                     and settlement.get("runner_state_sha256") == hashlib.sha256(raw[runner_path]).hexdigest(),
                     "workflow_control_origin_unproven")
            command_hash = hashlib.sha256(json.dumps(command, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
            controls = runner.get("control_requests")
            _require(isinstance(controls, dict) and controls.get(eid) == {
                "schema": "workflow_runner_control.v1", "command_sha256": command_hash}, "workflow_control_origin_unproven")
            if request["action"] == "run":
                _require(runner.get("start_request_id") == eid and runner.get("mode") == request["mode"],
                         "workflow_control_binding")
            else:
                _require(isinstance(runner.get("resume_requests"), dict)
                         and runner["resume_requests"].get(eid) == request["wait_id"], "workflow_control_binding")
            original = results.get(settlement["execution_request_id"])
            _require(isinstance(original, dict) and original["terminal_status"] == settlement["terminal_status"]
                     and type(original["action_executed"]) is bool
                     and original["action_executed"] is settlement["action_executed"], "workflow_control_input_unproven")
            results[eid] = {"kind": "learning_workflow", "terminal_status": "recovery_settled_control",
                "action_executed": None, "response_returned": False, "run_id": run,
                "execution_request_id": settlement["execution_request_id"], "control_command_sha256": command_hash,
                "runner_state_sha256": settlement["runner_state_sha256"], "settlement_sha256": settlements[run]}
        _require(_catalog(root) == raw, "catalog_changed")
        files = {path: hashlib.sha256(data).hexdigest() for path, data in sorted(raw.items())}
        digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {"contract_version": "session_input_terminal.v1", "catalog_sha256": digest, "files": files,
                "commands": results, "workflow_settlements": settlements, "input_terminal_settlement_verified": True}
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, ValueError) and str(error).startswith("session_input_"):
            raise
        raise ValueError("session_input_evidence_invalid") from error
