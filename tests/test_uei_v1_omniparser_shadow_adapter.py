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



class _BarrierCancellation:
    def __init__(self, stage: str) -> None:
        from threading import Lock

        self._cancelled = Event()
        self._lock = Lock()
        self._stage = stage
        self.entered = Event()
        self.release = Event()

    def is_set(self) -> bool:
        return self._cancelled.is_set()

    def set(self) -> None:
        with self._lock:
            self._cancelled.set()

    def run_if_not_cancelled(self, stage: str, action):
        if stage == self._stage:
            self.entered.set()
            assert self.release.wait(timeout=3)
        with self._lock:
            if self._cancelled.is_set():
                return False, None
            return True, action()

def test_fixed_worker_success_is_normalized_without_worker_identity_or_path(tmp_path: Path, monkeypatch):
    from app.learn.recognition.uei.omniparser_shadow_adapter import ROOT, OmniParserShadowAdapter

    process = FakeProcess(payload={"items": [{"source_item_id": "item/1", "kind": "text", "safe_text": "Search",
                                                "safe_role": "text", "safe_states": ["interactable"],
                                                "source_bbox": [1, 2, 10, 20], "source_coordinate_space": "capture_pixel_xyxy",
                                                "provider_confidence": 0.8}], "duration_ms": 2, "resource_units": 1})
    calls: list[dict[str, object]] = []
    monkeypatch.setattr("app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen", _fake_popen(process, calls))
    configuration = _config(tmp_path)
    output = OmniParserShadowAdapter(configuration=configuration).invoke(
        capture=_capture(tmp_path), budget=_budget(), invocation_id="invocation/1",
    )

    assert output.items[0].safe_text == "Search" and output.items[0].source_bbox == (1, 2, 10, 20)
    assert output.items[0].source_coordinate_space == "capture_pixel_xyxy"
    assert output.items[0].safe_role == "text"
    assert output.items[0].safe_states == ("interactable",)
    assert calls[0]["env"]["HF_HUB_OFFLINE"] == "1"
    assert calls[0]["env"]["HF_HUB_CACHE"] == str(configuration.cache_path)
    assert calls[0]["env"]["USERPROFILE"] == str(ROOT / "runtime_state" / "omniparser-home")
    assert not {"HOME", "HOMEDRIVE", "HOMEPATH"}.intersection(calls[0]["env"])
    assert "capture.png" not in repr(output)
    assert not calls[0]["output_path"].exists()


def test_offline_environment_preserves_only_windows_program_roots(tmp_path: Path, monkeypatch) -> None:
    from app.learn.recognition.uei.omniparser_shadow_adapter import _offline_environment

    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramW6432", r"C:\Program Files")
    monkeypatch.setenv("HOME", r"C:\Users\private")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\private")
    monkeypatch.setenv("HOMEDRIVE", "C:")
    monkeypatch.setenv("HOMEPATH", r"\Users\private")
    monkeypatch.setenv("ARBITRARY_PARENT_VALUE", "must-not-propagate")

    environment = _offline_environment(tmp_path / "cache")

    assert environment["ProgramFiles"] == r"C:\Program Files"
    assert environment["ProgramW6432"] == r"C:\Program Files"
    assert not {"HOME", "HOMEDRIVE", "HOMEPATH"}.intersection(environment)
    assert "ARBITRARY_PARENT_VALUE" not in environment


def test_offline_environment_sets_library_caches_without_user_identity(tmp_path: Path, monkeypatch) -> None:
    from app.learn.recognition.uei import omniparser_shadow_adapter as omni

    monkeypatch.setenv("HOME", r"C:\Users\private")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\private")
    monkeypatch.setenv("USERNAME", "private-user")
    monkeypatch.setenv("HOMEDRIVE", "C:")
    monkeypatch.setenv("HOMEPATH", r"\Users\private")
    monkeypatch.setenv("TORCHINDUCTOR_CACHE_DIR", r"C:\Users\private\torchinductor")
    monkeypatch.setenv("YOLO_CONFIG_DIR", r"C:\Users\private\ultralytics")
    monkeypatch.setattr(omni, "ROOT", tmp_path)
    cache_path = tmp_path / "huggingface" / "hub"

    environment = omni._offline_environment(cache_path)

    runtime_cache_root = tmp_path / "runtime_state" / "omniparser-home"
    assert environment["USERPROFILE"] == str(runtime_cache_root)
    assert environment["USERPROFILE"] != r"C:\Users\private"
    assert environment["TORCHINDUCTOR_CACHE_DIR"] == str(runtime_cache_root / "torchinductor")
    assert environment["YOLO_CONFIG_DIR"] == str(runtime_cache_root / "ultralytics")
    assert not {"HOME", "USERNAME", "HOMEDRIVE", "HOMEPATH"}.intersection(environment)


