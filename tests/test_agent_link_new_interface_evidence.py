from __future__ import annotations
import base64
from io import BytesIO
from PIL import Image
from app.agent_link.contracts import validate_batch, validate_candidate
from app.agent_link.candidate_projection import apply_candidate_diffs, index_candidate_fields, project_candidate_fields
from test_agent_link_flow_candidates import flow_batch
from copy import deepcopy
import pytest
from app.agent_link.contracts import AgentLinkError
from app.agent_link.candidate_projection import CandidateProjectionError


def _candidate():
    return {"contract_version": "agent_link_v1", "idempotency_key": "new-ui", "batch_id": "flow-batch",
            "issue_id": "issue", "baseline_revision": 1, "review_baseline_sha256": "a" * 64,
            "scope": {"interface_ids": ["i1"], "relationship_ids": []},
            "changes": [{"change_type": "interfaces_add", "anchor_interface_id": "i1",
                         "screenshots": [{"screenshot_id": "new-shot", "png_base64": _png()}],
                         "interfaces": [{"interface_id": "new-ui", "screenshot_id": "new-shot", "meaning": "新界面",
                                         "regions": [{"region_id": "new-region", "bbox": [1., 1., 5., 4.], "name": "新控件", "meaning": "新控件"}]}]}]}


def _diffs(batch, candidate):
    return [{"target_type": w.target_type, "target_id": w.target_id, "field": w.field,
             "baseline": None, "current": None, "proposed": deepcopy(w.proposed)}
            for w in project_candidate_fields(validate_candidate(candidate), batch, candidate["scope"])]


@pytest.mark.parametrize("case", ["baseline", "region_collision", "bbox", "corrupt_png", "empty_png", "anchor", "new_anchor", "cross_group"])
def test_new_interface_projection_rejects_unbound_or_invalid_evidence(case):
    batch, candidate = validate_batch(flow_batch()), _candidate()
    group = candidate["changes"][0]
    if case == "baseline": candidate.pop("review_baseline_sha256")
    elif case == "region_collision": group["interfaces"][0]["regions"][0]["region_id"] = "r1"
    elif case == "bbox": group["interfaces"][0]["regions"][0]["bbox"][2] = 100.
    elif case == "corrupt_png": group["screenshots"][0]["png_base64"] = group["screenshots"][0]["png_base64"][:44]
    elif case == "empty_png": group["screenshots"][0]["png_base64"] = "AA=="
    elif case == "anchor": group["anchor_interface_id"] = "i3"
    else:
        second = deepcopy(group)
        second["interfaces"][0]["interface_id"] = "second-ui"
        second["interfaces"][0]["regions"][0]["region_id"] = "second-region"
        second["screenshots"][0]["screenshot_id"] = "second-shot"
        second["interfaces"][0]["screenshot_id"] = "second-shot"
        if case == "new_anchor": second["anchor_interface_id"] = "new-ui"
        else:
            second["interfaces"].append(deepcopy(second["interfaces"][0]) | {"interface_id": "cross-ui", "screenshot_id": "new-shot", "regions": []})
        candidate["changes"].append(second)
    before = deepcopy(batch)
    with pytest.raises((AgentLinkError, CandidateProjectionError)):
        _diffs(batch, candidate)
    assert batch == before


