"""新宿主准入事务使用真实持久记录，不启动进程。"""
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import pytest

from app.core.json_snapshot import write_json_snapshot, read_json_snapshot
from app.execution.session_resources import SessionResourceJournal


@pytest.fixture
def scene(tmp_path, monkeypatch):
    from app.execution import session_epoch_admission as module
    old = tmp_path / ("session-" + "a" * 32)
    old.mkdir()
    identity = {"pid": 101, "created": 123.0}
    pointer = {"name": old.name, "host_identity": identity, "recognition_source": "agent_current",
               "delegate_profile": None, "api_profile": None}
    write_json_snapshot(tmp_path / "latest-session.json", pointer)
    write_json_snapshot(old / "report.json", {"runner_pid": 101})
    SessionResourceJournal(old, recognition_source="agent_current", host_identity=identity,
                           runner_identity={"pid": 101, "create_time_ns": 123000000000}).mark_ready()
    instant = SimpleNamespace(data_root=tmp_path, root=tmp_path / "code", session=old,
        recognition_source="agent_current", delegate_profile=None, api_profile=None, guard=RLock(),
        _lock=lambda: None, _startup_configuration=lambda: SimpleNamespace(source="agent_current"),
        _check_peer_hosts=lambda **kwargs: None)
    calls = []
    instant.status = lambda: {"phase": "ready", "host_alive": True, "session_directory": str(instant.session)}
    monkeypatch.setattr(module, "observe_session_resource_cleanup", lambda path: {
        "resources_cleanup_verified": True, "session_name": old.name, "host_identity": identity,
        "runner_identity": {"pid": 101, "create_time_ns": 123000000000},
        "recognition_source": "agent_current", "original_snapshots": {
            key: module._sha(p.read_bytes()) for key, p in {
                "pointer": tmp_path / "latest-session.json", "report": old / "report.json",
                "resources": old / "session-resources.json"}.items()}})
    monkeypatch.setattr(module, "_inspect_inputs", lambda *args, **kwargs: {
        "input_terminal_settlement_verified": True, "catalog_sha256": "f" * 64})
    monkeypatch.setattr(module.SessionEpochAdmission, "_verify_created", lambda *args: None)
    monkeypatch.setattr(module.SessionEpochAdmission, "_ready", lambda self, record: True)

    def launch(config, *, session_name, on_created, before_publish):
        calls.append(session_name)
        instant.session = tmp_path / session_name
        instant.host_identity = {"pid": 202, "created": 456.0}
        instant.session.mkdir()
        on_created(instant.host_identity)
        before_publish()
        write_json_snapshot(tmp_path / "latest-session.json", {**pointer, "name": session_name,
                                                               "host_identity": instant.host_identity})
        return instant.status()
    instant._launch_session = launch
    return module, instant, calls


def test_preview_is_stable_readonly_and_recovery_is_idempotent(scene):
    module, instant, calls = scene
    service = module.SessionEpochAdmission(instant)
    before = {p: p.read_bytes() for p in instant.data_root.rglob("*") if p.is_file()}
    preview = service.preview()
    assert service.preview() == preview
    assert {p: p.read_bytes() for p in instant.data_root.rglob("*") if p.is_file()} == before
    assert calls == []
    result = service.recover("recover-one", preview["preview_sha256"])
    assert result["recovery_admission"]["new_epoch_ready"] is True
    assert result["recovery_admission"]["workflow_takeover_completed"] is False
    assert service.recover("recover-one", preview["preview_sha256"]) == result
    assert len(calls) == 1


def test_started_without_identity_never_spawns_again(scene):
    module, instant, calls = scene
    service = module.SessionEpochAdmission(instant)
    preview = service.preview()
    def fail(*args, **kwargs):
        calls.append("failed-launch")
        raise RuntimeError("launch uncertainty")
    instant._launch_session = fail
    with pytest.raises(RuntimeError, match="uncertainty"):
        service.recover("recover-one", preview["preview_sha256"])
    result = service.recover("recover-one", preview["preview_sha256"])
    assert result["recovery_admission"]["phase"] == "launch_unknown"
    assert result["recovery_admission"]["new_epoch_ready"] is False
    with pytest.raises(ValueError, match="unfinished"):
        service.recover("other-request", preview["preview_sha256"])
    assert len(calls) == 1


