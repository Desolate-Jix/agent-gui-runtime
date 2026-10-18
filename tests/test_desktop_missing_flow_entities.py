from __future__ import annotations

import copy
import hashlib
import json
import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.agent_link.contracts import AgentLinkError
from app.desktop_review.workspace import NativeReviewFacade
from app.desktop_review.workspace import DesktopReviewError
from test_desktop_flow_candidates import _setup
from test_agent_link_flow_candidates import REVIEWER_TOKEN


def _changes():
    return [
        {"change_type":"relationships_add","relationships":[{"relationship_id":"new-rel","from_interface_id":"i1","to_interface_id":"i2","kind":"新增"}]},
        {"change_type":"steps_add","after_step_id":None,"steps":[{"step_id":"new-step","action_type":"open_detail","target_region_id":"r1","start_state":"i1","arrival_state":"i2","prerequisites":["已选"],"expected_result":"显示","stop_condition":"停止"}]},
    ]


def _submitted(service, grant, facade, changes=None):
    view = facade.request_relearn("task-flow", "flow-batch", 1, 0,
        {"interface_ids": ["i1", "i2"], "relationship_ids": []}, "遗漏步骤与关系", "feedback-new")
    issue = view["issues"][-1]
    payload = {"contract_version": "agent_link_v1", "idempotency_key": "entities-new", "batch_id": "flow-batch",
               "issue_id": issue["issue_id"], "baseline_revision": 1, "review_baseline_sha256": issue["review_baseline_sha256"],
               "scope": issue["scope"], "changes": changes or _changes()}
    candidate = service.agent_call(grant["token"], "submit_candidate", payload)
    comparison = facade.compare_relearn_candidate("task-flow", "flow-batch", 1, candidate["candidate_id"])
    return payload, candidate, comparison


def _adopt(facade, candidate, comparison):
    return facade.adopt_relearn_candidate("task-flow", "flow-batch", 1, candidate["candidate_id"],
        comparison["candidate_sha256"], comparison["review_baseline_sha256"], "adopt-new")


