"""资源证明只读，不能把身份缺口或关闭记录冒充完整恢复。"""
from copy import deepcopy
import hashlib
from pathlib import Path

import psutil
import pytest

from app.core.json_snapshot import write_json_snapshot
from app.execution import session_resources
from app.learn.hybrid import windows_process_scope as scopes


RID = "c" * 32
POLICY = {"kill_on_job_close": True, "breakaway_ok": False,
          "silent_breakaway_ok": False, "owner_handle_authority": "registry_parent"}


@pytest.fixture
def scene(tmp_path, monkeypatch):
    session = tmp_path / "新资源验收" / ("session-" + "d" * 32)
    session.mkdir(parents=True)
    journal = session_resources.SessionResourceJournal(session, recognition_source="agent_current",
        host_identity={"pid": 71, "created": 1.25}, runner_identity={"pid": 72, "create_time_ns": 1500000000})
    journal.mark_ready()
    write_json_snapshot(session.parent / "latest-session.json", {
        "name": session.name, "recognition_source": "agent_current", "host_identity": {"pid": 71, "created": 1.25}})
    write_json_snapshot(session / "report.json", {"runner_pid": 72, "phase": "ready"})
    def gone(pid):
        raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr(psutil, "Process", gone)
    return session, journal


def observe(session):
    from app.execution import session_resource_recovery as recovery
    operation = getattr(recovery, "observe_session_resource_cleanup", None)
    assert callable(operation), "resource cleanup observer is missing"
    return operation(session, timeout_seconds=.1)


def snapshot(session):
    return {str(path.relative_to(session.parent)): path.read_bytes()
            for path in session.parent.rglob("*") if path.is_file()}


def register(journal, phase="registered", *, closed=False):
    journal.register_model(RID, scope_name="Local\\AgentGuiNativeModel-" + hashlib.sha256(RID.encode()).hexdigest(),
        pid_file=journal.session_dir / "runtime-output" / "model-services" / RID / "model-server-pids" / "fresh.pid")
    if phase != "registered":
        journal.begin_model_scope(RID)
    if phase in {"scope_acquired", "launch_starting", "launch_registered", "ready"}:
        journal.model_scope_acquired(RID, POLICY)
    if phase in {"launch_starting", "launch_registered", "ready"}:
        journal.begin_model_launch(RID)
    if phase in {"launch_registered", "ready"}:
        journal.model_process_created(RID, {"pid": 73, "create_time_ns": 1600000000})
    if phase == "ready":
        journal.model_ready(RID, ownership="owned", member_identities=[{"pid": 74, "create_time_ns": 1700000000}])
    if closed:
        journal.model_closed(RID)


def verified(scope_name):
    zero = {"pids": [], "process_identities": [], "listeners": [], "remaining_owned_process_identities": []}
    return {"contract_version": scopes.PROCESS_SCOPE_CONTRACT_VERSION, "scope_name": scope_name,
        "authority": "windows_job_object", "scope_absent_after_owner_close": True,
        "cleanup_status": "verified", "observed_member_pids_before": [], "observed_member_identities_before": [],
        "member_pids_after": [], "member_identities_after": [], "remaining_owned_process_identities": [],
        "active_listeners_after": [], "pid_file_after": None, "stable_zero_observations": 3,
        "samples": [deepcopy(zero) for _ in range(3)]}


