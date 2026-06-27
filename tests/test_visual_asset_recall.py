from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.api.vision import _build_visual_asset_recall
from app.vision.schemas import ImageSize


def _draw_button(path: Path, *, xy: tuple[int, int], label: str) -> dict[str, int]:
    image = Image.new("RGB", (640, 420), "white")
    draw = ImageDraw.Draw(image)
    x, y = xy
    bbox = {"x": x, "y": y, "w": 150, "h": 46}
    draw.rounded_rectangle((x, y, x + bbox["w"], y + bbox["h"]), radius=8, fill=(229, 0, 125))
    draw.text((x + 28, y + 14), label, fill="white")
    image.save(path)
    return bbox


def _asset_store(
    *,
    template_path: Path,
    source_bbox: dict[str, int],
    label: str,
    semantic_action: str,
    danger_level: str,
    review_policy: dict | None = None,
) -> dict:
    return {
        "contract_version": "visual_asset_store_v1",
        "assets": [
            {
                "contract_version": "visual_asset_v1",
                "asset_id": "seek.quick_apply.primary",
                "label": label,
                "semantic_action": semantic_action,
                "danger_level": danger_level,
                "review_policy": review_policy,
                "requires_gate": True,
                "can_authorize_click": False,
                "source": {
                    "capture_id": "learn-capture",
                    "screenshot_size": {"width": 640, "height": 420},
                },
                "source_geometry": {
                    "bbox": source_bbox,
                    "click_point": {
                        "x": source_bbox["x"] + source_bbox["w"] // 2,
                        "y": source_bbox["y"] + source_bbox["h"] // 2,
                    },
                },
                "crop": {"tight_crop_ref": str(template_path)},
                "match_policy": {"scale_variants": [1.0], "min_score": 0.9},
                "scope": {"allowed_container_ids": ["seek:job_detail"]},
            }
        ],
    }


def test_visual_asset_recall_builds_fresh_seeded_candidate(tmp_path: Path) -> None:
    learned_path = tmp_path / "learned.png"
    target_path = tmp_path / "target.png"
    learned_bbox = _draw_button(learned_path, xy=(420, 60), label="Quick apply")
    target_bbox = _draw_button(target_path, xy=(430, 80), label="Quick apply")
    template_path = tmp_path / "quick_apply.png"
    with Image.open(learned_path) as image:
        image.crop(
            (
                learned_bbox["x"],
                learned_bbox["y"],
                learned_bbox["x"] + learned_bbox["w"],
                learned_bbox["y"] + learned_bbox["h"],
            )
        ).save(template_path)

    recall = _build_visual_asset_recall(
        metadata={"visual_assets": _asset_store(
            template_path=template_path,
            source_bbox=learned_bbox,
            label="Quick apply",
            semantic_action="open_apply_flow",
            danger_level="flow_entry",
        )},
        observe_reuse={},
        image_path=target_path,
        image_size=ImageSize(width=640, height=420),
        goal="点击申请",
    )

    assert recall["contract_version"] == "visual_asset_recall_v1"
    assert recall["status"] == "matched"
    assert recall["fast_lane_allowed"] is True
    assert recall["selected_candidate"]["bbox"] == target_bbox
    assert recall["selected_candidate"]["click_point"] == {"x": 505, "y": 103}
    assert recall["selected_candidate"]["risk_class"] == "safe_open_apply_flow"
    assert recall["selected_candidate"]["candidate_freshness"]["source"] == "visual_asset_match_v1"
    assert recall["selected_candidate"]["candidate_freshness"]["capture_id"] == str(target_path)


def test_visual_asset_recall_does_not_fast_lane_final_submit(tmp_path: Path) -> None:
    learned_path = tmp_path / "learned.png"
    target_path = tmp_path / "target.png"
    learned_bbox = _draw_button(learned_path, xy=(420, 60), label="Submit")
    _draw_button(target_path, xy=(430, 80), label="Submit")
    template_path = tmp_path / "submit.png"
    with Image.open(learned_path) as image:
        image.crop(
            (
                learned_bbox["x"],
                learned_bbox["y"],
                learned_bbox["x"] + learned_bbox["w"],
                learned_bbox["y"] + learned_bbox["h"],
            )
        ).save(template_path)

    recall = _build_visual_asset_recall(
        metadata={"visual_assets": _asset_store(
            template_path=template_path,
            source_bbox=learned_bbox,
            label="Submit",
            semantic_action="final_submit",
            danger_level="final_submit",
        )},
        observe_reuse={},
        image_path=target_path,
        image_size=ImageSize(width=640, height=420),
        goal="click Submit",
    )

    assert recall["status"] == "matched"
    assert recall["fast_lane_allowed"] is False
    assert recall["selected_candidate"] is None
    assert recall["matches"][0]["candidate"]["risk_class"] == "potential_side_effect_action"


