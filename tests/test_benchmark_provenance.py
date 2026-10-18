"""正式对照绑定可达审核版本，运行覆盖只能来自本轮原证据。"""
from copy import deepcopy
from hashlib import sha256
import json
import base64
from io import BytesIO
from PIL import Image

import pytest

from app.learning_memory.workflow_program import _digest
from tests.test_workflow_trial import services
from tests.test_workflow_verified_trial import setup_run


def frozen(steps=None):
    reference = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "form", "state_key": "ready"}
    steps = steps or [{"step_id": "open", "review_status": "reviewed", "action": {
        "kind": "click", "goal": "open", "target_memory": reference},
        "branches": {"success": None, "failure": None, "uncertain": None},
        "verification": {"kind": "target_present", "target": {"control_type": "Button", "name": "done"}},
        "outputs": []}]
    body = {"workflow_id": "workflow-" + "b" * 64,
            "project_snapshot_id": "workflow-project-snapshot-" + "c" * 64, "revision": 1,
            "definition": {"title": "fresh", "inputs": [], "outputs": [], "steps": steps}}
    digest = _digest(body)
    program = {**body, "content_sha256": digest, "program_id": "task-program-" + digest, "review_items": []}
    binding = {key: program[key] for key in ("workflow_id", "program_id", "content_sha256", "project_snapshot_id")}
    binding.update(start_step_id=steps[0]["step_id"], artifact_path="D:/fresh/program.json",
                   target_memory_steps=[s["step_id"] for s in steps if "target_memory" in s["action"]],
                   rule_verification_steps=[s["step_id"] for s in steps if (s.get("verification") or {}).get("kind") not in {None, "agent_judgment"}])
    return binding, program


def test_reachable_pending_and_hidden_failure_branch_cannot_be_ignored():
    from app.learning_memory.benchmark_provenance import inspect_program
    binding, program = frozen()
    first = deepcopy(program["definition"]["steps"][0])
    second = deepcopy(first)
    second.update(step_id="fallback", review_status="pending")
    first["branches"]["failure"] = "fallback"
    binding, program = frozen([first, second])
    with pytest.raises(ValueError, match="pending"):
        inspect_program(binding, program)
    second["review_status"] = "reviewed"
    binding, program = frozen([first, second])
    binding["target_memory_steps"] = ["open"]
    with pytest.raises(ValueError, match="coverage"):
        inspect_program(binding, program)


def test_unreachable_pending_is_not_counted_as_reviewed_or_covered():
    from app.learning_memory.benchmark_provenance import inspect_program
    binding, program = frozen()
    first = program["definition"]["steps"][0]
    unused = deepcopy(first)
    unused.update(step_id="unused", review_status="pending")
    binding, program = frozen([first, unused])
    binding["target_memory_steps"] = binding["rule_verification_steps"] = ["open"]
    audit = inspect_program(binding, program)
    assert audit["reachable_step_ids"] == ["open"]
    assert audit["reviewed_step_ids"] == ["open"]
    assert audit["program"] == program


@pytest.mark.parametrize("change", ["start", "hash", "identity", "cycle", "dangling", "duplicate", "target_missing"])
def test_program_binding_and_graph_integrity_are_enforced(change):
    from app.learning_memory.benchmark_provenance import inspect_program
    binding, program = frozen()
    if change == "start":
        binding["start_step_id"] = "other"
    elif change == "hash":
        program["definition"]["title"] = "tampered"
    elif change == "identity":
        binding["project_snapshot_id"] = "workflow-project-snapshot-" + "d" * 64
    else:
        step = program["definition"]["steps"][0]
        if change == "cycle": step["branches"]["failure"] = "open"
        if change == "dangling": step["branches"]["failure"] = "missing"
        if change == "duplicate": program["definition"]["steps"].append(deepcopy(step))
        if change == "target_missing": del step["action"]["target_memory"]
        binding, program = frozen(program["definition"]["steps"])
    with pytest.raises(ValueError):
        inspect_program(binding, program)


def evidence(ref, value):
    text = json.dumps(value, ensure_ascii=False)
    return {"ref": ref, "text": text, "sha256": sha256(text.encode("utf-8")).hexdigest()}


