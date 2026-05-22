from __future__ import annotations

from app.vision.anchor_grounding import apply_anchor_grounding_evaluation, evaluate_region_grounding
from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion


def _region(*, bbox: BBox, role: str = "icon", constraints: dict | None = None, relations: list[dict] | None = None) -> VisionRegion:
    return VisionRegion(
        region_id="region_icon",
        label="Icon",
        role=role,
        bbox=bbox,
        diagonal=Diagonal(x1=bbox.x, y1=bbox.y, x2=bbox.x + bbox.w, y2=bbox.y + bbox.h),
        normalized_diagonal=NormalizedDiagonal(nx1=0.0, ny1=0.0, nx2=1.0, ny2=1.0),
        description="Icon",
        anchor_relations=relations or [],
        grounding_constraints=constraints or {},
        confidence=0.8,
    )


def test_evaluate_region_grounding_flags_text_inside_visual_only_icon() -> None:
    region = _region(
        bbox=BBox(x=100, y=100, w=120, h=80),
        constraints={
            "text_inclusion_policy": "exclude_text",
            "negative_constraints": [{"anchor_id": "ocr_anchor_1"}],
        },
    )
    anchors = {"ocr_anchor_1": BBox(x=130, y=120, w=40, h=16)}

    evaluation = evaluate_region_grounding(region, anchors, image_size={"width": 400, "height": 300})

    assert evaluation["ok"] is False
    assert evaluation["text_inclusion_policy"] == "exclude_text"
    assert evaluation["included_anchor_ids"] == ["ocr_anchor_1"]
    assert evaluation["violations"][0]["type"] == "text_anchor_included_but_policy_excludes_text"


def test_evaluate_region_grounding_suggests_corrected_bbox_when_text_must_be_included() -> None:
    region = _region(
        bbox=BBox(x=100, y=100, w=40, h=40),
        role="button",
        constraints={
            "text_inclusion_policy": "include_referenced_text",
            "edge_constraints": {"right": {"anchor_id": "ocr_anchor_1"}},
        },
    )
    anchors = {"ocr_anchor_1": BBox(x=150, y=112, w=60, h=18)}

    evaluation = evaluate_region_grounding(region, anchors, image_size={"width": 400, "height": 300})

    assert evaluation["ok"] is False
    assert evaluation["excluded_anchor_ids"] == ["ocr_anchor_1"]
    assert evaluation["anchor_corrected_bbox"] == {"x": 100, "y": 100, "w": 110, "h": 40}
    assert evaluation["violations"][0]["type"] == "referenced_text_anchor_missing_from_bbox"


def test_apply_anchor_grounding_evaluation_writes_evidence_into_constraints() -> None:
    region = _region(
        bbox=BBox(x=100, y=100, w=40, h=40),
        role="button",
        constraints={"text_inclusion_policy": "include_referenced_text"},
        relations=[{"anchor_id": "ocr_anchor_1", "relation": "inside"}],
    )
    response = VisionAnalyzeResponse(
        provider="dummy",
        screen_summary="demo",
        state_guess=None,
        image_size=ImageSize(width=400, height=300),
        regions=[region],
    )
    payload = {
        "anchors": [
            {
                "anchor_id": "ocr_anchor_1",
                "text": "Start",
                "bbox": {"x": 150, "y": 112, "w": 60, "h": 18},
            }
        ]
    }

    apply_anchor_grounding_evaluation(response, payload)

    evaluation = response.regions[0].grounding_constraints["grounding_evaluation"]
    assert evaluation["contract_version"] == "anchor_grounding_evaluation_v1"
    assert evaluation["known_referenced_anchor_ids"] == ["ocr_anchor_1"]
    assert evaluation["anchor_frame_bbox"] == {"x": 150, "y": 112, "w": 60, "h": 18}
