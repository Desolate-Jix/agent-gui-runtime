from __future__ import annotations

import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import time
from threading import Event, Thread

import pytest

from app.learn.recognition.uei.provider_adapters import ProviderRunBudget, RestrictedCaptureLease


def _config(tmp_path: Path):
    from app.learn.recognition.uei.omniparser_shadow_adapter import TrustedOmniParserConfiguration

    interpreter = tmp_path / "python.exe"
    worker = tmp_path / "worker.py"
    code = tmp_path / "code"
    weights = tmp_path / "weights"
    cache = tmp_path / "cache"
    for path in (interpreter, worker):
        path.write_text("fixed", encoding="utf-8")
    for path in (code, weights, cache):
        path.mkdir(exist_ok=True)
    return TrustedOmniParserConfiguration(
        interpreter=interpreter, worker_script=worker, code_path=code, weights_path=weights, cache_path=cache,
        minimum_free_gpu_gib=0,
    )


def _capture(tmp_path: Path) -> RestrictedCaptureLease:
    image = tmp_path / "capture.png"
    image.write_bytes(b"synthetic-private-image")
    ref = {"id": "ref/1", "content_sha256": "a" * 64}
    return RestrictedCaptureLease(
        request_ref=ref, capture_lineage_ref=ref, artifact_ref=ref, capture_id="capture/1",
        artifact_sha256=sha256(image.read_bytes()).hexdigest(), image_size={"width": 40, "height": 30}, local_path=image,
    )


def _budget() -> ProviderRunBudget:
    return ProviderRunBudget(timeout_ms=100, max_output_bytes=1024, max_element_count=3,
                             max_string_length=32, resource_group="gpu_vision")


class FakeProcess:
    pid = 123
    _uei_fake_process = True

    def __init__(self, *, payload: object, timeout: bool = False) -> None:
        self.payload = payload
        self.timeout = timeout
        self.returncode = None if timeout else 0
        self.killed = False

    def communicate(self, timeout: float):
        if self.timeout:
            raise subprocess.TimeoutExpired("fixed", timeout)
        return b"", b""

    def poll(self):
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float) -> int:
        return self.returncode


def _fake_popen(process: FakeProcess, calls: list[dict[str, object]]):
    def spawn(command, **kwargs):
        output_path = Path(command[command.index("--output-json") + 1])
        if not process.timeout:
            output_path.write_text(json.dumps(process.payload), encoding="utf-8")
        calls.append({"command": command, **kwargs, "output_path": output_path})
        return process
    return spawn


def test_fixed_worker_success_is_normalized_without_worker_identity_or_path(tmp_path: Path, monkeypatch):
    from app.learn.recognition.uei.omniparser_shadow_adapter import OmniParserShadowAdapter

    process = FakeProcess(payload={"items": [{"source_item_id": "item/1", "kind": "text", "safe_text": "Search",
                                                "safe_role": "text", "safe_states": ["interactable"],
                                                "source_bbox": [1, 2, 10, 20], "source_coordinate_space": "capture_pixel_xyxy",
                                                "provider_confidence": 0.8}], "duration_ms": 2, "resource_units": 1})
    calls: list[dict[str, object]] = []
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", _fake_popen(process, calls))
    output = OmniParserShadowAdapter(configuration=_config(tmp_path)).invoke(
        capture=_capture(tmp_path), budget=_budget(), invocation_id="invocation/1",
    )

    assert output.items[0].safe_text == "Search" and output.items[0].source_bbox == (1, 2, 10, 20)
    assert output.items[0].source_coordinate_space == "capture_pixel_xyxy"
    assert output.items[0].safe_role == "text"
    assert output.items[0].safe_states == ("interactable",)
    assert calls[0]["env"]["HF_HUB_OFFLINE"] == "1"
    assert "capture.png" not in repr(output)
    assert not calls[0]["output_path"].exists()


