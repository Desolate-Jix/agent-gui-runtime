from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.vision.grid_overlay import create_grid_overlay_image


def test_create_grid_overlay_image_preserves_size_and_writes_file(tmp_path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "overlay.png"
    Image.new("RGB", (320, 180), color=(255, 255, 255)).save(source)

    result = create_grid_overlay_image(source, output, spacing=100)

    assert output.exists()
    assert result["width"] == 320
    assert result["height"] == 180
    assert result["spacing"] == 100
    assert result["minor_spacing"] == 25
    with Image.open(output) as image:
        assert image.size == (320, 180)
