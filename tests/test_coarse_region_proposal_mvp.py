from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app.learn.experiments.coarse_region_proposal_mvp import build_coarse_region_proposals
from scripts.eval_hierarchical_region_partition_mvp2 import _build_coarse_prompt_payload, run_ab_case


def _item(item_id: str, x: int, y: int, w: int, h: int, source: str = "uia") -> dict:
    return {
        "item_id": item_id,
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "source": source,
    }


def test_notepad_blank_editor_is_recovered_as_remainder_region() -> None:
    items = [
        _item("menu-file", 8, 8, 45, 24),
        _item("menu-edit", 58, 8, 45, 24),
        _item("window-controls", 930, 0, 70, 32),
        _item("status", 820, 570, 180, 30),
    ]

    result = build_coarse_region_proposals(items, {"width": 1000, "height": 600})

    proposals = result["proposals"]
    editor_candidates = [
        proposal
        for proposal in proposals
        if "remainder_region" in proposal["generation_sources"]
        and proposal["bbox"]["w"] >= 960
        and proposal["bbox"]["h"] >= 450
    ]
    assert len(editor_candidates) == 1
    assert editor_candidates[0]["contained_element_ids"] == []
    assert result["diagnostics"]["proposal_count"] <= 10


def test_three_column_layout_produces_distinct_coarse_columns() -> None:
    items = []
    for index, y in enumerate(range(30, 570, 70)):
        items.append(_item(f"rail-{index}", 8, y, 38, 65))
        items.append(_item(f"list-{index}", 90, y, 220, 65))
    items.extend(
        [
            _item("chat-header", 360, 20, 500, 55),
            _item("message-one", 520, 180, 260, 55),
            _item("composer", 370, 530, 480, 50),
        ]
    )

    result = build_coarse_region_proposals(items, {"width": 900, "height": 600})

    level_one = [proposal for proposal in result["proposals"] if proposal["proposal_level"] == 1]
    narrow_left = [proposal for proposal in level_one if proposal["bbox"]["x"] <= 20 and proposal["bbox"]["w"] <= 90]
    middle = [proposal for proposal in level_one if 50 <= proposal["bbox"]["x"] <= 150 and 150 <= proposal["bbox"]["w"] <= 320]
    wide_right = [proposal for proposal in level_one if proposal["bbox"]["x"] >= 300 and proposal["bbox"]["w"] >= 450]
    assert narrow_left
    assert middle
    assert wide_right


def test_projection_finds_narrow_column_boundary_and_sparse_remainder() -> None:
    items = []
    for index, y in enumerate(range(100, 920, 80)):
        items.append(_item(f"rail-{index}", 8, y, 70, 73))
        items.append(_item(f"list-{index}", 78, y, 315, 73))
    items.extend(
        [
            _item("sparse-action-one", 516, 510, 113, 48),
            _item("sparse-action-two", 650, 510, 85, 73),
            _item("window-control", 897, 0, 48, 42),
        ]
    )

    result = build_coarse_region_proposals(items, {"width": 952, "height": 1029})

    level_one = [proposal for proposal in result["proposals"] if proposal["proposal_level"] == 1]
    assert any(65 <= proposal["bbox"]["w"] <= 90 for proposal in level_one)
    assert any(300 <= proposal["bbox"]["w"] <= 380 and proposal["bbox"]["x"] >= 60 for proposal in level_one)
    assert any(proposal["bbox"]["x"] >= 390 and proposal["bbox"]["w"] >= 490 for proposal in level_one)


def test_local_lower_columns_do_not_split_the_entire_page_vertically() -> None:
    items = [
        _item("top-wide", 0, 0, 1000, 80),
        _item("hero-wide", 80, 100, 840, 220),
    ]
    for row_y in (420, 620):
        for column, x in enumerate((80, 300, 520, 740)):
            items.append(_item(f"card-{row_y}-{column}", x, row_y, 180, 150))

    result = build_coarse_region_proposals(items, {"width": 1000, "height": 800})

    level_one = [proposal for proposal in result["proposals"] if proposal["proposal_level"] == 1]
    assert all(proposal["bbox"]["w"] == 1000 for proposal in level_one)
    assert result["diagnostics"]["major_partition_source"][0] == "y_whitespace_partition"