def test_prepare_write_failure_has_zero_launches(scene, monkeypatch):
    module, instant, calls = scene
    service = module.SessionEpochAdmission(instant)
    preview = service.preview()
    monkeypatch.setattr(module, "write_json_snapshot", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        service.recover("recover-one", preview["preview_sha256"])
    assert calls == []


def test_changed_hash_rejected_before_launch(scene):
    module, instant, calls = scene
    with pytest.raises(ValueError, match="preview_changed"):
        module.SessionEpochAdmission(instant).recover("recover-one", "0" * 64)
    assert calls == []


@pytest.mark.parametrize("failed_phase", ["host_created", "pointer_published", "ready"])
def test_stage_write_failure_preserves_durable_state_without_second_spawn(scene, monkeypatch, failed_phase):
    module, instant, calls = scene
    service = module.SessionEpochAdmission(instant)
    preview = service.preview()
    original = module.write_json_snapshot
    failed = []

    def write(path, value):
        if Path(path).parent.name == "recovery-admissions" and value.get("phase") == failed_phase and not failed:
            failed.append(True)
            raise OSError("stage write failed")
        return original(path, value)

    monkeypatch.setattr(module, "write_json_snapshot", write)
    with pytest.raises(OSError, match="stage write failed"):
        service.recover("recover-one", preview["preview_sha256"])
    record = read_json_snapshot(instant.data_root / "recovery-admissions/recover-one.json")
    assert record["phase"] == {"host_created": "launch_started", "pointer_published": "host_created",
                               "ready": "pointer_published"}[failed_phase]
    result = service.recover("recover-one", preview["preview_sha256"])
    assert result["recovery_admission"]["phase"] == ("launch_unknown" if failed_phase == "host_created" else "ready")
    assert len(calls) == 1


def test_created_host_before_publish_failure_can_publish_same_host(scene, monkeypatch):
    module, instant, calls = scene
    service = module.SessionEpochAdmission(instant)
    preview = service.preview()
    failures = []

    def verify(self, record):
        if not failures:
            failures.append(True)
            raise ValueError("interrupted before publish")

    monkeypatch.setattr(module.SessionEpochAdmission, "_verify_created", verify)
    with pytest.raises(ValueError, match="interrupted"):
        service.recover("recover-one", preview["preview_sha256"])
    assert read_json_snapshot(instant.data_root / "latest-session.json")["name"] == "session-" + "a" * 32
    result = service.recover("recover-one", preview["preview_sha256"])
    assert result["recovery_admission"]["new_epoch_ready"] is True
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["report", "inventory", "input", "pointer", "record"])
def test_published_retry_rejects_drift_without_new_spawn(scene, monkeypatch, change):
    module, instant, calls = scene
    service = module.SessionEpochAdmission(instant)
    preview = service.preview()
    service.recover("recover-one", preview["preview_sha256"])
    old = instant.data_root / ("session-" + "a" * 32)
    if change in {"report", "inventory"}:
        path = old / ("report.json" if change == "report" else "session-resources.json")
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "input":
        monkeypatch.setattr(module, "_inspect_inputs", lambda *args, **kwargs: {"input_terminal_settlement_verified": True,
                                                                    "catalog_sha256": "0" * 64})
    elif change == "pointer":
        write_json_snapshot(instant.data_root / "latest-session.json", {"name": "session-" + "c" * 32})
    else:
        path = instant.data_root / "recovery-admissions/recover-one.json"
        record = read_json_snapshot(path)
        record["phase"] = "unknown"
        write_json_snapshot(path, record)
    with pytest.raises(ValueError):
        service.recover("recover-one", preview["preview_sha256"])
    assert len(calls) == 1


