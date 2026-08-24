from __future__ import annotations

from hashlib import sha256
from pathlib import Path

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


import importlib.util


_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "run_omniparser_learn_smoke",
    Path("scripts/run_omniparser_learn_smoke.py"),
)
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
runner = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(runner)


def test_weight_manifest_rejects_a_hash_mismatch_before_inference(tmp_path) -> None:
    weight = tmp_path / "icon_detect" / "model.pt"
    weight.parent.mkdir()
    weight.write_bytes(b"official-weight")

    with pytest.raises(OmniparserProviderError, match="weights_hash_mismatch") as exc_info:
        runner._verify_weight_manifest(
            tmp_path,
            {"icon_detect/model.pt": "0" * 64},
        )

    assert exc_info.value.code == "weights_hash_mismatch"


def test_florence_offline_cache_requires_both_exact_revisions(tmp_path) -> None:
    with pytest.raises(OmniparserProviderError, match="dependency_missing") as exc_info:
        runner._require_florence_offline_assets(tmp_path)

    assert exc_info.value.code == "dependency_missing"


def test_preflight_rejects_a_missing_process_inspector() -> None:
    with pytest.raises(OmniparserProviderError, match="dependency_missing") as exc_info:
        runner._resident_compute_models(psutil_module=None, current_pid=42)

    assert exc_info.value.code == "dependency_missing"


def test_benchmark_mode_requires_three_warm_repetitions() -> None:
    with pytest.raises(OmniparserProviderError, match="protocol_invalid"):
        runner._validate_warm_repetitions(2)

    assert runner._validate_warm_repetitions(3) == 3


def test_run_once_treats_missing_ocr_result_as_an_empty_evidence_set(tmp_path) -> None:
    observed: dict[str, object] = {}

    def check_ocr_box(*args, **kwargs):
        return (None, None), None

    def get_som_labeled_img(*args, **kwargs):
        observed["ocr_bbox"] = kwargs["ocr_bbox"]
        observed["ocr_text"] = kwargs["ocr_text"]
        return None, None, []

    items, _ = runner._run_once(
        input_path=tmp_path / "sparse-screen.png",
        detector=object(),
        caption=object(),
        check_ocr_box=check_ocr_box,
        get_som_labeled_img=get_som_labeled_img,
    )

    assert items == []
    assert observed == {"ocr_bbox": [], "ocr_text": []}


def test_per_run_metrics_include_element_interactivity_and_invalid_bbox_counts() -> None:
    metrics = runner._element_metrics(
        [
            {"bbox": [0.1, 0.2, 0.3, 0.4], "interactivity": True},
            {"bbox": [0.4, 0.2, 0.3, 0.5], "interactivity": False},
        ]
    )

    assert metrics == {"element_count": 2, "interactive_count": 1, "invalid_bbox_count": 1}



def test_pinned_caption_config_uses_local_weight_directory_with_exact_revision(tmp_path) -> None:
    weights = tmp_path / "weights"
    expected = weights / "icon_caption_florence"

    assert runner._pinned_caption_config_source(weights) == expected



def test_license_provenance_records_the_root_cc_by_source_without_claiming_mit(tmp_path) -> None:
    code = tmp_path / "code"
    weights = tmp_path / "weights"
    (code).mkdir()
    (weights / "icon_detect").mkdir(parents=True)
    (weights / "icon_caption_florence").mkdir()
    (code / "LICENSE").write_text("Attribution 4.0 International", encoding="utf-8")
    (weights / "icon_detect" / "LICENSE").write_text("AGPL", encoding="utf-8")
    (weights / "icon_caption_florence" / "LICENSE").write_text("MIT License", encoding="utf-8")

    provenance = runner._license_provenance(code, weights)

    assert provenance["official_code"]["root_license"] == "CC-BY-4.0"
    assert provenance["official_code"]["status"] == "ambiguous"
    assert "MIT" not in provenance["official_code"]



def test_pinned_caption_loader_passes_exact_external_code_revision_to_config_and_model(tmp_path) -> None:
    weights = tmp_path / "weights"
    (weights / "icon_caption_florence").mkdir(parents=True)
    calls: list[tuple[str, object, dict[str, object]]] = []

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

    class FakeTorch:
        cuda = FakeCuda()
        float16 = "float16"

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, source, **kwargs):
            calls.append(("processor", source, kwargs))
            return "processor"

    class FakeConfig:
        @classmethod
        def from_pretrained(cls, source, **kwargs):
            calls.append(("config", source, kwargs))
            return "config"

    class FakeModel:
        @classmethod
        def from_pretrained(cls, source, **kwargs):
            calls.append(("model", source, kwargs))

            class Loaded:
                def to(self, device):
                    assert device == "cuda"
                    return "model"

            return Loaded()

    result = runner._load_pinned_caption_model(
        weights,
        tmp_path / "hub",
        torch_module=FakeTorch(),
        auto_processor=FakeProcessor,
        auto_config=FakeConfig,
        auto_model=FakeModel,
    )

    assert result == {"model": "model", "processor": "processor"}
    config_call = next(call for call in calls if call[0] == "config")
    model_call = next(call for call in calls if call[0] == "model")
    assert config_call[2]["code_revision"] == runner.FLORENCE_MODEL_REVISION
    assert model_call[2]["code_revision"] == runner.FLORENCE_MODEL_REVISION
    assert model_call[2]["local_files_only"] is True
