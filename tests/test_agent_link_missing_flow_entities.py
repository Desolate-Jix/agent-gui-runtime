from __future__ import annotations

from copy import deepcopy
import pytest

from app.agent_link.contracts import AgentLinkError, validate_batch, validate_candidate
from app.agent_link.candidate_projection import CandidateProjectionError, apply_candidate_diffs, index_candidate_fields, project_candidate_fields
from test_agent_link_flow_candidates import flow_batch


def _step(identifier="new-step"):
    return {"step_id": identifier, "action_type": "open_detail", "target_region_id": "r1",
            "start_state": "i1", "arrival_state": "i2", "prerequisites": ["已选择"],
            "expected_result": "显示详情", "stop_condition": "停止等待"}


def _relation(identifier="new-relation"):
    return {"relationship_id": identifier, "from_interface_id": "i1", "to_interface_id": "i2", "kind": "打开详情"}


def _entity(kind, identifier, anchor=None):
    return {"target_type": kind, "target_id": identifier, "field": "entity", "baseline": None, "current": None,
            "proposed": {"after_step_id": anchor, "step": _step(identifier)} if kind == "step" else _relation(identifier)}


def _payload(changes):
    return {"contract_version": "agent_link_v1", "idempotency_key": "missing-flow", "batch_id": "flow-batch",
            "issue_id": "issue", "baseline_revision": 1, "review_baseline_sha256": "a" * 64,
            "scope": {"interface_ids": ["i1", "i2"], "relationship_ids": []}, "changes": changes}


def test_insertion_position_must_be_explicit_not_implicitly_prepend():
    with pytest.raises(AgentLinkError):
        validate_candidate(_payload([{"change_type": "steps_add", "steps": [_step()]}]))


def test_same_anchor_and_start_groups_keep_exact_candidate_order():
    batch = validate_batch(flow_batch())
    original = deepcopy(batch)
    diffs = [_entity("step", "a", "s1"), _entity("step", "head-a"), _entity("step", "b", "s1"),
             _entity("step", "head-b"), _entity("step", "tail", "s3")]
    assert [s["step_id"] for s in apply_candidate_diffs(batch, diffs)["steps"]] == [
        "head-a", "head-b", "s1", "a", "b", "outside", "s2", "s3", "tail"]
    assert batch == original


@pytest.mark.parametrize("kind", ["step", "relationship"])
def test_entity_aggregate_cap_and_normal_field_on_new_id_are_rejected(kind):
    batch = validate_batch(flow_batch())
    collection = "steps" if kind == "step" else "relationships"
    batch[collection] = [(_step if kind == "step" else _relation)(f"existing-{i}") for i in range(255)]
    before = deepcopy(batch)
    with pytest.raises(CandidateProjectionError):
        apply_candidate_diffs(batch, [_entity(kind, "a"), _entity(kind, "b")])
    assert batch == before
    field, old = ("expected_result", "显示详情") if kind == "step" else ("kind", "打开详情")
    with pytest.raises(CandidateProjectionError):
        apply_candidate_diffs(validate_batch(flow_batch()), [_entity(kind, "new"), {
            "target_type": kind, "target_id": "new", "field": field,
            "baseline": old, "current": old, "proposed": "同候选不得另改"}])


@pytest.mark.parametrize("invalid", ["new_anchor", "wrong_target", "missing_target", "target_id_type", "extra", "baseline_present"])
def test_strict_step_apply_rejects_invalid_entities_without_mutation(invalid):
    batch = validate_batch(flow_batch())
    before = deepcopy(batch)
    diffs = [_entity("step", "a"), _entity("step", "b", "s1")]
    if invalid == "new_anchor":
        diffs[1]["proposed"]["after_step_id"] = "a"
    elif invalid == "wrong_target":
        diffs[1]["proposed"]["step"]["target_region_id"] = "r2"
    elif invalid == "missing_target":
        diffs[1]["proposed"]["step"]["target_region_id"] = None
    elif invalid == "target_id_type":
        diffs[1]["target_id"] = []
    elif invalid == "extra":
        diffs[1]["proposed"]["step"]["approved"] = True
    else:
        diffs[1]["baseline"] = {}
    with pytest.raises(CandidateProjectionError):
        apply_candidate_diffs(batch, diffs)
    assert batch == before


@pytest.mark.parametrize("kind", ["steps_add", "relationships_add"])
def test_scope_duplicates_baseline_and_separate_writes_rejected_at_projection(kind):
    change = {"change_type": kind, "after_step_id": "s1", "steps": [_step()]} if kind == "steps_add" else {
        "change_type": kind, "relationships": [_relation()]}
    batch = validate_batch(flow_batch())
    for mutation in ("scope", "duplicate", "baseline", "separate", "old_id"):
        raw = _payload([deepcopy(change)])
        item = raw["changes"][0]
        if mutation == "scope":
            (item["steps"][0] if kind == "steps_add" else item["relationships"][0])[
                "arrival_state" if kind == "steps_add" else "to_interface_id"] = "i3"
        elif mutation == "duplicate":
            raw["changes"].append(deepcopy(item))
        elif mutation == "baseline":
            raw.pop("review_baseline_sha256")
        elif mutation == "old_id":
            if kind == "steps_add":
                item["steps"][0]["step_id"] = "s1"
            else:
                item["relationships"][0]["relationship_id"] = "rel-12"
        else:
            raw["changes"].append({"change_type": "semantic", "target_type": "step" if kind == "steps_add" else "relationship",
                                   "target_id": "new-step" if kind == "steps_add" else "new-relation", "meaning": "不另写"})
        candidate = validate_candidate(raw)
        with pytest.raises(CandidateProjectionError):
            project_candidate_fields(candidate, batch, candidate["scope"])


