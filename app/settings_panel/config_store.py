from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
VISION_CONFIG_PATH = ROOT_DIR / "configs" / "vision.json"
PANEL_CONFIG_PATH = ROOT_DIR / "configs" / "settings_panel.json"
MODEL_PROFILE_DIR = ROOT_DIR / "configs" / "model_profiles"
ARTIFACT_DIR = ROOT_DIR / "artifacts" / "settings-panel"

DEFAULT_OBSERVE_PROMPT = """Screen-understanding stage only:
- Explain the interface purpose briefly in screen_summary.
- Return a compact index of independently clickable controls: navigation, buttons, icon-only buttons, tabs, inputs, toggles, menus, and title-bar controls.
- Include small or uncertain icon controls with lower confidence rather than long explanations.
- Keep every label and likely action short; this is a fast discovery pass before precise localization.
- OCR coordinates are reference-only input: do not repeat OCR boxes, anchor relations, or detailed grounding evidence in the response.
- This stage describes available actions for agent planning; it must not choose or execute a click."""

DEFAULT_LOCATE_PROMPT = """Precision-localization stage only:
- Locate only the target named in goal; do not enumerate unrelated controls.
- First decide whether the clickable target is visual-only or includes visible text.
- Case A, visual-only icon: set text_inclusion_policy="exclude_text"; use nearby OCR boxes only as boundary rulers and negative constraints. The final diagonal must tightly cover the icon pixels, never the nearby label.
- Case B, text-bearing control: set text_inclusion_policy="include_referenced_text"; the final diagonal must include the referenced OCR text boxes and the visible clickable control surface.
- Select the nearest useful top, bottom, left, and right OCR anchors when available. Use them to form text_anchor_frame and anchor_relations before choosing coordinates.
- Justify all four final bbox edges in grounding_constraints.edge_constraints. Also provide center_constraints, size_constraints, negative_constraints, and final_bbox_reason.
- For small toolbar or navigation icons, prefer a tight box around the visible shape and reject boxes that drift into adjacent labels or neighboring controls.
- If multiple visual candidates remain plausible, keep confidence lower and state the ambiguity; do not invent a precise target."""

DEFAULT_PANEL_CONFIG: dict[str, Any] = {
    "runtime_base_url": "http://127.0.0.1:8000",
    "mode": "local_flow",
    "language": "zh-CN",
    "prompt_overrides": {
        "observe_additional_rules": DEFAULT_OBSERVE_PROMPT,
        "locate_additional_rules": DEFAULT_LOCATE_PROMPT,
    },
    "model_scripts": {
        "start": "scripts/model_servers/start_llama_vision_server.ps1",
        "stop": "scripts/model_servers/stop_local_vision_server.ps1",
    },
}


def load_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default, ensure_ascii=False))
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