def executed(*, matched=True, dispatched=True):
    binding, program = frozen()
    reference = program["definition"]["steps"][0]["action"]["target_memory"]
    command = {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "open", "click_kind": "single", "target_memory": reference}}
    identity = {"handle": 1, "process_id": 2, "process_create_time": 3.0}
    plan = {"contract_version": "memory_recognition_plan_v1", "goal": "open", "memory_evidence": {
        "reference": reference, "context_verified": True, "capture_id": "fresh", "sha256": "e" * 64},
        "recommended_target": {"capture_id": "fresh", "freshness": {"status": "current_recipe_revalidated", "current_sha256": "e" * 64}}}
    report = {"contract_version": "local_direct_step_v1", "phase": "returned", "memory_resolution": {
        "status": "matched" if matched else "miss", "reference": reference, "reason": "unique" if matched else "absent",
        "context_verified": True, "frame": {"window_identity": identity}},
        "target_identity": {"target_window_handle": 1, "process_id": 2, "process_create_time": 3.0},
        "response": {"success": True, "data": {"result": {"execution_path": {"action_executed": dispatched},
                                                         "recognition_plan": plan if matched else {}}}}}
    response = {"request_id": "exec", "command": command, "status": "returned", "result": report}
    files = [evidence("commands/exec.json", command), evidence("responses/exec.json", response)]
    trial = {key: binding[key] for key in ("workflow_id", "program_id", "project_snapshot_id", "start_step_id")}
    trial.update(run_id="trial-" + "f" * 64, execution_strategy="learned", status="completed", inputs={}, outputs={},
                 history=[{"step_id": "open", "execution_request_id": "exec", "receipt_sha256": files[1]["sha256"],
                           "terminal_receipt": None, "judged_by": "agent", "verdict": "success", "outputs": {}}])
    return binding, program, trial, files


@pytest.mark.parametrize("change", ["goal", "resolution_window", "plan_goal", "context"])
def test_memory_hit_cannot_be_relabelled_to_another_action_or_window(change):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = executed()
    command = json.loads(files[0]["text"])
    response = json.loads(files[1]["text"])
    if change == "goal":
        command["request"]["goal"] = "other"
        response["command"] = deepcopy(command)
    elif change == "resolution_window": response["result"]["memory_resolution"]["frame"]["window_identity"]["handle"] = 9
    elif change == "plan_goal": response["result"]["response"]["data"]["result"]["recognition_plan"]["goal"] = "other"
    elif change == "context": response["result"]["memory_resolution"]["context_verified"] = False
    files[0] = evidence(files[0]["ref"], command)
    files[1] = evidence(files[1]["ref"], response)
    trial["history"][0]["receipt_sha256"] = files[1]["sha256"]
    result = inspect_coverage(binding, program, trial, files)
    assert result["steps"][0]["target_memory"] == "unknown"
    assert not result["eligible_for_full_rule_comparison"]


@pytest.mark.parametrize("plan_uses_context_hint", [False, True])
def test_memory_plan_uses_original_action_goal_not_visual_fallback_hint(plan_uses_context_hint):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = executed()
    response = json.loads(files[1]["text"])
    resolution = response["result"]["memory_resolution"]
    resolution.update(goal="open", grounding_goal="open; visible row target_value contains R-current")
    if plan_uses_context_hint:
        response["result"]["response"]["data"]["result"]["recognition_plan"]["goal"] = resolution["grounding_goal"]
    files[1] = evidence(files[1]["ref"], response)
    trial["history"][0]["receipt_sha256"] = files[1]["sha256"]
    result = inspect_coverage(binding, program, trial, files)
    if plan_uses_context_hint:
        assert "benchmark_current_memory_plan_unverified" in result["errors"]
        assert result["steps"][0]["target_memory"] == "unknown"
    else:
        assert result["errors"] == []
        assert result["steps"][0]["target_memory"] == "memory_execution_hit"
    assert not result["eligible_for_full_rule_comparison"]


@pytest.mark.parametrize("matched,dispatched,expected", [(True, True, "memory_execution_hit"),
    (True, False, "not_executed"), (False, True, "miss")])
def test_actual_memory_plan_and_dispatch_are_required(matched, dispatched, expected):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    args = executed(matched=matched, dispatched=dispatched)
    result = inspect_coverage(*args)
    assert result["steps"][0]["target_memory"] == expected
    assert result["steps"][0]["verification"] == "agent"
    assert not result["eligible_for_full_rule_comparison"]


