from __future__ import annotations


def test_quality_filter_removes_only_sub_ten_pixel_candidates() -> None:
    from app.learn.recognition.omniparser_quality import filter_omniparser_candidates

    items = [
        {"type": "icon", "content": "tiny", "bbox": [0.0, 0.0, 0.009, 0.5], "interactivity": True, "source": "yolo"},
        {"type": "icon", "content": "boundary", "bbox": [0.0, 0.0, 0.01, 0.5], "interactivity": True, "source": "yolo"},
        {"type": "text", "content": "readable", "bbox": [0.1, 0.1, 0.4, 0.2], "interactivity": False, "source": "ocr"},
    ]

    filtered, summary = filter_omniparser_candidates(
        items,
        image_size={"width": 1000, "height": 800},
    )

    assert [item["content"] for item in filtered] == ["boundary", "readable"]
    assert summary == {
        "input_count": 3,
        "output_count": 2,
        "removed_tiny_count": 1,
        "removed_duplicate_count": 0,
        "minimum_capture_side_px": 10,
        "removed_candidates": [
            {
                "input_index": 0,
                "candidate_fingerprint": summary["removed_candidates"][0]["candidate_fingerprint"],
                "reason": "below_minimum_capture_side",
            }
        ],
    }


def test_quality_filter_dedupes_only_equivalent_high_overlap_candidates() -> None:
    from app.learn.recognition.omniparser_quality import filter_omniparser_candidates

    duplicate_a = {"type": "icon", "content": " Quick Apply ", "bbox": [0.1, 0.2, 0.5, 0.4], "interactivity": True, "source": "yolo"}
    duplicate_b = {"type": "icon", "content": "quick apply", "bbox": [0.101, 0.2, 0.501, 0.4], "interactivity": True, "source": "yolo"}
    different_text = {"type": "icon", "content": "Cancel", "bbox": [0.1, 0.2, 0.5, 0.4], "interactivity": True, "source": "yolo"}
    different_role = {"type": "text", "content": "Quick Apply", "bbox": [0.1, 0.2, 0.5, 0.4], "interactivity": True, "source": "yolo"}

    forward, forward_summary = filter_omniparser_candidates(
        [duplicate_a, duplicate_b, different_text, different_role],
        image_size={"width": 1000, "height": 800},
    )
    reverse, reverse_summary = filter_omniparser_candidates(
        [different_role, different_text, duplicate_b, duplicate_a],
        image_size={"width": 1000, "height": 800},
    )

    assert len(forward) == len(reverse) == 3
    assert forward_summary["removed_duplicate_count"] == 1
    assert reverse_summary["removed_duplicate_count"] == 1
    forward_winner = next(item for item in forward if item["content"].strip().casefold() == "quick apply" and item["type"] == "icon")
    reverse_winner = next(item for item in reverse if item["content"].strip().casefold() == "quick apply" and item["type"] == "icon")
    assert forward_winner == reverse_winner


def test_quality_filter_rejects_malformed_geometry_instead_of_hiding_it() -> None:
    import pytest

    from app.learn.recognition.omniparser_quality import filter_omniparser_candidates

    with pytest.raises(ValueError, match="omniparser_candidate_invalid"):
        filter_omniparser_candidates(
            [{"type": "icon", "content": "bad", "bbox": [0.5, 0.2, 0.1, 0.4]}],
            image_size={"width": 1000, "height": 800},
        )
