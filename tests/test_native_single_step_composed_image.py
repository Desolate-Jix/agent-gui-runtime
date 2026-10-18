"""实际 cache PNG、callsite、线程代理与 loopback HTTP 的离线组合验收。"""
from hashlib import sha256
from pathlib import Path
from threading import Event, Thread, get_ident

import pytest

from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from tests.test_native_grounded_image_material import grounded_image_runtime
from tests.test_live_runtime_composition_w3b import _WindowManager, _bound


@pytest.mark.parametrize("stable_pixels", [True, False])
def test_actual_cached_preview_approval_and_http_consume_share_one_runtime(tmp_path, grounded_image_runtime, monkeypatch, stable_pixels):
    runtime = grounded_image_runtime
    # PNG 只读测试的 12 帧不足以覆盖执行后捕获；组合测试提供完整观测序列。
    runtime.evidence._window_manager = _WindowManager(*[_bound() for _ in range(64)])
    if stable_pixels:
        original_capture = runtime.screenshot.capture_window
        first_frame = []
        def stable_capture(**kwargs):
            result = original_capture(**kwargs)
            path = Path(result["image_path"])
            if not first_frame:
                first_frame.append(path.read_bytes())
            # 对照组只固定合成像素，保留真实新 capture ID 和后续全部验证。
            path.write_bytes(first_frame[0])
            return result
        monkeypatch.setattr(runtime.screenshot, "capture_window", stable_capture)
    original_windows = runtime.service._window_manager
    calls = []

    class Windows:
        def list_visible_windows(self):
            return [{"handle": 4242, "process_id": 9001, "title": "Synthetic target", "process_name": "fixture.exe"}]

        def bind_window_by_handle(self, handle):
            assert handle == 4242
            return original_windows.get_bound_window()

        def get_bound_window(self):
            return original_windows.get_bound_window()

    windows = Windows()

    def factory(*, project_root, selection, window_manager):
        calls.append(get_ident())
        assert project_root == tmp_path.resolve()
        assert selection == runtime.service._selection
        assert window_manager is windows
        return runtime.service

    factory.window_manager = windows
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path, "synthetic-composed-reviewer", port=0)
    coordinator = NativeSingleStepCoordinator(tmp_path, host.facade, host, runtime_factory=factory,
                                              thread_initializer=lambda: None, thread_finalizer=lambda: None)
    mapped_errors = []
    original_mapping = coordinator._mapped
    def tracked_mapping(error, *args, **kwargs):
        mapped_errors.append((type(error).__name__, str(error), getattr(error, "code", None)))
        return original_mapping(error, *args, **kwargs)
    monkeypatch.setattr(coordinator, "_mapped", tracked_mapping)
    try:
        host.start()
        inventory = coordinator.inventory()
        asset = inventory["assets"][0]
        observed = coordinator.prepare(asset_id=asset["asset_id"], asset_content_sha256=asset["content_sha256"],
                                       target_window_handle=4242, target_process_id=9001)
        assert len(observed["actions"]) == 1
        assert observed["actions"][0]["semantic_action"] == "open_apply_flow"
        pending = coordinator.request_review(action_id=observed["actions"][0]["action_id"])
        capture = pending["preview"]["grounding_preview"]["capture_lineage"]
        assert sha256(pending["png_bytes"]).hexdigest() == capture["screenshot_sha256"]
        assert pending["png_bytes"] == runtime.screenshot.paths[-1].read_bytes()
        assert runtime.backends[0].attempt_count == 0
        approved = coordinator.approve(confirmation_id=pending["confirmation_id"],
                                       preview_content_sha256=pending["preview"]["content_sha256"])
        assert approved == {**pending, "phase": "approved"}
        assert runtime.backends[0].attempt_count == 0
        response = coordinator.execute(confirmation_id=pending["confirmation_id"])
        assert response["contract_version"] == "native_single_step_response_v1"
        assert response["confirmation_id"] == pending["confirmation_id"]
        assert response["artifact_is_authorization"] is False
        if stable_pixels:
            assert response["kind"] == "receipt", str(response["payload"])
            assert runtime.backends[0].attempt_count == 1
            assert any(ref.startswith("grounded-consume:") for ref in response["payload"]["evidence"]["trace_refs"])
        else:
            assert response["kind"] == "decision"
            assert response["payload"]["status"] == "REJECTED"
            assert response["payload"]["reason_code"] == "grounded_confirmation_stale"
            assert runtime.backends[0].attempt_count == 0
        assert coordinator.cancel() == {"phase": "idle", "cleanup_verified": True}
        assert host.status()["phase"] == "ready"
        assert host.status()["staging_only"] is True
        assert calls == [coordinator._owner.thread_id]
        assert get_ident() != calls[0]
        assert runtime.backends[0].attempt_count == int(stable_pixels)
    finally:
        try:
            coordinator.shutdown()
        except Exception as error:
            # 仅释放失败测试的空闲线程，仍明确判定生产清理失败。
            coordinator._owner.close()
            raise AssertionError((getattr(error, "code", None), mapped_errors)) from error


def test_closed_owner_rejects_recycled_numeric_thread_identity(monkeypatch):
    from app.desktop_review import single_step_runtime_owner as module
    owner = module.SerialRuntimeOwner(initializer=lambda: None, finalizer=lambda: None)
    saved_id = owner.call(get_ident)
    owner.close()
    calls = []
    monkeypatch.setattr(module, "get_ident", lambda: saved_id)
    with pytest.raises(module.RuntimeOwnerError):
        owner.call(lambda: calls.append("wrong-thread"))
    assert calls == []


def test_every_owner_close_waits_until_finalizer_really_finishes():
    from app.desktop_review.single_step_runtime_owner import SerialRuntimeOwner
    entered, release, second_finished = Event(), Event(), Event()
    def finalizer():
        entered.set()
        assert release.wait(5)
    owner = SerialRuntimeOwner(initializer=lambda: None, finalizer=finalizer)
    owner.call(lambda: None)
    first = Thread(target=owner.close)
    second = Thread(target=lambda: (owner.close(), second_finished.set()))
    first.start()
    assert entered.wait(2)
    second.start()
    try:
        assert not second_finished.wait(.05), "close returned while owner finalizer was still active"
    finally:
        release.set()
        first.join(2)
        second.join(2)
        assert not first.is_alive() and not second.is_alive()


def test_owner_thread_cannot_mark_itself_closed_before_join():
    from app.desktop_review.single_step_runtime_owner import RuntimeOwnerError, SerialRuntimeOwner
    owner = SerialRuntimeOwner(initializer=lambda: None, finalizer=lambda: None)
    try:
        with pytest.raises(RuntimeOwnerError):
            owner.call(owner.close)
        assert owner.call(lambda: "still-owned") == "still-owned"
    finally:
        owner.close()
