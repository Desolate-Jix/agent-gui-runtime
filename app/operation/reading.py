from __future__ import annotations

import hashlib
import re
from typing import Any


CONTRACT_VERSION = "read_region_batch_v1"


def build_read_region_batch_report(
    *,
    target_container_id: str,
    target_bbox: dict[str, Any] | None,
    captures: list[dict[str, Any]],
    max_captures: int,
    stop_after_no_new_content: int = 2,
    wrong_scope_detected: bool = False,
) -> dict[str, Any]:
    merged_lines: list[str] = []
    seen: set[str] = set()
    normalized_capture_summaries: list[dict[str, Any]] = []
    consecutive_no_new_content = 0
    stop_reason = "max_captures"

    for index, capture in enumerate(captures):
        lines = extract_ocr_text_lines(capture.get("ocr_result"))
        new_lines: list[str] = []
        new_hashes: list[str] = []
        for line in lines:
            line_hash = normalized_line_hash(line)
            if not line_hash or line_hash in seen:
                continue
            seen.add(line_hash)
            merged_lines.append(line)
            new_lines.append(line)
            new_hashes.append(line_hash)
        if new_lines:
            consecutive_no_new_content = 0
        else:
            consecutive_no_new_content += 1
        normalized_capture_summaries.append(
            {
                "index": index,
                "image_path": capture.get("image_path"),
                "trace_path": capture.get("trace_path"),
                "line_count": len(lines),
                "new_unique_line_count": len(new_lines),
                "new_unique_line_hashes": new_hashes,
                "scroll_trace_path": capture.get("scroll_trace_path"),
                "scroll_wheel_clicks": capture.get("scroll_wheel_clicks"),
                "scroll_effect_status": capture.get("scroll_effect_status"),
            }
        )
        if wrong_scope_detected:
            stop_reason = "wrong_scope_detected"
            break
        if consecutive_no_new_content >= max(1, int(stop_after_no_new_content)):
            stop_reason = "no_new_content"
            break

    if len(captures) < max_captures and stop_reason == "max_captures":
        stop_reason = "captures_exhausted"

    return {
        "contract_version": CONTRACT_VERSION,
        "target_container_id": target_container_id,
        "target_bbox": _bbox(target_bbox),
        "capture_strategy": {
            "mode": "adaptive_batch_scroll",
            "max_captures": int(max_captures),
            "stop_after_no_new_content": int(stop_after_no_new_content),
        },
        "captures": normalized_capture_summaries,
        "capture_count": len(normalized_capture_summaries),
        "merged_text_lines": merged_lines,
        "merged_text": "\n".join(merged_lines),
        "unique_line_count": len(merged_lines),
        "wrong_scope_detected": bool(wrong_scope_detected),
        "stop_reason": stop_reason,
        "status": "blocked_wrong_scope" if wrong_scope_detected else ("ok" if merged_lines else "empty"),
    }


def extract_ocr_text_lines(ocr_result: dict[str, Any] | None) -> list[str]:
    payload = ocr_result if isinstance(ocr_result, dict) else {}
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = payload.get("texts")
    if not isinstance(raw_items, list):
        raw_items = payload.get("anchors")
    if not isinstance(raw_items, list):
        raw_items = payload.get("matches")
    if not isinstance(raw_items, list):
        raw_items = []

    lines: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            text = item.get("text") or item.get("label") or item.get("value")
        else:
            text = item
        cleaned = clean_text_line(text)
        if cleaned:
            lines.append(cleaned)
    return lines


def clean_text_line(value: Any) -> str:
    text = " ".join(str(value or "").replace("\r", "\n").split())
    return text.strip()


def normalized_line_hash(value: Any) -> str:
    text = clean_text_line(value).casefold()
    text = re.sub(r"\s+", " ", text)
    text = text.lstrip("•·-–— ")
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _bbox(value: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(value.get("x") or 0)
        y = int(value.get("y") or 0)
        w = int(value.get("w") if value.get("w") is not None else value.get("width"))
        h = int(value.get("h") if value.get("h") is not None else value.get("height"))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}
