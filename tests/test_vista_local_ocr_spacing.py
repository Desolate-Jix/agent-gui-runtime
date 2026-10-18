"""局部 OCR 允许已绑定标签的空白丢失，不放宽候选身份和点位核验。"""

import pytest
from PIL import Image

from app.api import vision
from app.core.runtime_artifacts import pinned_runtime_output_root
from app.operation.recognition.control_target import control_target_matches, control_target_ocr_matches, uia_control_matches
from app.vision.schemas import BBox, ImageSize
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def _corroborate(tmp_path, monkeypatch, *, label="Google Search", text="GoogleSearch",
                 point=None, candidate_label=None, candidate_role="button", bbox=None):
    source = tmp_path / "synthetic-screen.png"
    Image.new("RGB", (2560, 1400), "white").save(source)
    point = point or {"x": 1178, "y": 862}
    candidate = vision._recognition_candidate_from_vista_direct(
        goal=label if candidate_label is None else candidate_label, point=point,
        image_size=ImageSize(width=2560, height=1400), bbox_size=48,
    )
    candidate.role = candidate_role
    candidate.element.role = candidate_role
    candidate.element.bbox = BBox(x=1136, y=851, w=131, h=36)
    candidate.refined_bbox = None
    matches = [] if text is None else [OCRTextMatch(
        text=text, score=0.99,
        bbox=OCRBoundingBox(**(bbox or {"x": 42, "y": 35, "width": 97, "height": 16})),
    )]
    monkeypatch.setattr(vision.ocr_service, "scan_image",
                        lambda path: OCRResult(image_path=path, matches=matches))
    with pinned_runtime_output_root(tmp_path / "output"):
        return vision._corroborate_vista_direct_point(
            image_path=source, goal=label, candidate=candidate, point=point, app_name="synthetic",
            control_target={"contract_version": "recognition_control_target_v1", "label": label,
                            "role": "button", "source_binding_sha256": "a" * 64},
        )


@pytest.mark.parametrize("label,text", [
    ("Google Search", "GoogleSearch"),
    ("Open Settings", "OpenSettings"),
    ("Google Search", "Google Search"),
])
def test_bound_local_ocr_spacing_preserves_observed_text_and_model_point(tmp_path, monkeypatch, label, text):
    result = _corroborate(tmp_path, monkeypatch, label=label, text=text)
    assert result.status == "grounded"
    assert result.confidence == 0.82
    assert result.matched_text == text
    assert result.crop_bbox == {"x": 1112, "y": 827, "w": 179, "h": 84}
    assert result.matched_text_bbox == {"x": 1154, "y": 862, "w": 97, "h": 16}
    assert result.refined_click_point == {"x": 1178, "y": 862}
    assert "vista_point_matches_local_ocr" in result.reasons


@pytest.mark.parametrize("change", [
    {"text": None}, {"text": "GoogleSearcb"}, {"text": "Google-Search"},
    {"text": "Search"}, {"text": "GoogleSearchSubmit"},
    {"candidate_label": "GoogleSearch"}, {"candidate_label": "Account Settings"},
    {"candidate_role": "link"},
    {"point": {"x": 1178, "y": 861}},
    {"bbox": {"x": 0, "y": 0, "width": 20, "height": 16}},
])
def test_spacing_does_not_cover_missing_mismatched_or_displaced_evidence(tmp_path, monkeypatch, change):
    result = _corroborate(tmp_path, monkeypatch, **change)
    assert result.status == "unverified" and result.confidence == 0.0
    assert "vista_point_lacks_local_corroboration" in result.reasons


def test_control_identity_still_requires_exact_word_boundaries():
    target = {"label": "Google Search", "role": "button"}
    assert control_target_matches("Google Search", "button", target)
    assert not control_target_matches("GoogleSearch", "button", target)
    assert not uia_control_matches({"name": "GoogleSearch", "control_type": "Button"}, target)


def test_whitespace_collision_cannot_merge_two_control_identities():
    target = {"label": "Google Search", "role": "button"}
    controls = [
        {"control_id": "target", "name": "Google Search", "control_type": "Button"},
        {"control_id": "other", "name": "GoogleSearch", "control_type": "Button"},
    ]
    assert [item["control_id"] for item in controls if uia_control_matches(item, target)] == ["target"]
    assert control_target_ocr_matches("GoogleSearch", "button", target, candidate_label="Google Search")
    assert not control_target_ocr_matches("GoogleSearch", "button", target, candidate_label="GoogleSearch")


@pytest.mark.parametrize("change", [
    {"candidate_role": "link"},
    {"candidate_label": "Account Settings"},
    {"point": {"x": 1178, "y": 861}},
    {"text": "Google-Search"},
])
def test_exact_ocr_cannot_bypass_typed_target_identity_or_point(tmp_path, monkeypatch, change):
    # 精确 OCR 也必须遵守已有控件身份；不能从中心点快捷分支提前返回。
    options = {"text": "Google Search", **change}
    result = _corroborate(tmp_path, monkeypatch, **options)
    assert result.status == "unverified"
    assert result.confidence == 0.0
    assert result.coordinate_source == "vista_point_v1_unverified"
