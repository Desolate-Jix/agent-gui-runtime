from __future__ import annotations

import json
from threading import Thread

import pytest

from tests.test_native_model_request import _server
from tests.test_native_single_step_coordinator import _Windows
from tests.test_desktop_exact_review import _new_runtime, _complete, _record_dir, _load, _TOKEN
from tests.test_native_text_saved_workflow import _SYNTHETIC_NATIVE_BINDING
from copy import deepcopy
from app.agent.reviewed_workflow_asset import content_sha256
from tests.test_formal_model_service import _configuration
from tests.test_formal_model_service import backend


def _fresh_coordinator(tmp_path, monkeypatch, state, *, grounded_scene=False):
    from types import SimpleNamespace
    from app.api import vision
    from app.core import screenshot
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from app.desktop_review.host import DesktopReviewHost
    from modules.ocr.contracts import OCRResult
    from modules.ocr.contracts import OCRTextMatch, OCRBoundingBox
    from PIL import Image, ImageDraw, ImageFont
    snapshot, profile_path = _configuration(tmp_path, readiness_timeout_seconds=3)
    config = snapshot.to_dict(); config["vision"]["local"].update(endpoint=state.endpoint, runtime="transformers", output_contract="vista_point_v1")
    snapshot.path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    profile = json.loads(profile_path.read_text(encoding="utf-8")); profile.update(endpoint=state.endpoint, port=state.port, runtime="transformers")
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    windows = _Windows(); windows.window.rect = SimpleNamespace(left=10, top=10, right=50, bottom=30)
    _store, inbox, facade, saved = _new_runtime(tmp_path)
    compiled = _complete(facade, facade.prepare_exact_review("task", "exact-review-batch", saved["revision"], deepcopy(_SYNTHETIC_NATIVE_BINDING)))
    asset = _load(_record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json")["asset"]
    facade.publish_exact_review(compiled["compile_receipt_id"])
    facade.close()
    _store.close()
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "root", _TOKEN)
    host.start()
    co = NativeSingleStepCoordinator(tmp_path / "root", host.facade, host, vision_config_path=snapshot.path, thread_initializer=lambda: None, thread_finalizer=lambda: None)
    co._window_manager = windows
    monkeypatch.setattr(co, "_check_runtime_environment", lambda: None)
    import app.core.window_manager as window_module
    monkeypatch.setattr(window_module, "window_manager", windows)
    monkeypatch.setattr(screenshot, "window_manager", windows); monkeypatch.setattr(screenshot, "MSS_BACKEND_AVAILABLE", True)
    class Capture:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def grab(self, monitor):
            size = monitor["width"], monitor["height"]
            image = Image.new("RGB", size, (3, 5, 7))
            if grounded_scene:
                draw = ImageDraw.Draw(image)
                font = ImageFont.load_default(size=8)
                draw.text((2, 0), "list", fill="white", font=font)
                draw.text((2, 10), "Open", fill="white", font=font)
            return SimpleNamespace(size=size, rgb=image.tobytes())
    monkeypatch.setattr(screenshot, "mss", Capture)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=path, matches=[]))
    if grounded_scene:
        def scan(path):
            with Image.open(path) as image:
                assert image.size == (40, 20)
            return OCRResult(image_path=path, matches=[
                OCRTextMatch(text="list", score=0.99, bbox=OCRBoundingBox(x=2, y=0, width=18, height=9)),
                OCRTextMatch(text="Open", score=0.99, bbox=OCRBoundingBox(x=2, y=10, width=22, height=10)),
            ])
        monkeypatch.setattr(vision.ocr_service, "scan_image", scan)
        def model_reply():
            prompt = json.dumps(state.requests[-1]["messages"])
            state.response_content = "[250, 250]" if "Click list" in prompt else "[250, 750]"
        state.on_request = model_reply
    from app.agent.native_identity import WindowsNativeIdentityReader
    from tests.test_native_current_evidence import _NativeIdentityReader
    from app.operation.screen_reading.uia_provider import uia_provider
    from tests.test_live_runtime_composition_w3b import _UIAProvider
    identity = _NativeIdentityReader(process_id=7, executable_path=asset["application"]["executable_path"])
    monkeypatch.setattr(WindowsNativeIdentityReader, "read_identity", lambda self, handle: identity.read_identity(handle))
    uia = _UIAProvider(handle=41, process_id=7)
    def snapshot_window(bound, **_kwargs):
        result = uia.snapshot_window(bound)
        result["window"]["bbox"] = {"x": 10, "y": 10, "w": 40, "h": 20}
        return result
    monkeypatch.setattr(uia_provider, "snapshot_window", snapshot_window)
    return co, asset


@pytest.mark.parametrize("cancel", [False, True])
def test_native_production_session_uses_saved_asset_model_and_real_cleanup(tmp_path, monkeypatch, backend, cancel):
    """真实发布/准备/模型观察/取消链；合成结果不代表实际模型准确率。"""
    with _server(hang=cancel) as state:
        coordinator, asset = _fresh_coordinator(tmp_path, monkeypatch, state)
        outcomes = []
        def prepare():
            outcomes.append(_capture(lambda: coordinator.prepare(
                asset_id=asset["asset_id"], asset_content_sha256=content_sha256(asset),
                target_window_handle=41, target_process_id=7)))
        worker = Thread(target=prepare, daemon=True)
        try:
            worker.start()
            assert state.received.wait(3)
            if cancel:
                coordinator.cancel_waiting()
            worker.join(timeout=4)
            assert not worker.is_alive()
            outcome = outcomes[0]
            assert state.requests
            assert len({item["request_id"] for item in state.requests}) == len(state.requests)
            if cancel:
                assert outcome.code == "model_request_cancelled"
                assert coordinator._phase == "prepare_recovery_required"
                assert coordinator._runtime is not None
                assert coordinator._model_service._pending_request_id == state.requests[0]["request_id"]
                assert len(state.requests) == 1
            else:
                if isinstance(outcome, Exception):
                    raise outcome
                assert outcome["phase"] == "observed"
                assert outcome["session_id"] == coordinator._observation.session_id
                assert coordinator._observation.workflow.asset_content_sha256 == content_sha256(asset)
                assert outcome["actions"] == []
                assert coordinator._model_service._pending_request_id is None
                # 只有模型点而无独立文字证据时，原生会话应安全停止。
                assert coordinator._runtime._controller is None
            assert coordinator._confirmation_id is None and backend.cleanups == []
            assert coordinator.cancel()["cleanup_verified"] is True
            assert coordinator._runtime is None and coordinator._model_service is None
            assert backend.cleanups
        finally:
            state.release.set()
            worker.join(timeout=8)
            coordinator.shutdown()


def _capture(fn):
    try: return fn()
    except Exception as exc: return exc