@pytest.mark.parametrize("change", ["missing", "response_hash", "plan_missing", "reference", "capture", "trial_start"])
def test_missing_or_changed_actual_evidence_never_becomes_memory_hit(change):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = executed()
    if change == "missing": files.pop()
    elif change == "response_hash": trial["history"][0]["receipt_sha256"] = "0" * 64
    elif change == "trial_start": trial["start_step_id"] = "other"
    else:
        value = json.loads(files[1]["text"])
        result = value["result"]["response"]["data"]["result"]
        if change == "plan_missing": result.pop("recognition_plan")
        if change == "reference": result["recognition_plan"]["memory_evidence"]["reference"]["recipe_id"] = "other"
        if change == "capture": result["recognition_plan"]["recommended_target"]["capture_id"] = "old"
        files[1] = evidence(files[1]["ref"], value)
        trial["history"][0]["receipt_sha256"] = files[1]["sha256"]
    result = inspect_coverage(binding, program, trial, files)
    assert not result["eligible_for_full_rule_comparison"]
    assert result["status"] == "partial"
    assert all(step["target_memory"] != "memory_execution_hit" for step in result["steps"])


def test_real_service_generated_rule_receipt_is_recognized(services):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    trials, run, ticket, result, envelope = setup_run(services)
    state = trials.record_verified_result(run["run_id"], "verify", ticket["execution_request_id"], result)
    program = trials.programs.load(state["workflow_id"], state["program_id"])
    # 正式绑定另经审核；这里保留服务生成的运行证据，仅验证覆盖解析。
    definition = deepcopy(program["definition"])
    first = definition["steps"][0]
    first["action"]["target_memory"] = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "form", "state_key": "ready"}
    for step in definition["steps"]:
        step["review_status"] = "reviewed"
        if step["action"]["kind"] == "click":
            step["action"]["target_memory"] = deepcopy(first["action"]["target_memory"])
    binding, pinned = frozen(definition["steps"])
    pinned["definition"] = definition
    body = {k: v for k, v in pinned.items() if k not in {"program_id", "content_sha256", "review_items"}}
    pinned["content_sha256"] = _digest(body)
    pinned["program_id"] = "task-program-" + pinned["content_sha256"]
    binding.update(program_id=pinned["program_id"], content_sha256=pinned["content_sha256"])
    state.update(**{key: binding[key] for key in ("workflow_id", "program_id", "project_snapshot_id")})
    envelope["receipt"]["run_id"] = state["run_id"]
    response_path = trials.session / "responses" / (ticket["execution_request_id"] + ".json")
    raw = response_path.read_text(encoding="utf-8")
    response = json.loads(raw)
    files = [{"ref": "responses/" + response_path.name, "text": raw, "sha256": sha256(raw.encode()).hexdigest()},
             evidence("commands/" + response_path.name, response["command"]),
             evidence("workflow-observations/verify.json", envelope)]
    covered = inspect_coverage(binding, pinned, state, files)
    indexed = {step["step_id"]: step for step in covered["steps"]}
    assert indexed["search"]["verification"] == "rule_verified"
    assert indexed["open"]["verification"] == "not_reached"
    assert not covered["eligible_for_full_rule_comparison"]


def test_binary_evidence_validates_actual_bytes_without_reading_disk():
    from app.learning_memory.benchmark_provenance import _files
    raw = b"fresh image bytes"
    entry = {"ref": "workflow-observations/fresh.png", "sha256": sha256(raw).hexdigest(),
             "data_base64": base64.b64encode(raw).decode("ascii")}
    assert _files([entry])[entry["ref"]]["raw"] == raw
    entry["data_base64"] = base64.b64encode(b"changed").decode("ascii")
    with pytest.raises(ValueError, match="hash"):
        _files([entry])


