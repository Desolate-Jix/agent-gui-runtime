from pathlib import Path

from PIL import Image

from scripts.run_learn_screenshot_exploration import run_screenshot_exploration


def test_screenshot_exploration_marks_source_as_screenshot_only(tmp_path: Path) -> None:
    image = tmp_path / "screen.png"
    Image.new("RGB", (320, 180), "white").save(image)

    report = run_screenshot_exploration(image_path=image, require_stage1_gate=True, root=tmp_path)

    assert report["contract_version"] == "learn_two_stage_screen_understanding_v1"
    assert report["source_provenance"]["source_type"] == "screenshot_only"
    assert report["source_provenance"]["trace_available"] is False
    assert report["source_provenance"]["ocr_uia_inventory_available"] is False
    assert report["model_grounding_evidence"]["model_accuracy_claim_allowed"] is False
    assert report["safety"]["live_clicks"] == 0
    assert report["safety"]["execute_binding_enabled"] is False
    assert report["exploration_status"]["status"] == "no_review_boxes"
    assert report["exploration_status"]["demo_readiness"] == "not_demo_ready"
    assert "safe screenshot-only pipeline ran" in report["exploration_status"]["interpretation"]
