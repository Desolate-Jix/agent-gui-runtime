"""冻结 C 路线不能被待审定义、短流程或普通命令冒充。"""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.learning_memory.benchmark_manifest import digest, freeze_manifest
from app.learning_memory.workflow_program import _digest
from tests.test_benchmark_collection import ASSESSMENT, ConnectedClient, frozen, module


def bound_collection(tmp_path, *, case_inputs=None, input_declarations=None, with_read=False):
    root, original = frozen(tmp_path)
    value = json.loads(original.read_text(encoding="utf-8"))
    spec = {key: value[key] for key in ("benchmark_id", "model", "cases", "artifacts")}
    declarations = input_declarations or [{"name": "value", "type": "text", "required": True}]
    input_name = declarations[0]["name"]
    if case_inputs is not None:
        spec["cases"][0]["inputs"] = deepcopy(case_inputs)
    reference = {"recipe_id": "target-recipe-" + "a" * 64,
                 "interface_key": "record-desk", "state_key": "query"}
    step = {"step_id": "search", "title": "Search", "source_node_id": None,
            "target_node_id": None, "action": {"kind": "input_sequence",
                "field_goal": "query", "text": {"source": "input", "name": input_name},
                "clear_existing": True, "submit_search": False, "target_memory": reference},
            "preconditions": [], "success_conditions": [],
            "branches": {"success": None, "failure": None, "uncertain": None},
            "outputs": [], "review_status": "reviewed", "provenance": "manual",
            "verification": {"kind": "field_equals", "target": {"name": "query", "control_type": "Edit"},
                "expected": {"source": "input", "name": input_name}}}
    steps = [step]
    if with_read:
        step["branches"]["success"] = "read"
        read = deepcopy(step)
        read.update(step_id="read", title="Read", action={"kind": "read_text", "goal": "Read current detail"},
                    branches={"success": None, "failure": None, "uncertain": None},
                    outputs=[{"name": "detail", "type": "text"}],
                    read_spec={"method": "agent_read", "output_name": "detail", "target": {"name": "detail", "control_type": "Text"}})
        read.pop("verification")
        steps.append(read)
    content = {"workflow_id": "workflow-" + "1" * 64,
               "project_snapshot_id": "workflow-snapshot-" + "2" * 64, "revision": 1,
               "definition": {"title": "fresh benchmark", "inputs": declarations, "outputs": [], "steps": steps}}
    checksum = _digest(content)
    program = {**content, "content_sha256": checksum,
               "program_id": "task-program-" + checksum, "review_items": []}
    path = tmp_path / "program.json"
    path.write_text(json.dumps(program, ensure_ascii=False), encoding="utf-8")
    binding = {key: program[key] for key in (
        "workflow_id", "program_id", "content_sha256", "project_snapshot_id")}
    binding.update(start_step_id="search", artifact_path=str(path.resolve()),
                   target_memory_steps=["search"], rule_verification_steps=["search"])
    spec["artifacts"] = [{"kind": "workflow", "version": program["program_id"], "path": str(path.resolve())}]
    spec["cases"][0]["c_workflow"] = binding
    target = tmp_path / "bound-manifest.json"
    freeze_manifest(spec, root=root, destination=target)
    client = ConnectedClient(tmp_path / "session")
    api = module()
    run = api.BenchmarkCollection(manifest_path=target, root=root,
                                 directory=tmp_path / "collection", client=client)
    return api, run, client, program, binding


def projected_collection(tmp_path, **changes):
    return bound_collection(tmp_path,
        case_inputs=changes.get("case_inputs", {"record_id": "R1", "query": "R1"}),
        input_declarations=changes.get("declarations", [{"name": "record_id", "type": "text", "required": True}]))


def start_projected(run, client, program, binding, inputs=None):
    read_bound(run, client, program, binding)
    actual = {"record_id": "R1"} if inputs is None else inputs
    trial = {key: binding[key] for key in ("workflow_id", "program_id", "project_snapshot_id", "start_step_id")}
    trial.update(run_id="trial-projected", execution_strategy="learned", inputs=actual,
                 status="ready", current_step_id="search", history=[], pending=None)
    client.result = {"status": "returned", "result": trial}
    cmd = command("start", binding); cmd["request"]["inputs"] = actual
    call(run, "projected-start", cmd)
    return trial


def test_projected_frozen_inputs_start_and_replay_without_changing_case(tmp_path):
    api, run, client, program, binding = projected_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    trial = start_projected(run, client, program, binding)
    client.result = {"status": "returned", "result": {**trial, "status": "completed", "text": "current"}}
    call(run, "projected-status", command("status", binding, run_id=trial["run_id"]))
    run.finish(request_id="projected-status", assessment=ASSESSMENT)
    report = api.compare_collection(run.directory)
    assert report["runs"][0]["completed"] is True
    assert report["workflow_provenance"][0]["trial"]["inputs"] == {"record_id": "R1"}
    assert run.manifest["cases"][0]["inputs"] == {"record_id": "R1", "query": "R1"}


@pytest.mark.parametrize("inputs", [{"record_id": "other"}, {}, {"record_id": "R1", "query": "R1"}])
def test_projected_start_rejects_changed_missing_or_extra_inputs_before_dispatch(tmp_path, inputs):
    _, run, client, program, binding = projected_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    read_bound(run, client, program, binding)
    cmd = command("start", binding); cmd["request"]["inputs"] = inputs
    with pytest.raises(ValueError, match="inputs_not_frozen"):
        call(run, "bad-projected-start", cmd)
    assert len(client.calls) == 1


