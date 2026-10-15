"""本机慢分块 HTTP 和迟到 provider 回归，不连接外部 API。"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Thread
from time import monotonic, sleep

import pytest

from tests.test_openai_decisions import payload, reply


@contextmanager
def trickle_server(*, first_fast=False):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(self.path)
            body = json.dumps(reply()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                if first_fast and len(calls) != 2:
                    self.wfile.write(body)
                    self.wfile.flush()
                    return
                for offset in range(0, len(body), 10):
                    self.wfile.write(body[offset:offset + 10])
                    self.wfile.flush()
                    sleep(0.025)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/decisions", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)


def test_owned_transport_stops_continuous_chunks_at_total_deadline(monkeypatch):
    import app.judgment.openai_decisions as module
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    with trickle_server(first_fast=True) as (url, calls):
        monkeypatch.setattr(module, "ENDPOINT", url)
        provider = module.OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", timeout_seconds=2)
        try:
            assert provider.judge(payload())["usage"]["total_tokens"] == 12
            provider.timeout_seconds = 0.2
            started = monotonic()
            with pytest.raises(TimeoutError):
                provider.judge(payload())
            assert monotonic() - started < 0.65
            assert calls == ["/decisions", "/decisions"]
            provider.timeout_seconds = 2
            assert provider.judge(payload())["usage"]["total_tokens"] == 12
            assert calls == ["/decisions"] * 3
        finally:
            provider.close()
        transport = provider._client._transport
        assert not transport._thread.is_alive() and transport._loop.is_closed()
        assert not transport._tasks


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br"])
def test_encoded_response_is_closed_before_body_read(monkeypatch, encoding):
    import httpx
    from app.judgment import http_deadline
    closed = []
    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            pytest.fail("encoded body must not be read or decompressed")
            yield b""

        async def aclose(self):
            closed.append("body")

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, headers={"content-encoding": encoding}, stream=ForbiddenBody())

        async def aclose(self):
            closed.append("transport")

    monkeypatch.setattr(http_deadline.httpx, "AsyncHTTPTransport", lambda **_: Transport())
    with httpx.Client(transport=http_deadline.DeadlineHTTPTransport()) as client:
        with pytest.raises(ValueError, match="decision_content_encoding_unsupported"):
            client.post("http://synthetic.invalid", content=b"{}", timeout=0.5)
    assert closed == ["body", "transport"]


def test_late_provider_result_is_authenticated_timeout_and_never_retried(tmp_path, monkeypatch):
    import app.judgment.service as module
    from tests.test_adaptive_decision_policy import service, arguments, waiting_context, round_context
    runtime, calls, client = service(tmp_path, monkeypatch)
    clock = [0]
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    original = runtime._provider.judge
    def late(data):
        answer = original(data)
        clock[0] += 1_000_000_000
        return answer
    monkeypatch.setattr(runtime._provider, "judge", late)
    args = arguments(tmp_path, review_context=waiting_context(),
                     assessment_context=round_context(timeout_seconds=0.5))
    try:
        result = runtime.evaluate(**args)
        assert result["status"] == "timeout"
        assert result["verdict"] == "uncertain" and result["disposition"] == "review_required"
        assert not result["adopted"] and result["automatic_retry_allowed"] is False
        assert runtime.validate_result(result, **args)
        assert runtime.evaluate(**args) == result and len(calls) == 1
    finally:
        client.close()


def test_expired_absolute_deadline_never_dispatches(monkeypatch):
    import httpx
    from app.judgment import http_deadline

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            pytest.fail("expired absolute deadline must not send a request")

    monkeypatch.setattr(http_deadline.httpx, "AsyncHTTPTransport", lambda **_: Transport())
    with httpx.Client(transport=http_deadline.DeadlineHTTPTransport(error_prefix="api")) as client:
        with pytest.raises(TimeoutError, match="api_provider_timeout"):
            client.post("http://synthetic.invalid", content=b"{}", timeout=5,
                        extensions={"total_deadline": monotonic() - 1})


@pytest.mark.parametrize("maximum,accepted", [(64 * 1024, False), (128 * 1024, True)])
def test_shared_transport_uses_configured_response_bound(monkeypatch, maximum, accepted):
    import httpx
    from app.judgment import http_deadline
    body = b"x" * (80 * 1024)

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield body

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, stream=Body())

    monkeypatch.setattr(http_deadline.httpx, "AsyncHTTPTransport", lambda **_: Transport())
    with httpx.Client(transport=http_deadline.DeadlineHTTPTransport(
            max_response_bytes=maximum, error_prefix="api", thread_name="vision-api-test")) as client:
        if accepted:
            assert client.post("http://synthetic.invalid", content=b"{}", timeout=1).content == body
        else:
            with pytest.raises(ValueError, match="api_response_too_large"):
                client.post("http://synthetic.invalid", content=b"{}", timeout=1)


def test_absolute_deadline_limits_the_existing_read_budget():
    import httpx
    from app.judgment.http_deadline import DeadlineHTTPTransport
    with trickle_server() as (url, calls):
        with httpx.Client(transport=DeadlineHTTPTransport(error_prefix="api")) as client:
            started = monotonic()
            with pytest.raises(TimeoutError, match="api_provider_timeout"):
                client.post(url, content=b"{}", timeout=2,
                            extensions={"total_deadline": started + .2})
            assert monotonic() - started < .65
            assert calls == ["/decisions"]


@contextmanager
def error_response_server(*, status, body_mode):
    calls, release = [], Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(self.path)
            body = b"x" * (128 * 1024)
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("x-request-id", "loopback-error-request")
            if body_mode == "encoded":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            if body_mode == "delayed":
                release.wait(2)
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/error", calls
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(1)


@pytest.mark.parametrize("encoding", ["identity", "gzip"])
def test_non_200_transport_closes_body_without_reading(monkeypatch, encoding):
    import httpx
    from app.judgment import http_deadline

    closed = []

    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            pytest.fail("HTTP error status must be returned without reading its body")
            yield b""

        async def aclose(self):
            closed.append("body")

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(401, headers={"content-encoding": encoding,
                "content-length": "1048576", "x-request-id": "synthetic-error-request"},
                stream=ForbiddenBody())

        async def aclose(self):
            closed.append("transport")

    monkeypatch.setattr(http_deadline.httpx, "AsyncHTTPTransport", lambda **_: Transport())
    with httpx.Client(transport=http_deadline.DeadlineHTTPTransport(error_prefix="api")) as client:
        response = client.post("http://synthetic.invalid", content=b"{}", timeout=0.5)
        assert response.status_code == 401
        assert response.headers["x-request-id"] == "synthetic-error-request"
        assert response.content == b""
        assert closed == ["body"]
    assert closed == ["body", "transport"]


@pytest.mark.parametrize("body_mode", ["oversized", "delayed", "encoded"])
@pytest.mark.parametrize("status,code", [(401, "api_authentication_failed"), (429, "api_rate_limited")])
def test_owned_api_transport_preserves_non_200_status_before_body(
        tmp_path, monkeypatch, body_mode, status, code):
    from hashlib import sha256
    from PIL import Image
    from app.vision.external_grounding_api import ApiGroundingError, ApiGroundingProfile, ChatCompletionsGrounder

    monkeypatch.setenv("API_DEADLINE_TEST_KEY", "synthetic-secret")
    image = tmp_path / "synthetic-frame.png"
    Image.new("RGB", (100, 80), "white").save(image)
    capture = {"image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
        "capture_id": "synthetic-capture", "image_size": {"width": 100, "height": 80}}
    with error_response_server(status=status, body_mode=body_mode) as (url, calls):
        profile = ApiGroundingProfile(endpoint=url, model="synthetic-model",
            api_key_env="API_DEADLINE_TEST_KEY", timeout_seconds=0.2, max_response_bytes=1024)
        with ChatCompletionsGrounder(profile) as grounder:
            with pytest.raises(ApiGroundingError, match=code) as failure:
                grounder.ground(request_id="synthetic-request", capture=capture, goal="synthetic target")
        assert failure.value.status_code == status
        assert failure.value.provider["provider_request_id"] == "loopback-error-request"
        assert failure.value.attempt["status"] == "failure"
        assert calls == ["/error"]


@pytest.mark.parametrize("body_mode", ["oversized", "delayed", "encoded"])
@pytest.mark.parametrize("status", [401, 429])
def test_owned_decision_transport_preserves_non_200_status_before_body(monkeypatch, body_mode, status):
    import app.judgment.openai_decisions as module

    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    with error_response_server(status=status, body_mode=body_mode) as (url, calls):
        monkeypatch.setattr(module, "ENDPOINT", url)
        provider = module.OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", timeout_seconds=1)
        try:
            with pytest.raises(OSError, match=f"decision_http_status_{status}"):
                provider.judge(payload())
            assert calls == ["/error"]
        finally:
            provider.close()
