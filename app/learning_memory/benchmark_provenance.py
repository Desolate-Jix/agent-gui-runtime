"""正式基准的定义来源及本轮证据审计，不改变普通试跑权限。"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import base64
import binascii
from io import BytesIO
from pathlib import Path, PurePosixPath

from PIL import Image

from .workflow_program import _digest, _id, _WORKFLOW, _PROGRAM, _HASH
from .receipt_adapter import content_hash
from .target_recipe import validate_target_reference
from .workflow_verification import KINDS, verify_step
from .workflow_trial import _execution_identity, _command, _selection_context, _actual_action_executed, _conditions


_FIELDS = {"workflow_id", "program_id", "content_sha256", "project_snapshot_id", "start_step_id",
           "artifact_path", "target_memory_steps", "rule_verification_steps"}


def validate_binding(binding: dict) -> dict:
    """只检查描述符；冻结文件归属由采集清单负责。"""
    if not isinstance(binding, dict) or set(binding) != _FIELDS:
        raise ValueError("benchmark_binding_fields_invalid")
    for key, pattern in (("workflow_id", _WORKFLOW), ("program_id", _PROGRAM), ("content_sha256", _HASH)):
        _id(binding[key], "benchmark_" + key, pattern)
    for key in ("start_step_id", "project_snapshot_id"):
        _id(binding[key], "benchmark_" + key)
    if (not isinstance(binding["artifact_path"], str) or not Path(binding["artifact_path"]).is_absolute()):
        raise ValueError("benchmark_artifact_path_invalid")
    for key in ("target_memory_steps", "rule_verification_steps"):
        values = binding[key]
        if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
            raise ValueError("benchmark_binding_coverage_invalid")
        for value in values:
            _id(value, "benchmark_step_id")
    return deepcopy(binding)


def inspect_program(binding: dict, program: dict) -> dict:
    """只为正式对照检查已保存版本的可达定义，不提供输入授权。"""
    validate_binding(binding)
    fields = {"workflow_id", "project_snapshot_id", "revision", "definition", "program_id", "content_sha256", "review_items"}
    if not isinstance(program, dict) or set(program) != fields:
        raise ValueError("benchmark_saved_program_invalid")
    body = {key: value for key, value in program.items() if key not in {"program_id", "content_sha256", "review_items"}}
    digest = _digest(body)
    if program["content_sha256"] != digest or program["program_id"] != "task-program-" + digest:
        raise ValueError("benchmark_program_hash_mismatch")
    if any(program[key] != binding[key] for key in ("workflow_id", "program_id", "content_sha256", "project_snapshot_id")):
        raise ValueError("benchmark_program_identity_mismatch")
    definition = program.get("definition")
    if not isinstance(definition, dict) or not isinstance(definition.get("steps"), list):
        raise ValueError("benchmark_definition_invalid")
    steps = {}
    for step in definition["steps"]:
        if not isinstance(step, dict):
            raise ValueError("benchmark_step_invalid")
        identity = _id(step.get("step_id"), "benchmark_step_id")
        if identity in steps:
            raise ValueError("benchmark_duplicate_step")
        branches = step.get("branches")
        if not isinstance(branches, dict) or set(branches) != {"success", "failure", "uncertain"}:
            raise ValueError("benchmark_branches_invalid")
        steps[identity] = step
    if binding["start_step_id"] not in steps:
        raise ValueError("benchmark_start_step_unknown")
    visiting, visited = set(), set()
    def visit(identity):
        if identity not in steps:
            raise ValueError("benchmark_dangling_branch")
        if identity in visiting:
            raise ValueError("benchmark_branch_cycle")
        if identity in visited:
            return
        visiting.add(identity)
        for target in steps[identity]["branches"].values():
            if target is not None:
                if not isinstance(target, str):
                    raise ValueError("benchmark_branch_invalid")
                visit(target)
        visiting.remove(identity)
        visited.add(identity)
    visit(binding["start_step_id"])
    reachable = sorted(visited)
    # 未到达步骤不参与审核计数，但整个保存图仍须结构合法。
    for identity in steps:
        visit(identity)
    targets, rules = [], []
    for identity in reachable:
        step = steps[identity]
        if step.get("review_status") != "reviewed":
            raise ValueError("benchmark_reachable_review_pending")
        action = step.get("action")
        if not isinstance(action, dict):
            raise ValueError("benchmark_action_invalid")
        if action.get("kind") in {"click", "input_sequence"}:
            if "target_memory" not in action:
                raise ValueError("benchmark_target_memory_missing")
            validate_target_reference(action["target_memory"])
            targets.append(identity)
        verification = step.get("verification")
        if verification is not None:
            if not isinstance(verification, dict) or verification.get("kind") not in KINDS:
                raise ValueError("benchmark_verification_invalid")
            if verification["kind"] != "agent_judgment" or verification.get("image_check") is not None:
                if verification.get("image_check") is not None:
                    from .image_verification import validate_image_check
                    validate_image_check(verification["image_check"])
                    if verification["kind"] != "agent_judgment" or step.get("outputs") or "read_spec" in step or action.get("kind") == "read_text":
                        raise ValueError("benchmark_image_check_step_invalid")
                rules.append(identity)
    if sorted(binding["target_memory_steps"]) != targets or sorted(binding["rule_verification_steps"]) != rules:
        raise ValueError("benchmark_declared_coverage_mismatch")
    return {"reachable_step_ids": reachable, "reviewed_step_ids": reachable,
            "target_memory_steps": targets, "rule_verification_steps": rules, "program": deepcopy(program)}


def _files(evidence_files):
    if not isinstance(evidence_files, list):
        raise ValueError("benchmark_evidence_files_invalid")
    files = {}
    for item in evidence_files:
        if not isinstance(item, dict) or set(item) not in ({"ref", "sha256", "text"}, {"ref", "sha256", "data_base64"}):
            raise ValueError("benchmark_evidence_file_invalid")
        ref = item["ref"]
        if (not isinstance(ref, str) or not ref or ":" in ref or "\\" in ref or PurePosixPath(ref).is_absolute()
                or ".." in PurePosixPath(ref).parts or ref in files):
            raise ValueError("benchmark_evidence_reference_invalid")
        if "text" in item:
            if not isinstance(item["text"], str):
                raise ValueError("benchmark_evidence_text_invalid")
            raw = item["text"].encode("utf-8")
        else:
            try:
                raw = base64.b64decode(item["data_base64"], validate=True)
            except (ValueError, TypeError, binascii.Error) as error:
                raise ValueError("benchmark_evidence_base64_invalid") from error
        if sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("benchmark_evidence_hash_mismatch")
        files[ref] = {**item, "raw": raw}
    return files


def _lookup_ref(ref, error="benchmark_evidence_reference_invalid"):
    # 仅规范化只读索引，原观察及其哈希仍按原字节比较。
    if not isinstance(ref, str) or not ref:
        raise ValueError(error)
    normalized = ref.replace("\\", "/")
    path = PurePosixPath(normalized)
    if ":" in normalized or path.is_absolute() or ".." in path.parts or str(path) == ".":
        raise ValueError(error)
    return path.as_posix()


def _json(files, ref):
    ref = _lookup_ref(ref)
    if ref not in files:
        raise ValueError("benchmark_evidence_missing:" + ref)
    if "text" not in files[ref]:
        raise ValueError("benchmark_evidence_json_missing")
    value = json.loads(files[ref]["text"])
    if not isinstance(value, dict):
        raise ValueError("benchmark_evidence_json_invalid")
    return value


def _effective(files, entry):
    execution = _id(entry.get("execution_request_id"), "benchmark_execution_id")
    command = _json(files, "commands/" + execution + ".json")
    response_ref = "responses/" + execution + ".json"
    response = _json(files, response_ref)
    if entry.get("receipt_sha256") != files[response_ref]["sha256"] or response.get("request_id", execution) != execution or response.get("command") != command:
        raise ValueError("benchmark_original_receipt_mismatch")
    result = response.get("result")
    terminal = entry.get("terminal_receipt")
    if isinstance(result, dict) and result.get("contract_version") == "agent_command.v1":
        ref = "agent-commands/" + execution + ".json"
        actual = _json(files, ref)
        if (result.get("command_id") != execution or actual.get("command_id") != execution
                or actual.get("contract_version") != "agent_command.v1" or actual.get("status") not in {"completed", "failed", "cancelled"}
                or not isinstance(terminal, dict) or terminal.get("sha256") != content_hash(actual)
                or terminal.get("hash_scope") != "canonical_json" or terminal.get("status") != actual["status"]
                or not isinstance(terminal.get("path"), str) or not terminal["path"].replace("\\", "/").endswith("/" + ref)):
            raise ValueError("benchmark_terminal_receipt_mismatch")
        result = actual.get("result")
    elif terminal is not None:
        raise ValueError("benchmark_unexpected_terminal_receipt")
    if not isinstance(result, dict):
        raise ValueError("benchmark_execution_result_missing")
    return execution, command, result, response_ref


def _local_report(command, result):
    if command.get("kind") == "input_sequence":
        focus = [row for row in result.get("steps", []) if row.get("name") == "focus" and row.get("operation") == "execute_recognition_plan"]
        if len(focus) != 1:
            raise ValueError("benchmark_focus_receipt_missing")
        result = focus[0].get("receipt")
    if not isinstance(result, dict) or result.get("contract_version") != "local_direct_step_v1":
        raise ValueError("benchmark_local_receipt_missing")
    return result


def _selection_coverage(files, step, trial, entry, execution, command, report, outputs):
    from .selection_satisfaction import validate_selection_receipt
    context = _selection_context({**trial, "outputs": outputs}, step, command, execution)
    proof = report.get("row_selection_proof") or {}
    source = proof.get("binding", {}).get("session_directory")
    if not isinstance(source, str) or not Path(source).is_absolute():
        raise ValueError("benchmark_selection_source_missing")
    root = Path(source).resolve()
    def capture_bytes(path):
        ref = Path(path).relative_to(root).as_posix()
        item = files.get(ref)
        if not isinstance(item, dict) or "data_base64" not in item:
            raise ValueError("benchmark_selection_image_missing")
        return item["raw"]
    actual = _actual_action_executed(report)
    if (type(actual) is not bool or not validate_selection_receipt(report, command["request"],
            command=command, action_executed=actual, expected_context=context,
            session_dir=root, capture_loader=capture_bytes)
            or entry.get("command_succeeded") is not True
            or entry.get("action_executed") is not actual
            or entry.get("input_route_succeeded") is not actual
            or entry.get("selection_proof_sha256") != proof.get("sha256")):
        raise ValueError("benchmark_selection_receipt_unproven")
    if entry.get("terminal_receipt") is not None:
        terminal = _json(files, "agent-commands/" + execution + ".json")
        if terminal.get("status") != "completed" or terminal.get("action_executed") is not actual:
            raise ValueError("benchmark_selection_terminal_mismatch")
    original = _json(files, "responses/" + execution + ".json")
    if original.get("status") != "returned":
        raise ValueError("benchmark_selection_receipt_unproven")
    # 原动作效果不能代替程序的业务条件；归档须重算当时的有效结论。
    judge = entry.get("judged_by")
    verdict = entry.get(str(judge) + "_verdict")
    submitted = (entry.get("review_request") or {}).get("submitted_outputs")
    observations = entry.get("observations")
    if (verdict not in {"success", "failure", "uncertain"} or not isinstance(submitted, dict)
            or not isinstance(observations, dict)):
        raise ValueError("benchmark_selection_review_missing")
    if judge == "rule":
        verification = entry.get("verification") or {}
        if (observations != verification.get("observations", {}).get("values", {})
                or submitted != verification.get("outputs")):
            raise ValueError("benchmark_selection_review_mismatch")
    condition = _conditions(step["success_conditions"], trial.get("inputs", {}),
        {**outputs, **{step["step_id"] + "." + key: value for key, value in submitted.items()}}, observations)
    effective_verdict = (verdict if verdict != "success" else "success" if condition == "true"
                         else "failure" if condition == "false" else "uncertain")
    if (entry.get("condition_result") != condition or entry.get("verdict") != effective_verdict
            or entry.get("outputs") != (submitted if effective_verdict == "success" else {})):
        raise ValueError("benchmark_selection_business_condition_mismatch")
    return actual


def _target(step, command, result, inputs, outputs, *, selection_validated=False):
    reference = step["action"]["target_memory"]
    expected = _command(step, inputs, outputs)
    base = deepcopy(command)
    base.pop('vision_capabilities', None)
    if base != expected:
        raise ValueError("benchmark_action_semantics_mismatch")
    if (command.get("request") or {}).get("target_memory") != reference:
        raise ValueError("benchmark_target_reference_mismatch")
    report = _local_report(command, result)
    resolution = report.get("memory_resolution")
    if not isinstance(resolution, dict) or resolution.get("reference") != reference:
        raise ValueError("benchmark_memory_resolution_missing")
    state = resolution.get("status")
    if state in {"miss", "ambiguous", "unsupported"}:
        return state
    if state != "matched":
        raise ValueError("benchmark_memory_resolution_invalid")
    if (resolution.get("context_verified") is not True or (resolution.get("frame") or {}).get("window_identity") != _execution_identity({"result": report})):
        raise ValueError("benchmark_memory_window_unverified")
    data = (report.get("response") or {}).get("data") or {}
    action = data.get("result", data)
    executed = (action.get("execution_path") or {}).get("action_executed")
    if executed is False:
        return "memory_selection_satisfied" if selection_validated else "not_executed"
    plan = action.get("recognition_plan") or {}
    memory = plan.get("memory_evidence") or {}
    candidate = plan.get("recommended_target") or {}
    freshness = candidate.get("freshness") or {}
    if (executed is not True or plan.get("contract_version") != "memory_recognition_plan_v1"
            or plan.get("goal") != step["action"].get("field_goal", step["action"].get("goal"))
            or memory.get("reference") != reference or memory.get("context_verified") is not True
            or not isinstance(memory.get("capture_id"), str) or not memory["capture_id"]
            or candidate.get("capture_id") != memory["capture_id"]
            or not isinstance(memory.get("sha256"), str) or not _HASH.fullmatch(memory["sha256"])
            or freshness.get("status") != "current_recipe_revalidated" or freshness.get("current_sha256") != memory["sha256"]):
        raise ValueError("benchmark_current_memory_plan_unverified")
    return "memory_execution_hit"


def _verification(files, step, trial, entry, execution, response_ref, outputs, command, effective, *, selection_validated=False):
    judge = entry.get("judged_by")
    if judge in {"agent", "runtime"}:
        return judge
    result = entry.get("verification")
    if judge != "rule" or not isinstance(result, dict) or result.get("source") != "rule":
        raise ValueError("benchmark_verification_source_missing")
    observation = result.get("observations")
    if not isinstance(observation, dict):
        raise ValueError("benchmark_verification_observation_missing")
    ref = _lookup_ref(observation.get("evidence_ref"), "benchmark_verification_reference_invalid")
    if not ref.startswith("workflow-observations/"):
        raise ValueError("benchmark_verification_reference_invalid")
    envelope = _json(files, ref)
    receipt, frame = envelope.get("receipt"), envelope.get("frame")
    before = effective.get("capture") or {}
    before_id = before.get("capture_id") or execution + ":before:" + str(before.get("sha256", "no_input"))
    api = effective.get("response") or {}
    data = api.get("data") or {}
    action = data.get("result", data)
    if selection_validated:
        dispatched = True
    elif command.get("kind") == "input_sequence":
        dispatched = effective.get("status") == "completed" and effective.get("action_executed") is True
    elif command.get("kind") == "read_text":
        dispatched = effective.get("status") in {"agent_read_required", "text_observed", "no_text_detected"}
    else:
        dispatched = (effective.get("phase") == "returned" and api.get("success") is True
                      and (action.get("execution_path") or {}).get("action_executed", action.get("action_executed")) is True)
    original = _json(files, response_ref)
    if original.get("status") == "failed" or (entry.get("terminal_receipt") or {}).get("status", "completed") != "completed":
        dispatched = False
    actual = False if command.get("kind") == "read_text" else _actual_action_executed(effective)
    proof = effective.get("row_selection_proof") if selection_validated else None
    if (envelope.get("contract_version") != "workflow_observation.v1" or envelope.get("observation") != observation
            or envelope.get("source_receipt_sha256") != files[response_ref]["sha256"]
            or envelope.get("terminal_receipt") != entry.get("terminal_receipt")
            or not isinstance(receipt, dict) or not isinstance(frame, dict)
            or receipt.get("evidence_ref", "").replace("\\", "/") != response_ref
            or any(receipt.get(key) != value for key, value in {"run_id": trial["run_id"], "step_id": step["step_id"], "execution_request_id": execution}.items())
            or receipt.get("window_identity") != frame.get("window_identity")
            or receipt.get("window_identity") != _execution_identity({"result": effective})
            or receipt.get("pre_capture_id") != before_id
            or receipt.get("status") != ("completed" if dispatched else "failed")
            or receipt.get("action_executed") is not actual
            or receipt.get("row_selection_proof") != proof
            or receipt.get("post_capture_id") != frame.get("capture_id")
            or receipt.get("post_capture_sha256") != frame.get("sha256")):
        raise ValueError("benchmark_verification_binding_mismatch")
    image_check = step.get("verification", {}).get("image_check")
    if image_check is not None:
        from .image_verification import match_image_check
        reference_ref = "library/desktop-review/evidence-objects/" + image_check["reference_sha256"] + ".png"
        reference = files.get(reference_ref)
        current = [item for ref, item in files.items() if "data_base64" in item
                   and (frame.get("image_path", "").replace("\\", "/") == ref
                        or frame.get("image_path", "").replace("\\", "/").endswith("/" + ref))]
        if not isinstance(reference, dict) or "data_base64" not in reference or len(current) != 1:
            raise ValueError("benchmark_image_check_snapshot_missing")
        proof = match_image_check(image_check, reference["raw"], frame, current_raw=current[0]["raw"])
        if proof.get("matched") is not True or proof != observation.get("values", {}).get("image_check"):
            raise ValueError("benchmark_image_check_proof_mismatch")
    computed = verify_step(step, inputs=trial.get("inputs", {}),
                           outputs={key: {"run_id": trial["run_id"], "value": value} for key, value in outputs.items()},
                           receipt=receipt, observation=observation)
    if (computed != result or entry.get("rule_verdict") != computed["verdict"]
            or entry.get("outputs") != (computed["outputs"] if entry.get("verdict") == "success" else {})):
        raise ValueError("benchmark_verification_result_mismatch")
    return "rule_verified" if computed["reason"] in {"rule_verified", "image_rule_verified"} and computed["verdict"] == "success" else (
        "rule_failure" if computed["verdict"] == "failure" else "rule_uncertain")


def _image_verified(files, frame):
    path = frame.get("image_path") if isinstance(frame, dict) else None
    if not isinstance(path, str):
        return False
    matches = [item for ref, item in files.items() if "data_base64" in item and path.replace("\\", "/").endswith("/" + ref)]
    if len(matches) != 1 or matches[0]["sha256"] != frame.get("sha256"):
        return False
    try:
        with Image.open(BytesIO(matches[0]["raw"])) as image:
            image.verify()
        with Image.open(BytesIO(matches[0]["raw"])) as image:
            return frame.get("image_size") == {"width": image.width, "height": image.height}
    except (ValueError, OSError):
        return False


def inspect_coverage(binding: dict, program: dict, trial: dict, evidence_files: list) -> dict:
    """缺证据保留未知；不读取文件、不补造模型调用或输入事实。"""
    result = {"status": "partial", "steps": [], "errors": [],
              "limitations": ["model_telemetry_not_assessed"],
              "eligible_for_full_rule_comparison": False}
    try:
        audit = inspect_program(binding, program)
        if (not isinstance(trial, dict) or any(trial.get(key) != binding[key] for key in ("workflow_id", "program_id", "project_snapshot_id", "start_step_id"))
                or trial.get("execution_strategy") != "learned" or not isinstance(trial.get("history"), list)):
            raise ValueError("benchmark_trial_identity_mismatch")
        _id(trial.get("run_id"), "benchmark_run_id")
        files = _files(evidence_files)
    except (ValueError, TypeError, KeyError) as error:
        result["errors"].append(str(error))
        return result
    definitions = {step["step_id"]: step for step in program["definition"]["steps"]}
    rows = {identity: {"step_id": identity, "target_memory": "not_reached", "verification": "not_reached", "execution_request_ids": []}
            for identity in audit["reachable_step_ids"]}
    outputs = {}
    execution_ids = set()
    images_verified = True
    expected = binding["start_step_id"]
    for entry in trial["history"]:
        identity = entry.get("step_id") if isinstance(entry, dict) else None
        if identity not in rows or identity != expected:
            result["errors"].append("benchmark_history_path_mismatch")
            break
        row, step = rows[identity], definitions[identity]
        row.update(target_memory="unknown" if identity in binding["target_memory_steps"] else "not_applicable", verification="unknown")
        try:
            execution, command, effective, response_ref = _effective(files, entry)
            if execution in execution_ids:
                raise ValueError("benchmark_execution_ticket_reused")
            execution_ids.add(execution)
            row["execution_request_ids"].append(execution)
            from .selection_satisfaction import selection_requested
            selection_validated = selection_requested(step.get("action"))
            if selection_validated:
                row["action_executed"] = _selection_coverage(files, step, trial, entry, execution,
                    command, effective, outputs)
            if identity in binding["target_memory_steps"]:
                try:
                    row["target_memory"] = _target(step, command, effective, trial.get("inputs", {}), outputs,
                        selection_validated=selection_validated)
                except (ValueError, TypeError, KeyError, AttributeError) as error:
                    result["errors"].append(str(error))
            row["verification"] = _verification(files, step, trial, entry, execution, response_ref, outputs,
                command, effective, selection_validated=selection_validated)
            if entry.get("judged_by") == "rule":
                observation = entry["verification"]["observations"]
                frame = _json(files, observation["evidence_ref"]).get("frame")
                row["verification_image_verified"] = _image_verified(files, frame)
                images_verified = images_verified and row["verification_image_verified"]
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            result["errors"].append(str(error))
        verdict = entry.get("verdict")
        if verdict not in {"success", "failure", "uncertain"} or not isinstance(entry.get("outputs"), dict):
            result["errors"].append("benchmark_history_verdict_invalid")
            break
        expected = step["branches"].get(verdict)
        if verdict == "success":
            outputs.update({identity + "." + key: value for key, value in entry.get("outputs", {}).items()})
    result["steps"] = list(rows.values())
    if not images_verified:
        result["limitations"].append("image_bytes_not_independently_verified")
    reached = [row for row in rows.values() if row["verification"] != "not_reached"]
    remaining_agent_actions = any(row["verification"] == "agent" and definitions[row["step_id"]]["action"]["kind"] != "read_text"
                                  for row in reached)
    if remaining_agent_actions:
        result["limitations"].append("remaining_action_agent_judgment")
    complete = bool(reached) and not result["errors"] and all(row["target_memory"] != "unknown" and row["verification"] != "unknown" for row in reached)
    result["status"] = "complete" if complete else "partial"
    result["eligible_for_full_rule_comparison"] = (complete and images_verified and not remaining_agent_actions and trial.get("status") == "completed" and expected is None
        and any(row["target_memory"] == "memory_execution_hit" for row in reached)
        and any(row["verification"] == "rule_verified" for row in reached if row["step_id"] in binding["rule_verification_steps"])
        and all(entry.get("verdict") == "success" for entry in trial["history"])
        and all(row["target_memory"] in {"memory_execution_hit", "not_applicable"} for row in reached)
        and all(row["verification"] == "rule_verified" for row in reached if row["step_id"] in binding["rule_verification_steps"]))
    return result


__all__ = ["validate_binding", "inspect_program", "inspect_coverage"]
