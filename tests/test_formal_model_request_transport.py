from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from PIL import Image

from app.vision.local_provider import LocalVisionProvider
from app.vision.request_control import (
    ModelRequestContext,
    ModelRequestError,
    current_model_request,
    pinned_model_request,
    read_cancellable_response,
)
from app.vision.schemas import VisionAnalyzeRequest


@contextmanager
def server(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_model_request_error_accepts_code_as_its_first_argument():
    error = ModelRequestError("model_request_cancelled")
    assert error.code == "model_request_cancelled"
    assert error.computation_stopped is False


def test_cancellable_transport_reads_utf8_response():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write("成功".encode("utf-8"))
        def log_message(self, *_): pass
    with server(Handler) as endpoint:
        result = read_cancellable_response(Request(endpoint, data=b"{}", method="POST"), timeout=2, context=ModelRequestContext(threading.Event()))
    assert result == "成功".encode("utf-8")


def test_http11_keepalive_content_length_response_finishes():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_POST(self):
            body = b'{"ok":true}'
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_): pass
    with server(Handler) as endpoint:
        response = read_cancellable_response(Request(endpoint, data=b"{}", method="POST"), timeout=1, context=ModelRequestContext(threading.Event()))
    assert response == b'{"ok":true}'


def test_fragmented_chunked_response_uses_http_framing():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_POST(self):
            self.send_response(200); self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
            for part in (b"hello", b" world"):
                self.wfile.write(f"{len(part):X}\r\n".encode() + part + b"\r\n"); self.wfile.flush(); time.sleep(0.02)
            self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
        def log_message(self, *_): pass
    with server(Handler) as endpoint:
        response = read_cancellable_response(Request(endpoint, data=b"{}", method="POST"), timeout=1, context=ModelRequestContext(threading.Event()))
    assert response == b"hello world"


def test_precancelled_transport_sends_no_post():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self): calls.append(1); self.send_response(200); self.end_headers()
        def log_message(self, *_): pass
    with server(Handler) as endpoint:
        cancelled = threading.Event(); cancelled.set()
        with pytest.raises(ModelRequestError, match="cancelled") as raised:
            read_cancellable_response(Request(endpoint, data=b"{}", method="POST"), timeout=2, context=ModelRequestContext(cancelled))
    assert raised.value.code == "model_request_cancelled"
    assert calls == []


def test_cancellation_unblocks_headers_hang_with_one_request():
    started = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            started.set(); time.sleep(5)
        def log_message(self, *_): pass
    with server(Handler) as endpoint:
        cancelled = threading.Event(); result = []
        thread = threading.Thread(target=lambda: result.append(_capture(lambda: read_cancellable_response(Request(endpoint, data=b"{}", method="POST"), timeout=10, context=ModelRequestContext(cancelled)))))
        thread.start(); assert started.wait(1); cancelled.set(); thread.join(2)
    assert not thread.is_alive()
    assert isinstance(result[0], ModelRequestError) and result[0].code == "model_request_cancelled"


def test_cancellation_unblocks_partial_body_hang_without_watcher_leak():
    started = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200); self.send_header("Content-Length", "100"); self.end_headers()
            self.wfile.write(b"{"); self.wfile.flush(); started.set(); time.sleep(5)
        def log_message(self, *_): pass
    with server(Handler) as endpoint:
        cancelled = threading.Event(); result = []
        thread = threading.Thread(target=lambda: result.append(_capture(lambda: read_cancellable_response(Request(endpoint, data=b"{}", method="POST"), timeout=10, context=ModelRequestContext(cancelled)))) )
        thread.start(); assert started.wait(1); cancelled.set(); thread.join(2)
    assert not thread.is_alive()
    assert isinstance(result[0], ModelRequestError) and result[0].code == "model_request_cancelled"
    assert not [item for item in threading.enumerate() if item.name == "model-request-cancel"]


def test_header_stall_without_cancel_honors_request_deadline():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self): time.sleep(2)
        def log_message(self, *_): pass
    with server(Handler) as endpoint:
        started = time.monotonic()
        with pytest.raises(ModelRequestError) as raised:
            read_cancellable_response(Request(endpoint, data=b"{}", method="POST"), timeout=0.2, context=ModelRequestContext(threading.Event()))
    assert raised.value.code == "model_request_timeout"
    assert time.monotonic() - started < 1


def test_redirect_is_rejected_without_contacting_redirect_target():
    target_calls = []
    class Target(BaseHTTPRequestHandler):
        def do_POST(self): target_calls.append(1); self.send_response(200); self.end_headers()
        def log_message(self, *_): pass
    with server(Target) as target:
        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self): self.send_response(302); self.send_header("Location", target); self.end_headers()
            def log_message(self, *_): pass
        with server(Redirect) as source:
            with pytest.raises(HTTPError) as raised:
                read_cancellable_response(Request(source, data=b"{}", method="POST"), timeout=2, context=ModelRequestContext(threading.Event()))
    assert raised.value.code == 302
    assert target_calls == []


def test_nested_context_isolation():
    outer = ModelRequestContext(threading.Event())
    inner = ModelRequestContext(threading.Event())
    assert current_model_request() is None
    with pinned_model_request(outer):
        assert current_model_request() is outer
        with pinned_model_request(inner): assert current_model_request() is inner
        assert current_model_request() is outer
    assert current_model_request() is None


def test_provider_scoped_request_cancels_without_retry(tmp_path):
    started = threading.Event(); calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(1); started.set(); time.sleep(5)
        def log_message(self, *_): pass
    image = tmp_path / "screen.png"; Image.new("RGB", (2, 2)).save(image)
    with server(Handler) as endpoint:
        cancelled = threading.Event(); result = []
        provider = LocalVisionProvider(endpoint=endpoint, timeout_seconds=10)
        with pinned_model_request(ModelRequestContext(cancelled)):
            context = ModelRequestContext(cancelled)
            def run():
                with pinned_model_request(context):
                    result.append(_capture(lambda: provider.analyze(VisionAnalyzeRequest(image_path=str(image)))))
            thread = threading.Thread(target=run)
            thread.start(); assert started.wait(1); cancelled.set(); thread.join(2)
    assert not thread.is_alive() and calls == [1]
    assert isinstance(result[0], ModelRequestError) and result[0].code == "model_request_cancelled"


def _capture(fn):
    try: return fn()
    except Exception as exc: return exc
