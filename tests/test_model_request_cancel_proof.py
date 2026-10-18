from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from contextlib import contextmanager

from app.core import model_server


@contextmanager
def server():
    state = {"active_request": {"request_id": "req-1"}}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({"contract_version": "model_request_cancel_response_v1", "status": "cancellation_acknowledged", "request_id": "req-1"}).encode())
            state["active_request"] = None
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            if self.path.endswith("/health"): self.wfile.write(json.dumps({"status":"busy", "active_request":state["active_request"]}).encode())
            else: self.wfile.write(b'{"data": []}')
        def log_message(self, *_): pass
    instance=ThreadingHTTPServer(("127.0.0.1",0),Handler); thread=threading.Thread(target=instance.serve_forever,daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{instance.server_port}/v1", state
    finally: instance.shutdown(); instance.server_close(); thread.join()


def test_cancel_proof_uses_matching_ack_and_valid_post_ack_health():
    with server() as (base, _):
        result=model_server._cancel_profile_request(profile={"profile_id":"test","endpoint":base+"/chat/completions","request_cancel_endpoint":base+"/cancel","runtime":"transformers"},request_id="req-1",timeout=1,verify_seconds=.2,verify_instance=lambda: None)
    assert result["status"] == "terminated"


def test_cancel_proof_rejects_mismatched_acknowledgement(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self,*_): return None
        def read(self): return b'{"contract_version":"model_request_cancel_response_v1","status":"cancellation_acknowledged","request_id":"other"}'
    monkeypatch.setattr(model_server.urllib.request,"urlopen",lambda *_args,**_kwargs:Response())
    result=model_server._cancel_profile_request(profile={"profile_id":"test","request_cancel_endpoint":"http://127.0.0.1:1/cancel"},request_id="req-1",timeout=1,verify_seconds=0)
    assert result["status"] == "cancel_failed"



def test_cancel_proof_does_not_promote_missing_health_to_terminated(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self,*_): return None
        def read(self): return b'{"contract_version":"model_request_cancel_response_v1","status":"cancellation_acknowledged","request_id":"req-1"}'
    monkeypatch.setattr(model_server.urllib.request,"urlopen",lambda *_args,**_kwargs:Response())
    monkeypatch.setattr(model_server,"check_model_server",lambda *_args,**_kwargs:{"status":"unreachable","health":None})
    result=model_server._cancel_profile_request(profile={"profile_id":"test","request_cancel_endpoint":"http://127.0.0.1:1/cancel"},request_id="req-1",timeout=.01,verify_seconds=.01)
    assert result["status"] == "cancellation_acknowledged_pending"


def test_cancel_proof_requires_explicit_well_formed_active_request(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self,*_): return None
        def read(self): return b'{"contract_version":"model_request_cancel_response_v1","status":"cancellation_acknowledged","request_id":"req-1"}'
    monkeypatch.setattr(model_server.urllib.request,"urlopen",lambda *_args,**_kwargs:Response())
    for active_request in ({}, {"request_id":"req-1"}):
        monkeypatch.setattr(model_server,"check_model_server",lambda *_args, active_request=active_request, **_kwargs:{"status":"busy","health":{"status":"busy","active_request":active_request}})
        result=model_server._cancel_profile_request(profile={"profile_id":"test","request_cancel_endpoint":"http://127.0.0.1:1/cancel"},request_id="req-1",timeout=.01,verify_seconds=.01)
        assert result["status"] == "cancellation_acknowledged_pending"


def test_cancel_proof_instance_change_is_failed(monkeypatch):
    calls=[]
    def verify():
        calls.append(1)
        if len(calls) == 2: raise RuntimeError("instance changed")
    result=model_server._cancel_profile_request(
        profile={"profile_id":"test","request_cancel_endpoint":"http://127.0.0.1:1/cancel"}, request_id="req-1", timeout=.1, verify_seconds=.1,
        verify_instance=verify, request_reader=lambda *_: b'{"contract_version":"model_request_cancel_response_v1","status":"cancellation_acknowledged","request_id":"req-1"}',
    )
    assert result["status"] == "cancel_failed"


def test_late_health_cannot_become_termination_proof(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self,*_): return None
        def read(self): return b'{"contract_version":"model_request_cancel_response_v1","status":"cancellation_acknowledged","request_id":"req-1"}'
    monkeypatch.setattr(model_server.urllib.request,"urlopen",lambda *_args,**_kwargs:Response())
    def late_health(*_args, **_kwargs):
        import time
        time.sleep(.03)
        return {"status":"busy","health":{"status":"busy","active_request":None}}
    monkeypatch.setattr(model_server,"check_model_server",late_health)
    result=model_server._cancel_profile_request(profile={"profile_id":"test","request_cancel_endpoint":"http://127.0.0.1:1/cancel"},request_id="req-1",timeout=.01,verify_seconds=.01)
    assert result["status"] == "cancellation_acknowledged_pending"
