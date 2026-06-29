from __future__ import annotations

import hashlib
import json
from typing import Any

from app.operation.reading import extract_ocr_text_lines


DETAIL_SNAPSHOT_CONTRACT = "runtime_detail_snapshot_v1"


def with_detail_snapshot(detail: dict[str, Any], *, source: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(detail)
    previous_snapshot = previous.get("runtime_detail_snapshot") if isinstance(previous, dict) and isinstance(previous.get("runtime_detail_snapshot"), dict) else {}
    revision = int(previous_snapshot.get("revision") or 0) + 1
    payload["runtime_detail_snapshot"] = {
        "contract_version": DETAIL_SNAPSHOT_CONTRACT,
        "source": source,
        "revision": revision,
        "previous_snapshot_id": previous_snapshot.get("snapshot_id"),
        "snapshot_id": _snapshot_id(payload, revision=revision, source=source),
    }
    return payload


def merge_read_batch_into_detail_snapshot(
    detail: dict[str, Any],
    batch: dict[str, Any],
    *,
    section_role: str = "batch_ocr",
) -> dict[str, Any]:
    merged = dict(detail)
    lines = [str(item).strip() for item in batch.get("merged_text_lines") or [] if str(item or "").strip()]
    if not lines:
        for capture in batch.get("captures") or []:
            if isinstance(capture, dict):
                lines.extend(extract_ocr_text_lines(capture.get("ocr_result")))
    existing_sections = [item for item in merged.get("description_sections") or [] if isinstance(item, dict)]
    seen = {_section_key(item.get("text")) for item in existing_sections}
    next_index = len(existing_sections)
    for line in lines:
        key = _section_key(line)
        if not key or key in seen:
            continue
        seen.add(key)
        existing_sections.append({"index": next_index, "role": section_role, "text": line})
        next_index += 1
    merged["description_sections"] = existing_sections
    merged["trace_paths"] = _merge_unique(
        merged.get("trace_paths"),
        [
            item.get("trace_path")
            for item in batch.get("captures", [])
            if isinstance(item, dict) and item.get("trace_path")
        ],
    )
    merged["detail_batch_status"] = batch.get("status")
    merged["detail_batch_stop_reason"] = batch.get("stop_reason")
    merged["detail_bottom_reached"] = batch.get("stop_reason") == "no_new_content"
    merged["detail_batch_unique_line_count"] = batch.get("unique_line_count")
    merged["runtime_detail_dataflow"] = {
        "contract_version": "runtime_detail_dataflow_v1",
        "source_batch_contract": batch.get("contract_version"),
        "source_batch_status": batch.get("status"),
        "merged_text_line_count": len(lines),
        "description_section_count": len(existing_sections),
    }
    return with_detail_snapshot(merged, source="read_region_batch", previous=detail)


def put_latest_detail_snapshot(state: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    snapshot = detail.get("runtime_detail_snapshot") if isinstance(detail.get("runtime_detail_snapshot"), dict) else {}
    state["detail"] = detail
    state["latest_detail_snapshot"] = dict(snapshot)
    return detail


def require_latest_detail_snapshot(state: dict[str, Any], detail: dict[str, Any] | None) -> None:
    if not isinstance(detail, dict):
        raise ValueError("latest detail snapshot is missing")
    expected = state.get("latest_detail_snapshot") if isinstance(state.get("latest_detail_snapshot"), dict) else {}
    actual = detail.get("runtime_detail_snapshot") if isinstance(detail.get("runtime_detail_snapshot"), dict) else {}
    if not expected:
        return
    if expected.get("snapshot_id") != actual.get("snapshot_id"):
        raise ValueError(
            "stale detail snapshot: expected "
            f"{expected.get('snapshot_id')!r}, got {actual.get('snapshot_id')!r}"
        )


def _snapshot_id(detail: dict[str, Any], *, revision: int, source: str) -> str:
    payload = {
        "revision": revision,
        "source": source,
        "title": detail.get("title"),
        "company": detail.get("company"),
        "sections": [
            str(item.get("text") or "")
            for item in detail.get("description_sections") or []
            if isinstance(item, dict)
        ],
        "trace_paths": detail.get("trace_paths") if isinstance(detail.get("trace_paths"), list) else [],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _section_key(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _merge_unique(*values: Any) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            key = str(item)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged
