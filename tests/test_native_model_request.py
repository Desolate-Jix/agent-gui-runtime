"""正式拥有者、真实 VISTA 两阶段客户端与隔离 HTTP 服务的接线。"""

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from tests.test_formal_model_service import _configuration, backend
from tests.test_native_single_step_coordinator import _Facade, _Host, _Windows


@contextmanager
def _server(*, hang=False):
    state = SimpleNamespace(requests=[], received=Event(), release=Event(), on_request=None,
                            response_content="[500, 500]")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            state.received.set()
            if state.on_request is not None:
                state.on_request()
            if hang:
                state.release.wait(8)
                return
            body = json.dumps({"choices": [{"message": {"content": state.response_content}}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    state.port = server.server_port
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def _real_chain(tmp_path, monkeypatch, state):
    from app.agent.live_controller import ServerWorkflowBinding
    from app.agent.runtime_session_selection import RuntimeSessionSelection
    from app.api import vision
    from app.core import screenshot
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from modules.ocr.contracts import OCRResult

    snapshot, profile_path = _configuration(tmp_path, readiness_timeout_seconds=3)
    config = snapshot.to_dict()
    config["vision"]["local"].update(endpoint=state.endpoint, runtime="transformers", output_contract="vista_point_v1")
    snapshot.path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile.update(endpoint=state.endpoint, port=state.port, runtime="transformers")
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    windows = _Windows()
    windows.window.rect = SimpleNamespace(left=10, top=10, right=50, bottom=30)
    co = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), vision_config_path=snapshot.path,
                                    thread_initializer=lambda: None, thread_finalizer=lambda: None)
    co._window_manager = windows
    monkeypatch.setattr(co, "_check_runtime_environment", lambda: None)
    monkeypatch.setattr(screenshot, "window_manager", windows)
    monkeypatch.setattr(screenshot, "MSS_BACKEND_AVAILABLE", True)

    class Capture:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def grab(self, monitor):
            size = monitor["width"], monitor["height"]
            return SimpleNamespace(size=size, rgb=bytes((3, 5, 7)) * (size[0] * size[1]))

    monkeypatch.setattr(screenshot, "mss", Capture)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=path, matches=[]))
    selection = RuntimeSessionSelection("asset-request", "a" * 64, 41, 7)

    def build():
        callsite = co._create_runtime_on_owner(selection)
        return callsite._controller_factory(ServerWorkflowBinding(workflow_id="request-flow", asset_id="asset-request",
            application_identity_key="native:editor.exe:notepad", target_window_handle=41))

    controller = co._owner.call(build)
    adapter = controller._observation_source

    def capture_visibility(*, bound, rect):
        allowed = bound is windows.window and rect == {
            "left": 10,
            "top": 10,
            "width": 40,
            "height": 20,
        }
        return {
            "allowed": allowed,
            "reason": "capture_window_visible" if allowed else "capture_binding_changed",
        }

    monkeypatch.setattr(
        windows,
        "validate_bound_capture_visibility",
        capture_visibility,
        raising=False,
    )
    monkeypatch.setattr(adapter._screenshot_service, "_window_manager", windows)

    def recognize():
        capture = adapter._screenshot_service.capture_window(focus_window=False)
        return adapter._recognition_runner(image_path=capture["image_path"], goal="synthetic target", provider_mode="local",
            uia_snapshot={"status": "ok", "window": {"handle": 41, "process_id": 7}, "controls": []})

    return co, recognize


def _close_chain(co):
    # 此测试只构造原控制器并识别，不声称已经创建完整审核会话。
    co._owner.call(co._model_service.close)
    co._model_service = None
    co._factory_outcome_unknown = False
    co._phase = "idle"
    co.shutdown()


def test_real_factory_vista_two_phases_have_distinct_scoped_request_ids(tmp_path, monkeypatch, backend):
    from app.api import vision

    original_recognition_plan = vision.recognition_plan

    def explicit_refinement(request):
        # 默认已为单阶段；此用例显式请求两阶段，继续核验各阶段的独立请求 ID。
        request = request.model_copy(update={"metadata": {
            **request.metadata, "vista_direct_grounding": {"refine": True},
        }})
        return original_recognition_plan(request)

    monkeypatch.setattr(vision, "recognition_plan", explicit_refinement)
    with _server() as state:
        co, recognize = _real_chain(tmp_path, monkeypatch, state)
        try:
            result = co._owner.call(recognize)
            assert result["execution_path"]["action_executed"] is False
            assert Path(result["image_path"]).is_relative_to(tmp_path / "runtime-output")
            assert len(state.requests) == 2
            ids = [request.get("request_id") for request in state.requests]
            assert all(ids) and len(set(ids)) == 2
        finally:
            _close_chain(co)