def test_installed_configuration_snapshot_is_sealed_at_construction_and_survives_profile_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from app.learn.hybrid import windows_process_scope
    from app.learn.recognition.uei import omniparser_shadow_adapter as omni

    runtime = tmp_path / "runtime"
    interpreter = runtime / "Scripts" / "python.exe"
    worker = tmp_path / "worker.py"
    code = tmp_path / "code"
    weights = tmp_path / "weights"
    cache = tmp_path / "cache"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("fixed", encoding="utf-8")
    worker.write_text("fixed", encoding="utf-8")
    for path in (code, weights, cache):
        path.mkdir()
    profile_path = tmp_path / "learn_mode_omniparser_v2.json"
    original_profile = {
        "expected_paths": {
            "runtime_path": "runtime",
            "code_path": "code",
            "weights_path": "weights",
            "huggingface_cache_path": str(cache),
        },
        "runtime_probe": {"minimum_free_gpu_gib": 3},
        "launchable": True,
        "download_status": "downloaded",
    }
    profile_path.write_text(json.dumps(original_profile), encoding="utf-8")
    monkeypatch.setattr(omni, "ROOT", tmp_path)
    monkeypatch.setattr(omni, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(omni, "WORKER_PATH", worker)
    adapter = omni.OmniParserShadowAdapter()
    snapshot = adapter.installed_configuration_snapshot

    profile_path.write_text(
        json.dumps(
            {
                **original_profile,
                "expected_paths": {
                    **original_profile["expected_paths"],
                    "weights_path": "replaced-weights",
                },
                "runtime_probe": {"minimum_free_gpu_gib": 99},
            }
        ),
        encoding="utf-8",
    )
    captured_runtime: list[dict[str, object]] = []
    process = FakeProcess(
        payload={"items": [], "duration_ms": 1, "resource_units": 1}
    )
    process.process_identity = {"pid": process.pid, "create_time_ns": 7}

    def _spawn(command: list[str], **kwargs: object) -> FakeProcess:
        before_resume = kwargs["before_resume"]
        before_resume(dict(process.process_identity))
        output = Path(command[command.index("--output-json") + 1])
        output.write_text(json.dumps(process.payload), encoding="utf-8")
        return process

    class _Scope:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def pids(self) -> list[int]:
            return [process.pid]

        def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", "omni-scope")
    monkeypatch.setattr(windows_process_scope, "spawn_process_in_scope", _spawn)
    monkeypatch.setattr(windows_process_scope, "WindowsProcessScope", _Scope)
    monkeypatch.setattr(
        attestation,
        "current_benchmark_dispatch_context",
        lambda: {"provider": "omni", "operation_ref": {}, "window_binding": {}},
    )
    monkeypatch.setattr(
        attestation,
        "attest_benchmark_provider_dispatch",
        lambda **kwargs: captured_runtime.append(kwargs["provider_runtime"])
        or {"content_sha256": "d" * 64},
    )
    adapter._cleanup_observation = {
        "process_identity": None,
        "descendant_identities": [],
        "inventory_observable": True,
    }
    monkeypatch.setattr(adapter, "_capture_cleanup_process_tree", lambda value: None)

    adapter._invoke_worker(
        capture=_capture(tmp_path), budget=_budget(), cancellation_event=None
    )

    assert snapshot["contract_version"] == "omniparser_installed_configuration_snapshot_v1"
    assert snapshot["profile_id"] == omni.PROFILE_ID
    assert snapshot["interpreter_path"] == str(interpreter.resolve())
    assert snapshot["worker_script_path"] == str(worker.resolve())
    assert snapshot["code_path"] == str(code.resolve())
    assert snapshot["weights_path"] == str(weights.resolve())
    assert snapshot["cache_path"] == str(cache.resolve())
    assert snapshot["minimum_free_gpu_gib"] == 3
    assert snapshot["is_available"] is True
    assert snapshot["content_sha256"] == omni.content_sha256(snapshot)
    assert captured_runtime == [
        {
            "provider": "omni",
            "process_identity": process.process_identity,
            "scope_name": "omni-scope",
            "installed_configuration_snapshot": snapshot,
        }
    ]


def test_adapter_persists_exact_invocation_cleanup_observation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.learn.recognition.uei import omniparser_shadow_adapter as adapter_module
    from app.learn.hybrid import windows_process_scope

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(adapter_module, "OMNI_CLEANUP_OBSERVATION_ROOT", tmp_path / "cleanup")
    lineage = {
        "run_id": "run-omni-adapter",
        "workflow_revision": 7,
        "operation_id": "operation-omni-adapter",
        "stage": "screen_understanding",
        "stage_execution_id": "execution-omni-adapter",
    }
    scope_name = windows_process_scope.process_scope_name(lineage, "omni")
    scope = windows_process_scope.WindowsProcessScope(scope_name, create=True)
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setenv(
        "AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", str(tmp_path / "runtime.json")
    )
    monkeypatch.setenv("AGENT_GUI_HYBRID_LINEAGE_JSON", json.dumps(lineage))
    real_spawn = windows_process_scope.spawn_process_in_scope

    def controlled_scoped_spawn(command, **kwargs):
        output_path = Path(command[command.index("--output-json") + 1])
        payload = {"items": [], "duration_ms": 2, "resource_units": 1}
        code = (
            "import json,time;"
            f"open({str(output_path)!r},'w',encoding='utf-8').write("
            f"json.dumps({payload!r}));time.sleep(0.03)"
        )
        calls.append({"command": command, "output_path": output_path})
        return real_spawn(
            [sys.executable, "-c", code],
            scope_name=kwargs["scope_name"],
            cwd=kwargs["cwd"],
        )

    monkeypatch.setattr(
        windows_process_scope,
        "spawn_process_in_scope",
        controlled_scoped_spawn,
    )

    try:
        adapter_module.OmniParserShadowAdapter(
            configuration=_config(tmp_path),
            resource_lease_manager=adapter_module.ProcessResourceLeaseManager(
                root=tmp_path / "leases"
            ),
        ).invoke(
            capture=_capture(tmp_path),
            budget=_budget(),
            invocation_id="invocation/cleanup-observed",
        )
    finally:
        scope.close()
    observation = adapter_module.load_omniparser_invocation_cleanup_observation(
        "invocation/cleanup-observed"
    )

    assert observation["cleanup_status"] == "verified"
    provider_pid = observation["process_identity"]["pid"]
    assert provider_pid > 0
    assert observation["provider_processes_after"] == []
    assert observation["orphan_descendant_identities"] == []
    assert observation["active_listeners_after"] == []
    assert observation["pid_file_paths"] == []
    assert observation["lease_files_after"] == []
    assert observation["process_scope_name"] == scope_name
    assert provider_pid in observation["process_scope_acquisition"][
        "member_pids"
    ]
    assert provider_pid in observation["process_scope_cleanup"][
        "observed_member_pids_before"
    ] or observation["process_scope_cleanup"]["observed_member_pids_before"] == []


@pytest.mark.parametrize("owner_scope_closed", [False, True])
def test_abnormal_reconciliation_removes_exact_resource_lease_and_seals_observation(
    tmp_path: Path,
    monkeypatch,
    owner_scope_closed: bool,
) -> None:
    from app.learn.recognition.uei import omniparser_shadow_adapter as adapter_module
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    monkeypatch.setattr(adapter_module, "OMNI_CLEANUP_OBSERVATION_ROOT", tmp_path / "cleanup")
    lineage = {
        "run_id": "run-omni-abnormal",
        "workflow_revision": 7,
        "operation_id": "operation-omni-abnormal",
        "stage": "screen_understanding",
        "stage_execution_id": "execution-omni-abnormal",
    }
    scope_name = process_scope_name(lineage, "omni")
    scope = WindowsProcessScope(scope_name, create=True)
    manager = adapter_module.ProcessResourceLeaseManager(root=tmp_path / "leases")
    lease = manager("gpu_vision")
    assert lease is not None
    runtime_path = tmp_path / "omni-runtime.json"
    adapter_module.persist_omniparser_invocation_owner(
        runtime_path,
        invocation_id="invocation/abnormal-owner",
        resource_group="gpu_vision",
        resource_lease=lease,
        lineage=lineage,
        process_scope_name=scope_name,
    )
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    adapter_module.publish_omniparser_process_identity(
        runtime_path,
        process_identity=helper.process_identity,
    )
    if owner_scope_closed:
        scope.close()
        helper.wait(10)
        assert helper.poll() is not None
    try:
        evidence = adapter_module.reconcile_omniparser_invocation_owner(
            runtime_path,
            expected_lineage=lineage,
            expected_scope_name=scope_name,
        )
        assert evidence["status"] == "verified"
        assert list((tmp_path / "leases").glob("*.lock")) == []
        assert helper.poll() is not None
        observation = adapter_module.load_omniparser_invocation_cleanup_observation(
            "invocation/abnormal-owner"
        )
        assert observation["cleanup_status"] == "verified"
        assert observation["cleanup_reason"] == "outer_worker_terminated"
        assert observation["lineage"] == lineage
    finally:
        helper.close()
        if not owner_scope_closed:
            scope.close()


@pytest.mark.parametrize(
    "crash_phase", ["intent", "lease_removed", "scope_cleaned", "observation_written"]
)
def test_omni_abnormal_finalization_retries_each_durable_phase(
    tmp_path: Path,
    monkeypatch,
    crash_phase: str,
) -> None:
    from app.learn.recognition.uei import omniparser_shadow_adapter as adapter_module
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    monkeypatch.setattr(adapter_module, "OMNI_CLEANUP_OBSERVATION_ROOT", tmp_path / "cleanup")
    lineage = {
        "run_id": f"run-omni-crash-{crash_phase}",
        "workflow_revision": 7,
        "operation_id": f"operation-omni-crash-{crash_phase}",
        "stage": "screen_understanding",
        "stage_execution_id": f"execution-omni-crash-{crash_phase}",
    }
    scope_name = process_scope_name(lineage, "omni")
    scope = WindowsProcessScope(scope_name, create=True)
    lease = adapter_module.ProcessResourceLeaseManager(root=tmp_path / "leases")(
        "gpu_vision"
    )
    assert lease is not None
    runtime_path = tmp_path / "runtime.json"
    adapter_module.persist_omniparser_invocation_owner(
        runtime_path,
        invocation_id=f"invocation/crash-{crash_phase}",
        resource_group="gpu_vision",
        resource_lease=lease,
        lineage=lineage,
        process_scope_name=scope_name,
    )
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    adapter_module.publish_omniparser_process_identity(
        runtime_path,
        process_identity=helper.process_identity,
    )
    original_write = adapter_module._write_sealed_json
    injected = False

    def crash_after_phase(path, document):
        nonlocal injected
        original_write(path, document)
        finalization = document.get("finalization") if isinstance(document, dict) else None
        if (
            not injected
            and isinstance(finalization, dict)
            and finalization.get("phase") == crash_phase
        ):
            injected = True
            raise RuntimeError(f"injected-{crash_phase}")

    monkeypatch.setattr(adapter_module, "_write_sealed_json", crash_after_phase)
    try:
        with pytest.raises(RuntimeError, match=f"injected-{crash_phase}"):
            adapter_module.reconcile_omniparser_invocation_owner(
                runtime_path,
                expected_lineage=lineage,
                expected_scope_name=scope_name,
            )
        monkeypatch.setattr(adapter_module, "_write_sealed_json", original_write)
        recovered = adapter_module.reconcile_omniparser_invocation_owner(
            runtime_path,
            expected_lineage=lineage,
            expected_scope_name=scope_name,
        )
        assert recovered["status"] == "verified"
        owner = json.loads(runtime_path.read_text(encoding="utf-8"))
        assert owner["state"] == "released"
        assert owner["finalization"]["phase"] == "released"
        assert list((tmp_path / "leases").glob("*.lock")) == []
    finally:
        if helper.poll() is None:
            scope.terminate()
            helper.wait(10)
        helper.close()
        scope.close()


def test_omni_normal_finally_interruption_recovers_owned_lease_removal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.learn.recognition.uei import omniparser_shadow_adapter as adapter_module
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    monkeypatch.setattr(adapter_module, "OMNI_CLEANUP_OBSERVATION_ROOT", tmp_path / "cleanup")
    lineage = {
        "run_id": "run-omni-normal-interruption",
        "workflow_revision": 7,
        "operation_id": "operation-omni-normal-interruption",
        "stage": "screen_understanding",
        "stage_execution_id": "execution-omni-normal-interruption",
    }
    scope_name = process_scope_name(lineage, "omni")
    scope = WindowsProcessScope(scope_name, create=True)
    lease = adapter_module.ProcessResourceLeaseManager(root=tmp_path / "leases")(
        "gpu_vision"
    )
    assert lease is not None
    runtime_path = tmp_path / "runtime.json"
    adapter_module.persist_omniparser_invocation_owner(
        runtime_path,
        invocation_id="invocation/normal-finally-interrupted",
        resource_group="gpu_vision",
        resource_lease=lease,
        lineage=lineage,
        process_scope_name=scope_name,
    )
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    adapter_module.publish_omniparser_process_identity(
        runtime_path,
        process_identity=helper.process_identity,
    )
    adapter_module._begin_omniparser_finalization(runtime_path, "completed")
    lease.release()
    try:
        recovered = adapter_module.reconcile_omniparser_invocation_owner(
            runtime_path,
            expected_lineage=lineage,
            expected_scope_name=scope_name,
        )
        assert recovered["status"] == "verified"
        observation = recovered["cleanup_observation"]
        assert observation["cleanup_reason"] == "completed"
        assert observation["cleanup_status"] == "verified"
        assert list((tmp_path / "leases").glob("*.lock")) == []
        assert helper.poll() is not None
    finally:
        if helper.poll() is None:
            scope.terminate()
            helper.wait(10)
        helper.close()
        scope.close()


@pytest.mark.parametrize(
    "crash_phase", ["lease_removed", "scope_cleaned", "observation_written", "released"]
)
def test_real_normal_omni_finalizer_recovers_after_every_durable_advance(
    tmp_path: Path,
    monkeypatch,
    crash_phase: str,
) -> None:
    from app.learn.recognition.uei import omniparser_shadow_adapter as adapter_module
    from app.learn.hybrid import windows_process_scope

    monkeypatch.setattr(adapter_module, "OMNI_CLEANUP_OBSERVATION_ROOT", tmp_path / "cleanup")
    lineage = {
        "run_id": f"run-normal-advance-{crash_phase}",
        "workflow_revision": 7,
        "operation_id": f"operation-normal-advance-{crash_phase}",
        "stage": "screen_understanding",
        "stage_execution_id": f"execution-normal-advance-{crash_phase}",
    }
    scope_name = windows_process_scope.process_scope_name(lineage, "omni")
    scope = windows_process_scope.WindowsProcessScope(scope_name, create=True)
    runtime_path = tmp_path / "runtime.json"
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("AGENT_GUI_HYBRID_LINEAGE_JSON", json.dumps(lineage))
    real_spawn = windows_process_scope.spawn_process_in_scope

    def controlled_scoped_spawn(command, **kwargs):
        output_path = Path(command[command.index("--output-json") + 1])
        payload = {"items": [], "duration_ms": 2, "resource_units": 1}
        code = (
            "import json,time;"
            f"open({str(output_path)!r},'w',encoding='utf-8').write("
            f"json.dumps({payload!r}));time.sleep(0.03)"
        )
        return real_spawn(
            [sys.executable, "-c", code],
            scope_name=kwargs["scope_name"],
            cwd=kwargs["cwd"],
        )

    monkeypatch.setattr(
        windows_process_scope, "spawn_process_in_scope", controlled_scoped_spawn
    )
    original_advance = adapter_module._advance_omniparser_finalization
    injected = False

    def crash_after_advance(path, phase, **evidence):
        nonlocal injected
        document = original_advance(path, phase, **evidence)
        if not injected and phase == crash_phase:
            injected = True
            raise RuntimeError(f"injected-normal-{crash_phase}")
        return document

    monkeypatch.setattr(
        adapter_module, "_advance_omniparser_finalization", crash_after_advance
    )
    invocation_id = f"invocation/normal-advance-{crash_phase}"
    try:
        with pytest.raises(RuntimeError, match=f"injected-normal-{crash_phase}"):
            adapter_module.OmniParserShadowAdapter(
                configuration=_config(tmp_path),
                resource_lease_manager=adapter_module.ProcessResourceLeaseManager(
                    root=tmp_path / "leases"
                ),
            ).invoke(
                capture=_capture(tmp_path),
                budget=_budget(),
                invocation_id=invocation_id,
            )
        if crash_phase == "scope_cleaned":
            observation_path = adapter_module._cleanup_observation_path(invocation_id)
            exact_observation = json.loads(
                observation_path.read_text(encoding="utf-8")
            )
            stale_observation = dict(exact_observation)
            stale_observation.pop("content_sha256")
            stale_observation["resource_lease_identity"] = {
                **stale_observation["resource_lease_identity"],
                "lease_token_sha256": "f" * 64,
            }
            observation_path.write_text(
                json.dumps(adapter_module.seal_immutable(stale_observation)),
                encoding="utf-8",
            )
            adapter_module._mark_omniparser_runtime_released(
                runtime_path, invocation_id
            )
            stale_owner = json.loads(runtime_path.read_text(encoding="utf-8"))
            assert stale_owner["finalization"]["phase"] == "scope_cleaned"
            observation_path.write_text(
                json.dumps(exact_observation), encoding="utf-8"
            )
        monkeypatch.setattr(
            adapter_module,
            "_advance_omniparser_finalization",
            original_advance,
        )
        first = adapter_module.reconcile_omniparser_invocation_owner(
            runtime_path,
            expected_lineage=lineage,
            expected_scope_name=scope_name,
        )
        second = adapter_module.reconcile_omniparser_invocation_owner(
            runtime_path,
            expected_lineage=lineage,
            expected_scope_name=scope_name,
        )
        assert first == second
        assert first["status"] == "verified"
        assert first["cleanup_observation"]["cleanup_reason"] == "completed"
        owner = json.loads(runtime_path.read_text(encoding="utf-8"))
        assert owner["state"] == "released"
        assert owner["finalization"]["phase"] == "released"
        assert owner["finalization"]["scope_cleanup_evidence"][
            "cleanup_status"
        ] == "verified"
        assert list((tmp_path / "leases").glob("*.lock")) == []
    finally:
        scope.close()


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


def test_cancellation_winning_before_lease_prevents_lease_and_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        OmniParserShadowAdapterError,
    )

    cancellation = _BarrierCancellation("before_lease")
    lease_calls: list[str] = []
    spawn_calls: list[object] = []
    monkeypatch.setattr(
        "app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen",
        lambda *args, **kwargs: spawn_calls.append((args, kwargs)),
    )
    errors: list[BaseException] = []
    adapter = OmniParserShadowAdapter(
        configuration=_config(tmp_path),
        resource_lease_manager=lambda group: lease_calls.append(group),
        gpu_free_gib=lambda: 16.0,
    )
    thread = Thread(
        target=lambda: _capture_adapter_error(
            errors,
            adapter,
            capture=_capture(tmp_path),
            budget=_budget(),
            invocation_id="invocation/cancel-before-lease",
            cancellation_event=cancellation,
        )
    )
    thread.start()
    assert cancellation.entered.wait(timeout=3)
    cancellation.set()
    cancellation.release.set()
    thread.join(timeout=3)

    assert len(errors) == 1
    assert isinstance(errors[0], OmniParserShadowAdapterError)
    assert errors[0].cleanup_status == "clean"
    assert lease_calls == []
    assert spawn_calls == []