@pytest.mark.parametrize("case", ["orphan_shot", "orphan_interface", "bbox", "authority", "anchor_type", "duplicate_region", "metadata_bool", "new_interface_write", "new_region_write", "new_regions_add"])
def test_pure_new_interface_apply_rejects_partial_malformed_or_secondary_writes(case):
    batch = validate_batch(flow_batch())
    diffs = _diffs(batch, _candidate())
    shot, interface = diffs
    if case == "orphan_shot": diffs = [shot]
    elif case == "orphan_interface": diffs = [interface]
    elif case == "bbox": interface["proposed"]["interface"]["regions"][0]["bbox"][2] = 100.
    elif case == "authority": interface["proposed"]["interface"]["execute_binding_enabled"] = True
    elif case == "anchor_type": interface["proposed"]["anchor_interface_id"] = []
    elif case == "duplicate_region": interface["proposed"]["interface"]["regions"][0]["region_id"] = "r1"
    elif case == "metadata_bool": shot["proposed"]["width"] = True
    elif case == "new_regions_add":
        diffs.append({"target_type": "region", "target_id": "separate-region", "field": "entity", "baseline": None, "current": None,
                      "proposed": {"interface_id": "new-ui", "region": {"region_id": "separate-region", "bbox": [1., 1., 5., 4.], "name": "新增", "meaning": "新增"}}})
    else:
        target = "interface" if case == "new_interface_write" else "region"
        identity = "new-ui" if target == "interface" else "new-region"
        meaning = "新界面" if target == "interface" else "新控件"
        diffs.append({"target_type": target, "target_id": identity, "field": "meaning", "baseline": meaning, "current": meaning, "proposed": "二次改写"})
    before = deepcopy(batch)
    with pytest.raises(CandidateProjectionError):
        apply_candidate_diffs(batch, diffs)
    assert batch == before

def _png():
    image=Image.new("RGB",(20,10),"white"); out=BytesIO(); image.save(out,format="PNG"); return base64.b64encode(out.getvalue()).decode()

def test_interfaces_add_projects_canonical_screenshot_and_interface_entities():
    batch=validate_batch(flow_batch())
    candidate=validate_candidate({"contract_version":"agent_link_v1","idempotency_key":"new-ui","batch_id":"flow-batch","issue_id":"issue","baseline_revision":1,"review_baseline_sha256":"a"*64,"scope":{"interface_ids":["i1"],"relationship_ids":[]},"changes":[{"change_type":"interfaces_add","anchor_interface_id":"i1","screenshots":[{"screenshot_id":"new-shot","png_base64":_png()}],"interfaces":[{"interface_id":"new-ui","screenshot_id":"new-shot","meaning":"新界面","regions":[{"region_id":"new-region","bbox":[1.0,1.0,5.0,4.0],"name":"新控件","meaning":"新控件"}]}]}]})
    writes=project_candidate_fields(candidate,batch,candidate["scope"])
    assert {(w.target_type,w.target_id,w.field) for w in writes} == {("screenshot","new-shot","entity"),("interface","new-ui","entity")}
    shot=next(w.proposed for w in writes if w.target_type=="screenshot")
    assert shot["width"]==20 and shot["height"]==10 and len(shot["sha256"])==64
    assert ("interface","new-ui","entity") not in index_candidate_fields(batch)
    index=index_candidate_fields(batch)
    diffs=[{"target_type":w.target_type,"target_id":w.target_id,"field":w.field,"baseline":index.get((w.target_type,w.target_id,w.field)),"current":index.get((w.target_type,w.target_id,w.field)),"proposed":w.proposed} for w in writes]
    applied=apply_candidate_diffs(batch,diffs)
    assert applied["screenshots"][-1]["screenshot_id"] == "new-shot"
    assert applied["interfaces"][-1]["interface_id"] == "new-ui"


@pytest.mark.parametrize("collection", ["screenshots", "interfaces"])
def test_new_evidence_aggregate_cap_rejects_at_projection_and_apply(collection):
    wire = flow_batch()
    if collection == "screenshots":
        wire["screenshots"].extend({"screenshot_id": f"old-shot-{n}", "png_base64": _png()} for n in range(31))
    else:
        wire["interfaces"].extend({"interface_id": f"old-ui-{n}", "screenshot_id": "screen", "meaning": "已有界面", "regions": []} for n in range(125))
    full = validate_batch(wire)
    diffs = _diffs(validate_batch(flow_batch()), _candidate())
    with pytest.raises(CandidateProjectionError): _diffs(full, _candidate())
    with pytest.raises(CandidateProjectionError): apply_candidate_diffs(full, diffs)


