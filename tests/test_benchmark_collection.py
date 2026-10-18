"""基准采集保留原 MCP 回执、失败和未分类成本。"""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest


def module():
    name = "scripts.benchmark_learning_workflow"
    assert importlib.util.find_spec(name) is not None, "benchmark collection entrypoint is missing"
    return __import__(name, fromlist=["BenchmarkCollection"])


class ConnectedClient:
    recognition_source = "agent_current"
    status = {"phase": "ready", "host_alive": True}

    def __init__(self, session):
        self.session_directory = str(session)
        self.calls = []
        self.result = {"status": "returned", "result": {"text": "current"}}

    async def call(self, tool, args):
        self.calls.append((tool, args))
        return {**self.result, "request_id": args.get("request_id")}


def frozen(tmp_path):
    from app.learning_memory.benchmark_manifest import freeze_manifest, FAMILIES
    root = tmp_path / "source"
    (root / "app" / "learning_memory").mkdir(parents=True)
    (root / "app" / "learning_memory" / "benchmark_scoring.py").write_bytes(
        (Path(__file__).resolve().parents[1] / "app/learning_memory/benchmark_scoring.py").read_bytes())
    for relative in module()._COMPARISON_SOURCES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((Path(__file__).resolve().parents[1] / relative).read_bytes())
    cases = []
    for family in FAMILIES:
        for i in range(20):
            cases.append({"case_id": f"{family}-{i}", "task_family": family,
                "variation": "stable" if i < 8 else "unseen" if i < 14 else "layout",
                "cohort": "scored", "seed": i, "inputs": {"value": "current"},
                "success_rule": {"all": [{"path": ["result", "text"], "equals": "current"}]},
                "timeout_seconds": 60, "cold_or_warm": "warm", "is_negative": False,
                "routes": ["A", "C", "B"] if i < 5 else ["A", "C"]})
    path = tmp_path / "manifest.json"
    freeze_manifest({"benchmark_id": "protocol-test", "model": {"source": "agent_current",
        "model": "caller", "config_digest": "a" * 64}, "cases": cases, "artifacts": []},
        root=root, destination=path)
    return root, path


def collection(tmp_path):
    api = module()
    root, manifest = frozen(tmp_path)
    client = ConnectedClient(tmp_path / "session")
    bundle = tmp_path / "collection"
    return api, api.BenchmarkCollection(manifest_path=manifest, root=root,
        directory=bundle, client=client), client, bundle


ASSESSMENT = {"wrong_clicks": 0, "recovery_count": 0, "safe_rejection": False,
              "evidence": {"observer": "contract-test", "detail": "read-only response checked"}}


def test_entrypoint_is_implemented():
    assert callable(module().main)


