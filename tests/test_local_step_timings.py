"""受控时钟覆盖本地步骤计时；所有系统、模型和输入边界均为替身。"""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import Event, RLock
from types import SimpleNamespace

import pytest

from app.core import runtime_artifacts
from app.desktop_review import local_direct_step as direct


class Clock:
    def __init__(self):
        self.ms = 0

    def advance(self, ms):
        self.ms += ms

    def perf_counter(self):
        return self.ms / 1000

    def now(self):
        return (datetime(2026, 9, 14, tzinfo=timezone.utc) + timedelta(milliseconds=self.ms)).isoformat()


@pytest.fixture
def timed_scene(tmp_path, monkeypatch):
    from app.vision import configuration, model_service

    clock = Clock()
    monkeypatch.setattr(runtime_artifacts.time, "perf_counter", clock.perf_counter)
    monkeypatch.setattr(direct, "perf_counter", clock.perf_counter, raising=False)
    monkeypatch.setattr(direct, "_now", clock.now)
    state = SimpleNamespace(events=[], error_at=None, failure=RuntimeError("private text / private token"),
                            release_failure=None, report_writes=0, started_at=None, finished_at=None)

    def event(name, duration):
        state.events.append(name)
        clock.advance(duration)
        if state.error_at == name:
            raise state.failure

    original_validate = direct._validated_request

    def validate(operation, request):
        event("validate", 2)
        return original_validate(operation, request)

    monkeypatch.setattr(direct, "_validated_request", validate)
    identity = {"contract_version": "windows_native_identity_observation_v1",
        "provider": "windows_native_identity", "status": "observed", "target_window_handle": 321,
        "process_id": 12, "process_create_time": 123.5, "executable_path": "c:\\fixture\\editor.exe"}
    bound = SimpleNamespace(handle=321, process_id=12,
        rect=SimpleNamespace(left=0, top=0, right=800, bottom=600))

    def bind(handle):
        event("bind", 31)
        return bound

    def read_identity(handle):
        event("identity", 37)
        state.started_at = clock.now()
        return dict(identity)

    manager = SimpleNamespace(bind_window_by_handle=bind)
    monkeypatch.setattr(direct, "WindowsNativeIdentityReader",
                        lambda **kwargs: SimpleNamespace(read_identity=read_identity))
    monkeypatch.setattr(direct, "_local_operator_step_scope", nullcontext)
    monkeypatch.setattr(direct, "_local_operator_input_scope", lambda **kwargs: nullcontext())
    monkeypatch.setattr(direct, "observe_recovery_windows", lambda manager, identity:
        {"status": "unavailable", "candidates": [], "authorizes_input": False,
         "successor_identity_verified": False})

    class Capture:
        def __init__(self, **kwargs):
            self.root = kwargs["capture_dir"]

        def capture_window(self, **kwargs):
            event("capture", 41)
            self.root.mkdir(parents=True)
            path = self.root / "current.png"
            path.write_bytes(b"synthetic capture bytes")
            return {"image_path": str(path), "image_width": 800, "image_height": 600}

    monkeypatch.setattr(direct, "ScreenshotService", Capture)
    original_read = Path.read_bytes

    def read_bytes(path):
        if path.name == "current.png":
            event("capture_hash", 43)
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    def post_action(*args):
        event("route", 47)
        state.finished_at = clock.now()
        return {"success": True}

    monkeypatch.setattr(direct, "_post_action", post_action)
    original_write = direct._write_report

    def write_report(output, report):
        state.report_writes += 1
        event("report_write_" + str(state.report_writes), 53)
        original_write(output, report)

    monkeypatch.setattr(direct, "_write_report", write_report)
    snapshot, frozen = object(), object()

    def load(path):
        event("configuration_load", 7)
        return snapshot

    def freeze(value):
        assert value is snapshot
        event("configuration_freeze", 11)
        return frozen

    monkeypatch.setattr(configuration, "load_formal_vision_configuration", load)
    monkeypatch.setattr(model_service, "freeze_model_service", freeze)
    monkeypatch.setattr(configuration, "pinned_vision_configuration", lambda value: nullcontext())

    class Coordinator(direct.LocalDirectStepMixin):
        def __init__(self):
            self._runtime_output_root = tmp_path
            self._vision_config_path = tmp_path / "not-read.json"
            self._guard = RLock()
            self._uses_production_factory = True
            self._automatic_safety_interception = False
            self._runtime = self._learning_binding = self._model_service = None
            self._attached = self._shutdown = False
            self._cancel_wait = Event()
            self._keep_models_loaded = False
            self._resident_model_services = {}
            self._owner = SimpleNamespace(call=self.owner_call)

        def owner_call(self, callback):
            event("owner_queue", 13)
            result = callback()
            event("owner_return", 17)
            return result

        def _begin(self, phase):
            event("begin", 3)

        def _end(self):
            event("end", 29)

        def _require_host_ready(self, **kwargs):
            event("host", 5)

        def _error(self, code, message):
            return RuntimeError(message)

        def _windows(self):
            return manager

        def _prepare_model_service_on_owner(self, value):
            assert value is frozen
            event("model_prepare", 19)

        def _release_model_service(self):
            event("model_release", 23)
            if state.release_failure is not None:
                raise state.release_failure

    coordinator = Coordinator()
    return coordinator, state, clock, frozen