@pytest.mark.parametrize("frozen", [{"query": "R1"}, {"record_id": True, "query": "R1"}])
def test_projected_required_source_and_runtime_type_are_validated(tmp_path, frozen):
    _, run, client, program, binding = projected_collection(tmp_path, case_inputs=frozen)
    run.begin(case_id="query_verify-0", route="C")
    read_bound(run, client, program, binding)
    cmd = command("start", binding); cmd["request"]["inputs"] = {"record_id": frozen.get("record_id")}
    with pytest.raises(ValueError, match="required_input_missing|input_type_invalid"):
        call(run, "missing-source", cmd)
    assert len(client.calls) == 1


@pytest.mark.parametrize("inputs", [{"record_id": "other"}, {}, {"record_id": "R1", "query": "R1"}])
def test_projected_trial_receipt_inputs_cannot_drift(tmp_path, inputs):
    _, run, client, program, binding = projected_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    trial = start_projected(run, client, program, binding)
    client.result = {"status": "returned", "result": {**trial, "inputs": inputs}}
    with pytest.raises(ValueError, match="trial_inputs_mismatch"):
        call(run, "drifted-status", command("status", binding, run_id=trial["run_id"]))


def test_projected_journal_replay_rejects_rehashed_start_input_change(tmp_path):
    api, run, client, program, binding = projected_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    start_projected(run, client, program, binding)
    def edit(events):
        event = next(row for row in events if row["kind"] == "call"
                     and row["payload"]["arguments"].get("request_id") == "projected-start")
        event["payload"]["arguments"]["command"]["request"]["inputs"]["record_id"] = "other"
    rehash_journal(run.directory, edit)
    with pytest.raises(ValueError, match="inputs_not_frozen"):
        api.compare_collection(run.directory)


def test_projected_start_receipt_cannot_add_undeclared_query(tmp_path):
    _, run, client, program, binding = projected_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    read_bound(run, client, program, binding)
    trial = {key: binding[key] for key in ("workflow_id", "program_id", "project_snapshot_id", "start_step_id")}
    trial.update(run_id="trial-projected", execution_strategy="learned",
                 inputs={"record_id": "R1", "query": "R1"}, status="ready", history=[])
    client.result = {"status": "returned", "result": trial}
    cmd = command("start", binding); cmd["request"]["inputs"] = {"record_id": "R1"}
    with pytest.raises(ValueError, match="trial_inputs_mismatch"):
        call(run, "bad-start-receipt", cmd)


def test_projected_replay_cannot_change_original_trial_receipt(tmp_path):
    api, run, client, program, binding = projected_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    start_projected(run, client, program, binding)
    def edit(events):
        event = next(row for row in events if row["kind"] == "receipt"
                     and row["payload"]["request_id"] == "projected-start")
        event["payload"]["receipt"]["result"]["inputs"] = {"record_id": "other"}
    rehash_journal(run.directory, edit)
    with pytest.raises(ValueError, match="trial_inputs_mismatch"):
        api.compare_collection(run.directory)


def test_projected_optional_inputs_use_only_frozen_values_and_original_types(tmp_path):
    declarations = [{"name": "record_id", "type": "text", "required": True},
                    {"name": "present", "type": "number", "required": False},
                    {"name": "absent", "type": "boolean", "required": False}]
    api, run, client, program, binding = projected_collection(tmp_path,
        case_inputs={"record_id": "R1", "query": "R1", "present": 7}, declarations=declarations)
    run.begin(case_id="query_verify-0", route="C")
    read_bound(run, client, program, binding)
    case = run.manifest["cases"][0]
    definition = run._definitions[run._active["attempt_id"]]
    assert api._frozen_workflow_inputs(case, definition) == {"record_id": "R1", "present": 7}
    changed = deepcopy(case); changed["inputs"]["present"] = True
    with pytest.raises(ValueError, match="input_type_invalid"):
        api._frozen_workflow_inputs(changed, definition)


def command(action, binding, **extra):
    request = {"action": action, **extra}
    if action in {"read", "start"}:
        request.update({key: binding[key] for key in ("workflow_id", "program_id")})
    if action == "start":
        request.update(start_step_id=binding["start_step_id"], inputs={"value": "current"})
    return {"kind": "learning_workflow", "request": request}


def call(run, request_id, cmd):
    return asyncio.run(run.call("instant_run", {"request_id": request_id, "command": cmd}))


def read_bound(run, client, program, binding):
    client.result = {"status": "returned", "result": deepcopy(program)}
    call(run, "definition-read", command("read", binding))


def start_bound(run, client, program, binding):
    read_bound(run, client, program, binding)
    trial = {key: binding[key] for key in ("workflow_id", "program_id", "project_snapshot_id", "start_step_id")}
    trial.update(run_id="trial-one", execution_strategy="learned", inputs={"value": "current"},
                 status="ready", current_step_id="search", history=[], pending=None)
    client.result = {"status": "returned", "result": trial}
    call(run, "trial-start", command("start", binding))
    return trial


def test_bound_c_requires_original_saved_definition_read_before_start(tmp_path):
    _, run, client, _, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    with pytest.raises(ValueError, match="definition.*required"):
        call(run, "start-without-read", command("start", binding))
    assert client.calls == []