@pytest.mark.parametrize("payload", [
    {"items": [], "duration_ms": 1, "resource_units": 0, "capture_id": "forged"},
    {"items": [{"source_item_id": "item/1", "kind": "text", "safe_text": "Authorization: Bearer token",
                 "source_bbox": [1, 2, 10, 20], "source_coordinate_space": "image_pixel_xyxy", "provider_confidence": None}], "duration_ms": 1, "resource_units": 0},
    {"items": [{"source_item_id": "item/1", "kind": "text", "safe_text": "x" * 33,
                 "source_bbox": [1, 2, 10, 20], "source_coordinate_space": "image_pixel_xyxy", "provider_confidence": None}], "duration_ms": 1, "resource_units": 0},
])
def test_invalid_or_secret_worker_output_fails_closed_and_cleans_exchange(tmp_path: Path, monkeypatch, payload):
    from app.learn.recognition.uei.omniparser_shadow_adapter import OmniParserShadowAdapter, OmniParserShadowAdapterError

    process = FakeProcess(payload=payload)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", _fake_popen(process, calls))
    with pytest.raises(OmniParserShadowAdapterError):
        OmniParserShadowAdapter(configuration=_config(tmp_path)).invoke(
            capture=_capture(tmp_path), budget=_budget(), invocation_id="invocation/1",
        )
    assert process.killed is False and not calls[0]["output_path"].exists()


def test_timeout_terminates_worker_tree_and_releases_lease_without_orphan(tmp_path: Path, monkeypatch):
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        OmniParserShadowAdapterError,
        ProcessResourceLeaseManager,
    )

    process = FakeProcess(payload={}, timeout=True)
    calls: list[dict[str, object]] = []
    lease_root = tmp_path / "timeout-leases"
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", _fake_popen(process, calls))
    with pytest.raises(OmniParserShadowAdapterError, match="timeout") as captured:
        OmniParserShadowAdapter(
            configuration=_config(tmp_path),
            resource_lease_manager=ProcessResourceLeaseManager(root=lease_root),
        ).invoke(
            capture=_capture(tmp_path), budget=_budget(), invocation_id="invocation/1",
        )
    assert captured.value.cleanup_status == "clean"
    assert process.killed is True
    assert process.poll() is not None
    assert list(lease_root.glob("*.lock")) == []
    assert not calls[0]["output_path"].exists()


def test_resource_rejection_happens_before_spawn(tmp_path: Path, monkeypatch):
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        OmniParserShadowAdapterError,
    )

    calls: list[dict[str, object]] = []
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", lambda *a, **k: calls.append({}))
    with pytest.raises(OmniParserShadowAdapterError, match="resource"):
        OmniParserShadowAdapter(configuration=_config(tmp_path), resource_lease_manager=lambda group: None,
                               gpu_free_gib=lambda: 99).invoke(
            capture=_capture(tmp_path), budget=_budget(), invocation_id="invocation/1",
        )
    assert calls == []


def test_parent_gpu_preflight_rejects_before_spawn_and_default_cache_is_trusted(tmp_path: Path, monkeypatch):
    from dataclasses import replace
    from app.learn.recognition.uei.omniparser_shadow_adapter import OmniParserShadowAdapter, OmniParserShadowAdapterError

    calls: list[dict[str, object]] = []
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", lambda *a, **k: calls.append({}))
    with pytest.raises(OmniParserShadowAdapterError, match="resource"):
        OmniParserShadowAdapter(configuration=replace(_config(tmp_path), minimum_free_gpu_gib=8), gpu_free_gib=lambda: 4.3).invoke(
            capture=_capture(tmp_path), budget=_budget(), invocation_id="invocation/gpu",
        )
    assert calls == []


def test_device_zero_gpu_probe_parses_system_free_memory_and_fails_closed(monkeypatch):
    from types import SimpleNamespace
    from app.learn.recognition.uei.omniparser_shadow_adapter import _free_gpu_gib

    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="4180 MiB\n12000 MiB\n"))
    assert _free_gpu_gib() == pytest.approx(4180 / 1024)
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    assert _free_gpu_gib() == 0.0


