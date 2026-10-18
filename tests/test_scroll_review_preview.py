from copy import deepcopy
from hashlib import sha256
import json
from urllib.parse import urlsplit

import pytest

from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.reviewed_workflow_replay import (
    resolve_current_state, select_transition_for_review, select_verified_transition,
    validate_current_grounding, validate_review_grounding_preview,
)
from tests.test_live_runtime_composition_w3b import _adapter, _OriginReader
from tests.test_native_current_evidence import _NativeIdentityReader
from test_reviewed_scroll_compilation import PARAMETERS, scroll_review
from test_reviewed_workflow_compiler_v2 import _persist_reviewed_workflow, _run_compile


POLICY = {"minimum_confidence": 0.9, "minimum_score_margin": 0.2}


def _rehash_selection(selection):
    body = {key: value for key, value in selection.items() if key not in {"selection_sha256", "review_selection_sha256"}}
    digest = sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    selection.update(selection_sha256=digest, review_selection_sha256=digest)


def scroll_preview_inputs(tmp_path):
    source, digest = _persist_reviewed_workflow(tmp_path, scroll_review())
    compiled = _run_compile(tmp_path, source, digest)
    assert compiled["status"] == "compiled"
    asset = compiled["asset"]
    origin = asset["application"]["canonical_origin"]
    adapter, _, screenshot, _, _ = _adapter(tmp_path, asset,
        origin=_OriginReader(origin=origin), application_identity_key=f"web:{urlsplit(origin).hostname}")
    adapter._native_identity_reader = _NativeIdentityReader(executable_path=r"c:\browser\browser.exe")
    current = adapter.capture_current(session_id="scroll-review", asset=asset, target_window_handle=4242)
    assert current["screenshot_sha256"] == sha256(screenshot.paths[0].read_bytes()).hexdigest()
    resolution = resolve_current_state(asset, current)
    assert resolution["status"] == "resolved"
    transition = next(item for item in asset["transitions"] if item["semantic_action"] == "scroll_region")
    selection = select_transition_for_review(asset, resolution,
        transition_id=transition["transition_id"], current_observation=current)
    assert selection["status"] == "selected", selection
    resolved = adapter.resolve(session_id="scroll-review", selection=selection, current_observation=current)
    assert resolved["status"] == "resolved", resolved
    grounding = resolved["grounding"]
    gate = ReviewedWorkflowGateAdapter().evaluate_review(selection=selection, grounding=grounding, **resolved["gate_context"])
    return asset, adapter, current, resolution, selection, grounding, gate, resolved["gate_context"]


def test_reviewed_scroll_real_capture_to_gate_preview_binds_parameters_without_execution(tmp_path):
    asset, _, current, resolution, selection, grounding, gate, context = scroll_preview_inputs(tmp_path)
    assert selection["scroll_parameters"] == PARAMETERS
    assert grounding["scroll_parameters"] == PARAMETERS
    assert gate["allowed"] is True
    assert gate["scroll_parameters"] == PARAMETERS
    preview = validate_review_grounding_preview(asset, selection, grounding, gate, policy=POLICY)
    assert preview["status"] == "validated", preview
    assert preview["scroll_parameters"] == PARAMETERS
    assert preview["bbox"] == {"x": 40, "y": 50, "w": 120, "h": 40}
    assert preview["click_point"] == {"x": 100, "y": 70}
    assert preview["review_only"] is True
    assert preview["grants_action_authority"] is False
    assert preview["execute_binding_enabled"] is False
    assert ReviewedWorkflowGateAdapter().evaluate(selection=selection, grounding=grounding, **context)["allowed"] is False
    assert validate_current_grounding(asset, selection, grounding, gate, policy=POLICY)["status"] == "blocked"
    assert select_verified_transition(asset, resolution, transition_id=selection["transition_id"],
        current_observation=current, human_confirmation={"decision": "approved"})["failure_code"] == "human_review_required"
    selection["scroll_parameters"]["direction"] = "up"
    assert preview["scroll_parameters"] == PARAMETERS
    assert grounding["scroll_parameters"] == PARAMETERS
    assert gate["scroll_parameters"] == PARAMETERS


@pytest.mark.parametrize("part", ["selection", "grounding", "gate"])
@pytest.mark.parametrize("mutation", [{"direction": "up"}, {"wheel_clicks": True}, {"target_container_id": "other-pane"}, {"x": 10}])
def test_scroll_preview_rejects_independent_parameter_drift_even_when_rehashed(tmp_path, part, mutation):
    asset, _, _, _, selection, grounding, gate, _ = scroll_preview_inputs(tmp_path)
    values = {"selection": selection, "grounding": grounding, "gate": gate}
    values[part]["scroll_parameters"].update(mutation)
    if part == "selection":
        _rehash_selection(selection)
        gate["selection_sha256"] = selection["selection_sha256"]
    result = validate_review_grounding_preview(asset, selection, grounding, gate, policy=POLICY)
    assert result["status"] == "blocked", result


@pytest.mark.parametrize("part", ["selection", "grounding", "gate"])
def test_scroll_preview_rejects_missing_parameters_in_any_layer(tmp_path, part):
    asset, _, _, _, selection, grounding, gate, _ = scroll_preview_inputs(tmp_path)
    del {"selection": selection, "grounding": grounding, "gate": gate}[part]["scroll_parameters"]
    assert validate_review_grounding_preview(asset, selection, grounding, gate, policy=POLICY)["status"] == "blocked"


@pytest.mark.parametrize("point", [{"x": 160, "y": 70}, {"x": 100, "y": 90}])
def test_scroll_preview_rejects_exclusive_right_bottom_container_edges(tmp_path, point):
    asset, _, _, _, selection, grounding, gate, _ = scroll_preview_inputs(tmp_path)
    grounding["click_point"] = point
    gate["selected_click_point"] = deepcopy(point)
    assert validate_review_grounding_preview(asset, selection, grounding, gate, policy=POLICY)["status"] == "blocked"


def test_current_adapter_does_not_project_parameters_from_a_mutated_selection(tmp_path):
    _, adapter, current, _, selection, _, _, _ = scroll_preview_inputs(tmp_path)
    selection["scroll_parameters"]["wheel_clicks"] = 3
    _rehash_selection(selection)
    result = adapter.resolve(session_id="scroll-review", selection=selection, current_observation=current)
    assert result["status"] == "unresolved"


def test_real_review_gate_rejects_mismatched_scroll_parameters_before_approval(tmp_path):
    _, _, _, _, selection, grounding, _, context = scroll_preview_inputs(tmp_path)
    grounding["scroll_parameters"]["direction"] = "up"
    assert ReviewedWorkflowGateAdapter().evaluate_review(selection=selection, grounding=grounding, **context)["allowed"] is False
