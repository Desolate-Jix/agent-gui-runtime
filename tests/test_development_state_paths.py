import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import start_test_panel as launcher


STATE_ENV = "AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv(STATE_ENV, raising=False)


def write_config(tmp_path, value):
    path = tmp_path / "development.json"
    path.write_text(json.dumps({"learning_workflow_store_path": value}), encoding="utf-8")
    return path


def test_configured_state_resolves_beside_config_and_only_changes_child_environment(tmp_path):
    config = launcher.load_launcher_config(write_config(tmp_path, "\u6570\u636e/runs.json"))
    before = dict(os.environ)
    environment = launcher.build_runtime_environment(config)
    assert environment[STATE_ENV] == str(tmp_path / "\u6570\u636e/runs.json")
    assert dict(os.environ) == before
    assert not (tmp_path / "\u6570\u636e").exists()
    report = launcher.check_launcher_environment(config)
    assert report["state_store"]["source"] == "launcher_config"
    assert report["state_store"]["path"] == environment[STATE_ENV]
    assert report["state_store"]["contents"] == "not_read"


def test_default_and_inherited_paths_match_runtime_resolution(tmp_path, monkeypatch):
    from app.learn.workflow_paths import resolve_learning_workflow_store_path
    config = launcher.LauncherConfig()
    report = launcher.check_launcher_environment(config)
    assert report["state_store"]["path"] == str(resolve_learning_workflow_store_path())
    assert report["state_store"]["source"] == "default"
    monkeypatch.setenv(STATE_ENV, "runtime_state/custom.json")
    environment = launcher.build_runtime_environment(config)
    assert environment[STATE_ENV] == str(resolve_learning_workflow_store_path())
    assert launcher.check_launcher_environment(config)["state_store"]["source"] == "environment"


def test_memory_mode_is_explicit_and_never_becomes_a_filename(tmp_path):
    config = launcher.load_launcher_config(write_config(tmp_path, ":memory:"))
    assert launcher.build_runtime_environment(config)[STATE_ENV] == ":memory:"
    report = launcher.check_launcher_environment(config)
    assert report["state_store"]["mode"] == "memory"
    assert report["state_store"]["path"] is None


def test_conflicting_environment_is_rejected_not_silently_overridden(tmp_path, monkeypatch):
    config = launcher.load_launcher_config(write_config(tmp_path, "runs.json"))
    monkeypatch.setenv(STATE_ENV, ":memory:")
    with pytest.raises(RuntimeError, match="conflict"):
        launcher.build_runtime_environment(config)
    monkeypatch.setenv(STATE_ENV, str(tmp_path / "runs.json"))
    assert launcher.build_runtime_environment(config)[STATE_ENV] == str(tmp_path / "runs.json")


@pytest.mark.parametrize("value", [None, "", "  ", True, 2, "bad\u0000path"])
def test_invalid_state_config_is_rejected(tmp_path, value):
    with pytest.raises(RuntimeError, match="config"):
        launcher.load_launcher_config(write_config(tmp_path, value))


def test_state_path_cannot_be_directory_or_console_log(tmp_path):
    with pytest.raises(RuntimeError, match="directory"):
        launcher.load_launcher_config(write_config(tmp_path, str(tmp_path)))
    config_path = tmp_path / "development.json"
    config_path.write_text(json.dumps({"log_path": "same.json", "learning_workflow_store_path": "same.json"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="log"):
        launcher.load_launcher_config(config_path)


def test_custom_state_runtime_is_not_silently_reused_without_identity(tmp_path, monkeypatch):
    config = launcher.load_launcher_config(write_config(tmp_path, "runs.json"))
    monkeypatch.setattr(launcher, "probe_port", lambda port: launcher.PortProbe(port, "agent_runtime", "healthy"))
    monkeypatch.setattr(launcher, "start_runtime", lambda *a, **k: pytest.fail("must not start"))
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *a: pytest.fail("must not open"))
    with pytest.raises(RuntimeError, match="state.*identity"):
        launcher.launch_panel(config=config)


def test_child_receives_configured_path_and_actual_store_resolver_agrees(tmp_path, monkeypatch):
    config = launcher.load_launcher_config(write_config(tmp_path, "\u72b6\u6001/runs.json"))
    calls = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda command, **kwargs: calls.append(kwargs))
    config = launcher.LauncherConfig(log_path=tmp_path / "console.log", learning_workflow_store_path=config.learning_workflow_store_path)
    launcher.start_runtime(9011, config=config)
    assert calls[0]["env"][STATE_ENV] == str(tmp_path / "\u72b6\u6001/runs.json")


def test_fresh_process_imports_real_store_only_in_memory_then_resolves_configured_path(tmp_path):
    config = launcher.load_launcher_config(write_config(tmp_path, "\u72b6\u6001/runs.json"))
    environment = launcher.build_runtime_environment(config)
    script = "import os, json, sys; target=os.environ['AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH']; os.environ['AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH']=':memory:'; from app.learn.workflow_store import resolve_learning_workflow_store_path, learning_workflow_run_store; os.environ['AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH']=target; print(json.dumps({'path':str(resolve_learning_workflow_store_path()),'memory':learning_workflow_run_store._state_path is None}))"
    result = subprocess.run([sys.executable, "-c", script], cwd=launcher.REPO_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"path": environment[STATE_ENV], "memory": True}
    assert not (tmp_path / "\u72b6\u6001").exists()


