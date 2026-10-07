"""两个安装根连接仍核对真实进程、入口、会话与同库关系。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.learning_memory.execution_installation import build_execution_installation_descriptor
from app.learning_memory.workflow_run_client import WorkflowRunClient
from test_workflow_run_client import _live


def _execution(tmp_path):
    root = tmp_path / "separate-execution"
    entry = root / "scripts/run_local_step_session.py"
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b"fixture")
    descriptor = build_execution_installation_descriptor(root, version="0.1.0-test.8",
        files=["scripts/run_local_step_session.py"])
    (root / "execution-installation.json").write_text(json.dumps(descriptor), encoding="utf-8")
    return root, entry


@pytest.mark.parametrize("variant", ["valid", "wrong_entry", "wrong_session", "duplicate_output", "same_pid_wrong_entry", "wrong_parent", "stale", "upgrade", "different_library", "entry_as_argument", "trailing_output"])
def test_explicit_installation_keeps_live_identity_and_library_contract(tmp_path, monkeypatch, variant):
    import app.learning_memory.workflow_run_client as module
    session, library, pointer, report = _live(tmp_path)
    root, entry = _execution(tmp_path)
    owner = pointer["host_identity"]
    pid = owner["pid"] if variant == "same_pid_wrong_entry" else 2147483000
    report["runner_pid"] = pid
    (session / "report.json").write_text(json.dumps(report), encoding="utf-8")
    command = ["python.exe", str(entry), "--output", str(session)]
    if variant in {"wrong_entry", "same_pid_wrong_entry"}:
        command[1] = str(Path(__file__).resolve().parents[1] / "scripts/run_local_step_session.py")
    elif variant == "wrong_session":
        command[-1] = str(session.parent / "other")
    elif variant == "duplicate_output":
        command += ["--output", str(session)]
    elif variant == "entry_as_argument":
        command.insert(1, str(root / "untrusted.py"))
    elif variant == "trailing_output":
        command.append("--output")
    elif variant == "different_library":
        library = tmp_path / "other-library"
        library.mkdir()
    runner = SimpleNamespace(pid=pid, is_running=lambda: True, status=lambda: "running",
        create_time=lambda: owner["created"] + (1 if pid != owner["pid"] else 0),
        ppid=lambda: owner["pid"] + (1 if variant == "wrong_parent" else 0), cmdline=lambda: command)
    actual = module.psutil
    proxy = SimpleNamespace(**{name: getattr(actual, name) for name in dir(actual)})
    proxy.Process = lambda value=None: runner if value == pid else actual.Process(value)
    monkeypatch.setattr(module, "psutil", proxy)
    client = WorkflowRunClient(session, library, execution_root=root)
    if variant in {"valid", "upgrade", "stale"}:
        assert client.connect()["host_alive"] is True
        assert client._instant.root == root.resolve()
        if variant == "upgrade":
            entry.write_bytes(b"changed")
            with pytest.raises(ValueError, match="execution_installation_"):
                client.control({"action": "status", "run_id": "run-one"}, "after-upgrade")
        elif variant == "stale":
            runner.create_time = lambda: owner["created"] + 2
            with pytest.raises(ValueError, match="workflow_run_runner_identity_changed"):
                client.control({"action": "status", "run_id": "run-one"}, "after-stale")
    else:
        with pytest.raises(ValueError):
            client.connect()
    client.close()
    assert not list((session / "commands").glob("*.json"))
    assert not (session.parent / "owner.lock").exists()
    assert not (session / "closing.json").exists()


def test_session_report_cannot_choose_an_execution_root(tmp_path):
    session, library, _, report = _live(tmp_path)
    report["execution_root"] = str(tmp_path / "untrusted")
    (session / "report.json").write_text(json.dumps(report), encoding="utf-8")
    client = WorkflowRunClient(session, library)
    client.connect()
    assert client._instant.root == Path(__file__).resolve().parents[1]
