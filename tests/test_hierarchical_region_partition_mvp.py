from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app.learn.experiments.hierarchical_region_partition import (
    RegionFrame,
    build_anonymous_candidates,
    compile_hierarchical_regions,
)
from scripts.eval_hierarchical_region_partition_mvp import PROMPT, _build_prompt_payload, run_case


def _items() -> list[dict]:
    return [
        {"item_id": "nav-1", "label": "Home", "role": "button", "bbox": {"x": 8, "y": 20, "w": 40, "h": 30}, "source": "uia"},
        {"item_id": "nav-2", "label": "Library", "role": "button", "bbox": {"x": 8, "y": 60, "w": 40, "h": 30}, "source": "ocr"},
        {"item_id": "card-1", "label": "First card", "role": "card", "bbox": {"x": 80, "y": 20, "w": 100, "h": 70}, "sources": ["vision", "ocr"]},
        {"item_id": "card-2", "label": "Second card", "role": "card", "bbox": {"x": 190, "y": 20, "w": 100, "h": 70}, "source": "vision"},
    ]


def test_build_anonymous_candidates_preserves_original_coordinates() -> None:
    candidates = build_anonymous_candidates(_items(), {"width": 320, "height": 180})

    assert [item["candidate_id"] for item in candidates] == ["C1", "C2", "C3", "C4"]
    assert candidates[0]["bbox"] == {"x": 8, "y": 20, "w": 40, "h": 30}
    assert candidates[0]["coordinate_space"] == "original_image"
    assert candidates[2]["source_types"] == ["ocr", "vision"]
    assert "label" not in candidates[0]


