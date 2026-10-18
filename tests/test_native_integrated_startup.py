import json
import os
from pathlib import Path
import subprocess
import sys
import time


def test_real_native_host_runtime_import_and_reopen_share_one_isolated_interpreter(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
                       PYTHONFAULTHANDLER="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                       AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:", CUDA_VISIBLE_DEVICES="")
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    data = tmp_path / "原生集成验收"
    command = [sys.executable, str(root / "scripts/smoke_native_integrated_startup.py"), "--data-root", str(data)]
    result = subprocess.run(command, cwd=tmp_path, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=90)
    evidence = os.environ.get("R6B9_SMOKE_EVIDENCE")
    if evidence:
        destination = Path(evidence)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "native-startup-process.json").write_text(json.dumps({
            "command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    snapshot = data / "native-startup.png"
    assert snapshot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    if evidence:
        (destination / "native-startup.png").write_bytes(snapshot.read_bytes())
    assert report["contract_version"] == "native_integrated_startup_smoke_v1"
    assert report["native_ready"] is True
    assert report["runtime_backend_import_verified"] is True
    assert report["owner_thread_isolated"] is True
    assert report["owner_thread_stopped"] is True
    assert report["cleanup_verified"] is True
    assert report["same_path_reopen_verified"] is True
    assert report["runtime_execution_verified"] is False
    assert report["real_agent_verified"] is False
    assert report["artifact_is_authorization"] is False
    assert report["data_root"] == str(data.resolve())
    assert all(item["inside_interpreter"] for item in report["package_origins"])
    assert "private" not in report


def test_standalone_supervisor_rejects_incomplete_proof_even_when_child_exits_zero():
    from scripts.smoke_native_integrated_startup import supervise
    false_proof = {"contract_version": "native_integrated_startup_smoke_v1", "native_ready": True,
                   "runtime_backend_import_verified": True, "owner_thread_isolated": True,
                   "owner_thread_stopped": False, "cleanup_verified": True, "same_path_reopen_verified": True,
                   "runtime_execution_verified": False, "real_agent_verified": False, "artifact_is_authorization": False,
                   "package_origins": [{"module": "PySide6", "inside_interpreter": True}]}
    code, report = supervise([sys.executable, "-c", "print(" + repr(json.dumps(false_proof)) + ")"], timeout=5)
    assert code == 2
    assert report["worker_returncode"] == 0
    assert report["owner_thread_stopped"] is False


def test_supervisor_bounds_a_stuck_child_without_claiming_verified_cleanup():
    from scripts.smoke_native_integrated_startup import supervise
    started = time.monotonic()
    code, report = supervise([sys.executable, "-c", "import time;time.sleep(60)"], timeout=.25)
    assert code == 2 and report["worker_timed_out"] is True
    assert report["cleanup_verified"] is False
    assert report["worker_reaped"] is True
    assert time.monotonic() - started < 8


def test_startup_timeout_drains_real_qt_job_and_closes_host_before_returning(tmp_path):
    root = Path(__file__).resolve().parents[1]
    data = tmp_path / "timeout-drain"
    source = f"""import sys,json,time
sys.path.insert(0, {str(root)!r})
from pathlib import Path
from app.desktop_review.host import DesktopReviewHost
from scripts.smoke_native_integrated_startup import run_worker
original = DesktopReviewHost.start
def delayed(self, *args, **kwargs):
    time.sleep(.2)
    return original(self, *args, **kwargs)
DesktopReviewHost.start = delayed
code, report = run_worker(Path({str(data)!r}), startup_timeout=.01)
print(json.dumps({{'code': code, 'report': report}}, ensure_ascii=False))
"""
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
                       AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:")
    result = subprocess.run([sys.executable, "-c", source], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["code"] == 2
    assert outcome["report"]["failure_type"] == "TimeoutError"
    assert outcome["report"]["cleanup_verified"] is True
    assert outcome["report"]["owner_thread_stopped"] is True
    assert "QThread: Destroyed" not in result.stderr


def test_supervisor_preserves_non_utf8_diagnostics_without_lossy_replacement():
    import base64
    from scripts.smoke_native_integrated_startup import supervise

    code, report = supervise([sys.executable, "-c",
                              "import sys;sys.stdout.buffer.write(b'{}');sys.stderr.buffer.write(b'\\xff\\xfe')"], timeout=5)
    assert code == 2
    assert base64.b64decode(report["worker_stderr_base64"]) == b"\xff\xfe"
    assert report["worker_stderr_decode_error"]["encoding"] == "utf-8"
    assert "worker_stderr_utf8" not in report
    assert report["cleanup_verified"] is False


def test_closing_timeout_waits_for_same_real_shutdown_and_owner_join(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = f"""import sys,json,time
sys.path.insert(0, {str(root)!r})
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
import scripts.smoke_native_integrated_startup as smoke
closing = Event()
clock = time.monotonic
smoke.time = SimpleNamespace(monotonic=lambda: clock() + (100 if closing.is_set() else 0))
original = NativeSingleStepCoordinator.shutdown
def delayed(self, *args, **kwargs):
    closing.set()
    time.sleep(.2)
    return original(self, *args, **kwargs)
NativeSingleStepCoordinator.shutdown = delayed
code, report = smoke.run_worker(Path({str(tmp_path / 'closing-drain')!r}))
print(json.dumps({{'code': code, 'report': report}}, ensure_ascii=False))
"""
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
                       AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:")
    result = subprocess.run([sys.executable, "-c", source], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["code"] == 2
    report = outcome["report"]
    assert report["failure_type"] == "TimeoutError" and report["failure_phase"] == "closing"
    assert report["runtime_backend_import_verified"] is True
    assert report["cleanup_verified"] is True and report["owner_thread_stopped"] is True
    assert report["same_path_reopen_verified"] is False
    assert "QThread: Destroyed" not in result.stderr