def test_benchmark_mode_accepts_one_closed_cold_plus_three_warm_session(tmp_path: Path, monkeypatch):
    from app.learn.recognition.uei.omniparser_shadow_adapter import OmniParserShadowAdapter

    payload = {"items": [], "duration_ms": 10, "resource_units": 2,
               "benchmark": {"cold_ms": 10, "warm_ms": [3, 2, 2], "warm_p50_ms": 2,
                             "warm_p95_ms": 3, "item_counts": [1, 1, 1, 1],
                             "invalid_item_counts": [0, 0, 0, 0], "peak_mib": 2}}
    process, calls = FakeProcess(payload=payload), []
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", _fake_popen(process, calls))
    adapter = OmniParserShadowAdapter(configuration=_config(tmp_path), gpu_free_gib=lambda: 99, benchmark_mode=True)
    output = adapter.invoke(capture=_capture(tmp_path), budget=_budget(), invocation_id="invocation/benchmark")

    assert len(calls) == 1 and "--benchmark" in calls[0]["command"] and output.items == ()
    assert adapter.last_benchmark == payload["benchmark"]
    assert adapter.provider_version == "v2.0.1+benchmark-cold1-warm3"
    assert OmniParserShadowAdapter(configuration=_config(tmp_path)).provider_version == "v2.0.1"


@pytest.mark.parametrize("benchmark", [
    {},
    {"cold_ms": 1, "warm_ms": [1, 2], "warm_p50_ms": 1, "warm_p95_ms": 2,
     "item_counts": [0, 0, 0, 0], "invalid_item_counts": [0, 0, 0, 0], "peak_mib": 0},
    {"cold_ms": 1, "warm_ms": [1, 2, 3], "warm_p50_ms": 1, "warm_p95_ms": 3,
     "item_counts": [0, 0, 0, 0], "invalid_item_counts": [0, 0, 0, 0], "peak_mib": 0, "raw_path": "private"},
])
def test_benchmark_diagnostics_fail_closed_and_normal_mode_rejects_them(tmp_path: Path, monkeypatch, benchmark):
    from app.learn.recognition.uei.omniparser_shadow_adapter import OmniParserShadowAdapter, OmniParserShadowAdapterError

    payload = {"items": [], "duration_ms": 1, "resource_units": 0, "benchmark": benchmark}
    process, calls = FakeProcess(payload=payload), []
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", _fake_popen(process, calls))
    with pytest.raises(OmniParserShadowAdapterError):
        OmniParserShadowAdapter(configuration=_config(tmp_path), gpu_free_gib=lambda: 99, benchmark_mode=True).invoke(
            capture=_capture(tmp_path), budget=_budget(), invocation_id="invocation/benchmark",
        )
    process, calls = FakeProcess(payload=payload), []
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", _fake_popen(process, calls))
    with pytest.raises(OmniParserShadowAdapterError):
        OmniParserShadowAdapter(configuration=_config(tmp_path), gpu_free_gib=lambda: 99).invoke(
            capture=_capture(tmp_path), budget=_budget(), invocation_id="invocation/normal",
        )


def test_cancellation_before_spawn_does_not_acquire_lease_or_start_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        OmniParserShadowAdapterError,
    )

    calls: list[dict[str, object]] = []
    lease_calls: list[str] = []
    monkeypatch.setattr(
        "app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen",
        lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )
    cancelled = Event()
    cancelled.set()

    with pytest.raises(OmniParserShadowAdapterError, match="cancel") as captured:
        OmniParserShadowAdapter(
            configuration=_config(tmp_path),
            resource_lease_manager=lambda group: lease_calls.append(group),
        ).invoke(
            capture=_capture(tmp_path),
            budget=_budget(),
            invocation_id="invocation/cancel-before",
            cancellation_event=cancelled,
        )

    assert captured.value.cleanup_status == "clean"
    assert calls == []
    assert lease_calls == []


