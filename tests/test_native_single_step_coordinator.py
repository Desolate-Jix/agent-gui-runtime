from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread, get_ident
from types import SimpleNamespace
import os

import pytest

from app.desktop_review.single_step_coordinator import (
    NativeSingleStepCoordinator,
    NativeSingleStepCoordinatorError,
)
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step import NativeSingleStepError


CONFIRMATION = "grounded-confirmation." + "a" * 64
PREVIEW_SHA = "b" * 64


@dataclass
class _Window:
    handle: int = 41
    title: str = "Editor"
    process_id: int = 7
    process_name: str = "editor.exe"
    is_active: bool = True


class _Windows:
    def __init__(self) -> None:
        self.window = _Window()
        self.calls: list[tuple[str, int]] = []

    def list_visible_windows(self):
        self.calls.append(("list", get_ident()))
        return [vars(self.window)]

    def bind_window_by_handle(self, handle):
        self.calls.append(("bind", get_ident()))
        assert handle == self.window.handle
        return self.window

    def get_bound_window(self):
        self.calls.append(("get", get_ident()))
        return self.window


class _Preview:
    def __init__(self, runtime): self.runtime = runtime
    def to_dict(self):
        return {
            "content_sha256": PREVIEW_SHA,
            "session_id": "session-1",
            "observation_id": "observation-1",
            "intent_id": self.runtime.request.intent_id,
            "workflow": {"workflow_id": "workflow-1", "asset_id": "asset-1"},
            "target_window_handle": 41,
            "target_process_id": 7,
            "review_selection": {"transition_id": "action-1"},
        }


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.phase = "grounded_confirmation_pending"
        self.start_failures = 0
        self.observation = SimpleNamespace(
            session_id="session-1",
            observation_id="observation-1",
            workflow=SimpleNamespace(workflow_id="workflow-1", asset_id="asset-1"),
            available_actions=(SimpleNamespace(
                action_id="action-1", semantic_action="open_apply_flow",
                target_state_id="state-2",
            ), SimpleNamespace(
                action_id="runtime.safe_stop", semantic_action="safe_stop",
                target_state_id=None,
            ), SimpleNamespace(
                action_id="observe-1", semantic_action="observe",
                target_state_id="state-1",
            )),
        )

    def start_session(self):
        self.calls.append(("start", get_ident()))
        if self.start_failures:
            self.start_failures -= 1
            raise RuntimeError("injected partial start failure")
        return self.observation

    def request_grounded_confirmation(self, request):
        self.calls.append(("request", get_ident()))
        self.request = request
        return self._claim()

    def decide_grounded_confirmation(self, **kwargs):
        self.calls.append(("decide", get_ident()))
        self.phase = "grounded_confirmation_approved"
        return self._claim()

    def get_local_grounded_confirmation(self, **kwargs):
        self.calls.append(("get-confirmation", get_ident()))
        return self._claim()

    def get_local_grounded_image(self, **kwargs):
        self.calls.append(("get-image", get_ident()))
        return b"\x89PNG\r\n\x1a\nowned"

    def consume_grounded_confirmation(self, **kwargs):
        self.calls.append(("consume", get_ident()))
        return SimpleNamespace(status="REJECTED", reason_code="grounded_confirmation_stale", confirmation_id=CONFIRMATION)

    def cancel_grounded_review(self, **kwargs):
        self.calls.append(("cancel-grounded", get_ident()))
        grounded = SimpleNamespace(confirmation_id=CONFIRMATION, closed_reason_code="grounded_confirmation_cancelled")
        return SimpleNamespace(phase="grounded_confirmation_closed", observation=self.observation, grounded_confirmation=grounded)

    def cancel_prepared_session(self, **kwargs):
        self.calls.append(("cancel-prepared", get_ident()))

    def _claim(self):
        grounded = SimpleNamespace(
            confirmation_id=CONFIRMATION, preview=_Preview(self), requested_at="2026-09-07T00:00:00Z",
            expires_at="2026-09-07T00:05:00Z", owner_is_current=True,
        )
        intent = SimpleNamespace(intent_id=self.request.intent_id)
        binding = SimpleNamespace(target_window_handle=41)
        return SimpleNamespace(phase=self.phase, observation=self.observation, intent=intent,
                               server_binding=binding, grounded_confirmation=grounded)


