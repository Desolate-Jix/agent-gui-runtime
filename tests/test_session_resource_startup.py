"""原 runner 在资源清单前绑定真实 epoch，拒绝身份与配置漂移。"""
from pathlib import Path
from types import SimpleNamespace
import pytest
import psutil
from app.core.json_snapshot import write_json_snapshot
from scripts import run_local_step_session as startup

@pytest.fixture
def native_scene(tmp_path, monkeypatch):
    session = tmp_path / "验收根目录" / ("session-" + "a" * 32)
    session.mkdir(parents=True)
    entry = str(Path(startup.__file__).resolve())
    facts = {800: (200.125, 700), 700: (190.125, 600)}
    class Process:
        def __init__(self, pid):
            if pid not in facts:
                raise psutil.NoSuchProcess(pid)
            self.pid = pid
        def create_time(self):
            return facts[self.pid][0]
        def ppid(self):
            return facts[self.pid][1]
        def is_running(self):
            return True
        def status(self):
            return psutil.STATUS_RUNNING
        def cmdline(self):
            return ["python.exe", entry, "--output", str(session)]
    monkeypatch.setattr(startup.os, "getpid", lambda: 800)
    monkeypatch.setattr(psutil, "Process", Process)
    pointer = {"name":session.name,"host_identity":{"pid":700,"created":190.125},
               "recognition_source":"agent_current","delegate_profile":None,"api_profile":None}
    write_json_snapshot(session.parent/"latest-session.json",pointer)
    return session,pointer,facts

def initialise(session, source="agent_current", parent_pid=600):
    operation=getattr(startup,"initialize_session_resources",None)
    assert callable(operation), "maintained runner resource initialization is missing"
    return operation(session,source,parent_pid=parent_pid,timeout_seconds=0)

def test_initial_inventory_pins_original_launcher_and_actual_runner(native_scene):
    session,pointer,_=native_scene
    journal=initialise(session)
    from app.execution.session_resources import read_session_resources
    snapshot=read_session_resources(session)
    assert snapshot["host_identity"]==pointer["host_identity"]
    assert snapshot["runner_identity"]=={"pid":800,"create_time_ns":200125000000}
    assert snapshot["recognition_source"]=="agent_current"
    assert snapshot["phase"]=="initializing" and snapshot["resources"]=={}
    journal.mark_ready()
    assert read_session_resources(session)["phase"]=="ready"

@pytest.mark.parametrize("drift", ["pointer", "source", "launcher_created", "runner_parent", "entry", "output", "owner_parent"])
def test_invalid_original_attachment_writes_no_inventory(native_scene, monkeypatch, drift):
    session,pointer,facts=native_scene
    parent_pid=600
    if drift=="pointer":
        pointer["name"]="session-"+"b"*32
    elif drift=="source":
        pointer["recognition_source"]="local"
    elif drift=="launcher_created":
        pointer["host_identity"]["created"]+=1
    elif drift=="runner_parent":
        facts[800]=(200.125,600)
    elif drift=="owner_parent":
        parent_pid=601
    elif drift in {"entry","output"}:
        original=psutil.Process
        class Changed(original):
            def cmdline(self):
                return ["python.exe",str(Path("other.py").resolve()) if drift=="entry" else str(Path(startup.__file__).resolve()),
                        "--output", str(session.parent/"other") if drift=="output" else str(session)]
        monkeypatch.setattr(psutil,"Process",Changed)
    write_json_snapshot(session.parent/"latest-session.json",pointer)
    with pytest.raises(ValueError,match="resource_"):
        initialise(session,parent_pid=parent_pid)
    assert not (session/"session-resources.json").exists()

def test_unverifiable_launcher_is_not_inactive_or_registered(native_scene, monkeypatch):
    session,_,_=native_scene
    original=psutil.Process
    def denied(pid):
        if pid==700:
            raise psutil.AccessDenied(pid)
        return original(pid)
    monkeypatch.setattr(psutil,"Process",denied)
    with pytest.raises(ValueError,match="resource_"):
        initialise(session)
    assert not (session/"session-resources.json").exists()

def test_managed_start_requires_pointer_without_backfilling_it(native_scene):
    session,_,_=native_scene
    pointer=session.parent/"latest-session.json"
    pointer.unlink()
    with pytest.raises(ValueError,match="resource_"):
        initialise(session)
    assert not pointer.exists()
    assert not (session/"session-resources.json").exists()

def test_unmanaged_original_cli_uses_own_runner_identity(native_scene):
    session,_,_=native_scene
    (session.parent/"latest-session.json").unlink()
    journal=initialise(session,parent_pid=None)
    from app.execution.session_resources import read_session_resources
    snapshot=read_session_resources(session)
    assert snapshot["host_identity"]=={"pid":800,"created":200.125}
    assert snapshot["runner_identity"]["pid"]==800
    assert snapshot["resources"]=={} and snapshot["phase"]=="initializing"

