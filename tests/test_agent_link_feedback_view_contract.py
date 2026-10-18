import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json

import mcp.server
from PIL import Image
import pytest

from app.agent_link import mcp_bridge
from app.agent_link.feedback_view import compact_feedback_view


@pytest.fixture
def feedback():
    image = BytesIO()
    Image.new("RGB", (8, 6), "white").save(image, format="PNG")
    return {"issues": [{
        "issue_id": "issue", "review_baseline_sha256": "a" * 64,
        "scope": {"interface_ids": ["interface"], "relationship_ids": []},
        "review_baseline": {
            "contract_version": "desktop_review_baseline_v1",
            "task_id": "task", "workspace_revision": 1,
            "source_ref": "b" * 64, "batch_sha256": "c" * 64,
            "batch": {
                "screenshots": [{"screenshot_id": "image", "width": 8, "height": 6,
                    "png_base64": base64.b64encode(image.getvalue()).decode("ascii")}],
                "interfaces": [{"interface_id": "interface", "meaning": "用途",
                    "recognition_text": "真实标题", "regions": [{"bbox": [0, 0, 8, 6]}]}],
                "steps": [{"step_id": "step", "action": "fill_field"}],
            },
        },
    }]}


def test_view_preserves_semantics_source_digest_and_original(feedback):
    original = deepcopy(feedback)
    result = compact_feedback_view(feedback)
    assert feedback == original
    issue = result["issues"][0]
    source = original["issues"][0]["review_baseline"]
    assert "review_baseline" not in issue
    view = issue["review_baseline_view"]
    assert view["contract_version"] == "desktop_review_baseline_view_v1"
    assert view["source_contract_version"] == source["contract_version"]
    assert view["source_baseline_sha256"] == issue["review_baseline_sha256"] == "a" * 64
    assert view["artifact_is_authorization"] is False
    for key in ("task_id", "workspace_revision", "source_ref", "batch_sha256"):
        assert view[key] == source[key]
    assert issue["scope"] == original["issues"][0]["scope"]
    assert view["batch"]["interfaces"] == source["batch"]["interfaces"]
    assert view["batch"]["steps"] == source["batch"]["steps"]
    raw = base64.b64decode(source["batch"]["screenshots"][0]["png_base64"])
    assert view["batch"]["screenshots"] == [{"screenshot_id": "image", "width": 8,
        "height": 6, "sha256": hashlib.sha256(raw).hexdigest(), "inline_image_omitted": True}]
    assert "png_base64" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("bad_image", ["%%%", base64.b64encode(b"not a png").decode("ascii")])
def test_malformed_image_is_not_silently_removed(feedback, bad_image):
    feedback["issues"][0]["review_baseline"]["batch"]["screenshots"][0]["png_base64"] = bad_image
    with pytest.raises(ValueError, match="screenshot is malformed"):
        compact_feedback_view(feedback)


def test_mismatched_screenshot_digest_is_rejected(feedback):
    feedback["issues"][0]["review_baseline"]["batch"]["screenshots"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest disagrees"):
        compact_feedback_view(feedback)


def test_legacy_feedback_is_unchanged():
    feedback = {"issues": [{"issue_id": "legacy", "note": "重新检查"}], "status": "pending"}
    assert compact_feedback_view(feedback) == feedback


def test_registered_mcp_tool_uses_view_without_adding_authority(monkeypatch, feedback):
    registered = {}
    original = deepcopy(feedback)

    class CapturingServer:
        def __init__(self, **kwargs):
            pass

        def add_tool(self, function, *, name, description):
            registered[name] = function

        def run(self, **kwargs):
            pass

    def backend(url, token, operation, args):
        if operation == "status":
            assert args == {}
            return {"contract_version": "agent_link_v1", "capabilities": ["read_feedback"]}
        assert operation == "read_feedback"
        assert args == {"batch_id": "batch"}
        return feedback

    monkeypatch.setattr(mcp.server, "MCPServer", CapturingServer)
    monkeypatch.setattr(mcp_bridge, "_configuration", lambda: ("http://127.0.0.1:1234", "fixture"))
    monkeypatch.delenv("AGENT_LINK_ARTIFACT_BUNDLE", raising=False)
    monkeypatch.setattr(mcp_bridge, "_call", backend)
    mcp_bridge.run_stdio()
    assert set(registered) == {"agent_link_status", "submit_learning_batch",
        "read_learning_feedback", "submit_relearning_candidate"}
    result = registered["read_learning_feedback"]("batch")
    assert "review_baseline_view" in result["issues"][0]
    assert "png_base64" not in json.dumps(result)
    assert feedback == original
