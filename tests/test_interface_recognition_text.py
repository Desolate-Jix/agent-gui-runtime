from __future__ import annotations

import base64
from io import BytesIO
from copy import deepcopy
from types import SimpleNamespace

import pytest

from PIL import Image

from app.agent_link.contracts import AgentLinkError, validate_batch
from app.agent_link.candidate_projection import apply_candidate_diffs, index_candidate_fields, project_candidate_fields
from app.agent.reviewed_workflow_compiler import _stable_node_anchors
from app.desktop_review.external_mapping import build_external_workflow_review

def _png():
    stream = BytesIO(); Image.new("RGB", (1, 1), "white").save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def batch(recognition_text=None):
    interface = {"interface_id":"screen","screenshot_id":"shot","meaning":"purpose prose","regions":[]}
    if recognition_text is not None: interface["recognition_text"] = recognition_text
    return {"contract_version":"agent_link_v1","idempotency_key":"key","batch_id":"batch","title":"title","learning_outcome":"completed","screenshots":[{"screenshot_id":"shot","png_base64":_png()}],"interfaces":[interface],"relationships":[],"steps":[],"issues":[]}

def test_absent_hash_shape_and_observable_external_anchor_are_separate():
    old = validate_batch(batch())
    assert "recognition_text" not in old["interfaces"][0]
    current = validate_batch(batch("Notepad"))
    review = build_external_workflow_review(batch=current, task_id="task", source_ref="a"*64, revision=1)
    node = review["nodes"][0]
    assert node["display_name"] == node["agent_description"] == "purpose prose"
    assert node["recognition_text"] == "Notepad"
    anchors, _ = _stable_node_anchors(node, "state")
    assert [item["label"] for item in anchors] == ["Notepad"]

def test_external_missing_text_omits_prose_but_nonexternal_keeps_legacy_anchor():
    review = build_external_workflow_review(batch=validate_batch(batch()), task_id="task", source_ref="a"*64, revision=1)
    node = review["nodes"][0]
    assert _stable_node_anchors(node, "state")[0] == []
    node["surface_type"] = "native"
    node["evidence"].pop("external_source_kind")
    assert _stable_node_anchors(node, "state")[0][0]["label"] == "purpose prose"

def test_semantic_candidate_roundtrip_and_noninterface_rejection():
    source = validate_batch(batch())
    candidate = {"changes":[{"change_type":"semantic","target_type":"interface","target_id":"screen","meaning":"purpose prose","recognition_text":"Notepad"}]}
    writes = project_candidate_fields(candidate, source, {"interface_ids":["screen"],"relationship_ids":[]})
    indexed = index_candidate_fields(source)
    diffs = [{"target_type":w.target_type,"target_id":w.target_id,"field":w.field,"baseline":indexed[(w.target_type,w.target_id,w.field)],"current":indexed[(w.target_type,w.target_id,w.field)],"proposed":w.proposed} for w in writes]
    assert apply_candidate_diffs(source, diffs)["interfaces"][0]["recognition_text"] == "Notepad"
    with pytest.raises(Exception):
        project_candidate_fields({"changes":[{"change_type":"semantic","target_type":"region","target_id":"none","meaning":"x","recognition_text":"x"}]}, source, {"interface_ids":["screen"],"relationship_ids":[]})
    with pytest.raises(AgentLinkError): validate_batch(batch("  "))
