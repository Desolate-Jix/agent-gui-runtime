from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.run_layout_regularization_experiment import run_layout_regularization_experiment


def test_experiment_writes_comparison_and_read_only_report(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = Image.new("RGB", (800, 500), (210, 214, 218))
    draw = ImageDraw.Draw(image)
    for x in (50, 275, 500):
        draw.rectangle((x, 100, x + 200, 320), fill=(252, 252, 252), outline=(180, 184, 188), width=2)
    image.save(source)

    current_overlay = tmp_path / "current.png"
    image.save(current_overlay)
    report = tmp_path / "replay.json"
    report.write_text(
        json.dumps(
            {
                "source_image_path": str(source),
                "overlay_status": {"path": str(current_overlay), "status": "generated"},
                "fusion": {
                    "fused_review_boxes": [
                        {
                            "box_type": "subregion_group",
                            "number": f"card_{index}",
                            "role": "tile_card_parent",
                            "label": f"Card {index}",
                            "bbox": {"x": x + 15, "y": 250, "w": 150, "h": 32},
                            "render_in_main_overlay": True,
                        }
                        for index, x in enumerate((50, 275, 500), start=1)
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contract_version": "learn_layout_regularization_experiment_manifest_v1",
                "cases": [
                    {
                        "case_id": "three_cards",
                        "replay_report_path": str(report),
                        "source_image_path": str(source),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_layout_regularization_experiment(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert result["contract_version"] == "learn_layout_regularization_experiment_report_v1"
    assert result["case_count"] == 1
    assert result["cases"][0]["alignment_group_count"] == 1
    assert Path(result["cases"][0]["regularized_overlay_path"]).exists()
    assert Path(result["cases"][0]["comparison_path"]).exists()
    assert Path(result["report_path"]).exists()
    assert Path(result["demo_index_path"]).exists()
    assert result["safety"]["live_clicks"] == 0
    assert result["safety"]["artifact_is_authorization"] is False
