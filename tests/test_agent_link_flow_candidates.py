from __future__ import annotations

import asyncio
import base64
import copy
import json
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agent_link.contracts import AgentLinkError, canonical_hash
from app.agent_link.contracts import validate_batch, validate_candidate, validate_scope
from app.agent_link.review_baseline import candidate_content_sha256, validate_candidate_changes
from app.agent_link.http_app import create_agent_link_app
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore


REVIEWER_TOKEN = "reviewer-secret-value-123"


def _png() -> str:
    image = Image.new("RGB", (96, 64), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def flow_batch() -> dict:
    interfaces = []
    for number in range(1, 4):
        interfaces.append({
            "interface_id": f"i{number}", "screenshot_id": "screen",
            "meaning": f"界面 {number}",
            "regions": [{
                "region_id": f"r{number}", "bbox": [number * 20.0, 2.0, 16.0, 12.0],
                "name": f"控件 {number}", "meaning": f"区域 {number}",
            }],
        })
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "batch-key",
        "batch_id": "flow-batch", "title": "流程候选批次",
        "learning_outcome": "completed", "outcome_reason": None,
        "screenshots": [{"screenshot_id": "screen", "png_base64": _png()}],
        "interfaces": interfaces,
        "relationships": [{
            "relationship_id": "rel-12", "from_interface_id": "i1",
            "to_interface_id": "i2", "kind": "旧连接",
        }],
        "steps": [
            _step("s1", "i1", "i2", "r1"),
            _step("outside", "i3", "i3", "r3"),
            _step("s2", "i2", "i1", "r2"),
            _step("s3", "i1", "i1", "r1"),
        ],
        "issues": [],
    }


def _step(step_id: str, start: str, arrival: str, region: str) -> dict:
    return {
        "step_id": step_id, "action_type": "open_detail",
        "target_region_id": region, "start_state": start, "arrival_state": arrival,
        "prerequisites": ["旧前置"], "expected_result": "旧结果",
        "stop_condition": "旧停止",
    }


def flow_changes() -> list[dict]:
    return [
        {
            "change_type": "step_flow", "step_id": "s1",
            "action_type": "open_link", "target_region_id": "r2",
            "start_state": "i2", "arrival_state": "i1",
            "prerequisites": ["已经选择目标文件"],
            "expected_result": "详情面板显示所选文件",
            "stop_condition": "目标或详情不一致则停止",
        },
        {
            "change_type": "relationship_flow", "relationship_id": "rel-12",
            "from_interface_id": "i2", "to_interface_id": "i1", "kind": "返回详情",
        },
        {"change_type": "step_order", "step_ids": ["s3", "s1", "s2"]},
    ]


def _setup(tmp_path):
    path = tmp_path / "inbox.json"
    store = AgentLinkStore(path)
    service = AgentLinkService(store, REVIEWER_TOKEN)
    grant = service.reviewer_call(REVIEWER_TOKEN, "create_connection", {
        "task_id": "task-flow", "agent_name": "synthetic-agent",
    })
    service.agent_call(grant["token"], "submit_batch", flow_batch())
    original = service.reviewer_call(REVIEWER_TOKEN, "get_batch", {
        "task_id": "task-flow", "batch_id": "flow-batch",
    })["batch"]
    baseline_batch = copy.deepcopy(original)
    raw = copy.deepcopy(baseline_batch)
    for screenshot in raw["screenshots"]:
        for field in ("sha256", "width", "height"):
            screenshot.pop(field, None)
    baseline = {
        "contract_version": "desktop_review_baseline_v1", "task_id": "task-flow",
        "workspace_revision": 1, "source_ref": canonical_hash(original),
        "batch_sha256": canonical_hash(baseline_batch), "batch": raw,
    }
    service.reviewer_call(REVIEWER_TOKEN, "record_feedback", {
        "task_id": "task-flow", "batch_id": "flow-batch", "idempotency_key": "feedback",
        "expected_revision": 0, "notes": [], "issues": [{
            "issue_id": "issue-flow",
            "scope": {"interface_ids": ["i1", "i2"], "relationship_ids": ["rel-12"]},
            "message": "核对完整流程", "review_baseline": baseline,
        }],
    })
    return path, store, service, grant, baseline


def _candidate(baseline: dict, *, key: str = "candidate", changes=None) -> dict:
    return {
        "contract_version": "agent_link_v1", "idempotency_key": key,
        "batch_id": "flow-batch", "issue_id": "issue-flow", "baseline_revision": 1,
        "review_baseline_sha256": canonical_hash(baseline),
        "scope": {"interface_ids": ["i1", "i2"], "relationship_ids": ["rel-12"]},
        "changes": flow_changes() if changes is None else changes,
    }