def run_step(coordinator, operation="execute_recognition_plan", request=None):
    return coordinator.execute_local_step(target_window_handle=321, target_process_id=12,
        operation=operation, request={"goal": "synthetic target"} if request is None else request)


def saved_report(coordinator):
    reports = list(coordinator._runtime_output_root.glob("local-direct-steps/*/report.json"))
    assert len(reports) == 1
    return json.loads(reports[0].read_text(encoding="utf-8"))


def saved_invocation(coordinator):
    reports = list(coordinator._runtime_output_root.glob("local-direct-invocations/*/invocation.json"))
    assert len(reports) == 1
    content = reports[0].read_text(encoding="utf-8")
    assert "private text" not in content and "private token" not in content
    assert "request" not in json.loads(content)
    return json.loads(content)


def stages(timings):
    return {step["name"]: step for step in timings["steps"]}


def test_inclusive_invocation_covers_prepare_release_and_preserves_legacy_timestamps(timed_scene):
    co, state, clock, _frozen = timed_scene
    result = run_step(co)
    assert saved_report(co) == result
    assert result["started_at"] == state.started_at
    assert result["finished_at"] == state.finished_at
    invocation = result["invocation_timings"]
    inner = result["local_step_timings"]
    assert invocation["inclusive"] is True and invocation["nested_timings_additive"] is False
    assert invocation["final_timing_sync_excluded"] is True
    assert invocation["total_ms"] == 464 == clock.ms - 53
    assert inner["total_ms"] == 305
    outer_stages = stages(invocation)
    assert outer_stages["request_validation"]["elapsed_ms"] == 2
    assert outer_stages["host_preparation"]["elapsed_ms"] == 5
    assert outer_stages["configuration_load"]["elapsed_ms"] == 18
    assert outer_stages["model_prepare_or_reuse"]["elapsed_ms"] == 49
    assert outer_stages["model_prepare_or_reuse"]["mode"] == "prepare"
    assert outer_stages["owner_dispatch"]["elapsed_ms"] == inner["total_ms"] + 30
    assert outer_stages["owner_dispatch"]["queue_wait_ms"] == 13
    assert outer_stages["model_release"]["elapsed_ms"] == 23
    inner_stages = stages(inner)
    assert inner_stages["binding_identity"]["elapsed_ms"] == 68
    assert inner_stages["capture_hash"]["elapsed_ms"] == 84
    assert inner_stages["route_call"]["elapsed_ms"] == 47
    assert [step["elapsed_ms"] for step in inner["steps"] if step["name"] == "report_persist"] == [53, 53]
    assert state.events.count("route") == state.events.count("model_prepare") == state.events.count("model_release") == 1


def test_resident_reuse_is_observed_without_new_preparation_or_dispatch(timed_scene):
    co, state, _clock, frozen = timed_scene
    co._keep_models_loaded = True
    co._resident_model_services[frozen] = object()
    result = run_step(co)
    assert stages(result["invocation_timings"])["model_prepare_or_reuse"]["mode"] == "reuse"
    assert state.events.count("model_prepare") == state.events.count("route") == 1


def test_non_model_action_has_no_model_or_configuration_stages(timed_scene):
    co, state, _clock, _frozen = timed_scene
    result = run_step(co, "press_key", {"key": "Enter", "x": 30, "y": 20})
    assert saved_report(co) == result
    assert not ({"model_prepare_or_reuse", "model_release", "configuration_load"} & stages(result["invocation_timings"]).keys())
    assert state.events.count("route") == 1 and "model_prepare" not in state.events


