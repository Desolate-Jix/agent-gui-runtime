"""取消后的健康确认也必须使用同一个有界读取通道。"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
import time

from app.core import model_server
from app.vision.request_control import ModelRequestContext, read_cancellable_response


def test_scoped_cancel_health_drip_does_not_hold_owner_past_control_budget():
    release = Event()
    health_started = Event()
    outcomes = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = {"contract_version": "model_request_cancel_response_v1", "request_id": "req-drip",
                       "status": "cancellation_acknowledged"}
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.endswith("/health"):
                self.send_response(200)
                self.end_headers()
                health_started.set()
                try:
                    while not release.wait(.01):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            else:
                self.send_response(503)
                self.end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = Thread(target=server.serve_forever, daemon=True)
    serving.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1"
    control = ModelRequestContext(Event())

    def cancel():
        outcomes.append(model_server._cancel_profile_request(
            profile={"profile_id": "drip", "runtime": "transformers",
                     "endpoint": endpoint + "/chat/completions", "request_cancel_endpoint": endpoint + "/cancel"},
            request_id="req-drip", timeout=.15, verify_seconds=.15,
            request_reader=lambda request, timeout: read_cancellable_response(request, timeout=timeout, context=control)))

    worker = Thread(target=cancel, daemon=True)
    try:
        started = time.monotonic()
        worker.start()
        assert health_started.wait(2)
        worker.join(timeout=1.5)
        assert not worker.is_alive(), "health drips must not retain the cancellation owner"
        assert time.monotonic() - started < 2
        assert outcomes[0]["status"] == "cancellation_acknowledged_pending"
    finally:
        release.set()
        worker.join(timeout=3)
        server.shutdown()
        server.server_close()
        serving.join(timeout=2)
        assert not worker.is_alive() and not serving.is_alive()
