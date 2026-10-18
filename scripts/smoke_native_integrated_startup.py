"""以真实组件验证独立环境的原生启动、Runtime 导入和关闭；不运行 GUI 动作。"""

from __future__ import annotations

import argparse
import base64
import importlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import get_ident
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REQUIRED_MODULES = {"PySide6", "pywinauto", "comtypes", "mss", "mcp", "PIL", "loguru"}


def complete_proof(report: dict) -> bool:
    origins = report.get("package_origins")
    return (
        report.get("contract_version") == "native_integrated_startup_smoke_v1"
        and "failure_type" not in report
        and all(report.get(key) is True for key in (
            "native_ready", "runtime_backend_import_verified", "owner_thread_isolated",
            "owner_thread_stopped", "cleanup_verified", "same_path_reopen_verified",
        ))
        and all(report.get(key) is False for key in (
            "runtime_execution_verified", "real_agent_verified", "artifact_is_authorization",
        ))
        and isinstance(origins, list) and len(origins) == len(REQUIRED_MODULES)
        and all(isinstance(item, dict) and isinstance(item.get("module"), str)
                and item.get("inside_interpreter") is True for item in origins)
        and {item["module"] for item in origins} == REQUIRED_MODULES
    )


def supervise(command: list[str], *, timeout: float) -> tuple[int, dict]:
    """只约束本次创建的诊断子进程；强制终止不等于应用清理已验证。"""
    report = {"cleanup_verified": False, "runtime_execution_verified": False,
              "real_agent_verified": False, "artifact_is_authorization": False}
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as error:
        return 2, dict(report, failure_type=type(error).__name__, worker_started=False)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.output or b"", error.stderr or b""
            process.stdout.close()
            process.stderr.close()
    captures = {}
    for label, raw in (("stdout", stdout), ("stderr", stderr)):
        captures[f"worker_{label}_base64"] = base64.b64encode(raw).decode("ascii")
        try:
            captures[f"worker_{label}_utf8"] = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            captures[f"worker_{label}_decode_error"] = {"encoding": "utf-8", "start": error.start}
    if not timed_out:
        try:
            parsed = json.loads(captures.get("worker_stdout_utf8", ""))
            if not isinstance(parsed, dict):
                raise ValueError("worker report must be an object")
            report.update(parsed)
        except (ValueError, TypeError) as error:
            report["failure_type"] = type(error).__name__
    else:
        report["failure_type"] = "TimeoutError"
    report.update(captures)
    report.update(worker_started=True, worker_pid=process.pid, worker_returncode=process.poll(),
                  worker_timed_out=timed_out, worker_reaped=process.returncode is not None)
    success = (not timed_out and process.returncode == 0 and complete_proof(report)
               and not any(key.endswith("_decode_error") for key in captures))
    return (0 if success else 2), report