@pytest.mark.parametrize("change", ["program_id", "start_step_id", "ordinary_command", "save"])
def test_bound_c_cannot_change_version_skip_entry_or_execute_unbound_command(tmp_path, change):
    _, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    read_bound(run, client, program, binding)
    cmd = command("start", binding)
    if change in {"program_id", "start_step_id"}:
        cmd["request"][change] = "other"
    elif change == "ordinary_command":
        cmd = {"kind": "read_text"}
    else:
        cmd = {"kind": "learning_workflow", "request": {"action": "save"}}
    with pytest.raises(ValueError, match="benchmark_c_"):
        call(run, "changed-start", cmd)
    assert len(client.calls) == 1


def test_definition_read_receipt_cannot_claim_different_reviewed_content(tmp_path):
    _, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    client.result = {"status": "returned", "result": deepcopy(program)}
    client.result["result"]["definition"]["steps"][0]["review_status"] = "pending"
    with pytest.raises(ValueError, match="benchmark_c_|integrity|hash|checksum"):
        call(run, "wrong-definition", command("read", binding))
    assert len(client.calls) == 1
    with pytest.raises(ValueError, match="definition.*required"):
        call(run, "start-after-invalid-read", command("start", binding))


def test_original_trial_and_missing_execution_evidence_remain_unqualified(tmp_path):
    api, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    trial = start_bound(run, client, program, binding)
    client.result = {"status": "returned", "result": {**trial, "status": "completed", "text": "current"}}
    call(run, "trial-status", command("status", binding, run_id="trial-one"))
    row = run.finish(request_id="trial-status", assessment=ASSESSMENT)
    assert row["completed"] is True
    assert row["telemetry"] == {"planning": False, "grounding": False, "verification": False}
    report = api.compare_collection(run.directory)
    provenance = report["workflow_provenance"][0]
    assert provenance["definition"]["program"]["program_id"] == binding["program_id"]
    assert provenance["coverage"]["eligible_for_full_rule_comparison"] is False
    assert report["c_route_contract"]["eligible_for_full_rule_comparison"] is False
    assert "c_route_coverage_unverified" in report["limitations"]
    assert report["empirical_acceptance"] is False


def test_original_diagnostic_manifest_does_not_claim_reviewed_c(tmp_path):
    from tests.test_benchmark_collection import collection
    api, run, _, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    call(run, "diagnostic-read", {"kind": "read_text"})
    run.finish(request_id="diagnostic-read", assessment=ASSESSMENT)
    report = api.compare_collection(bundle)
    assert report["c_route_contract"]["eligible_for_full_rule_comparison"] is False
    assert report["workflow_provenance"][0]["status"] == "unbound"
    assert "c_route_definition_unbound" in report["limitations"]


def test_finish_cannot_use_definition_read_as_final_workflow_result(tmp_path):
    _, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    read_bound(run, client, program, binding)
    with pytest.raises(ValueError, match="benchmark_c_finish"):
        run.finish(request_id="definition-read", assessment=ASSESSMENT)


def test_steps_only_control_pins_same_definition_and_keeps_its_original_strategy(tmp_path):
    _, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="B")
    read_bound(run, client, program, binding)
    changed = command("start", binding)
    changed["request"]["program_id"] = "other"
    with pytest.raises(ValueError, match="definition_mismatch"):
        call(run, "other-control", changed)
    trial = {key: binding[key] for key in ("workflow_id", "program_id", "project_snapshot_id", "start_step_id")}
    trial.update(run_id="control-one", execution_strategy="steps_only", inputs={"value": "current"},
                 status="ready", current_step_id="search", history=[], pending=None)
    client.result = {"status": "returned", "result": trial}
    call(run, "control-start", command("start", binding))
    assert client.calls[-1][1]["command"]["request"]["execution_strategy"] == "steps_only"


def rehash_journal(directory, edit):
    path = directory / "journal.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    edit(events)
    previous = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["manifest_sha256"]
    for index, event in enumerate(events):
        event.update(sequence=index, previous_sha256=previous)
        event["sha256"] = digest({key: value for key, value in event.items() if key != "sha256"})
        previous = event["sha256"]
    path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8")


@pytest.mark.parametrize("change", ["coverage", "definition", "trial"])
def test_comparison_recomputes_c_provenance_from_original_receipts(tmp_path, change):
    api, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    trial = start_bound(run, client, program, binding)
    client.result = {"status": "returned", "result": {**trial, "status": "completed", "text": "current"}}
    call(run, "trial-status", command("status", binding, run_id="trial-one"))
    run.finish(request_id="trial-status", assessment=ASSESSMENT)

    def edit(events):
        provenance = next(event for event in events if event["kind"] == "finish")["payload"]["workflow_provenance"]
        if change == "coverage":
            provenance["coverage"]["eligible_for_full_rule_comparison"] = True
        elif change == "definition":
            provenance["definition"]["program"]["definition"]["title"] = "invented"
        else:
            provenance["trial"]["status"] = "invented"

    rehash_journal(run.directory, edit)
    with pytest.raises(ValueError, match="benchmark_c_.*(mismatch|changed)"):
        api.compare_collection(run.directory)