def verified_execution():
    from app.learning_memory.workflow_verification import verify_step
    binding, program, trial, files = executed()
    identity = {"handle": 1, "process_id": 2, "process_create_time": 3.0}
    response = json.loads(files[1]["text"])
    response["result"]["target_identity"] = {"target_window_handle": 1, "process_id": 2, "process_create_time": 3.0}
    response["result"]["capture"] = {"capture_id": "before"}
    files[1] = evidence(files[1]["ref"], response)
    stream = BytesIO()
    Image.new("RGB", (8, 6), "white").save(stream, format="PNG")
    raw = stream.getvalue()
    digest = sha256(raw).hexdigest()
    normalized = {"run_id": trial["run_id"], "step_id": "open", "request_id": "verify", "execution_request_id": "exec",
        "status": "completed", "action_executed": True, "pre_capture_id": "before", "post_capture_id": "after",
        "post_capture_sha256": digest, "window_identity": identity, "scope_id": "current", "evidence_ref": files[1]["ref"]}
    observation = {key: normalized[key] for key in ("run_id", "step_id", "request_id", "execution_request_id", "window_identity", "scope_id")}
    observation.update(capture_id="after", capture_sha256=digest, complete=True, source="uia_value",
                       values={"target_present": True}, evidence_ref="workflow-observations/verify.json")
    frame = {"capture_id": "after", "sha256": digest, "window_identity": identity,
             "image_path": "D:/fresh/session/workflow-observations/after.png", "image_size": {"width": 8, "height": 6}}
    result = verify_step(program["definition"]["steps"][0], inputs={}, outputs={}, receipt=normalized, observation=observation)
    trial["history"][0].update(receipt_sha256=files[1]["sha256"], judged_by="rule", rule_verdict="success", verification=result)
    envelope = {"contract_version": "workflow_observation.v1", "receipt": normalized, "observation": observation,
                "frame": frame, "source_receipt_sha256": files[1]["sha256"]}
    files.append(evidence(observation["evidence_ref"], envelope))
    files.append({"ref": "workflow-observations/after.png", "sha256": digest, "data_base64": base64.b64encode(raw).decode("ascii")})
    return binding, program, trial, files


def test_windows_rule_observation_lookup_preserves_original_envelope():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    from app.learning_memory.workflow_verification import verify_step
    binding, program, trial, files = verified_execution()
    observation = trial["history"][0]["verification"]["observations"]
    observation["evidence_ref"] = "workflow-observations\\verify.json"
    envelope = json.loads(files[2]["text"])
    envelope["observation"]["evidence_ref"] = observation["evidence_ref"]
    envelope["receipt"]["evidence_ref"] = "responses\\exec.json"
    trial["history"][0]["verification"] = verify_step(program["definition"]["steps"][0],
        inputs={}, outputs={}, receipt=envelope["receipt"], observation=observation)
    files[2] = evidence(files[2]["ref"], envelope)
    result = inspect_coverage(binding, program, trial, files)
    assert result["steps"][0]["verification"] == "rule_verified"
    assert result["eligible_for_full_rule_comparison"]
    assert observation["evidence_ref"] == "workflow-observations\\verify.json"
    envelope["observation"]["evidence_ref"] = "workflow-observations/verify.json"
    files[2] = evidence(files[2]["ref"], envelope)
    changed = inspect_coverage(binding, program, trial, files)
    assert "benchmark_verification_binding_mismatch" in changed["errors"]


@pytest.mark.parametrize("ref", ["workflow-observations\\..\\verify.json", "\\workflow-observations\\verify.json",
                                "C:\\workflow-observations\\verify.json"])
def test_rule_lookup_rejects_unsafe_windows_references(ref):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = verified_execution()
    trial["history"][0]["verification"]["observations"]["evidence_ref"] = ref
    result = inspect_coverage(binding, program, trial, files)
    assert "benchmark_verification_reference_invalid" in result["errors"]


def test_duplicate_snapshot_conflict_still_rejected():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = verified_execution()
    files.append(evidence(files[1]["ref"], {"changed": True}))
    result = inspect_coverage(binding, program, trial, files)
    assert "benchmark_evidence_reference_invalid" in result["errors"]


def test_full_rule_comparison_requires_actual_image_bytes_and_bound_rule():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = verified_execution()
    full = inspect_coverage(binding, program, trial, files)
    assert full["eligible_for_full_rule_comparison"]
    assert full["steps"][0]["verification_image_verified"]
    missing = inspect_coverage(binding, program, trial, files[:-1])
    assert missing["steps"][0]["verification"] == "rule_verified"
    assert not missing["eligible_for_full_rule_comparison"]
    assert "image_bytes_not_independently_verified" in missing["limitations"]