def test_proposals_are_anonymous_bounded_and_not_atomic_elements() -> None:
    items = [
        _item("nav-a", 20, 20, 40, 20),
        _item("nav-b", 80, 20, 40, 20),
        _item("content-a", 30, 130, 250, 80),
        _item("content-b", 320, 130, 250, 80),
        _item("content-c", 30, 250, 540, 100),
    ]

    result = build_coarse_region_proposals(items, {"width": 600, "height": 400})

    proposals = result["proposals"]
    assert 2 <= len([item for item in proposals if item["proposal_level"] == 1]) <= 8
    assert all(item["proposal_id"].startswith("P") for item in proposals)
    assert all(item["candidate_id"] == item["proposal_id"] for item in proposals)
    assert all(item["coordinate_space"] == "original_image" for item in proposals)
    assert all(item["bbox"]["x"] >= 0 and item["bbox"]["y"] >= 0 for item in proposals)
    assert all(item["bbox"]["x"] + item["bbox"]["w"] <= 600 for item in proposals)
    assert all(item["bbox"]["y"] + item["bbox"]["h"] <= 400 for item in proposals)
    assert all("label" not in item and "role" not in item for item in proposals)
    assert any(len(item["contained_element_ids"]) > 1 for item in proposals)
    assert len(proposals) < len(items) + 4


def test_proposal_evidence_exposes_generation_sources_and_density() -> None:
    items = [
        _item("left-1", 10, 20, 50, 30, "ocr"),
        _item("left-2", 10, 80, 50, 30, "uia"),
        _item("right-1", 260, 20, 120, 60, "parser"),
    ]

    result = build_coarse_region_proposals(items, {"width": 400, "height": 240})

    for proposal in result["proposals"]:
        assert proposal["generation_sources"]
        assert 0.0 <= proposal["area_ratio"] <= 1.0
        assert 0.0 <= proposal["evidence"]["separator_strength"] <= 1.0
        assert 0.0 <= proposal["evidence"]["whitespace_boundary_strength"] <= 1.0
        assert 0.0 <= proposal["evidence"]["element_density"] <= 1.0


def test_coarse_prompt_payload_excludes_element_ids_and_semantic_names() -> None:
    result = build_coarse_region_proposals(
        [_item("private-element", 10, 10, 100, 30), _item("other-element", 10, 120, 100, 30)],
        {"width": 300, "height": 200},
    )

    payload = _build_coarse_prompt_payload(result["proposals"], {"width": 300, "height": 200})
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["evidence_kind"] == "coarse_region_proposal"
    assert payload["candidate_count"] == len(result["proposals"])
    assert "private-element" not in encoded
    assert "contained_element_ids" not in encoded
    assert "sidebar" not in encoded


def test_ab_runner_calls_same_model_config_once_per_experiment_without_repair(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 180), "white").save(image_path)
    trial_path = tmp_path / "trial.json"
    trial_path.write_text(
        json.dumps(
            {
                "observe_bundle": {"image_path": str(image_path)},
                "screen_inventory": [
                    _item("left-a", 0, 0, 80, 80),
                    _item("left-b", 0, 90, 80, 80),
                    _item("right-a", 180, 0, 140, 80),
                    _item("right-b", 180, 90, 140, 80),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def model_caller(*, image_path: Path, prompt_text: str, max_tokens: int, temperature: float) -> str:
        calls.append(
            {
                "image_path": str(image_path),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "coarse": '"evidence_kind":"coarse_region_proposal"' in prompt_text,
            }
        )
        ids = ["P1", "P2"] if calls[-1]["coarse"] else ["C1", "C2"]
        return json.dumps(
            {
                "schema_version": "hierarchical_region_partition_mvp_v1",
                "page_type": "generic surface",
                "regions": [
                    {
                        "region_id": f"R{index}",
                        "level": 1,
                        "parent_id": "root",
                        "source_candidate_ids": [candidate_id],
                        "content_summary": "anonymous area",
                        "optional_role": "unknown",
                        "confidence": 0.8,
                        "children": [],
                    }
                    for index, candidate_id in enumerate(ids, start=1)
                ],
                "unassigned_candidate_ids": [],
                "candidate_gaps": [],
            }
        )

    report = run_ab_case(
        case={"case_id": "synthetic", "trial_result_path": str(trial_path)},
        out_dir=tmp_path / "out",
        model_caller=model_caller,
    )

    assert len(calls) == 2
    assert calls[0]["max_tokens"] == calls[1]["max_tokens"] == 3072
    assert calls[0]["temperature"] == calls[1]["temperature"] == 0.0
    assert calls[0]["coarse"] is False
    assert calls[1]["coarse"] is True
    assert report["model_call_count"] == 2
    assert report["repair_call_count"] == 0
    assert report["experiment_a"]["source_type"] == "actual_model_call"
    assert report["experiment_b"]["source_type"] == "actual_model_call"
    assert Path(report["experiment_a"]["raw_response_path"]).exists()
    assert Path(report["experiment_b"]["raw_response_path"]).exists()