@pytest.mark.parametrize("explicit", [False, True])
def test_cli_workspace_root_uses_original_client_and_journals_it(tmp_path, monkeypatch, explicit):
    from io import StringIO
    api = module()
    root, manifest = frozen(tmp_path)
    output = tmp_path / "new-evidence"
    workspace = tmp_path / "existing-workspace"
    workspace.mkdir()
    marker = workspace / "preserved-library.txt"
    marker.write_text("existing library", encoding="utf-8")
    seen = {}
    class Client(ConnectedClient):
        def __init__(self, **options):
            super().__init__(tmp_path / "new-session")
            seen.update(options)
            self.data_root = options["data_root"].resolve()
            self.cleanup_error = None
        async def __aenter__(self):
            return self
        async def __aexit__(self, *unused):
            self.status = {"cleanup_verified": True}
    monkeypatch.setattr(api, "LearningBenchmarkClient", Client)
    monkeypatch.setattr(api.sys, "stdin", StringIO("{\"op\":\"stop\"}\n"))
    arguments = ["--phase", "baseline", "--root", str(root), "--manifest", str(manifest),
                 "--data-dir", str(output), "--recognition-source", "agent_current"]
    if explicit:
        arguments += ["--workspace-data-root", str(workspace)]
    assert api.main(arguments) == 0
    expected = workspace if explicit else output / "runtime"
    assert seen["data_root"] == expected
    assert seen["evidence_dir"] == output / "transport"
    rows = [json.loads(line) for line in (output / "collection/journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["payload"]["workspace_data_root"] == str(expected.resolve())
    assert rows[-1]["payload"]["status"]["cleanup_verified"] is True
    assert marker.read_text(encoding="utf-8") == "existing library"


def test_pilot_collection_exports_purpose_and_failure_without_formal_credit(tmp_path):
    from app.learning_memory.benchmark_manifest import digest
    api = module()
    root, manifest = frozen(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["purpose"] = "pilot"
    value["cases"] = [case for case in value["cases"] if case["task_family"] == "query_verify"
                      and int(case["case_id"].rsplit("-", 1)[1]) in {0, 1, 8, 9, 14, 15}]
    for case in value["cases"]:
        case["routes"] = ["A", "C"]
    value["manifest_sha256"] = digest({k: v for k, v in value.items() if k != "manifest_sha256"})
    manifest.write_text(json.dumps(value), encoding="utf-8")
    client = ConnectedClient(tmp_path / "session")
    bundle = tmp_path / "collection"
    collect = api.BenchmarkCollection(manifest_path=manifest, root=root, directory=bundle, client=client)
    collect.begin(case_id="query_verify-0", route="A")
    client.result = {"status": "returned", "result": {"text": "wrong"}}
    asyncio.run(collect.call("instant_run", {"request_id": "pilot-read", "command": {"kind": "read_text"}}))
    row = collect.finish(request_id="pilot-read", assessment=ASSESSMENT)
    assert row["purpose"] == "pilot" and row["completed"] is False
    collect.closed({"cleanup_verified": True})
    result = api.compare_collection(bundle)
    assert result["purpose"] == "pilot" and result["formal_quota_credit"] == 0
    assert result["empirical_acceptance"] is False
    output = tmp_path / "export" / "comparison.json"
    api.export_comparison(result, output)
    assert json.loads(output.read_text(encoding="utf-8"))["purpose"] == "pilot"
    assert json.loads(output.with_name("runs.jsonl").read_text(encoding="utf-8"))["purpose"] == "pilot"
    assert "pilot_not_formal_acceptance" in output.with_name("report.md").read_text(encoding="utf-8")


def test_original_receipt_rule_and_unknown_usage_survive_comparison(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    asyncio.run(run.call("instant_run", {"request_id": "read-one", "command": {"kind": "read_text"}}))
    row = run.finish(request_id="read-one", assessment=ASSESSMENT)
    assert row["completed"] is True and row["first_attempt_success"] is True
    assert row["elapsed_ns"] >= 0
    assert row["telemetry"] == {"planning": False, "grounding": False, "verification": False}
    report = api.compare_collection(bundle)
    assert report["comparison"]["routes"]["A"]["model_calls"]["total"] is None
    assert report["empirical_acceptance"] is False
    assert "planned_runs_missing" in report["limitations"]
    assert report["comparison"]["sample_sufficiency"]["meets_required_ac"] is False
    assert len(client.calls) == 1


def test_pending_is_not_success_and_original_input_cannot_be_replayed(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    client.result = {"status": "pending"}
    args = {"request_id": "original", "command": {"kind": "capture"}}
    asyncio.run(run.call("instant_run", args))
    with pytest.raises(ValueError, match="replay"):
        asyncio.run(run.call("instant_run", args))
    row = run.finish(request_id="original", assessment=ASSESSMENT)
    assert row["completed"] is False and row["first_attempt_success"] is False
    assert len(client.calls) == 1
    assert "unresolved_requests" in api.compare_collection(bundle)["limitations"]


def test_first_failure_and_explicit_retry_remain_and_no_attempt_overwrite(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    client.result = {"status": "returned", "result": {"text": "stale"}}
    asyncio.run(run.call("instant_run", {"request_id": "first", "command": {"kind": "read_text"}}))
    assert run.finish(request_id="first", assessment=ASSESSMENT)["completed"] is False
    run.begin(case_id="query_verify-0", route="A")
    client.result = {"status": "returned", "result": {"text": "current"}}
    asyncio.run(run.call("instant_run", {"request_id": "retry", "command": {"kind": "read_text"}}))
    retry = run.finish(request_id="retry", assessment=ASSESSMENT)
    assert retry["attempt_index"] == 2 and retry["first_attempt_success"] is False
    report = api.compare_collection(bundle)
    assert report["comparison"]["routes"]["A"]["attempts"] == 2
    assert report["comparison"]["routes"]["A"]["first_attempt_success_rate"] == 0
    with pytest.raises(FileExistsError):
        api.BenchmarkCollection(manifest_path=bundle / "manifest.json", root=run.root,
                                directory=bundle, client=client)


def test_misbound_receipt_and_source_drift_stop_before_next_input(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    source = run.root / "app" / "learning_memory" / "benchmark_scoring.py"
    source.write_text("# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="candidate"):
        asyncio.run(run.call("instant_run", {"request_id": "read", "command": {"kind": "read_text"}}))
    assert client.calls == []


def test_transport_failure_keeps_intent_and_does_not_retry(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    async def broken(tool, args):
        raise ConnectionError("private details must not appear in error metadata")
    client.call = broken
    with pytest.raises(ConnectionError):
        asyncio.run(run.call("instant_run", {"request_id": "lost", "command": {"kind": "read_text"}}))
    report = api.compare_collection(bundle)
    assert "unfinished_attempts" in report["limitations"]
    assert "transport_error" in (bundle / "journal.jsonl").read_text(encoding="utf-8")
    assert "private details" not in (bundle / "journal.jsonl").read_text(encoding="utf-8")


def test_journal_edit_is_detected(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    asyncio.run(run.call("instant_run", {"request_id": "one", "command": {"kind": "read_text"}}))
    run.finish(request_id="one", assessment=ASSESSMENT)
    path = bundle / "journal.jsonl"
    value = path.read_text(encoding="utf-8").replace('"current"', '"changed"')
    path.write_text(value, encoding="utf-8")
    with pytest.raises(ValueError, match="journal"):
        api.compare_collection(bundle)


def test_unresolved_attempt_cannot_overlap_next_case(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    client.result = {"status": "pending"}
    asyncio.run(run.call("instant_run", {"request_id": "waiting", "command": {"kind": "capture"}}))
    run.finish(request_id="waiting", assessment=ASSESSMENT)
    with pytest.raises(ValueError, match="unresolved"):
        run.begin(case_id="query_verify-1", route="C")


def test_frozen_deadline_prevents_new_input_but_allows_original_result(tmp_path, monkeypatch):
    api, run, client, bundle = collection(tmp_path)
    monkeypatch.setattr(api, "perf_counter_ns", lambda: 1)
    run.begin(case_id="query_verify-0", route="A")
    client.result = {"status": "pending"}
    asyncio.run(run.call("instant_run", {"request_id": "waiting", "command": {"kind": "capture"}}))
    monkeypatch.setattr(api, "perf_counter_ns", lambda: 61_000_000_000)
    with pytest.raises(ValueError, match="deadline"):
        asyncio.run(run.call("instant_run", {"request_id": "too-late", "command": {"kind": "capture"}}))
    client.result = {"status": "returned", "result": {"text": "current"}}
    asyncio.run(run.call("instant_result", {"request_id": "waiting"}))
    row = run.finish(request_id="waiting", assessment=ASSESSMENT)
    assert row["timed_out"] and not row["completed"]


def test_real_measurement_log_is_archived_with_original_run_and_evidence(tmp_path):
    from app.learning_memory.workflow_metrics import record_rule_observation
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    trial = {"run_id": "trial-current", "history": [], "pending": None,
             "status": "ready", "execution_strategy": "learned"}
    client.result = {"status": "returned", "result": trial}
    asyncio.run(run.call("instant_run", {"request_id": "start", "command": {
        "kind": "learning_workflow", "request": {"action": "start", "inputs": {"value": "current"}}}}))
    session = Path(client.session_directory)
    for directory in ("responses", "workflow-observations"):
        (session / directory).mkdir(parents=True)
    (session / "responses" / "execute-one.json").write_text('{"status":"returned"}', encoding="utf-8")
    (session / "workflow-observations" / "verify-one.json").write_text('{"text":"current"}', encoding="utf-8")
    record_rule_observation(session, {"measurement": {"started_ns": 10, "ended_ns": 20},
        "receipt": {"run_id": "trial-current", "step_id": "read", "request_id": "verify-one",
            "execution_request_id": "execute-one", "evidence_ref": "responses/execute-one.json"},
        "observation": {"evidence_ref": "workflow-observations/verify-one.json"}}, "success")
    client.result = {"status": "returned", "result": {**trial, "text": "current"}}
    asyncio.run(run.call("instant_run", {"request_id": "status", "command": {
        "kind": "learning_workflow", "request": {"action": "status", "run_id": "trial-current"}}}))
    row = run.finish(request_id="status", assessment=ASSESSMENT)
    assert row["run_id"] == "trial-current"
    assert row["events"][0]["request_id"] == "verify-one"
    assert row["events"][0]["phase"] == "verification"
    report = api.compare_collection(bundle)
    assert report["measurement_snapshots"][0]["evidence_files"][0]["sha256"]
    assert report["comparison"]["routes"]["C"]["model_calls"]["total"] is None


def test_original_start_result_replay_keeps_newer_trial_snapshot(tmp_path):
    _, run, client, _ = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="C")
    start = {"run_id": "trial-current", "history": [], "pending": None,
             "status": "ready", "execution_strategy": "learned"}
    client.result = {"status": "returned", "result": start}
    asyncio.run(run.call("instant_run", {"request_id": "start-original", "command": {
        "kind": "learning_workflow", "request": {"action": "start", "inputs": {"value": "current"}}}}))
    progressed = {**start, "history": [{"step_id": "read", "status": "completed"}], "status": "running"}
    client.result = {"status": "returned", "result": progressed}
    asyncio.run(run.call("instant_run", {"request_id": "status-later", "command": {
        "kind": "learning_workflow", "request": {"action": "status", "run_id": "trial-current"}}}))
    assert run._trials["trial-current"]["trial"] == progressed
    client.result = {"status": "returned", "result": start}
    replay = asyncio.run(run.call("instant_result", {"request_id": "start-original"}))
    assert replay["result"] == start
    assert run._trials["trial-current"]["trial"] == progressed
    with pytest.raises(ValueError, match="one_trial_per_attempt"):
        asyncio.run(run.call("instant_run", {"request_id": "same-attempt-new-start", "command": {
            "kind": "learning_workflow", "request": {"action": "start", "inputs": {"value": "current"}}}}))
    run.finish(request_id="status-later", assessment=ASSESSMENT)
    run.begin(case_id="query_verify-0", route="C")
    client.result = {"status": "returned", "result": start}
    with pytest.raises(ValueError, match="trial_reused"):
        asyncio.run(run.call("instant_run", {"request_id": "different-start", "command": {
            "kind": "learning_workflow", "request": {"action": "start", "inputs": {"value": "current"}}}}))


def test_a_route_rejects_workflow_and_memory_before_dispatch(tmp_path):
    _, run, client, bundle = collection(tmp_path)
    begun = run.begin(case_id="query_verify-0", route="A")
    assert begun["route_policy"]["execution_strategy"] == "ordinary"
    with pytest.raises(ValueError, match="route.*workflow"):
        asyncio.run(run.call("instant_run", {"request_id": "forbidden-workflow", "command": {
            "kind": "learning_workflow", "request": {"action": "start", "inputs": {"value": "current"}}}}))
    with pytest.raises(ValueError, match="target_memory"):
        asyncio.run(run.call("instant_run", {"request_id": "forbidden-memory", "command": {
            "kind": "step", "request": {"target_memory": {"recipe": "old"}}}}))
    assert client.calls == []
    assert all(json.loads(line)["kind"] != "call" for line in (bundle / "journal.jsonl").read_text(encoding="utf-8").splitlines())


def test_b_route_freezes_strategy_and_binds_followup_trial(tmp_path):
    _, run, client, bundle = collection(tmp_path)
    begun = run.begin(case_id="query_verify-0", route="B")
    assert begun["route_policy"]["execution_strategy"] == "steps_only"
    with pytest.raises(ValueError, match="execution_strategy"):
        asyncio.run(run.call("instant_run", {"request_id": "wrong-b", "command": {
            "kind": "learning_workflow", "request": {"action": "start", "inputs": {"value": "current"},
                                                  "execution_strategy": "learned"}}}))
    with pytest.raises(ValueError, match="target_memory"):
        asyncio.run(run.call("instant_run", {"request_id": "memory-b", "command": {
            "kind": "step", "request": {"target_memory": {"recipe": "old"}}}}))
    assert client.calls == []
    trial = {"run_id": "trial-b", "history": [], "pending": None,
             "status": "ready", "execution_strategy": "steps_only"}
    client.result = {"status": "returned", "result": trial}
    asyncio.run(run.call("instant_run", {"request_id": "start-b", "command": {
        "kind": "learning_workflow", "request": {"action": "start", "inputs": {"value": "current"}}}}))
    assert client.calls[-1][1]["command"]["request"]["execution_strategy"] == "steps_only"
    calls = [json.loads(line)["payload"] for line in (bundle / "journal.jsonl").read_text(encoding="utf-8").splitlines()
             if json.loads(line)["kind"] == "call"]
    assert calls[-1]["arguments"]["command"]["request"]["execution_strategy"] == "steps_only"
    with pytest.raises(ValueError, match="trial.*identity"):
        asyncio.run(run.call("instant_run", {"request_id": "other-trial", "command": {
            "kind": "learning_workflow", "request": {"action": "status", "run_id": "trial-other"}}}))
    assert len(client.calls) == 1
    client.result = {"status": "returned", "result": {key: value for key, value in trial.items()
                                                     if key != "execution_strategy"}}
    with pytest.raises(ValueError, match="execution_strategy"):
        asyncio.run(run.call("instant_run", {"request_id": "missing-strategy", "command": {
            "kind": "learning_workflow", "request": {"action": "status", "run_id": "trial-b"}}}))
    assert "missing-strategy" not in run._receipts


def test_b_followup_cannot_reuse_previous_attempt_trial(tmp_path):
    _, run, client, _ = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="B")
    client.result = {"status": "returned", "result": {"run_id": "old-trial", "history": [],
        "pending": None, "status": "ready", "execution_strategy": "steps_only"}}
    asyncio.run(run.call("instant_run", {"request_id": "start-old", "command": {
        "kind": "learning_workflow", "request": {"action": "start", "inputs": {"value": "current"}}}}))
    run.finish(request_id="start-old", assessment=ASSESSMENT)
    run.begin(case_id="query_verify-0", route="B")
    with pytest.raises(ValueError, match="trial_identity"):
        asyncio.run(run.call("instant_run", {"request_id": "old-status", "command": {
            "kind": "learning_workflow", "request": {"action": "status", "run_id": "old-trial"}}}))
    assert len(client.calls) == 1


def test_c_route_rejects_mismatched_trial_strategy(tmp_path):
    _, run, client, _ = collection(tmp_path)
    assert run.begin(case_id="query_verify-0", route="C")["route_policy"]["execution_strategy"] == "learned"
    client.result = {"status": "returned", "result": {"run_id": "trial-c", "history": [],
        "pending": None, "status": "ready", "execution_strategy": "steps_only"}}
    with pytest.raises(ValueError, match="execution_strategy"):
        asyncio.run(run.call("instant_run", {"request_id": "start-c", "command": {
            "kind": "learning_workflow", "request": {"action": "start", "inputs": {"value": "current"}}}}))


def test_failed_agent_command_is_failure_even_when_receipt_rule_matches(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    client.result = {"status": "returned", "result": {"text": "current",
        "contract_version": "agent_command.v1", "command_id": "failed", "status": "failed"}}
    asyncio.run(run.call("instant_run", {"request_id": "failed", "command": {"kind": "step"}}))
    assert run.finish(request_id="failed", assessment=ASSESSMENT)["completed"] is False


def test_conflicting_terminal_status_cannot_replace_first_failure(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    client.result = {"status": "returned", "result": {"text": "current",
        "contract_version": "agent_command.v1", "command_id": "original", "status": "failed"}}
    asyncio.run(run.call("instant_run", {"request_id": "original", "command": {"kind": "step"}}))
    client.result["result"]["status"] = "completed"
    with pytest.raises(ValueError, match="terminal.*changed"):
        asyncio.run(run.call("instant_run", {"request_id": "probe", "command": {
            "kind": "agent_command_status", "request": {"command_id": "original"}}}))
    assert run.finish(request_id="original", assessment=ASSESSMENT)["completed"] is False
    with pytest.raises(ValueError, match="terminal.*changed"):
        api.compare_collection(bundle)


def test_status_query_is_finished_even_while_original_command_is_running(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    client.result = {"status": "returned", "result": {"text": "current",
        "contract_version": "agent_command.v1", "command_id": "original", "status": "running"}}
    asyncio.run(run.call("instant_run", {"request_id": "original", "command": {"kind": "step"}}))
    for request_id, state in (("status-one", "running"), ("status-two", "completed")):
        client.result["result"]["status"] = state
        asyncio.run(run.call("instant_run", {"request_id": request_id, "command": {
            "kind": "agent_command_status", "request": {"command_id": "original"}}}))
    assert run.finish(request_id="original", assessment=ASSESSMENT)["completed"] is True
    run.begin(case_id="query_verify-1", route="A")


def continued_command(tmp_path, *, terminal=True, outer_pending=False):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    def send(identity, kind, state, request=None, outer="returned"):
        client.result = {"status": outer, "result": {"text": "current",
            "contract_version": "agent_command.v1", "command_id": "original", "status": state}}
        command = {"kind": kind}
        if request is not None:
            command["request"] = request
        return asyncio.run(run.call("instant_run", {"request_id": identity, "command": command}))
    send("original", "step", "running")
    send("awaiting", "agent_command_status", "awaiting_grounding", {"command_id": "original"})
    send("continue-control", "agent_command_continue", "running",
         {"command_id": "original", "grounding_request_id": "grounding-current"},
         "pending" if outer_pending else "returned")
    if terminal:
        send("terminal-control", "agent_command_status", "completed", {"command_id": "original"})
    return api, run, client, bundle


def test_continue_control_settles_without_overwriting_its_original_receipt(tmp_path):
    api, run, _, bundle = continued_command(tmp_path)
    assert run._receipts["continue-control"]["result"]["status"] == "running"
    row = run.finish(request_id="terminal-control", assessment=ASSESSMENT)
    assert row["completed"] is True
    events = [json.loads(line) for line in (bundle / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[-1]["payload"]["unresolved_requests"] == []
    assert api.compare_collection(bundle)["runs"][0]["completed"] is True
    run.begin(case_id="query_verify-1", route="A")


@pytest.mark.parametrize("terminal,outer_pending", [(False, False), (True, True)])
def test_continue_settlement_never_hides_pending_original_or_outer_request(tmp_path, terminal, outer_pending):
    api, run, _, bundle = continued_command(tmp_path, terminal=terminal, outer_pending=outer_pending)
    row = run.finish(request_id="terminal-control" if terminal else "original", assessment=ASSESSMENT)
    assert row["completed"] is False
    assert "unresolved_requests" in api.compare_collection(bundle)["limitations"]
    with pytest.raises(ValueError, match="unresolved"):
        run.begin(case_id="query_verify-1", route="A")


@pytest.mark.parametrize("change", ["clear", "add"])
def test_replay_recomputes_settlement_and_rejects_rehashed_unresolved_list(tmp_path, change):
    from tests.test_benchmark_collection_provenance import rehash_journal
    api, run, _, bundle = continued_command(tmp_path, terminal=change == "add")
    run.finish(request_id="terminal-control" if change == "add" else "original", assessment=ASSESSMENT)
    def edit(events):
        finish = next(event for event in events if event["kind"] == "finish")["payload"]
        finish["unresolved_requests"] = [] if change == "clear" else ["continue-control"]
    rehash_journal(bundle, edit)
    with pytest.raises(ValueError, match="unresolved.*mismatch"):
        api.compare_collection(bundle)


def test_continue_cannot_bind_wrong_parent_or_previous_attempt(tmp_path):
    _, run, client, _ = continued_command(tmp_path)
    client.result = {"status": "returned", "result": {"contract_version": "agent_command.v1",
        "command_id": "wrong", "status": "running"}}
    with pytest.raises(ValueError, match="identity_mismatch"):
        asyncio.run(run.call("instant_run", {"request_id": "wrong-parent", "command": {
            "kind": "agent_command_continue", "request": {"command_id": "original"}}}))
    # 错误请求保留未结算，另建已正常结束的会话验证跨轮次绑定。
    _, clean, client, _ = continued_command(tmp_path / "other")
    clean.finish(request_id="terminal-control", assessment=ASSESSMENT)
    clean.begin(case_id="query_verify-1", route="A")
    client.result = {"status": "returned", "result": {"contract_version": "agent_command.v1",
        "command_id": "original", "status": "running"}}
    with pytest.raises(ValueError, match="identity_mismatch"):
        asyncio.run(clean.call("instant_run", {"request_id": "cross-attempt", "command": {
            "kind": "agent_command_continue", "request": {"command_id": "original"}}}))


def test_comparison_rejects_unfrozen_scorer(tmp_path, monkeypatch):
    api, run, client, bundle = collection(tmp_path)
    monkeypatch.setattr(api, "_scoring_digest", lambda: "0" * 64, raising=False)
    with pytest.raises(ValueError, match="scoring.*changed"):
        api.compare_collection(bundle)


def test_cli_exports_rows_and_honest_report_without_overwriting(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    run.begin(case_id="query_verify-0", route="A")
    asyncio.run(run.call("instant_run", {"request_id": "original", "command": {"kind": "read_text"}}))
    run.finish(request_id="original", assessment=ASSESSMENT)
    output = tmp_path / "report" / "comparison.json"
    assert api.main(["--phase", "compare", "--data-dir", str(bundle.parent), "--output", str(output)]) == 0
    rows = [json.loads(line) for line in output.with_name("runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["completed"] is True
    report = output.with_name("report.md").read_text(encoding="utf-8")
    assert "caller_model_telemetry_unavailable" in report
    assert "empirical_acceptance=false" in report
    with pytest.raises(FileExistsError):
        api.main(["--phase", "compare", "--data-dir", str(bundle.parent), "--output", str(output)])


def test_comparison_cannot_use_changed_receipt_evaluator(tmp_path):
    api, run, client, bundle = collection(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_files"]["scripts/benchmark_learning_workflow.py"] = "0" * 64
    manifest["manifest_sha256"] = api.digest({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    journal_path = bundle / "journal.jsonl"
    opened = json.loads(journal_path.read_text(encoding="utf-8"))
    opened["previous_sha256"] = manifest["manifest_sha256"]
    opened["sha256"] = api.digest({k: v for k, v in opened.items() if k != "sha256"})
    journal_path.write_text(json.dumps(opened) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="scoring.*changed"):
        api.compare_collection(bundle)


def test_pending_negative_case_cannot_be_reported_as_correct_rejection(tmp_path):
    api = module()
    root, path = frozen(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    spec = {key: manifest[key] for key in ("benchmark_id", "model", "cases", "artifacts")}
    spec["cases"].append({**spec["cases"][0], "case_id": "negative-one",
                           "variation": "negative", "is_negative": True})
    negative_manifest = tmp_path / "negative-manifest.json"
    api.freeze_manifest(spec, root=root, destination=negative_manifest)
    client = ConnectedClient(tmp_path / "session")
    run = api.BenchmarkCollection(manifest_path=negative_manifest, root=root,
                                   directory=tmp_path / "collection", client=client)
    run.begin(case_id="negative-one", route="A")
    client.result = {"status": "pending"}
    asyncio.run(run.call("instant_run", {"request_id": "negative", "command": {"kind": "capture"}}))
    with pytest.raises(ValueError, match="rejection.*unverified"):
        run.finish(request_id="negative", assessment={**ASSESSMENT, "safe_rejection": True})


def test_collector_uses_real_fixture_outcome_without_exposing_private_truth(tmp_path):
    from PySide6.QtWidgets import QApplication
    from scripts.learning_benchmark_cases import build_cases, scenario_for
    from scripts.run_learning_workflow_fixture import _load_fixture_class
    api = module()
    root, unused = frozen(tmp_path)
    cases = build_cases(25)
    manifest = tmp_path / "case-manifest.json"
    api.freeze_manifest({"benchmark_id": "real-fixture-contract", "model": {
        "source": "agent_current", "model": "caller", "config_digest": "a" * 64},
        "cases": cases, "artifacts": []}, root=root, destination=manifest)
    app = QApplication.instance() or QApplication([])
    events = []
    window = _load_fixture_class()([], event_sink=lambda event: events.append(dict(event)))

    class Fixture:
        def prepare(self, case):
            window.reset_case(**scenario_for(case))
            return self.observe(case["case_id"])

        def observe(self, case_id):
            snapshot = window.state_snapshot()
            return {"snapshot": snapshot, "events": [event for event in events
                if event["event_index"] >= snapshot["reset_event_index"]]}

    client = ConnectedClient(tmp_path / "session")
    run = api.BenchmarkCollection(manifest_path=manifest, root=root, directory=tmp_path / "collection",
                                  client=client, fixture_driver=Fixture())
    assert run.next_case()["case_id"] == cases[0]["case_id"]
    started = run.begin(case_id=cases[0]["case_id"], route="A")
    assert "fixture_prepared" not in started and "records" not in started
    target = cases[0]["inputs"]["record_id"]
    detail = window.records_snapshot()[0]["detail"]
    assert detail not in json.dumps(started)
    asyncio.run(run.call("instant_run", {"request_id": "read-first", "command": {"kind": "read_text"}}))
    assert run.finish(request_id="read-first", assessment=ASSESSMENT)["completed"] is False
    assert run.next_case()["route"] == "C"
    run.begin(case_id=cases[0]["case_id"], route="C")
    window.query_field.setText(target)
    window.search_button.click()
    asyncio.run(run.call("instant_run", {"request_id": "read-second", "command": {"kind": "read_text"}}))
    assert run.finish(request_id="read-second", assessment=ASSESSMENT)["completed"] is True
    report = api.compare_collection(tmp_path / "collection")
    assert report["case_observations"][1]["verdict"]["completed"] is True
    assert report["comparison"]["routes"]["A"]["first_attempt_success_rate"] == 0
    assert report["comparison"]["routes"]["C"]["first_attempt_success_rate"] == 1
    assert report["empirical_acceptance"] is False
    window.close()
