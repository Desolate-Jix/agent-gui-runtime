"""真实链接行框的边缘不等于可点击文字；使用同控件独立 OCR 中心。"""
from copy import deepcopy
from hashlib import sha256

from PIL import Image
import pytest

from app.api import vision
from app.core.runtime_artifacts import pinned_runtime_output_root
from app.operation.recognition.control_corroboration import current_control_ocr_binding, has_current_control_ocr_binding, EVIDENCE_KEY
from tests.test_current_control_ocr_binding import _case
from modules.ocr.contracts import OCRResult, OCRTextMatch, OCRBoundingBox


def test_current_control_uses_observed_text_center_without_rewriting_model_point(tmp_path, monkeypatch):
    candidate, local, uia = _case()
    point = deepcopy(local.refined_click_point)
    path = tmp_path / "frame.png"
    Image.new("RGB", (800, 600), "white").save(path)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[
        OCRTextMatch(local.matched_text, .99, OCRBoundingBox(34, 51, 140, 15))]))
    with pinned_runtime_output_root(tmp_path):
        result = vision._corroborate_vista_direct_point(image_path=path, goal=candidate.label,
            candidate=candidate, point=point, app_name=None, uia_snapshot=uia)
    assert result.refined_click_point == {"x": 180, "y": 114}
    assert result.coordinate_source == "current_control_ocr_text_center"
    assert candidate.element.evidence["vista_direct_identity"]["point"] == point
    assert has_current_control_ocr_binding(candidate, result, uia, sha256(path.read_bytes()).hexdigest())
    assert candidate.element.evidence[EVIDENCE_KEY]["model_point"] == point


@pytest.mark.parametrize("change", [None, "arbitrary_point", "model_outside", "foreign_text", "overlap", "stale"])
def test_center_proof_recomputed_not_trusted_from_label(change):
    candidate, local, uia = _case()
    local.coordinate_source = "current_control_ocr_text_center"
    local.refined_click_point = {"x": 180, "y": 114}
    if change == "arbitrary_point": local.refined_click_point["x"] += 1
    if change == "model_outside": candidate.element.evidence["vista_direct_identity"]["point"]["y"] = 0
    if change == "foreign_text": local.matched_text = "Other button"
    if change == "overlap":
        other = deepcopy(uia["controls"][0]); other.update(control_id="other", runtime_id=[999], name="Other")
        uia["controls"].append(other)
    if change == "stale": uia["scan_complete"] = False
    assert (current_control_ocr_binding(candidate, local, uia, "a" * 64) is not None) == (change is None)