def run_worker(data_root: Path, *, startup_timeout: float = 35.0) -> tuple[int, dict]:
    """内部软期限只触发排空；阻塞导入的硬期限由进程外 supervise 保证。"""
    data_root = data_root.resolve()
    if data_root.exists() and (not data_root.is_dir() or any(data_root.iterdir())):
        raise ValueError("--data-root must be a new or empty directory")
    os.environ.update(QT_QPA_PLATFORM="offscreen", AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="")
    from app.runtime_environment import inspect_environment

    environment = inspect_environment()
    if environment["status"] != "metadata_present_unverified":
        return 2, {"code": "integrated_dependencies_missing", "environment": environment,
                   "cleanup_verified": False, "artifact_is_authorization": False}
    data_root.mkdir(parents=True, exist_ok=True)
    os.chdir(data_root)

    from PySide6.QtCore import QTimer
    from app.desktop_review.host import DesktopReviewHost
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from app.desktop_review.window import ReviewMainWindow, ensure_application

    application = ensure_application()
    application.setQuitOnLastWindowClosed(False)
    host = DesktopReviewHost(data_root / "inbox.json", data_root / "review", secrets.token_urlsafe(32), port=0)
    coordinator = NativeSingleStepCoordinator(data_root / "review", host.facade, host)
    window = ReviewMainWindow(host.facade, connections=host.connections, startup=host.start,
                              shutdown=coordinator.shutdown, single_step=coordinator)
    report = {
        "contract_version": "native_integrated_startup_smoke_v1", "interpreter": sys.executable,
        "data_root": str(data_root), "native_ready": False, "runtime_backend_import_verified": False,
        "owner_thread_isolated": False, "owner_thread_stopped": False, "cleanup_verified": False,
        "same_path_reopen_verified": False, "runtime_execution_verified": False,
        "real_agent_verified": False, "artifact_is_authorization": False, "package_origins": [],
    }
    deadline = time.monotonic() + startup_timeout
    phase = "starting"
    timer = QTimer()
    timer.setInterval(25)

    def import_runtime():
        importlib.import_module("app.api.agent_runtime")
        backend = importlib.import_module("app.core.window_manager")
        if backend.WINDOWS_BACKEND_AVAILABLE is not True:
            raise RuntimeError("Windows backend imports unavailable")
        prefix = Path(sys.prefix).resolve()
        origins = []
        for name in ("PySide6", "pywinauto", "comtypes", "mss", "mcp", "PIL", "loguru"):
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve()
            origins.append({"module": name, "path": str(path), "inside_interpreter": path.is_relative_to(prefix)})
        if not all(item["inside_interpreter"] for item in origins):
            raise RuntimeError("package loaded from a different environment")
        return origins

    def tick():
        nonlocal phase
        try:
            if phase in {"closing", "failure_closing"} and window._host_closed and not window._jobs:
                thread = coordinator._owner._thread
                report["owner_thread_stopped"] = thread is None or not thread.is_alive()
                report["cleanup_verified"] = (host.status()["phase"] == "stopped"
                                              and coordinator._shutdown is True
                                              and report["owner_thread_stopped"])
                timer.stop()
                application.exit(2 if "failure_type" in report else 0)
                return
            if phase == "failure_drain":
                if not window._jobs and window._operation in {"idle", "host_failed"}:
                    phase = "failure_closing"
                    window.close()
                return
            if phase == "failure_closing":
                # 清理失败不能循环重放关闭；硬期限会保留 cleanup 未验证的事实。
                return
            if time.monotonic() > deadline:
                raise TimeoutError("native startup or cleanup deadline exceeded")
            if phase == "starting" and host.status()["phase"] == "ready" and window._operation == "idle" and not window._jobs:
                report["native_ready"] = True
                report["package_origins"] = coordinator._owner.call(import_runtime)
                report["runtime_backend_import_verified"] = True
                report["owner_thread_isolated"] = coordinator._owner.thread_id != get_ident()
                import httpx

                response = httpx.get(host.status()["base_url"] + "/__native_startup_probe__", timeout=3,
                                     follow_redirects=False, trust_env=False)
                if response.status_code != 404:
                    raise RuntimeError("unexpected loopback listener response")
                report["loopback_probe_status"] = response.status_code
                snapshot = data_root / "native-startup.png"
                if not window.grab().save(str(snapshot)):
                    raise RuntimeError("native startup snapshot could not be saved")
                report["native_snapshot"] = str(snapshot)
                phase = "closing"
                window.close()
            elif window._operation == "host_failed" and not window._jobs:
                raise RuntimeError("native host lifecycle failed")
        except Exception as error:
            report.setdefault("failure_type", type(error).__name__)
            report.setdefault("failure_phase", phase)
            phase = "failure_closing" if phase == "closing" else "failure_drain"

    window.show()
    timer.timeout.connect(tick)
    timer.start()
    exit_code = application.exec()
    if exit_code == 0 and report["cleanup_verified"]:
        reopened = None
        try:
            reopened = DesktopReviewHost(data_root / "inbox.json", data_root / "review", secrets.token_urlsafe(32), port=0)
            report["cleanup_verified"] = False
            report["same_path_reopen_verified"] = reopened.start()["phase"] == "ready"
        except Exception as error:
            report["failure_type"] = type(error).__name__
        finally:
            if reopened is not None:
                try:
                    reopened.close()
                    report["cleanup_verified"] = reopened.status()["phase"] == "stopped"
                except Exception as error:
                    report["failure_type"] = type(error).__name__
    window.hide()
    return (0 if exit_code == 0 and complete_proof(report) else 2), report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded offscreen native startup smoke without external GUI actions.")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.worker:
        try:
            code, report = run_worker(arguments.data_root)
        except Exception as error:
            code, report = 2, {"failure_type": type(error).__name__, "cleanup_verified": False,
                               "artifact_is_authorization": False}
    else:
        code, report = supervise([sys.executable, str(Path(__file__).resolve()), "--worker",
                                  "--data-root", str(arguments.data_root.resolve())], timeout=65)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