class _Client:
    def __init__(self, proxy): self.proxy = proxy
    def execute(self, *, confirmation_id):
        if getattr(self.proxy, "fail_execute", False):
            raise NativeSingleStepError(
                "single_step_result_unknown", "injected", result_unknown=True
            )
        result = self.proxy.consume_grounded_confirmation(confirmation_id=confirmation_id)
        return {"contract_version":"native_single_step_response_v1", "confirmation_id":confirmation_id,
                "kind":"decision", "payload":{"status":result.status,"reason_code":result.reason_code,"confirmation_id":confirmation_id},
                "artifact_is_authorization":False}


class _Host:
    def __init__(self): self.single_step = None; self.proxy = None; self.fail_release = False
    def status(self): return {"contract_version":"native_review_host_v1", "phase":"ready", "base_url":"http://127.0.0.1:1", "staging_only":True}
    def attach_grounded_runtime(self, proxy, *, confirmation_id):
        self.proxy = proxy; self.single_step = _Client(proxy)
        return {"contract_version":"native_review_host_v2", "phase":"ready", "base_url":"http://127.0.0.1:1", "reviewed_single_step_enabled":True}
    def release_grounded_runtime(self, *, confirmation_id, timeout=5.0):
        if self.fail_release: raise NativeSingleStepError("runtime_cleanup_pending", "injected", result_unknown=True)
        self.proxy.cancel_grounded_review(session_id="session-1")
        self.single_step = None; self.proxy = None
    def close(self, *, timeout=5.0):
        if self.proxy is not None: self.release_grounded_runtime(confirmation_id=CONFIRMATION, timeout=timeout)


class _Facade:
    def list_reviewed_assets(self):
        return [{"asset_id":"asset-1", "content_sha256":"c"*64, "application":{"kind":"native"}, "display_name":"Editor"}]


def _coordinator(runtime, windows, host, init, fini):
    def factory(**_kwargs):
        return runtime
    factory.window_manager = windows
    return NativeSingleStepCoordinator(
        ".", _Facade(), host,
        runtime_factory=factory,
        thread_initializer=init,
        thread_finalizer=fini,
        foreground_timeout=0.2,
    )


def test_coordinator_is_lazy_and_all_runtime_calls_use_one_owner_thread():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    lifecycle = []
    coordinator = _coordinator(runtime, windows, host,
                               lambda: lifecycle.append(("init", get_ident())),
                               lambda: lifecycle.append(("fini", get_ident())))
    assert lifecycle == []
    inventory = coordinator.inventory()
    assert inventory["assets"][0]["asset_id"] == "asset-1"
    observed = coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                                   target_window_handle=41, target_process_id=7)
    assert observed == {"phase":"observed", "session_id":"session-1", "actions":[
        {"action_id":"action-1", "semantic_action":"open_apply_flow", "target":"state-2"}
    ]}
    pending = coordinator.request_review(action_id="action-1")
    assert pending["phase"] == "pending_review"
    assert pending["png_bytes"].startswith(b"\x89PNG")
    approved = coordinator.approve(confirmation_id=CONFIRMATION, preview_content_sha256=PREVIEW_SHA)
    assert approved["phase"] == "approved"
    response = coordinator.execute(confirmation_id=CONFIRMATION)
    assert response["kind"] == "decision"
    assert coordinator.cancel() == {"phase":"idle", "cleanup_verified":True}
    coordinator.shutdown()
    owner_ids = {thread_id for _name, thread_id in runtime.calls + windows.calls}
    assert len(owner_ids) == 1
    assert lifecycle[0] == ("init", next(iter(owner_ids)))
    assert lifecycle[-1] == ("fini", next(iter(owner_ids)))


def test_foreground_wait_is_passively_cancelled_without_starting_runtime():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    windows.window.is_active = False
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    outcome = []
    thread = Thread(target=lambda: outcome.append(pytest.raises(NativeSingleStepCoordinatorError,
        coordinator.prepare, asset_id="asset-1", asset_content_sha256="c"*64,
        target_window_handle=41, target_process_id=7)))
    thread.start()
    Event().wait(0.03)
    coordinator.cancel_waiting()
    thread.join(2)
    assert not thread.is_alive()
    assert outcome[0].value.code == "foreground_wait_cancelled"
    assert runtime.calls == []
    assert all(name in {"bind", "get"} for name, _tid in windows.calls)
    coordinator.shutdown()


