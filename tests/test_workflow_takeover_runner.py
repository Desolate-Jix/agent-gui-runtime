from copy import deepcopy
import json

import pytest

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.workflow_runner import WorkflowRunner, _digest
from tests.test_workflow_trial import services, WORKFLOW


@pytest.fixture
def imported(services, monkeypatch):
    programs, trials, saved, session = services
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "fresh"}, "new-run")
    state = trials.status(run["run_id"])
    state["current_step_id"] = "open"
    state["history"] = [{"step_id": "search", "source": "recovery_history"}]
    marker = {"contract_version": "workflow_recovery_import.v1", "claim_id": "c" * 64, "request_id": "takeover-one", "source_session_name": "session-" + "a" * 32,
              "source_run_id": "trial-" + "a" * 64, "source_step_id": "search", "source_execution_request_id": "original-input", "source_program_sha256": "d" * 64,
              "source_settlement_sha256": "e" * 64, "effect_evidence_ref": "takeover/effect.json", "effect_evidence_sha256": "f" * 64,
              "verified_history_sha256": _digest(state["history"]), "consumed_step_ids": ["search"], "status": "prepared"}
    state["recovery_import"] = marker
    write_json_snapshot(trials._path(run["run_id"]), state)
    path = session.parent / "workflow-takeovers" / (marker["claim_id"] + ".json")
    path.parent.mkdir()
    claim = {"contract_version": "workflow_takeover_claim.v1", "phase": "importing", "claim_id": marker["claim_id"], "request_id": marker["request_id"], "new_session_name": session.name, "new_run_id": run["run_id"], "recovery_import": deepcopy(marker), "imported_history_sha256": _digest(state["history"]), "trial_state_sha256": _digest(state)}
    write_json_snapshot(path, claim)
    calls = []
    def forbidden(*args, **kwargs): calls.append(True); raise AssertionError("import must not execute")
    runner = WorkflowRunner(session, library_root=programs.library._workspace_root, submit_command=forbidden, read_result=forbidden, verify_step=forbidden)
    monkeypatch.setattr(runner, "_trial", lambda action, run_id, *a, **k: trials.status(run_id) if action == "status" else forbidden())
    return runner, run["run_id"], path, claim, marker, trials, calls


def do_import(scene, **kwargs):
    runner, run, _, _, marker, _, _ = scene
    return runner.import_recovery(run, marker["request_id"], mode="until_wait", claim_id=marker["claim_id"], seen_steps=["search"], **kwargs)


def test_import_waits_and_same_id_is_readonly(imported):
    runner, run, _, _, _, _, calls = imported
    result = do_import(imported)
    assert result["runner_state"] == "waiting" and result["wait_reason"] == "takeover_ready"
    state = runner._load(run)
    assert state["ticket"] is None and state["steps_completed"] == 1 and state["seen_steps"] == ["search"]
    before = {p: p.read_bytes() for p in runner.root.glob("*.json")}
    assert do_import(imported) == result and before == {p: p.read_bytes() for p in runner.root.glob("*.json")}
    assert calls == []


def test_active_publish_failure_reuses_original_runner(imported, monkeypatch):
    runner, run, _, _, _, _, calls = imported
    original = runner._set_active
    monkeypatch.setattr(runner, "_set_active", lambda *a: (_ for _ in ()).throw(OSError("publish")))
    with pytest.raises(OSError): do_import(imported)
    raw = runner._path(run).read_bytes()
    monkeypatch.setattr(runner, "_set_active", original)
    do_import(imported)
    assert runner._path(run).read_bytes() == raw and runner._active_run() == run and calls == []


@pytest.mark.parametrize("action", ["start", "advance", "resume"])
def test_importing_claim_cannot_drive_or_write(imported, action):
    runner, run, _, _, marker, _, calls = imported
    do_import(imported)
    before = {p: p.read_bytes() for p in runner.root.glob("*.json")}
    with pytest.raises(ValueError, match="workflow_runner_recovery"):
        if action == "start": runner.start(run, marker["request_id"], "until_wait")
        elif action == "advance": runner.advance(run)
        else: runner.resume(run, "resume-one", runner.status(run)["wait"]["wait_id"])
    assert before == {p: p.read_bytes() for p in runner.root.glob("*.json")} and calls == []


def test_marker_drift_and_import_conflict_reject(imported):
    runner, run, _, _, marker, trials, _ = imported
    do_import(imported)
    with pytest.raises(ValueError): runner.import_recovery(run, "different", mode="until_wait", claim_id=marker["claim_id"], seen_steps=["search"])
    state = trials.status(run)
    state["recovery_import"]["consumed_step_ids"] = ["other"]
    write_json_snapshot(trials._path(run), state)
    with pytest.raises(ValueError): do_import(imported)


def test_completed_import_does_not_call_callbacks(imported):
    runner, run, path, claim, _, trials, calls = imported
    state = trials.status(run)
    state.update(status="completed", current_step_id=None)
    write_json_snapshot(trials._path(run), state)
    claim["trial_state_sha256"] = _digest(state)
    write_json_snapshot(path, claim)
    result = do_import(imported)
    assert result["runner_state"] == "completed" and result["wait"] is None and calls == []


@pytest.mark.parametrize("change", ["mode", "seen", "claim", "missing_claim", "other_active"])
def test_import_authority_and_argument_conflicts_preserve_runner(imported, change):
    runner, run, path, claim, marker, _, calls = imported
    do_import(imported)
    before = runner._path(run).read_bytes()
    kwargs = {"mode": "until_wait", "claim_id": marker["claim_id"], "seen_steps": ["search"]}
    if change == "mode": kwargs["mode"] = "single"
    if change == "seen": kwargs["seen_steps"] = ["other"]
    if change == "claim": claim["new_run_id"] = "trial-" + "f" * 64; write_json_snapshot(path, claim)
    if change == "missing_claim": path.write_text("{}", encoding="utf-8")
    if change == "other_active":
        other = "trial-" + "f" * 64
        runner._save({"schema": "workflow_runner.v1", "run_id": other, "runner_state": "waiting"})
        runner._set_active(other)
    with pytest.raises(ValueError): runner.import_recovery(run, marker["request_id"], **kwargs)
    assert runner._path(run).read_bytes() == before and calls == []


def test_ready_claim_accepts_new_history_after_first_downstream_step(imported):
    runner, run, path, claim, _, trials, calls = imported
    do_import(imported)
    claim["phase"] = "ready"
    write_json_snapshot(path, claim)
    state = trials.status(run)
    state["history"].append({"step_id": "open", "verdict": "success", "outputs": {}})
    state.update(status="completed", current_step_id=None)
    write_json_snapshot(trials._path(run), state)
    runner.resume(run, "resume-after-effect", runner.status(run)["wait"]["wait_id"])
    assert runner.advance(run)["runner_state"] == "completed" and calls == []
    state["history"][0]["source"] = "changed"
    write_json_snapshot(trials._path(run), state)
    with pytest.raises(ValueError, match="workflow_runner_recovery"):
        runner.advance(run)
