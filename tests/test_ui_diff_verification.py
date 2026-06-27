from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.execute.ui_diff_verification import build_ui_diff_verification


def test_ui_diff_detects_field_value_change_inside_target(tmp_path: Path) -> None:
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    Image.new("RGB", (240, 140), "white").save(before)
    image = Image.new("RGB", (240, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 180, 82), fill="white", outline="black")
    draw.text((52, 54), "Auckland", fill="black")
    image.save(after)

    result = build_ui_diff_verification(
        before,
        after,
        expected_change="field_value_changed",
        target_bbox={"x": 40, "y": 40, "w": 140, "h": 42},
    )

    assert result["contract_version"] == "ui_diff_verification_v1"
    assert result["verification_status"] == "pass"
    assert result["target_intersects_diff"] is True
    assert result["diff_bboxes"]


def test_ui_diff_fails_when_no_meaningful_change(tmp_path: Path) -> None:
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    Image.new("RGB", (160, 120), "white").save(before)
    Image.new("RGB", (160, 120), "white").save(after)

    result = build_ui_diff_verification(before, after, expected_change="step_changed")

    assert result["verification_status"] == "fail"
    assert result["failure_reason"] == "no_meaningful_visual_change"
