from __future__ import annotations

from scripts.benchmark_vista_scaling import evaluate_point


def test_evaluate_point_passes_inside_bbox_near_expected_click() -> None:
    result = evaluate_point(
        point={"x": 110, "y": 120},
        expected_bbox={"x": 90, "y": 100, "w": 80, "h": 50},
        expected_click_point={"x": 120, "y": 125},
        allowed_distance_px=24,
        neighbor_bboxes=[],
    )

    assert result["status"] == "pass"
    assert result["inside_expected_bbox"] is True
    assert result["nearest_neighbor_mistake"] is False


def test_evaluate_point_marks_edge_hit_as_risky() -> None:
    result = evaluate_point(
        point={"x": 92, "y": 120},
        expected_bbox={"x": 90, "y": 100, "w": 80, "h": 50},
        expected_click_point={"x": 120, "y": 125},
        allowed_distance_px=40,
        neighbor_bboxes=[],
    )

    assert result["status"] == "risky"
    assert "edge_margin_below_6px" in result["reasons"]


def test_evaluate_point_fails_neighbor_bbox_hit() -> None:
    result = evaluate_point(
        point={"x": 181, "y": 120},
        expected_bbox={"x": 90, "y": 100, "w": 80, "h": 50},
        expected_click_point={"x": 120, "y": 125},
        allowed_distance_px=40,
        neighbor_bboxes=[{"x": 175, "y": 100, "w": 80, "h": 50}],
    )

    assert result["status"] == "fail"
    assert result["nearest_neighbor_mistake"] is True
    assert "nearest_neighbor_mistake" in result["reasons"]
