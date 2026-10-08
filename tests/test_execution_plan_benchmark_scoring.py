"""原始收据与独立夹具真值计分；不启动宿主或调用判断服务。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def bundle(tmp_path):
    root = tmp_path / "fresh"
    session = root / "runtime" / ("session-" + "a" * 32)
    records = [{"id": "R-1", "name": "Record 1", "detail": "fresh-one"},
               {"id": "R-2", "name": "Record 2", "detail": "fresh-two"}]
    plan = {"schema_version": "task_plan.v1", "title": "Read two records", "inputs": {}, "steps": [
        {"step_id": f"step-{index}", "action": {"kind": "click", "goal": f"Open {row['id']}"},
         "verification": {"kind": "agent_judgment", "decision_condition":
             f"The current record detail area visibly shows exactly ID: {row['id']} | Detail: {row['detail']}."}}
        for index, row in enumerate(records)]}
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    source = {"schema_version": "task_plan_source.v1", "source_kind": "caller_plan", "plan_id": "task-plan-original",
        "plan_sha256": sha256(canonical).hexdigest(), "plan": plan, "owner_id": "owner-original",
        "session_directory": str(session), "target_identity": {"handle": 7, "process_id": 11, "process_create_time": 13.0}}
    history = []
    for index in range(2):
        execution = f"input-{index}"
        command = {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": f"Open R-{index + 1}"}}
        raw = {"request_id": execution, "status": "returned", "command": command,
               "started_at": f"2026-10-08T10:00:0{index + 1}+00:00",
               "finished_at": f"2026-10-08T10:00:0{index + 2}+00:00", "command_wall_ms": 1000,
               "result": {"status": "completed", "phase": "returned", "action_executed": True,
                   "target_identity": {"target_window_handle": 7, "process_id": 11, "process_create_time": 13.0},
                   "response": {"success": True}}}
        command_path, receipt_path = session / "commands" / f"{execution}.json", session / "responses" / f"{execution}.json"
        write(command_path, command)
        write(receipt_path, raw)
        history.append({"step_id": f"step-{index}", "execution_request_id": execution, "verdict": "success",
            "judged_by": "decision", "action_executed": True, "original_input_status": "completed",
            "evidence_refs": [{"path": f"commands/{execution}.json", "sha256": sha256(command_path.read_bytes()).hexdigest()},
                {"path": f"responses/{execution}.json", "sha256": sha256(receipt_path.read_bytes()).hexdigest()}]})
    state = {"schema": "task_plan_trial.v1", "source_kind": "caller_plan", "run_id": "trial-original",
        "start_request_id": "plan-start", "plan_id": source["plan_id"], "plan_sha256": source["plan_sha256"],
        "owner_id": source["owner_id"], "session_directory": str(session), "target_identity": source["target_identity"],
        "status": "completed", "pending": None, "current_step_id": None, "history": history}
    runner = {"schema": "workflow_runner.v1", "source_kind": "caller_plan", "run_id": state["run_id"],
              "start_request_id": "plan-start", "runner_state": "completed", "ticket": None, "wait": None,
              "steps_completed": 2}
    projected = {**state, "runner_state": "completed"}
    report = {"schema": "continuous_execution_live.v1", "session_directory": str(session), "plan": plan,
        "started_at": "2026-10-08T10:00:00+00:00", "ended_at": "2026-10-08T10:00:05+00:00",
        "plan_wall_ms": 3000, "intermediate_main_calls": 0, "events": [], "fixture_closed": True,
        "fixture_exit_code": 0, "result": {"original_request_id": "plan-start", "client_state": "terminal", "result": projected},
        "fixture_truth": {"correct_exact_order": True, "expected_order": ["R-1", "R-2"], "actual_order": ["R-1", "R-2"]}}
    start = {"kind": "task_plan", "request": {"action": "start", "plan": plan}}
    write(session / "commands" / "plan-start.json", start)
    write(session / "responses" / "plan-start.json", {"request_id": "plan-start", "status": "returned", "command": start,
        "result": {**state, "status": "pending", "history": [], "runner_state": "waiting"}})
    write(session / "task-plans" / "task-plan-original.json", source)
    write(session / "task-plans" / "trial-original.json", state)
    write(session / "task-plan-runners" / "trial-original.json", runner)
    host = {"phase": "stopped", "host_phase": "stopped", "cleanup_errors": [], "sampler_stopped": True,
        "finished_at": "2026-10-08T10:00:04+00:00", "task_plan_run": projected, "decision_service": {"mode": "auto"}}
    write(session / "report.json", host)
    write(root / "report.json", report)
    write(root / "fixture" / "manifest.json", {"pid": 11, "window_handle": 7})
    write(root / "fixture" / "closed.json", {"status": "closed", "exit_code": 0, "pid": 11})
    write(root / "fixture" / "oracle" / "records.json", {"schema": "learning_fixture_oracle.v1", "records": records})
    actions = [{"schema": "learning_fixture_action.v1", "event_index": index + 1, "action": "open_detail",
        "record_id": row["id"], "actual_detail": f"ID: {row['id']} | Detail: {row['detail']}",
        "case_id": None, "at": f"2026-10-08T10:00:0{index + 1}+00:00"} for index, row in enumerate(records)]
    actions.append({"schema": "learning_fixture_action.v1", "event_index": 3, "action": "fixture_closed",
                    "case_id": None, "at": "2026-10-08T10:00:04+00:00"})
    jsonl(root / "fixture" / "oracle" / "actions.jsonl", actions)
    calls = [{"tool": "instant_run", "request_id": "plan-start", "status": "returned", "elapsed_ms": 100},
        {"tool": "instant_status", "request_id": None, "status": "ready", "elapsed_ms": 10},
        {"tool": "instant_stop", "request_id": None, "status": "stopping", "elapsed_ms": 10},
        {"tool": "instant_status", "request_id": None, "status": "stopped", "elapsed_ms": 10}]
    jsonl(root / "client" / "calls.jsonl", calls)
    return root, session, report, state, runner, actions, calls


def score(root):
    from scripts.benchmark_execution_plan import score_execution_report
    return score_execution_report(root / "report.json")


def test_correct_oracle_completed_original_runner_and_cleanup_are_separate_proofs(tmp_path):
    root, session, *_ = bundle(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    result = score(root)
    assert result["outcome"] == "verified_success" and result["task_success"] is True
    assert result["cleanup"]["complete"] is True and result["complete_with_cleanup"] is True
    assert result["orchestration"]["client_adapter_pattern_supported"] is True
    assert result["orchestration"]["intermediate_main_calls"] is None
    assert result["comparison"]["median_improvement_percent"] is None
    assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("wrong", ["wrong_id", "stale_detail", "extra_open"])
def test_wrong_or_stale_oracle_never_accepts_reported_success(tmp_path, wrong):
    root, session, report, state, runner, actions, calls = bundle(tmp_path)
    if wrong == "wrong_id":
        actions[0]["record_id"] = "R-2"
    elif wrong == "stale_detail":
        actions[0]["actual_detail"] = "ID: R-1 | Detail: OLD VALUE"
    else:
        extra = deepcopy(actions[1])
        extra["event_index"] = 3
        actions.insert(2, extra)
        actions[-1]["event_index"] = 4
    jsonl(root / "fixture" / "oracle" / "actions.jsonl", actions)
    result = score(root)
    assert result["outcome"] == "false_success" and result["task_success"] is False


def test_waiting_original_state_is_not_completed_by_report_flags(tmp_path):
    root, session, report, state, runner, actions, calls = bundle(tmp_path)
    state.update(status="pending", history=state["history"][:1], pending={"execution_request_id": "input-1"})
    runner.update(runner_state="waiting", ticket={"execution_request_id": "input-1"}, steps_completed=1)
    write(session / "task-plans" / "trial-original.json", state)
    write(session / "task-plan-runners" / "trial-original.json", runner)
    report["zero_main_happy_path"] = True
    write(root / "report.json", report)
    result = score(root)
    assert result["outcome"] == "incomplete_or_unknown" and result["task_success"] is None


def test_missing_cleanup_proof_is_unknown_despite_reported_closed_flag(tmp_path):
    root, session, report, state, runner, actions, calls = bundle(tmp_path)
    write(session / "report.json", {"phase": "stopped", "task_plan_run": {**state, "runner_state": "completed"}})
    result = score(root)
    assert result["outcome"] == "verified_success" and result["cleanup"]["complete"] is None
    assert result["complete_with_cleanup"] is None


@pytest.mark.parametrize("change", ["duplicate_start", "extra_input", "callback", "missing_callbacks"])
def test_zero_main_flag_cannot_replace_bound_journal_and_callback_evidence(tmp_path, change):
    root, session, report, state, runner, actions, calls = bundle(tmp_path)
    if change == "duplicate_start":
        calls.insert(1, deepcopy(calls[0]))
    elif change == "extra_input":
        calls.insert(1, {"tool": "instant_run", "request_id": "unbound-input", "status": "returned", "elapsed_ms": 5})
    elif change == "callback":
        report["events"] = [{"schema": "task_plan_client_event.v1", "client_state": "verification_required"}]
    else:
        report.pop("events")
    jsonl(root / "client" / "calls.jsonl", calls)
    write(root / "report.json", report)
    result = score(root)
    assert result["orchestration"]["client_adapter_pattern_supported"] is not True
    assert result["orchestration"]["intermediate_main_calls"] is None


def test_changed_original_receipt_breaks_evidence_before_success(tmp_path):
    root, session, *_ = bundle(tmp_path)
    raw = json.loads((session / "responses" / "input-0.json").read_text(encoding="utf-8"))
    raw["result"]["action_executed"] = None
    write(session / "responses" / "input-0.json", raw)
    result = score(root)
    assert result["task_success"] is not True and "evidence_hash_changed" in result["runtime"]["errors"]


def test_nested_decision_times_are_not_added_and_queries_are_not_action_time(tmp_path):
    root, session, report, *_ = bundle(tmp_path)
    report["timeline_events"] = [
        {"kind": "action", "layer": "unknown", "clock_id": "test", "started_ns": 0, "ended_ns": 100000000},
        {"kind": "span", "layer": "decision", "clock_id": "test", "started_ns": 0, "ended_ns": 100000000},
        {"kind": "span", "layer": "decision", "clock_id": "test", "started_ns": 20000000, "ended_ns": 40000000},
        {"kind": "query", "layer": "input", "clock_id": "test", "started_ns": 0, "ended_ns": 900000000}]
    write(root / "report.json", report)
    result = score(root)
    assert result["timing"]["timeline"]["layers_ms"]["decision"] == 100
    assert result["timing"]["timeline"]["action_total_ms"] == 100
    assert result["timing"]["nested_timings_additive"] is False
    assert result["timing"]["client_journal_elapsed_sum_is_action_duration"] is False


def decision_ledger(session, *, unresolved=False):
    path = session / "judgments" / "decisions.sqlite3"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE dispatches(request_id TEXT PRIMARY KEY, request_sha256 TEXT, scope TEXT, dispatched INTEGER, marker_blob BLOB, result_blob BLOB)")
        db.execute("INSERT INTO dispatches VALUES(?,?,?,?,?,?)", ("decision-original", "e" * 64, "execution", 1, b"encrypted", None if unresolved else b"encrypted result"))
    return path


def test_dispatch_marker_without_provider_result_is_unknown_not_paid_zero(tmp_path):
    root, session, *_ = bundle(tmp_path)
    decision_ledger(session, unresolved=True)
    result = score(root)
    assert result["decision"]["session_dispatch_markers"] == 1
    assert result["decision"]["confirmed_provider_responses"] == 0
    assert result["decision"]["actual_paid_post_count"] is None
    assert result["decision"]["token_usage"] is None


def test_duplicate_decision_artifacts_count_one_bound_original_request(tmp_path):
    root, session, *_ = bundle(tmp_path)
    decision_ledger(session)
    artifact = {"binding": {"run_id": "trial-original", "step_id": "step-0", "execution_request_id": "input-0",
        "request_id": "decision-original"}, "result": {"source": "openai_decisions", "status": "completed",
        "request_id": "decision-original", "request_sha256": "e" * 64, "run_id": "trial-original",
        "execution_request_id": "input-0", "step_id": "step-0", "provider_request_id": "provider-original",
        "usage": {"input_tokens": 20, "output_tokens": 2, "total_tokens": 22}}}
    write(session / "task-plan-decisions" / "input-0.json", artifact)
    write(session / "task-plan-decisions" / "duplicate.json", artifact)
    result = score(root)
    assert result["decision"]["session_dispatch_markers"] == 1 and result["decision"]["confirmed_provider_responses"] == 1
    assert result["decision"]["token_usage"] == {"input_tokens": 20, "output_tokens": 2, "total_tokens": 22}
    assert result["decision"]["main_model_tokens"] is None


def test_scorer_never_reads_profile_keys_or_outside_session_references(tmp_path):
    root, session, report, state, *_ = bundle(tmp_path)
    forbidden = tmp_path / "key.txt"
    forbidden.write_text("DO NOT READ THIS FILE", encoding="utf-8")
    state["history"][0]["evidence_refs"] = [{"path": str(forbidden), "sha256": "f" * 64}]
    write(session / "task-plans" / "trial-original.json", state)
    write(root / "decision.json", {"api_key": "DO NOT READ THIS PROFILE"})
    result = score(root)
    assert result["task_success"] is not True and "evidence_reference_outside_scope" in result["runtime"]["errors"]
    assert "DO NOT READ" not in json.dumps(result)


def test_command_symlink_target_cannot_enter_profile_read_scope(tmp_path, monkeypatch):
    root, session, *_ = bundle(tmp_path)
    secret = root / "decision.json"
    write(secret, {"api_key": "DO NOT READ THIS PROFILE"})
    command = session / "commands" / "unrelated.json"
    write(command, {})
    resolve, read_bytes = Path.resolve, Path.read_bytes

    def redirected(path, *args, **kwargs):
        return resolve(secret) if path == command else resolve(path, *args, **kwargs)

    def guarded(path):
        assert path != secret
        return read_bytes(path)

    monkeypatch.setattr(Path, "resolve", redirected)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    result = score(root)
    assert "evidence_reference_outside_scope" in result["runtime"]["errors"]


def test_missing_ledger_does_not_prove_no_paid_requests_or_zero_tokens(tmp_path):
    root, *_ = bundle(tmp_path)
    result = score(root)
    assert result["decision"]["session_dispatch_markers"] is None
    assert result["decision"]["actual_paid_post_count"] is None
    assert result["decision"]["token_usage"] is None


def test_cleanup_failure_is_not_hidden_by_success_oracle(tmp_path):
    root, session, *_ = bundle(tmp_path)
    host = json.loads((session / "report.json").read_text(encoding="utf-8"))
    host["cleanup_errors"] = ["worker did not terminate"]
    write(session / "report.json", host)
    result = score(root)
    assert result["task_success"] is True
    assert result["cleanup"]["complete"] is False
    assert result["complete_with_cleanup"] is False


def test_other_run_receipt_binding_never_counts_as_completed_original_run(tmp_path):
    root, session, report, state, *_ = bundle(tmp_path)
    state["run_id"] = "trial-other"
    write(session / "task-plans" / "trial-original.json", state)
    result = score(root)
    assert result["task_success"] is None
    assert "trial_binding_mismatch" in result["runtime"]["errors"]


def test_completed_run_with_original_command_goal_swapped_is_unproven(tmp_path):
    root, session, report, state, *_ = bundle(tmp_path)
    path = session / "commands" / "input-0.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["request"]["goal"] = "Click another window"
    write(path, raw)
    result = score(root)
    assert result["task_success"] is None
    assert "original_action_goal_mismatch" in result["runtime"]["errors"]


def test_same_tokens_from_different_run_are_not_charged_to_current_plan(tmp_path):
    root, session, *_ = bundle(tmp_path)
    decision_ledger(session)
    write(session / "task-plan-decisions" / "other.json", {"binding": {"run_id": "trial-other"},
        "result": {"request_id": "decision-original", "provider_request_id": "provider-original",
            "source": "openai_decisions", "status": "completed", "usage": {"input_tokens": 20, "output_tokens": 2, "total_tokens": 22}}})
    result = score(root)
    assert result["decision"]["confirmed_provider_responses"] == 0
    assert result["decision"]["token_usage"] is None


def test_malformed_history_stays_unknown_without_crashing(tmp_path):
    root, session, report, state, *_ = bundle(tmp_path)
    state["history"] = "corrupt"
    write(session / "task-plans" / "trial-original.json", state)
    result = score(root)
    assert result["task_success"] is None
    assert "history_shape_or_prefix_mismatch" in result["runtime"]["errors"]


def test_maintained_receipts_bind_by_original_filename_when_top_id_is_absent(tmp_path):
    root, session, report, state, *_ = bundle(tmp_path)
    for name in ("plan-start", "input-0", "input-1"):
        path = session / "responses" / f"{name}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("request_id")
        write(path, raw)
        for row in state["history"]:
            for reference in row["evidence_refs"]:
                if reference["path"] == f"responses/{name}.json":
                    reference["sha256"] = sha256(path.read_bytes()).hexdigest()
    write(session / "task-plans" / "trial-original.json", state)
    result = score(root)
    assert result["outcome"] == "verified_success"


def test_explicit_different_receipt_id_is_rejected_even_with_correct_filename(tmp_path):
    root, session, *_ = bundle(tmp_path)
    path = session / "responses" / "plan-start.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["request_id"] = "other-start"
    write(path, raw)
    result = score(root)
    assert result["task_success"] is None
    assert "original_start_command_mismatch" in result["runtime"]["errors"]


def test_other_fixture_process_is_not_current_target_truth(tmp_path):
    root, session, *_ = bundle(tmp_path)
    write(root / "fixture" / "manifest.json", {"pid": 99, "window_handle": 101})
    result = score(root)
    assert result["task_success"] is None
    assert "fixture_target_binding_mismatch" in result["oracle"]["errors"]


def test_original_input_target_binding_cannot_be_omitted(tmp_path):
    root, session, report, state, *_ = bundle(tmp_path)
    path = session / "responses" / "input-0.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["result"].pop("target_identity")
    write(path, raw)
    state["history"][0]["evidence_refs"][1]["sha256"] = sha256(path.read_bytes()).hexdigest()
    write(session / "task-plans" / "trial-original.json", state)
    result = score(root)
    assert result["task_success"] is None
    assert "original_input_target_binding_unproven" in result["runtime"]["errors"]


def test_nonfinite_source_json_is_rejected_without_reinterpreting_success(tmp_path):
    root, session, *_ = bundle(tmp_path)
    path = session / "task-plans" / "task-plan-original.json"
    path.write_text('{"plan":{"inputs":{"bad":1e999}}}', encoding="utf-8")
    result = score(root)
    assert result["task_success"] is None
    assert "source_invalid" in result["runtime"]["errors"]


def test_compact_client_output_preserves_public_binding_without_private_host_fields(tmp_path):
    root, session, report, *_ = bundle(tmp_path)
    for key in ("owner_id", "session_directory", "target_identity"):
        report["result"]["result"].pop(key)
    write(root / "report.json", report)
    result = score(root)
    assert result["outcome"] == "verified_success"


def test_decision_inclusive_service_and_http_timings_stay_separate(tmp_path):
    root, session, *_ = bundle(tmp_path)
    decision_ledger(session)
    write(session / "task-plan-decisions" / "input-0.json", {"binding": {"run_id": "trial-original",
        "step_id": "step-0", "execution_request_id": "input-0", "request_id": "decision-original"},
        "result": {"source": "openai_decisions", "status": "completed", "request_id": "decision-original",
            "request_sha256": "e" * 64, "run_id": "trial-original", "execution_request_id": "input-0",
            "step_id": "step-0", "provider_request_id": "provider-original", "elapsed_ms": 100,
            "http_elapsed_ms": 80, "server_processing_ms": 70},
        "measurement": {"started_ns": 1000000000, "ended_ns": 1100000000}})
    result = score(root)
    assert result["decision"]["latencies"][0]["elapsed_ms"] == 100
    assert result["decision"]["latencies"][0]["http_elapsed_ms"] == 80
    assert result["decision"]["latencies"][0]["server_processing_ms"] == 70
    assert result["decision"]["measured_span_union_ms"] == 100
    assert result["decision"]["nested_timings_additive"] is False


def test_frozen_source_manifest_requires_explicit_safe_root_and_matching_bytes(tmp_path):
    from scripts.benchmark_execution_plan import score_execution_report
    root, session, report, *_ = bundle(tmp_path)
    source_root = tmp_path / "source"
    file = source_root / "app" / "execution.py"
    file.parent.mkdir(parents=True)
    file.write_text("pass\n", encoding="utf-8")
    report["source_sha256"] = {"app/execution.py": sha256(file.read_bytes()).hexdigest()}
    report["source_unchanged_during_run"] = True
    write(root / "report.json", report)
    assert score(root)["source_freeze"]["current_source_matches_manifest"] is None
    result = score_execution_report(root / "report.json", source_root=source_root)
    assert result["source_freeze"]["current_source_matches_manifest"] is True
    file.write_text("changed = True\n", encoding="utf-8")
    result = score_execution_report(root / "report.json", source_root=source_root)
    assert result["source_freeze"]["current_source_matches_manifest"] is False
    assert result["source_freeze"]["during_run_unchanged_status"] == "reported_by_acceptance_driver"


def test_source_manifest_cannot_read_outside_whitelisted_python_tree(tmp_path, monkeypatch):
    from scripts.benchmark_execution_plan import score_execution_report
    root, session, report, *_ = bundle(tmp_path)
    secret = tmp_path / "key.py"
    secret.write_text("DO NOT READ", encoding="utf-8")
    report["source_sha256"] = {"../key.py": "f" * 64}
    write(root / "report.json", report)
    original = Path.read_bytes

    def guarded(path):
        assert path != secret
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    result = score_execution_report(root / "report.json", source_root=tmp_path / "source")
    assert result["source_freeze"]["current_source_matches_manifest"] is not True
    assert "source_reference_outside_scope" in result["source_freeze"]["errors"]


def test_correct_details_from_earlier_fixture_events_are_not_current_run_proof(tmp_path):
    root, session, report, state, runner, actions, *_ = bundle(tmp_path)
    actions[0]["at"] = "2025-10-08T10:00:01+00:00"
    jsonl(root / "fixture" / "oracle" / "actions.jsonl", actions)
    result = score(root)
    assert result["task_success"] is None
    assert "fixture_event_time_unbound" in result["oracle"]["errors"]


def test_malformed_dispatch_marker_is_unknown_instead_of_zero_calls(tmp_path):
    root, session, *_ = bundle(tmp_path)
    path = decision_ledger(session)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE dispatches SET dispatched='invalid'")
    result = score(root)
    assert result["decision"]["session_dispatch_markers"] is None
    assert "decision_ledger_rows_invalid" in result["decision"]["errors"]


def test_cancelled_original_runner_is_distinct_from_success_and_pending(tmp_path):
    root, session, report, state, runner, *_ = bundle(tmp_path)
    state.update(status="cancelled", history=[])
    runner.update(runner_state="cancelled", steps_completed=0)
    write(session / "task-plans" / "trial-original.json", state)
    write(session / "task-plan-runners" / "trial-original.json", runner)
    result = score(root)
    assert result["outcome"] == "cancelled"
    assert result["task_success"] is False
