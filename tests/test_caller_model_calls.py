"""调用方凭据独立记账，不把业务交接或跨进程时钟当模型用量。"""
import json

import pytest

from app.learning_memory.workflow_control import workflow_control
from app.learning_memory.workflow_metrics import load_run_metrics
from tests.test_workflow_trial import services, response, WORKFLOW
from tests.test_workflow_runtime import runtime_scene
from test_learning_synthesis import _stop, _reply
from test_learning_action_evidence import repeated_state
from test_learning_observation_source import observation_scene


def call_record(**changes):
    value = {"provider": "test-provider", "model": "test-model", "call_id": "provider-call-1",
             "source": "agent_current", "phase": "verification", "status": "success",
             "usage": {"input_tokens": 11, "output_tokens": 3}, "elapsed_ms": 12.5}
    value.update(changes)
    return value


def prepared(services):
    programs, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "new"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    response(session, ticket)
    scope = {"kind": "workflow", "run_id": run["run_id"], "step_id": "search",
             "execution_request_id": ticket["execution_request_id"]}
    return programs.library, trials, run, scope


def record(library, session, scope, call, request_id="report-1"):
    return workflow_control(library, session,
        {"action": "record_model_call", "scope": scope, "model_call": call}, request_id)


def test_original_workflow_receipt_binds_report_without_settling_step(services):
    library, trials, run, scope = prepared(services)
    before = trials.status(run["run_id"])
    result = record(library, trials.session, scope, call_record())
    assert result["status"] == "recorded" and result["input_executed"] is False
    assert trials.status(run["run_id"]) == before
    report = load_run_metrics(trials.session, run["run_id"])
    assert report["caller_reported"]["model_calls"] == {"planning": 0, "grounding": 0, "verification": 1, "total": 1}
    assert report["caller_reported"]["usage"] == {"input_tokens": 11, "output_tokens": 3, "total_tokens": 14}
    assert report["caller_reported"]["elapsed_ms_sum"] == 12.5
    assert report["caller_reported"]["independently_verified"] is False
    assert report["observed"]["model_calls"]["total"] == 0
    assert report["observed"]["wall_elapsed_ns"] == 0
    assert report["total_model_calls"] is None and report["total_usage"] is None


def test_duplicate_call_is_idempotent_and_conflicting_usage_is_rejected(services):
    library, trials, run, scope = prepared(services)
    first = record(library, trials.session, scope, call_record())
    assert record(library, trials.session, scope, call_record(), "report-again") == first
    with pytest.raises(ValueError, match="conflict"):
        record(library, trials.session, scope, call_record(usage={"input_tokens": 99, "output_tokens": 0}))
    assert load_run_metrics(trials.session, run["run_id"])["caller_reported"]["model_calls"]["total"] == 1


@pytest.mark.parametrize("change", [
    {"call_id": ""}, {"usage": {"input_tokens": True, "output_tokens": 1}},
    {"usage": {"input_tokens": 1}}, {"elapsed_ms": float("nan")},
    {"phase": "wait"}, {"started_ns": 20}, {"status": "pending"},
])
def test_bad_telemetry_is_rejected_without_creating_receipts(services, change):
    library, trials, _, scope = prepared(services)
    with pytest.raises(ValueError):
        record(library, trials.session, scope, call_record(**change))
    assert not (trials.session / "caller-model-calls").exists()


def test_wrong_step_binding_is_rejected_and_missing_usage_stays_unknown(services):
    library, trials, run, scope = prepared(services)
    with pytest.raises(ValueError, match="binding"):
        record(library, trials.session, {**scope, "step_id": "open"}, call_record())
    record(library, trials.session, scope, call_record())
    record(library, trials.session, scope, call_record(call_id="provider-call-2", status="timeout", usage=None, elapsed_ms=None))
    result = load_run_metrics(trials.session, run["run_id"])["caller_reported"]
    assert result["model_calls"]["total"] == 2
    assert result["usage"] is None and result["usage_observed_calls"] == 1
    assert result["status_counts"] == {"success": 1, "timeout": 1}
    assert result["elapsed_ms_sum"] is None


def test_changed_or_corrupt_receipt_is_visible_without_breaking_existing_metrics(services):
    library, trials, run, scope = prepared(services)
    result = record(library, trials.session, scope, call_record())
    path = trials.session / result["evidence_ref"]
    original = path.read_bytes()
    path.write_bytes(b"{broken")
    report = load_run_metrics(trials.session, run["run_id"])
    assert report["caller_reported"]["status"] == "unavailable"
    assert report["observed"]["event_count"] == 0 and report["total_model_calls"] is None
    assert path.read_bytes() == b"{broken"
    path.write_bytes(original)
    assert load_run_metrics(trials.session, run["run_id"])["caller_reported"]["model_calls"]["total"] == 1


def test_one_provider_call_cannot_be_reassigned_to_another_run(services):
    library, trials, run, scope = prepared(services)
    record(library, trials.session, scope, call_record())
    trials.review(run["run_id"], "review", scope["execution_request_id"], "uncertain", {}, {})
    other = trials.start(WORKFLOW, run["program_id"], "search", {"query": "other"}, "start-other")
    ticket = trials.prepare(other["run_id"], "prepare-other")
    response(trials.session, ticket)
    other_scope = {**scope, "run_id": other["run_id"], "execution_request_id": ticket["execution_request_id"]}
    with pytest.raises(ValueError, match="conflict"):
        record(library, trials.session, other_scope, call_record())


