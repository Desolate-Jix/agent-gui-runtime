from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
VISION_CONFIG_PATH = ROOT_DIR / "configs" / "vision.json"
PANEL_CONFIG_PATH = ROOT_DIR / "configs" / "settings_panel.json"
ARTIFACT_DIR = ROOT_DIR / "artifacts" / "settings-panel"

DEFAULT_PANEL_CONFIG: dict[str, Any] = {
    "runtime_base_url": "http://127.0.0.1:8000",
    "mode": "local_flow",
    "language": "zh-CN",
    "prompt_overrides": {
        "additional_rules": (
            "For navigation icons, first identify nearby OCR text boxes as boundary rulers. "
            "Do not include adjacent navigation labels unless they are part of the target."
        )
    },
}


def load_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default, ensure_ascii=False))
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
