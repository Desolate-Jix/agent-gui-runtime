"""普通工作台来源发现只读复核既有准入，不替代当前效果预览。"""
from copy import deepcopy
from pathlib import Path

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services
from tests.test_workflow_unexecuted_takeover import build_unexecuted


def read_sources(scene):
    from app.learning_memory.workflow_takeover_sources import read_takeover_sources
    return read_takeover_sources(scene.new, scene.library_root)


@pytest.mark.parametrize("prefix_count", [0, 1])
def test_sources_are_pinned_readonly_and_do_not_claim_current_effect(build_unexecuted, prefix_count):
    scene = build_unexecuted(prefix_count)
    before = old_bytes(scene.epoch)
    commands = list((scene.new / "commands").glob("*.json"))
    rows = read_sources(scene)
    assert len(rows) == 1
    row = rows[0]
    assert row["admission_request_id"] == "fresh-epoch-admission"
    assert row["source_run_id"] == scene.source_run_id
    assert Path(row["source_session"]) == scene.epoch.old
    assert row["workflow_id"] == scene.original["workflow_id"]
    assert row["program_id"] == scene.original["program_id"]
    assert row["program_sha256"] == scene.original["recovery_settlement"]["program_sha256"]
    assert row["step_id"] == "search" and row["step_title"]
    assert row["terminal_status"] == "cancelled" and row["action_executed"] is False
    assert row["resume_unexecuted_available"] is True
    assert row["current_effect_verified"] is False
    assert list((scene.new / "commands").glob("*.json")) == commands
    assert old_bytes(scene.epoch) == before


@pytest.mark.parametrize("fact", [
    "action_true", "acceptance_unknown", "acceptance_nested_true",
    "completed", "failed", "dispatch_attempt", "last_execution", "pending_grounding",
])
def test_only_strict_original_zero_input_enables_resume(build_unexecuted, fact):
    scene = build_unexecuted(fact=fact)
    before = old_bytes(scene.epoch)
    rows = read_sources(scene)
    assert len(rows) == 1 and rows[0]["resume_unexecuted_available"] is False
    assert rows[0]["resume_unexecuted_reason"]
    assert rows[0]["current_effect_verified"] is False
    assert old_bytes(scene.epoch) == before
    assert not list((scene.new / "commands").glob("*.json"))


@pytest.mark.parametrize("change", ["worker", "trial", "active", "report"])
def test_source_drift_never_becomes_an_empty_candidate_list(build_unexecuted, change):
    scene = build_unexecuted()
    paths = {
        "worker": scene.epoch.old / "agent-commands" / (scene.old_eid + ".json"),
        "trial": scene.epoch.old / "workflow-trials" / (scene.source_run_id + ".json"),
        "active": scene.epoch.old / "workflow-runners" / "active.json",
        "report": scene.epoch.old / "report.json",
    }
    path = paths[change]
    value = read_json_snapshot(path)
    if change == "trial":
        value.pop("recovery_settlement")
    elif change == "active":
        value["run_id"] = "trial-" + "f" * 64
    else:
        value["changed_after_admission"] = True
    write_json_snapshot(path, value)
    with pytest.raises(ValueError):
        read_sources(scene)
    assert not list((scene.new / "commands").glob("*.json"))


@pytest.mark.parametrize("change", ["pointer", "identity", "not_ready", "admission_phase"])
def test_current_epoch_binding_is_rechecked(build_unexecuted, change):
    scene = build_unexecuted()
    if change in {"pointer", "identity"}:
        path = scene.new.parent / "latest-session.json"
        value = read_json_snapshot(path)
        if change == "pointer":
            value["name"] = "session-" + "f" * 32
        else:
            value["host_identity"]["created"] += 1
    elif change == "not_ready":
        path = scene.new / "report.json"
        value = read_json_snapshot(path)
        value["phase"] = "stopped"
    else:
        path = scene.new.parent / "recovery-admissions" / "fresh-epoch-admission.json"
        value = read_json_snapshot(path)
        value["phase"] = "pointer_published"
    write_json_snapshot(path, value)
    with pytest.raises(ValueError):
        read_sources(scene)
    assert not list((scene.new / "commands").glob("*.json"))


def test_foreign_ready_admission_is_not_offered(build_unexecuted):
    scene = build_unexecuted()
    path = scene.new.parent / "recovery-admissions" / "fresh-epoch-admission.json"
    value = read_json_snapshot(path)
    value["new_session_name"] = "session-" + "e" * 32
    write_json_snapshot(path, value)
    assert read_sources(scene) == []


def test_empty_original_epoch_does_not_invent_a_workflow(epoch_scene):
    scene = epoch_scene
    root = scene.old.parent / "memory-library"
    root.mkdir()
    preview = scene.manager.preview_recovery()
    scene.manager.recover_session("empty-workflow-epoch", preview["preview_sha256"])
    from app.learning_memory.workflow_takeover_sources import read_takeover_sources
    before = old_bytes(scene)
    assert read_takeover_sources(scene.manager.session, root) == []
    assert old_bytes(scene) == before


def test_foreign_library_and_source_path_are_rejected(build_unexecuted, tmp_path):
    scene = build_unexecuted()
    from app.learning_memory.workflow_takeover_sources import read_takeover_sources
    with pytest.raises(ValueError):
        read_takeover_sources(scene.new, tmp_path / "other-library")
    path = scene.new.parent / "recovery-admissions" / "fresh-epoch-admission.json"
    value = read_json_snapshot(path)
    value["preview"]["source_session"] = str(tmp_path / "outside")
    write_json_snapshot(path, value)
    with pytest.raises(ValueError):
        read_sources(scene)
    assert not list((scene.new / "commands").glob("*.json"))

def test_unrelated_live_report_updates_do_not_invalidate_source_scan(build_unexecuted, monkeypatch):
    scene = build_unexecuted()
    from app.learning_memory import workflow_takeover_sources as module
    original = module.inspect_session_input_terminal
    count = []
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        report = scene.new / "report.json"
        status = read_json_snapshot(report)
        status["observer_heartbeat"] = len(count)
        count.append(True)
        write_json_snapshot(report, status)
        return value
    monkeypatch.setattr(module, "inspect_session_input_terminal", observe)
    assert read_sources(scene)[0]["source_run_id"] == scene.source_run_id
    assert len(count) == 2
