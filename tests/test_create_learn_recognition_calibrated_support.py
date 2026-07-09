from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from scripts.bind_learn_recognition_support_to_manifest import bind_support_to_manifest
from scripts.create_learn_recognition_calibrated_support import create_calibrated_support


def test_create_calibrated_support_writes_exact_sha_bindable_artifact(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (200, 120), "white").save(screenshot)
    targets = tmp_path / "targets.json"
    targets.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "candidate_id": "search_button",
                        "label": "Search",
                        "role": "button",
                        "bbox": {"x": 40, "y": 20, "w": 80, "h": 30},
                        "click_point": {"x": 80, "y": 35},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = create_calibrated_support(
        screenshot_path=screenshot,
        targets_path=targets,
        out_dir=tmp_path / "support",
        app_name="test_app",
        state_hint="search_page",
    )

    support_path = Path(result["support_path"])
    payload = json.loads(support_path.read_text(encoding="utf-8"))
    assert payload["contract_version"] == "learn_recognition_same_screenshot_support_v1"
    assert payload["support_type"] == "calibrated_targets"
    assert payload["screenshot_sha256"] == _sha256_file(screenshot)
    assert payload["counts_as_model_ability"] is False
    assert payload["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "no_dispatch": True,
        "real_clicks_performed": 0,
        "final_submit_forbidden": True,
    }
    target = payload["sources"]["calibrated_targets"]["targets"][0]
    assert target["coordinate_validation"]["status"] == "valid"
    assert target["counts_as_model_ability"] is False
    assert target["artifact_is_authorization"] is False
    assert target["execute_binding_enabled"] is False

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"cases": [{"case_id": "locked_case", "screenshot_path": str(screenshot)}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    bind_result = bind_support_to_manifest(
        manifest_path=manifest,
        case_id="locked_case",
        support_path=support_path,
        out_path=tmp_path / "manifest.bound.json",
    )
    assert bind_result["status"] == "bound"
    assert bind_result["validity"]["status"] == "checksum_match"


def test_create_calibrated_support_rejects_invalid_bbox(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (100, 80), "white").save(screenshot)
    targets = tmp_path / "targets.json"
    targets.write_text(
        json.dumps(
            [{"candidate_id": "bad", "label": "Bad", "bbox": {"x": 90, "y": 70, "w": 40, "h": 20}}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        create_calibrated_support(
            screenshot_path=screenshot,
            targets_path=targets,
            out_dir=tmp_path / "support",
        )
    except ValueError as exc:
        assert "invalid calibrated target" in str(exc)
    else:
        raise AssertionError("invalid bbox should be rejected")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