def test_prepared_command_is_bound_by_exact_original_id_and_bytes(tmp_path):
    _, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    start_bound(run, client, program, binding)
    suggested = {"kind": "input_sequence", "request": {"field_goal": "query", "text": "current",
        "target_memory": program["definition"]["steps"][0]["action"]["target_memory"]}}
    client.result = {"status": "returned", "result": {"run_id": "trial-one", "execution_strategy": "learned",
        "status": "pending", "step_id": "search", "execution_request_id": "issued-execution", "suggested_command": suggested}}
    call(run, "prepare-one", command("prepare", binding, run_id="trial-one"))
    with pytest.raises(ValueError, match="not_bound_to_trial"):
        call(run, "replacement-execution", suggested)
    changed = deepcopy(suggested)
    changed["request"]["text"] = "other"
    with pytest.raises(ValueError, match="not_bound_to_trial"):
        call(run, "issued-execution", changed)
    client.result = {"status": "returned", "result": {"text": "current"}}
    call(run, "issued-execution", suggested)


def test_bound_c_ready_trial_is_not_completed_even_if_outcome_value_matches(tmp_path):
    _, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    trial = start_bound(run, client, program, binding)
    client.result = {"status": "returned", "result": {**trial, "text": "current"}}
    call(run, "still-ready", command("status", binding, run_id="trial-one"))
    row = run.finish(request_id="still-ready", assessment=ASSESSMENT)
    assert row["completed"] is False
    assert row["first_attempt_success"] is False


def prepared_agent_case(tmp_path):
    api, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    trial = start_bound(run, client, program, binding)
    suggested = {"kind": "input_sequence", "request": {"field_goal": "query", "text": "current"}}
    pending = {"step_id": "search", "execution_request_id": "issued-execution", "suggested_command": suggested}
    trial.update(status="pending", pending=pending)
    client.result = {"status": "returned", "result": deepcopy(trial)}
    call(run, "prepare-agent", command("prepare", binding, run_id="trial-one"))
    job = {"contract_version": "agent_command.v1", "command_id": "issued-execution",
        "status": "awaiting_grounding", "pending_grounding": {"request_id": "ag-one"}}
    path = Path(client.session_directory) / "agent-commands/issued-execution.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job), encoding="utf-8")
    return api, run, client, trial, job, binding


@pytest.mark.parametrize("kind,payload", [
    ("agent_command_status", {"command_id": "issued-execution"}),
    ("agent_command_cancel", {"command_id": "issued-execution"}),
    ("agent_command_continue", {"command_id": "issued-execution", "grounding_request_id": "ag-one"}),
    ("grounding_resolve", {"grounding_request_id": "ag-one", "result": {"status": "absent"}}),
    ("grounding_status", {"grounding_request_id": "ag-one"}),
    ("grounding_cancel", {"grounding_request_id": "ag-one"}),
])
def test_bound_agent_handoff_preserves_parent_and_replays_offline(tmp_path, kind, payload):
    api, run, client, trial, job, binding = prepared_agent_case(tmp_path)
    client.result = {"status": "returned", "result": job if kind.startswith("agent_command") else {"phase": "absent"}}
    call(run, "handoff-one", {"kind": kind, "request": payload})
    client.result = {"status": "returned", "result": {**trial, "status": "completed", "text": "current"}}
    call(run, "done", command("status", binding, run_id="trial-one"))
    run.finish(request_id="done", assessment=ASSESSMENT)
    assert api.compare_collection(run.directory)["workflow_provenance"][0]["status"] == "bound"


@pytest.mark.parametrize("change", ["parent", "grounding", "attempt", "job_parent"])
def test_bound_handoff_rejects_wrong_parent_grounding_or_attempt(tmp_path, change):
    _, run, client, _, job, _ = prepared_agent_case(tmp_path)
    request = {"command_id": "issued-execution", "grounding_request_id": "ag-one"}
    if change == "parent":
        request["command_id"] = "other"
    elif change == "grounding":
        request["grounding_request_id"] = "ag-other"
    elif change == "attempt":
        run._tickets["issued-execution"]["attempt_id"] = "other"
    else:
        job["command_id"] = "other"
        (Path(client.session_directory) / "agent-commands/issued-execution.json").write_text(json.dumps(job), encoding="utf-8")
    with pytest.raises(ValueError, match="benchmark_"):
        call(run, "wrong-handoff", {"kind": "agent_command_continue", "request": request})


@pytest.mark.parametrize("change", [None, "run", "step", "execution", "synthesis"])
def test_bound_telemetry_requires_exact_original_workflow_scope(tmp_path, change):
    _, run, client, _, _, _ = prepared_agent_case(tmp_path)
    scope = {"kind": "workflow", "run_id": "trial-one", "step_id": "search", "execution_request_id": "issued-execution"}
    if change:
        scope[{"run": "run_id", "step": "step_id", "execution": "execution_request_id", "synthesis": "kind"}[change]] = "other"
    client.result = {"status": "returned", "result": {"recorded": True}}
    cmd = {"kind": "learning_workflow", "request": {"action": "record_model_call", "scope": scope,
        "model_call": {"provider": "test", "model": "test", "call_id": "actual-one", "source": "agent_current",
            "phase": "grounding", "status": "success", "usage": None}}}
    if change:
        with pytest.raises(ValueError, match="benchmark_"):
            call(run, "telemetry", cmd)
    else:
        call(run, "telemetry", cmd)
        assert client.calls[-1][1]["command"] == cmd


