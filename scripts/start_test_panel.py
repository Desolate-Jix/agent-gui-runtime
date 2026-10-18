from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO_ROOT))

from app.learn.workflow_paths import (
    LEARNING_WORKFLOW_STORE_PATH_ENV,
    resolve_learning_workflow_store_path,
)

LOG_PATH = REPO_ROOT / "logs" / "test-panel-runtime.log"
PANEL_PORTS = (8000, 8765)
HEALTH_TIMEOUT_SECONDS = 1.5
STARTUP_TIMEOUT_SECONDS = 30.0
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "development.json"
LAUNCHER_DEPENDENCIES = ("uvicorn", "fastapi", "pydantic", "loguru", "psutil")
SETUP_HINT = "In the repository root, explicitly run: uv sync --locked --group dev"

ProbeStatus = Literal["agent_runtime", "foreign_service", "free"]


@dataclass(frozen=True)
class PortProbe:
    port: int
    status: ProbeStatus
    detail: str


@dataclass(frozen=True)
class RuntimeSelection:
    port: int
    should_start: bool


@dataclass(frozen=True)
class LauncherConfig:
    ports: tuple[int, ...] = PANEL_PORTS
    log_path: Path = LOG_PATH
    startup_timeout_seconds: float = STARTUP_TIMEOUT_SECONDS
    learning_workflow_store_path: str | None = None