@pytest.mark.parametrize("case", ["old_shot", "old_interface", "duplicate_shot", "duplicate_interface", "duplicate_region", "oversize_dimensions"])
def test_candidate_evidence_ids_and_png_limits(case):
    candidate = _candidate()
    group = candidate["changes"][0]
    if case == "old_shot":
        group["screenshots"][0]["screenshot_id"] = "screen"; group["interfaces"][0]["screenshot_id"] = "screen"
    elif case == "old_interface": group["interfaces"][0]["interface_id"] = "i1"
    elif case == "duplicate_shot": group["screenshots"].append(deepcopy(group["screenshots"][0]))
    elif case == "duplicate_interface": group["interfaces"].append(deepcopy(group["interfaces"][0]))
    elif case == "duplicate_region": group["interfaces"][0]["regions"].append(deepcopy(group["interfaces"][0]["regions"][0]))
    else:
        image = Image.new("RGB", (4097, 10), "white"); output = BytesIO(); image.save(output, format="PNG")
        group["screenshots"][0]["png_base64"] = base64.b64encode(output.getvalue()).decode("ascii")
    with pytest.raises((AgentLinkError, CandidateProjectionError)):
        _diffs(validate_batch(flow_batch()), candidate)


@pytest.mark.parametrize("location", ["candidate", "change", "screenshot", "interface", "region"])
def test_agent_new_evidence_wire_rejects_authority_and_derived_metadata(location):
    candidate = _candidate(); group = candidate["changes"][0]
    value = {"candidate": candidate, "change": group, "screenshot": group["screenshots"][0],
             "interface": group["interfaces"][0], "region": group["interfaces"][0]["regions"][0]}[location]
    value["sha256" if location == "screenshot" else "execute_binding_enabled"] = "a" * 64 if location == "screenshot" else True
    with pytest.raises(AgentLinkError): validate_candidate(candidate)


@pytest.mark.parametrize("case", ["extra_diff", "missing_baseline", "duplicate_diff", "wrong_shot_id", "wrong_sha", "old_anchor_rebind"])
def test_pure_apply_checks_exact_entity_envelope_and_image_bindings(case):
    batch = validate_batch(flow_batch()); diffs = _diffs(batch, _candidate())
    if case == "extra_diff": diffs[0]["approved"] = True
    elif case == "missing_baseline": diffs[0].pop("baseline")
    elif case == "duplicate_diff": diffs.append(deepcopy(diffs[0]))
    elif case == "wrong_shot_id": diffs[0]["target_id"] = "wrong"
    elif case == "wrong_sha": diffs[0]["proposed"]["sha256"] = "0" * 64
    else: diffs[1]["proposed"]["interface"]["screenshot_id"] = "screen"
    with pytest.raises(CandidateProjectionError): apply_candidate_diffs(batch, diffs)


def test_existing_flow_can_reference_new_interface_but_old_outside_scope_stays_closed():
    candidate, batch = _candidate(), validate_batch(flow_batch())
    step = deepcopy(batch["steps"][0])
    step["change_type"] = "step_flow"
    step.update(start_state="new-ui", arrival_state="i1", target_region_id="new-region")
    candidate["scope"]["interface_ids"].append("i2")
    candidate["scope"]["relationship_ids"] = ["rel-12"]
    candidate["changes"][:0] = [step, {"change_type": "relationship_flow", "relationship_id": "rel-12",
                                     "from_interface_id": "i1", "to_interface_id": "new-ui", "kind": "新的详情"}]
    from app.agent_link.review_baseline import validate_candidate_changes
    checked = validate_candidate(candidate)
    validate_candidate_changes(checked, batch, checked["scope"])
    candidate["changes"][0]["arrival_state"] = "i3"
    checked = validate_candidate(candidate)
    with pytest.raises(AgentLinkError): validate_candidate_changes(checked, batch, checked["scope"])
