from __future__ import annotations

import hashlib
import re
from typing import Any


CONTRACT_VERSION = "read_region_batch_v1"
SCROLL_VERIFICATION_CONTRACT = "collection_scroll_verification_v1"


def verify_collection_scroll(
    *,
    before: list[Any],
    after: list[Any],
    dispatched: bool,
    reached_bottom: bool = False,
    wrong_scope_detected: bool = False,
) -> dict[str, Any]:
    before_fingerprints = _normalized_fingerprints(before)
    after_fingerprints = _normalized_fingerprints(after)
    before_set = set(before_fingerprints)
    new_fingerprints = [
        fingerprint
        for fingerprint in after_fingerprints
        if fingerprint not in before_set
    ]
    dispatch_success = bool(dispatched)
    scope_failed = bool(wrong_scope_detected)
    effect_success = bool(
        dispatch_success
        and not scope_failed
        and (new_fingerprints or reached_bottom)
    )
    if scope_failed:
        status = "wrong_scope_detected"
    elif not dispatch_success:
        status = "not_dispatched"
    elif reached_bottom:
        status = "reached_bottom"
    elif new_fingerprints:
        status = "new_content"
    else:
        status = "no_new_content"
    return {
        "contract_version": SCROLL_VERIFICATION_CONTRACT,
        "scroll_dispatch_success": dispatch_success,
        "scroll_effect_success": effect_success,
        "new_item_fingerprints": new_fingerprints,
        "new_item_count": len(new_fingerprints),
        "reached_bottom": bool(reached_bottom),
        "wrong_scope_detected": scope_failed,
        "should_stop": bool(scope_failed or reached_bottom),
        "status": status,
    }


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
    seen_item_fingerprints: set[str] = set()
    new_item_observations: list[dict[str, str]] = []
    normalized_capture_summaries: list[dict[str, Any]] = []
    consecutive_no_new_content = 0
    stop_reason = "max_captures"
    previous_item_fingerprints: list[str] = []
    aggregate_wrong_scope = bool(wrong_scope_detected)
    aggregate_blocked_surface = False

    for index, capture in enumerate(captures):
        lines = extract_ocr_text_lines(capture.get("ocr_result"))
        explicit_fingerprints = capture.get("item_fingerprints")
        item_fingerprints = _normalized_fingerprints(
            explicit_fingerprints
            if isinstance(explicit_fingerprints, list)
            else [normalized_line_hash(line) for line in lines]
        )
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
        capture_wrong_scope = bool(
            wrong_scope_detected or capture.get("wrong_scope_detected") is True
        )
        aggregate_wrong_scope = aggregate_wrong_scope or capture_wrong_scope
        capture_blocked_surface = bool(
            capture.get("blocked_surface_detected") is True
            or capture.get("blocked_surface") is True
        )
        aggregate_blocked_surface = aggregate_blocked_surface or capture_blocked_surface
        scroll_verification: dict[str, Any] | None = None
        new_item_fingerprints: list[str] = []
        if index > 0 or capture.get("scroll_dispatched") is not None:
            scroll_verification = verify_collection_scroll(
                before=previous_item_fingerprints,
                after=item_fingerprints,
                dispatched=bool(capture.get("scroll_dispatched")),
                reached_bottom=capture.get("reached_bottom") is True,
                wrong_scope_detected=capture_wrong_scope,
            )
            new_item_fingerprints = list(
                scroll_verification["new_item_fingerprints"]
            )
            capture_id = clean_text_line(capture.get("capture_id"))
            for fingerprint in new_item_fingerprints:
                if fingerprint in seen_item_fingerprints:
                    continue
                new_item_observations.append(
                    {
                        "capture_id": capture_id,
                        "fingerprint": fingerprint,
                    }
                )
        seen_item_fingerprints.update(item_fingerprints)
        has_new_content = bool(
            new_item_fingerprints
            if isinstance(explicit_fingerprints, list)
            else new_lines
        )
        if has_new_content:
            consecutive_no_new_content = 0
        elif index > 0:
            consecutive_no_new_content += 1
        normalized_capture_summaries.append(
            {
                "index": index,
                "capture_id": capture.get("capture_id"),
                "image_path": capture.get("image_path"),
                "trace_path": capture.get("trace_path"),
                "line_count": len(lines),
                "new_unique_line_count": len(new_lines),
                "new_unique_line_hashes": new_hashes,
                "item_fingerprint_count": len(item_fingerprints),
                "new_item_fingerprints": new_item_fingerprints,
                "scroll_trace_path": capture.get("scroll_trace_path"),
                "scroll_wheel_clicks": capture.get("scroll_wheel_clicks"),
                "scroll_effect_status": capture.get("scroll_effect_status"),
                "scroll_dispatch_success": (
                    scroll_verification.get("scroll_dispatch_success")
                    if scroll_verification is not None
                    else None
                ),
                "scroll_effect_success": (
                    scroll_verification.get("scroll_effect_success")
                    if scroll_verification is not None
                    else None
                ),
                "wrong_scope_detected": capture_wrong_scope,
                "blocked_surface_detected": capture_blocked_surface,
                "reached_bottom": capture.get("reached_bottom") is True,
            }
        )
        previous_item_fingerprints = item_fingerprints
        if capture_wrong_scope:
            stop_reason = "wrong_scope_detected"
            break
        if capture_blocked_surface:
            stop_reason = "blocked_surface"
            break
        if capture.get("reached_bottom") is True:
            stop_reason = "reached_bottom"
            break
        if consecutive_no_new_content >= max(1, int(stop_after_no_new_content)):
            stop_reason = "no_new_content"
            break

    if len(captures) < max_captures and stop_reason == "max_captures":
        stop_reason = "captures_exhausted"
    reached_bottom = stop_reason == "reached_bottom"
    read_state = {
        "captures_exhausted": "still_reading",
        "wrong_scope_detected": "wrong_surface",
    }.get(stop_reason, stop_reason)
    read_complete = read_state == "reached_bottom"
    if read_state in {"wrong_surface", "blocked_surface"}:
        completion_status = "blocked"
    elif read_complete:
        completion_status = "complete"
    else:
        completion_status = "incomplete"

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
        "item_fingerprint_count": len(seen_item_fingerprints),
        "new_item_observations": new_item_observations,
        "wrong_scope_detected": aggregate_wrong_scope,
        "blocked_surface_detected": aggregate_blocked_surface,
        "stop_reason": stop_reason,
        "read_state": read_state,
        "read_complete": read_complete,
        "read_terminal": read_state != "still_reading",
        "completion_status": completion_status,
        "reached_bottom": reached_bottom,
        "status": (
            "blocked_wrong_scope"
            if aggregate_wrong_scope
            else ("ok" if merged_lines or seen_item_fingerprints else "empty")
        ),
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


def _normalized_fingerprints(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        fingerprint = clean_text_line(value)
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        normalized.append(fingerprint)
    return normalized


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