def test_anchor_scope_order_conflict_both_orders_and_optional_target_contract():
    batch = validate_batch(flow_batch())
    change = {"change_type": "steps_add", "after_step_id": "outside", "steps": [_step()]}
    candidate = validate_candidate(_payload([change]))
    with pytest.raises(CandidateProjectionError):
        project_candidate_fields(candidate, batch, candidate["scope"])
    change["after_step_id"] = None
    order = {"change_type": "step_order", "step_ids": ["s1", "s2", "s3"]}
    for changes in ([change, order], [order, change]):
        candidate = validate_candidate(_payload(changes))
        with pytest.raises(CandidateProjectionError):
            project_candidate_fields(candidate, batch, candidate["scope"])
    for action in ("observe", "safe_stop"):
        diff = _entity("step", "optional")
        diff["proposed"]["step"].update(action_type=action, target_region_id="r2")
        assert apply_candidate_diffs(batch, [diff])["steps"][0]["target_region_id"] == "r2"


def test_steps_and_relationships_add_project_and_apply_in_anchor_order():
    batch = validate_batch(flow_batch())
    candidate = validate_candidate({"contract_version":"agent_link_v1","idempotency_key":"flow-add","batch_id":"flow-batch","issue_id":"issue","baseline_revision":1,"review_baseline_sha256":"a"*64,"scope":{"interface_ids":["i1","i2"],"relationship_ids":["rel-12"]},"changes":[
        {"change_type":"relationships_add","relationships":[{"relationship_id":"missing-rel","from_interface_id":"i1","to_interface_id":"i2","kind":"新增关系"}]},
        {"change_type":"steps_add","after_step_id":None,"steps":[{"step_id":"first-new","action_type":"open_detail","target_region_id":"r1","start_state":"i1","arrival_state":"i2","prerequisites":["已选"],"expected_result":"显示","stop_condition":"停止"}]},
        {"change_type":"steps_add","after_step_id":"s1","steps":[{"step_id":"middle-new","action_type":"open_detail","target_region_id":"r1","start_state":"i1","arrival_state":"i2","prerequisites":["已选"],"expected_result":"显示","stop_condition":"停止"}]},
    ]})
    writes = project_candidate_fields(candidate,batch,candidate["scope"])
    index=index_candidate_fields(batch)
    diffs=[{"target_type":w.target_type,"target_id":w.target_id,"field":w.field,"baseline":index.get((w.target_type,w.target_id,w.field)),"current":index.get((w.target_type,w.target_id,w.field)),"proposed":w.proposed} for w in writes]
    applied=apply_candidate_diffs(batch,diffs)
    assert [x["step_id"] for x in applied["steps"]] == ["first-new","s1","middle-new","outside","s2","s3"]
    assert applied["relationships"][-1]["relationship_id"] == "missing-rel"


def test_apply_rejects_new_anchor_and_wrong_start_target_without_mutation():
    batch=validate_batch(flow_batch())
    original=__import__("copy").deepcopy(batch)
    step={"step_id":"bad","action_type":"open_detail","target_region_id":"r1","start_state":"i2","arrival_state":"i1","prerequisites":["x"],"expected_result":"x","stop_condition":"x"}
    for anchor in ("new-anchor", []):
        diff={"target_type":"step","target_id":"bad","field":"entity","baseline":None,"current":None,"proposed":{"after_step_id":anchor,"step":step}}
        with __import__("pytest").raises(CandidateProjectionError): apply_candidate_diffs(batch,[diff])
        assert batch==original


def test_steps_add_and_order_or_new_id_writes_are_rejected():
    batch=validate_batch(flow_batch())
    candidate={"contract_version":"agent_link_v1","idempotency_key":"x","batch_id":"flow-batch","issue_id":"i","baseline_revision":1,"review_baseline_sha256":"a"*64,"scope":{"interface_ids":["i1","i2"],"relationship_ids":["rel-12"]},"changes":[{"change_type":"steps_add","after_step_id":None,"steps":[{"step_id":"n","action_type":"open_detail","target_region_id":"r1","start_state":"i1","arrival_state":"i2","prerequisites":["x"],"expected_result":"x","stop_condition":"x"}]},{"change_type":"step_order","step_ids":["s1","s2","s3"]}]}
    candidate=validate_candidate(candidate)
    with __import__("pytest").raises(CandidateProjectionError): project_candidate_fields(candidate,batch,candidate["scope"])
