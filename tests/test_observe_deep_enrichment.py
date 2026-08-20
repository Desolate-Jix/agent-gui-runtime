from __future__ import annotations

import inspect

from app.operation.observe.contracts import ObserveScreenTaskInput


def test_model_io_failure_trace_preserves_provider_diagnostics() -> None:
    from app.vision.model_io import model_io_failure_payload

    error = RuntimeError("invalid model output")
    error.diagnostics = {
        "provider": "local_understanding",
        "raw_text": "{invalid",
    }

    assert model_io_failure_payload(error) == {
        "contract_version": "model_io_trace_v1",
        "status": "failed",
        "provider": "local_understanding",
        "raw_text": "{invalid",
    }


def test_visual_asset_policy_uses_neutral_observe_task() -> None:
    from app.learn.observe_enrichment.visual_assets import (
        should_learn_visual_assets,
    )

    fast_task = ObserveScreenTaskInput(learn_depth="fast")
    disabled_task = ObserveScreenTaskInput(
        learn_depth="fast",
        metadata={"visual_assets": {"enabled": False}},
    )

    assert should_learn_visual_assets(fast_task) is True
    assert should_learn_visual_assets(disabled_task) is False


def test_deep_enrichment_modules_do_not_import_api() -> None:
    from app.learn.observe_enrichment import deep_review, visual_assets

    source = inspect.getsource(deep_review) + inspect.getsource(visual_assets)

    assert "app.api" not in source
    assert "fastapi" not in source
