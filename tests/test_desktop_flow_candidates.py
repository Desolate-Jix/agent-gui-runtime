from __future__ import annotations

import copy

import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.agent_link.candidate_projection import (
    CandidateProjectionError,
    apply_candidate_diffs,
)
from app.desktop_review.exact_review import ExactReviewError
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from test_agent_link_flow_candidates import REVIEWER_TOKEN, flow_batch, flow_changes


_APPLICATION = {
    "kind": "native", "display_name": "Flow Editor",
    "executable_identity": "flow-editor.exe", "product_name": "Flow Product",
}


def _setup(tmp_path):
    path, root = tmp_path / "inbox.json", tmp_path / "review-data"
    store = AgentLinkStore(path)
    service = AgentLinkService(store, REVIEWER_TOKEN)
    grant = service.reviewer_call(REVIEWER_TOKEN, "create_connection", {
        "task_id": "task-flow", "agent_name": "synthetic-agent",
    })
    service.agent_call(grant["token"], "submit_batch", flow_batch())
    facade = NativeReviewFacade(service, REVIEWER_TOKEN, root)
    initial = facade.load_batch("task-flow", "flow-batch")
    saved = facade.save_revision(
        "task-flow", "flow-batch", 0, copy.deepcopy(initial["batch"])
    )
    return path, root, store, service, grant, facade, saved


def _submit(service, grant, facade, *, changes=None, key="candidate"):
    view = facade.request_relearn(
        "task-flow", "flow-batch", 1, 0,
        {"interface_ids": ["i1", "i2"], "relationship_ids": ["rel-12"]},
        "核对完整流程", "request",
    )
    issue = view["issues"][0]
    receipt = service.agent_call(grant["token"], "submit_candidate", {
        "contract_version": "agent_link_v1", "idempotency_key": key,
        "batch_id": "flow-batch", "issue_id": issue["issue_id"],
        "baseline_revision": 1,
        "review_baseline_sha256": issue["review_baseline_sha256"],
        "scope": issue["scope"],
        "changes": flow_changes() if changes is None else changes,
    })
    comparison = facade.compare_relearn_candidate(
        "task-flow", "flow-batch", 1, receipt["candidate_id"]
    )
    return issue, receipt, comparison


def test_full_flow_compare_adopt_restart_and_new_baseline_roundtrip(tmp_path):
    path, root, store, service, grant, facade, _ = _setup(tmp_path)
    prepared = facade.prepare_exact_review("task-flow", "flow-batch", 1, _APPLICATION)
    approved = facade.record_review_decisions(
        prepared["review_ref"], prepared["approval_revision"],
        [subject["subject_id"] for subject in prepared["subjects"]],
    )
    issue, candidate, comparison = _submit(service, grant, facade)
    assert comparison["status"] == "current"
    assert comparison["blocked_reasons"] == []
    by_key = {
        (diff["target_type"], diff["target_id"], diff["field"]): diff
        for diff in comparison["diffs"]
    }
    assert len(by_key) == 11
    for field in (
        "action_type", "target_region_id", "start_state", "arrival_state",
        "prerequisites", "expected_result", "stop_condition",
    ):
        assert ("step", "s1", field) in by_key
    for field in ("from_interface_id", "to_interface_id", "kind"):
        assert ("relationship", "rel-12", field) in by_key
    order = by_key[("batch", "flow-batch", "step_order")]
    assert order["baseline"] == ["s1", "outside", "s2", "s3"]
    assert order["current"] == order["baseline"]
    assert order["proposed"] == ["s3", "outside", "s1", "s2"]

    adopted = facade.adopt_relearn_candidate(
        "task-flow", "flow-batch", 1, candidate["candidate_id"],
        comparison["candidate_sha256"], comparison["review_baseline_sha256"],
        "adopt-flow",
    )
    batch = adopted["snapshot"]["batch"]
    assert [step["step_id"] for step in batch["steps"]] == ["s3", "outside", "s1", "s2"]
    changed_step = next(step for step in batch["steps"] if step["step_id"] == "s1")
    assert {field: changed_step[field] for field in (
        "action_type", "target_region_id", "start_state", "arrival_state",
        "prerequisites", "expected_result", "stop_condition",
    )} == {
        "action_type": "open_link", "target_region_id": "r2",
        "start_state": "i2", "arrival_state": "i1",
        "prerequisites": ["已经选择目标文件"],
        "expected_result": "详情面板显示所选文件",
        "stop_condition": "目标或详情不一致则停止",
    }
    assert batch["relationships"][0] == {
        "relationship_id": "rel-12", "from_interface_id": "i2",
        "to_interface_id": "i1", "kind": "返回详情",
    }
    with pytest.raises(ExactReviewError):
        facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])

    facade.close(); store.close()
    reopened_store = AgentLinkStore(path)
    reopened = NativeReviewFacade(
        AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN, root
    )
    try:
        assert reopened.load_batch("task-flow", "flow-batch") == adopted["snapshot"]
        retry = reopened.adopt_relearn_candidate(
            "task-flow", "flow-batch", 1, candidate["candidate_id"],
            comparison["candidate_sha256"], comparison["review_baseline_sha256"],
            "adopt-flow",
        )
        assert retry["snapshot"] == adopted["snapshot"]
        new_view = reopened.request_relearn(
            "task-flow", "flow-batch", 2, 1,
            {"interface_ids": ["i1", "i2"], "relationship_ids": ["rel-12"]},
            "复核新顺序", "request-new-order",
        )
        assert [
            step["step_id"] for step in new_view["issues"][-1]["review_baseline"]["batch"]["steps"]
        ] == ["s3", "outside", "s1", "s2"]
    finally:
        reopened.close(); reopened_store.close()


