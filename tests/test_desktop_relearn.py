from __future__ import annotations

import base64
import copy
import json
from io import BytesIO

import pytest
from PIL import Image

from app.agent_link import AgentLinkService, AgentLinkStore
from app.agent_link.contracts import canonical_hash
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade


REVIEWER_TOKEN = "reviewer-secret-value-123"


def _png_base64() -> str:
    image = Image.new("RGB", (80, 60), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _batch() -> dict:
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "batch-key",
        "batch_id": "batch-1", "title": "中文审核批次", "learning_outcome": "completed",
        "outcome_reason": None,
        "screenshots": [{"screenshot_id": "screen-1", "png_base64": _png_base64()}],
        "interfaces": [{
            "interface_id": "interface-1", "screenshot_id": "screen-1", "meaning": "原始界面",
            "regions": [{"region_id": "region-1", "bbox": [2.0, 3.0, 20.0, 15.0], "name": "详情", "meaning": "原始框"}],
        }],
        "relationships": [],
        "steps": [{
            "step_id": "step-1", "action_type": "open_detail", "target_region_id": "region-1",
            "start_state": "interface-1", "arrival_state": "interface-1", "prerequisites": [],
            "expected_result": "原始结果", "stop_condition": "停止",
        }],
        "issues": [],
    }


def _setup(tmp_path):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, REVIEWER_TOKEN)
    grant = service.reviewer_call(REVIEWER_TOKEN, "create_connection", {
        "task_id": "task-1", "agent_name": "synthetic-agent",
    })
    service.agent_call(grant["token"], "submit_batch", _batch())
    facade = NativeReviewFacade(service, REVIEWER_TOKEN, tmp_path / "review-data")
    edited = copy.deepcopy(facade.load_batch("task-1", "batch-1")["batch"])
    edited["interfaces"][0]["meaning"] = "人工界面"
    edited["interfaces"][0]["regions"][0]["meaning"] = "人工框"
    edited["interfaces"][0]["regions"][0]["bbox"] = [3.0, 4.0, 20.0, 15.0]
    edited["steps"][0]["expected_result"] = "人工结果"
    saved = facade.save_revision("task-1", "batch-1", 0, edited)
    return store, service, grant, facade, saved