def test_status_contract_and_actual_mcp_schema_expose_flow_types(tmp_path, monkeypatch):
    _, store, service, grant, _ = _setup(tmp_path)
    try:
        status = service.agent_call(grant["token"], "status", {})
        assert status["capabilities"] == ["read_feedback", "status", "submit_batch", "submit_candidate"]
        assert status["candidate_change_types"] == [
            "geometry", "regions_add", "interfaces_add", "steps_add", "relationships_add", "relationship", "relationship_flow", "semantic",
            "step", "step_flow", "step_order",
        ]

        import mcp.server
        from app.agent_link import mcp_bridge

        captured = []
        monkeypatch.setenv("AGENT_LINK_BASE_URL", "http://127.0.0.1:65534")
        monkeypatch.setenv("AGENT_LINK_TOKEN", grant["token"])
        monkeypatch.setattr(mcp.server.MCPServer, "run", lambda self, **_: captured.append(self))
        monkeypatch.setattr(mcp_bridge, "_call", lambda _url, _token, operation, arguments: (
            status if operation == "status" and arguments == {} else pytest.fail("unexpected Agent Link call")
        ))
        mcp_bridge.run_stdio()
        tools = asyncio.run(captured[0].list_tools())
        schema = next(tool.input_schema for tool in tools if tool.name == "submit_relearning_candidate")
        rendered = json.dumps(schema, ensure_ascii=False)
        for change_type in ("regions_add", "interfaces_add", "steps_add", "relationships_add", "step_flow", "relationship_flow", "step_order"):
            assert change_type in rendered
    finally:
        store.close()


def test_legacy_step_candidate_json_and_hash_are_frozen():
    raw = {
        "contract_version": "agent_link_v1", "idempotency_key": "old",
        "batch_id": "flow-batch", "issue_id": "legacy", "baseline_revision": 1,
        "scope": {"interface_ids": ["i1"], "relationship_ids": []},
        "changes": [{
            "change_type": "step", "step_id": "s1", "action_type": "open_detail",
            "target_region_id": "r1", "expected_result": "旧结果",
        }],
    }
    normalized = validate_candidate(raw)
    assert normalized == raw
    assert canonical_hash(normalized) == "6437006ba7aac3244c4a0e6ac9bfa6430c9546d74a13feeeee81bac6c7f1b1bd"


@pytest.mark.parametrize("action", ["observe", "safe_stop"])
def test_old_step_optional_actions_still_require_target_in_original_start(tmp_path, action):
    _, store, service, grant, baseline = _setup(tmp_path)
    try:
        old_change = {
            "change_type": "step", "step_id": "s1", "action_type": action,
            "target_region_id": "r2", "expected_result": "旧类型不可放宽目标范围",
        }
        with pytest.raises(AgentLinkError, match="step change"):
            service.agent_call(
                grant["token"], "submit_candidate",
                _candidate(baseline, changes=[old_change]),
            )
    finally:
        store.close()


def test_http_service_and_disk_roundtrip_accept_exact_flow_candidate(tmp_path):
    path, store, service, grant, baseline = _setup(tmp_path)
    app = create_agent_link_app(service)
    client = TestClient(app, client=("127.0.0.1", 50101))
    response = client.post(
        "/agent/submit_candidate",
        headers={"Authorization": "Bearer " + grant["token"]},
        json=_candidate(baseline),
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    persisted = store.snapshot()["candidates"][receipt["candidate_id"]]
    assert persisted["changes"] == flow_changes()
    store.close()
    reopened = AgentLinkStore(path)
    try:
        loaded = reopened.snapshot()["candidates"][receipt["candidate_id"]]
        assert loaded["changes"] == flow_changes()
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "changes",
    [
        [{**flow_changes()[0], "target_region_id": None}],
        [{**flow_changes()[0], "start_state": "i3"}],
        [{**flow_changes()[0], "arrival_state": "i3"}],
        [{**flow_changes()[0], "target_region_id": "r1"}],
        [{**flow_changes()[0], "prerequisites": [""]}],
        [{**flow_changes()[0], "prerequisites": ["x" * 4001]}],
        [{**flow_changes()[0], "stop_condition": "   "}],
        [{**flow_changes()[1], "to_interface_id": "i3"}],
        [{"change_type": "step_order", "step_ids": ["s1", "s2"]}],
        [{"change_type": "step_order", "step_ids": ["s1", "s2", "s2"]}],
        [{"change_type": "step_order", "step_ids": ["s1", "s2", "new"]}],
        [flow_changes()[2], flow_changes()[2]],
    ],
)
def test_invalid_flow_scope_references_order_conditions_and_conflicts_do_not_persist(tmp_path, changes):
    _, store, service, grant, baseline = _setup(tmp_path)
    try:
        before = store.snapshot()
        with pytest.raises(AgentLinkError):
            service.agent_call(grant["token"], "submit_candidate", _candidate(baseline, changes=changes))
        after = store.snapshot()
        assert after["candidates"] == before["candidates"]
        assert after["idempotency"] == before["idempotency"]
    finally:
        store.close()


