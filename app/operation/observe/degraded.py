from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from app.core.ocr_service import ocr_service
from app.operation.observe.contracts import (
    ObserveScreenReadResult,
    ObserveScreenTaskInput,
)
from app.operation.screen_reading.uia_provider import uia_provider


def image_size_payload(
    *,
    image_path: str,
    live_capture: dict[str, Any] | None,
) -> dict[str, int]:
    if isinstance(live_capture, dict):
        width = _number(
            live_capture.get("image_width") or live_capture.get("width")
        )
        height = _number(
            live_capture.get("image_height") or live_capture.get("height")
        )
        if width and height:
            return {"width": int(width), "height": int(height)}
    try:
        with Image.open(image_path) as image:
            return {
                "width": int(image.width),
                "height": int(image.height),
            }
    except Exception:
        return {"width": 0, "height": 0}


def build_degraded_observation(
    *,
    task: ObserveScreenTaskInput,
    image_path: str,
    live_capture: dict[str, Any] | None,
    screen_result: ObserveScreenReadResult,
) -> dict[str, Any]:
    image_size = image_size_payload(
        image_path=image_path,
        live_capture=live_capture,
    )
    ocr_payload: dict[str, Any] = {
        "image_path": image_path,
        "matches": [],
        "metadata": {"status": "unavailable"},
    }
    ocr_error = None
    try:
        ocr_payload = ocr_service.scan_image(str(image_path)).to_dict()
    except Exception as exc:
        ocr_error = str(exc)
        ocr_payload["metadata"] = {
            "status": "failed",
            "error": ocr_error,
        }

    try:
        uia_snapshot = uia_provider.snapshot_bound_window()
    except Exception as exc:
        uia_snapshot = {
            "provider": "windows_uia",
            "status": "failed",
            "reason": str(exc),
            "control_count": 0,
            "controls": [],
        }

    texts = _texts_from_ocr_payload(ocr_payload)
    error_details = screen_result.error
    screen_summary = (
        "Degraded screen observation from OCR/UIA because model screen "
        "reading failed."
    )
    state_guess = (
        task.state_hint
        or _first_compact_text(*(item.get("text") for item in texts[:5]))
        or "ocr fallback observation"
    )
    screen_reading_payload = {
        "contract_version": "screen_reading_v1",
        "status": "degraded",
        "image_path": image_path,
        "app_name": task.app_name,
        "image_size": image_size,
        "screen_summary": screen_summary,
        "state_guess": state_guess,
        "texts": texts,
        "ui": {
            "summary": {
                "element_count": 0,
                "module_count": 0,
                "icon_candidate_count": 0,
                "text_backed_element_count": 0,
                "visual_only_element_count": 0,
            },
            "elements": [],
            "modules": [],
            "icon_candidates": [],
            "provider_slots": {
                "uia": {
                    "status": "connected",
                    "last_scan_status": uia_snapshot.get("status"),
                    "control_count": uia_snapshot.get("control_count"),
                }
            },
            "learning_hooks": [],
        },
        "ui_elements": [],
        "modules": [],
        "relationships": [],
        "execution_relevance": {
            "safe_action_candidates": [],
            "risky_candidates": [],
            "unknown_candidates": [],
        },
        "uncertainties": {
            "status": "degraded_model_failure",
            "reason": "screen_reading_failed",
            "needed_evidence": [
                "model_json_repair_or_retry",
                "locate_target_before_click",
            ],
        },
        "source_layers": {
            "vision_regions_v1": {
                "provider": task.provider_mode or "local_understanding",
                "status": "failed",
                "error": error_details,
            },
            "ocr_result": {
                "engine": str(
                    (ocr_payload.get("metadata") or {}).get("engine") or "ocr"
                ),
                "match_count": len(texts),
                "error": ocr_error,
            },
            "windows_uia": {
                "status": uia_snapshot.get("status"),
                "control_count": uia_snapshot.get("control_count"),
                "available": uia_snapshot.get("status") == "ok",
            },
        },
        "raw_refs": {
            "ocr_image_path": ocr_payload.get("image_path"),
            "degraded_from_error": error_details,
            "model_io": screen_result.model_io,
        },
    }
    return {
        "contract_version": "screen_observation_v1",
        "status": "degraded",
        "image_path": image_path,
        "image_size": image_size,
        "app_name": task.app_name,
        "screen_summary": screen_summary,
        "state_guess": state_guess,
        "texts": texts,
        "ocr_result": ocr_payload,
        "screen_reading": screen_reading_payload,
        "degraded_reason": {
            "code": "screen_reading_failed",
            "message": screen_result.message,
            "error": error_details,
            "model_io": screen_result.model_io,
        },
        "execution_path": {
            "vision_provider_requested": (
                task.provider_mode or "local_understanding"
            ),
            "vision_provider_used": None,
            "vision_model_used": False,
            "page_structure_used": False,
            "screen_reading_used": False,
            "degraded_observe_fallback_used": True,
            "coordinate_source": "ocr_result_v1",
        },
    }


def _texts_from_ocr_payload(
    ocr_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    texts: list[dict[str, Any]] = []
    matches = ocr_payload.get("matches")
    for index, match in enumerate(matches if isinstance(matches, list) else []):
        if not isinstance(match, dict):
            continue
        text = _first_compact_text(match.get("text"))
        bbox = _normalize_bbox(match.get("bbox"))
        if not text or not bbox:
            continue
        texts.append(
            {
                "id": f"ocr_fallback_text_{index}",
                "text": text,
                "bbox": bbox,
                "confidence": _bounded_float(match.get("score")),
                "source": "ocr_fallback",
                "source_index": index,
            }
        )
    return texts


def _normalize_bbox(value: Any) -> dict[str, int] | None:
    item = value if isinstance(value, dict) else {}
    x = _number(item.get("x"))
    y = _number(item.get("y"))
    width = _number(item.get("w") if "w" in item else item.get("width"))
    height = _number(item.get("h") if "h" in item else item.get("height"))
    if None in {x, y, width, height} or width <= 0 or height <= 0:
        return None
    return {
        "x": int(round(x)),
        "y": int(round(y)),
        "w": int(round(width)),
        "h": int(round(height)),
    }


def _first_compact_text(*values: Any) -> str:
    return next(
        (
            " ".join(str(value).split())
            for value in values
            if value is not None and str(value).strip()
        ),
        "",
    )


def _bounded_float(value: Any) -> float:
    number = _number(value)
    return max(0.0, min(1.0, number or 0.0))


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