@pytest.mark.parametrize("failure_stage,begin_completed,release_expected,total_ms", [
    ("validate", False, False, 2), ("begin", False, False, 5), ("host", True, False, 39),
    ("configuration_load", True, False, 46), ("model_prepare", True, True, 112), ("bind", True, True, 173),
])
def test_pre_dispatch_failure_has_private_free_timings_and_same_exception(
        timed_scene, failure_stage, begin_completed, release_expected, total_ms):
    co, state, _clock, _frozen = timed_scene
    state.error_at = failure_stage
    with pytest.raises(RuntimeError) as raised:
        run_step(co)
    assert raised.value is state.failure
    report = saved_invocation(co)
    assert report["invocation_status"] == "raised"
    assert report["invocation_error_type"] == "RuntimeError"
    assert report["invocation_timings"]["total_ms"] == total_ms
    assert "route" not in state.events
    assert ("end" in state.events) is begin_completed
    assert ("model_release" in state.events) is release_expected


@pytest.mark.parametrize("failure_stage", ["capture", "route", "report_write_2"])
def test_owner_failure_syncs_timings_to_existing_report_without_reexecuting(timed_scene, failure_stage):
    co, state, _clock, _frozen = timed_scene
    state.error_at = failure_stage
    with pytest.raises(RuntimeError) as raised:
        run_step(co)
    assert raised.value is state.failure
    report = saved_report(co)
    assert report["invocation_status"] == "raised"
    assert report["local_input_scope_closed"] is True
    assert report["invocation_timings"]["total_ms"] >= report["local_step_timings"]["total_ms"]
    assert state.events.count("route") == (0 if failure_stage == "capture" else 1)
    assert state.events.count("model_release") == state.events.count("end") == 1


@pytest.mark.parametrize("prepare_fails", [False, True])
def test_cleanup_failure_remains_primary_and_still_records_completed_stages(timed_scene, prepare_fails):
    co, state, _clock, _frozen = timed_scene
    state.release_failure = ValueError("private token during cleanup")
    state.error_at = "model_prepare" if prepare_fails else None
    with pytest.raises(ValueError) as raised:
        run_step(co)
    assert raised.value is state.release_failure
    report = saved_invocation(co) if prepare_fails else saved_report(co)
    assert report["invocation_error_type"] == "ValueError"
    assert stages(report["invocation_timings"])["model_release"]["elapsed_ms"] == 23
    assert state.events.count("end") == 1


def test_enabled_safety_policy_still_blocks_before_model_capture_and_route(timed_scene):
    co, state, _clock, _frozen = timed_scene
    co._automatic_safety_interception = True
    with pytest.raises(RuntimeError, match="automatic safety interception"):
        run_step(co)
    assert not ({"configuration_load", "model_prepare", "capture", "route"} & set(state.events))
    assert saved_invocation(co)["invocation_status"] == "raised"


def test_timing_sync_failure_does_not_replace_original_cleanup_error(timed_scene):
    co, state, _clock, _frozen = timed_scene
    state.release_failure = ValueError("private token during cleanup")
    state.error_at = "report_write_3"
    with pytest.raises(ValueError) as raised:
        run_step(co)
    assert raised.value is state.release_failure
    assert any("RuntimeError" in note for note in raised.value.__notes__)
    assert "route" in state.events and state.events.count("route") == 1


def test_successful_action_does_not_hide_timing_sync_failure_or_retry(timed_scene):
    co, state, _clock, _frozen = timed_scene
    state.error_at = "report_write_3"
    with pytest.raises(RuntimeError) as raised:
        run_step(co)
    assert raised.value is state.failure
    assert saved_report(co)["phase"] == "returned"
    assert state.events.count("route") == state.events.count("model_release") == state.events.count("end") == 1


def test_preparation_failure_is_preserved_when_invocation_storage_is_unavailable(timed_scene, monkeypatch):
    co, state, _clock, _frozen = timed_scene
    state.error_at = "model_prepare"
    original_write = Path.write_text

    def write_text(path, *args, **kwargs):
        if path.name == "invocation.json":
            raise OSError("private token in storage error")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text)
    with pytest.raises(RuntimeError) as raised:
        run_step(co)
    assert raised.value is state.failure
    assert raised.value.__notes__ == ["local step timing persistence failed: OSError"]
    assert "route" not in state.events and state.events.count("model_release") == 1


def test_invalid_operation_is_not_written_to_failure_artifact(timed_scene):
    co, state, _clock, _frozen = timed_scene
    with pytest.raises(ValueError, match="unsupported local"):
        run_step(co, "private token")
    assert saved_invocation(co)["operation"] == "unsupported"
    assert state.events == ["validate"]
