from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import json

from PIL import Image
import pytest

from app.agent_link.contracts import canonical_hash, validate_batch
from app.agent_link.feedback_view import compact_feedback_view
from app.agent_link.host import OwnedAgentLinkHttpHost
from app.agent_link.mcp_bridge import _call
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore


_REVIEWER_TOKEN = "fresh-feedback-reviewer-token"
_LIMIT = 2_500_000


def _fresh_batch() -> dict:
    image = Image.new("L", (1024, 1024), 0)
    output = BytesIO()
    image.save(output, format="PNG", compress_level=0)
    return {
        "contract_version": "agent_link_v1",
        "idempotency_key": "fresh-feedback-transport",
        "batch_id": "fresh-feedback-transport",
        "title": "新流程反馈",
        "learning_outcome": "completed",
        "screenshots": [{
            "screenshot_id": "fresh-capture",
            "png_base64": base64.b64encode(output.getvalue()).decode("ascii"),
        }],
        "interfaces": [{
            "interface_id": "fresh-interface",
            "screenshot_id": "fresh-capture",
            "meaning": "测试反馈读取，不执行动作",
            "regions": [],
        }],
        "relationships": [],
        "steps": [],
        "issues": [],
    }


def _wire_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@pytest.mark.parametrize("issue_count", [1, 2])
def test_feedback_view_is_compacted_before_real_bridge_response_limit(tmp_path, issue_count):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, _REVIEWER_TOKEN)
    host = OwnedAgentLinkHttpHost(service)
    try:
        grant = service.reviewer_call(_REVIEWER_TOKEN, "create_connection", {
            "task_id": "fresh-task", "agent_name": "isolated-contract-client",
        })
        base_url = host.start()
        batch = _fresh_batch()
        assert len(_wire_bytes(batch)) < _LIMIT
        receipt = _call(base_url, grant["token"], "submit_batch", batch)
        assert receipt["status"] == "pending_review_proposal"
        normalized = validate_batch(batch)
        baseline = {
            "contract_version": "desktop_review_baseline_v1",
            "task_id": "fresh-task",
            "workspace_revision": 1,
            "source_ref": canonical_hash(normalized),
            "batch_sha256": canonical_hash(normalized),
            "batch": batch,
        }
        service.reviewer_call(_REVIEWER_TOKEN, "record_feedback", {
            "task_id": "fresh-task",
            "batch_id": batch["batch_id"],
            "idempotency_key": "fresh-feedback-issues",
            "expected_revision": 0,
            "notes": [],
            "issues": [{
                "issue_id": f"fresh-issue-{index}",
                "scope": {"interface_ids": ["fresh-interface"], "relationship_ids": []},
                "message": f"检查界面含义 {index}",
                "review_baseline": deepcopy(baseline),
            } for index in range(issue_count)],
        })
        canonical = service.agent_call(grant["token"], "read_feedback", {
            "batch_id": batch["batch_id"],
        })
        before = deepcopy(canonical)
        if issue_count == 2:
            assert len(_wire_bytes(canonical)) > _LIMIT

        view = _call(base_url, grant["token"], "read_feedback_view", {
            "batch_id": batch["batch_id"],
        })

        assert len(_wire_bytes(view)) < _LIMIT
        assert view["revision"] == 1
        assert len(view["issues"]) == issue_count
        assert compact_feedback_view(view) == view
        before_by_id = {item["issue_id"]: item for item in before["issues"]}
        for issue in view["issues"]:
            saved_baseline = before_by_id[issue["issue_id"]]["review_baseline"]
            expected_baseline_hash = canonical_hash(saved_baseline)
            assert "review_baseline" not in issue
            assert issue["review_baseline_sha256"] == expected_baseline_hash
            visible = issue["review_baseline_view"]
            assert visible["source_baseline_sha256"] == expected_baseline_hash
            shot = visible["batch"]["screenshots"][0]
            assert "png_base64" not in shot
            assert shot["inline_image_omitted"] is True
            assert shot["sha256"] == normalized["screenshots"][0]["sha256"]
        assert service.agent_call(grant["token"], "read_feedback", {
            "batch_id": batch["batch_id"],
        }) == before

        foreign = service.reviewer_call(_REVIEWER_TOKEN, "create_connection", {
            "task_id": "other-task", "agent_name": "other-isolated-client",
        })
        for operation in ("read_feedback", "read_feedback_view"):
            with pytest.raises(RuntimeError, match="rejected"):
                _call(base_url, foreign["token"], operation, {
                    "batch_id": batch["batch_id"],
                })
    finally:
        host.close()
        store.close()
    assert host.phase == "stopped"
