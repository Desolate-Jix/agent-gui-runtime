"""公共轴向导航点限幅与逐帧 UIA 消歧来源绑定；仅用合成原图。"""
from copy import deepcopy

import pytest

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.fresh_learning_action_preview import FreshLearningActionPreview, validate_fresh_execution_preview, validate_navigation_execution_equivalence
from app.agent.learned_control_reference import recognition_target_from_learned_control
from app.agent.navigation_visual_stability import NavigationVisualPixelsChanged
from tests.test_navigation_execution_equivalence import _direct, _proof
from tests.test_navigation_visual_stability import _current, _far_pixels, _fixture, _png, _revalidate_preview


def _pair(*, label="Open details", role="button", box=(40, 30, 131, 36), offset=(14, 0),
          disambiguation=True, direct=True, target_pixels=False, refined_box=None):
    original, png = _fixture()
    data = original.to_dict()
    bbox = dict(zip(("x", "y", "w", "h"), box))
    point = {"x": box[0] + box[2] // 2, "y": box[1] + box[3] // 2}
    binding = data["intent"]["learned_control"]
    binding["region"].update(recognition_text=label, kind=role, name=label, bbox=list(box))
    binding["binding_sha256"] = payload_sha256({key: value for key, value in binding.items() if key != "binding_sha256"})
    data["intent"]["goal"] = label
    evidence = data["observation_evidence"]
    evidence["recognition"]["goal"] = label
    projection = evidence["recognition"]["result"]
    for item in (projection, projection["candidate_result"], projection["narrow_search_result"]):
        item["goal"] = label
    projection["candidate_result"]["summary"]["control_target"] = recognition_target_from_learned_control(binding, semantic_action="open_detail")
    candidate = projection["candidate_result"]["candidates"][0]
    candidate.update(label=label, text=label, role=role, refined_bbox=deepcopy(refined_box or bbox))
    candidate["element"].update(label=label, text=label, role=role, bbox=deepcopy(bbox), click_point=dict(point))
    candidate["element"]["evidence"] = {}
    local = projection["narrow_search_result"]["results"][0]
    local.update(matched_text=label, crop_bbox=deepcopy(bbox), matched_text_bbox=deepcopy(bbox),
                 refined_click_point=dict(point), coordinate_source="vista_point_v1_corroborated_by_local_ocr")
    control = data["uia_snapshot"]["controls"][0]
    control.update(name=label, control_type="Button" if role == "button" else "Hyperlink",
                   bbox=deepcopy(bbox), screen_bbox=deepcopy(bbox))
    if disambiguation:
        other = {**deepcopy(control), "control_id": "distant-namesake", "runtime_id": [42, 7, 10]}
        other["bbox"]["y"] += 90
        other["screen_bbox"]["y"] += 90
        data["uia_snapshot"]["controls"].insert(0, other)
        data["uia_snapshot"]["control_count"] = evidence["uia"]["control_count"] = 2
    if direct:
        _direct(data, point)
    if disambiguation:
        _disambiguation(data, point)
    original = _revalidate_preview(data)
    current_png = _png(((box[0] + 5, box[1] + 5),) if target_pixels else _far_pixels())
    data = original.to_dict()
    data["observation_evidence"] = _current(original, current_png)
    data["capture_source"]["source_id"] = "e" * 64
    point = {"x": point["x"] + offset[0], "y": point["y"] + offset[1]}
    data["observation_evidence"]["recognition"]["result"]["narrow_search_result"]["results"][0]["refined_click_point"] = point
    if direct:
        _direct(data, point)
    if disambiguation:
        _disambiguation(data, point)
    return original, _revalidate_preview(data), png, current_png


def _disambiguation(data, point):
    evidence = data["observation_evidence"]
    candidate = evidence["recognition"]["result"]["candidate_result"]["candidates"][0]
    candidate["element"]["evidence"]["current_uia_point_disambiguation"] = {
        "source": "current_screenshot_vista_point_and_uia_bbox_v1", "matching_control_count": 2,
        "selected_control_id": "details-control", "excluded_control_ids": ["distant-namesake"],
        "point": dict(point), "screenshot_sha256": evidence["capture"]["screenshot_sha256"],
    }


@pytest.mark.parametrize("label,role,box,offset", [
    ("Open details", "button", (40, 30, 131, 36), (14, 0)),
    ("Read guide", "link", (60, 40, 100, 40), (16, 9)),
    ("查看详情", "button", (25, 20, 64, 32), (-16, 0)),
    ("打开帮助", "link", (100, 20, 40, 40), (10, -10)),
    ("Show map", "button", (30, 40, 48, 24), (-12, 6)),
    ("Open details", "button", (40, 30, 131, 36), (0, 0)),
])
def test_same_target_axis_bounded_points_require_real_original_image_proof(label, role, box, offset):
    original, current, png, current_png = _pair(label=label, role=role, box=box, offset=offset)
    proof = _proof(original, current, png, current_png)
    assert validate_navigation_execution_equivalence(original, current) is None
    assert validate_fresh_execution_preview(original, current, navigation_visual_proof=proof) is None
    assert original.to_dict()["observation_evidence"]["capture"]["screenshot_sha256"] != current.to_dict()["observation_evidence"]["capture"]["screenshot_sha256"]


@pytest.mark.parametrize("box,offset", [
    ((40, 30, 131, 64), (17, 0)), ((40, 30, 131, 64), (-17, 0)),
    ((40, 30, 40, 40), (11, 0)), ((40, 30, 100, 30), (8, 8)),
    ((40, 30, 80, 80), (16, 17)),
])
def test_global_cap_small_control_and_diagonal_axis_excess_are_rejected(box, offset):
    original, current, png, current_png = _pair(box=box, offset=offset)
    proof = _proof(original, current, png, current_png)
    with pytest.raises(ValueError, match="axis bound"):
        validate_fresh_execution_preview(original, current, navigation_visual_proof=proof)


def test_smallest_effective_target_box_controls_axis_bound():
    original, current, png, current_png = _pair(box=(40, 30, 120, 60), offset=(11, 0),
        refined_box={"x": 80, "y": 30, "w": 40, "h": 60})
    proof = _proof(original, current, png, current_png)
    with pytest.raises(ValueError, match="axis bound"):
        validate_fresh_execution_preview(original, current, navigation_visual_proof=proof)


@pytest.mark.parametrize("mutation", ["hash", "point", "source", "unknown", "count", "selected", "excluded", "duplicate_excluded"])
def test_disambiguation_is_verified_per_frame_even_if_both_claim_same_bad_metadata(mutation):
    original, current, png, current_png = _pair(offset=(1, 0))
    changed = []
    for preview in (original, current):
        data = preview.to_dict()
        fact = data["observation_evidence"]["recognition"]["result"]["candidate_result"]["candidates"][0]["element"]["evidence"]["current_uia_point_disambiguation"]
        if mutation == "hash": fact["screenshot_sha256"] = "f" * 64
        elif mutation == "point": fact["point"] = {"x": 1, "y": 1}
        elif mutation == "source": fact["source"] = "historical-guessed-point"
        elif mutation == "unknown": fact["unchecked_field"] = "must-not-be-ignored"
        elif mutation == "count": fact["matching_control_count"] = 3
        elif mutation == "selected": fact["selected_control_id"] = "distant-namesake"
        elif mutation == "excluded": fact["excluded_control_ids"] = ["unrelated"]
        elif mutation == "duplicate_excluded": fact["excluded_control_ids"] *= 2
        changed.append(_revalidate_preview(data))
    proof = _proof(*changed, png, current_png)
    with pytest.raises(ValueError, match="disambiguation"):
        validate_fresh_execution_preview(*changed, navigation_visual_proof=proof)


@pytest.mark.parametrize("mutation", ["label", "runtime", "bbox", "cross_control", "ocr", "non_direct", "danger"])
def test_target_identity_ocr_risk_and_independent_direct_evidence_are_not_relaxed(mutation):
    original, current, png, current_png = _pair(offset=(1, 0))
    data = current.to_dict()
    candidate = data["observation_evidence"]["recognition"]["result"]["candidate_result"]["candidates"][0]
    local = data["observation_evidence"]["recognition"]["result"]["narrow_search_result"]["results"][0]
    if mutation == "label": candidate["label"] = "Other details"
    elif mutation == "runtime": data["uia_snapshot"]["controls"][1]["runtime_id"][-1] += 9
    elif mutation == "bbox": candidate["refined_bbox"]["x"] += 1
    elif mutation == "cross_control":
        point = {"x": local["refined_click_point"]["x"], "y": local["refined_click_point"]["y"] + 90}
        _direct(data, point); _disambiguation(data, point)
    elif mutation == "ocr": local["matched_text_bbox"]["x"] += 200
    elif mutation == "non_direct": candidate["element"]["evidence"].pop("vista_direct_identity")
    elif mutation == "danger": data["risk"]["hard_blocked"] = True
    with pytest.raises(ValueError):
        if mutation == "danger":
            data["preview_sha256"] = payload_sha256({key: value for key, value in data.items() if key != "preview_sha256"})
            changed = FreshLearningActionPreview.from_dict(data)
        else:
            changed = _revalidate_preview(data)
        proof = _proof(original, changed, png, current_png)
        validate_fresh_execution_preview(original, changed, navigation_visual_proof=proof)


def test_expanded_jitter_without_sealed_proof_or_with_target_pixel_change_is_rejected():
    original, current, _, _ = _pair()
    with pytest.raises(ValueError, match="drifted"):
        validate_fresh_execution_preview(original, current)
    original, current, png, current_png = _pair(target_pixels=True)
    with pytest.raises(NavigationVisualPixelsChanged):
        _proof(original, current, png, current_png)


@pytest.mark.parametrize("first,second", [("Viewdetails", "View details"), ("View details", "Viewdetails"),
                                         ("View\tdetails", "Viewdetails")])
def test_each_frame_verified_local_ocr_spacing_is_not_target_or_risk_drift(first, second):
    original, current, png, current_png = _pair(label="View details", offset=(0, 0), disambiguation=False)
    changed = []
    for preview, text in zip((original, current), (first, second)):
        data = preview.to_dict()
        data["observation_evidence"]["recognition"]["result"]["narrow_search_result"]["results"][0]["matched_text"] = text
        changed.append(_revalidate_preview(data))
    assert validate_navigation_execution_equivalence(*changed) is None
    proof = _proof(*changed, png, current_png)
    assert validate_fresh_execution_preview(*changed, navigation_visual_proof=proof) is None
    assert [item.to_dict()["observation_evidence"]["recognition"]["result"]["narrow_search_result"]["results"][0]["matched_text"] for item in changed] == [first, second]


@pytest.mark.parametrize("mutation", ["typo", "punctuation", "case", "submit", "source", "ocr_box", "element_id"])
def test_local_ocr_spacing_normalization_never_hides_non_spacing_or_unbound_evidence(mutation):
    original, current, _, _ = _pair(label="View details", offset=(0, 0))
    first = original.to_dict()
    first["observation_evidence"]["recognition"]["result"]["narrow_search_result"]["results"][0]["matched_text"] = "Viewdetails"
    original = _revalidate_preview(first)
    data = current.to_dict()
    local = data["observation_evidence"]["recognition"]["result"]["narrow_search_result"]["results"][0]
    if mutation == "typo": local["matched_text"] = "View detai1s"
    elif mutation == "punctuation": local["matched_text"] = "View-details"
    elif mutation == "case": local["matched_text"] = "VIEW details"
    elif mutation == "submit": local["matched_text"] = "View details Submit"
    elif mutation == "source": local["coordinate_source"] = "untrusted"
    elif mutation == "ocr_box": local["matched_text_bbox"]["x"] += 200
    elif mutation == "element_id": local["element_id"] = "different-control"
    with pytest.raises(ValueError):
        validate_navigation_execution_equivalence(original, _revalidate_preview(data))
