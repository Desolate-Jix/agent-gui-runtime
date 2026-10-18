"""归档准入链仅证明来源，不授予恢复输入。"""
from copy import deepcopy
from hashlib import sha256
import json

import psutil
import pytest

from app.core.json_snapshot import write_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.execution.session_resources import SessionResourceJournal
from tests.test_session_admitted_settlement import admitted
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


@pytest.fixture
def archived(admitted, monkeypatch):
    old, _, recovery, run, path, first = admitted
    first["phase"] = "ready"
    write_json_snapshot(path, first)
    middle = old.parent / first["new_session_name"]
    middle.mkdir()
    pointer = json.loads((old.parent / "latest-session.json").read_text(encoding="utf-8"))
    write_json_snapshot(middle / "report.json", {"runner_pid": 900002})
    journal = SessionResourceJournal(middle, recognition_source="agent_current", host_identity=pointer["host_identity"],
        runner_identity={"pid": 900002, "create_time_ns": 124000000000})
    journal.mark_ready()
    raw = (old.parent / "latest-session.json").read_bytes()
    proof = {"contract_version": "session_resource_cleanup.v1", "resources_cleanup_verified": True,
        "session_name": middle.name, "host_identity": pointer["host_identity"], "recognition_source": "agent_current",
        "runner_identity": journal._state["runner_identity"], "original_snapshots": {"pointer": sha256(raw).hexdigest(),
            "report": sha256((middle / "report.json").read_bytes()).hexdigest(), "resources": sha256(journal.path.read_bytes()).hexdigest()}}
    preview = {"contract_version": "session_epoch_admission_preview.v1", "source_session": str(middle),
        "original_pointer_raw_utf8": raw.decode("utf-8"), "resource_proof": proof,
        "input_proof": {"contract_version": "session_input_terminal.v1", "input_terminal_settlement_verified": True,
            "files": {name: sha256((middle / name).read_bytes()).hexdigest()
                      for name in ("report.json", "session-resources.json")}}}
    digest = sha256(canonical_json_bytes(preview)).hexdigest()
    preview["preview_sha256"] = digest
    second = {"contract_version": "session_epoch_admission.v1", "request_id": "admitted-two", "phase": "ready",
        "preview": preview, "preview_sha256": digest, "new_session_name": "session-" + "c" * 32,
        "new_host_identity": {"pid": 900003, "created": 125.0}}
    successor = path.parent / "admitted-two.json"
    write_json_snapshot(successor, second)
    write_json_snapshot(old.parent / "latest-session.json", {**pointer, "name": second["new_session_name"],
        "host_identity": second["new_host_identity"]})
    def process(pid):
        if pid != 900003:
            raise psutil.NoSuchProcess(pid)
        return type("Process", (), {"create_time": lambda self: 125.0, "is_running": lambda self: True,
            "status": lambda self: psutil.STATUS_RUNNING})()
    monkeypatch.setattr(psutil, "Process", process)
    return old, recovery, run, path, successor, second


def test_archived_reads_real_settlement_without_changing_files(archived):
    old, recovery, run, first, successor, _ = archived
    before = {p: p.read_bytes() for p in old.parent.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        recovery.status_admitted(run, first)
    state = recovery.status_archived(run, first, [successor])
    assert state == recovery.trials.status(run)
    assert state["recovery_settlement"]["action_executed"] is True
    assert before == {p: p.read_bytes() for p in old.parent.rglob("*") if p.is_file()}


@pytest.mark.parametrize("change", ["missing", "phase", "hash", "route", "resources", "owner_alive", "final_reuse", "cycle", "mode", "host"])
def test_archived_invalid_chain_rejects(archived, monkeypatch, change):
    old, recovery, run, first, successor, second = archived
    paths = [successor]
    if change == "missing": paths = []
    elif change == "phase": second["phase"] = "launch_started"
    elif change == "hash": second["preview_sha256"] = "0" * 64
    elif change == "route":
        pointer = json.loads(second["preview"]["original_pointer_raw_utf8"])
        pointer["delegate_profile"] = "foreign"
        second["preview"]["original_pointer_raw_utf8"] = json.dumps(pointer)
        second["preview"]["resource_proof"]["original_snapshots"]["pointer"] = sha256(second["preview"]["original_pointer_raw_utf8"].encode("utf-8")).hexdigest()
        digest = sha256(canonical_json_bytes({key: value for key, value in second["preview"].items() if key != "preview_sha256"})).hexdigest()
        second["preview_sha256"] = second["preview"]["preview_sha256"] = digest
    elif change == "resources": (old.parent / second["preview"]["resource_proof"]["session_name"] / "session-resources.json").write_bytes(b"{}")
    elif change == "cycle": paths = [successor, first]
    elif change == "mode": second["mode"] = "resume"
    elif change == "host": second["new_host_identity"]["created"] = True
    else:
        def process(pid):
            if change == "owner_alive" and pid == 900002:
                created = 124.0
            elif pid == 900003:
                created = 126.0 if change == "final_reuse" else 125.0
            else: raise psutil.NoSuchProcess(pid)
            return type("Process", (), {"create_time": lambda self: created, "is_running": lambda self: True,
                "status": lambda self: psutil.STATUS_RUNNING})()
        monkeypatch.setattr(psutil, "Process", process)
    write_json_snapshot(successor, second)
    with pytest.raises(ValueError): recovery.status_archived(run, first, paths)


def test_archived_cross_validation_drift_is_rejected(archived, monkeypatch):
    old, recovery, run, first, successor, _ = archived
    original = recovery._status
    changed = []

    def status(*args, **kwargs):
        result = original(*args, **kwargs)
        if not changed:
            successor.write_bytes(successor.read_bytes() + b" ")
            changed.append(True)
        return result

    monkeypatch.setattr(recovery, "_status", status)
    with pytest.raises(ValueError, match="admission_changed"):
        recovery.status_archived(run, first, [successor])
    assert changed


def test_archived_successor_input_assets_must_match_catalog(archived):
    old, recovery, run, first, successor, second = archived
    middle = old.parent / second["preview"]["resource_proof"]["session_name"]
    (middle / "commands").mkdir()
    write_json_snapshot(middle / "commands/foreign.json", {"kind": "step"})
    with pytest.raises(ValueError, match="input_snapshot_invalid"):
        recovery.status_archived(run, first, [successor])
