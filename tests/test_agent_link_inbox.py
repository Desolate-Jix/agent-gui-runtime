from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO

import pytest
from PIL import Image


def _png_base64() -> str:
    image = Image.new("RGB", (16, 12), "white")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def _batch(batch_id: str = "batch-a", key: str = "batch-key") -> dict:
    return {
        "contract_version": "agent_link_v1", "idempotency_key": key, "batch_id": batch_id,
        "title": "\u5217\u8868\u5230\u8be6\u60c5", "learning_outcome": "completed",
        "screenshots": [{"screenshot_id": "screen-list", "png_base64": _png_base64()}, {"screenshot_id": "screen-detail", "png_base64": _png_base64()}],
        "interfaces": [
            {"interface_id": "interface-list", "screenshot_id": "screen-list", "meaning": "\u5217\u8868", "regions": [{"region_id": "region-row", "bbox": [0, 0, 16, 12], "name": "\u5217\u8868\u884c", "kind": "item", "meaning": "\u6253\u5f00\u8be6\u60c5"}]},
            {"interface_id": "interface-detail", "screenshot_id": "screen-detail", "meaning": "\u8be6\u60c5", "regions": [{"region_id": "region-title", "bbox": [1, 1, 8, 6], "label": "\u6807\u9898", "type": "text", "meaning": "\u8be6\u60c5\u6807\u9898"}]},
        ],
        "relationships": [{"relationship_id": "rel-a", "from_interface_id": "interface-list", "to_interface_id": "interface-detail", "kind": "opens_detail"}],
        "steps": [{"step_id": "step-a", "action_type": "open_detail", "target_region_id": "region-row", "start_state": "interface-list", "arrival_state": "interface-detail", "prerequisites": ["row_visible"], "expected_result": "detail_visible", "stop_condition": "stop_before_submit"}],
        "issues": [{"issue_id": "reported-a", "region_id": "region-row", "description": "\u672a\u53d7\u4fe1\u4efb"}],
    }

def _connection(service, task_id="task-a", name="sample"):
    return service.reviewer_call("reviewer-secret-value-123", "create_connection", {"task_id": task_id, "agent_name": name})


def test_batch_feedback_candidate_survive_restart(tmp_path):
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    path = tmp_path / "inbox.json"
    store = AgentLinkStore(path)
    service = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    grant = _connection(service)
    assert grant["task_id"] == "task-a"
    assert "token" in grant
    batch_receipt = service.agent_call(grant["token"], "submit_batch", _batch())
    assert batch_receipt["status"] == "pending_review_proposal"
    feedback = service.reviewer_call("reviewer-secret-value-123", "record_feedback", {
        "task_id": "task-a", "batch_id": "batch-a", "idempotency_key": "feedback-key", "expected_revision": 0,
        "notes": [{"note_id": "note-a", "text": "\u9700\u8981\u4fee\u6539"}],
        "issues": [{"issue_id": "issue-a", "scope": {"interface_ids": ["interface-list"], "relationship_ids": ["rel-a"]}, "message": "\u4fee\u6539\u6846\u9009\u62e9"}],
    })
    assert feedback["revision"] == 1
    visible = service.agent_call(grant["token"], "read_feedback", {"batch_id": "batch-a"})
    assert visible["revision"] == 1
    candidate = service.agent_call(grant["token"], "submit_candidate", {
        "contract_version": "agent_link_v1", "idempotency_key": "candidate-key", "batch_id": "batch-a",
        "issue_id": "issue-a", "baseline_revision": 1,
        "scope": {"interface_ids": ["interface-list"], "relationship_ids": ["rel-a"]},
        "changes": [{"change_type": "geometry", "region_id": "region-row", "bbox": [0, 0, 15, 11]}],
    })
    assert candidate["status"] == "pending_review_proposal"
    store.close()

    restarted = AgentLinkStore(path)
    reloaded = AgentLinkService(restarted, reviewer_token="reviewer-secret-value-123")
    assert reloaded.agent_call(grant["token"], "read_feedback", {"batch_id": "batch-a"})["revision"] == 1
    restarted.close()