def load_launcher_config(path: Path = DEFAULT_CONFIG_PATH) -> LauncherConfig:
    try:
        path = path.resolve()
        with path.open("rb") as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            raise ValueError("file exceeds 64 KiB")
        payload = json.loads(raw.decode("utf-8-sig"))
        allowed = {"ports", "log_path", "startup_timeout_seconds", "learning_workflow_store_path"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValueError(f"expected an object containing only {', '.join(sorted(allowed))}")
        ports = payload.get("ports", list(PANEL_PORTS))
        if (not isinstance(ports, list) or not 1 <= len(ports) <= 16
                or any(type(port) is not int or not 1 <= port <= 65535 for port in ports)
                or len(set(ports)) != len(ports)):
            raise ValueError("ports must contain 1-16 unique integers in 1..65535")
        timeout = payload.get("startup_timeout_seconds", STARTUP_TIMEOUT_SECONDS)
        if type(timeout) not in (int, float) or not 0 < timeout <= 300:
            raise ValueError("startup_timeout_seconds must be a finite number in (0, 300]")
        log_value = payload.get("log_path")
        if log_value is None and "log_path" not in payload:
            log_path = LOG_PATH
        else:
            if not isinstance(log_value, str) or not log_value.strip() or "\x00" in log_value:
                raise ValueError("log_path must be a nonempty file path")
            log_path = (path.parent / log_value).resolve()
        if log_path.is_dir():
            raise ValueError("log_path points to a directory")
        state_path = None
        if "learning_workflow_store_path" in payload:
            value = payload["learning_workflow_store_path"]
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ValueError("learning_workflow_store_path must be a nonempty path or :memory:")
            state_path = ":memory:" if value.strip() == ":memory:" else str((path.parent / value.strip()).resolve())
        config = LauncherConfig(tuple(ports), log_path, float(timeout), state_path)
        build_runtime_environment(config)
        return config
    except (OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"Invalid launcher config {path}: {exc}") from exc


def build_runtime_environment(config: LauncherConfig) -> dict[str, str]:
    """只配置子进程；拒绝冲突，不能悄悄覆盖测试隔离或用户已选状态库。"""
    environment = dict(os.environ)
    inherited = environment.get(LEARNING_WORKFLOW_STORE_PATH_ENV, "").strip()
    selected = config.learning_workflow_store_path
    if selected is not None:
        if inherited:
            inherited_path = resolve_learning_workflow_store_path(environment=environment)
            selected_path = resolve_learning_workflow_store_path(environment={LEARNING_WORKFLOW_STORE_PATH_ENV: selected})
            if inherited_path != selected_path:
                raise RuntimeError(f"State path conflict: launcher config and {LEARNING_WORKFLOW_STORE_PATH_ENV} disagree")
        environment[LEARNING_WORKFLOW_STORE_PATH_ENV] = selected
    state_path = resolve_learning_workflow_store_path(environment=environment)
    if state_path is not None:
        if state_path.is_dir():
            raise RuntimeError("State path is a directory, expected a JSON file")
        if state_path == config.log_path.resolve():
            raise RuntimeError("State path must not be the runtime console log")
    if selected is not None or inherited:
        environment[LEARNING_WORKFLOW_STORE_PATH_ENV] = str(state_path) if state_path is not None else ":memory:"
    return environment


def check_launcher_environment(config: LauncherConfig) -> dict[str, object]:
    environment = build_runtime_environment(config)
    state_path = resolve_learning_workflow_store_path(environment=environment)
    state_source = "launcher_config" if config.learning_workflow_store_path is not None else (
        "environment" if os.environ.get(LEARNING_WORKFLOW_STORE_PATH_ENV, "").strip() else "default")
    missing = [name for name in LAUNCHER_DEPENDENCIES if importlib.util.find_spec(name) is None]
    python_supported = sys.version_info[:2] == (3, 11)
    return {
        "status": "metadata_present_runtime_not_run" if python_supported and not missing else "blocked",
        "python": sys.executable,
        "python_supported": python_supported,
        "required_python": ">=3.11,<3.12",
        "missing_dependencies": missing,
        "setup_hint": SETUP_HINT,
        "state_store": {"path": str(state_path) if state_path is not None else None,
                        "mode": "file" if state_path is not None else "memory", "source": state_source,
                        "contents": "not_read", "writability": "not_tested", "migration": "not_performed"},
        "config": {"host": "127.0.0.1", "ports": list(config.ports), "workers": 1,
                   "log_path": str(config.log_path), "startup_timeout_seconds": config.startup_timeout_seconds},
        "scope": "Launcher dependency metadata only; not full installation, import, model, or service readiness. Log writability is not tested.",
        "runtime": {key: "not_run" for key in ("service", "model", "ocr", "gpu", "gui", "network")},
    }


def is_agent_runtime_health(payload: object) -> bool:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return False
    data = payload.get("data")
    return isinstance(data, dict) and data.get("service") == "agent-gui-runtime"


def probe_port(port: int) -> PortProbe:
    health_url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(health_url, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if is_agent_runtime_health(payload):
            return PortProbe(port=port, status="agent_runtime", detail="healthy")
        return PortProbe(
            port=port,
            status="foreign_service",
            detail="health response belongs to another service",
        )
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        if _port_is_listening(port):
            return PortProbe(
                port=port,
                status="foreign_service",
                detail=f"port is occupied but runtime health validation failed: {exc}",
            )
        return PortProbe(port=port, status="free", detail=str(exc))


def choose_runtime_port(probes: list[PortProbe]) -> RuntimeSelection:
    for probe in probes:
        if probe.status == "agent_runtime":
            return RuntimeSelection(port=probe.port, should_start=False)
    for probe in probes:
        if probe.status == "free":
            return RuntimeSelection(port=probe.port, should_start=True)
    details = "; ".join(f"{probe.port}: {probe.detail}" for probe in probes)
    raise RuntimeError(f"No available panel port. {details}")


def start_runtime(port: int, *, config: LauncherConfig = LauncherConfig()) -> subprocess.Popen[bytes]:
    environment = build_runtime_environment(config)
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = config.log_path.open("ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
            ],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=environment,
        )
    finally:
        log_handle.close()


def _child_owns_listener(process: subprocess.Popen[bytes], port: int) -> bool:
    # 仅启动等待阶段查询本次子进程；离线检查不导入 psutil 或扫描进程。
    import psutil

    try:
        connections = psutil.Process(process.pid).net_connections(kind="tcp")
    except psutil.Error as exc:
        raise RuntimeError(f"Cannot verify child listener ownership for PID {process.pid}: {exc}") from exc
    return any(connection.status == psutil.CONN_LISTEN and connection.laddr
               and connection.laddr.ip == "127.0.0.1" and connection.laddr.port == port
               for connection in connections)


def _check_child_running(process: subprocess.Popen[bytes], config: LauncherConfig) -> None:
    return_code = process.poll()
    if return_code is not None:
        raise RuntimeError(
            f"FastAPI runtime exited with code {return_code}. "
            f"Check {config.log_path}.\n{_read_log_tail(path=config.log_path)}"
        )


def wait_for_runtime(process: subprocess.Popen[bytes], port: int, *, config: LauncherConfig = LauncherConfig()) -> None:
    deadline = time.monotonic() + config.startup_timeout_seconds
    while time.monotonic() < deadline:
        _check_child_running(process, config)
        if _child_owns_listener(process, port):
            probe = probe_port(port)
            _check_child_running(process, config)
            if probe.status == "agent_runtime" and _child_owns_listener(process, port):
                return
        time.sleep(0.5)
    raise RuntimeError(
        f"FastAPI runtime did not become ready on port {port} within "
        f"{config.startup_timeout_seconds:g} seconds. Check {config.log_path}.\n{_read_log_tail(path=config.log_path)}"
    )


def launch_panel(*, open_browser: bool = True, config: LauncherConfig = LauncherConfig()) -> str:
    environment = build_runtime_environment(config)
    probes = [probe_port(port) for port in config.ports]
    selection = choose_runtime_port(probes)
    if not selection.should_start and environment.get(LEARNING_WORKFLOW_STORE_PATH_ENV, "").strip():
        free_probes = [probe for probe in probes if probe.status == "free"]
        if not free_probes:
            raise RuntimeError("Cannot verify existing runtime state-store identity; use a free configured port or stop that runtime explicitly")
        selection = choose_runtime_port(free_probes)
    if selection.should_start:
        print(f"Starting agent-gui-runtime on port {selection.port}...")
        process = start_runtime(selection.port, config=config)
        wait_for_runtime(process, selection.port, config=config)
    else:
        print(f"Using existing agent-gui-runtime on port {selection.port}.")

    panel_url = f"http://127.0.0.1:{selection.port}/panel"
    if open_browser:
        print(f"Opening {panel_url}")
        webbrowser.open(panel_url)
    return panel_url


def _port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.3)
        return client.connect_ex(("127.0.0.1", port)) == 0


