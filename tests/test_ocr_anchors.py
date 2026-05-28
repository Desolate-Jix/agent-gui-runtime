from __future__ import annotations

from app.vision.ocr_anchors import build_ocr_anchor_payload, build_prompt_anchor_projection
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


def test_prompt_anchor_projection_encodes_selected_text_and_geometry_as_relation_matrix() -> None:
    anchors = [
        {
            "anchor_id": "ocr_anchor_1",
            "text": "停止加速",
            "bbox": {"x": 190, "y": 505, "w": 62, "h": 18},
            "confidence": 0.99,
            "goal_similarity": 0.9,
        },
        {
            "anchor_id": "ocr_anchor_2",
            "text": "maximize",
            "bbox": {"x": 750, "y": 12, "w": 17, "h": 18},
            "confidence": 0.98,
            "goal_similarity": 0.4,
        },
    ]
    anchors.extend(
        {
            "anchor_id": f"ocr_anchor_{index}",
            "text": f"chat text {index}",
            "bbox": {"x": (index * 31) % 780, "y": 100 + (index * 33) % 1100, "w": 42, "h": 18},
            "confidence": 0.8,
            "goal_similarity": 0.0,
        }
        for index in range(3, 50)
    )

    projection = build_prompt_anchor_projection(
        {
            "coordinate_space": "inference_image",
            "image_size": {"width": 820, "height": 1303},
            "anchors": anchors,
        },
        max_anchors=12,
    )

    assert projection is not None
    assert projection["contract_version"] == "ocr_prompt_matrix_v1"
    assert projection["profile"] == "relation_matrix_compact"
    assert projection["source_anchor_count"] == 49
    assert projection["anchor_count"] <= 12
    assert projection["text_anchor_count"] == projection["anchor_count"]
    assert projection["goal_match_count"] == 1
    assert projection["columns"] == ["i", "t", "x", "y", "w", "h", "m"]
    assert [1, "停止加速", 190, 505, 62, 18, 1] in projection["rows"]
    assert [2, "maximize", 750, 12, 17, 18, 0] in projection["rows"]
    assert ["visual_icon", "exclude_text", "boundary|alignment|exclusion"] in projection["relation_policy_rows"]


def test_single_character_titlebar_symbol_is_not_a_text_match_for_close_window_goal() -> None:
    ocr = OCRResult(
        image_path="qq.png",
        metadata={"engine": "test_ocr"},
        matches=[
            OCRTextMatch(text="口", score=0.99, bbox=OCRBoundingBox(x=750, y=12, width=17, height=18)),
        ],
    )

    payload = build_ocr_anchor_payload(ocr, image_size=ImageSize(width=820, height=1303), goal="关闭窗口")
    projection = build_prompt_anchor_projection(payload)

    assert payload["anchors"][0]["goal_similarity"] < 0.55
    assert projection is not None
    assert projection["text_anchor_count"] == 1
    assert projection["goal_match_count"] == 0
    assert projection["rows"] == [[1, "口", 750, 12, 17, 18, 0]]


def test_prompt_anchor_projection_prioritizes_layout_around_goal_matched_text() -> None:
    anchors = [
        {
            "anchor_id": "ocr_anchor_1",
            "text": "搜索游戏",
            "bbox": {"x": 200, "y": 100, "w": 60, "h": 20},
            "confidence": 0.99,
            "goal_similarity": 1.0,
        },
        {
            "anchor_id": "ocr_anchor_2",
            "text": "筛选",
            "bbox": {"x": 205, "y": 135, "w": 45, "h": 16},
            "confidence": 0.98,
            "goal_similarity": 0.0,
        },
        {
            "anchor_id": "ocr_anchor_3",
            "text": "附近入口",
            "bbox": {"x": 270, "y": 102, "w": 55, "h": 18},
            "confidence": 0.97,
            "goal_similarity": 0.0,
        },
        {
            "anchor_id": "ocr_anchor_4",
            "text": "Title",
            "bbox": {"x": 10, "y": 8, "w": 40, "h": 18},
            "confidence": 0.96,
            "goal_similarity": 0.0,
        },
        {
            "anchor_id": "ocr_anchor_5",
            "text": "远处同排文字",
            "bbox": {"x": 500, "y": 102, "w": 80, "h": 18},
            "confidence": 0.95,
            "goal_similarity": 0.0,
        },
    ]

    projection = build_prompt_anchor_projection(
        {"coordinate_space": "inference_image", "image_size": {"width": 600, "height": 400}, "anchors": anchors},
        max_anchors=4,
        focus_neighbor_limit=3,
    )

    assert projection is not None
    assert projection["rows"] == [
        [1, "搜索游戏", 200, 100, 60, 20, 1],
        [3, "附近入口", 270, 102, 55, 18, 0],
        [2, "筛选", 205, 135, 45, 16, 0],
        [4, "Title", 10, 8, 40, 18, 0],
    ]
    assert projection["focus_relation_columns"] == ["f", "n", "r", "g"]
    assert projection["focus_relation_rows"] == [[1, 3, "R", 10], [1, 2, "B", 15]]
    assert projection["focus_relation_count"] == 2


def test_prompt_anchor_projection_can_disable_focus_neighbor_expansion() -> None:
    anchors = [
        {
            "anchor_id": "ocr_anchor_1",
            "text": "搜索游戏",
            "bbox": {"x": 200, "y": 100, "w": 60, "h": 20},
            "confidence": 0.99,
            "goal_similarity": 1.0,
        },
        {
            "anchor_id": "ocr_anchor_2",
            "text": "附近入口",
            "bbox": {"x": 270, "y": 102, "w": 55, "h": 18},
            "confidence": 0.97,
            "goal_similarity": 0.0,
        },
        {
            "anchor_id": "ocr_anchor_3",
            "text": "Title",
            "bbox": {"x": 10, "y": 8, "w": 40, "h": 18},
            "confidence": 0.96,
            "goal_similarity": 0.0,
        },
    ]

    projection = build_prompt_anchor_projection(
        {"coordinate_space": "inference_image", "image_size": {"width": 600, "height": 400}, "anchors": anchors},
        max_anchors=2,
        focus_neighbor_limit=0,
    )

    assert projection is not None
    assert projection["rows"] == [
        [1, "搜索游戏", 200, 100, 60, 20, 1],
        [3, "Title", 10, 8, 40, 18, 0],
    ]
    assert projection["focus_relation_count"] == 0
    assert "focus_relation_rows" not in projection


def test_prompt_anchor_projection_defaults_to_48_selected_rows() -> None:
    anchors = [
        {
            "anchor_id": f"ocr_anchor_{index}",
            "text": f"row {index}",
            "bbox": {"x": index * 4, "y": 100 + index * 3, "w": 30, "h": 12},
            "confidence": 0.9,
            "goal_similarity": 0.0,
        }
        for index in range(1, 61)
    ]

    projection = build_prompt_anchor_projection(
        {"coordinate_space": "inference_image", "image_size": {"width": 800, "height": 600}, "anchors": anchors}
    )

    assert projection is not None
    assert projection["source_anchor_count"] == 60
    assert projection["anchor_count"] == 48
    assert projection["text_anchor_count"] == 48