def test_synthesis_reports_actual_supplied_usage_separately_from_handoff(repeated_state):
    store, _, _, _, _ = repeated_state
    original = _stop(store)["synthesis_request"]
    completed = store.control("learning_workflow", _reply(original), "synthesis-reply")
    assert completed["metrics"]["total_model_calls"] is None
    scope = {"kind": "synthesis", "synthesis_id": original["synthesis_id"],
             "source_sha256": original["source_sha256"], "reply_request_id": "synthesis-reply"}
    request = {"action": "record_model_call", "scope": scope, "model_call": call_record(phase="planning")}
    from app.instant_mcp import InstantCommand
    assert InstantCommand.model_validate({"kind": "learning_workflow", "request": request}).command()["request"] == request
    store.control("learning_workflow", request, "report-synthesis")
    status = store.control("learning_workflow", {"action": "synthesis_status", "synthesis_id": original["synthesis_id"]}, "read-synthesis")
    assert status["metrics"]["caller_reported"]["model_calls"]["planning"] == 1
    assert status["metrics"]["caller_reported"]["usage"]["total_tokens"] == 14
    assert status["metrics"]["total_model_calls"] is None
    assert status["metrics"]["total_usage"] is None
    assert status["draft"] == completed["draft"]
    with pytest.raises(ValueError, match="binding"):
        store.control("learning_workflow", {**request, "scope": {**scope, "reply_request_id": "other-reply"}}, "wrong-reply")


def test_valid_json_tampering_is_detected_in_caller_summary(services):
    library, trials, run, scope = prepared(services)
    result = record(library, trials.session, scope, call_record())
    path = trials.session / result["evidence_ref"]
    value = json.loads(path.read_text(encoding="utf-8"))
    value["model_call"]["usage"]["input_tokens"] = 10000
    path.write_text(json.dumps(value), encoding="utf-8")
    assert load_run_metrics(trials.session, run["run_id"])["caller_reported"]["status"] == "unavailable"


def test_replaced_original_workflow_receipt_invalidates_reported_usage(services):
    library, trials, run, scope = prepared(services)
    record(library, trials.session, scope, call_record())
    path = trials.session / "responses" / (scope["execution_request_id"] + ".json")
    path.write_bytes(path.read_bytes() + b"\n")
    report = load_run_metrics(trials.session, run["run_id"])
    assert report["caller_reported"]["status"] == "unavailable"
    assert report["observed"]["event_count"] == 0 and report["total_usage"] is None


def test_changed_synthesis_completion_invalidates_only_reported_metrics(repeated_state):
    from app.learning_memory.workspace import MemoryWorkspace
    store, _, _, _, _ = repeated_state
    original = _stop(store)["synthesis_request"]
    store.control("learning_workflow", _reply(original), "synthesis-reply")
    scope = {"kind": "synthesis", "synthesis_id": original["synthesis_id"],
             "source_sha256": original["source_sha256"], "reply_request_id": "synthesis-reply"}
    result = store.control("learning_workflow", {"action": "record_model_call", "scope": scope,
        "model_call": call_record(phase="planning")}, "report-synthesis")
    receipt = json.loads((store.session / result["evidence_ref"]).read_text(encoding="utf-8"))
    with MemoryWorkspace(store.session.parent / "memory-library") as library:
        completion = library._artifact_root / receipt["binding"]["evidence_ref"]
        completion.write_bytes(completion.read_bytes() + b"\n")
    status = store.control("learning_workflow", {"action": "synthesis_status", "synthesis_id": original["synthesis_id"]}, "read-synthesis")
    assert status["status"] == "draft_ready"
    assert status["metrics"]["caller_reported"]["status"] == "unavailable"
    assert status["metrics"]["total_usage"] is None


def test_original_runtime_status_and_host_report_expose_caller_usage_without_dispatch(runtime_scene):
    from scripts.run_local_step_session import record_workflow_control
    runtime, trials, run, session, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "single"}, "start-runtime")
    ticket = trials.status(run["run_id"])["pending"]
    response(session, ticket)
    command_ids = sorted(path.name for path in (session / "commands").glob("*.json"))
    before = runtime.control({"action": "status", "run_id": run["run_id"]}, "before-report")
    scope = {"kind": "workflow", "run_id": run["run_id"], "step_id": ticket["step_id"],
             "execution_request_id": ticket["execution_request_id"]}
    record(trials.programs.library, session, scope, call_record())
    host_report = {}
    after = record_workflow_control(host_report, runtime,
        {"action": "status", "run_id": run["run_id"]}, "read-report")
    assert host_report["workflow_run"]["metrics"]["caller_reported"]["usage"]["total_tokens"] == 14
    assert "caller_reported" not in before["metrics"]
    assert after["metrics"]["observed"] == before["metrics"]["observed"]
    assert after["metrics"]["total_model_calls"] is None
    assert after["pending"] == before["pending"] and after["history"] == before["history"]
    assert sorted(path.name for path in (session / "commands").glob("*.json")) == command_ids