def test_saved_human_revision_roundtrip_and_three_way_compare_are_readonly(tmp_path):
    store, service, grant, facade, saved = _setup(tmp_path)
    try:
        original_before = service.reviewer_call(REVIEWER_TOKEN, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"})["batch"]
        view = facade.request_relearn(
            "task-1", "batch-1", 1, 0,
            {"interface_ids": ["interface-1"], "relationship_ids": []},
            "请根据人工框和中文语义重学", "request-1",
        )
        assert view["contract_version"] == "desktop_relearn_review_v1"
        assert view["workspace_revision"] == 1 and view["feedback_revision"] == 1
        feedback = service.agent_call(grant["token"], "read_feedback", {"batch_id": "batch-1"})
        issue = feedback["issues"][0]
        assert issue["review_baseline"]["batch"]["interfaces"][0]["meaning"] == "人工界面"
        assert issue["review_baseline"]["workspace_revision"] == 1
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "idempotency_key": "candidate-1",
            "batch_id": "batch-1", "issue_id": issue["issue_id"], "baseline_revision": 1,
            "review_baseline_sha256": issue["review_baseline_sha256"],
            "scope": issue["scope"],
            "changes": [
                {"change_type": "geometry", "region_id": "region-1", "bbox": [4.0, 5.0, 20.0, 15.0]},
                {"change_type": "semantic", "target_type": "region", "target_id": "region-1", "meaning": "候选框"},
                {"change_type": "step", "step_id": "step-1", "action_type": "open_detail", "target_region_id": "region-1", "expected_result": "候选结果"},
            ],
        })
        comparison = facade.compare_relearn_candidate("task-1", "batch-1", 1, candidate["candidate_id"])
        assert comparison["contract_version"] == "desktop_relearn_comparison_v1"
        assert comparison["status"] == "current" and comparison["blocked_reasons"] == []
        by_field = {(item["target_type"], item["target_id"], item["field"]): item for item in comparison["diffs"]}
        assert by_field[("region", "region-1", "bbox")] == {
            "target_type": "region", "target_id": "region-1", "field": "bbox",
            "baseline": [3.0, 4.0, 20.0, 15.0], "current": [3.0, 4.0, 20.0, 15.0],
            "proposed": [4.0, 5.0, 20.0, 15.0],
        }
        assert by_field[("region", "region-1", "meaning")]["baseline"] == "人工框"
        assert by_field[("step", "step-1", "expected_result")]["proposed"] == "候选结果"
        assert facade.load_batch("task-1", "batch-1") == saved
        assert service.reviewer_call(REVIEWER_TOKEN, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"})["batch"] == original_before
    finally:
        facade.close(); store.close()


def test_request_is_stable_idempotent_and_requires_exact_saved_revision(tmp_path):
    store, _, _, facade, _ = _setup(tmp_path)
    try:
        args = (
            "task-1", "batch-1", 1, 0,
            {"interface_ids": ["interface-1"], "relationship_ids": []},
            "重学", "stable-key",
        )
        first = facade.request_relearn(*args)
        second = facade.request_relearn(*args)
        assert first == second
        assert len(first["issues"]) == 1
        with pytest.raises(DesktopReviewError, match="正整数|saved"):
            facade.load_relearn_review("task-1", "batch-1", 0)
    finally:
        facade.close(); store.close()


def test_new_workspace_revision_makes_candidate_stale_and_withdraw_is_exact(tmp_path):
    store, service, grant, facade, saved = _setup(tmp_path)
    try:
        view = facade.request_relearn("task-1", "batch-1", 1, 0, {"interface_ids": ["interface-1"], "relationship_ids": []}, "重学", "request")
        issue = view["issues"][0]
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "idempotency_key": "candidate",
            "batch_id": "batch-1", "issue_id": issue["issue_id"], "baseline_revision": 1,
            "review_baseline_sha256": issue["review_baseline_sha256"], "scope": issue["scope"],
            "changes": [{"change_type": "semantic", "target_type": "interface", "target_id": "interface-1", "meaning": "候选界面"}],
        })
        changed = copy.deepcopy(saved["batch"])
        changed["interfaces"][0]["meaning"] = "第二个人工版本"
        facade.save_revision("task-1", "batch-1", 1, changed)
        comparison = facade.compare_relearn_candidate("task-1", "batch-1", 2, candidate["candidate_id"])
        assert comparison["status"] == "stale"
        assert comparison["diffs"][0]["current"] == "第二个人工版本"
        withdrawn = facade.withdraw_relearn("task-1", "batch-1", 2, issue["issue_id"], 1, "withdraw")
        assert withdrawn["feedback_revision"] == 2
        assert facade.compare_relearn_candidate("task-1", "batch-1", 2, candidate["candidate_id"])["status"] == "withdrawn"
    finally:
        facade.close(); store.close()


def test_load_rejects_malformed_service_baseline_identity(tmp_path, monkeypatch):
    store, service, _, facade, _ = _setup(tmp_path)
    try:
        facade.request_relearn(
            "task-1", "batch-1", 1, 0,
            {"interface_ids": ["interface-1"], "relationship_ids": []},
            "重学", "request",
        )
        original_call = service.reviewer_call

        def tampered(token, operation, arguments):
            result = original_call(token, operation, arguments)
            if operation == "get_batch":
                result["issues"][0]["review_baseline_sha256"] = "0" * 64
            return result

        monkeypatch.setattr(service, "reviewer_call", tampered)
        with pytest.raises(DesktopReviewError, match="基线|baseline"):
            facade.load_relearn_review("task-1", "batch-1", 1)
    finally:
        facade.close(); store.close()


def test_old_persisted_duplicate_candidate_reloads_as_legacy_unbound(tmp_path):
    store, service, grant, facade, _ = _setup(tmp_path)
    service.reviewer_call(REVIEWER_TOKEN, "record_feedback", {
        "task_id": "task-1", "batch_id": "batch-1", "idempotency_key": "legacy-feedback",
        "expected_revision": 0, "notes": [], "issues": [{
            "issue_id": "legacy", "scope": {"interface_ids": ["interface-1"], "relationship_ids": []},
            "message": "旧问题",
        }],
    })
    receipt = service.agent_call(grant["token"], "submit_candidate", {
        "contract_version": "agent_link_v1", "idempotency_key": "legacy-candidate",
        "batch_id": "batch-1", "issue_id": "legacy", "baseline_revision": 1,
        "scope": {"interface_ids": ["interface-1"], "relationship_ids": []},
        "changes": [{"change_type": "geometry", "region_id": "region-1", "bbox": [4.0, 5.0, 20.0, 15.0]}],
    })
    root = facade._artifact_root
    path = store._path
    facade.close(); store.close()
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candidates"][receipt["candidate_id"]]["changes"].append(
        {"change_type": "geometry", "region_id": "region-1", "bbox": [5.0, 6.0, 20.0, 15.0]}
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    reopened = AgentLinkStore(path)
    reopened_facade = NativeReviewFacade(AgentLinkService(reopened, REVIEWER_TOKEN), REVIEWER_TOKEN, root)
    try:
        comparison = reopened_facade.compare_relearn_candidate("task-1", "batch-1", 1, receipt["candidate_id"])
        assert comparison["status"] == "legacy_unbound"
        assert any("duplicate_target_field" in reason for reason in comparison["blocked_reasons"])
    finally:
        reopened_facade.close(); reopened.close()


