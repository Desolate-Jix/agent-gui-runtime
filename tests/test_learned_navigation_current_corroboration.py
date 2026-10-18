"""学习控件消费者保留局部 OCR 佐证，并用当前点消歧同名控件。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.learned_control_reference import recognition_target_from_learned_control, validate_current_learned_control
from app.vision.schemas import BBox


def _case(*, text="GoogleSearch", duplicate=False):
    binding = {
        "contract_version": "learned_control_binding_v1",
        "reference": {"interface_id": "interface-search", "version_id": "interface-version-" + "a" * 64,
                      "region_id": "region-search"},
        "task_id": "task-new-search", "content_sha256": "a" * 64,
        "region": {"region_id": "region-search", "name": "Search", "kind": "button", "meaning": "Open results",
                   "recognition_text": "Google Search", "bbox": [1, 1, 10, 10]},
        "application_identity": {"kind": "native", "executable_path": "c:\\synthetic\\search.exe"},
        "source_screenshot_sha256": "b" * 64,
    }
    binding["binding_sha256"] = payload_sha256(binding)
    candidate = SimpleNamespace(candidate_id="candidate-current", element_id="element-current",
        label="Google Search", text="Google Search", role="button", refined_bbox=None,
        element=SimpleNamespace(label="Google Search", text="Google Search", role="button",
                                bbox=BBox(x=1136, y=851, w=131, h=36)))
    local = SimpleNamespace(candidate_id=candidate.candidate_id, element_id=candidate.element_id,
        matched_text=text, refined_click_point={"x": 1192, "y": 862}, status="grounded", confidence=0.82,
        coordinate_source="vista_point_v1_corroborated_by_local_ocr",
        crop_bbox={"x": 1112, "y": 827, "w": 179, "h": 84},
        matched_text_bbox={"x": 1154, "y": 862, "w": 97, "h": 16})
    control = {"control_id": "current", "name": "Google Search", "control_type": "Button",
               "enabled": True, "visible": True, "patterns": ["Invoke"], "bbox": candidate.element.bbox.to_dict()}
    controls = [control]
    if duplicate:
        controls.insert(0, {**deepcopy(control), "control_id": "distant", "bbox": {**control["bbox"], "y": 537}})
    return dict(binding=binding, candidate=candidate, local=local, uia={"controls": controls},
        application={**binding["application_identity"], "process_create_time": 1.0},
        semantic_action="open_detail", control_target=recognition_target_from_learned_control(binding, semantic_action="open_detail"))


def test_consumer_accepts_already_corroborated_ocr_spacing():
    assert validate_current_learned_control(**_case()) is None


def test_consumer_uses_current_point_not_global_same_label_count():
    assert validate_current_learned_control(**_case(text="Google Search", duplicate=True)) is None


@pytest.mark.parametrize("reverse", [False, True])
def test_spacing_and_distant_same_name_are_accepted_without_first_match_selection(reverse):
    case = _case(duplicate=True)
    if reverse:
        case["uia"]["controls"].reverse()
    assert validate_current_learned_control(**case) is None


@pytest.mark.parametrize("mutation", [
    "overlap", "no_hit", "disabled", "invisible", "unknown_enabled", "unknown_visible",
    "wrong_uia_role", "wrong_uia_label",
    "wrong_candidate_label", "wrong_candidate_role", "wrong_ocr_text", "unverified",
    "wrong_coordinate_source", "ocr_outside", "point_outside_ocr", "wrong_local_candidate",
    "wrong_local_element", "wrong_target", "wrong_binding", "wrong_application",
])
def test_consumer_rejects_ambiguous_or_inconsistent_current_evidence(mutation):
    case = _case()
    control = case["uia"]["controls"][0]
    local = case["local"]
    if mutation == "overlap": case["uia"]["controls"].append({**deepcopy(control), "control_id": "overlap"})
    elif mutation == "no_hit": control["bbox"]["y"] = 537
    elif mutation == "disabled": control["enabled"] = False
    elif mutation == "invisible": control["visible"] = False
    elif mutation == "unknown_enabled": control["enabled"] = None
    elif mutation == "unknown_visible": control["visible"] = None
    elif mutation == "wrong_uia_role": control["control_type"] = "Hyperlink"
    elif mutation == "wrong_uia_label": control["name"] = "GoogleSearch"
    elif mutation == "wrong_candidate_label": case["candidate"].label = "GoogleSearch"
    elif mutation == "wrong_candidate_role": case["candidate"].role = "link"
    elif mutation == "wrong_ocr_text": local.matched_text = "GoogleSearchSubmit"
    elif mutation == "unverified": local.status = "unverified"
    elif mutation == "wrong_coordinate_source": local.coordinate_source = "unknown"
    elif mutation == "ocr_outside": local.matched_text_bbox["x"] = 1300
    elif mutation == "point_outside_ocr": local.refined_click_point["y"] = 861
    elif mutation == "wrong_local_candidate": local.candidate_id = "foreign"
    elif mutation == "wrong_local_element": local.element_id = "foreign"
    elif mutation == "wrong_target": case["control_target"]["label"] = "Other"
    elif mutation == "wrong_binding": case["binding"]["region"]["recognition_text"] = "Other"
    elif mutation == "wrong_application": case["application"]["executable_path"] = "c:\\other.exe"
    with pytest.raises(ValueError):
        validate_current_learned_control(**case)
