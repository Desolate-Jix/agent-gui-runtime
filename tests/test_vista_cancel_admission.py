from __future__ import annotations

import threading
import pytest
import app.vision.model_workers.vista_openai_server as vista


@pytest.fixture(autouse=True)
def reset_state():
    with vista.ACTIVE_REQUEST_LOCK:
        vista.ACTIVE_REQUEST = None
        vista.ACTIVE_CANCEL_EVENT = None
        vista.CANCELLED_REQUEST_IDS.clear()
    yield


def test_cancel_before_activation_fences_exact_request():
    receipt = vista._cancel_active_request("late-request")
    assert receipt["status"] == "request_not_active"
    assert receipt["request_fenced"] is True
    with pytest.raises(vista.ModelRequestCancelled):
        vista._activate_request(request_id="late-request", cancel_event=threading.Event(), metadata={})
    active = vista._activate_request(request_id="other-request", cancel_event=threading.Event(), metadata={})
    assert active["request_id"] == "other-request"


def test_active_cancellation_fences_and_signals_matching_request():
    event = threading.Event()
    vista._activate_request(request_id="request-a", cancel_event=event, metadata={})
    assert vista._cancel_active_request("request-b")["status"] == "request_id_mismatch"
    receipt = vista._cancel_active_request("request-a")
    assert receipt["status"] == "cancellation_acknowledged"
    assert receipt["request_fenced"] is True
    assert event.is_set()


def test_handler_admission_rejects_body_that_arrives_after_cancel_fence():
    import json
    import socket
    import time
    import urllib.request
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), vista.VistaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    body = json.dumps({"request_id": "late-handler", "messages": []}).encode()
    client = socket.create_connection(("127.0.0.1", server.server_port))
    client.sendall((
        b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(body)).encode() + b"\r\n\r\n"
    ))
    try:
        deadline = time.monotonic() + 1
        while not vista.GENERATE_LOCK.locked() and time.monotonic() < deadline: time.sleep(.01)
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/v1/cancel", data=b'{"request_id":"late-handler"}', headers={"Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=1) as response:
            receipt = json.loads(response.read())
        assert receipt["request_fenced"] is True
        client.sendall(body)
        assert b" 409 " in client.recv(4096)
    finally:
        client.close(); server.shutdown(); server.server_close(); thread.join()


def test_other_active_request_does_not_prevent_fencing_late_cancelled_request():
    active_event = threading.Event()
    vista._activate_request(request_id="active-b", cancel_event=active_event, metadata={})
    receipt = vista._cancel_active_request("late-a")
    assert receipt["status"] == "request_id_mismatch"
    assert not active_event.is_set()
    vista._clear_active_request("active-b")
    with pytest.raises(vista.ModelRequestCancelled):
        vista._activate_request(request_id="late-a", cancel_event=threading.Event(), metadata={})