def test_real_ready_validator_binds_journal_launcher_runner_and_empty_queue(tmp_path, monkeypatch):
    from app.execution import session_epoch_admission as module
    session = tmp_path / ("session-" + "b" * 32)
    session.mkdir()
    host = {"pid": 202, "created": 456.0}
    instant = SimpleNamespace(data_root=tmp_path, root=tmp_path / "code", recognition_source="agent_current",
                              delegate_profile=None, api_profile=None)
    command = ["python.exe", str(instant.root / "scripts/run_local_step_session.py"), "--output", str(session),
               "--recognition-source", "agent_current", "--local-no-learning"]
    process = SimpleNamespace(create_time=lambda: 456.0, is_running=lambda: True,
                              status=lambda: "running", cmdline=lambda: command, ppid=lambda: 202)
    monkeypatch.setattr(module.psutil, "Process", lambda pid: process)
    journal = SessionResourceJournal(session, recognition_source="agent_current", host_identity=host,
                                    runner_identity={"pid": 203, "create_time_ns": 456000000000})
    journal.mark_ready()
    write_json_snapshot(session / "report.json", {"phase": "ready", "runner_pid": 203})
    record = {"new_session_name": session.name, "new_host_identity": host, "phase": "pointer_published"}
    service = module.SessionEpochAdmission(instant)
    assert service._ready(record) is True
    process.ppid = lambda: 999
    with pytest.raises(ValueError, match="ancestry"):
        service._ready(record)
    process.ppid = lambda: 202
    (session / "commands").mkdir()
    (session / "commands/old.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="not_empty"):
        service._ready(record)


@pytest.mark.parametrize("drift", ["owner_revived", "old_file", "foreign_pointer"])
def test_unknown_launch_does_not_claim_current_proofs_after_old_epoch_drift(scene, monkeypatch, drift):
    module, instant, calls = scene
    service = module.SessionEpochAdmission(instant)
    preview = service.preview()

    def uncertain(*args, **kwargs):
        calls.append("uncertain-launch")
        raise RuntimeError("created identity unavailable")

    instant._launch_session = uncertain
    with pytest.raises(RuntimeError, match="identity unavailable"):
        service.recover("recover-one", preview["preview_sha256"])
    record_path = instant.data_root / "recovery-admissions/recover-one.json"
    before_record = record_path.read_bytes()
    assert read_json_snapshot(record_path)["phase"] == "launch_started"
    old = Path(preview["source_session"])
    if drift == "owner_revived":
        def active(*args):
            raise ValueError("resource_original_process_active")
        monkeypatch.setattr(module, "_inactive", active)
        monkeypatch.setattr(module, "observe_session_resource_cleanup", active)
    elif drift == "old_file":
        (old / "report.json").write_bytes((old / "report.json").read_bytes() + b" ")
    else:
        write_json_snapshot(instant.data_root / "latest-session.json", {"name": "session-" + "c" * 32})
    result = service.recover("recover-one", preview["preview_sha256"])
    facts = result["recovery_admission"]
    assert facts["phase"] == "launch_unknown"
    assert facts["new_epoch_ready"] is False
    assert facts["resources_cleanup_verified"] is False
    assert facts["input_terminal_settlement_verified"] is False
    assert facts["historical_resources_cleanup_verified"] is True
    assert facts["historical_input_terminal_settlement_verified"] is True
    assert facts["workflow_takeover_completed"] is False
    assert len(calls) == 1
    assert record_path.read_bytes() == before_record


def test_fresh_ready_rejects_actual_workflow_runner_directory(tmp_path, monkeypatch):
    from app.execution import session_epoch_admission as module
    session = tmp_path / ("session-" + "b" * 32)
    session.mkdir()
    host = {"pid": 202, "created": 456.0}
    instant = SimpleNamespace(data_root=tmp_path, recognition_source="agent_current")
    journal = SessionResourceJournal(session, recognition_source="agent_current", host_identity=host,
        runner_identity={"pid": 202, "create_time_ns": 456000000000})
    journal.mark_ready()
    write_json_snapshot(session / "report.json", {"phase": "ready", "runner_pid": 202})
    monkeypatch.setattr(module.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 456.0))
    monkeypatch.setattr(module.SessionEpochAdmission, "_process", lambda *args: None)
    (session / "workflow-runners").mkdir()
    (session / "workflow-runners/active.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="new_host_not_empty"):
        module.SessionEpochAdmission(instant)._ready({"new_session_name": session.name,
                                                    "new_host_identity": host, "phase": "pointer_published"})


@pytest.mark.parametrize("source,arguments", [
    ("local", []), ("local", ["--model-directory", "foreign"]),
    ("local", ["--model-directory", "models", "--model-directory", "models"]),
    ("agent_current", ["--model-directory", "models"]),
])
def test_process_rejects_missing_foreign_duplicate_or_unexpected_model_directory(tmp_path, monkeypatch, source, arguments):
    from app.execution import session_epoch_admission as module
    session = tmp_path / ("session-" + "b" * 32)
    instant = SimpleNamespace(root=tmp_path / "code", recognition_source=source, delegate_profile=None,
                              api_profile=None, model_directory=tmp_path / "models")
    command = ["python.exe", str(instant.root / "scripts/run_local_step_session.py"), "--output", str(session),
               "--recognition-source", source, "--local-no-learning", *arguments]
    process = SimpleNamespace(create_time=lambda: 456.0, is_running=lambda: True, status=lambda: "running",
                              cmdline=lambda: command)
    monkeypatch.setattr(module.psutil, "Process", lambda pid: process)
    with pytest.raises(ValueError, match="model_directory"):
        module.SessionEpochAdmission(instant)._process({"pid": 202, "created": 456.0}, session)
