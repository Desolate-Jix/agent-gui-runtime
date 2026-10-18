from __future__ import annotations

import base64
import hashlib
import json
import sys
from types import ModuleType

import pytest

from tests.test_agent_link_inbox import _batch, _png_base64


def _bundle(*, connection_id: str = "connection-a", task_id: str = "task-a") -> dict:
    png_base64 = _png_base64()
    return {
        "contract_version": "agent_link_artifact_bundle_v1",
        "connection_id": connection_id,
        "task_id": task_id,
        "artifacts": [{
            "artifact_id": "screen.list-1",
            "sha256": hashlib.sha256(base64.b64decode(png_base64)).hexdigest(),
            "png_base64": png_base64,
        }],
    }


def _reference(bundle: dict, screenshot_id: str = "screen-list") -> dict:
    artifact = bundle["artifacts"][0]
    return {"screenshot_id": screenshot_id, "artifact_id": artifact["artifact_id"], "sha256": artifact["sha256"]}


def test_bundle_expands_exact_original_png_bytes_and_keeps_inline_compatibility():
    from app.agent_link.artifacts import BridgeBatchInput, expand_batch, validate_artifact_bundle

    bundle = _bundle()
    catalog = validate_artifact_bundle(bundle, connection_id="connection-a", task_id="task-a")
    reference_batch = _batch()
    reference_batch["screenshots"][0] = _reference(bundle)
    expanded = expand_batch(BridgeBatchInput.model_validate(reference_batch), catalog)

    assert base64.b64decode(expanded["screenshots"][0]["png_base64"]) == base64.b64decode(bundle["artifacts"][0]["png_base64"])
    assert expanded["screenshots"][1] == reference_batch["screenshots"][1]


def test_bundle_rejects_binding_digest_png_and_duplicate_artifacts():
    from app.agent_link.artifacts import validate_artifact_bundle
    from app.agent_link.contracts import AgentLinkError

    bundle = _bundle()
    with pytest.raises(AgentLinkError, match="binding"):
        validate_artifact_bundle(bundle, connection_id="other", task_id="task-a")
    bad_digest = _bundle(); bad_digest["artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(AgentLinkError, match="digest"):
        validate_artifact_bundle(bad_digest, connection_id="connection-a", task_id="task-a")
    bad_png = _bundle(); bad_png["artifacts"][0]["png_base64"] = base64.b64encode(b"not png").decode("ascii")
    bad_png["artifacts"][0]["sha256"] = hashlib.sha256(b"not png").hexdigest()
    with pytest.raises(AgentLinkError, match="PNG"):
        validate_artifact_bundle(bad_png, connection_id="connection-a", task_id="task-a")
    duplicate = _bundle(); duplicate["artifacts"].append(duplicate["artifacts"][0].copy())
    with pytest.raises(AgentLinkError, match="unique"):
        validate_artifact_bundle(duplicate, connection_id="connection-a", task_id="task-a")


def test_loader_rejects_duplicate_json_keys_and_keeps_immutable_snapshot(tmp_path):
    from app.agent_link.artifacts import load_artifact_catalog
    from app.agent_link.contracts import AgentLinkError

    path = tmp_path / "bundle.json"
    path.write_text('{"contract_version":"agent_link_artifact_bundle_v1","connection_id":"connection-a","connection_id":"other","task_id":"task-a","artifacts":[]}', encoding="utf-8")
    with pytest.raises(AgentLinkError, match="duplicate"):
        load_artifact_catalog(path, connection_id="connection-a", task_id="task-a")
    bundle = _bundle(); path.write_text(json.dumps(bundle), encoding="utf-8")
    catalog = load_artifact_catalog(path, connection_id="connection-a", task_id="task-a")
    path.write_text(json.dumps({**bundle, "artifacts": []}), encoding="utf-8")
    assert catalog.resolve(_reference(bundle))["png_base64"] == bundle["artifacts"][0]["png_base64"]


def test_reference_requires_catalog_known_id_and_exact_digest():
    from app.agent_link.artifacts import BridgeBatchInput, expand_batch, validate_artifact_bundle
    from app.agent_link.contracts import AgentLinkError

    bundle = _bundle(); batch = _batch(); batch["screenshots"][0] = _reference(bundle)
    bridge_batch = BridgeBatchInput.model_validate(batch)
    with pytest.raises(AgentLinkError, match="catalog"):
        expand_batch(bridge_batch, None)
    catalog = validate_artifact_bundle(bundle, connection_id="connection-a", task_id="task-a")
    unknown = _batch(); unknown["screenshots"][0] = {**_reference(bundle), "artifact_id": "unknown"}
    with pytest.raises(AgentLinkError, match="unknown"):
        expand_batch(BridgeBatchInput.model_validate(unknown), catalog)
    mismatch = _batch(); mismatch["screenshots"][0] = {**_reference(bundle), "sha256": "0" * 64}
    with pytest.raises(AgentLinkError, match="digest"):
        expand_batch(BridgeBatchInput.model_validate(mismatch), catalog)


def test_candidate_interfaces_add_expands_reference_images():
    from app.agent_link.artifacts import BridgeCandidateInput, expand_candidate, validate_artifact_bundle

    bundle = _bundle(); catalog = validate_artifact_bundle(bundle, connection_id="connection-a", task_id="task-a")
    candidate = {
        "contract_version": "agent_link_v1", "idempotency_key": "candidate", "batch_id": "batch-a", "issue_id": "issue-a", "baseline_revision": 1,
        "scope": {"interface_ids": ["interface-list"], "relationship_ids": []},
        "changes": [{
            "change_type": "interfaces_add", "anchor_interface_id": "interface-list", "screenshots": [_reference(bundle, "screen-new")],
            "interfaces": [{"interface_id": "interface-new", "screenshot_id": "screen-new", "meaning": "new", "regions": []}],
        }],
    }
    expanded = expand_candidate(BridgeCandidateInput.model_validate(candidate), catalog)
    assert expanded["changes"][0]["screenshots"][0]["png_base64"] == bundle["artifacts"][0]["png_base64"]


def test_stdio_loads_configured_bundle_after_single_status_binding(tmp_path, monkeypatch):
    from app.agent_link import mcp_bridge

    bundle = _bundle(); path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    calls, tools = [], {}

    class FakeServer:
        def __init__(self, **kwargs):
            pass

        def add_tool(self, function, *, name, description):
            tools[name] = function

        def run(self, **kwargs):
            assert kwargs == {"transport": "stdio"}

    fake_mcp, fake_server = ModuleType("mcp"), ModuleType("mcp.server")
    fake_server.MCPServer = FakeServer
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server)
    monkeypatch.setenv("AGENT_LINK_BASE_URL", "http://127.0.0.1:30123")
    monkeypatch.setenv("AGENT_LINK_TOKEN", "token-value-long-enough")
    monkeypatch.setenv("AGENT_LINK_ARTIFACT_BUNDLE", str(path))
    monkeypatch.setattr(mcp_bridge, "_call", lambda *args: calls.append(args[2]) or {"connection_id": "connection-a", "task_id": "task-a"})

    mcp_bridge.run_stdio()

    assert calls == ["status"]
    batch = _batch(); batch["screenshots"][0] = _reference(bundle)
    tools["submit_learning_batch"](batch=mcp_bridge.BridgeBatchInput.model_validate(batch))
    assert calls[-1] == "submit_batch"


