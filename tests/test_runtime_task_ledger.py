"""Only synthetic persisted sessions; no host, input, screenshots or model calls."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from app import runtime_task_ledger as ledger


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def scene(tmp_path, monkeypatch):
    root = tmp_path / "installed-runtime"
    root.mkdir()
    session = tmp_path / "data" / ("session-" + "a" * 32)
    session.mkdir(parents=True)
    for name in ("commands", "responses"):
        (session / name).mkdir()
    journal = {"contract_version": "session_resources.v1", "session_name": session.name,
        "recognition_source": "agent_current", "host_identity": {"pid": 999991, "created": 123.0},
        "runner_identity": {"pid": 999991, "create_time_ns": 123000000000}, "phase": "ready", "resources": {}}
    report = {"finished_at": "2026-10-24T00:00:00Z", "phase": "stopped", "host_phase": "stopped",
        "cleanup_errors": [], "sampler_stopped": True, "runner_pid": 999991}
    save(session / "session-resources.json", journal)
    save(session / "report.json", report)
    processes = {os.getpid(): 123.0}
    def process(pid):
        if pid not in processes:
            raise psutil.NoSuchProcess(pid)
        return SimpleNamespace(create_time=lambda: processes[pid], is_running=lambda: True,
                               status=lambda: psutil.STATUS_RUNNING)
    monkeypatch.setattr(psutil, "Process", process)
    return SimpleNamespace(root=root, session=session, journal=journal, report=report, processes=processes)


def marker(scene):
    return next(ledger.registry_directory(scene.root).glob("*.json"))


def evidence_bytes(scene):
    return {str(path): path.read_bytes() for path in scene.session.rglob("*") if path.is_file()}


def command(scene, request_id="input", *, response=True):
    value = {"kind": "step", "operation": "type_text", "request": {"text": "synthetic"}}
    save(scene.session / "commands" / (request_id + ".json"), value)
    if response:
        save(scene.session / "responses" / (request_id + ".json"), {"command": value,
             "status": "returned", "result": {"phase": "returned", "response": {"data": {"action_executed": True}}}})
    return value


def test_registration_precedes_host_creation_and_is_idempotent(tmp_path):
    root = tmp_path / "runtime"
    session = tmp_path / "external-data" / ("session-" + "a" * 32)
    first = ledger.register(root, session)
    path = next(ledger.registry_directory(root).iterdir())
    raw, stamp = path.read_bytes(), path.stat().st_mtime_ns
    assert ledger.register(root, session) == first
    assert path.read_bytes() == raw and path.stat().st_mtime_ns == stamp
    assert not session.exists() and not root.exists()
    with pytest.raises(ledger.RuntimeTaskLedgerError):
        ledger.assert_settled(root)
    assert path.exists()


def test_known_unlaunched_parent_can_clear_only_its_uncreated_session(scene):
    session = scene.session.parent / ("session-" + "c" * 32)
    ledger.register(scene.root, session)
    assert ledger.abandon_unlaunched(scene.root, session)["abandoned"] is True
    assert not session.exists() and not list(ledger.registry_directory(scene.root).iterdir())


@pytest.mark.parametrize("failure", ["created_empty_directory", "other_parent", "reused_parent_pid"])
def test_unlaunched_abandon_cannot_hide_created_or_foreign_host(scene, failure):
    session = scene.session.parent / ("session-" + "c" * 32)
    ledger.register(scene.root, session)
    path = marker(scene)
    if failure == "created_empty_directory":
        session.mkdir()
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
        if failure == "other_parent": value["registrant"]["pid"] += 100
        else: value["registrant"]["created"] += 1
        save(path, value)
    before = path.read_bytes()
    with pytest.raises(ledger.RuntimeTaskLedgerError):
        ledger.abandon_unlaunched(scene.root, session)
    assert path.read_bytes() == before


def test_absent_registry_does_not_claim_legacy_coverage_or_create_files(tmp_path):
    root = tmp_path / "runtime"
    result = ledger.assert_settled(root)
    assert result["registered_sessions"] == 0
    assert result["coverage"] == "registered_sessions_only" and result["legacy_sessions_proven"] is False
    assert list(tmp_path.iterdir()) == []


def test_completed_input_is_verified_readonly_and_only_exact_marker_cleared(scene):
    command(scene)
    ledger.register(scene.root, scene.session)
    before = evidence_bytes(scene)
    assert ledger.assert_settled(scene.root)["registered_sessions"] == 1
    assert marker(scene).exists() and evidence_bytes(scene) == before
    assert ledger.clear(scene.root, scene.session)["cleared"] is True
    assert ledger.clear(scene.root, scene.session)["cleared"] is False
    assert evidence_bytes(scene) == before


def test_direct_cli_keeps_arbitrary_absolute_output_directory_contract(scene):
    old = scene.session
    scene.session = old.with_name("direct-cli-output-中文")
    old.rename(scene.session)
    scene.journal["session_name"] = scene.session.name
    save(scene.session / "session-resources.json", scene.journal)
    command(scene)
    ledger.register(scene.root, scene.session)
    assert ledger.assert_settled(scene.root)["registered_sessions"] == 1
    assert ledger.clear(scene.root, scene.session)["cleared"] is True


@pytest.mark.parametrize("field,value", [("finished_at", None), ("phase", "ready"),
    ("host_phase", "cleanup_pending"), ("cleanup_errors", [{"operation": "shutdown"}]),
    ("sampler_stopped", False), ("runner_pid", 88888)])
def test_dead_pid_never_substitutes_for_cleanup_proof(scene, field, value):
    ledger.register(scene.root, scene.session)
    scene.report[field] = value
    save(scene.session / "report.json", scene.report)
    with pytest.raises(ledger.RuntimeTaskLedgerError):
        ledger.clear(scene.root, scene.session)
    assert marker(scene).exists()


def test_missing_report_after_crash_blocks_even_without_any_live_pid(scene):
    ledger.register(scene.root, scene.session)
    (scene.session / "report.json").unlink()
    with pytest.raises(ledger.RuntimeTaskLedgerError):
        ledger.assert_settled(scene.root)
    assert marker(scene).exists()


@pytest.mark.parametrize("failure", ["missing_response", "unknown_input", "orphan_response", "waiting_worker"])
def test_report_cleanup_does_not_hide_unsettled_original_input(scene, failure):
    ledger.register(scene.root, scene.session)
    original = command(scene, response=failure != "missing_response")
    if failure == "unknown_input":
        save(scene.session / "responses/input.json", {"command": original, "status": "failed", "result": {"phase": "result_unknown"}})
    elif failure == "orphan_response":
        save(scene.session / "responses/orphan.json", {"status": "returned"})
    elif failure == "waiting_worker":
        original = {"kind": "desktop_click", "request": {"goal": "synthetic"}}
        save(scene.session / "commands/input.json", original)
        save(scene.session / "responses/input.json", {"command": original, "status": "returned", "result": {
            "contract_version": "agent_command.v1", "command_id": "input", "status": "running", "action_executed": False}})
        save(scene.session / "agent-commands/input.json", {"contract_version": "agent_command.v1", "command_id": "input",
            "status": "awaiting_grounding", "action_executed": False, "dispatch_in_progress": False, "dispatch_attempts": []})
    with pytest.raises(ledger.RuntimeTaskLedgerError):
        ledger.assert_settled(scene.root, clear_settled=True)
    assert marker(scene).exists()


def test_live_original_runner_blocks_maintenance_but_can_clear_after_final_cleanup(scene):
    current = os.getpid()
    scene.journal.update(host_identity={"pid": current, "created": 123.0},
                         runner_identity={"pid": current, "create_time_ns": 123000000000})
    scene.report["runner_pid"] = current
    scene.processes[current] = 123.0
    save(scene.session / "session-resources.json", scene.journal)
    save(scene.session / "report.json", scene.report)
    ledger.register(scene.root, scene.session)
    with pytest.raises(ledger.RuntimeTaskLedgerError):
        ledger.assert_settled(scene.root)
    assert ledger.clear(scene.root, scene.session)["cleared"] is True


@pytest.mark.parametrize("damage", ["root", "session", "filename", "json", "duplicate_key", "interrupted_registration"])
def test_corrupt_or_foreign_registry_entries_are_never_ignored(scene, damage):
    ledger.register(scene.root, scene.session)
    path = marker(scene)
    value = json.loads(path.read_text(encoding="utf-8"))
    if damage == "root": value["installation_root"] = str(scene.root.parent / "foreign")
    if damage == "session": value["session_path"] = str(scene.session.parent / ("session-" + "b" * 32))
    if damage in {"root", "session"}: save(path, value)
    if damage == "filename": path.rename(path.with_name("b" * 64 + ".json"))
    if damage == "json": path.write_text("{", encoding="utf-8")
    if damage == "duplicate_key": path.write_text('{"schema":"wrong","schema":"runtime_task_ledger.v1"}', encoding="utf-8")
    if damage == "interrupted_registration": (path.parent / ".register-interrupted.tmp").write_bytes(b"partial")
    before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
    with pytest.raises(ledger.RuntimeTaskLedgerError):
        ledger.assert_settled(scene.root, clear_settled=True)
    assert {p.name: p.read_bytes() for p in path.parent.iterdir()} == before


@pytest.mark.parametrize("path", ["relative/session-" + "a" * 32, "../session-" + "a" * 32])
def test_relative_or_traversing_session_is_rejected_without_registration(scene, path):
    with pytest.raises(ledger.RuntimeTaskLedgerError):
        ledger.register(scene.root, path)
    assert not ledger.registry_directory(scene.root).exists()


def test_reparse_observation_is_rejected_before_read_or_write(scene, monkeypatch):
    original = Path.lstat
    def facts(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == scene.session:
            return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400)
        return value
    monkeypatch.setattr(Path, "lstat", facts)
    with pytest.raises(ledger.RuntimeTaskLedgerError, match="reparse"):
        ledger.register(scene.root, scene.session)
    assert not ledger.registry_directory(scene.root).exists()


def test_registry_drift_never_prunes_previously_verified_entries(scene, monkeypatch):
    ledger.register(scene.root, scene.session)
    original = ledger.read_session_status
    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        (ledger.registry_directory(scene.root) / ("f" * 64 + ".json")).write_bytes(b"{}")
        return result
    monkeypatch.setattr(ledger, "read_session_status", drift)
    with pytest.raises(ledger.RuntimeTaskLedgerError, match="registry_changed"):
        ledger.assert_settled(scene.root, clear_settled=True)
    assert len(list(ledger.registry_directory(scene.root).iterdir())) == 2


def test_evidence_drift_during_probe_keeps_registration(scene, monkeypatch):
    from app.core import session_input_terminal as core
    ledger.register(scene.root, scene.session)
    original = core.inspect_session_input_terminal
    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        scene.report["phase"] = "cleanup_pending"
        save(scene.session / "report.json", scene.report)
        return result
    monkeypatch.setattr(core, "inspect_session_input_terminal", drift)
    with pytest.raises(ledger.RuntimeTaskLedgerError, match="evidence_changed"):
        ledger.clear(scene.root, scene.session)
    assert marker(scene).exists()


def recovery(scene):
    from app.core.session_input_terminal import inspect_session_input_terminal
    from app.desktop_review.external_mapping import canonical_json_bytes
    from app.execution.session_resource_recovery import observe_session_resource_cleanup
    scene.report.pop("finished_at")
    scene.report["phase"] = "ready"
    save(scene.session / "report.json", scene.report)
    pointer = {"name": scene.session.name, "host_identity": scene.journal["host_identity"],
               "recognition_source": "agent_current", "delegate_profile": None, "api_profile": None}
    save(scene.session.parent / "latest-session.json", pointer)
    preview = {"contract_version": "session_epoch_admission_preview.v1", "source_session": str(scene.session),
        "original_pointer_raw_utf8": (scene.session.parent / "latest-session.json").read_bytes().decode("utf-8"),
        "resource_proof": observe_session_resource_cleanup(scene.session),
        "input_proof": inspect_session_input_terminal(scene.session, scene.session.parent / "memory-library")}
    digest = hashlib.sha256(canonical_json_bytes(preview)).hexdigest()
    preview["preview_sha256"] = digest
    record = {"contract_version": "session_epoch_admission.v1", "request_id": "recover-original",
        "preview_sha256": digest, "preview": preview, "new_session_name": "session-" + "b" * 32,
        "phase": "ready", "new_host_identity": {"pid": 999992, "created": 124.0}}
    path = scene.session.parent / "recovery-admissions/recover-original.json"
    save(path, record)
    pointer.update(name=record["new_session_name"], host_identity=record["new_host_identity"])
    save(scene.session.parent / "latest-session.json", pointer)
    return path, record


def test_explicit_recovery_revalidates_original_epoch_after_pointer_moves(scene):
    command(scene)
    ledger.register(scene.root, scene.session)
    recovery(scene)
    before = evidence_bytes(scene)
    proof = ledger.assert_settled(scene.root, clear_settled=True)
    assert proof["cleared_sessions"] == 1 and evidence_bytes(scene) == before


@pytest.mark.parametrize("damage", ["not_ready", "report_changed", "historical_flag_only"])
def test_recovery_is_not_a_way_to_erase_unknown_or_changed_evidence(scene, damage):
    ledger.register(scene.root, scene.session)
    path, record = recovery(scene)
    if damage == "not_ready":
        record["phase"] = "host_created"
        save(path, record)
    elif damage == "report_changed":
        scene.report["unexpected"] = True
        save(scene.session / "report.json", scene.report)
    else:
        record["preview"]["input_proof"] = {"input_terminal_settlement_verified": True}
        from app.desktop_review.external_mapping import canonical_json_bytes
        preview = {k: v for k, v in record["preview"].items() if k != "preview_sha256"}
        digest = hashlib.sha256(canonical_json_bytes(preview)).hexdigest()
        record["preview"]["preview_sha256"] = record["preview_sha256"] = digest
        save(path, record)
    with pytest.raises(ledger.RuntimeTaskLedgerError):
        ledger.assert_settled(scene.root, clear_settled=True)
    assert marker(scene).exists()