def test_cancellation_winning_before_popen_releases_lease_without_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        OmniParserShadowAdapterError,
        ProcessResourceLeaseManager,
    )

    cancellation = _BarrierCancellation("before_popen")
    lease_root = tmp_path / "barrier-leases"
    spawn_calls: list[object] = []
    monkeypatch.setattr(
        "app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen",
        lambda *args, **kwargs: spawn_calls.append((args, kwargs)),
    )
    errors: list[BaseException] = []
    adapter = OmniParserShadowAdapter(
        configuration=_config(tmp_path),
        resource_lease_manager=ProcessResourceLeaseManager(root=lease_root),
        gpu_free_gib=lambda: 16.0,
    )
    thread = Thread(
        target=lambda: _capture_adapter_error(
            errors,
            adapter,
            capture=_capture(tmp_path),
            budget=_budget(),
            invocation_id="invocation/cancel-before-popen",
            cancellation_event=cancellation,
        )
    )
    thread.start()
    assert cancellation.entered.wait(timeout=3)
    cancellation.set()
    cancellation.release.set()
    thread.join(timeout=3)

    assert len(errors) == 1
    assert isinstance(errors[0], OmniParserShadowAdapterError)
    assert errors[0].cleanup_status == "clean"
    assert spawn_calls == []
    assert list(lease_root.glob("*.lock")) == []