def test_direct_manual_step_reorder_preserves_identity_and_persists(tmp_path):
    _, _, store, _, _, facade, saved = _setup(tmp_path)
    try:
        edited = copy.deepcopy(saved["batch"])
        edited["steps"] = [edited["steps"][2], edited["steps"][0], edited["steps"][1], edited["steps"][3]]
        revision = facade.save_revision("task-flow", "flow-batch", 1, edited)
        assert [step["step_id"] for step in revision["batch"]["steps"]] == ["s2", "s1", "outside", "s3"]
        assert facade.load_batch("task-flow", "flow-batch") == revision
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("action", ["final_submit", "unknown_action_xyz"])
def test_dangerous_and_unknown_step_flow_are_blocked_and_not_adopted(tmp_path, action):
    _, _, store, service, grant, facade, saved = _setup(tmp_path)
    try:
        change = flow_changes()[0]
        change.update(action_type=action)
        _, candidate, comparison = _submit(service, grant, facade, changes=[change])
        assert comparison["status"] == "blocked"
        assert any("action" in reason for reason in comparison["blocked_reasons"])
        with pytest.raises(DesktopReviewError):
            facade.adopt_relearn_candidate(
                "task-flow", "flow-batch", 1, candidate["candidate_id"],
                comparison["candidate_sha256"], comparison["review_baseline_sha256"],
                "blocked-adoption",
            )
        assert facade.load_batch("task-flow", "flow-batch") == saved
    finally:
        facade.close(); store.close()


def test_no_effect_scoped_order_is_blocked(tmp_path):
    _, _, store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, _, comparison = _submit(
            service, grant, facade,
            changes=[{"change_type": "step_order", "step_ids": ["s1", "s2", "s3"]}],
        )
        assert comparison["status"] == "blocked"
        assert any("no_effect" in reason for reason in comparison["blocked_reasons"])
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("mutation", ["wrong_current", "duplicate", "missing", "new", "unknown"])
def test_shared_apply_is_immutable_and_rejects_malformed_full_order(tmp_path, mutation):
    _, _, store, _, _, facade, saved = _setup(tmp_path)
    try:
        batch = saved["batch"]
        original = copy.deepcopy(batch)
        current = [step["step_id"] for step in batch["steps"]]
        diff = {
            "target_type": "batch", "target_id": "flow-batch", "field": "step_order",
            "baseline": copy.deepcopy(current), "current": copy.deepcopy(current),
            "proposed": ["s3", "outside", "s2", "s1"],
        }
        diffs = [diff]
        if mutation == "wrong_current":
            diff["current"] = [True, "outside", "s2", "s3"]
        elif mutation == "duplicate":
            diffs.append(copy.deepcopy(diff))
        elif mutation == "missing":
            diff["proposed"] = ["s3", "outside", "s2"]
        elif mutation == "new":
            diff["proposed"] = ["s3", "outside", "s2", "new"]
        else:
            diff.update(target_type="step", target_id="s1", field="authority")
        with pytest.raises(CandidateProjectionError):
            apply_candidate_diffs(batch, diffs)
        assert batch == original
    finally:
        facade.close(); store.close()
