"""OCR 留白中的重复文字不能冒充目标控件内的重复标签。"""
from copy import deepcopy

import pytest

from app.core.runtime_artifacts import pinned_runtime_output_root
from app.operation.recognition.local_grounding import run_local_grounding
from app.operation.recognition.schemas import LocalGroundingRequest
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch
from tests.test_uia_action_identity_context import _rig


def _run(tmp_path, *, kind="Button", variant="outside"):
    fast, arguments = _rig(tmp_path, kind=kind)
    candidate = next(deepcopy(c) for c in arguments["candidates"]
                     if c.element.evidence["screen_inventory_action"]["source_id"] == "selected")
    inside = OCRTextMatch("Atlas Search", .99, OCRBoundingBox(24, 24, 95, 12))
    second = OCRTextMatch("Atlas Search", .98, OCRBoundingBox(24, 64, 95, 12))
    if variant == "inside_duplicate":
        second.bbox.y = 42
    elif variant == "no_source":
        candidate.element.evidence.clear()
    elif variant == "drifted_box":
        candidate.element.evidence["screen_inventory_action"]["bbox"]["x"] += 1
    elif variant == "synthetic":
        candidate.bbox_refine_reason = "synthetic_bbox_around_vista_direct_point"
    matches = [second] if variant == "outside_only" else [inside, second]
    image = fast["screen_reading"]["image_path"]
    with pinned_runtime_output_root(tmp_path):
        result = run_local_grounding(LocalGroundingRequest(
            image_path=image, goal="Atlas Search", candidates=[candidate],
            ocr_scan=lambda path: OCRResult(image_path=path, matches=matches)))
    return result.results[0], matches


@pytest.mark.parametrize("kind", ["Button", "Hyperlink"])
def test_padding_namesake_does_not_defeat_target_control_match(tmp_path, kind):
    result, matches = _run(tmp_path, kind=kind)
    assert result.status == "grounded"
    assert result.matched_text == "Atlas Search"
    assert result.matched_text_bbox == {"x": 24, "y": 24, "width": 95, "height": 12}
    assert "local_ocr_scoped_to_control_bbox" in result.reasons
    assert len(matches) == 2


@pytest.mark.parametrize("variant", ["inside_duplicate", "outside_only", "no_source", "drifted_box", "synthetic"])
def test_context_scope_does_not_invent_unique_target_or_geometry(tmp_path, variant):
    result, _ = _run(tmp_path, variant=variant)
    assert result.status != "grounded"
    assert result.matched_text is None