def test_scopes_idempotency_and_revocation_are_enforced(tmp_path):
    from app.agent_link.contracts import AgentLinkError
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    first, second = _connection(service), _connection(service, "task-b", "other")
    receipt = service.agent_call(first["token"], "submit_batch", _batch())
    assert service.agent_call(first["token"], "submit_batch", _batch()) == receipt
    changed = _batch(); changed["title"] = "different"
    with pytest.raises(AgentLinkError, match="idempotency"):
        service.agent_call(first["token"], "submit_batch", changed)
    with pytest.raises(AgentLinkError, match="not found"):
        service.agent_call(second["token"], "read_feedback", {"batch_id": "batch-a"})
    with pytest.raises(AgentLinkError, match="reviewer"):
        service.agent_call(first["token"], "create_connection", {"task_id": "x", "agent_name": "x"})
    service.reviewer_call("reviewer-secret-value-123", "revoke_connection", {"connection_id": first["connection_id"], "idempotency_key": "revoke"})
    with pytest.raises(AgentLinkError, match="revoked"):
        service.agent_call(first["token"], "status", {})
    store.close()
    reopened = AgentLinkStore(tmp_path / "inbox.json")
    with pytest.raises(AgentLinkError, match="revoked"):
        AgentLinkService(reopened, reviewer_token="reviewer-secret-value-123").agent_call(first["token"], "status", {})
    reopened.close()


def test_rejects_stale_unknown_and_malformed_external_data(tmp_path):
    from app.agent_link.contracts import AgentLinkError
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    grant = _connection(service)
    invalid = _batch(); invalid["screenshots"][0]["png_base64"] = base64.b64encode(b"not png").decode()
    with pytest.raises(AgentLinkError, match="PNG"):
        service.agent_call(grant["token"], "submit_batch", invalid)
    service.agent_call(grant["token"], "submit_batch", _batch())
    with pytest.raises(AgentLinkError, match="contract"):
        service.agent_call(grant["token"], "submit_batch", {**_batch("batch-b", "b"), "authority": "approved"})
    feedback = service.reviewer_call("reviewer-secret-value-123", "record_feedback", {
        "task_id": "task-a", "batch_id": "batch-a", "idempotency_key": "feedback", "expected_revision": 0, "notes": [],
        "issues": [{"issue_id": "issue-a", "scope": {"interface_ids": ["interface-list"], "relationship_ids": []}, "message": "fix"}],
    })
    service.reviewer_call("reviewer-secret-value-123", "withdraw_issue", {"task_id": "task-a", "batch_id": "batch-a", "issue_id": "issue-a", "expected_revision": feedback["revision"], "idempotency_key": "withdraw"})
    with pytest.raises(AgentLinkError, match="withdrawn"):
        service.agent_call(grant["token"], "submit_candidate", {"contract_version": "agent_link_v1", "idempotency_key": "candidate", "batch_id": "batch-a", "issue_id": "issue-a", "baseline_revision": 1, "scope": {"interface_ids": ["interface-list"], "relationship_ids": []}, "changes": [{"change_type": "geometry", "region_id": "region-row", "bbox": [0, 0, 15, 11]}]})
    store.close()


def test_corrupt_store_is_never_reset(tmp_path):
    from app.agent_link.contracts import AgentLinkError
    from app.agent_link.store import AgentLinkStore

    path = tmp_path / "broken.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(AgentLinkError, match="corrupt"):
        AgentLinkStore(path)