def _artifacts(facade):
    return {str(path.relative_to(facade._artifact_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in facade._artifact_root.rglob("*") if path.is_file()
            and path != facade._workspace_root / ".owner.lock"}


@pytest.mark.parametrize("action", ["final_submit", "send", "invented_action"])
def test_new_step_dangerous_and_unknown_actions_are_blocked_without_writes(tmp_path, action):
    _, _, store, service, grant, facade, saved = _setup(tmp_path)
    try:
        changes = _changes()
        changes[1]["steps"][0]["action_type"] = action
        _, candidate, comparison = _submitted(service, grant, facade, changes)
        assert comparison["status"] == "blocked"
        assert any("action:new-step:" + action in reason for reason in comparison["blocked_reasons"])
        before = _artifacts(facade)
        with pytest.raises(DesktopReviewError):
            _adopt(facade, candidate, comparison)
        assert facade.load_batch("task-flow", "flow-batch") == saved and _artifacts(facade) == before
    finally:
        facade.close(); store.close()


def test_agent_cannot_forge_flow_baseline_or_use_reviewer_role(tmp_path):
    _, _, store, service, grant, facade, _ = _setup(tmp_path)
    try:
        payload, _, _ = _submitted(service, grant, facade)
        before = service.reviewer_call(REVIEWER_TOKEN, "get_batch", {"task_id": "task-flow", "batch_id": "flow-batch"})
        for mutation in ("missing", "foreign", "body"):
            invalid = copy.deepcopy(payload)
            invalid["idempotency_key"] = "invalid-" + mutation
            if mutation == "missing":
                invalid.pop("review_baseline_sha256")
            elif mutation == "foreign":
                invalid["review_baseline_sha256"] = "0" * 64
            else:
                invalid["review_baseline"] = {}
            with pytest.raises(AgentLinkError):
                service.agent_call(grant["token"], "submit_candidate", invalid)
        with pytest.raises(AgentLinkError):
            service.agent_call(grant["token"], "record_feedback", {})
        assert service.reviewer_call(REVIEWER_TOKEN, "get_batch", {"task_id": "task-flow", "batch_id": "flow-batch"}) == before
    finally:
        facade.close(); store.close()


def test_current_collision_has_entity_evidence_for_both_new_types_and_cannot_adopt(tmp_path):
    _, _, store, service, grant, facade, _ = _setup(tmp_path)
    try:
        payload, first, comparison = _submitted(service, grant, facade)
        payload["idempotency_key"] = "second-colliding"
        second = service.agent_call(grant["token"], "submit_candidate", payload)
        saved = _adopt(facade, first, comparison)["snapshot"]
        collision = facade.compare_relearn_candidate("task-flow", "flow-batch", 2, second["candidate_id"])
        assert collision["status"] == "stale"
        for kind, identity in (("step", "new-step"), ("relationship", "new-rel")):
            diff = next(d for d in collision["diffs"] if d["target_type"] == kind)
            assert diff["baseline"] is None and diff["current"] is not None
            assert f"reference_drift:{kind}:{identity}:entity" in collision["blocked_reasons"]
        with pytest.raises(DesktopReviewError):
            facade.adopt_relearn_candidate("task-flow", "flow-batch", 2, second["candidate_id"],
                collision["candidate_sha256"], collision["review_baseline_sha256"], "collision-adopt")
        assert facade.load_batch("task-flow", "flow-batch") == saved
    finally:
        facade.close(); store.close()


def test_bad_flow_origin_is_rejected_before_writes_and_missing_origin_chain_rejected(tmp_path, monkeypatch):
    path, root, store, service, grant, facade, saved = _setup(tmp_path)
    try:
        _, candidate, comparison = _submitted(service, grant, facade)
        before = _artifacts(facade)
        assert before and any(name.endswith("workspace.json") for name in before) and any(name.endswith(".png") for name in before)
        original_save = facade._save_revision_locked
        def tamper(*args, **kwargs):
            kwargs["relearn_adoption"]["candidate_sha256"] = "0" * 64
            return original_save(*args, **kwargs)
        with monkeypatch.context() as context:
            context.setattr(facade, "_save_revision_locked", tamper)
            with pytest.raises(DesktopReviewError):
                _adopt(facade, candidate, comparison)
        assert _artifacts(facade) == before and facade.load_batch("task-flow", "flow-batch") == saved
        adopted = _adopt(facade, candidate, comparison)["snapshot"]
        assert adopted["batch"]["screenshots"] == saved["batch"]["screenshots"]
        current = facade._workspace_dir("task-flow", "flow-batch") / "current.json"
        manifest = json.loads(current.read_text(encoding="utf-8"))
        child = facade._artifact_root / manifest["workspace_path"]
        snapshot = json.loads(child.read_text(encoding="utf-8"))
        snapshot["relearn_adoption"] = None
        raw = (json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        child.write_bytes(raw)
        manifest["workspace_sha256"] = hashlib.sha256(raw).hexdigest()
        current.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        facade.close(); store.close()
        store = AgentLinkStore(path)
        facade = NativeReviewFacade(AgentLinkService(store, REVIEWER_TOKEN), REVIEWER_TOKEN, root)
        with pytest.raises(DesktopReviewError):
            facade.load_batch("task-flow", "flow-batch")
    finally:
        facade.close(); store.close()


def test_service_compare_adopt_reopen_and_next_feedback_entities(tmp_path):
    path, root, store, service, grant, facade, saved = _setup(tmp_path)
    try:
        view=facade.request_relearn("task-flow","flow-batch",1,0,{"interface_ids":["i1","i2"],"relationship_ids":["rel-12"]},"补齐流程","flow-add")
        issue=view["issues"][-1]
        receipt=service.agent_call(grant["token"],"submit_candidate",{"contract_version":"agent_link_v1","idempotency_key":"flow-entity","batch_id":"flow-batch","issue_id":issue["issue_id"],"baseline_revision":1,"review_baseline_sha256":issue["review_baseline_sha256"],"scope":issue["scope"],"changes":_changes()})
        comparison=facade.compare_relearn_candidate("task-flow","flow-batch",1,receipt["candidate_id"])
        assert comparison["status"] == "current"
        adopted=facade.adopt_relearn_candidate("task-flow","flow-batch",1,receipt["candidate_id"],comparison["candidate_sha256"],comparison["review_baseline_sha256"],"adopt-flow-entity")
        batch=adopted["snapshot"]["batch"]
        assert batch["steps"][0]["step_id"] == "new-step" and batch["relationships"][-1]["relationship_id"] == "new-rel"
        for mutate in ("step-add","step-delete","relation-reorder", "relation-add", "relation-delete"):
            invalid=copy.deepcopy(batch)
            if mutate=="step-add": invalid["steps"].append(copy.deepcopy(invalid["steps"][0]) | {"step_id":"ordinary"})
            elif mutate=="step-delete": invalid["steps"].pop(0)
            elif mutate=="relation-add": invalid["relationships"].append(copy.deepcopy(invalid["relationships"][-1]) | {"relationship_id":"ordinary"})
            elif mutate=="relation-delete": invalid["relationships"].pop()
            else: invalid["relationships"][:]=invalid["relationships"][::-1]
            with pytest.raises(DesktopReviewError): facade.save_revision("task-flow","flow-batch",2,invalid)
            assert facade.load_batch("task-flow", "flow-batch") == adopted["snapshot"]
        saved2=facade.save_revision("task-flow","flow-batch",2,copy.deepcopy(batch))
        facade.close(); store.close()
        store = AgentLinkStore(path)
        service = AgentLinkService(store, REVIEWER_TOKEN)
        facade = NativeReviewFacade(service, REVIEWER_TOKEN, root)
        assert facade.load_batch("task-flow", "flow-batch") == saved2
        nextv=facade.request_relearn("task-flow","flow-batch",3,1,{"interface_ids":["i1","i2"],"relationship_ids":["rel-12","new-rel"]},"继续","next-flow")
        nxt=nextv["issues"][-1]
        follow=service.agent_call(grant["token"],"submit_candidate",{"contract_version":"agent_link_v1","idempotency_key":"next-flow","batch_id":"flow-batch","issue_id":nxt["issue_id"],"baseline_revision":2,"review_baseline_sha256":nxt["review_baseline_sha256"],"scope":nxt["scope"],"changes":[{"change_type":"semantic","target_type":"step","target_id":"new-step","meaning":"下一轮"},{"change_type":"relationship","relationship_id":"new-rel","kind":"下一轮关系"}]})
        assert facade.compare_relearn_candidate("task-flow","flow-batch",3,follow["candidate_id"])["status"]=="current"
        assert facade.load_batch("task-flow","flow-batch")["batch"]==saved2["batch"]
    finally:
        facade.close();store.close()