def test_fresh_process_writes_and_reloads_only_the_configured_temporary_store(tmp_path):
    config = launcher.load_launcher_config(write_config(tmp_path, "isolated/runs.json"))
    environment = launcher.build_runtime_environment(config)
    script = "from app.learn.workflow_store import learning_workflow_run_store as store, LearningWorkflowRunStore, resolve_learning_workflow_store_path; import json; store.transition(run_id='dev-path-test', expected_revision=0, stage='bind_capture', outcome='running', reason='offline path test'); store.close(); reloaded=LearningWorkflowRunStore(state_path=resolve_learning_workflow_store_path()); print(json.dumps(reloaded.get('dev-path-test'))); reloaded.close()"
    result = subprocess.run([sys.executable, "-c", script], cwd=launcher.REPO_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["revision"] == 1
    assert (tmp_path / "isolated/runs.json").is_file()


def test_inherited_custom_state_also_blocks_unverified_runtime_reuse(monkeypatch):
    monkeypatch.setenv(STATE_ENV, ":memory:")
    monkeypatch.setattr(launcher, "probe_port", lambda port: launcher.PortProbe(port, "agent_runtime", "healthy"))
    with pytest.raises(RuntimeError, match="state.*identity"):
        launcher.launch_panel(open_browser=False)


def test_pure_path_import_has_no_store_or_model_imports(tmp_path):
    environment = {**os.environ, STATE_ENV: str(tmp_path / "must-not-create/runs.json")}
    script = "import sys; from app.learn.workflow_paths import resolve_learning_workflow_store_path; resolve_learning_workflow_store_path(); assert not any(n in sys.modules for n in ['app.learn.workflow_store','app.main','torch','app.core.model_server'])"
    result = subprocess.run([sys.executable, "-c", script], cwd=launcher.REPO_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "must-not-create").exists()


def test_custom_state_skips_existing_runtime_and_uses_configured_free_port(monkeypatch):
    monkeypatch.setenv(STATE_ENV, ":memory:")
    config = launcher.LauncherConfig(ports=(9001, 9002))
    monkeypatch.setattr(launcher, "probe_port", lambda port: launcher.PortProbe(port, "agent_runtime" if port == 9001 else "free", "test"))
    calls = []
    monkeypatch.setattr(launcher, "start_runtime", lambda port, **kw: calls.append(port) or "child")
    monkeypatch.setattr(launcher, "wait_for_runtime", lambda *a, **kw: None)
    assert launcher.launch_panel(config=config, open_browser=False) == "http://127.0.0.1:9002/panel"
    assert calls == [9002]


def test_exited_child_cannot_be_replaced_by_another_healthy_runtime(monkeypatch):
    class Exited:
        def poll(self):
            return 98
    monkeypatch.setattr(launcher, "probe_port", lambda port: launcher.PortProbe(port, "agent_runtime", "another process"))
    monkeypatch.setattr(launcher, "_read_log_tail", lambda **kw: "fixture")
    with pytest.raises(RuntimeError, match="exited with code 98"):
        launcher.wait_for_runtime(Exited(), 9001)


def test_readiness_requires_child_owned_listener_on_both_sides_of_health(monkeypatch):
    class Child:
        pid = 123
        def poll(self):
            return None
    calls = []
    monkeypatch.setattr(launcher, "_child_owns_listener", lambda process, port: calls.append("owner") or True)
    monkeypatch.setattr(launcher, "probe_port", lambda port: calls.append("health") or launcher.PortProbe(port, "agent_runtime", "healthy"))
    launcher.wait_for_runtime(Child(), 9001)
    assert calls == ["owner", "health", "owner"]


def test_unowned_listener_is_not_accepted_as_child_ready(monkeypatch):
    class Child:
        pid = 123
        def poll(self):
            return None
    monkeypatch.setattr(launcher, "_child_owns_listener", lambda *a: False)
    monkeypatch.setattr(launcher, "probe_port", lambda port: pytest.fail("must not trust health before ownership"))
    ticks = iter([0, 1, 40])
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(launcher.time, "sleep", lambda *a: None)
    monkeypatch.setattr(launcher, "_read_log_tail", lambda **kw: "fixture")
    with pytest.raises(RuntimeError, match="did not become ready"):
        launcher.wait_for_runtime(Child(), 9001)


def test_listener_query_checks_exact_child_pid_address_and_port(monkeypatch):
    import psutil
    seen = []
    connections = []
    def process(pid):
        seen.append(pid)
        return SimpleNamespace(net_connections=lambda **kw: connections)
    monkeypatch.setattr(psutil, "Process", process)
    child = SimpleNamespace(pid=123)
    for ip, port, status, expected in [("127.0.0.1", 9001, "LISTEN", True), ("127.0.0.1", 9002, "LISTEN", False), ("0.0.0.0", 9001, "LISTEN", False), ("127.0.0.1", 9001, "ESTABLISHED", False)]:
        connections[:] = [SimpleNamespace(laddr=SimpleNamespace(ip=ip, port=port), status=status)]
        assert launcher._child_owns_listener(child, 9001) is expected
    assert seen == [123] * 4


def test_listener_query_permission_failure_is_explicit(monkeypatch):
    import psutil
    def denied(pid):
        raise psutil.AccessDenied(pid)
    monkeypatch.setattr(psutil, "Process", denied)
    with pytest.raises(RuntimeError, match="Cannot verify child listener ownership"):
        launcher._child_owns_listener(SimpleNamespace(pid=123), 9001)
