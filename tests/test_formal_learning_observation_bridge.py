from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from fastapi.testclient import TestClient
import pytest
from PIL import Image


_stream = BytesIO()
Image.new("RGB", (1, 1), (7, 8, 9)).save(_stream, format="PNG")
_PNG_BASE64 = base64.b64encode(_stream.getvalue()).decode("ascii")
_PNG_SHA256 = sha256(_stream.getvalue()).hexdigest()


class _ObservationService:
    def agent_call(self, token: str, operation: str, arguments: dict) -> dict:
        assert token == "agent-token-value-123"
        assert operation == "observe_learning_screen"
        assert arguments["segment_id"] == "segment-1"
        return {
            "contract_version": "agent_learning_observation_v1",
            "source_id": "source-1",
            "graph_id": "graph-1",
            "observation": {"title": "Settings", "meaning": "Inspect settings"},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "action_executed": False,
            "screenshot": {
                "mime_type": "image/png",
                "sha256": _PNG_SHA256,
                "width": 1,
                "height": 1,
                "png_base64": _PNG_BASE64,
            },
        }


def test_http_allows_observe_learning_screen_at_agent_boundary():
    from app.agent_link.http_app import create_agent_link_app

    client = TestClient(create_agent_link_app(_ObservationService()), client=("127.0.0.1", 50123))
    response = client.post(
        "/agent/observe_learning_screen",
        headers={"Authorization": "Bearer agent-token-value-123"},
        json={
            "segment_id": "segment-1", "idempotency_key": "capture-1",
            "application_identity": {"kind": "native", "executable_path": "C:/Fresh/fresh.exe"},
            "target_window_handle": 100, "target_process_id": 200,
            "title": "Settings", "meaning": "Inspect settings",
        },
    )
    assert response.status_code == 200
    assert response.json()["screenshot"]["png_base64"] == _PNG_BASE64


def test_observation_mcp_result_preserves_image_without_duplicate_base64_text():
    from mcp.types import ImageContent
    from app.agent_link.mcp_bridge import _observation_mcp_result

    result = _observation_mcp_result({
        "contract_version": "agent_learning_observation_v1",
        "source_id": "source-1", "graph_id": "graph-1",
        "observation": {"title": "Settings", "meaning": "Inspect settings"},
        "artifact_is_authorization": False, "execute_binding_enabled": False, "action_executed": False,
        "screenshot": {
            "mime_type": "image/png", "sha256": _PNG_SHA256,
            "width": 1, "height": 1, "png_base64": _PNG_BASE64,
        },
    })
    assert any(isinstance(item, ImageContent) and item.data == _PNG_BASE64 for item in result.content)
    text_content = next(item.text for item in result.content if item.type == "text")
    assert _PNG_BASE64 not in text_content
    assert result.structured_content["screenshot"] == {
        "mime_type": "image/png", "sha256": _PNG_SHA256, "width": 1, "height": 1,
    }
    assert result.structured_content["artifact_is_authorization"] is False
    assert result.structured_content["execute_binding_enabled"] is False
    assert result.structured_content["action_executed"] is False


@pytest.mark.parametrize("changed", ["bytes", "digest", "dimensions", "authority"])
def test_observation_bridge_rejects_inconsistent_image_or_authority(changed):
    from app.agent_link.mcp_bridge import _observation_mcp_result

    response = _ObservationService().agent_call("agent-token-value-123", "observe_learning_screen", {"segment_id": "segment-1"})
    if changed == "bytes":
        response["screenshot"]["png_base64"] = base64.b64encode(b"not a PNG").decode("ascii")
        response["screenshot"]["sha256"] = sha256(b"not a PNG").hexdigest()
    elif changed == "digest":
        response["screenshot"]["sha256"] = "0" * 64
    elif changed == "dimensions":
        response["screenshot"]["width"] = 2
    else:
        response["action_executed"] = True
    with pytest.raises(RuntimeError, match="observation response is invalid"):
        _observation_mcp_result(response)


def test_observation_bridge_allows_eight_megabyte_response_only_for_observe_operation():
    from app.agent_link.mcp_bridge import _call

    payload = json.dumps({"payload": "x" * 3_000_000}).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        assert len(_call(base_url, "agent-token-value-123", "observe_learning_screen", {} )["payload"]) == 3_000_000
        with pytest.raises(RuntimeError, match="response exceeds limit"):
            _call(base_url, "agent-token-value-123", "status", {})
    finally:
        server.shutdown()
        thread.join()