def test_normalized_success_cannot_override_failed_original_report():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = verified_execution()
    response = json.loads(files[1]["text"])
    response["result"]["phase"] = "failed"
    files[1] = evidence(files[1]["ref"], response)
    trial["history"][0]["receipt_sha256"] = files[1]["sha256"]
    envelope = json.loads(files[2]["text"])
    envelope["source_receipt_sha256"] = files[1]["sha256"]
    files[2] = evidence(files[2]["ref"], envelope)
    result = inspect_coverage(binding, program, trial, files)
    assert result["steps"][0]["verification"] == "unknown"
    assert not result["eligible_for_full_rule_comparison"]


@pytest.mark.parametrize("change", ["window", "normalized_action", "original_capture", "rule_output", "image_bytes"])
def test_independently_consistent_envelope_cannot_replace_original_execution(change):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = verified_execution()
    envelope = json.loads(files[2]["text"])
    if change == "window":
        for field in ("receipt", "observation", "frame"):
            envelope[field]["window_identity"]["handle"] = 999
        trial["history"][0]["verification"]["observations"]["window_identity"]["handle"] = 999
    elif change == "normalized_action": envelope["receipt"]["action_executed"] = False
    elif change == "original_capture": envelope["receipt"]["pre_capture_id"] = "invented"
    elif change == "rule_output": trial["history"][0]["outputs"] = {"invented": "data"}
    elif change == "image_bytes": files[-1]["data_base64"] = base64.b64encode(b"changed").decode("ascii")
    files[2] = evidence(files[2]["ref"], envelope)
    result = inspect_coverage(binding, program, trial, files)
    assert not result["eligible_for_full_rule_comparison"]


@pytest.mark.parametrize("state", ["ambiguous", "unsupported"])
def test_fallback_categories_remain_explicit_even_when_action_succeeds(state):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = executed(matched=False)
    response = json.loads(files[1]["text"])
    response["result"]["memory_resolution"]["status"] = state
    files[1] = evidence(files[1]["ref"], response)
    trial["history"][0]["receipt_sha256"] = files[1]["sha256"]
    assert inspect_coverage(binding, program, trial, files)["steps"][0]["target_memory"] == state


def test_async_terminal_canonical_hash_and_focus_receipt_bind_to_original_execution():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    from app.learning_memory.receipt_adapter import content_hash
    binding, program, trial, files = executed()
    step = deepcopy(program["definition"]["steps"][0])
    reference = step["action"]["target_memory"]
    step["action"] = {"kind": "input_sequence", "field_goal": "open", "text": {"source": "constant", "value": "fresh"},
                      "clear_existing": True, "submit_search": False, "target_memory": reference}
    binding, program = frozen([step])
    trial.update(**{key: binding[key] for key in ("program_id", "project_snapshot_id", "workflow_id")})
    command = {"kind": "input_sequence", "request": {"field_goal": "open", "text": "fresh", "clear_existing": True,
                                                        "submit_search": False, "target_memory": reference}}
    report = json.loads(files[1]["text"])["result"]
    terminal = {"contract_version": "agent_command.v1", "command_id": "exec", "status": "completed",
                "result": {"contract_version": "input_sequence_v1", "status": "completed", "action_executed": True,
                           "steps": [{"name": "focus", "operation": "execute_recognition_plan", "receipt": report}]}}
    response = {"request_id": "exec", "command": command, "status": "returned",
                "result": {"contract_version": "agent_command.v1", "command_id": "exec", "status": "running"}}
    files = [evidence("commands/exec.json", command), evidence("responses/exec.json", response), evidence("agent-commands/exec.json", terminal)]
    trial["history"][0].update(receipt_sha256=files[1]["sha256"], terminal_receipt={"path": "D:/fresh/session/agent-commands/exec.json",
        "status": "completed", "sha256": content_hash(terminal), "hash_scope": "canonical_json"})
    assert inspect_coverage(binding, program, trial, files)["steps"][0]["target_memory"] == "memory_execution_hit"
    trial["history"][0]["terminal_receipt"]["sha256"] = "0" * 64
    assert inspect_coverage(binding, program, trial, files)["steps"][0]["target_memory"] == "unknown"