@pytest.mark.parametrize("replace_at", ["before", "during"])
def test_real_request_rejects_replaced_model_without_fallback(tmp_path, monkeypatch, backend, replace_at):
    with _server() as state:
        co, recognize = _real_chain(tmp_path, monkeypatch, state)
        try:
            if replace_at == "before":
                backend.owned_listeners = False
            else:
                state.on_request = lambda: setattr(backend, "owned_listeners", False)
            with pytest.raises(Exception) as error:
                co._owner.call(recognize)
            assert error.value.code == "model_service_owner_mismatch"
            assert len(state.requests) == (0 if replace_at == "before" else 1)
            assert backend.cleanups == []
        finally:
            _close_chain(co)


def test_stop_request_unblocks_actual_vista_and_does_not_retry_or_accept_result(tmp_path, monkeypatch, backend):
    with _server(hang=True) as state:
        co, recognize = _real_chain(tmp_path, monkeypatch, state)
        outcome = []

        def run():
            try:
                outcome.append(co._owner.call(recognize))
            except Exception as error:
                outcome.append(error)

        thread = Thread(target=run, daemon=True)
        thread.start()
        try:
            assert state.received.wait(3)
            co.cancel_waiting()
            thread.join(timeout=2)
            assert not thread.is_alive(), "cancel must release the synchronous owner request"
            assert len(outcome) == 1 and getattr(outcome[0], "code", None) == "model_request_cancelled"
            assert len(state.requests) == 1
            assert backend.cleanups == []
        finally:
            state.release.set()
            thread.join(timeout=8)
            _close_chain(co)


def test_wrapped_cancellation_keeps_cleanup_flags_and_reports_original_reason():
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from app.vision.request_control import ModelRequestContext

    cancelled = Event()
    cancelled.set()
    try:
        ModelRequestContext(cancelled).check_cancelled()
    except Exception as cause:
        wrapper = RuntimeError("preparation cleanup retained")
        wrapper.__cause__ = cause
    mapped = NativeSingleStepCoordinator._mapped(wrapper, "runtime_prepare_failed", "private",
                                                 force_unknown=True, retry_preparation=True)
    assert mapped.code == "model_request_cancelled"
    assert mapped.result_unknown and mapped.retry_preparation
    assert "服务端计算尚未确认停止" in mapped.message


def test_cancel_button_only_announces_request_pending_until_owner_returns(tmp_path, monkeypatch):
    from app.agent.runtime_session_selection import RuntimeSessionSelection
    from app.desktop_review.single_step_dialog import _JobFailure, SingleStepDialog
    from app.desktop_review.window import ensure_application
    from tests.test_native_model_service import _coordinator

    application = ensure_application()
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    dialog = SingleStepDialog(co)
    selection = RuntimeSessionSelection("asset-request", "a" * 64, 41, 7)
    co._runtime = object()
    co._selection = selection
    co._phase = "prepare_recovery_required"
    co._busy = True
    dialog._selection = selection
    dialog._phase = "prepare_recovery_required"
    dialog._has_owner = True
    dialog._operation = "prepare"
    job = object()
    dialog._jobs.add(job)
    dialog._update_controls()
    try:
        assert dialog.stop_wait_button.isEnabled()
        dialog._stop_wait()

        assert co._cancel_wait.is_set()
        assert co._runtime is not None
        assert dialog._phase == "prepare_recovery_required"
        assert dialog._has_owner
        assert "窗口准备调用返回" in dialog.status_label.text()

        dialog._job_result(
            dialog._request_id,
            _JobFailure("model_request_cancelled", True, False, False),
        )
        dialog._job_finished(job)

        assert dialog._phase == "recovery_required"
        assert "服务端计算未确认停止" in dialog.status_label.text()
    finally:
        co._end()
        co._clear()
        co._cancel_wait.clear()
        dialog.deleteLater()
        co.shutdown()
