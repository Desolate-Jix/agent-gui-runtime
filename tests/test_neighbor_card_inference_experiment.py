from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.run_neighbor_card_inference_experiment import (
    run_neighbor_card_inference_experiment,
)


def test_experiment_reports_fixture_recall_delta_without_execution_authority(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    image = Image.new("RGB", (800, 500), (210, 214, 218))
    draw = ImageDraw.Draw(image)
    for y in (60, 250):
        for x in (40, 210, 380, 550):
            draw.rectangle(
                (x, y, x + 150, y + 160),
                fill=(252, 252, 252),
                outline=(180, 184, 188),
                width=2,
            )
    image.save(source)

    replay_report = tmp_path / "replay.json"
    replay_report.write_text(
        json.dumps(
            {
                "fusion": {
                    "fused_review_boxes": [
                        {
                            "box_type": "subregion_group",
                            "number": f"card_{index}",
                            "role": "tile_card_parent",
                            "label": f"Card {index}",
                            "bbox": {"x": x + 20, "y": 175, "w": 110, "h": 30},
                            "render_in_main_overlay": True,
                        }
                        for index, x in enumerate((210, 380), start=1)
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contract_version": "learn_neighbor_card_inference_experiment_manifest_v1",
                "cases": [
                    {
                        "case_id": "aligned_cards",
                        "source_image_path": str(source),
                        "source_image_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "replay_report_path": str(replay_report),
                        "expected_card_bboxes": [
                            {"x": x, "y": 60, "w": 150, "h": 160}
                            for x in (40, 210, 380, 550)
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_neighbor_card_inference_experiment(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["contract_version"] == "learn_neighbor_card_inference_experiment_report_v1"
    case = report["cases"][0]
    assert case["structural_card_recall_before"]["passed"] == 2
    assert case["structural_card_recall_before"]["attempted"] == 4
    assert case["structural_card_recall_after"]["passed"] == 4
    assert case["structural_card_recall_after"]["attempted"] == 4
    assert case["neighbor_proposal_precision"]["passed"] == 2
    assert case["neighbor_proposal_precision"]["attempted"] == 2
    assert case["recall_rate_delta"] == 0.5
    assert Path(case["overlay_path"]).exists()
    assert report["interpretation"].startswith("single-fixture offline comparison")
    assert report["safety"]["live_clicks"] == 0
    assert report["safety"]["artifact_is_authorization"] is False


def test_experiment_marks_checksum_mismatch_invalid(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (120, 120), "white").save(source)
    replay_report = tmp_path / "replay.json"
    replay_report.write_text('{"fusion":{"fused_review_boxes":[]}}', encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contract_version": "learn_neighbor_card_inference_experiment_manifest_v1",
                "cases": [
                    {
                        "case_id": "stale",
                        "source_image_path": str(source),
                        "source_image_sha256": "wrong",
                        "replay_report_path": str(replay_report),
                        "expected_card_bboxes": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_neighbor_card_inference_experiment(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["case_count"] == 0
    assert report["invalid_case_count"] == 1
    assert report["invalid_cases"][0]["failure_category"] == "stale_fixture"