def test_loader_reads_at_most_bundle_limit_plus_one_byte():
    from io import BytesIO

    from app.agent_link.artifacts import MAX_ARTIFACT_BUNDLE_BYTES, load_artifact_catalog
    from app.agent_link.contracts import AgentLinkError

    calls = []

    class Reader(BytesIO):
        def read(self, size=-1):
            calls.append(size)
            return super().read(size)

    class PathLike:
        def open(self, mode):
            assert mode == "rb"
            return Reader(b"x" * (MAX_ARTIFACT_BUNDLE_BYTES + 1))

    with pytest.raises(AgentLinkError, match="exceeds"):
        load_artifact_catalog(PathLike(), connection_id="connection-a", task_id="task-a")
    assert calls == [MAX_ARTIFACT_BUNDLE_BYTES + 1]


def test_registered_catalog_does_not_bypass_existing_http_request_limit(monkeypatch):
    from io import BytesIO
    from PIL import Image
    from app.agent_link.artifacts import BridgeBatchInput, expand_batch, validate_artifact_bundle
    from app.agent_link import mcp_bridge

    buffer = BytesIO()
    Image.new("RGB", (800, 800), "white").save(buffer, format="PNG", compress_level=0)
    raw = buffer.getvalue()
    bundle = _bundle()
    bundle["artifacts"][0].update(png_base64=base64.b64encode(raw).decode("ascii"), sha256=hashlib.sha256(raw).hexdigest())
    catalog = validate_artifact_bundle(bundle, connection_id="connection-a", task_id="task-a")
    batch = _batch(); batch["screenshots"][0] = _reference(bundle)
    expanded = expand_batch(BridgeBatchInput.model_validate(batch), catalog)
    assert len(json.dumps(expanded).encode("utf-8")) > 2_500_000

    def forbidden_network(*args, **kwargs):
        pytest.fail("oversize request must be rejected before network access")

    monkeypatch.setattr(mcp_bridge, "build_opener", forbidden_network)
    with pytest.raises(RuntimeError, match="request exceeds limit"):
        mcp_bridge._call("http://127.0.0.1:30123", "token-value-long-enough", "submit_batch", expanded)
