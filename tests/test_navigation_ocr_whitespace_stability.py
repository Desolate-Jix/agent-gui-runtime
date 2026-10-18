"""两帧 OCR 空白形式变化不改变已绑定导航目标，也不改写原始证据。"""

from copy import deepcopy
import json

import pytest

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.learned_control_reference import recognition_target_from_learned_control
from app.agent.navigation_visual_stability import (
    NavigationVisualStabilityScope,
    verify_navigation_visual_stability_reference,
)
from tests.test_navigation_visual_stability import _current, _fixture, _png, _revalidate_preview


def _preview(label="Open Settings", text="OpenSettings", *, role="button"):
    preview, png = _fixture()
    data = preview.to_dict()
    binding = data["intent"]["learned_control"]
    binding["region"].update(recognition_text=label, kind=role)
    binding["binding_sha256"] = payload_sha256({
        key: value for key, value in binding.items() if key != "binding_sha256"
    })
    projection = data["observation_evidence"]["recognition"]["result"]
    projection["candidate_result"]["summary"]["control_target"] = recognition_target_from_learned_control(
        binding, semantic_action="open_detail"
    )
    candidate = projection["candidate_result"]["candidates"][0]
    for item in (candidate, candidate["element"]):
        item.update(label=label, text=label, role=role)
    control = data["uia_snapshot"]["controls"][0]
    control.update(name=label, control_type="Hyperlink" if role == "link" else "Button")
    local = projection["narrow_search_result"]["results"][0]
    local.update(matched_text=text, coordinate_source="vista_point_v1_corroborated_by_local_ocr")
    data["observation_evidence"]["recognition"]["result_sha256"] = payload_sha256(projection)
    return _revalidate_preview(data), png


def _next(preview, png, text):
    current = _current(preview, png)
    projection = current["recognition"]["result"]
    projection["narrow_search_result"]["results"][0]["matched_text"] = text
    current["recognition"]["result_sha256"] = payload_sha256(projection)
    return current


@pytest.mark.parametrize("label,before,after,role", [
    ("Open Settings", "OpenSettings", "Open Settings", "button"),
    ("Open Settings", "Open Settings", "OpenSettings", "button"),
    ("View details", "Viewdetails", "View\tdetails", "link"),
    ("查看 Settings", "查看Settings", "查看 Settings", "button"),
    ("打开 设置", "打开设置", "打开\u3000设置", "button"),
    ("查看 Settings", "查看 Settings", "查 看Settings", "link"),
])
def test_whitespace_only_transition_preserves_raw_evidence_and_persisted_proof(label, before, after, role):
    preview, png = _preview(label, before, role=role)
    current = _next(preview, png, after)
    original_preview, original_current = deepcopy(preview.to_dict()), deepcopy(current)
    scope = NavigationVisualStabilityScope(preview, png)
    expectation = scope.expectation_reference
    assert expectation["selected_target"]["matched_text"] == before

    reference = scope.validate(current, png).to_reference()
    assert reference["changed_pixels"] == 0
    assert reference["before_evidence_sha256"] == payload_sha256(original_preview["observation_evidence"])
    assert reference["after_evidence_sha256"] == payload_sha256(original_current)
    assert preview.to_dict() == original_preview and current == original_current
    assert scope.expectation_reference == expectation
    verify_navigation_visual_stability_reference(
        json.loads(json.dumps(reference)), original_preview["observation_evidence"], current,
        json.loads(json.dumps(expectation)), png, png,
    )


@pytest.mark.parametrize("text", [
    "OpenSettingx", "Open-Settings", "OpenSettingsSubmit", "Settings", "opensettings", "",
])
def test_character_punctuation_case_and_missing_text_changes_remain_rejected(text):
    preview, png = _preview()
    with pytest.raises(ValueError):
        NavigationVisualStabilityScope(preview, png).validate(_next(preview, png, text), png)


@pytest.mark.parametrize("change", [
    "application", "uia_identity", "candidate_label", "candidate_role", "point", "risk",
    "ocr_bbox", "ocr_bbox_inside", "coordinate_source", "confidence", "unverified", "old_capture", "target_pixels",
])
def test_whitespace_does_not_hide_identity_geometry_risk_or_pixel_changes(change):
    preview, png = _preview()
    after_png = _png(((130, 75),)) if change == "target_pixels" else png
    current = _next(preview, after_png, "Open Settings")
    projection = current["recognition"]["result"]
    candidate = projection["candidate_result"]["candidates"][0]
    local = projection["narrow_search_result"]["results"][0]
    if change == "application": current["application"]["process_create_time"] += 1
    elif change == "uia_identity": current["uia"]["snapshot_sha256"] = "f" * 64
    elif change == "candidate_label": candidate["label"] = "Different Settings"
    elif change == "candidate_role": candidate["role"] = "link"
    elif change == "point": local["refined_click_point"] = {"x": 200, "y": 75}
    elif change == "risk": candidate["element"]["interaction_policy"]["ad_risk"] = 0.95
    elif change == "ocr_bbox": local["matched_text_bbox"]["x"] = 200
    elif change == "ocr_bbox_inside": local["matched_text_bbox"]["w"] -= 1
    elif change == "coordinate_source": local["coordinate_source"] = "untrusted"
    elif change == "confidence": local["confidence"] = 0.99
    elif change == "unverified": local["status"] = "unverified"
    elif change == "old_capture": current["capture"]["capture_id"] = "capture-before"
    current["recognition"]["result_sha256"] = payload_sha256(projection)
    with pytest.raises(ValueError):
        NavigationVisualStabilityScope(preview, png).validate(current, after_png)


def test_existing_exact_text_reference_keeps_its_original_structure():
    preview, png = _preview(text="Open Settings")
    scope = NavigationVisualStabilityScope(preview, png)
    current = _next(preview, png, "Open Settings")
    expectation = scope.expectation_reference
    reference = scope.validate(current, png).to_reference()
    assert expectation["contract_version"] == "navigation_visual_expectation_v1"
    assert expectation["selected_target"]["matched_text"] == "Open Settings"
    verify_navigation_visual_stability_reference(
        reference, preview.to_dict()["observation_evidence"], current, expectation, png, png
    )
