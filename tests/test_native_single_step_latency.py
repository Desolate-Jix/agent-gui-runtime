"""loopback 单步响应允许有界长验证；超时绝不自动重发。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import time

import httpx
import pytest

from app.desktop_review.single_step import NativeSingleStepError, OwnedSingleStepClient

TOKEN = "latency-test-execution-token"
CONFIRMATION = "grounded-confirmation." + "d" * 64


def _decision():
    return {"contract_version": "native_single_step_response_v1", "confirmation_id": CONFIRMATION,
        "kind": "decision", "payload": {"status": "REJECTED",
            "reason_code": "grounded_confirmation_stale", "confirmation_id": CONFIRMATION},
        "artifact_is_authorization": False}


def test_owned_client_waits_for_bounded_slow_loopback_response():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.path)
            length = int(self.headers["content-length"])
            assert json.loads(self.rfile.read(length)) == {"confirmation_id": CONFIRMATION}
            time.sleep(10.5)
            content = json.dumps(_decision(), separators=(",", ":")).encode("utf-8")
            self.send_response(200); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(content))); self.end_headers()
            self.wfile.write(content)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        client = OwnedSingleStepClient(base_url=f"http://127.0.0.1:{server.server_port}",
            token=TOKEN, confirmation_id=CONFIRMATION)
        assert client.execute(confirmation_id=CONFIRMATION) == _decision()
        assert calls == ["/action/execute_recognition_plan"]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_read_timeout_is_unknown_and_never_reposts(monkeypatch):
    posts = []
    class Client:
        def __init__(self, **kwargs):
            timeout = kwargs["timeout"]
            assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (5.0, 180.0, 10.0, 5.0)
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def post(self, *args, **kwargs):
            posts.append((args, kwargs))
            raise httpx.ReadTimeout("controlled timeout")
    monkeypatch.setattr(httpx, "Client", Client)
    client = OwnedSingleStepClient(base_url="http://127.0.0.1:49123", token=TOKEN,
        confirmation_id=CONFIRMATION)
    with pytest.raises(NativeSingleStepError) as error:
        client.execute(confirmation_id=CONFIRMATION)
    assert error.value.code == "single_step_result_unknown"
    assert error.value.result_unknown is True
    assert len(posts) == 1
