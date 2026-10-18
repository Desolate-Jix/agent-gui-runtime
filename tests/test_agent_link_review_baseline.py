from __future__ import annotations

import base64
import copy
import hashlib
import json
from io import BytesIO

import pytest
from PIL import Image

from app.agent_link.contracts import AgentLinkError, canonical_hash
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore


REVIEWER_TOKEN = "reviewer-secret-value-123"


def _png_base64(color: str = "white") -> str:
    image = Image.new("RGB", (32, 24), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _batch() -> dict:
    return {
        "contract_version": "agent_link_v1",
        "idempotency_key": "batch-key",
        "batch_id": "batch-1",
        "title": "中文重学批次",
        "learning_outcome": "completed",
        "outcome_reason": None,
        "screenshots": [{"screenshot_id": "screen-1", "png_base64": _png_base64()}],
        "interfaces": [{
            "interface_id": "interface-1",
            "screenshot_id": "screen-1",
            "meaning": "原始界面",
            "regions": [{
                "region_id": "region-1", "bbox": [2.0, 3.0, 20.0, 15.0],
                "name": "详情", "meaning": "原始区域",
            }],
        }],
        "relationships": [],
        "steps": [{
            "step_id": "step-1", "action_type": "open_detail",
            "target_region_id": "region-1", "start_state": "interface-1",
            "arrival_state": "interface-1", "prerequisites": [],
            "expected_result": "原始结果", "stop_condition": "停止",
        }],
        "issues": [],
    }


def _setup(tmp_path):
    path = tmp_path / "inbox.json"
    store = AgentLinkStore(path)
    service = AgentLinkService(store, REVIEWER_TOKEN)
    grant = service.reviewer_call(REVIEWER_TOKEN, "create_connection", {
        "task_id": "task-1", "agent_name": "synthetic-agent",
    })
    service.agent_call(grant["token"], "submit_batch", _batch())
    original = service.reviewer_call(REVIEWER_TOKEN, "get_batch", {
        "task_id": "task-1", "batch_id": "batch-1",
    })["batch"]
    reviewed = copy.deepcopy(original)
    reviewed["interfaces"][0]["meaning"] = "人工界面"
    reviewed["interfaces"][0]["regions"][0]["meaning"] = "人工区域"
    reviewed["interfaces"][0]["regions"][0]["bbox"] = [3.0, 4.0, 20.0, 15.0]
    reviewed["steps"][0]["expected_result"] = "人工结果"
    raw_reviewed = copy.deepcopy(reviewed)
    for screenshot in raw_reviewed["screenshots"]:
        for key in ("sha256", "width", "height"):
            screenshot.pop(key, None)
    baseline = {
        "contract_version": "desktop_review_baseline_v1",
        "task_id": "task-1",
        "workspace_revision": 1,
        "source_ref": canonical_hash(original),
        "batch_sha256": canonical_hash(reviewed),
        "batch": raw_reviewed,
    }
    return path, store, service, grant, original, reviewed, baseline


def _record(service, baseline, *, issue_id="relearn-1", key="feedback-1"):
    return service.reviewer_call(REVIEWER_TOKEN, "record_feedback", {
        "task_id": "task-1", "batch_id": "batch-1", "idempotency_key": key,
        "expected_revision": 0, "notes": [],
        "issues": [{
            "issue_id": issue_id,
            "scope": {"interface_ids": ["interface-1"], "relationship_ids": []},
            "message": "请按人工版本重学",
            "review_baseline": baseline,
        }],
    })


def _candidate(baseline_sha256: str | None, *, changes=None, key="candidate-1") -> dict:
    value = {
        "contract_version": "agent_link_v1", "idempotency_key": key,
        "batch_id": "batch-1", "issue_id": "relearn-1", "baseline_revision": 1,
        "scope": {"interface_ids": ["interface-1"], "relationship_ids": []},
        "changes": changes or [{
            "change_type": "geometry", "region_id": "region-1",
            "bbox": [4.0, 5.0, 20.0, 15.0],
        }],
    }
    if baseline_sha256 is not None:
        value["review_baseline_sha256"] = baseline_sha256
    return value


def test_relearn_roundtrip_pins_saved_human_revision(tmp_path):
    path, store, service, grant, original, reviewed, baseline = _setup(tmp_path)
    try:
        _record(service, baseline)
        feedback = service.agent_call(grant["token"], "read_feedback", {"batch_id": "batch-1"})
        issue = feedback["issues"][0]
        assert issue["review_baseline"] == baseline
        assert issue["review_baseline_sha256"] == canonical_hash(baseline)
        receipt = service.agent_call(
            grant["token"], "submit_candidate",
            _candidate(issue["review_baseline_sha256"]),
        )
        detail = service.reviewer_call(REVIEWER_TOKEN, "get_batch", {
            "task_id": "task-1", "batch_id": "batch-1",
        })
        candidate = next(item for item in detail["candidates"] if item["candidate_id"] == receipt["candidate_id"])
        assert candidate["review_baseline_sha256"] == canonical_hash(baseline)
        assert candidate["candidate_sha256"]
        assert detail["batch"] == original
        store.close()
        reopened = AgentLinkStore(path)
        try:
            loaded = AgentLinkService(reopened, REVIEWER_TOKEN).reviewer_call(
                REVIEWER_TOKEN, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"}
            )
            assert loaded["issues"][0]["review_baseline"]["batch_sha256"] == canonical_hash(reviewed)
        finally:
            reopened.close()
    finally:
        store.close()


def test_baseline_binding_rejects_missing_wrong_task_evidence_and_stable_ids(tmp_path):
    _, store, service, grant, _, _, baseline = _setup(tmp_path)
    try:
        _record(service, baseline)
        with pytest.raises(AgentLinkError, match="baseline"):
            service.agent_call(grant["token"], "submit_candidate", _candidate(None))
        with pytest.raises(AgentLinkError, match="baseline"):
            service.agent_call(grant["token"], "submit_candidate", _candidate("0" * 64, key="wrong"))
    finally:
        store.close()

    for label, mutate in (
        ("task", lambda value: value.update(task_id="task-other")),
        ("png", lambda value: value["batch"]["screenshots"][0].update(png_base64=_png_base64("black"))),
        ("id", lambda value: value["batch"]["interfaces"][0]["regions"][0].update(region_id="other")),
    ):
        _, store, service, _, _, _, baseline = _setup(tmp_path / label)
        try:
            mutate(baseline)
            with pytest.raises(AgentLinkError):
                _record(service, baseline)
            assert service.agent_call(
                service.reviewer_call(REVIEWER_TOKEN, "create_connection", {
                    "task_id": "unused", "agent_name": "unused-agent",
                })["token"], "status", {}
            )["staging_only"] is True
        finally:
            store.close()


def test_legacy_shape_stays_absent_and_cannot_claim_a_human_baseline(tmp_path):
    _, store, service, grant, _, _, _ = _setup(tmp_path)
    try:
        service.reviewer_call(REVIEWER_TOKEN, "record_feedback", {
            "task_id": "task-1", "batch_id": "batch-1", "idempotency_key": "legacy-feedback",
            "expected_revision": 0, "notes": [], "issues": [{
                "issue_id": "legacy", "scope": {"interface_ids": ["interface-1"], "relationship_ids": []},
                "message": "legacy issue",
            }],
        })
        issue = service.agent_call(grant["token"], "read_feedback", {"batch_id": "batch-1"})["issues"][0]
        assert "review_baseline" not in issue
        assert "review_baseline_sha256" not in issue
        raw = store.snapshot()["feedback"]["batch-1"]["issues"]["legacy"]
        assert "review_baseline" not in raw and "review_baseline_sha256" not in raw
        forged = _candidate("a" * 64)
        forged["issue_id"] = "legacy"
        with pytest.raises(AgentLinkError, match="baseline"):
            service.agent_call(grant["token"], "submit_candidate", forged)
    finally:
        store.close()


def test_duplicate_target_field_is_rejected_and_tampering_fails_reload(tmp_path):
    path, store, service, grant, _, _, baseline = _setup(tmp_path)
    _record(service, baseline)
    baseline_sha = canonical_hash(baseline)
    with pytest.raises(AgentLinkError, match="duplicate"):
        service.agent_call(grant["token"], "submit_candidate", _candidate(baseline_sha, changes=[
            {"change_type": "semantic", "target_type": "step", "target_id": "step-1", "meaning": "A"},
            {"change_type": "step", "step_id": "step-1", "action_type": "open_detail", "target_region_id": "region-1", "expected_result": "B"},
        ]))
    receipt = service.agent_call(grant["token"], "submit_candidate", _candidate(baseline_sha, key="valid"))
    store.close()
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candidates"][receipt["candidate_id"]]["changes"][0]["bbox"][0] = 7.0
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AgentLinkError, match="corrupt"):
        AgentLinkStore(path)


@pytest.mark.parametrize("tamper", ["contract", "bool_revision", "zero_revision", "unknown", "not_object"])
def test_disk_reload_strictly_revalidates_baseline_contract_and_releases_owner(tmp_path, tamper):
    path, store, service, _, _, _, baseline = _setup(tmp_path)
    _record(service, baseline)
    store.close()
    original_bytes = path.read_bytes()
    payload = json.loads(original_bytes.decode("utf-8"))
    issue = payload["feedback"]["batch-1"]["issues"]["relearn-1"]
    if tamper == "contract":
        issue["review_baseline"]["contract_version"] = "desktop_review_baseline_v2"
    elif tamper == "bool_revision":
        issue["review_baseline"]["workspace_revision"] = True
    elif tamper == "zero_revision":
        issue["review_baseline"]["workspace_revision"] = 0
    elif tamper == "unknown":
        issue["review_baseline"]["authority"] = "approved"
    else:
        issue["review_baseline"] = "not-an-object"
    issue["review_baseline_sha256"] = canonical_hash(issue["review_baseline"])
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AgentLinkError, match="corrupt"):
        AgentLinkStore(path)
    path.write_bytes(original_bytes)
    reopened = AgentLinkStore(path)
    reopened.close()