def test_visual_asset_recall_respects_gate_required_review_policy(tmp_path: Path) -> None:
    learned_path = tmp_path / "learned.png"
    target_path = tmp_path / "target.png"
    learned_bbox = _draw_button(learned_path, xy=(420, 60), label="Quick apply")
    _draw_button(target_path, xy=(430, 80), label="Quick apply")
    template_path = tmp_path / "quick_apply.png"
    with Image.open(learned_path) as image:
        image.crop(
            (
                learned_bbox["x"],
                learned_bbox["y"],
                learned_bbox["x"] + learned_bbox["w"],
                learned_bbox["y"] + learned_bbox["h"],
            )
        ).save(template_path)

    recall = _build_visual_asset_recall(
        metadata={"visual_assets": _asset_store(
            template_path=template_path,
            source_bbox=learned_bbox,
            label="Quick apply",
            semantic_action="open_apply_flow",
            danger_level="flow_entry",
            review_policy={
                "contract_version": "visual_asset_review_policy_v1",
                "risk_tier": "medium",
                "click_permission": "gate_required",
                "fast_lane_eligible": False,
            },
        )},
        observe_reuse={},
        image_path=target_path,
        image_size=ImageSize(width=640, height=420),
        goal="点击申请",
    )

    assert recall["status"] == "matched"
    assert recall["fast_lane_allowed"] is False
    assert recall["selected_candidate"] is None
    assert recall["matches"][0]["asset_summary"]["review_policy"]["click_permission"] == "gate_required"


def test_visual_asset_recall_accepts_learned_interface_map_assets(tmp_path: Path) -> None:
    learned_path = tmp_path / "learned.png"
    target_path = tmp_path / "target.png"
    learned_bbox = _draw_button(learned_path, xy=(420, 60), label="Continue")
    target_bbox = _draw_button(target_path, xy=(430, 80), label="Continue")
    template_path = tmp_path / "continue.png"
    with Image.open(learned_path) as image:
        image.crop(
            (
                learned_bbox["x"],
                learned_bbox["y"],
                learned_bbox["x"] + learned_bbox["w"],
                learned_bbox["y"] + learned_bbox["h"],
            )
        ).save(template_path)

    learned_interface_map = {
        "contract_version": "learned_interface_map_v1",
        "fixed_visual_assets": [
            {
                "asset_id": "seek.continue.primary",
                "label": "Continue",
                "semantic_action": "continue_next_step",
                "danger_level": "continue_step",
                "requires_gate": True,
                "can_authorize_click": False,
                "region_id": "application_form",
                "allowed_region_ids": ["application_form"],
                "source_geometry": {
                    "bbox": learned_bbox,
                    "click_point": {
                        "x": learned_bbox["x"] + learned_bbox["w"] // 2,
                        "y": learned_bbox["y"] + learned_bbox["h"] // 2,
                    },
                },
                "template_refs": {"tight_crop_ref": str(template_path)},
                "match_policy": {"scale_variants": [1.0], "min_score": 0.9},
            }
        ],
    }

    recall = _build_visual_asset_recall(
        metadata={"learned_interface_map": learned_interface_map},
        observe_reuse={},
        image_path=target_path,
        image_size=ImageSize(width=640, height=420),
        goal="继续下一步",
    )

    assert recall["status"] == "matched"
    assert recall["fast_lane_allowed"] is True
    assert recall["selected_asset_id"] == "seek.continue.primary"
    assert recall["selected_candidate"]["bbox"] == target_bbox
    assert recall["selected_candidate"]["click_point"] == {"x": 505, "y": 103}
    assert recall["selected_candidate"]["risk_class"] == "safe_continue_next_step"
    assert recall["matches"][0]["allowed_region"]["container_id"] == "application_form"
