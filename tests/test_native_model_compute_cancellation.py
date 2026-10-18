"""原生拥有者经过真实推理/取消/健康 HTTP 链，不加载模型或输入外部软件。"""

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from tests.test_formal_model_service import backend
from tests.test_native_model_request import _close_chain


@contextmanager
def _compute_server():
    state = SimpleNamespace(active=None, received=Event(), release=Event(), requests=[], cancels=[], healthy=True,
                            response=None, response_status=200)

    class Handler(BaseHTTPRequestHandler):
        def send(self, payload, status=200):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            if self.path == "/v1/health" and state.healthy:
                self.send({"status": "busy" if state.active else "ok", "model": "fixture-model", "active_request": state.active})
            elif self.path == "/v1/models" and state.healthy:
                self.send({"data": [{"id": "fixture-model"}]})
            else:
                self.send({"error": "synthetic health unavailable"}, 503)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            rid = request["request_id"]
            if self.path == "/v1/cancel":
                state.cancels.append(rid)
                active_id = (state.active or {}).get("request_id")
                status = "request_not_active" if active_id is None else (
                    "cancellation_acknowledged" if active_id == rid else "request_id_mismatch")
                if status == "cancellation_acknowledged":
                    state.release.set()
                self.send({"contract_version": "model_request_cancel_response_v1", "status": status,
                           "request_id": rid, "request_fenced": True})
                return
            state.requests.append(rid)
            state.active = {"request_id": rid}
            state.received.set()
            state.release.wait(8)
            state.active = None
            self.send(state.response if state.response is not None else {"choices": [{"message": {"content": "[500, 500]"}}]},
                      state.response_status)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.port = server.server_port
    state.origin = f"http://127.0.0.1:{state.port}"
    state.endpoint = state.origin + "/v1/chat/completions"
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("healthy", [True, False])
def test_formal_cancel_only_confirms_compute_with_real_matching_control_and_health(tmp_path, monkeypatch, backend, healthy):
    from app.core import model_server
    from tests import test_native_model_request as chain

    with _compute_server() as server:
        original_configuration = chain._configuration

        def configuration(*args, **kwargs):
            snapshot, path = original_configuration(*args, **kwargs)
            profile = json.loads(path.read_text(encoding="utf-8"))
            profile.update(request_cancel_supported=True, request_cancel_endpoint=server.origin + "/v1/cancel")
            path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            return snapshot, path

        monkeypatch.setattr(chain, "_configuration", configuration)
        backend.statuses = ["running"]
        co, recognize = chain._real_chain(tmp_path, monkeypatch, server)
        monkeypatch.setattr(model_server, "check_model_server", backend.original_check)
        server.healthy = healthy
        outcomes = []

        def run():
            try:
                outcomes.append(co._owner.call(recognize))
            except Exception as error:
                outcomes.append(error)

        worker = Thread(target=run, daemon=True)
        worker.start()
        try:
            assert server.received.wait(3)
            co.cancel_waiting()
            worker.join(timeout=4)
            assert not worker.is_alive()
            assert len(server.requests) == len(server.cancels) == 1
            assert server.requests == server.cancels
            error = outcomes[0]
            assert error.code == "model_request_cancelled"
            assert error.computation_stopped is healthy
            assert (co._model_service._pending_request_id is None) is healthy
            assert co._cancel_wait.is_set()
            assert backend.cleanups == []
        finally:
            server.healthy = True
            server.release.set()
            worker.join(timeout=8)
            _close_chain(co)


def test_server_proof_survives_wrapped_error_and_qt_job_without_clearing_recovery(tmp_path, monkeypatch):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from app.desktop_review.single_step_dialog import SingleStepDialog, _safe_operation
    from app.desktop_review.window import ensure_application
    from app.vision.request_control import ModelRequestError
    from tests.test_native_model_service import _coordinator

    application = ensure_application()
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    dialog = SingleStepDialog(co)
    try:
        cause = ModelRequestError("model_request_cancelled")
        cause.computation_stopped = True
        wrapper = RuntimeError("private cleanup details")
        wrapper.__cause__ = cause
        mapped = NativeSingleStepCoordinator._mapped(wrapper, "runtime_prepare_failed", "private",
                                                     force_unknown=True, retry_preparation=True)
        assert mapped.computation_stopped is True
        assert mapped.result_unknown and mapped.retry_preparation

        def operation():
            raise mapped

        result = _safe_operation(operation)
        assert result.computation_stopped is True
        assert result.result_unknown and result.retry_preparation
        dialog._job_result(dialog._request_id, result)
        assert "已确认本次请求不再活动" in dialog.status_label.text()
        assert "未自动继续" in dialog.status_label.text()
        assert "private" not in dialog.status_label.text()
    finally:
        dialog.deleteLater()
        co.shutdown()


@pytest.mark.parametrize(("status", "body", "code"), [
    (200, b"not-json", "model_response_invalid"), (200, b"\xff", "model_response_invalid"),
    (500, b"\xff", "model_response_invalid"), (400, b'{"error":"bad input"}', "model_response_http_error"),
])
def test_complete_invalid_response_is_rejected_without_pending_request_or_retry(tmp_path, monkeypatch, backend, status, body, code):
    from app.vision.request_control import ModelRequestError
    from tests.test_native_model_request import _real_chain

    with _compute_server() as server:
        backend.statuses = ["running"]
        server.response = body
        server.response_status = status
        server.release.set()
        co, recognize = _real_chain(tmp_path, monkeypatch, server)
        try:
            with pytest.raises(ModelRequestError) as failure:
                co._owner.call(recognize)
            assert failure.value.code == code
            assert len(server.requests) == 1
            assert co._model_service._pending_request_id is None
            assert failure.value.computation_stopped is False
        finally:
            # 替身服务无取消端点；失败红测也须回收测试线程，不改变生产清理逻辑。
            if co._model_service._pending_request_id is not None:
                co._owner.call(lambda: co._model_service.complete_request(server.requests[0]))
            _close_chain(co)