def test_offline_replay_rejects_second_start_with_new_outer_id(tmp_path):
    api, run, client, program, binding = bound_collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    trial = start_bound(run, client, program, binding)
    client.result = {"status": "returned", "result": {**trial, "status": "completed", "text": "current"}}
    call(run, "done", command("status", binding, run_id="trial-one"))
    run.finish(request_id="done", assessment=ASSESSMENT)

    def edit(events):
        copies = [deepcopy(event) for event in events if event["kind"] in {"call", "receipt"}
            and (event["payload"].get("request_id") == "trial-start"
                 or event["payload"].get("arguments", {}).get("request_id") == "trial-start")]
        for event in copies:
            if event["kind"] == "call":
                event["payload"]["arguments"]["request_id"] = "second-start"
            else:
                event["payload"]["request_id"] = "second-start"
                event["payload"]["receipt"]["request_id"] = "second-start"
        index = next(i for i, event in enumerate(events) if event["kind"] == "finish")
        events[index:index] = copies

    rehash_journal(run.directory, edit)
    with pytest.raises(ValueError, match="benchmark_(one_trial|trial_reused)"):
        api.compare_collection(run.directory)


def test_handoff_refresh_rejects_previous_grounding_after_job_changes(tmp_path):
    _, run, client, _, job, _ = prepared_agent_case(tmp_path)
    client.result = {"status": "returned", "result": {"phase": "absent"}}
    call(run, "resolve-one", {"kind": "grounding_status", "request": {"grounding_request_id": "ag-one"}})
    job["pending_grounding"]["request_id"] = "ag-two"
    (Path(client.session_directory) / "agent-commands/issued-execution.json").write_text(json.dumps(job), encoding="utf-8")
    with pytest.raises(ValueError, match="benchmark_handoff_grounding_mismatch"):
        call(run, "stale-continue", {"kind": "agent_command_continue",
            "request": {"command_id": "issued-execution", "grounding_request_id": "ag-one"}})


@pytest.mark.parametrize("change", ["job_text", "outer_command", "attempt"])
def test_offline_handoff_snapshot_cannot_be_reassigned(tmp_path, change):
    api, run, client, trial, _, binding = prepared_agent_case(tmp_path)
    client.result = {"status": "returned", "result": {"phase": "absent"}}
    call(run, "resolve-one", {"kind": "grounding_status", "request": {"grounding_request_id": "ag-one"}})
    client.result = {"status": "returned", "result": {**trial, "status": "completed", "text": "current"}}
    call(run, "done", command("status", binding, run_id="trial-one"))
    run.finish(request_id="done", assessment=ASSESSMENT)

    def edit(events):
        handoff = next(event["payload"] for event in events if event["kind"] == "workflow_handoff")
        if change == "job_text":
            handoff["evidence"]["text"] += " "
        elif change == "outer_command":
            handoff["command"]["request"]["grounding_request_id"] = "ag-other"
        else:
            handoff["attempt_id"] = "other-attempt"

    rehash_journal(run.directory, edit)
    with pytest.raises((ValueError, KeyError)):
        api.compare_collection(run.directory)


@pytest.mark.parametrize("key", ["program_id", "workflow_id", "project_snapshot_id", "start_step_id", "inputs", "execution_strategy"])
def test_full_trial_receipt_cannot_change_frozen_identity(tmp_path, key):
    _, run, client, trial, _, binding = prepared_agent_case(tmp_path)
    trial[key] = {} if key == "inputs" else "other"
    client.result = {"status": "returned", "result": trial}
    with pytest.raises(ValueError, match="benchmark_"):
        call(run, "changed-state", command("status", binding, run_id="trial-one"))


@pytest.mark.parametrize("kind", ["agent_command_continue", "grounding_resolve", "grounding_status", "agent_command_cancel"])
def test_deadline_allows_reconciliation_but_not_resumed_dispatch(tmp_path, kind):
    _, run, client, _, job, _ = prepared_agent_case(tmp_path)
    run._active["started_ns"] = 0
    payload = {"command_id": "issued-execution"} if kind.startswith("agent_command") else {"grounding_request_id": "ag-one"}
    if kind == "agent_command_continue":
        payload["grounding_request_id"] = "ag-one"
    if kind == "grounding_resolve":
        payload["result"] = {"status": "absent"}
    client.result = {"status": "returned", "result": job if kind.startswith("agent_command") else {"phase": "absent"}}
    if kind in {"agent_command_continue", "grounding_resolve"}:
        with pytest.raises(ValueError, match="benchmark_deadline_exceeded"):
            call(run, "expired", {"kind": kind, "request": payload})
    else:
        call(run, "expired", {"kind": kind, "request": payload})


@pytest.mark.parametrize("value", [[], "bad", None])
def test_bound_guard_rejects_non_object_request(tmp_path, value):
    _, run, _, _, _, _ = prepared_agent_case(tmp_path)
    with pytest.raises(ValueError, match="benchmark_workflow_request_invalid"):
        call(run, "invalid-object", {"kind": "learning_workflow", "request": value})