def test_failed_start_is_partial_and_never_full_rule_eligible():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program = frozen()
    result = inspect_coverage(binding, program, None, [])
    assert result["status"] == "partial"
    assert not result["eligible_for_full_rule_comparison"]


def test_rule_fact_does_not_turn_effective_failure_into_full_comparison_success():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = verified_execution()
    trial["history"][0]["verdict"] = "failure"
    result = inspect_coverage(binding, program, trial, files)
    assert result["steps"][0]["verification"] == "rule_verified"
    assert not result["eligible_for_full_rule_comparison"]


def test_unreachable_invalid_graph_is_rejected_even_when_review_is_out_of_scope():
    from app.learning_memory.benchmark_provenance import inspect_program
    binding, program = frozen()
    first = program["definition"]["steps"][0]
    unused = deepcopy(first)
    unused.update(step_id="unused", review_status="pending")
    unused["branches"]["failure"] = "unused"
    binding, program = frozen([first, unused])
    binding["target_memory_steps"] = binding["rule_verification_steps"] = ["open"]
    with pytest.raises(ValueError, match="cycle"):
        inspect_program(binding, program)


def test_remaining_action_agent_judgment_prevents_full_rule_claim():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = verified_execution()
    first = deepcopy(program["definition"]["steps"][0])
    first["branches"]["success"] = "agent-action"
    second = deepcopy(first)
    second.update(step_id="agent-action", verification={"kind": "agent_judgment"})
    second["branches"]["success"] = None
    binding, program = frozen([first, second])
    trial.update(program_id=binding["program_id"])
    command = json.loads(files[0]["text"])
    response = json.loads(files[1]["text"])
    response["request_id"] = "exec-second"
    second_files = [evidence("commands/exec-second.json", command), evidence("responses/exec-second.json", response)]
    trial["history"].append({"step_id": "agent-action", "execution_request_id": "exec-second",
        "receipt_sha256": second_files[1]["sha256"], "terminal_receipt": None,
        "judged_by": "agent", "verdict": "success", "outputs": {}})
    result = inspect_coverage(binding, program, trial, files + second_files)
    assert not result["eligible_for_full_rule_comparison"]
    assert "remaining_action_agent_judgment" in result["limitations"]


def test_execution_ticket_cannot_cover_two_different_history_steps():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = verified_execution()
    first = deepcopy(program["definition"]["steps"][0])
    first["branches"]["success"] = "second"
    second = deepcopy(first)
    second.update(step_id="second", verification={"kind": "agent_judgment"})
    second["branches"]["success"] = None
    binding, program = frozen([first, second])
    trial.update(program_id=binding["program_id"])
    trial["history"].append({"step_id": "second", "execution_request_id": "exec",
        "receipt_sha256": files[1]["sha256"], "terminal_receipt": None,
        "judged_by": "agent", "verdict": "success", "outputs": {}})
    result = inspect_coverage(binding, program, trial, files)
    assert result["status"] == "partial"
    assert "benchmark_execution_ticket_reused" in result["errors"]
    assert not result["eligible_for_full_rule_comparison"]


def test_agent_read_remains_allowed_without_claiming_model_telemetry():
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = verified_execution()
    first = deepcopy(program["definition"]["steps"][0])
    first["branches"]["success"] = "read-current"
    second = {"step_id": "read-current", "review_status": "reviewed", "action": {"kind": "read_text", "goal": "current"},
              "branches": {"success": None, "failure": None, "uncertain": None}, "outputs": [],
              "verification": {"kind": "agent_judgment"}}
    binding, program = frozen([first, second])
    trial.update(program_id=binding["program_id"])
    command = {"kind": "read_text", "max_chars": 10000}
    response = {"status": "returned", "command": command, "result": {"contract_version": "captured_text_v1", "status": "text_observed"}}
    additions = [evidence("commands/read.json", command), evidence("responses/read.json", response)]
    trial["history"].append({"step_id": "read-current", "execution_request_id": "read", "receipt_sha256": additions[1]["sha256"],
                            "terminal_receipt": None, "judged_by": "agent", "verdict": "success", "outputs": {}})
    result = inspect_coverage(binding, program, trial, files + additions)
    assert result["eligible_for_full_rule_comparison"]
    assert "remaining_action_agent_judgment" not in result["limitations"]
    assert "model_telemetry_not_assessed" in result["limitations"]


