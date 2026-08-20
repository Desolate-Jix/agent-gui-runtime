from pathlib import Path

from PIL import Image

from app.learn.recognition.two_stage import model_grounding_evidence_status_from_two_stage
from scripts.run_learn_two_stage_replay import (
    _apply_source_image_override,
    _overlay_status,
    _source_image_status,
)


def test_source_image_status_flags_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.png"

    status = _source_image_status(missing)

    assert status["path"] == str(missing)
    assert status["exists"] is False
    assert status["status"] == "missing_path"


def test_overlay_status_explains_missing_source_image(tmp_path: Path) -> None:
    source_status = _source_image_status(tmp_path / "missing.png")

    status = _overlay_status(overlay_path="", source_image_status=source_status)

    assert status["status"] == "not_rendered"
    assert status["reason"] == "source_image_missing"


def test_overlay_status_available_when_overlay_exists(tmp_path: Path) -> None:
    image = tmp_path / "source.png"
    image.write_bytes(b"not used by helper")
    source_status = _source_image_status(image)

    status = _overlay_status(overlay_path="artifacts/review-overlays/example.png", source_image_status=source_status)

    assert source_status["status"] == "available"
    assert status["status"] == "available"
    assert status["path"] == "artifacts/review-overlays/example.png"


def test_source_image_override_updates_bundle_with_real_image_size(tmp_path: Path) -> None:
    image = tmp_path / "override.png"
    Image.new("RGB", (321, 123), "white").save(image)
    bundle = {"image_path": "missing.png", "screen_size": {"width": 1, "height": 1}}

    status = _apply_source_image_override(bundle, str(image))

    assert status["applied"] is True
    assert status["reason"] == "explicit_source_image_override"
    assert status["original_path"] == "missing.png"
    assert bundle["image_path"] == str(image)
    assert bundle["source_image_path"] == str(image)
    assert bundle["screen_size"] == {"width": 321, "height": 123}


def test_source_image_override_missing_path_does_not_change_bundle(tmp_path: Path) -> None:
    bundle = {"image_path": "original.png"}

    status = _apply_source_image_override(bundle, str(tmp_path / "missing.png"))

    assert status["applied"] is False
    assert status["reason"] == "override_missing"
    assert bundle["image_path"] == "original.png"


def test_model_grounding_evidence_rejects_recommendation_only_report() -> None:
    report = {
        "model_call_plan": {
            "semantic_model": "qwen3_vl_8b_q4_k_m",
            "coordinate_model": "vista_4b_transformers",
        },
        "stage1_region_localization": {
            "regions": [
                {
                    "region_id": "top",
                    "coordinate_validation": {
                        "model_grounding_attempted": False,
                        "semantic_model": "not_run",
                        "coordinate_model": "not_run",
                    },
                },
                {
                    "region_id": "main",
                    "coordinate_validation": {
                        "model_grounding_attempted": False,
                        "semantic_model": "not_run",
                        "coordinate_model": "not_run",
                    },
                },
            ]
        },
        "stage2_numbering": {"numbered_item_count": 12},
    }

    status = model_grounding_evidence_status_from_two_stage(report)

    assert status["status"] == "not_valid_for_model_grounding_evidence"
    assert status["model_grounding_attempted_count"] == 0
    assert status["model_call_plan_is_recommendation_only"] is True
    assert status["reason"] == "no_model_grounding_attempts_recorded"


def test_model_grounding_evidence_accepts_recorded_model_grounding() -> None:
    report = {
        "stage1_region_localization": {
            "regions": [
                {
                    "region_id": "main",
                    "coordinate_validation": {
                        "model_grounding_attempted": True,
                        "semantic_model": "qwen3_vl_8b_q4_k_m",
                        "coordinate_model": "vista_4b_transformers",
                    },
                }
            ]
        },
        "stage2_numbering": {"numbered_item_count": 3},
    }

    status = model_grounding_evidence_status_from_two_stage(report)

    assert status["status"] == "valid_for_model_grounding_evidence"
    assert status["model_grounding_attempted_count"] == 1
    assert status["model_grounded_region_ids"] == ["main"]
