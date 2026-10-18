from __future__ import annotations

import copy

import pytest

from app.agent_link.contracts import AgentLinkError, validate_batch, validate_candidate
from app.agent_link.candidate_projection import (
    CandidateProjectionError, apply_candidate_diffs, index_candidate_fields,
    project_candidate_fields,
)
from test_agent_link_flow_candidates import _setup, _candidate as flow_candidate, flow_batch


def _candidate(*, region_id="missing-control-1"):
    return validate_candidate({
        "contract_version": "agent_link_v1", "idempotency_key": "add-region",
        "batch_id": "flow-batch", "issue_id": "issue", "baseline_revision": 1,
        "review_baseline_sha256": "a" * 64,
        "scope": {"interface_ids": ["i1", "i2"], "relationship_ids": ["rel-12"]},
        "changes": [
            {"change_type": "regions_add", "interface_id": "i1", "regions": [{
                "region_id": region_id, "bbox": [1.0, 2.0, 10.0, 8.0],
                "name": "遗漏按钮", "meaning": "尚待人工审核的按钮含义",
            }]},
            {"change_type": "step_flow", "step_id": "s1", "action_type": "open_detail",
             "target_region_id": region_id, "start_state": "i1", "arrival_state": "i2",
             "prerequisites": ["已选择"], "expected_result": "显示", "stop_condition": "停止"},
        ],
    })


def test_regions_add_projects_entity_diff_and_applies_before_step_reference():
    batch = validate_batch(flow_batch())
    original = copy.deepcopy(batch)
    candidate = _candidate()
    writes = project_candidate_fields(candidate, batch, candidate["scope"])
    added = writes[0]
    assert (added.target_type, added.target_id, added.field, added.proposed) == (
        "region", "missing-control-1", "entity", {"interface_id": "i1", "region": {
            "region_id": "missing-control-1", "bbox": [1.0, 2.0, 10.0, 8.0],
            "name": "遗漏按钮", "label": None, "type": None, "kind": None,
            "meaning": "尚待人工审核的按钮含义",
        }},
    )
    index = index_candidate_fields(batch)
    diffs = [{"target_type": item.target_type, "target_id": item.target_id, "field": item.field,
              "baseline": index.get((item.target_type, item.target_id, item.field)),
              "current": index.get((item.target_type, item.target_id, item.field)), "proposed": item.proposed}
             for item in writes]
    applied = apply_candidate_diffs(batch, diffs)
    assert applied["interfaces"][0]["regions"][-1]["region_id"] == "missing-control-1"
    assert next(step for step in applied["steps"] if step["step_id"] == "s1")["target_region_id"] == "missing-control-1"
    assert batch == original


def test_regions_add_rejects_duplicate_and_current_entity():
    batch = validate_batch(flow_batch())
    with pytest.raises(CandidateProjectionError):
        project_candidate_fields(_candidate(region_id="r1"), batch, _candidate()["scope"])
    with pytest.raises(CandidateProjectionError):
        apply_candidate_diffs(batch, [{
            "target_type": "region", "target_id": "r1", "field": "entity",
            "baseline": None, "current": None, "proposed": {"interface_id": "i1", "region": copy.deepcopy(batch["interfaces"][0]["regions"][0])},
        }])


def _entity_diff(region_id, *, interface_id="i1"):
    return {"target_type": "region", "target_id": region_id, "field": "entity",
            "baseline": None, "current": None, "proposed": {"interface_id": interface_id, "region": {
                "region_id": region_id, "bbox": [1.0, 2.0, 10.0, 8.0], "name": "新增", "meaning": "新增"}}}


def test_regions_add_rejects_separate_geometry_or_semantic_on_new_id():
    batch = validate_batch(flow_batch())
    for extra in (
        {"change_type": "geometry", "region_id": "missing-control-1", "bbox": [2.0, 2.0, 8.0, 8.0]},
        {"change_type": "semantic", "target_type": "region", "target_id": "missing-control-1", "meaning": "不单独修改"},
    ):
        candidate = _candidate()
        candidate["changes"].append(extra)
        with pytest.raises(CandidateProjectionError):
            project_candidate_fields(candidate, batch, candidate["scope"])


def test_apply_additions_enforces_aggregate_limit_and_strict_parent_type():
    batch = validate_batch(flow_batch())
    batch["interfaces"][0]["regions"] = [copy.deepcopy(batch["interfaces"][0]["regions"][0]) for _ in range(127)]
    for number, region in enumerate(batch["interfaces"][0]["regions"]):
        region["region_id"] = f"full-{number}"
    original = copy.deepcopy(batch)
    with pytest.raises(CandidateProjectionError):
        apply_candidate_diffs(batch, [_entity_diff("new-1"), _entity_diff("new-2")])
    assert batch == original
    invalid = _entity_diff("bad-parent", interface_id="i1")
    invalid["proposed"]["interface_id"] = []
    with pytest.raises(CandidateProjectionError):
        apply_candidate_diffs(validate_batch(flow_batch()), [invalid])


def test_only_entity_addition_can_use_absent_baseline_target():
    batch = validate_batch(flow_batch())
    with pytest.raises(CandidateProjectionError):
        apply_candidate_diffs(batch, [{"target_type": "region", "target_id": "absent", "field": "meaning",
            "baseline": None, "current": None, "proposed": "不允许创建普通字段"}])


def test_submit_rejects_missing_or_foreign_baseline_and_agent_feedback_operation(tmp_path):
    _, store, service, grant, baseline = _setup(tmp_path)
    try:
        payload = flow_candidate(baseline, changes=[{"change_type": "regions_add", "interface_id": "i1", "regions": [{
            "region_id": "missing-control-1", "bbox": [1.0, 2.0, 10.0, 8.0], "name": "新增", "meaning": "新增"}]}])
        for bad in (None, "0" * 64):
            candidate = copy.deepcopy(payload)
            if bad is None:
                candidate.pop("review_baseline_sha256")
            else:
                candidate["review_baseline_sha256"] = bad
            with pytest.raises(AgentLinkError):
                service.agent_call(grant["token"], "submit_candidate", candidate)
        injected = copy.deepcopy(payload)
        injected["review_baseline"] = baseline
        with pytest.raises(AgentLinkError):
            service.agent_call(grant["token"], "submit_candidate", injected)
        with pytest.raises(AgentLinkError):
            service.agent_call(grant["token"], "record_feedback", {"review_baseline": baseline})
    finally:
        store.close()


@pytest.mark.parametrize("mutation", ["duplicate", "outside", "nonfinite", "over_limit", "foreign_scope"])
def test_regions_add_contract_rejects_duplicate_scope_and_geometry_limits(mutation):
    payload = _candidate()
    addition = payload["changes"][0]
    if mutation == "duplicate":
        payload["changes"].append(copy.deepcopy(addition))
    elif mutation == "outside":
        addition["regions"][0]["bbox"] = [90.0, 2.0, 10.0, 8.0]
    elif mutation == "nonfinite":
        addition["regions"][0]["bbox"] = [1.0, 2.0, float("inf"), 8.0]
    elif mutation == "over_limit":
        addition["regions"] = [dict(addition["regions"][0], region_id=f"many-{number}") for number in range(129)]
    else:
        addition["interface_id"] = "i3"
    if mutation in {"nonfinite", "over_limit"}:
        with pytest.raises(AgentLinkError):
            validate_candidate(payload)
    else:
        candidate = validate_candidate(payload)
        with pytest.raises(CandidateProjectionError):
            project_candidate_fields(candidate, validate_batch(flow_batch()), candidate["scope"])