@pytest.mark.parametrize("variation", ["negative", "recovery"])
def test_negative_and_recovery_diagnostics_do_not_enter_positive_c_qualification(tmp_path, variation):
    root, path = frozen(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    spec = {key: manifest[key] for key in ("benchmark_id", "model", "cases", "artifacts")}
    spec["cases"].append({**spec["cases"][0], "case_id": "diagnostic-case",
        "variation": variation, "is_negative": True})
    target = tmp_path / "diagnostic-manifest.json"
    freeze_manifest(spec, root=root, destination=target)
    api = module()
    client = ConnectedClient(tmp_path / "session")
    run = api.BenchmarkCollection(manifest_path=target, root=root, directory=tmp_path / "collection", client=client)
    run.begin(case_id="diagnostic-case", route="C")
    call(run, "diagnostic", {"kind": "read_text"})
    run.finish(request_id="diagnostic", assessment=ASSESSMENT)
    report = api.compare_collection(run.directory)
    assert report["c_route_contract"]["scope"] == "scored_positive_nonrecovery"
    assert report["c_route_contract"]["scored_attempts"] == 0
    assert report["workflow_provenance"][0]["is_negative"] is True
    assert report["workflow_provenance"][0]["variation"] == variation
    assert len(report["runs"] + report["excluded_learning_warmup_recovery"]) == 1
    assert "c_route_definition_unbound" not in report["limitations"]
    api.export_comparison(report, tmp_path / "output/comparison.json")
    text = (tmp_path / "output/report.md").read_text(encoding="utf-8")
    assert "scored_positive_nonrecovery" in text
    assert "bound_definitions=0" in text
    assert "eligible_for_full_rule_comparison=false" in text


def test_cancel_ack_does_not_remain_pending_after_original_execution_is_reconciled(tmp_path):
    api, run, client, trial, job, binding = prepared_agent_case(tmp_path)
    client.result = {"status": "returned", "result": {**job, "cancel_requested": True}}
    call(run, "cancel-ack", {"kind": "agent_command_cancel", "request": {"command_id": "issued-execution"}})
    client.result = {"status": "returned", "result": {**job, "status": "cancelled"}}
    call(run, "cancel-result", {"kind": "agent_command_status", "request": {"command_id": "issued-execution"}})
    client.result = {"status": "returned", "result": {**trial, "status": "cancelled", "text": "current"}}
    call(run, "cancelled-trial", command("status", binding, run_id="trial-one"))
    assert run.finish(request_id="cancelled-trial", assessment=ASSESSMENT)["completed"] is False
    report = api.compare_collection(run.directory)
    assert "unresolved_requests" not in report["limitations"]
    run.begin(case_id="query_verify-1", route="A")


def test_offline_replay_preserves_baseline_no_memory_policy(tmp_path):
    from tests.test_benchmark_collection import collection
    api, run, _, _ = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    call(run, "baseline-read", {"kind": "read_text"})
    run.finish(request_id="baseline-read", assessment=ASSESSMENT)

    def edit(events):
        intent = next(event for event in events if event["kind"] == "call")
        intent["payload"]["arguments"]["command"]["request"] = {"target_memory": {"recipe_id": "invented"}}

    rehash_journal(run.directory, edit)
    with pytest.raises(ValueError, match="benchmark_route_target_memory_forbidden"):
        api.compare_collection(run.directory)


def internal_read_case(tmp_path, route="C"):
    api, run, client, program, binding = bound_collection(tmp_path, with_read=True)
    run.begin(case_id="query_verify-0", route=route)
    read_bound(run, client, program, binding)
    trial = {key: binding[key] for key in ("workflow_id", "program_id", "project_snapshot_id", "start_step_id")}
    trial.update(run_id="trial-one", execution_strategy="learned" if route == "C" else "steps_only",
                 inputs={"value": "current"}, status="ready", current_step_id="search", history=[], pending=None)
    client.result = {"status": "returned", "result": deepcopy(trial)}
    call(run, "trial-start", command("start", binding))
    original = {"kind": "read_text", "max_chars": 10000}
    trial.update(status="pending", current_step_id="read", pending={"step_id": "read",
        "execution_request_id": "internal-read", "suggested_command": original})
    client.result = {"status": "returned", "result": deepcopy(trial)}
    call(run, "runner-status", command("status", binding, run_id="trial-one"))
    receipt = {"status": "returned", "command": original,
               "result": {"status": "agent_read_required", "text": None, "action_executed": False}}
    session = Path(client.session_directory)
    for folder, value in (("commands", original), ("responses", receipt)):
        path = session / folder / "internal-read.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    from app.instant_mcp import InstantSession
    public = InstantSession(tmp_path, tmp_path / "unused-runtime", recognition_source="agent_current")
    public.session = session
    client.result = public.result("internal-read")
    return api, run, client, trial, binding, receipt


@pytest.mark.parametrize("route", ["B", "C"])
def test_bound_runner_internal_read_result_finishes_and_replays_without_dispatch(tmp_path, route):
    api, run, client, trial, binding, _ = internal_read_case(tmp_path, route)
    receipt = asyncio.run(run.call("instant_result", {"request_id": "internal-read", "detail": "full"}))
    assert receipt["result"]["status"] == "agent_read_required"
    assert "command" not in receipt
    assert not any(args.get("request_id") == "internal-read" and tool != "instant_result" for tool, args in client.calls)
    client.result = {"status": "returned", "result": {**trial, "pending": None, "status": "completed", "text": "current"}}
    call(run, "done", command("status", binding, run_id="trial-one"))
    row = run.finish(request_id="done", assessment=ASSESSMENT)
    assert row["completed"] is True
    events = [json.loads(line) for line in (run.directory / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[-1]["payload"]["unresolved_requests"] == []
    report = api.compare_collection(run.directory)
    assert report["runs"][0]["completed"] is True
    assert report["empirical_acceptance"] is False
    if route == "C":
        assert report["workflow_provenance"][0]["coverage"]["eligible_for_full_rule_comparison"] is False


@pytest.mark.parametrize("change", ["unknown", "attempt", "run", "pending", "definition", "missing_command", "missing_response",
                                         "command", "response_command", "response_identity", "not_returned", "path"])
def test_internal_read_requires_bound_original_dispatched_files(tmp_path, change):
    _, run, client, _, _, receipt = internal_read_case(tmp_path)
    request_id = "internal-read"
    session = Path(client.session_directory)
    if change == "unknown":
        request_id = "unknown"
    elif change == "attempt":
        run._tickets[request_id]["attempt_id"] = "other"
    elif change == "run":
        run._tickets[request_id]["run_id"] = "other"
    elif change == "pending":
        run._trials["trial-one"]["trial"]["pending"]["execution_request_id"] = "other"
    elif change == "definition":
        run._definitions.clear()
    elif change.startswith("missing_"):
        folder = "commands" if change == "missing_command" else "responses"
        (session / folder / (request_id + ".json")).rename(session / folder / "unrelated.json")
    elif change == "command":
        (session / "commands" / (request_id + ".json")).write_text('{"kind":"read_text","max_chars":1}', encoding="utf-8")
    elif change in {"response_command", "response_identity", "not_returned"}:
        if change == "response_command":
            receipt["command"] = {"kind": "capture"}
        elif change == "response_identity":
            receipt["request_id"] = "other"
        else:
            receipt["status"] = "pending"
        (session / "responses" / (request_id + ".json")).write_text(json.dumps(receipt), encoding="utf-8")
    else:
        request_id = "../internal-read"
        run._tickets[request_id] = run._tickets["internal-read"]
        run._trials["trial-one"]["trial"]["pending"]["execution_request_id"] = request_id
    before = len(client.calls)
    with pytest.raises(ValueError, match="benchmark_"):
        asyncio.run(run.call("instant_result", {"request_id": request_id}))
    assert len(client.calls) == before


@pytest.mark.parametrize("change", ["ticket", "dispatch_text", "dispatch_ref", "attempt", "poll_identity", "receipt_command"])
def test_internal_result_replay_rejects_rehashed_binding_or_dispatch_tampering(tmp_path, change):
    api, run, _, _, _, _ = internal_read_case(tmp_path)
    asyncio.run(run.call("instant_result", {"request_id": "internal-read"}))
    def edit(events):
        source = next(event["payload"] for event in events if event["kind"] == "workflow_internal_result")
        if change == "ticket":
            source["ticket"]["step_id"] = "search"
        elif change == "dispatch_text":
            source["evidence"]["response"]["text"] += " "
        elif change == "dispatch_ref":
            source["evidence"]["command"]["ref"] = "commands/other.json"
        elif change == "attempt":
            source["attempt_id"] = "other"
        elif change == "poll_identity":
            event = next(event for event in events if event["kind"] == "call" and event["payload"]["tool"] == "instant_result")
            event["payload"]["arguments"]["request_id"] = "other"
        else:
            event = next(event for event in events if event["kind"] == "receipt" and event["payload"]["tool"] == "instant_result")
            event["payload"]["receipt"]["command"] = {"kind": "capture"}
    rehash_journal(run.directory, edit)
    with pytest.raises(ValueError, match="benchmark_"):
        api.compare_collection(run.directory)


def test_internal_result_keeps_steps_only_no_memory_policy(tmp_path):
    _, run, client, _, _, receipt = internal_read_case(tmp_path, "B")
    changed = {"kind": "read_text", "max_chars": 10000, "request": {"target_memory": {"recipe_id": "invented"}}}
    run._tickets["internal-read"]["command"] = changed
    run._trials["trial-one"]["trial"]["pending"]["suggested_command"] = changed
    receipt["command"] = changed
    session = Path(client.session_directory)
    for folder, value in (("commands", changed), ("responses", receipt)):
        (session / folder / "internal-read.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="benchmark_route_target_memory_forbidden"):
        asyncio.run(run.call("instant_result", {"request_id": "internal-read"}))


def internal_agent_case(tmp_path, state):
    api, run, client, trial, job, binding = prepared_agent_case(tmp_path)
    original = trial["pending"]["suggested_command"]
    job = {**job, "status": state, "request": {"private": "original input"}}
    if state == "running":
        job["pending_grounding"] = None
    receipt = {"status": "returned", "command": original, "result": job}
    session = Path(client.session_directory)
    for folder, value in (("commands", original), ("responses", receipt)):
        path = session / folder / "issued-execution.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    from app.instant_mcp import InstantSession
    public = InstantSession(tmp_path, tmp_path / "unused-runtime", recognition_source="agent_current")
    public.session = session
    client.result = public.result("issued-execution")
    return api, run, client, trial, job, binding, receipt


@pytest.mark.parametrize("state", ["running", "awaiting_grounding"])
@pytest.mark.parametrize("settled", [False, True])
def test_internal_agent_readback_requires_original_worker_terminal_for_settlement(tmp_path, state, settled):
    api, run, client, trial, job, binding, _ = internal_agent_case(tmp_path, state)
    receipt = asyncio.run(run.call("instant_result", {"request_id": "issued-execution", "detail": "full"}))
    assert receipt["result"]["status"] == state
    assert "command" not in receipt and "request" not in receipt["result"]
    assert not api._terminal(receipt) and not api._succeeded(receipt)
    if settled:
        client.result = {"status": "returned", "result": {**job, "status": "completed"}}
        call(run, "worker-terminal", {"kind": "agent_command_status", "request": {"command_id": "issued-execution"}})
    client.result = {"status": "returned", "result": {**trial, "pending": None, "status": "completed", "text": "current"}}
    call(run, "done", command("status", binding, run_id="trial-one"))
    row = run.finish(request_id="done", assessment=ASSESSMENT)
    assert row["completed"] is settled
    events = [json.loads(line) for line in (run.directory / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ("issued-execution" in events[-1]["payload"]["unresolved_requests"]) is not settled
    report = api.compare_collection(run.directory)
    assert report["runs"][0]["completed"] is settled
    assert ("unresolved_requests" in report["limitations"]) is not settled


@pytest.mark.parametrize("change", ["command_id", "missing_command_id", "unknown_state", "pending_outer", "snapshot_sha"])
def test_internal_agent_readback_rejects_invalid_envelopes(tmp_path, change):
    api, run, client, _, _, _, receipt = internal_agent_case(tmp_path, "running")
    session = Path(client.session_directory)
    if change == "command_id":
        receipt["result"]["command_id"] = "other"
    elif change == "missing_command_id":
        receipt["result"].pop("command_id")
    elif change == "unknown_state":
        receipt["result"]["status"] = "invented"
    elif change == "pending_outer":
        receipt["status"] = "pending"
    else:
        source = api._current_internal_result(run.manifest, run._active, "issued-execution",
            run._definitions, run._tickets, run._trials, session)
        source["evidence"]["response"]["sha256"] = "0" * 64
        with pytest.raises(ValueError, match="snapshot_changed"):
            api._internal_result_source(run.manifest, run._active, "issued-execution",
                run._definitions, run._tickets, run._trials, source["evidence"])
        return
    (session / "responses/issued-execution.json").write_text(json.dumps(receipt), encoding="utf-8")
    before = len(client.calls)
    with pytest.raises(ValueError, match="response_mismatch"):
        asyncio.run(run.call("instant_result", {"request_id": "issued-execution"}))
    assert len(client.calls) == before


@pytest.mark.parametrize("change", ["attempt", "run", "ticket", "command", "response_command"])
def test_internal_agent_readback_preserves_binding_checks(tmp_path, change):
    _, run, client, _, _, _, receipt = internal_agent_case(tmp_path, "running")
    session = Path(client.session_directory)
    ticket = run._tickets["issued-execution"]
    if change == "attempt":
        ticket["attempt_id"] = "other"
    elif change == "run":
        ticket["run_id"] = "other"
    elif change == "ticket":
        ticket["step_id"] = "other"
    elif change == "command":
        (session / "commands/issued-execution.json").write_text('{"kind":"capture"}', encoding="utf-8")
    else:
        receipt["command"] = {"kind": "capture"}
        (session / "responses/issued-execution.json").write_text(json.dumps(receipt), encoding="utf-8")
    before = len(client.calls)
    with pytest.raises(ValueError, match="benchmark_"):
        asyncio.run(run.call("instant_result", {"request_id": "issued-execution"}))
    assert len(client.calls) == before


@pytest.mark.parametrize("change", ["command_id", "unknown_state"])
def test_internal_agent_replay_rejects_rehashed_envelope_tampering(tmp_path, change):
    api, run, _, _, _, _, _ = internal_agent_case(tmp_path, "running")
    asyncio.run(run.call("instant_result", {"request_id": "issued-execution"}))
    def edit(events):
        source = next(event["payload"] for event in events if event["kind"] == "workflow_internal_result")
        snapshot = source["evidence"]["response"]
        value = json.loads(snapshot["text"])
        value["result"]["command_id" if change == "command_id" else "status"] = "other"
        snapshot["text"] = json.dumps(value)
        snapshot["sha256"] = sha256(snapshot["text"].encode("utf-8")).hexdigest()
    rehash_journal(run.directory, edit)
    with pytest.raises(ValueError, match="response_mismatch"):
        api.compare_collection(run.directory)


def test_collector_snapshots_windows_rule_references_only_once(tmp_path):
    _, run, client, trial, _, _ = internal_read_case(tmp_path)
    trial["history"] = [{"step_id": "read", "execution_request_id": "internal-read",
        "verification": {"evidence_refs": ["responses\\internal-read.json",
            "workflow-observations\\verify.json"]}}]
    run._trials["trial-one"]["trial"] = trial
    original = '{"observation":{"evidence_ref":"workflow-observations\\\\verify.json"}}'
    path = Path(client.session_directory) / "workflow-observations/verify.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(original, encoding="utf-8")
    result = run._provenance()
    refs = [item["ref"] for item in result["evidence_files"]]
    assert refs.count("responses/internal-read.json") == 1
    assert refs.count("workflow-observations/verify.json") == 1
    assert next(item["text"] for item in result["evidence_files"]
                if item["ref"] == "workflow-observations/verify.json") == original
    assert trial["history"][0]["verification"]["evidence_refs"][0] == "responses\\internal-read.json"


def test_collector_windows_reference_cannot_escape_session(tmp_path):
    _, run, client, trial, _, _ = internal_read_case(tmp_path)
    trial["history"] = [{"step_id": "read", "execution_request_id": "internal-read",
        "verification": {"evidence_refs": ["..\\outside.json"]}}]
    run._trials["trial-one"]["trial"] = trial
    outside = Path(client.session_directory).parent / "outside.json"
    outside.write_text('{"private":"outside"}', encoding="utf-8")
    result = run._provenance()
    assert "evidence_ref_outside_session" in result["collection_errors"]
    assert all(item.get("text") != outside.read_text(encoding="utf-8") for item in result["evidence_files"])
