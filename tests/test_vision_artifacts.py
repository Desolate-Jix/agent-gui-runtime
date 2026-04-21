from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app.vision.artifacts import save_region_artifacts
from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion


def _region(region_id: str, x1: int, y1: int, x2: int, y2: int) -> VisionRegion:
    bbox = BBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1)
    return VisionRegion(
        region_id=region_id,
        label=region_id,
        role="button",
        bbox=bbox,
        diagonal=Diagonal(x1=x1, y1=y1, x2=x2, y2=y2),
        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.1, nx2=0.2, ny2=0.2),
        description="demo region",
        ocr_text="Demo",
        text_lines=["Demo"],
        possible_destinations=["demo_page"],
        confidence=0.9,
        layout_key="layout",
        content_key="content",
        match_key=f"{region_id}:match",
    )


def test_save_region_artifacts_writes_annotated_image_crops_and_manifest(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (200, 120), color=(240, 240, 240)).save(image_path)

    output_root = tmp_path / "vision-regions"
    monkeypatch.setattr("app.vision.artifacts.ARTIFACTS_DIR", output_root)

    response = VisionAnalyzeResponse(
        provider="demo",
        screen_summary="demo",
        state_guess="home",
        image_size=ImageSize(width=200, height=120),
        regions=[_region("region_a", 10, 10, 70, 40), _region("region_b", 80, 50, 150, 100)],
    )

    artifacts = save_region_artifacts(image_path, response)

    assert Path(artifacts["bundle_dir"]).exists()
    assert Path(artifacts["annotated_image_path"]).exists()
    assert Path(artifacts["manifest_path"]).exists()
    assert artifacts["region_count"] == 2
    assert len(artifacts["regions"]) == 2
    for item in artifacts["regions"]:
        assert Path(item["crop_path"]).exists()
        assert Path(item["annotated_crop_path"]).exists()

    manifest = json.loads(Path(artifacts["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["region_count"] == 2
    assert manifest["regions"][0]["region_id"] == "region_a"
