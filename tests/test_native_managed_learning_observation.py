"""受管目标观察通过正式 host 与 owner 边界。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, get_ident

import pytest

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from app.vision.request_control import current_model_request
from tests.test_formal_fresh_learning_observation import _ScreenshotService, _owner

_REVIEWER = "managed-observation-reviewer"
_APPLICATION = {"kind": "web", "canonical_origin": "https://fresh.example"}


def _open_segment(host):
    connection = host._service.reviewer_call(_REVIEWER, "create_connection", {
        "task_id": "managed-observation-task", "agent_name": "managed-observer",
    })
    segment = host._service.agent_call(connection["token"], "start_learning_segment", {
        "idempotency_key": "managed-segment", "title": "Managed observation",
    })
    return connection, segment


def _request(segment, *, key="managed-capture", goal="Read screen"):
    return {
        "segment_id": segment["segment_id"], "idempotency_key": key,
        "application_identity": _APPLICATION, "target_window_handle": 4242,
        "target_process_id": 9001, "title": "Managed screen",
        "meaning": "A fresh managed observation", "goal": goal,
    }


def _packet_owner(root: Path, application: dict, captures: list, trace: list):
    screenshot = _ScreenshotService(root / "capture")
    capture = screenshot.capture_window

    def traced_capture(**kwargs):
        trace.append(("capture", get_ident()))
        return capture(**kwargs)

    screenshot.capture_window = traced_capture
    actual = _owner(root, application=application, screenshot=screenshot)

    class Owner:
        def observe(self, **kwargs):
            trace.append(("observe", get_ident()))
            assert current_model_request() is not None
            captures.append(screenshot)
            return actual.observe(**kwargs)

    return Owner()


def _managed_rig(tmp_path, monkeypatch, *, behavior=None, close_proof=None, hold_prepare=None, no_service=False):
    """真实 host/provider/SerialRuntimeOwner；仅替换 OS 与模型边界。"""
    import app.agent.fresh_learning_factory as factory_module
    import app.desktop_review.single_step_coordinator as coordinator_module

    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", _REVIEWER)
    trace, captures = [], []
    calls = {"load": 0, "freeze": 0, "factory": 0, "prepare": 0, "close": 0}
    snapshot = object()
    proof = {"cleanup_verified": True} if close_proof is None else close_proof

    def load(_path):
        calls["load"] += 1
        trace.append(("load", get_ident()))
        return snapshot

    def freeze(configuration):
        assert configuration is snapshot
        calls["freeze"] += 1
        trace.append(("freeze", get_ident()))
        if no_service:
            return None
        return ("frozen", configuration)

    class Service:
        def __init__(self, configuration, *, output_root):
            if no_service:
                pytest.fail("a valid configuration without model_service must not construct a service")
            assert configuration == ("frozen", snapshot)

        def prepare(self, cancel):
            calls["prepare"] += 1
            trace.append(("prepare", get_ident()))
            if hold_prepare is not None:
                entered, released = hold_prepare
                entered.set()
                assert released.wait(5), "test did not release managed preparation"
            if behavior == "cancel_after_prepare":
                cancel.set()

        def close(self):
            calls["close"] += 1
            trace.append(("close", get_ident()))
            return dict(proof)

        def verify_request_instance(self, endpoint, model):
            pass

        def begin_request(self, request_id):
            pass

        def complete_request(self, request_id):
            pass

        def cancel_request(self, request_id):
            pass

    def factory(**kwargs):
        calls["factory"] += 1
        trace.append(("factory", get_ident()))
        assert kwargs["vision_configuration"] is snapshot
        if no_service:
            screenshot = _ScreenshotService(kwargs["project_root"] / "capture")
            captures.append(screenshot)
            return _owner(kwargs["project_root"], application=kwargs["application_identity"], screenshot=screenshot)
        owner = _packet_owner(kwargs["project_root"], kwargs["application_identity"], captures, trace)
        original_observe = owner.observe

        def observe(**observe_kwargs):
            if behavior == "late_cancel":
                coordinator.cancel_waiting()
            if behavior == "failure":
                raise RuntimeError("capture failed")
            return original_observe(**observe_kwargs)

        owner.observe = observe
        return owner

    monkeypatch.setattr(coordinator_module, "load_formal_vision_configuration", load)
    monkeypatch.setattr(coordinator_module, "freeze_model_service", freeze)
    monkeypatch.setattr(coordinator_module, "FormalModelService", Service)
    monkeypatch.setattr(factory_module, "create_fresh_learning_observation_owner", factory)
    coordinator = NativeSingleStepCoordinator(
        tmp_path / "review", host.facade, host, thread_initializer=lambda: None,
        thread_finalizer=lambda: None, enable_agent_learning=False,
    )
    monkeypatch.setattr(coordinator, "_check_runtime_environment", lambda: None)
    monkeypatch.setattr(coordinator, "_require_host_ready", lambda **kwargs: None)
    host.enable_learning_runtime(coordinator)
    connection, segment = _open_segment(host)
    return host, coordinator, connection, segment, calls, trace, captures, proof


def _close_managed(coordinator, host):
    try:
        coordinator.shutdown()
    finally:
        host.close()


def test_goal_none_uses_facts_only_owner_and_never_starts_model_service(tmp_path, monkeypatch):
    import app.agent.fresh_learning_factory as factory_module

    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", _REVIEWER)
    connection, segment = _open_segment(host)
    captures = []

    def facts_only_factory(**kwargs):
        assert "vision_configuration" not in kwargs
        captures.append(kwargs)
        return _owner(kwargs["project_root"], application=kwargs["application_identity"], screenshot=_ScreenshotService(kwargs["project_root"] / "capture"))

    monkeypatch.setattr(factory_module, "create_fresh_learning_observation_owner", facts_only_factory)
    try:
        result = host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment, goal=None))
        assert result["action_executed"] is False
        assert len(captures) == 1
        assert host.learning_runtime is None
    finally:
        host.close()


def test_targeted_goal_without_coordinator_fails_closed_before_capture(tmp_path, monkeypatch):
    import app.agent.fresh_learning_factory as factory_module

    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", _REVIEWER)
    connection, segment = _open_segment(host)
    monkeypatch.setattr(factory_module, "create_fresh_learning_observation_owner", lambda **kwargs: pytest.fail("must not capture"))
    try:
        with pytest.raises(AgentLinkError) as denied:
            host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        assert denied.value.code == "learning_runtime_unavailable"
        assert host.facade.list_batches() == []
    finally:
        host.close()


def test_targeted_replay_reuses_committed_packet_without_second_model_or_capture(tmp_path, monkeypatch):
    host, coordinator, connection, segment, calls, trace, captures, _proof = _managed_rig(tmp_path, monkeypatch)
    try:
        request = _request(segment)
        first = host._service.agent_call(connection["token"], "observe_learning_screen", request)
        replay = host._service.agent_call(connection["token"], "observe_learning_screen", request)
        assert replay == first
        assert calls == {"load": 1, "freeze": 1, "factory": 1, "prepare": 1, "close": 1}
        assert len(captures) == 1
        assert [name for name, _thread_id in trace] == ["load", "freeze", "prepare", "factory", "observe", "capture", "close"]
        assert len({thread_id for _name, thread_id in trace}) == 1
        assert coordinator.learning_runtime_state()["phase"] == "idle"
    finally:
        _close_managed(coordinator, host)


def test_targeted_valid_configuration_without_service_reaches_factory_without_constructing_service(tmp_path, monkeypatch):
    host, coordinator, connection, segment, calls, _trace, captures, _proof = _managed_rig(
        tmp_path, monkeypatch, no_service=True,
    )
    try:
        result = host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        assert result["action_executed"] is False
        assert calls["load"] == calls["freeze"] == calls["factory"] == 1
        assert calls["prepare"] == calls["close"] == 0
        assert len(captures) == 1
    finally:
        _close_managed(coordinator, host)


@pytest.mark.parametrize("behavior", ["late_cancel", "cancel_after_prepare", "failure"])
def test_cancel_or_capture_failure_never_stages_managed_observation(tmp_path, monkeypatch, behavior):
    host, coordinator, connection, segment, calls, _trace, _captures, _proof = _managed_rig(tmp_path, monkeypatch, behavior=behavior)
    try:
        with pytest.raises(AgentLinkError) as failed:
            host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        assert failed.value.code == "observation_failed"
        assert host.facade.list_batches() == []
        stored = host.learning_segments.get(connection_id=connection["connection_id"], task_id=connection["task_id"], segment_id=segment["segment_id"])
        assert stored.get("observations", []) == []
        assert calls["close"] == 1
        assert coordinator.learning_runtime_state()["phase"] == "idle"
    finally:
        _close_managed(coordinator, host)


def test_concurrent_targeted_prepare_is_busy_and_does_not_start_second_model(tmp_path, monkeypatch):
    entered, released = Event(), Event()
    host, coordinator, connection, segment, calls, _trace, _captures, _proof = _managed_rig(tmp_path, monkeypatch, hold_prepare=(entered, released))
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(host._service.agent_call, connection["token"], "observe_learning_screen", _request(segment))
            try:
                assert entered.wait(5)
                with pytest.raises(AgentLinkError) as busy:
                    host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment, key="second-capture"))
                assert busy.value.code == "learning_busy"
                with pytest.raises(Exception) as coordinator_busy:
                    coordinator.prepare(asset_id="asset", asset_content_sha256="a" * 64,
                                        target_window_handle=4242, target_process_id=9001)
                assert getattr(coordinator_busy.value, "code", None) == "lifecycle_busy"
            finally:
                released.set()
            running.result(timeout=10)
        assert calls["load"] == calls["freeze"] == calls["prepare"] == calls["factory"] == calls["close"] == 1
    finally:
        released.set()
        _close_managed(coordinator, host)


def test_close_failure_after_capture_retains_owner_blocks_new_work_then_cancel_recovers(tmp_path, monkeypatch):
    proof = {"cleanup_verified": False}
    host, coordinator, connection, segment, calls, _trace, _captures, _proof = _managed_rig(tmp_path, monkeypatch, close_proof=proof)
    try:
        with pytest.raises(AgentLinkError) as failed:
            host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        assert failed.value.code == "observation_failed"
        assert coordinator.learning_runtime_state()["phase"] == "passive_observation_cleanup_required"
        assert coordinator._model_release_pending is True
        with pytest.raises(AgentLinkError) as blocked:
            host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment, key="blocked-capture"))
        assert blocked.value.code == "observation_failed"
        assert calls["factory"] == 1 and host.facade.list_batches() == []
        proof["cleanup_verified"] = True
        assert coordinator.cancel()["cleanup_verified"] is True
        assert coordinator.learning_runtime_state()["phase"] == "idle"
    finally:
        _close_managed(coordinator, host)


def test_capture_and_close_failure_retains_owner_until_cancel_recovers(tmp_path, monkeypatch):
    proof = {"cleanup_verified": False}
    host, coordinator, connection, segment, calls, _trace, _captures, _proof = _managed_rig(tmp_path, monkeypatch, behavior="failure", close_proof=proof)
    try:
        with pytest.raises(AgentLinkError) as failed:
            host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        assert failed.value.code == "observation_failed"
        assert coordinator.learning_runtime_state()["phase"] == "passive_observation_cleanup_required"
        assert coordinator._model_release_pending is True
        assert host.facade.list_batches() == [] and calls["factory"] == 1
        proof["cleanup_verified"] = True
        assert coordinator.cancel()["cleanup_verified"] is True
        assert coordinator.learning_runtime_state()["phase"] == "idle"
    finally:
        _close_managed(coordinator, host)
