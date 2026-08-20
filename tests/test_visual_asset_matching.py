from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.operation.visual_asset_matching import match_visual_asset


def _draw_button(path: Path, *, button_xy: tuple[int, int], label: str = "Quick apply") -> dict[str, int]:
    image = Image.new("RGB", (500, 260), "white")
    draw = ImageDraw.Draw(image)
    x, y = button_xy
    bbox = {"x": x, "y": y, "w": 144, "h": 44}
    draw.rounded_rectangle((x, y, x + bbox["w"], y + bbox["h"]), radius=8, fill=(229, 0, 125))
    draw.text((x + 28, y + 13), label, fill="white")
    image.save(path)
    return bbox


def test_visual_asset_match_recalls_button_candidate_inside_scope(tmp_path: Path) -> None:
    learned_path = tmp_path / "learned.png"
    target_path = tmp_path / "target.png"
    learned_bbox = _draw_button(learned_path, button_xy=(220, 120))
    target_bbox = _draw_button(target_path, button_xy=(260, 140))
    template_path = tmp_path / "template.png"
    with Image.open(learned_path) as image:
        image.crop(
            (
                learned_bbox["x"],
                learned_bbox["y"],
                learned_bbox["x"] + learned_bbox["w"],
                learned_bbox["y"] + learned_bbox["h"],
            )
        ).save(template_path)

    result = match_visual_asset(
        asset_id="seek.quick_apply.button.primary",
        template_path=template_path,
        target_image_path=target_path,
        label="Quick apply",
        semantic_action="open_apply_flow",
        allowed_region={"x": 200, "y": 100, "w": 260, "h": 130, "container_id": "seek:job_detail"},
        scales=(1.0,),
        min_score=0.9,
        artifact_dir=tmp_path / "match-artifacts",
        capture_id="capture-1",
    )

    assert result["contract_version"] == "visual_asset_match_v1"
    assert result["matched"] is True
    assert result["scope_ok"] is True
    assert result["match_score"] >= 0.99
    assert result["bbox"] == target_bbox
    assert result["click_point"] == {"x": 332, "y": 162}
    assert result["elapsed_ms"] < 1000
    assert result["match_method"] in {"gray_template", "edge_template"}
    assert result["ambiguous"] is False
    assert Path(result["current_roi_ref"]).exists()
    assert Path(result["current_match_ref"]).exists()
    assert result["top_candidates"]
    assert result["can_authorize_click"] is False
    assert result["candidate"]["risk_class"] == "safe_open_apply_flow"
    assert result["candidate"]["container_id"] == "seek:job_detail"
    assert result["candidate"]["candidate_freshness"]["capture_id"] == "capture-1"


def test_visual_asset_match_respects_container_scope(tmp_path: Path) -> None:
    learned_path = tmp_path / "learned.png"
    target_path = tmp_path / "target.png"
    learned_bbox = _draw_button(learned_path, button_xy=(40, 40))
    _draw_button(target_path, button_xy=(40, 40))
    template_path = tmp_path / "template.png"
    with Image.open(learned_path) as image:
        image.crop(
            (
                learned_bbox["x"],
                learned_bbox["y"],
                learned_bbox["x"] + learned_bbox["w"],
                learned_bbox["y"] + learned_bbox["h"],
            )
        ).save(template_path)

    result = match_visual_asset(
        asset_id="seek.quick_apply.button.primary",
        template_path=template_path,
        target_image_path=target_path,
        label="Quick apply",
        semantic_action="open_apply_flow",
        allowed_region={"x": 250, "y": 100, "w": 220, "h": 120, "container_id": "seek:job_detail"},
        scales=(1.0,),
        min_score=0.9,
    )

    assert result["matched"] is False
    assert result["threshold_ok"] is False
    assert result["can_authorize_click"] is False


def test_visual_asset_match_handles_scaled_button_without_old_coordinates(tmp_path: Path) -> None:
    learned_path = tmp_path / "learned.png"
    target_path = tmp_path / "target.png"
    learned_bbox = _draw_button(learned_path, button_xy=(40, 40))
    template_path = tmp_path / "template.png"
    with Image.open(learned_path) as image:
        template = image.crop(
            (
                learned_bbox["x"],
                learned_bbox["y"],
                learned_bbox["x"] + learned_bbox["w"],
                learned_bbox["y"] + learned_bbox["h"],
            )
        )
        template.save(template_path)
        scaled = template.resize((180, 55))
    target = Image.new("RGB", (520, 300), "white")
    target.paste(scaled, (260, 150))
    target.save(target_path)

    result = match_visual_asset(
        asset_id="seek.quick_apply.button.primary",
        template_path=template_path,
        target_image_path=target_path,
        label="Quick apply",
        semantic_action="open_apply_flow",
        allowed_region={"x": 220, "y": 110, "w": 260, "h": 150, "container_id": "seek:job_detail"},
        scales=(1.0, 1.25),
        min_score=0.9,
        capture_id="capture-scaled",
    )

    assert result["matched"] is True
    assert result["scale"] == 1.25
    assert result["bbox"] == {"x": 260, "y": 150, "w": 180, "h": 55}
    assert result["click_point"] == {"x": 350, "y": 177}
    assert result["candidate"]["candidate_freshness"]["capture_id"] == "capture-scaled"