def image_execution(tmp_path):
    from tests.test_image_verification import sample
    from app.learning_memory.image_verification import match_image_check
    from app.learning_memory.workflow_verification import verify_step
    binding, program, trial, files = verified_execution()
    check, raw, _, frame = sample(tmp_path)
    step = deepcopy(program["definition"]["steps"][0])
    step["verification"] = {"kind": "agent_judgment", "image_check": check}
    binding, program = frozen([step])
    # 新合成证据按共同入口编译；不改写既有现场归档。
    from app.learning_memory.workflow_trial import _command
    command = _command(step, {}, {})
    execution = json.loads(files[1]['text'])
    execution['command'] = command
    files[0] = evidence(files[0]['ref'], command)
    files[1] = evidence(files[1]['ref'], execution)
    trial['history'][0]['receipt_sha256'] = files[1]['sha256']
    binding["rule_verification_steps"] = ["open"]
    trial.update(program_id=program["program_id"])
    envelope = json.loads(files[-2]["text"])
    envelope['source_receipt_sha256'] = files[1]['sha256']
    frame.update(capture_id="after", image_path="D:/fresh/session/workflow-observations/after.png")
    proof = match_image_check(check, raw, dict(frame, image_path=str(tmp_path / "desktop-review/evidence-objects" / (check["reference_sha256"] + ".png"))))
    envelope["frame"] = frame
    envelope["receipt"]["post_capture_sha256"] = frame["sha256"]
    envelope["observation"].update(capture_sha256=frame["sha256"], source="image_template", values={"image_check": proof})
    result = verify_step(step, inputs={}, outputs={}, receipt=envelope["receipt"], observation=envelope["observation"])
    assert result["reason"] == "image_rule_verified"
    trial["history"][0]["verification"] = result
    files[-2] = evidence("workflow-observations/verify.json", envelope)
    files[-1] = {"ref": "workflow-observations/after.png", "sha256": frame["sha256"], "data_base64": base64.b64encode(raw).decode("ascii")}
    files.append({"ref": "library/desktop-review/evidence-objects/" + check["reference_sha256"] + ".png",
                  "sha256": check["reference_sha256"], "data_base64": base64.b64encode(raw).decode("ascii")})
    return binding, program, trial, files


def test_actual_image_rule_is_counted_from_current_archived_pixels(tmp_path):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    args = image_execution(tmp_path)
    result = inspect_coverage(*args)
    assert result["steps"][0]["verification"] == "rule_verified"
    assert result["eligible_for_full_rule_comparison"] is True


def test_image_rule_missing_reference_snapshot_stays_unknown(tmp_path):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    binding, program, trial, files = image_execution(tmp_path)
    result = inspect_coverage(binding, program, trial, files[:-1])
    assert result["steps"][0]["verification"] == "unknown"
    assert result["eligible_for_full_rule_comparison"] is False


def test_forged_image_proof_cannot_override_wrong_current_archived_pixels(tmp_path):
    from app.learning_memory.benchmark_provenance import inspect_coverage
    from app.learning_memory.workflow_verification import verify_step
    binding, program, trial, files = image_execution(tmp_path)
    stream = BytesIO()
    Image.new("RGB", (80, 60), "black").save(stream, format="PNG")
    raw = stream.getvalue()
    digest = sha256(raw).hexdigest()
    envelope = json.loads(files[-3]["text"])
    envelope["frame"]["sha256"] = digest
    envelope["receipt"]["post_capture_sha256"] = digest
    envelope["observation"]["capture_sha256"] = digest
    envelope["observation"]["values"]["image_check"]["capture_sha256"] = digest
    trial["history"][0]["verification"] = verify_step(program["definition"]["steps"][0], inputs={}, outputs={},
        receipt=envelope["receipt"], observation=envelope["observation"])
    assert trial["history"][0]["verification"]["verdict"] == "success"
    files[-3] = evidence("workflow-observations/verify.json", envelope)
    files[-2] = {"ref": "workflow-observations/after.png", "sha256": digest, "data_base64": base64.b64encode(raw).decode("ascii")}
    result = inspect_coverage(binding, program, trial, files)
    assert result["steps"][0]["verification"] == "unknown"
    assert "benchmark_image_check_proof_mismatch" in result["errors"]
    assert not result["eligible_for_full_rule_comparison"]
