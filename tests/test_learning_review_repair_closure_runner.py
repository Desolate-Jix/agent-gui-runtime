from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app.learn.recognition.model_review import validate_review_patch
from scripts.run_learning_review_repair_closure import _configure_stdout_utf8, run_closure


class _Utf8Probe:
    def __init__(self) -> None:
        self.encoding = "gbk"
        self.requested_encoding = ""

    def reconfigure(self, *, encoding: str) -> None:
        self.requested_encoding = encoding


def test_closure_runner_configures_windows_stdout_as_utf8() -> None:
    stream = _Utf8Probe()

    _configure_stdout_utf8(stream)

    assert stream.requested_encoding == "utf-8"


def test_closure_runner_replays_generic_deterministic_repair(tmp_path: Path) -> None:
    stage2 = {
        "regions": [
            {
                "region_id": "primary",
                "bbox": {"x": 0, "y": 0, "w": 400, "h": 300},
                "numbered_items": [
                    {"item_id": "item", "bbox": {"x": 20, "y": 20, "w": 80, "h": 30}}
                ],
                "subregion_groups": [
                    {
                        "group_id": "wrong_wrapper",
                        "role": "tile_card_parent",
                        "bbox": {"x": 10, "y": 10, "w": 100, "h": 50},
                        "member_item_ids": ["item"],
                    }
                ],
            }
        ]
    }
    patch = validate_review_patch(
        stage2,
        {
            "keep": [],
            "remove": [{"region_id": "wrong_wrapper", "reason": "false parent"}],
            "relabel": [],
            "missing": [
                {
                    "description": "recover list",
                    "parent_region_id": "primary",
                    "expected_role": "list_container",
                    "rough_roi": {"x": 10, "y": 10, "w": 100, "h": 50},
                    "repair_route": "stage1_repartition",
                    "reason": "false parent removed",
                }
            ],
            "needs_human_review": [],
        },
    )
    source_path = tmp_path / "source.json"
    patch_path = tmp_path / "patch.json"
    source_path.write_text(json.dumps({"two_stage_understanding": {"stage2_numbering": stage2}}), encoding="utf-8")
    patch_path.write_text(json.dumps(patch), encoding="utf-8")

    screenshot_path = tmp_path / "frozen.png"
    Image.new("RGB", (400, 300), "white").save(screenshot_path)

    report = run_closure(
        stage2_source_path=source_path,
        validated_patch_path=patch_path,
        screenshot_path=str(screenshot_path),
        out_path=tmp_path / "closure.json",
    )

    assert report["workflow_state"] == "completed_review_only"
    assert report["generic_repair_request_count"] == 1
    assert report["deterministic_repair_passed"] == 1
    assert report["safety"]["real_clicks"] == 0
    assert Path(report["final_repaired_overlay_path"]).exists()
    assert report["three_image_evidence"]["final_repaired_fusion"] == report["final_repaired_overlay_path"]
    assert report["final_graph_revision"] != report["source_graph_revision"]