@pytest.mark.parametrize("action_type", ["final_submit", "unknown_action_xyz"])
def test_dangerous_or_unknown_actions_and_no_effect_are_blocked(tmp_path, action_type):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        view = facade.request_relearn("task-1", "batch-1", 1, 0, {"interface_ids": ["interface-1"], "relationship_ids": []}, "重学", "request")
        issue = view["issues"][0]
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "idempotency_key": "candidate",
            "batch_id": "batch-1", "issue_id": issue["issue_id"], "baseline_revision": 1,
            "review_baseline_sha256": issue["review_baseline_sha256"], "scope": issue["scope"],
            "changes": [
                {"change_type": "semantic", "target_type": "interface", "target_id": "interface-1", "meaning": "人工界面"},
                {"change_type": "step", "step_id": "step-1", "action_type": action_type, "target_region_id": "region-1", "expected_result": "人工结果"},
            ],
        })
        comparison = facade.compare_relearn_candidate("task-1", "batch-1", 1, candidate["candidate_id"])
        assert comparison["status"] == "blocked"
        assert any("action" in reason for reason in comparison["blocked_reasons"])
        assert any("no_effect" in reason for reason in comparison["blocked_reasons"])
    finally:
        facade.close(); store.close()


def test_candidate_step_scope_uses_saved_human_start_interface_not_original(tmp_path):
    from app.agent_link.contracts import AgentLinkError

    batch = _batch()
    batch["interfaces"].append({
        "interface_id": "interface-2", "screenshot_id": "screen-1", "meaning": "第二界面",
        "regions": [{"region_id": "region-2", "bbox": [25.0, 3.0, 20.0, 15.0], "name": "返回", "meaning": "第二界面的目标"}],
    })
    path, root = tmp_path / "inbox.json", tmp_path / "review-data"
    store = AgentLinkStore(path)
    service = AgentLinkService(store, REVIEWER_TOKEN)
    grant = service.reviewer_call(REVIEWER_TOKEN, "create_connection", {"task_id": "task-1", "agent_name": "synthetic-agent"})
    service.agent_call(grant["token"], "submit_batch", batch)
    facade = NativeReviewFacade(service, REVIEWER_TOKEN, root)
    try:
        edited = copy.deepcopy(facade.load_batch("task-1", "batch-1")["batch"])
        edited["steps"][0].update(start_state="interface-2", arrival_state="interface-2", target_region_id="region-2")
        facade.save_revision("task-1", "batch-1", 0, edited)
        view = facade.request_relearn("task-1", "batch-1", 1, 0, {"interface_ids": ["interface-2"], "relationship_ids": []}, "只复核人工改到第二界面的步骤", "moved-start")
        issue = view["issues"][0]
        proposal = {
            "contract_version": "agent_link_v1", "idempotency_key": "new-source-target",
            "batch_id": "batch-1", "issue_id": issue["issue_id"], "baseline_revision": 1,
            "review_baseline_sha256": issue["review_baseline_sha256"], "scope": issue["scope"],
            "changes": [{"change_type": "step", "step_id": "step-1", "action_type": "back", "target_region_id": "region-2", "expected_result": "显示上一层"}],
        }
        candidate = service.agent_call(grant["token"], "submit_candidate", proposal)
        wrong = copy.deepcopy(proposal)
        wrong["idempotency_key"] = "wrong-old-target"
        wrong["changes"][0]["target_region_id"] = "region-1"
        with pytest.raises(AgentLinkError, match="step change"):
            service.agent_call(grant["token"], "submit_candidate", wrong)
        expected = facade.compare_relearn_candidate("task-1", "batch-1", 1, candidate["candidate_id"])
        assert expected["status"] == "current"
        assert expected["blocked_reasons"] == []
    finally:
        facade.close(); store.close()
    restarted = AgentLinkStore(path)
    loaded = NativeReviewFacade(AgentLinkService(restarted, REVIEWER_TOKEN), REVIEWER_TOKEN, root)
    try:
        assert loaded.compare_relearn_candidate("task-1", "batch-1", 1, candidate["candidate_id"]) == expected
    finally:
        loaded.close(); restarted.close()
