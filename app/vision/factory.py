from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.vision.api_provider import ApiVisionProvider
from app.vision.local_provider import LocalVisionProvider

DEFAULT_CONFIG = {
    "vision": {
        "mode": "local",
        "fallback_mode": "api",
        "timeout_seconds": 30,
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
    def load_config(path: str | Path = "configs/vision.json") -> dict[str, Any]:
        cfg_path = Path(path)
        if not cfg_path.exists():
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            return DEFAULT_CONFIG
        return json.loads(cfg_path.read_text(encoding="utf-8"))

    @staticmethod
    def create(mode: str | None = None, config: dict[str, Any] | None = None):
        cfg = config or VisionProviderFactory.load_config()
        vision_cfg = cfg.get("vision") or {}
        selected_mode = str(mode or vision_cfg.get("mode") or "local").strip().lower()
        if selected_mode == "local":
            local_cfg = vision_cfg.get("local") or {}
            return LocalVisionProvider(
                endpoint=local_cfg.get("endpoint"),
                model_name=local_cfg.get("model_name"),
            )
        if selected_mode == "api":
            api_cfg = vision_cfg.get("api") or {}
            return ApiVisionProvider(
                endpoint=api_cfg.get("endpoint"),
                model_name=api_cfg.get("model"),
                provider_name=api_cfg.get("provider"),
            )
        raise ValueError(f"Unsupported vision mode: {selected_mode}")
