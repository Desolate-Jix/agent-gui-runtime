from __future__ import annotations

from pathlib import Path
from typing import Any

from app.vision.api_provider import ApiVisionProvider
from app.vision.configuration import _select_local_config, load_vision_config
from app.vision.local_provider import LocalVisionProvider

DEFAULT_CONFIG = {
    "vision": {
        "mode": "local",
        "fallback_mode": "api",
        "timeout_seconds": 600,
        "local": {
            "model_name": "local_stub",
            "endpoint": None,
        },
        "api": {
            "provider": "api_stub",
            "model": "api_stub",
            "endpoint": None,
        },
    }
}


class VisionProviderFactory:
    @staticmethod
    def load_config(path: str | Path | None = None) -> dict[str, Any]:
        return load_vision_config(path)

    @staticmethod
    def create(mode: str | None = None, config: dict[str, Any] | None = None):
        cfg = VisionProviderFactory.load_config() if config is None else config
        vision_cfg = cfg.get("vision") or {}
        selected_mode = str(mode or vision_cfg.get("mode") or "local").strip().lower()
        if selected_mode in {"local", "local_understanding", "local_grounding"}:
            local_cfg = _select_local_config(vision_cfg, selected_mode)
            return LocalVisionProvider(
                endpoint=local_cfg.get("endpoint"),
                model_name=local_cfg.get("model_name"),
                timeout_seconds=float(vision_cfg.get("timeout_seconds") or 600),
            )
        if selected_mode == "api":
            api_cfg = vision_cfg.get("api") or {}
            return ApiVisionProvider(
                endpoint=api_cfg.get("endpoint"),
                model_name=api_cfg.get("model"),
                provider_name=api_cfg.get("provider"),
            )
        raise ValueError(f"Unsupported vision mode: {selected_mode}")

