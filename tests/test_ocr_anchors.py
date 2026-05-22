from __future__ import annotations

from app.vision.ocr_anchors import build_ocr_anchor_payload
from app.vision.schemas import ImageSize
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def test_ocr_anchor_payload_keeps_all_matches_by_default() -> None:
    ocr = OCRResult(
        image_path="demo.png",
        metadata={"engine": "test_ocr"},
        matches=[
            OCRTextMatch(
                text=f"Text {index}",
                score=0.1 + (index * 0.01),
                bbox=OCRBoundingBox(x=index, y=index + 1, width=10, height=6),
            )
            for index in range(30)
        ],
    )

    payload = build_ocr_anchor_payload(ocr, image_size=ImageSize(width=300, height=200), goal="Text")

    assert payload["total_detected_count"] == 30
    assert payload["anchor_count"] == 30
    assert len(payload["anchors"]) == 30


def test_ocr_anchor_payload_still_allows_explicit_limit() -> None:
    ocr = OCRResult(
        image_path="demo.png",
        metadata={"engine": "test_ocr"},
        matches=[
            OCRTextMatch(
                text=f"Text {index}",
                score=0.9,
                bbox=OCRBoundingBox(x=index, y=index, width=10, height=6),
            )
            for index in range(10)
        ],
    )

    payload = build_ocr_anchor_payload(
        ocr,
        image_size=ImageSize(width=300, height=200),
        goal="Text",
        max_anchors=3,
    )

    assert payload["total_detected_count"] == 10
    assert payload["anchor_count"] == 3
    assert len(payload["anchors"]) == 3
