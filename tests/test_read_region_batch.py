from __future__ import annotations

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
    assert report["capture_count"] == 3
    assert report["merged_text_lines"] == ["A", "B"]


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
