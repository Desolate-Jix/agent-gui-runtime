"""导航视觉消费者与定位阶段共用空白佐证和当前点唯一性。"""

from copy import deepcopy

import pytest

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.navigation_visual_stability import NavigationVisualStabilityScope, navigation_visual_expectation
from tests.test_navigation_visual_stability import _current, _fixture, _revalidate_preview


def _preview(*, spaceless=True, duplicate=False):
    preview, png = _fixture()
    data = preview.to_dict()
    evidence = data["observation_evidence"]
    local = evidence["recognition"]["result"]["narrow_search_result"]["results"][0]
    local["coordinate_source"] = "vista_point_v1_corroborated_by_local_ocr"
    if spaceless:
        local["matched_text"] = "Viewdetails"
    if duplicate:
        other = deepcopy(data["uia_snapshot"]["controls"][0])
        other.update(control_id="distant-details", runtime_id=[42, 7, 10])
        other["bbox"]["y"] += 70
        other["screen_bbox"]["y"] += 70
        data["uia_snapshot"]["controls"].insert(0, other)
        data["uia_snapshot"]["control_count"] += 1
        evidence["uia"]["control_count"] += 1
    evidence["recognition"]["result_sha256"] = payload_sha256(evidence["recognition"]["result"])
    return _revalidate_preview(data), png


@pytest.mark.parametrize("spaceless,duplicate", [(True, False), (False, True), (True, True)])
def test_navigation_expectation_accepts_corroborated_spacing_and_unique_point(spaceless, duplicate):
    preview, png = _preview(spaceless=spaceless, duplicate=duplicate)
    target = navigation_visual_expectation(preview)["selected_target"]
    assert target["control_id"] == "details-control" and target["runtime_id"] == [42, 7, 9]
    assert target["matched_text"] == ("Viewdetails" if spaceless else "View details")
    scope = NavigationVisualStabilityScope(preview, png)
    proof = scope.validate(_current(preview, png), png)
    assert proof.to_reference()["changed_pixels"] == 0


@pytest.mark.parametrize("mutation", ["overlap", "runtime_id", "control_id", "screen_bbox", "role", "point", "ocr"])
def test_navigation_consumer_keeps_identity_geometry_and_overlap_rejections(mutation):
    preview, _ = _preview(spaceless=True, duplicate=True)
    data = preview.to_dict()
    controls = data["uia_snapshot"]["controls"]
    local = data["observation_evidence"]["recognition"]["result"]["narrow_search_result"]["results"][0]
    if mutation == "overlap":
        controls[0]["bbox"] = deepcopy(controls[1]["bbox"])
        controls[0]["screen_bbox"] = deepcopy(controls[1]["screen_bbox"])
    elif mutation == "runtime_id": controls[0]["runtime_id"] = list(controls[1]["runtime_id"])
    elif mutation == "control_id": controls[0]["control_id"] = controls[1]["control_id"]
    elif mutation == "screen_bbox": controls[1]["screen_bbox"]["x"] += 1
    elif mutation == "role": controls[1]["control_type"] = "Hyperlink"
    elif mutation == "point": local["refined_click_point"]["y"] -= 20
    elif mutation == "ocr": local["matched_text"] = "ViewdetailsSubmit"
    with pytest.raises(ValueError):
        navigation_visual_expectation(_revalidate_preview(data))
