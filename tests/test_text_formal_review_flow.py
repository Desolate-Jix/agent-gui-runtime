from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from urllib.parse import urlsplit

from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.reviewed_workflow_replay import resolve_current_state, select_transition_for_review, validate_current_grounding, validate_review_grounding_preview
from tests.test_live_runtime_composition_w3b import _adapter, _OriginReader
from tests.test_native_current_evidence import _NativeIdentityReader
from test_reviewed_workflow_compiler_v2 import _base_review, _persist_reviewed_workflow, _run_compile

PARAMETERS = {"contract_version": "reviewed_text_parameters_v1", "target_field_id": "job_card", "content": {"kind": "literal", "text": "\u79d8\u5bc6\u539f\u6587"}, "clear_existing": True, "sensitive": True, "submit": False, "clipboard_policy": "restore_previous"}
POLICY = {"minimum_confidence": 0.9, "minimum_score_margin": 0.2}

def _text_review():
    review = _base_review()
    node, edge = review["nodes"][0], review["edges"][0]
    candidate = node["action_candidates"][0]
    candidate.update(semantic_action="fill_field", target_control_id="job_card", target_region_id="", text_parameters=deepcopy(PARAMETERS))
    edge.update(action_type="fill_field", target_control_id="job_card", target_region_id="", text_parameters=deepcopy(PARAMETERS), requires_user_confirmation=True, risk_level="medium")
    return review

def text_preview_inputs(tmp_path):
    """真实编译与当前定位链，供本地 owner/Controller 测试复用。"""
    source, digest = _persist_reviewed_workflow(tmp_path, _text_review())
    compiled = _run_compile(tmp_path, source, digest)
    assert compiled["status"] == "compiled", compiled
    asset = compiled["asset"]
    transition = next(item for item in asset["transitions"] if item["semantic_action"] == "fill_field")
    origin = asset["application"]["canonical_origin"]
    adapter, _, screenshot, _, _ = _adapter(tmp_path, asset, origin=_OriginReader(origin=origin), application_identity_key=f"web:{urlsplit(origin).hostname}")
    adapter._native_identity_reader = _NativeIdentityReader(executable_path=r"c:\browser\browser.exe")
    from tests.text_field_fixture_support import SyntheticTextFieldReader
    adapter._text_field_reader = SyntheticTextFieldReader()
    current = adapter.capture_current(session_id="text-review", asset=asset, target_window_handle=4242)
    assert current["screenshot_sha256"] == sha256(screenshot.paths[0].read_bytes()).hexdigest()
    resolution = resolve_current_state(asset, current)
    selection = select_transition_for_review(asset, resolution, transition_id=transition["transition_id"], current_observation=current)
    assert selection["status"] == "selected", selection
    resolved = adapter.resolve(session_id="text-review", selection=selection, current_observation=current)
    assert resolved["status"] == "resolved", resolved
    gate = ReviewedWorkflowGateAdapter().evaluate_review(selection=selection, grounding=resolved["grounding"], **resolved["gate_context"])
    return asset, adapter, transition, current, resolution, selection, resolved, gate


def test_compiled_fill_only_reaches_read_only_grounded_preview_with_redacted_reference(tmp_path):
    asset, _, transition, _, _, selection, resolved, gate = text_preview_inputs(tmp_path)
    assert transition["risk_policy"]["requires_user_confirmation"] is True
    assert transition["risk_policy"]["risk_level"] in {"medium", "high"}
    assert "text_parameters" not in selection
    assert "\u79d8\u5bc6\u539f\u6587" not in str(selection)
    assert selection["text_parameters_ref"]["sensitive"] is True
    preview = validate_review_grounding_preview(asset, selection, resolved["grounding"], gate, policy=POLICY)
    assert preview["status"] == "validated", preview
    assert preview["text_parameters_ref"] == selection["text_parameters_ref"]
    assert "\u79d8\u5bc6\u539f\u6587" not in str(preview)
    assert validate_current_grounding(asset, selection, resolved["grounding"], gate, policy=POLICY)["status"] == "blocked"