def test_wrong_preview_hash_does_not_approve():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                        target_window_handle=41, target_process_id=7)
    coordinator.request_review(action_id="action-1")
    with pytest.raises(NativeSingleStepCoordinatorError) as caught:
        coordinator.approve(confirmation_id=CONFIRMATION, preview_content_sha256="d"*64)
    assert caught.value.code == "preview_identity_mismatch"
    assert not any(name == "decide" for name, _tid in runtime.calls)
    coordinator.cancel()
    coordinator.shutdown()


def test_review_rejects_a_self_consistent_but_different_window_identity():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    try:
        coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                            target_window_handle=41, target_process_id=7)
        original = runtime._claim
        def wrong_claim():
            claim = original()
            payload = claim.grounded_confirmation.preview.to_dict()
            payload["target_process_id"] = 999
            claim.grounded_confirmation.preview = SimpleNamespace(to_dict=lambda: payload)
            return claim
        runtime._claim = wrong_claim
        with pytest.raises(NativeSingleStepCoordinatorError) as caught:
            coordinator.request_review(action_id="action-1")
        assert caught.value.code == "review_snapshot_invalid"
        # 发布后的 owner 必须仍可由显式取消回收。
        coordinator.cancel()
    finally:
        if coordinator._phase != "idle":
            runtime._claim = original
            coordinator.cancel()
        coordinator.shutdown()


def test_actual_owned_http_executes_through_the_same_runtime_owner(tmp_path):
    runtime, windows = _Runtime(), _Windows()
    host = DesktopReviewHost(
        tmp_path / "inbox.json", tmp_path / "review", "reviewer-token-123"
    )
    host.start()
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    try:
        coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                            target_window_handle=41, target_process_id=7)
        pending = coordinator.request_review(action_id="action-1")
        coordinator.approve(
            confirmation_id=pending["confirmation_id"],
            preview_content_sha256=pending["preview"]["content_sha256"],
        )
        response = coordinator.execute(confirmation_id=CONFIRMATION)
        assert response["contract_version"] == "native_single_step_response_v1"
        assert response["kind"] == "decision"
        assert coordinator.cancel()["cleanup_verified"] is True
        owner_ids = {thread_id for _name, thread_id in runtime.calls}
        assert len(owner_ids) == 1
    finally:
        coordinator.shutdown()


def test_inventory_normalizes_optional_labels_and_omits_unbindable_windows():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    def listed():
        return [
            {"handle": 41, "title": None, "process_id": 7, "process_name": None},
            {"handle": 42, "title": "No PID", "process_id": None, "process_name": None},
            {"handle": True, "title": "Bool", "process_id": 8, "process_name": "bad"},
        ]
    windows.list_visible_windows = listed
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    try:
        assert coordinator.inventory()["windows"] == [{
            "handle": 41, "title": "", "process_id": 7, "process_name": "",
        }]
    finally:
        coordinator.shutdown()


def test_every_post_prepare_operation_passively_requires_exact_foreground():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    try:
        coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                            target_window_handle=41, target_process_id=7)
        windows.window.is_active = False
        failures = []
        thread = Thread(target=lambda: _capture(failures, lambda: coordinator.request_review(action_id="action-1")))
        thread.start(); Event().wait(0.03); coordinator.cancel_waiting(); thread.join(2)
        assert failures[0].code == "foreground_wait_cancelled"
        assert not any(name == "request" for name, _tid in runtime.calls)
        windows.window.is_active = True
        pending = coordinator.request_review(action_id="action-1")

        windows.window.is_active = False; failures.clear()
        thread = Thread(target=lambda: _capture(failures, lambda: coordinator.approve(
            confirmation_id=CONFIRMATION, preview_content_sha256=PREVIEW_SHA)))
        thread.start(); Event().wait(0.03); coordinator.cancel_waiting(); thread.join(2)
        assert failures[0].code == "foreground_wait_cancelled"
        assert not any(name == "decide" for name, _tid in runtime.calls)
        windows.window.is_active = True
        coordinator.approve(confirmation_id=CONFIRMATION, preview_content_sha256=PREVIEW_SHA)

        windows.window.is_active = False; failures.clear()
        thread = Thread(target=lambda: _capture(failures, lambda: coordinator.execute(confirmation_id=CONFIRMATION)))
        thread.start(); Event().wait(0.03); coordinator.cancel_waiting(); thread.join(2)
        assert failures[0].code == "foreground_wait_cancelled"
        assert not any(name == "consume" for name, _tid in runtime.calls)
        windows.window.is_active = True
        coordinator.execute(confirmation_id=CONFIRMATION)
        coordinator.cancel()
    finally:
        if coordinator._phase != "idle": coordinator.cancel()
        coordinator.shutdown()