def test_empty_inventory_proof_does_not_admit_or_rewrite(scene):
    session, _ = scene
    before = snapshot(session)
    result = observe(session)
    assert result["contract_version"] == "session_resource_cleanup.v1"
    assert result["resources_cleanup_verified"] is True
    assert result["input_terminal_settlement_verified"] is False and result["new_epoch_ready"] is False
    assert snapshot(session) == before
    assert result["original_snapshots"]["resources"] == hashlib.sha256((session / "session-resources.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("phase", ["scope_starting", "launch_starting"])
@pytest.mark.parametrize("closed", [False, True])
def test_incomplete_launch_is_unknown_even_after_closed(scene, monkeypatch, phase, closed):
    session, journal = scene
    register(journal, phase, closed=closed)
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", lambda *a, **k: pytest.fail("incomplete evidence cannot enter scope proof"))
    before = snapshot(session)
    result = observe(session)
    assert result["resources_cleanup_verified"] is False
    assert result["model_resources"][RID]["status"] == "indeterminate"
    assert snapshot(session) == before


def test_owned_observation_pins_all_members_and_never_terminates(scene, monkeypatch):
    session, journal = scene
    register(journal, "ready")
    journal.model_cleanup_members_observed(RID, [{"pid": 75, "create_time_ns": 1800000000}])
    def read_scope(name, **kwargs):
        assert kwargs["terminate"] is False and kwargs["remove_owned_pid_file"] is False
        assert kwargs["listener_ports"] == [] and kwargs["stable_zero_observations"] == 3
        assert Path(kwargs["pid_file"]).is_relative_to(session)
        assert {(r["pid"], r["create_time_ns"]) for r in kwargs["retained_process_identities"]} == {
            (73, 1600000000), (74, 1700000000), (75, 1800000000)}
        return verified(name)
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", read_scope)
    before = snapshot(session)
    assert observe(session)["resources_cleanup_verified"] is True
    assert snapshot(session) == before


def test_owned_pending_request_can_only_prove_process_cleanup(scene, monkeypatch):
    session, journal = scene
    register(journal, "ready")
    journal.model_request_started(RID, "original-owned-request")
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", lambda name, **kwargs: verified(name))
    before = snapshot(session)
    proof = observe(session)
    assert proof["resources_cleanup_verified"] is True
    assert proof["input_terminal_settlement_verified"] is False and proof["new_epoch_ready"] is False
    assert session_resources.read_session_resources(session)["resources"][RID]["pending_request_id"] == "original-owned-request"
    assert snapshot(session) == before


def test_proof_decodes_inventory_from_the_same_bytes_it_hashes(scene, monkeypatch):
    from app.execution import session_resource_recovery as recovery
    session, journal = scene
    register(journal, "scope_starting")
    different = session_resources.read_session_resources(session)
    different["resources"] = {}
    monkeypatch.setattr(recovery, "read_session_resources", lambda root: different, raising=False)
    proof = observe(session)
    assert proof["resources_cleanup_verified"] is False
    assert RID in proof["model_resources"]


@pytest.mark.parametrize("pending", [False, True])
def test_external_model_is_left_alone_and_pending_is_unresolved(scene, monkeypatch, pending):
    session, journal = scene
    register(journal)
    journal.model_ready(RID, ownership="external", member_identities=[{"pid": 76, "create_time_ns": 1900000000}])
    if pending:
        journal.model_request_started(RID, "original-external-request")
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", lambda *a, **k: pytest.fail("external scope must not be opened"))
    before = snapshot(session)
    assert observe(session)["resources_cleanup_verified"] is (not pending)
    assert snapshot(session) == before


@pytest.mark.parametrize("failure", ["remaining", "pid_file", "short_samples", "wrong_scope", "denied"])
def test_scope_claim_without_complete_observation_is_not_proof(scene, monkeypatch, failure):
    session, journal = scene
    register(journal, "ready")
    def read_scope(name, **kwargs):
        if failure == "denied":
            raise psutil.AccessDenied(73)
        result = verified(name)
        if failure == "remaining": result["remaining_owned_process_identities"] = [{"pid": 73, "create_time_ns": 1600000000}]
        if failure == "pid_file": result["pid_file_after"] = str(kwargs["pid_file"])
        if failure == "short_samples": result["samples"] = result["samples"][:2]
        if failure == "wrong_scope": result["scope_name"] = "different"
        return result
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", read_scope)
    assert observe(session)["resources_cleanup_verified"] is False


@pytest.mark.parametrize("mode", ["live", "denied", "reused"])
def test_owner_incarnation_is_checked_without_killing_pid_reuse(scene, monkeypatch, mode):
    session, _ = scene
    class Process:
        def __init__(self, pid):
            self.pid = pid
            if mode == "denied": raise psutil.AccessDenied(pid)
        def create_time(self): return 9.25 if mode == "reused" else (1.25 if self.pid == 71 else 1.5)
        def is_running(self): return True
        def status(self): return psutil.STATUS_RUNNING
    monkeypatch.setattr(psutil, "Process", Process)
    before = snapshot(session)
    if mode == "reused":
        assert observe(session)["resources_cleanup_verified"] is True
    else:
        with pytest.raises(ValueError, match="resource_"):
            observe(session)
    assert snapshot(session) == before


@pytest.mark.parametrize("which", ["pointer", "report", "resources"])
def test_binding_or_original_snapshot_drift_rejected(scene, monkeypatch, which):
    session, journal = scene
    register(journal, "ready")
    path = {"pointer":session.parent/"latest-session.json", "report":session/"report.json",
            "resources":session/"session-resources.json"}[which]
    def change(name, **kwargs):
        path.write_bytes(path.read_bytes() + b" ")
        return verified(name)
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", change)
    with pytest.raises(ValueError, match="resource_"):
        observe(session)


def test_missing_inventory_is_not_backfilled(scene):
    session, _ = scene
    (session / "session-resources.json").unlink()
    before = snapshot(session)
    with pytest.raises((OSError, ValueError)):
        observe(session)
    assert snapshot(session) == before


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), 11])
def test_invalid_budget_is_not_silently_changed(scene, timeout):
    from app.execution import session_resource_recovery as recovery
    session, _ = scene
    before = snapshot(session)
    with pytest.raises(ValueError, match="resource_"):
        recovery.observe_session_resource_cleanup(session, timeout_seconds=timeout)
    assert snapshot(session) == before