def test_cancellation_during_worker_terminates_tree_releases_lease_and_leaves_no_orphan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        OmniParserShadowAdapterError,
        ProcessResourceLeaseManager,
    )

    lease_root = tmp_path / "leases"
    manager = ProcessResourceLeaseManager(root=lease_root)
    process = FakeProcess(payload={}, timeout=True)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen",
        _fake_popen(process, calls),
    )
    cancelled = Event()
    errors: list[BaseException] = []
    adapter = OmniParserShadowAdapter(
        configuration=_config(tmp_path),
        resource_lease_manager=manager,
    )

    thread = Thread(
        target=lambda: _capture_adapter_error(
            errors,
            adapter,
            capture=_capture(tmp_path),
            budget=_budget(),
            invocation_id="invocation/cancel-during",
            cancellation_event=cancelled,
        )
    )
    thread.start()
    deadline = time.monotonic() + 3
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    cancelled.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], OmniParserShadowAdapterError)
    assert "cancel" in str(errors[0])
    assert errors[0].cleanup_status == "clean"
    assert process.killed is True
    assert process.poll() is not None
    assert list(lease_root.glob("*.lock")) == []
    assert not calls[0]["output_path"].exists()


def _capture_adapter_error(errors: list[BaseException], adapter, **kwargs) -> None:
    try:
        adapter.invoke(**kwargs)
    except BaseException as exc:
        errors.append(exc)

def test_file_lease_release_fails_closed_when_lock_token_is_tampered(tmp_path: Path):
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapterError,
        ProcessResourceLeaseManager,
    )

    root = tmp_path / "leases"
    manager = ProcessResourceLeaseManager(root=root)
    lease = manager("gpu_vision")
    assert lease is not None
    lock_path = root / "gpu_vision.lock"
    lock_path.write_text("forged-token", encoding="utf-8")

    with pytest.raises(OmniParserShadowAdapterError, match="cleanup"):
        lease.release()

    assert lock_path.is_file()
    assert getattr(lease, "_released") is False


def test_windows_taskkill_failure_never_reports_clean_tree_cleanup(monkeypatch):
    from types import SimpleNamespace
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        OmniParserShadowAdapterError,
    )

    if __import__("os").name != "nt":
        pytest.skip("Windows taskkill contract")
    process = FakeProcess(payload={}, timeout=True)
    process._uei_fake_process = False
    monkeypatch.setattr(
        "app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    with pytest.raises(OmniParserShadowAdapterError, match="cleanup"):
        OmniParserShadowAdapter._terminate_tree(process)

    assert process.killed is True and process.returncode == -9


def test_windows_real_child_tree_is_gone_after_termination(tmp_path: Path):
    from app.learn.recognition.uei.omniparser_shadow_adapter import OmniParserShadowAdapter

    if os.name != "nt":
        pytest.skip("Windows process-tree contract")
    pid_file = tmp_path / "child.pid"
    parent_code = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='utf-8');"
        "time.sleep(120)"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code, str(pid_file)],
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    child_pid = 0
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not pid_file.is_file():
            time.sleep(0.02)
        assert pid_file.is_file()
        child_pid = int(pid_file.read_text(encoding="utf-8"))

        OmniParserShadowAdapter._terminate_tree(parent)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _windows_pid_is_active(child_pid):
            time.sleep(0.02)
        assert parent.poll() is not None
        assert _windows_pid_is_active(child_pid) is False
    finally:
        if parent.poll() is None:
            subprocess.run(["taskkill", "/PID", str(parent.pid), "/T", "/F"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if child_pid and _windows_pid_is_active(child_pid):
            subprocess.run(["taskkill", "/PID", str(child_pid), "/T", "/F"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _windows_pid_is_active(pid: int) -> bool:
    if os.name != "nt":
        return False
    import ctypes

    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
            return False
        return exit_code.value == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(process)
