from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from app.desktop_review.host import DesktopReviewHost
from tests.test_agent_link_inbox import _batch, _png_base64

ROOT = Path(__file__).resolve().parents[1]
SDK_PYTHON = Path(sys.executable)
REVIEWER = "artifact-mcp-reviewer-secret"


def _bundle() -> tuple[dict, dict]:
    png_base64 = _png_base64()
    digest = hashlib.sha256(base64.b64decode(png_base64)).hexdigest()
    artifact = {"artifact_id": "original.qt", "sha256": digest, "png_base64": png_base64}
    return artifact, {"screenshot_id": "screen-list", "artifact_id": artifact["artifact_id"], "sha256": digest}


@pytest.mark.parametrize("entry_args", [["scripts/start_agent_link_mcp.py"], ["scripts/start_agent_review.py", "--agent-link-mcp"]])
def test_sdk_stdio_reference_expands_exact_bytes_and_rejects_unknown_artifacts(tmp_path, entry_args):
    mcp = pytest.importorskip("mcp")
    Client, StdioServerParameters = mcp.Client, mcp.StdioServerParameters
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER, port=0)
    try:
        base_url = host.start()["base_url"]
        connection = host.connections.create_connection("task-a", "artifact-sdk")
        artifact, reference = _bundle()
        bundle_path = tmp_path / "bundle.json"
        bundle_path.write_text(json.dumps({
            "contract_version": "agent_link_artifact_bundle_v1",
            "connection_id": connection["connection_id"], "task_id": "task-a", "artifacts": [artifact],
        }), encoding="utf-8")
        environment = {
            **os.environ, "AGENT_LINK_BASE_URL": base_url,
            "AGENT_LINK_TOKEN": connection["token"],
            "AGENT_LINK_ARTIFACT_BUNDLE": str(bundle_path), "PYTHONIOENCODING": "utf-8",
        }
        parameters = StdioServerParameters(
            command=str(SDK_PYTHON), args=entry_args,
            env=environment, cwd=ROOT,
        )

        async def round_trip() -> None:
            async with Client(parameters) as client:
                tools = await client.list_tools()
                assert sorted(tool.name for tool in tools.tools) == [
                    "agent_link_status", "read_learning_feedback", "submit_learning_batch", "submit_relearning_candidate",
                ]
                batch = _batch(); batch["screenshots"][0] = reference
                submitted = await client.call_tool("submit_learning_batch", {"batch": batch})
                assert json.loads(submitted.content[0].text)["status"] == "pending_review_proposal"
                unknown = _batch("unknown-batch", "unknown-key")
                unknown["screenshots"][0] = {**reference, "artifact_id": "not-registered"}
                rejected = await client.call_tool("submit_learning_batch", {"batch": unknown})
                assert rejected.is_error
                mismatch = _batch("mismatch-batch", "mismatch-key")
                mismatch["screenshots"][0] = {**reference, "sha256": "0" * 64}
                rejected = await client.call_tool("submit_learning_batch", {"batch": mismatch})
                assert rejected.is_error

        asyncio.run(round_trip())
        stored = host.facade.load_batch("task-a", "batch-a")["batch"]
        assert hashlib.sha256(base64.b64decode(stored["screenshots"][0]["png_base64"])).hexdigest() == artifact["sha256"]
        assert [item["batch_id"] for item in host.facade.list_batches()] == ["batch-a"]
    finally:
        host.close()
