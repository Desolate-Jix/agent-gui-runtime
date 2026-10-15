"""真实回环 HTTP 验证闲置连接复用；虚拟时钟不影响请求截止时间。"""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Lock, Thread
from types import SimpleNamespace

import httpcore._async.http11 as http11
import httpx
import pytest

from tests.test_luna_choice_review_provider import decision_body, payload, response_body


@contextmanager
def _loopback_server():
    state = SimpleNamespace(requests=[], closed={}, lock=Lock())

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            with state.lock:
                self.connection_id = len(state.closed) + 1
                state.closed[self.connection_id] = Event()

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            with state.lock:
                state.requests.append({"connection": self.connection_id,
                    "path": self.path, "body": json.loads(body)})
            answer = response_body() if self.path == "/v1/responses" else decision_body()
            raw = json.dumps(answer).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            self.wfile.flush()

        def finish(self):
            try:
                super().finish()
            finally:
                state.closed[self.connection_id].set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)


def _owned_provider(monkeypatch, url):
    import app.judgment.openai_decisions as module
    monkeypatch.setenv("CONNECTION_REUSE_TEST_KEY", "synthetic-loopback-only")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setattr(module, "ENDPOINT", url + "/v1/decisions")
    monkeypatch.setattr(module, "REVIEW_ENDPOINT", url + "/v1/responses")
    clients, extensions = [], []
    real_client = httpx.Client

    def create_client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        assert kwargs["timeout"] == 8
        client = real_client(**kwargs)
        clients.append(client)
        exchange = client._transport.handle_request

        def handle(request):
            extensions.append(deepcopy(request.extensions))
            return exchange(request)

        monkeypatch.setattr(client._transport, "handle_request", handle)
        return client

    monkeypatch.setattr(module.httpx, "Client", create_client)
    return module.OpenAIDecisionsProvider(api_key_env="CONNECTION_REUSE_TEST_KEY"), clients, extensions


def _idle_clock(monkeypatch):
    now = [1000.0]
    # 只控制连接的空闲过期判定，不替换 time.monotonic 或生产 deadline 时钟。
    monkeypatch.setattr(http11, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_decision_and_ordinary_reuse_connection_across_idle_gaps_over_five_seconds(monkeypatch):
    now = _idle_clock(monkeypatch)
    with _loopback_server() as (url, state):
        provider, clients, extensions = _owned_provider(monkeypatch, url)
        try:
            assert not clients
            assert provider.judge(payload())["choice_result"]["choice"] == "condition_not_met"
            now[0] += 6
            assert provider.judge(payload())["choice_result"]["choice"] == "condition_not_met"
            now[0] += 59
            assert provider.review(payload())["review_result"]["choice"] == "condition_met"
            assert [r["connection"] for r in state.requests] == [1, 1, 1]
            assert [r["path"] for r in state.requests] == ["/v1/decisions", "/v1/decisions", "/v1/responses"]
            assert len(clients) == 1 and provider._client is clients[0]
            first, second, review = [r["body"] for r in state.requests]
            assert first == second
            assert review["input"][0]["content"][:-1] == first["input"][0]["content"]
            question_text = review["input"][0]["content"][-1]["text"]
            prefix = "Question and allowed choices (JSON): "
            assert question_text.startswith(prefix)
            question, end = json.JSONDecoder().raw_decode(question_text[len(prefix):])
            assert question == first["questions"][0]
            assert question_text[len(prefix) + end:].startswith("\nOutput exactly one allowed choice value")
            assert len(extensions) == 3
            assert all(0 < e["timeout"]["read"] <= 8 and "total_deadline" in e for e in extensions)
        finally:
            provider.close()
        assert clients[0].is_closed
        assert all(event.wait(1) for event in state.closed.values())


def test_idle_over_sixty_seconds_reconnects_and_close_releases_connections(monkeypatch):
    import app.judgment.openai_decisions as module
    now = _idle_clock(monkeypatch)
    with _loopback_server() as (url, state):
        provider, clients, _ = _owned_provider(monkeypatch, url)
        try:
            provider.judge(payload())
            now[0] += 61
            provider.judge(payload())
            assert [r["connection"] for r in state.requests] == [1, 2]
            assert state.closed[1].wait(1)
            assert len(clients) == 1
        finally:
            provider.close()
        assert clients[0].is_closed and state.closed[2].wait(1)
        transport = clients[0]._transport
        assert not transport._thread.is_alive() and transport._loop.is_closed()
        with pytest.raises(OSError, match="decision_provider_closed"):
            provider.judge(payload())
        assert len(state.requests) == 2
        replacement = module.OpenAIDecisionsProvider(api_key_env="CONNECTION_REUSE_TEST_KEY")
        try:
            replacement.judge(payload())
            assert [r["connection"] for r in state.requests] == [1, 2, 3]
            assert len(clients) == 2 and replacement._client is clients[1]
        finally:
            replacement.close()
        assert state.closed[3].wait(1)
