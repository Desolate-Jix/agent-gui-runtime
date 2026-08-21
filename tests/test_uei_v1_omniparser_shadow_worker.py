from __future__ import annotations

from pathlib import Path

import pytest


def _patch_runner(monkeypatch, *, outputs):
    from scripts import run_omniparser_learn_smoke as runner

    observed: dict[str, object] = {}
    values = iter(outputs)
    monkeypatch.setattr(runner, "_load_profile", lambda: {
        "expected_paths": {
            "code_path": "vendor/OmniParser",
            "weights_path": "models/omniparser/v2.0.1/weights",
            "huggingface_cache_path": "~/.cache/huggingface/hub",
        },
    })

    def preflight(*, code_path, weights_path, hub_cache):
        observed["preflight_cache"] = hub_cache
        return {}

    def load_models(code_path, weights_path, hub_cache):
        observed["model_cache"] = hub_cache
        return object(), object(), object(), object()

    monkeypatch.setattr(runner, "_preflight", preflight)
    monkeypatch.setattr(runner, "_load_official_models", load_models)
    monkeypatch.setattr(runner, "_run_once", lambda **kwargs: next(values))
    return observed


def test_worker_uses_profile_huggingface_cache_for_preflight_and_model_load(tmp_path: Path, monkeypatch):
    from scripts import run_uei_omniparser_shadow_worker as worker

    observed = _patch_runner(monkeypatch, outputs=[([], 4.0)])
    monkeypatch.setattr(worker, "_peak_resource_units", lambda: 7)

    result = worker._run(tmp_path / "capture.png", {"width": 20, "height": 10})

    expected = Path("~/.cache/huggingface/hub").expanduser()
    assert observed == {"preflight_cache": expected, "model_cache": expected}
    assert result["resource_units"] == 7


def test_benchmark_worker_records_observed_invalid_counts_for_cold_and_three_warm_runs(tmp_path: Path, monkeypatch):
    from scripts import run_uei_omniparser_shadow_worker as worker

    valid = {"bbox": [0.1, 0.2, 0.5, 0.8], "type": "text", "content": "Search"}
    invalid_bbox = {"bbox": [0.5, 0.2, 0.1, 0.8], "type": "text", "content": "Bad"}
    _patch_runner(monkeypatch, outputs=[
        ([valid], 10.2),
        ([valid, invalid_bbox], 3.1),
        ([valid], 2.2),
        ([valid, "invalid"], 2.8),
    ])
    monkeypatch.setattr(worker, "_peak_resource_units", lambda: 9)

    result = worker._run(tmp_path / "capture.png", {"width": 20, "height": 10}, benchmark=True)

    assert result["benchmark"] == {
        "cold_ms": 10,
        "warm_ms": [3, 2, 3],
        "warm_p50_ms": 3,
        "warm_p95_ms": 3,
        "item_counts": [1, 2, 1, 2],
        "invalid_item_counts": [0, 1, 0, 1],
        "peak_mib": 9,
    }


@pytest.mark.parametrize("items", [[{"bbox": [0.1, 0.2, 0.5]}], ["invalid"]])
def test_worker_rejects_malformed_cold_output_before_persistence(tmp_path: Path, monkeypatch, items):
    from scripts import run_uei_omniparser_shadow_worker as worker

    _patch_runner(monkeypatch, outputs=[(items, 1.0)])
    monkeypatch.setattr(worker, "_peak_resource_units", lambda: 0)

    with pytest.raises(ValueError, match="worker_output_invalid"):
        worker._run(tmp_path / "capture.png", {"width": 20, "height": 10})