def _read_log_tail(max_lines: int = 30, *, path: Path = LOG_PATH) -> str:
    if not path.exists():
        return "Runtime log was not created."
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Start or reuse the local test panel.")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--check", action="store_true", help="Read launcher metadata only; do not start or probe anything.")
    parser.add_argument("--json", action="store_true", help="Machine-readable output for --check.")
    args = parser.parse_args(argv)
    if args.json and not args.check:
        parser.error("--json requires --check")
    try:
        config = load_launcher_config(args.config)
        report = check_launcher_environment(config)
        if args.check:
            if args.json:
                print(json.dumps(report, ensure_ascii=False))
            else:
                print(f"Launcher check: {report['status']}\n{report['scope']}")
                print(f"Python: {sys.executable}; required: {report['required_python']}")
                print(f"Missing dependencies: {report['missing_dependencies']}\n{SETUP_HINT}")
            return 0 if report["status"] == "metadata_present_runtime_not_run" else 1
        if report["status"] == "blocked":
            raise RuntimeError(f"Python 3.11 and launcher dependencies required; missing: {report['missing_dependencies']}. {SETUP_HINT}")
        panel_url = launch_panel(open_browser=not args.no_browser, config=config)
    except (RuntimeError, OSError) as exc:
        if args.check and args.json:
            print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
            return 1
        print(f"Failed to start the test panel: {exc}", file=sys.stderr)
        return 1
    print(f"Test panel is ready: {panel_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