def test_anonymous_candidates_are_bounded_without_losing_screen_coverage() -> None:
    items = [
        {
            "item_id": f"item-{index}",
            "bbox": {"x": (index % 20) * 50, "y": (index // 20) * 50, "w": 20, "h": 20},
            "source": "ocr",
        }
        for index in range(200)
    ]

    candidates = build_anonymous_candidates(items, {"width": 1000, "height": 500})

    assert len(candidates) == 96
    occupied_bands = {int((item["bbox"]["y"] + item["bbox"]["h"] / 2) // 100) for item in candidates}
    assert occupied_bands == {0, 1, 2, 3, 4}


def test_model_prompt_candidate_table_stays_compact() -> None:
    candidates = build_anonymous_candidates(
        [
            {
                "item_id": f"item-{index}",
                "bbox": {"x": (index % 12) * 80, "y": (index // 12) * 50, "w": 40, "h": 30},
                "source": "vision",
            }
            for index in range(96)
        ],
        {"width": 1000, "height": 500},
    )

    payload = _build_prompt_payload(candidates, {"width": 1000, "height": 500})
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    assert payload["candidate_columns"] == ["id", "x", "y", "w", "h", "edges", "count", "sources"]
    assert payload["candidate_count"] == 96
    assert len(encoded) < 12000
    assert "candidate IDs only" not in PROMPT
    assert "Never synthesize" in PROMPT


def test_compile_builds_two_level_regions_and_frame_crops(tmp_path: Path) -> None:
    candidates = build_anonymous_candidates(_items(), {"width": 320, "height": 180})
    payload = {
        "schema_version": "hierarchical_region_partition_mvp_v1",
        "page_type": "media collection",
        "regions": [
            {
                "region_id": "R1",
                "level": 1,
                "parent_id": "root",
                "source_candidate_ids": ["C1", "C2"],
                "content_summary": "compact navigation",
                "optional_role": "navigation",
                "confidence": 0.9,
                "children": [],
            },
            {
                "region_id": "R2",
                "level": 1,
                "parent_id": "root",
                "source_candidate_ids": ["C3", "C4"],
                "content_summary": "content cards",
                "optional_role": "content",
                "confidence": 0.86,
                "children": ["R2.1"],
            },
            {
                "region_id": "R2.1",
                "level": 2,
                "parent_id": "R2",
                "source_candidate_ids": ["C3"],
                "content_summary": "first card",
                "optional_role": "media",
                "confidence": 0.81,
                "children": [],
            },
        ],
        "unassigned_candidate_ids": [],
        "candidate_gaps": [],
    }

    compiled = compile_hierarchical_regions(payload, candidates, {"width": 320, "height": 180})
    assert compiled["validator"]["valid"] is True
    assert compiled["regions_by_id"]["R2"]["bbox"] == {"x": 80, "y": 20, "w": 210, "h": 70}

    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 180), "white").save(image_path)
    frame = RegionFrame(image_path=image_path, compiled=compiled)
    assert [item["region_id"] for item in frame.get_region_children("R2")] == ["R2.1"]
    crop_path = frame.crop_region("R2.1", tmp_path / "crops")
    assert Image.open(crop_path).size == (100, 70)


def test_compile_rejects_missing_candidate_and_disconnected_union() -> None:
    candidates = [
        {"candidate_id": "C1", "bbox": {"x": 0, "y": 0, "w": 20, "h": 20}, "coordinate_space": "original_image"},
        {"candidate_id": "C2", "bbox": {"x": 280, "y": 140, "w": 20, "h": 20}, "coordinate_space": "original_image"},
    ]
    payload = {
        "schema_version": "hierarchical_region_partition_mvp_v1",
        "regions": [
            {
                "region_id": "R1",
                "level": 1,
                "parent_id": "root",
                "source_candidate_ids": ["C1", "C2", "C404"],
                "content_summary": "invalid union",
                "optional_role": "unknown",
                "confidence": 0.4,
                "children": [],
            }
        ],
        "unassigned_candidate_ids": [],
        "candidate_gaps": [],
    }

    compiled = compile_hierarchical_regions(payload, candidates, {"width": 320, "height": 180})
    reasons = {item["reason"] for item in compiled["validator"]["failures"]}
    assert "invalid_candidate_reference" in reasons
    assert "disconnected_candidate_union" in reasons
    assert compiled["validator"]["valid"] is False


def test_compile_rejects_child_outside_parent_and_severe_sibling_overlap() -> None:
    candidates = [
        {"candidate_id": "C1", "bbox": {"x": 0, "y": 0, "w": 100, "h": 100}, "coordinate_space": "original_image"},
        {"candidate_id": "C2", "bbox": {"x": 20, "y": 20, "w": 100, "h": 100}, "coordinate_space": "original_image"},
        {"candidate_id": "C3", "bbox": {"x": 150, "y": 0, "w": 40, "h": 40}, "coordinate_space": "original_image"},
    ]
    payload = {
        "schema_version": "hierarchical_region_partition_mvp_v1",
        "regions": [
            {"region_id": "R1", "level": 1, "parent_id": "root", "source_candidate_ids": ["C1"], "content_summary": "one", "optional_role": "content", "confidence": 0.8, "children": ["R1.1"]},
            {"region_id": "R2", "level": 1, "parent_id": "root", "source_candidate_ids": ["C2"], "content_summary": "two", "optional_role": "content", "confidence": 0.8, "children": []},
            {"region_id": "R1.1", "level": 2, "parent_id": "R1", "source_candidate_ids": ["C3"], "content_summary": "outside", "optional_role": "unknown", "confidence": 0.5, "children": []},
        ],
        "unassigned_candidate_ids": [],
        "candidate_gaps": [],
    }

    compiled = compile_hierarchical_regions(payload, candidates, {"width": 320, "height": 180})
    reasons = {item["reason"] for item in compiled["validator"]["failures"]}
    assert "child_outside_parent" in reasons
    assert "severe_sibling_overlap" in reasons


def test_offline_case_writes_review_artifacts(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 180), "white").save(image_path)
    trial_path = tmp_path / "trial.json"
    trial_path.write_text(
        json.dumps(
            {
                "observe_bundle": {"image_path": str(image_path)},
                "screen_inventory": [
                    {"item_id": "left", "bbox": {"x": 0, "y": 0, "w": 80, "h": 180}, "source": "uia"},
                    {"item_id": "main", "bbox": {"x": 80, "y": 0, "w": 240, "h": 180}, "source": "vision"},
                ],
                "two_stage_understanding": {
                    "stage1_structure": {
                        "structure_regions": [
                            {"region_id": "old_left", "bbox": {"x": 0, "y": 0, "w": 20, "h": 180}}
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    model_payload = {
        "schema_version": "hierarchical_region_partition_mvp_v1",
        "page_type": "two column test",
        "regions": [
            {
                "region_id": "R1",
                "level": 1,
                "parent_id": "root",
                "source_candidate_ids": ["C1"],
                "content_summary": "left controls",
                "optional_role": "navigation",
                "confidence": 0.9,
                "children": [],
            },
            {
                "region_id": "R2",
                "level": 1,
                "parent_id": "root",
                "source_candidate_ids": ["C2"],
                "content_summary": "main content",
                "optional_role": "content",
                "confidence": 0.9,
                "children": [],
            },
        ],
        "unassigned_candidate_ids": [],
        "candidate_gaps": [],
    }

    report = run_case(
        case={"case_id": "synthetic", "trial_result_path": str(trial_path)},
        out_dir=tmp_path / "out",
        recorded_model_payload=model_payload,
    )

    assert report["validator"]["valid"] is True
    assert report["metrics"]["crop_success_rate"] == 1.0
    assert Path(report["candidate_overlay_path"]).exists()
    assert Path(report["old_v1_overlay_path"]).exists()
    assert Path(report["region_overlay_path"]).exists()
    assert len(report["crop_paths"]) == 2
    assert report["old_v1_summary"]["region_count"] == 1
    assert Path(report["comparison_report_path"]).exists()
