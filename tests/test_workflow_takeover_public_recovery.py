"""公开接管在原写盘失败后续接，同逻辑提交不得重放旧输入。"""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from tests.test_workflow_takeover_public import public_scene, preview, commit, run_control
from tests.test_workflow_recovery_import import import_scene
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


@pytest.mark.parametrize("stage", ["trial_write", "runner_active", "claim_ready"])
def test_public_failed_commit_new_outer_id_continues_same_import(public_scene, monkeypatch, stage):
    from app.desktop_review import workspace as disk
    public = public_scene
    scene = public.scene
    view = preview(public)
    run_id = view["new_run_id"]
    replace = disk.os.replace
    failed = []

    def controlled_replace(source, destination):
        path = Path(destination)
        chosen = stage == "trial_write" and path == scene.new / "workflow-trials" / (run_id + ".json")
        chosen = chosen or stage == "runner_active" and path == scene.new / "workflow-runners/active.json"
        if stage == "claim_ready" and path.parent == scene.new.parent / "workflow-takeovers":
            chosen = json.loads(Path(source).read_text(encoding="utf-8")).get("phase") == "ready"
        if chosen and not failed:
            failed.append(True)
            raise OSError("controlled_public_commit_failure")
        return replace(source, destination)

    monkeypatch.setattr(disk.os, "replace", controlled_replace)
    with pytest.raises(OSError, match="controlled_public_commit_failure"):
        commit(public, view)
    command = read_json_snapshot(scene.new / "commands/public-commit.json")
    write_json_snapshot(scene.new / "responses/public-commit.json", {"command": command,
        "status": "failed", "error_type": "OSError", "error": "controlled_public_commit_failure"})
    claims = list((scene.new.parent / "workflow-takeovers").glob("*.json"))
    assert len(claims) == 1 and read_json_snapshot(claims[0])["phase"] == "importing"
    assert (scene.new / "workflow-takeover-commits/public-preview.json").is_file()
    count = len(public.calls)
    snapshot = commit(public, view, "public-commit-retry")
    assert snapshot["run_id"] == run_id and snapshot["wait_reason"] == "takeover_ready"
    assert len(public.calls) == count + 1
    assert read_json_snapshot(claims[0])["phase"] == "ready"
    assert old_bytes(scene.epoch) == scene.old_before
    assert all(read_json_snapshot(path)["kind"] == "learning_workflow"
               for path in (scene.new / "commands").glob("*.json"))


def test_public_ready_commit_readback_allows_original_pending_downstream(public_scene):
    public = public_scene
    scene = public.scene
    view = preview(public)
    first = commit(public, view)
    run_control(public, "continue-downstream", {"action": "continue", "run_id": first["run_id"],
        "wait_id": first["wait"]["wait_id"]})
    pending = public.runtime.tick(force=True)
    assert pending["pending"]["step_id"] == "open"
    eid = pending["pending"]["execution_request_id"]
    assert not (scene.new / "responses" / (eid + ".json")).exists()
    command = read_json_snapshot(scene.new / "commands" / (eid + ".json"))
    worker = {"contract_version": "agent_command.v1", "command_id": eid, "status": "running",
        "action_executed": False, "dispatch_in_progress": False, "dispatch_attempts": [], "result": None}
    (scene.new / "agent-commands").mkdir(exist_ok=True)
    write_json_snapshot(scene.new / "agent-commands" / (eid + ".json"), worker)
    write_json_snapshot(scene.new / "responses" / (eid + ".json"),
                        {"command": command, "status": "returned", "result": worker})
    before = {path: path.read_bytes() for folder in ("workflow-trials", "workflow-runners", "agent-commands")
              for path in (scene.new / folder).glob("*.json")}
    count = len(public.calls)
    enabled = public.runtime._enabled_run
    assert enabled == first['run_id']
    again = commit(public, view, "public-commit-pending-read")
    assert again["run_id"] == first["run_id"]
    assert public.runtime._enabled_run == enabled
    assert len(public.calls) == count
    assert {path: path.read_bytes() for path in before} == before
    assert old_bytes(scene.epoch) == scene.old_before
    assert sum(read_json_snapshot(path)["kind"] != "learning_workflow"
               for path in (scene.new / "commands").glob("*.json")) == 1


@pytest.mark.parametrize("selected", [None, {}])
def test_public_preview_requires_actual_selected_control_evidence(public_scene, monkeypatch, selected):
    from app.learning_memory import workflow_takeover_observation as observer
    original = observer.read_step_observation

    def read(*args, **kwargs):
        result = original(*args, **kwargs)
        result["evidence"]["selected_control"] = selected
        return result

    monkeypatch.setattr(observer, "read_step_observation", read)
    with pytest.raises(ValueError):
        preview(public_scene)
    assert not list((public_scene.scene.new / "workflow-takeover-previews").glob("*.json"))
    assert old_bytes(public_scene.scene.epoch) == public_scene.scene.old_before


def test_target_absent_complete_presence_has_valid_takeover_signature(public_scene):
    from app.learning_memory.workflow_takeover_runtime import _signature
    from app.learning_memory.workflow_verification import verify_current_effect
    envelope = deepcopy(public_scene.scene.envelope)
    envelope['observation'].update(source='presence', complete=True, values={'target_present': False})
    identity = envelope['effect']['window_identity']
    snapshot = {'status': 'ok', 'provider': 'windows_uia', 'scan_complete': True,
        'truncated': False, 'provider_tree_valid': True, 'scan_scope': 'bound_window',
        'controls': [], 'window': {'handle': identity['handle'], 'process_id': identity['process_id']}}
    envelope['native_evidence'] = {'selected_control': None,
        'before_uia_snapshot': deepcopy(snapshot), 'after_uia_snapshot': deepcopy(snapshot),
        'visual_stability': {'scope': 'full_window', 'matched': True}}
    step = {'step_id': envelope['effect']['source_step_id'], 'outputs': [],
        'verification': {'kind': 'target_absent', 'target': {'control_type': 'Text', 'name': '已消失提示'}}}
    envelope['verification'] = verify_current_effect(step, inputs={}, outputs={},
        effect=envelope['effect'], observation=envelope['observation'])
    assert envelope['verification']['verdict'] == 'success'
    signature = _signature(envelope)
    assert signature['source'] == 'presence' and signature['control'] is None
    assert signature['values'] == {'target_present': False} and signature['verdict'] == 'success'
    for key in ('before_uia_snapshot', 'after_uia_snapshot'):
        incomplete = deepcopy(envelope)
        incomplete['native_evidence'][key]['scan_complete'] = False
        with pytest.raises(ValueError, match='semantic_scope_not_verified'):
            _signature(incomplete)
    unstable = deepcopy(envelope)
    unstable['native_evidence']['visual_stability']['matched'] = False
    with pytest.raises(ValueError, match='semantic_scope_not_verified'):
        _signature(unstable)
    assert old_bytes(public_scene.scene.epoch) == public_scene.scene.old_before
