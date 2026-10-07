import hashlib
import json

import pytest

from app.execution import session_resources as resources


RID = "a" * 32
POLICY = {"kill_on_job_close": True, "breakaway_ok": False, "silent_breakaway_ok": False, "owner_handle_authority": "registry_parent"}


def journal(tmp_path):
    root = tmp_path / "session-test"
    root.mkdir()
    return resources.SessionResourceJournal(root, recognition_source="uia", host_identity={"pid": 12, "created": 1.5}, runner_identity={"pid": 13, "create_time_ns": 1500000001})


def registered(j):
    j.register_model(RID, scope_name="Local\\AgentGuiNativeModel-" + hashlib.sha256(RID.encode()).hexdigest(), pid_file=j.session_dir / "runtime-output" / "model-services" / RID / "model-server-pids" / "model.pid")


def launched(j):
    registered(j)
    j.begin_model_scope(RID)
    j.model_scope_acquired(RID, POLICY)
    j.begin_model_launch(RID)
    j.model_process_created(RID, {"pid": 14, "create_time_ns": 1500000002})
    j.model_ready(RID, ownership="owned", member_identities=[{"pid": 15, "create_time_ns": 1500000003}])


def test_owned_lifecycle_retains_identity_and_request(tmp_path):
    j = journal(tmp_path)
    launched(j)
    j.mark_ready()
    j.model_request_started(RID, "request-1")
    before = j.path.read_bytes()
    with pytest.raises(ValueError):
        j.model_request_finished(RID, "wrong")
    assert j.path.read_bytes() == before
    j.model_request_finished(RID, "request-1")
    j.model_closed(RID)
    closed = j.path.read_bytes()
    j.model_closed(RID)
    assert j.path.read_bytes() == closed
    state = resources.read_session_resources(j.session_dir)
    assert state["phase"] == "ready"
    assert len(state["resources"][RID]["member_identities"]) == 2
    with pytest.raises(ValueError):
        j.model_ready(RID, ownership="external", member_identities=[])


def test_write_failure_does_not_advance_memory(tmp_path, monkeypatch):
    j = journal(tmp_path)
    registered(j)
    before = j.path.read_bytes()
    writer = resources.write_json_snapshot
    monkeypatch.setattr(resources, "write_json_snapshot", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        j.begin_model_scope(RID)
    assert j.path.read_bytes() == before
    monkeypatch.setattr(resources, "write_json_snapshot", writer)
    j.begin_model_scope(RID)
    assert resources.read_session_resources(j.session_dir)["resources"][RID]["phase"] == "scope_starting"


def test_registration_and_strict_reader(tmp_path):
    j = journal(tmp_path)
    registered(j)
    before = j.path.read_bytes()
    with pytest.raises(ValueError):
        registered(j)
    assert j.path.read_bytes() == before
    state = json.loads(before)
    state["resources"][RID]["pid_file"] = "../outside.pid"
    j.path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError):
        resources.read_session_resources(j.session_dir)


@pytest.mark.parametrize("mutation", ["epoch", "scope", "identity", "policy", "phase", "extra"])
def test_reader_rejects_corrupt_contract(tmp_path, mutation):
    j = journal(tmp_path)
    launched(j)
    state = json.loads(j.path.read_bytes())
    model = state["resources"][RID]
    if mutation == "epoch": state["session_name"] = "different"
    if mutation == "scope": model["scope_name"] += "x"
    if mutation == "identity": model["member_identities"][0]["pid"] = True
    if mutation == "policy": model["policy"]["breakaway_ok"] = True
    if mutation == "phase": model["phase"] = "unknown"
    if mutation == "extra": state["secret"] = "unallowed"
    j.path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError): resources.read_session_resources(j.session_dir)


def test_external_and_closed_request_guard(tmp_path):
    j = journal(tmp_path)
    registered(j)
    j.model_ready(RID, ownership="external", member_identities=[{"pid": 99, "create_time_ns": 1000000000}])
    j.model_request_started(RID, "request")
    with pytest.raises(ValueError): j.model_request_started(RID, "other")
    with pytest.raises(ValueError): j.model_closed(RID)
    j.model_request_finished(RID, "request")
    j.model_closed(RID)
    with pytest.raises(ValueError): j.model_request_started(RID, "again")


def test_ready_union_and_owned_cannot_downgrade(tmp_path):
    j = journal(tmp_path)
    launched(j)
    j.model_ready(RID, ownership="owned", member_identities=[])
    j.model_ready(RID, ownership="owned", member_identities=[{"pid": 15, "create_time_ns": 1500000003}, {"pid": 15, "create_time_ns": 1500000004}])
    before = j.path.read_bytes()
    assert len(resources.read_session_resources(j.session_dir)["resources"][RID]["member_identities"]) == 3
    with pytest.raises(ValueError): j.model_ready(RID, ownership="external", member_identities=[])
    assert j.path.read_bytes() == before