def test_legacy_partial_start_without_cleanup_proof_cannot_restart_same_selection():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    runtime.start_failures = 1
    factory_calls = []
    def factory(**_kwargs): factory_calls.append(1); return runtime
    factory.window_manager = windows
    coordinator = NativeSingleStepCoordinator(
        ".", _Facade(), host, runtime_factory=factory,
        thread_initializer=lambda: None, thread_finalizer=lambda: None,
    )
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as first:
            coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                                target_window_handle=41, target_process_id=7)
        assert first.value.code == "runtime_prepare_failed"
        assert first.value.result_unknown is True
        with pytest.raises(NativeSingleStepCoordinatorError) as wrong:
            coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                                target_window_handle=42, target_process_id=7)
        assert wrong.value.code == "runtime_cleanup_pending"
        with pytest.raises(NativeSingleStepCoordinatorError) as unverified:
            coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                                target_window_handle=41, target_process_id=7)
        assert unverified.value.code == "runtime_cleanup_pending"
        assert unverified.value.retry_preparation is False
        assert factory_calls == [1]
        assert [name for name, _thread in runtime.calls].count("start") == 1
        assert coordinator._runtime is runtime
        with pytest.raises(NativeSingleStepCoordinatorError):
            coordinator.shutdown()
        assert coordinator._runtime is runtime
        assert host.status()["phase"] == "ready"
    finally:
        # 仅结束没有真实资源的 legacy 测试替身线程，不作为 Runtime 清理证明。
        coordinator._owner.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows COM contract")
def test_default_owner_initializes_a_real_mta_and_finalizes():
    from ctypes import OleDLL, byref, c_int
    from app.desktop_review.single_step_runtime_owner import SerialRuntimeOwner

    owner = SerialRuntimeOwner()
    apartment, qualifier = c_int(-1), c_int(-1)
    try:
        result = owner.call(
            lambda: (
                OleDLL("ole32").CoGetApartmentType(byref(apartment), byref(qualifier)),
                apartment.value,
                qualifier.value,
            )
        )
        assert result == (0, 1, 0)
    finally:
        owner.close()


def test_owner_proxy_call_from_owner_thread_is_inline_not_self_queued():
    from app.desktop_review.single_step_runtime_owner import SerialRuntimeOwner

    owner = SerialRuntimeOwner(initializer=lambda: None, finalizer=lambda: None)
    try:
        assert owner.call(lambda: owner.call(get_ident)) == owner.thread_id
    finally:
        owner.close()


def test_unknown_http_result_and_cleanup_failure_both_retain_exact_owner():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    try:
        coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                            target_window_handle=41, target_process_id=7)
        pending = coordinator.request_review(action_id="action-1")
        coordinator.approve(confirmation_id=CONFIRMATION, preview_content_sha256=PREVIEW_SHA)
        host.proxy.fail_execute = True
        with pytest.raises(NativeSingleStepCoordinatorError) as unknown:
            coordinator.execute(confirmation_id=CONFIRMATION)
        assert unknown.value.result_unknown is True
        with pytest.raises(NativeSingleStepCoordinatorError) as invalid_phase:
            coordinator.prepare(asset_id="asset-1", asset_content_sha256="c"*64,
                                target_window_handle=41, target_process_id=7)
        assert invalid_phase.value.code == "invalid_phase"
        host.fail_release = True
        with pytest.raises(NativeSingleStepCoordinatorError) as cleanup:
            coordinator.cancel()
        assert cleanup.value.code == "runtime_cleanup_pending"
        assert coordinator._runtime is runtime and coordinator._attached is True
        host.fail_release = False
        coordinator.cancel()
    finally:
        if coordinator._phase != "idle":
            host.fail_release = False
            coordinator.cancel()
        coordinator.shutdown()


def _capture(failures, operation):
    try: operation()
    except BaseException as error: failures.append(error)
