"""接管未完整持久化时，原入口不能绕过尚未创建的 runner。"""
from app.core.json_snapshot import write_json_snapshot
import pytest

from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services, WORKFLOW


@pytest.mark.parametrize("phase", ["prepared", "importing"])
@pytest.mark.parametrize("entry", ["start", "admit"])
def test_partial_takeover_blocks_competing_input_before_trial_or_runner_exists(runtime_scene, phase, entry):
    runtime, trials, run, session, _ = runtime_scene
    before = {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*") if p.is_file()}
    root = session.parent / "workflow-takeovers"
    root.mkdir()
    write_json_snapshot(root / ("a" * 64 + ".json"), {
        "contract_version": "workflow_takeover_claim.v1", "claim_id": "a" * 64,
        "new_session_name": session.name, "new_run_id": run["run_id"], "phase": phase})
    with pytest.raises(ValueError, match="workflow_takeover_import_in_progress"):
        if entry == "start":
            trials.start(WORKFLOW, run["program_id"], "search", {"query": "other"}, "competing")
        else:
            runtime.admit("competing", {"kind": "select", "request": {}})
    assert before == {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*") if p.is_file()}


def test_partial_takeover_in_another_epoch_does_not_block_read_only_or_this_epoch(runtime_scene):
    runtime, _, _, session, _ = runtime_scene
    (session.parent / "workflow-takeovers").mkdir()
    write_json_snapshot(session.parent / "workflow-takeovers" / ("a" * 64 + ".json"), {
        "contract_version": "workflow_takeover_claim.v1", "claim_id": "a" * 64,
        "new_session_name": "session-foreign", "phase": "importing"})
    runtime.admit("read-only", {"kind": "capture"})
    runtime.admit("select-new", {"kind": "select", "request": {}})
