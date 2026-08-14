from __future__ import annotations

import pytest

from app.operation.reading import build_read_region_batch_report, extract_ocr_text_lines


def _ocr(*texts: str) -> dict:
    return {"items": [{"text": text} for text in texts]}


def test_read_region_batch_merges_unique_lines() -> None:
    report = build_read_region_batch_report(
        target_container_id="seek:job_detail",
        target_bbox={"x": 10, "y": 20, "w": 300, "h": 500},
        max_captures=3,
        captures=[
            {"image_path": "a.png", "ocr_result": _ocr("Title", "React", "AI tools")},
            {"image_path": "b.png", "ocr_result": _ocr("React", "Client collaboration", "AI tools")},
        ],
    )

    assert report["contract_version"] == "read_region_batch_v1"
    assert report["status"] == "ok"
    assert report["unique_line_count"] == 4
    assert report["merged_text_lines"] == ["Title", "React", "AI tools", "Client collaboration"]
    assert report["captures"][1]["new_unique_line_count"] == 1


def test_read_region_batch_stops_after_no_new_content() -> None:
    report = build_read_region_batch_report(
        target_container_id="seek:job_detail",
        target_bbox={"x": 0, "y": 0, "width": 100, "height": 100},
        max_captures=5,
        stop_after_no_new_content=2,
        captures=[
            {"ocr_result": _ocr("A", "B")},
            {"ocr_result": _ocr("A", "B")},
            {"ocr_result": _ocr("A", "B")},
            {"ocr_result": _ocr("C")},
        ],
    )

    assert report["stop_reason"] == "no_new_content"
    assert report["completion_status"] == "incomplete"
    assert report["reached_bottom"] is False
    assert report["capture_count"] == 3
    assert report["merged_text_lines"] == ["A", "B"]


def test_read_region_batch_only_marks_complete_for_explicit_reached_bottom() -> None:
    report = build_read_region_batch_report(
        target_container_id="article:body",
        target_bbox={"x": 0, "y": 0, "width": 100, "height": 100},
        max_captures=5,
        captures=[
            {"ocr_result": _ocr("A", "B")},
            {
                "ocr_result": _ocr("C"),
                "reached_bottom": True,
                "scroll_effect_status": "boundary",
            },
            {"ocr_result": _ocr("must not be consumed")},
        ],
    )

    assert report["stop_reason"] == "reached_bottom"
    assert report["completion_status"] == "complete"
    assert report["reached_bottom"] is True
    assert report["capture_count"] == 2
    assert report["merged_text_lines"] == ["A", "B", "C"]


def test_read_region_batch_wrong_scope_blocks() -> None:
    report = build_read_region_batch_report(
        target_container_id="seek:job_detail",
        target_bbox={"x": 0, "y": 0, "w": 100, "h": 100},
        max_captures=5,
        wrong_scope_detected=True,
        captures=[{"ocr_result": _ocr("A")}],
    )

    assert report["status"] == "blocked_wrong_scope"
    assert report["stop_reason"] == "wrong_scope_detected"
    assert report["completion_status"] == "blocked"


def test_read_region_batch_max_captures_is_not_complete() -> None:
    report = build_read_region_batch_report(
        target_container_id="seek:job_detail",
        target_bbox={"x": 0, "y": 0, "w": 100, "h": 100},
        max_captures=2,
        captures=[
            {"ocr_result": _ocr("A")},
            {"ocr_result": _ocr("B")},
        ],
    )

    assert report["stop_reason"] == "max_captures"
    assert report["read_state"] == "max_captures"
    assert report["read_complete"] is False


@pytest.mark.parametrize(
    ("captures", "max_captures", "wrong_scope_detected", "expected_state", "expected_complete"),
    [
        ([{"ocr_result": _ocr("A")}], 2, False, "still_reading", False),
        ([{"ocr_result": _ocr("A"), "reached_bottom": True}], 2, False, "reached_bottom", True),
        (
            [{"ocr_result": _ocr("A")}, {"ocr_result": _ocr("A")}],
            3,
            False,
            "no_new_content",
            False,
        ),
        ([{"ocr_result": _ocr("A")}], 2, True, "wrong_surface", False),
        ([{"ocr_result": _ocr("A"), "blocked_surface_detected": True}], 2, False, "blocked_surface", False),
    ],
)
def test_read_region_batch_classifies_terminal_state(
    captures: list[dict],
    max_captures: int,
    wrong_scope_detected: bool,
    expected_state: str,
    expected_complete: bool,
) -> None:
    report = build_read_region_batch_report(
        target_container_id="seek:job_detail",
        target_bbox={"x": 0, "y": 0, "w": 100, "h": 100},
        max_captures=max_captures,
        stop_after_no_new_content=1,
        wrong_scope_detected=wrong_scope_detected,
        captures=captures,
    )

    assert report["read_state"] == expected_state
    assert report["read_complete"] is expected_complete


def test_extract_ocr_text_lines_accepts_texts_shape() -> None:
    assert extract_ocr_text_lines({"texts": [{"label": " One "}, "Two"]}) == ["One", "Two"]


def test_extract_ocr_text_lines_accepts_ocr_result_matches_shape() -> None:
    ocr_result = {
        "matches": [
            {"text": "Intermediate Software Engineer", "score": 0.98},
            {"text": "Vista Group", "score": 0.95},
        ]
    }

    assert extract_ocr_text_lines(ocr_result) == ["Intermediate Software Engineer", "Vista Group"]