def test_registration_failure_and_epoch_reopen(tmp_path, monkeypatch):
    j = journal(tmp_path)
    before = j.path.read_bytes()
    writer = resources.write_json_snapshot
    monkeypatch.setattr(resources, "write_json_snapshot", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError): registered(j)
    assert j.path.read_bytes() == before
    monkeypatch.setattr(resources, "write_json_snapshot", writer)
    registered(j)
    with pytest.raises(ValueError): resources.SessionResourceJournal(j.session_dir, recognition_source="other", host_identity={"pid": 22, "created": 2.5}, runner_identity={"pid": 23, "create_time_ns": 2500000000})


def test_invalid_path_scope_and_out_of_order_do_not_write(tmp_path):
    j = journal(tmp_path)
    before = j.path.read_bytes()
    with pytest.raises(ValueError): j.register_model(RID, scope_name="wrong", pid_file=j.session_dir / "outside.pid")
    assert j.path.read_bytes() == before
    registered(j)
    before = j.path.read_bytes()
    with pytest.raises(ValueError): j.begin_model_launch(RID)
    assert j.path.read_bytes() == before


@pytest.mark.parametrize("phase", ["registered", "scope_starting", "scope_acquired", "launch_starting", "launch_registered", "ready"])
def test_early_close_preserves_incomplete_launch_facts(tmp_path, phase):
    j = journal(tmp_path)
    registered(j)
    stages = [("scope_starting", lambda: j.begin_model_scope(RID)), ("scope_acquired", lambda: j.model_scope_acquired(RID, POLICY)), ("launch_starting", lambda: j.begin_model_launch(RID)), ("launch_registered", lambda: j.model_process_created(RID, {"pid": 14, "create_time_ns": 1500000002})), ("ready", lambda: j.model_ready(RID, ownership="owned", member_identities=[]))]
    if phase != "registered":
        for target, operation in stages:
            operation()
            if target == phase: break
    old = resources.read_session_resources(j.session_dir)["resources"][RID]
    j.model_closed(RID)
    closed = resources.read_session_resources(j.session_dir)["resources"][RID]
    assert closed["closed_from_phase"] == phase
    assert closed["ownership"] == old["ownership"] and closed["member_identities"] == old["member_identities"]
    before = j.path.read_bytes()
    j.model_closed(RID)
    assert j.path.read_bytes() == before
    with pytest.raises(ValueError): j.begin_model_scope(RID)
    closed["closed_from_phase"] = "ready"
    if phase in {"registered", "scope_starting", "scope_acquired", "launch_starting"}:
        state = resources.read_session_resources(j.session_dir)
        state["resources"][RID] = closed
        j.path.write_text(json.dumps(state), encoding="utf-8")
        with pytest.raises(ValueError): resources.read_session_resources(j.session_dir)


def test_cleanup_members_separate_union_and_failed_write(tmp_path, monkeypatch):
    j = journal(tmp_path)
    launched(j)
    original = resources.read_session_resources(j.session_dir)["resources"][RID]["member_identities"]
    member = {"pid": 20, "create_time_ns": 1500000005}
    before = j.path.read_bytes()
    writer = resources.write_json_snapshot
    monkeypatch.setattr(resources, "write_json_snapshot", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError): j.model_cleanup_members_observed(RID, [member])
    assert j.path.read_bytes() == before
    monkeypatch.setattr(resources, "write_json_snapshot", writer)
    j.model_cleanup_members_observed(RID, [member, member, {**member, "create_time_ns": 1500000006}])
    saved = resources.read_session_resources(j.session_dir)["resources"][RID]
    assert saved["member_identities"] == original and len(saved["cleanup_member_identities"]) == 2
    j.model_closed(RID)
    with pytest.raises(ValueError): j.model_cleanup_members_observed(RID, [member])


@pytest.mark.parametrize("request_id", [None, True, False, "", " "])
def test_invalid_request_id_not_silently_ignored(tmp_path, request_id):
    j = journal(tmp_path)
    launched(j)
    before = j.path.read_bytes()
    with pytest.raises(ValueError): j.model_request_started(RID, request_id)
    assert j.path.read_bytes() == before


def test_external_requires_identity_and_rejects_cleanup_members(tmp_path):
    j = journal(tmp_path)
    registered(j)
    with pytest.raises(ValueError): j.model_ready(RID, ownership="external", member_identities=[])
    j.model_ready(RID, ownership="external", member_identities=[{"pid": 99, "create_time_ns": 1000000000}])
    with pytest.raises(ValueError): j.model_cleanup_members_observed(RID, [])
