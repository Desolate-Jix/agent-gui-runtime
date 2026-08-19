from __future__ import annotations

from hashlib import sha256

import pytest

from app.learn.recognition.omniparser_provider import (
    OmniparserProviderError,
    build_failed_screen_parser_result,
    normalize_omniparser_result,
    sha256_file,
)


def _context() -> dict[str, object]:
    return {
        "profile_id": "learn_mode_omniparser_v2",
        "model_revision": "v.2.0.1@0123456789abcdef",
        "capture_id": "capture-static-contact-sheet",
        "source_run_id": "omniparser-smoke-cold-001",
        "screenshot_sha256": "a" * 64,
        "image_size": {"width": 1200, "height": 800},
        "coordinate_space": "image_pixel_xyxy",
        "timing": {"inference_ms": 12.5},
        "resource_usage": {"gpu_available": False},
        "provenance": {"official_repo": "microsoft/OmniParser", "code_revision": "0123456789abcdef"},
    }


def test_normalize_success_returns_stable_non_authorizing_elements() -> None:
    result = normalize_omniparser_result(
        parsed_content_list=[
            {"type": "text", "content": "Search", "bbox": [10, 20, 110, 60], "interactivity": True, "source": "official"},
            {"type": "icon", "content": "settings", "bbox": [0.1, 0.2, 0.3, 0.4], "interactivity": False},
        ],
        **_context(),
    )

    assert result["contract_version"] == "screen_parser_result_v1"
    assert result["status"] == "success"
    assert result["screenshot_sha256"] == "a" * 64
    repeat = normalize_omniparser_result(
        parsed_content_list=[
            {"type": "text", "content": "Search", "bbox": [10, 20, 110, 60], "interactivity": True, "source": "official"},
            {"type": "icon", "content": "settings", "bbox": [0.1, 0.2, 0.3, 0.4], "interactivity": False},
        ],
        **_context(),
    )
    assert result["elements"][0]["element_id"].startswith("omniparser_0001_")
    assert result["elements"][0]["element_id"] == repeat["elements"][0]["element_id"]
    assert result["elements"][0]["bbox"] == [10.0, 20.0, 110.0, 60.0]
    assert result["elements"][1]["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert result["review_only"] is True
    assert result["grounding_eligible"] is False


def test_normalize_rejects_an_illegal_bbox_with_stable_error_code() -> None:
    with pytest.raises(OmniparserProviderError, match="invalid_bbox") as exc_info:
        normalize_omniparser_result(
            parsed_content_list=[{"type": "button", "content": "bad", "bbox": [90, 40, 20, 50]}],
            **_context(),
        )

    assert exc_info.value.code == "invalid_bbox"


def test_failed_result_preserves_missing_dependency_or_weights_code() -> None:
    result = build_failed_screen_parser_result(
        error_code="weights_missing",
        error_details="Required official weights are absent from models/omniparser/v2.0.1.",
        stage="runtime_preflight",
        **_context(),
    )

    assert result["status"] == "failed"
    assert result["error"] == {
        "code": "weights_missing",
        "details": "Required official weights are absent from models/omniparser/v2.0.1.",
        "stage": "runtime_preflight",
    }
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False


def test_sha256_file_binds_the_exact_screenshot_bytes(tmp_path) -> None:
    screenshot = tmp_path / "static-contact-sheet.png"
    screenshot.write_bytes(b"privacy-audited-static-image")

    assert sha256_file(screenshot) == sha256(b"privacy-audited-static-image").hexdigest()