def test_individually_valid_old_and_new_step_writes_conflict_on_same_fields(tmp_path):
    _, store, service, grant, baseline = _setup(tmp_path)
    try:
        old_change = {
            "change_type": "step", "step_id": "s1", "action_type": "open_detail",
            "target_region_id": "r1", "expected_result": "旧类型单独有效",
        }
        with pytest.raises(AgentLinkError) as failure:
            service.agent_call(
                grant["token"], "submit_candidate",
                _candidate(baseline, changes=[flow_changes()[0], old_change]),
            )
        assert failure.value.code == "duplicate_change"
    finally:
        store.close()


def test_observe_allows_null_target_but_normal_and_unknown_actions_remain_strict(tmp_path):
    _, store, service, grant, baseline = _setup(tmp_path)
    try:
        observe = flow_changes()[0]
        observe.update(action_type="observe", target_region_id=None)
        service.agent_call(grant["token"], "submit_candidate", _candidate(baseline, changes=[observe]))
        unknown = copy.deepcopy(observe)
        unknown.update(action_type="mystery", target_region_id="r2")
        service.agent_call(grant["token"], "submit_candidate", _candidate(baseline, key="unknown", changes=[unknown]))
    finally:
        store.close()


def test_legacy_issue_rejects_new_flow_types_but_retains_old_candidate_shape(tmp_path):
    _, store, service, grant, _ = _setup(tmp_path)
    try:
        service.reviewer_call(REVIEWER_TOKEN, "record_feedback", {
            "task_id": "task-flow", "batch_id": "flow-batch", "idempotency_key": "legacy-feedback",
            "expected_revision": 1, "notes": [], "issues": [{
                "issue_id": "legacy", "scope": {"interface_ids": ["i1", "i2"], "relationship_ids": ["rel-12"]},
                "message": "旧问题",
            }],
        })
        value = _candidate({}, key="legacy-flow", changes=[flow_changes()[0]])
        value.pop("review_baseline_sha256")
        value.update(issue_id="legacy", baseline_revision=2)
        with pytest.raises(AgentLinkError, match="baseline|基线"):
            service.agent_call(grant["token"], "submit_candidate", value)

        old = _candidate({}, key="legacy-old", changes=[{
            "change_type": "semantic", "target_type": "interface", "target_id": "i1", "meaning": "旧兼容",
        }])
        old.pop("review_baseline_sha256")
        old.update(issue_id="legacy", baseline_revision=2)
        receipt = service.agent_call(grant["token"], "submit_candidate", old)
        stored = store.snapshot()["candidates"][receipt["candidate_id"]]
        assert stored["changes"] == old["changes"]
        assert "review_baseline_sha256" not in stored
    finally:
        store.close()


def test_original_flow_endpoints_must_also_be_inside_scope():
    batch = validate_batch(flow_batch())
    scope = validate_scope(
        {"interface_ids": ["i1"], "relationship_ids": ["rel-12"]}, batch
    )
    for change in (
        {
            **flow_changes()[0], "start_state": "i1", "arrival_state": "i1",
            "target_region_id": "r1",
        },
        {
            **flow_changes()[1], "from_interface_id": "i1", "to_interface_id": "i1",
        },
    ):
        candidate = validate_candidate({
            "contract_version": "agent_link_v1", "idempotency_key": "candidate",
            "batch_id": "flow-batch", "issue_id": "issue", "baseline_revision": 1,
            "review_baseline_sha256": "a" * 64, "scope": scope, "changes": [change],
        })
        with pytest.raises(AgentLinkError, match="outside scope"):
            validate_candidate_changes(candidate, batch, scope)


def test_disk_reload_rejects_tampered_scoped_order_even_with_recomputed_digest(tmp_path):
    path, store, service, grant, baseline = _setup(tmp_path)
    receipt = service.agent_call(
        grant["token"], "submit_candidate", _candidate(baseline)
    )
    store.close()
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidate = payload["candidates"][receipt["candidate_id"]]
    candidate["changes"][2]["step_ids"] = ["s1", "s2"]
    candidate["candidate_sha256"] = candidate_content_sha256(candidate)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AgentLinkError, match="corrupt"):
        AgentLinkStore(path)
