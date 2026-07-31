from __future__ import annotations

import argparse
import json
import os
import shutil
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
LOG_PATH = REPO_ROOT / "logs" / "test-panel-runtime.log"
PANEL_PORTS = (8000, 8765)
HEALTH_TIMEOUT_SECONDS = 1.5
STARTUP_TIMEOUT_SECONDS = 30.0

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


def start_runtime(port: int) -> subprocess.Popen[bytes]:
    uv_path = shutil.which("uv")
    if not uv_path:
        raise RuntimeError("uv is not available on PATH")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_handle = LOG_PATH.open("ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.Popen(
            [
                uv_path,
                "run",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    finally:
        log_handle.close()


def wait_for_runtime(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        probe = probe_port(port)
        if probe.status == "agent_runtime":
            return
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(
                f"FastAPI runtime exited with code {return_code}. "
                f"Check {LOG_PATH}.\n{_read_log_tail()}"
            )
        time.sleep(0.5)
    raise RuntimeError(
        f"FastAPI runtime did not become ready on port {port} within "
        f"{STARTUP_TIMEOUT_SECONDS:.0f} seconds. Check {LOG_PATH}.\n{_read_log_tail()}"
    )


def launch_panel(*, open_browser: bool = True) -> str:
    probes = [probe_port(port) for port in PANEL_PORTS]
    selection = choose_runtime_port(probes)
    if selection.should_start:
        print(f"Starting agent-gui-runtime on port {selection.port}...")
        process = start_runtime(selection.port)
        wait_for_runtime(process, selection.port)
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


def _read_log_tail(max_lines: int = 30) -> str:
    if not LOG_PATH.exists():
        return "Runtime log was not created."
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start or reuse the local test panel.")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        panel_url = launch_panel(open_browser=not args.no_browser)
    except RuntimeError as exc:
        print(f"Failed to start the test panel: {exc}", file=sys.stderr)
        return 1
    print(f"Test panel is ready: {panel_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