def test_reviewer_get_batch_keeps_original_feedback_history_and_candidates(tmp_path):
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    grant = _connection(service)
    original = _batch()
    service.agent_call(grant["token"], "submit_batch", original)
    first = service.reviewer_call("reviewer-secret-value-123", "record_feedback", {"task_id": "task-a", "batch_id": "batch-a", "idempotency_key": "f1", "expected_revision": 0, "notes": [{"note_id": "n1", "text": "first"}], "issues": [{"issue_id": "issue-a", "scope": {"interface_ids": ["interface-list"], "relationship_ids": ["rel-a"]}, "message": "fix"}]})
    assert first["revision"] == 1
    second = service.reviewer_call("reviewer-secret-value-123", "record_feedback", {"task_id": "task-a", "batch_id": "batch-a", "idempotency_key": "f2", "expected_revision": 1, "notes": [{"note_id": "n2", "text": "second"}], "issues": []})
    assert second["revision"] == 2
    detail = service.reviewer_call("reviewer-secret-value-123", "get_batch", {"task_id": "task-a", "batch_id": "batch-a"})
    assert detail["batch"]["interfaces"][0]["regions"][0]["meaning"] == "\u6253\u5f00\u8be6\u60c5"
    assert [entry["revision"] for entry in detail["feedback_history"]] == [1, 2]
    assert detail["candidates"] == []
    store.close()


def test_shared_store_serializes_revoke_after_inflight_write(tmp_path, monkeypatch):
    import threading
    from app.agent_link.contracts import AgentLinkError
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    store = AgentLinkStore(tmp_path / "inbox.json")
    one = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    two = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    grant = one.reviewer_call("reviewer-secret-value-123", "create_connection", {"task_id": "task-a", "agent_name": "sample"})
    entered, release = threading.Event(), threading.Event()
    original = store._write_state
    calls = 0
    def paused(state):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set(); assert release.wait(3)
        original(state)
    monkeypatch.setattr(store, "_write_state", paused)
    worker = threading.Thread(target=lambda: one.agent_call(grant["token"], "submit_batch", _batch()), daemon=True)
    worker.start(); assert entered.wait(3)
    revoker = threading.Thread(target=lambda: two.reviewer_call("reviewer-secret-value-123", "revoke_connection", {"connection_id": grant["connection_id"], "idempotency_key": "revoke"}), daemon=True)
    revoker.start(); release.set(); worker.join(3); revoker.join(3)
    assert not worker.is_alive() and not revoker.is_alive()
    assert store.snapshot()["connections"][grant["connection_id"]]["revoked"] is True
    assert any("revoke_connection" in key for key in store.snapshot()["idempotency"])
    with pytest.raises(AgentLinkError, match="revoked"):
        one.agent_call(grant["token"], "status", {})
    store.close()


