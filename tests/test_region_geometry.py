from __future__ import annotations

from modules.region.geometry import generate_zone_points, normalized_point


def test_generate_zone_points_returns_nine_candidates() -> None:
    zone = {"x": 10, "y": 20, "width": 100, "height": 80}
    points = generate_zone_points(zone)
    assert len(points) == 9
    assert points[4]["label"] == "center"


def test_generate_zone_points_prefers_cached_point_first() -> None:
    zone = {"x": 100, "y": 200, "width": 100, "height": 100}
    points = generate_zone_points(zone, preferred_norm_point={"nx": 0.5, "ny": 0.5})
    assert points[0] == {"x": 150, "y": 250, "label": "preferred_cached_point"}
    assert len({(point["x"], point["y"]) for point in points}) == len(points)


def test_normalized_point_rounds_to_four_decimals() -> None:
    zone = {"x": 50, "y": 100, "width": 120, "height": 80}
    point = {"x": 110, "y": 140}
    assert normalized_point(zone, point) == {"nx": 0.5, "ny": 0.5}
