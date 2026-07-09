from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.screenshot import screenshot_service as default_screenshot_service
from app.operation.screen_reading.uia_provider import uia_provider as default_uia_provider


def capture_same_screenshot_uia_support(
    *,
    out_dir: str | Path,
    app_name: str = "",
    state_hint: str = "",
    screenshot_service: Any = default_screenshot_service,
    uia_provider: Any = default_uia_provider,
    max_controls: int = 250,
    json_stdout: bool = False,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    capture = screenshot_service.capture_window(
        save_image=True,
        purpose="learn-recognition-same-screenshot-support",
        name_hint=_safe_name(app_name or state_hint or "learn_support"),
    )
    screenshot_path = Path(str(capture.get("image_path") or ""))
    if not screenshot_path.exists():
        raise FileNotFoundError(f"screenshot was not created: {screenshot_path}")
    screenshot_sha256 = _sha256_file(screenshot_path)
    uia_snapshot = uia_provider.snapshot_bound_window(max_controls=max_controls)
    sources = {
        "uia": {
            "provider": uia_snapshot.get("provider") or "windows_uia",
            "provider_version": uia_snapshot.get("provider_version"),
            "status": uia_snapshot.get("status"),
            "window": uia_snapshot.get("window") if isinstance(uia_snapshot.get("window"), dict) else {},
            "control_count": int(uia_snapshot.get("control_count") or 0),
            "controls": [item for item in (uia_snapshot.get("controls") or []) if isinstance(item, dict)],
        }
    }
    payload = {
        "contract_version": "learn_recognition_same_screenshot_support_v1",
        "support_type": "uia",
        "support_scope": "same_screenshot_interactable_support_only",
        "created_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "app_name": app_name,
        "state_hint": state_hint,
        "screenshot_path": str(screenshot_path),
        "screenshot_sha256": screenshot_sha256,
        "screenshot": {
            "path": str(screenshot_path),
            "sha256": screenshot_sha256,
            "image_width": capture.get("image_width"),
            "image_height": capture.get("image_height"),
            "window_size": capture.get("window_size") if isinstance(capture.get("window_size"), dict) else {},
        },
        "sources": sources,
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "no_dispatch": True,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
        "interpretation": (
            "Same-screenshot UIA support can help parser/PathGraph candidate review, "
            "but it is not Execute authorization and does not prove model accuracy."
        ),
    }
    support_path = out_dir / "same_screenshot_uia_support.json"
    support_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "success": True,
        "support_path": str(support_path),
        "screenshot_path": str(screenshot_path),
        "screenshot_sha256": screenshot_sha256,
        "support_source_keys": sorted(sources.keys()),
        "uia_status": str(uia_snapshot.get("status") or "unknown"),
        "uia_control_count": int(uia_snapshot.get("control_count") or 0),
        "safety": payload["safety"],
    }
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value.strip())
    return safe[:60] or "learn_support"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--app-name", default="")
    parser.add_argument("--state-hint", default="")
    parser.add_argument("--max-controls", type=int, default=250)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    capture_same_screenshot_uia_support(
        out_dir=args.out,
        app_name=args.app_name,
        state_hint=args.state_hint,
        max_controls=args.max_controls,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