def test_nested_corrupt_state_releases_owner_lock(tmp_path):
    import json
    from app.agent_link.contracts import AgentLinkError
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    path = tmp_path / "inbox.json"
    store = AgentLinkStore(path)
    service = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    grant = service.reviewer_call("reviewer-secret-value-123", "create_connection", {"task_id": "task-a", "agent_name": "sample"})
    store.close()
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["connections"][grant["connection_id"]]["revoked"] = 0
    payload["connections"][grant["connection_id"]]["authority"] = "approved"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AgentLinkError, match="corrupt"):
        AgentLinkStore(path)
    payload["connections"][grant["connection_id"]].pop("authority"); payload["connections"][grant["connection_id"]]["revoked"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    recovered = AgentLinkStore(path)
    assert recovered.snapshot()["connections"][grant["connection_id"]]["revoked"] is False
    recovered.close()


def test_failed_atomic_write_never_publishes_memory(tmp_path, monkeypatch):
    from app.agent_link.contracts import AgentLinkError
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    grant = service.reviewer_call("reviewer-secret-value-123", "create_connection", {"task_id": "task-a", "agent_name": "sample"})
    monkeypatch.setattr(store, "_write_state", lambda state: (_ for _ in ()).throw(AgentLinkError("persistence_failed", "inbox update was not persisted")))
    with pytest.raises(AgentLinkError, match="persisted"):
        service.agent_call(grant["token"], "submit_batch", _batch())
    assert store.snapshot()["batches"] == {}
    store.close()


def test_loader_rejects_tampered_candidate_scope_and_receipt(tmp_path):
    import json
    from app.agent_link.contracts import AgentLinkError
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    path = tmp_path / "inbox.json"; store = AgentLinkStore(path); service = AgentLinkService(store, reviewer_token="reviewer-secret-value-123")
    grant = _connection(service); service.agent_call(grant["token"], "submit_batch", _batch())
    service.reviewer_call("reviewer-secret-value-123", "record_feedback", {"task_id":"task-a", "batch_id":"batch-a", "idempotency_key":"feedback", "expected_revision":0, "notes":[], "issues":[{"issue_id":"issue-a", "scope":{"interface_ids":["interface-list"], "relationship_ids":["rel-a"]}, "message":"fix"}]})
    service.agent_call(grant["token"], "submit_candidate", {"contract_version":"agent_link_v1", "idempotency_key":"candidate", "batch_id":"batch-a", "issue_id":"issue-a", "baseline_revision":1, "scope":{"interface_ids":["interface-list"], "relationship_ids":["rel-a"]}, "changes":[{"change_type":"geometry", "region_id":"region-row", "bbox":[0,0,15,11]}]})
    store.close(); payload=json.loads(path.read_text(encoding="utf-8")); candidate=next(iter(payload["candidates"].values())); candidate["scope"]={"interface_ids":["interface-detail"],"relationship_ids":[]}; candidate["changes"][0]["region_id"]="region-title"
    path.write_text(json.dumps(payload),encoding="utf-8")
    with pytest.raises(AgentLinkError, match="corrupt"): AgentLinkStore(path)
    candidate["scope"]={"interface_ids":["interface-list"],"relationship_ids":["rel-a"]}; candidate["changes"][0]["region_id"]="region-row"
    receipt_key=next(key for key in payload["idempotency"] if "submit_batch" in key); payload["idempotency"][receipt_key]["receipt"]={"contract_version":"agent_link_v1","batch_id":"batch-a","status":"approved","staging_only":False,"authority":"reviewed"}
    path.write_text(json.dumps(payload),encoding="utf-8")
    with pytest.raises(AgentLinkError, match="corrupt"): AgentLinkStore(path)


def test_steps_issues_and_incomplete_outcomes_have_strict_contract(tmp_path):
    import copy
    from app.agent_link.contracts import AgentLinkError
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    store=AgentLinkStore(tmp_path / "inbox.json"); service=AgentLinkService(store, reviewer_token="reviewer-secret-value-123"); grant=_connection(service)
    duplicate_step=_batch(); duplicate_step["steps"].append(copy.deepcopy(duplicate_step["steps"][0]))
    with pytest.raises(AgentLinkError): service.agent_call(grant["token"], "submit_batch", duplicate_step)
    duplicate_issue=_batch(); duplicate_issue["issues"].append(copy.deepcopy(duplicate_issue["issues"][0]))
    with pytest.raises(AgentLinkError): service.agent_call(grant["token"], "submit_batch", duplicate_issue)
    incomplete=_batch("partial-a", "partial-key"); incomplete["learning_outcome"]="partial"; incomplete["outcome_reason"]="stopped before screenshots"; incomplete["screenshots"]=[]; incomplete["interfaces"]=[]; incomplete["relationships"]=[]; incomplete["steps"]=[]; incomplete["issues"]=[]
    receipt=service.agent_call(grant["token"], "submit_batch", incomplete)
    assert receipt["learning_outcome"] == "partial" and receipt["incomplete"] is True
    store.close()


def test_withdrawal_transitions_candidates_to_reloadable_states(tmp_path):
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore
    path=tmp_path/"inbox.json"; store=AgentLinkStore(path); service=AgentLinkService(store, reviewer_token="reviewer-secret-value-123"); grant=_connection(service)
    service.agent_call(grant["token"],"submit_batch",_batch())
    service.reviewer_call("reviewer-secret-value-123","record_feedback",{"task_id":"task-a","batch_id":"batch-a","idempotency_key":"f1","expected_revision":0,"notes":[],"issues":[{"issue_id":"i1","scope":{"interface_ids":["interface-list"],"relationship_ids":["rel-a"]},"message":"x"},{"issue_id":"i2","scope":{"interface_ids":["interface-list"],"relationship_ids":["rel-a"]},"message":"y"}]})
    for issue,key in (("i1","c1"),("i2","c2")):
        service.agent_call(grant["token"],"submit_candidate",{"contract_version":"agent_link_v1","idempotency_key":key,"batch_id":"batch-a","issue_id":issue,"baseline_revision":1,"scope":{"interface_ids":["interface-list"],"relationship_ids":["rel-a"]},"changes":[{"change_type":"geometry","region_id":"region-row","bbox":[0,0,15,11]}]})
    service.reviewer_call("reviewer-secret-value-123","withdraw_issue",{"task_id":"task-a","batch_id":"batch-a","issue_id":"i1","expected_revision":1,"idempotency_key":"w"})
    store.close(); reopened=AgentLinkStore(path); reloaded=AgentLinkService(reopened,reviewer_token="reviewer-secret-value-123")
    detail=reloaded.reviewer_call("reviewer-secret-value-123","get_batch",{"task_id":"task-a","batch_id":"batch-a"})
    assert sorted(item["status"] for item in detail["candidates"]) == ["stale","withdrawn"]
    reloaded.reviewer_call("reviewer-secret-value-123","record_feedback",{"task_id":"task-a","batch_id":"batch-a","idempotency_key":"f2","expected_revision":2,"notes":[],"issues":[]})
    reloaded.reviewer_call("reviewer-secret-value-123","withdraw_issue",{"task_id":"task-a","batch_id":"batch-a","issue_id":"i2","expected_revision":3,"idempotency_key":"w2"})
    reopened.close()
    reopened=AgentLinkStore(path)
    assert all(item["status"] == "withdrawn" for item in reopened.snapshot()["candidates"].values())
    reopened.close()


def test_step_change_requires_original_step_scope_and_start_interface(tmp_path):
    import copy
    from app.agent_link.contracts import AgentLinkError
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore
    store=AgentLinkStore(tmp_path/"inbox.json"); service=AgentLinkService(store,reviewer_token="reviewer-secret-value-123"); grant=_connection(service); service.agent_call(grant["token"],"submit_batch",_batch())
    service.reviewer_call("reviewer-secret-value-123","record_feedback",{"task_id":"task-a","batch_id":"batch-a","idempotency_key":"f","expected_revision":0,"notes":[],"issues":[{"issue_id":"detail","scope":{"interface_ids":["interface-detail"],"relationship_ids":[]},"message":"x"}]})
    with pytest.raises(AgentLinkError,match="scope"):
        service.agent_call(grant["token"],"submit_candidate",{"contract_version":"agent_link_v1","idempotency_key":"bad-step","batch_id":"batch-a","issue_id":"detail","baseline_revision":1,"scope":{"interface_ids":["interface-detail"],"relationship_ids":[]},"changes":[{"change_type":"step","step_id":"step-a","action_type":"open_detail","target_region_id":"region-title","expected_result":"x"}]})
    service.reviewer_call("reviewer-secret-value-123","record_feedback",{"task_id":"task-a","batch_id":"batch-a","idempotency_key":"f2","expected_revision":1,"notes":[],"issues":[{"issue_id":"list","scope":{"interface_ids":["interface-list","interface-detail"],"relationship_ids":[]},"message":"fix step"}]})
    candidate={"contract_version":"agent_link_v1","idempotency_key":"valid-step","batch_id":"batch-a","issue_id":"list","baseline_revision":2,"scope":{"interface_ids":["interface-list","interface-detail"],"relationship_ids":[]},"changes":[{"change_type":"step","step_id":"step-a","action_type":"open_detail","target_region_id":"region-row","expected_result":"detail_visible"}]}
    wrong=copy.deepcopy(candidate); wrong["changes"][0]["target_region_id"]="region-title"
    with pytest.raises(AgentLinkError,match="scope"):
        service.agent_call(grant["token"],"submit_candidate",wrong)
    assert service.agent_call(grant["token"],"submit_candidate",candidate)["status"] == "pending_review_proposal"
    store.close()
    path=tmp_path/"inbox.json"; reopened=AgentLinkStore(path); reopened.close()
    payload=json.loads(path.read_text(encoding="utf-8"))
    next(iter(payload["candidates"].values()))["changes"][0]["target_region_id"]="region-title"
    path.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
    with pytest.raises(AgentLinkError,match="corrupt"):
        AgentLinkStore(path)
