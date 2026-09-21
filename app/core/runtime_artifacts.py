from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional


LOGS_DIR = Path("logs")
TRACES_DIR = LOGS_DIR / "traces"
ARTIFACTS_DIR = Path("artifacts")
SCREENSHOTS_DIR = ARTIFACTS_DIR / "screenshots"
VERIFICATION_DIR = ARTIFACTS_DIR / "verification"
REVIEW_OVERLAYS_DIR = ARTIFACTS_DIR / "review-overlays"
RECOGNITION_CROPS_DIR = ARTIFACTS_DIR / "recognition-crops"
LOCAL_LEARNING_DIR = ARTIFACTS_DIR / "local-learning"
LEARNED_INSTRUCTION_ARTIFACTS_DIR = LOCAL_LEARNING_DIR / "instructions"
TRACE_MAX_PAYLOAD_BYTES = int(os.environ.get("OPENCLAW_TRACE_MAX_PAYLOAD_BYTES", str(20 * 1024 * 1024)))
TRACE_MAX_STRING_CHARS = int(os.environ.get("OPENCLAW_TRACE_MAX_STRING_CHARS", "20000"))
TRACE_MAX_LIST_ITEMS = int(os.environ.get("OPENCLAW_TRACE_MAX_LIST_ITEMS", "200"))
TRACE_MAX_DEPTH = int(os.environ.get("OPENCLAW_TRACE_MAX_DEPTH", "12"))
TRACE_COMPACT_LIST_KEYS = {"scroll_history", "previous_scrolls", "history", "attempts"}
TRACE_BINARY_TEXT_KEYS = {"image_base64", "base64", "image_bytes", "bytes", "png", "jpg", "jpeg"}

_runtime_output_root: ContextVar[Path | None] = ContextVar("runtime_output_root", default=None)


def _validated_relative_path(relative_path: str | Path) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.anchor or any(part == ".." for part in candidate.parts):
        raise ValueError("relative_path must be a relative path without '..'")
    return candidate


@contextmanager
def pinned_runtime_output_root(root: Path) -> Iterator[Path]:
    """为单次操作绑定绝对输出根目录，进入时不创建目录。"""
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError("root must be an absolute Path")
    token = _runtime_output_root.set(root)
    try:
        yield root
    finally:
        _runtime_output_root.reset(token)


def runtime_output_directory(relative_path: str | Path, *, legacy_path: Path | None = None, create: bool = False) -> Path:
    """从操作范围或兼容旧路径解析输出目录。"""
    relative = _validated_relative_path(relative_path)
    root = _runtime_output_root.get()
    directory = root / relative if root is not None else (legacy_path if legacy_path is not None else relative)
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory

def slugify(value: Optional[str], *, fallback: str = "item", max_length: int = 80) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if text:
        return _limit_slug(text, source=value or "", max_length=max_length)

    source = (value or "").strip()
    if source:
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
        return _limit_slug(f"{fallback}-{digest}", source=source, max_length=max_length)
    return _limit_slug(fallback, source=fallback, max_length=max_length)


def _limit_slug(slug: str, *, source: str, max_length: int) -> str:
    if max_length <= 0 or len(slug) <= max_length:
        return slug
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
    prefix_length = max(1, max_length - len(digest) - 1)
    return f"{slug[:prefix_length].rstrip('-')}-{digest}"


def timestamp_label() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def window_label(*, title: Optional[str], process_name: Optional[str], handle: Optional[int]) -> str:
    preferred = slugify(title, fallback="")
    if preferred:
        return preferred
    process_slug = slugify(process_name, fallback="")
    if process_slug:
        return process_slug
    if handle is not None:
        return f"window-{int(handle)}"
    return "window"


def roi_label(roi: Optional[dict[str, Any]]) -> str:
    if not roi:
        return "full-window"
    return "roi-x{0}-y{1}-w{2}-h{3}".format(
        int(roi.get("x", 0)),
        int(roi.get("y", 0)),
        int(roi.get("width", 0)),
        int(roi.get("height", 0)),
    )


def build_screenshot_path(
    *,
    title: Optional[str],
    process_name: Optional[str],
    handle: Optional[int],
    purpose: str,
    roi: Optional[dict[str, Any]],
    name_hint: Optional[str] = None,
) -> Path:
    parts = [
        window_label(title=title, process_name=process_name, handle=handle),
        slugify(purpose, fallback="capture"),
    ]
    if name_hint:
        parts.append(slugify(name_hint, fallback="target"))
    parts.append(roi_label(roi))
    parts.append(timestamp_label())
    return runtime_output_directory("artifacts/screenshots", legacy_path=SCREENSHOTS_DIR, create=True) / ("__".join(parts) + ".png")


def build_verification_image_path(*, action_name: str, suffix: str = "diff") -> Path:
    name = "__".join([slugify(action_name, fallback="action"), slugify(suffix, fallback="artifact"), timestamp_label()])
    return runtime_output_directory("artifacts/verification", legacy_path=VERIFICATION_DIR, create=True) / f"{name}.png"


def build_review_overlay_path(*, name_hint: Optional[str] = None, suffix: str = "review-overlay") -> Path:
    parts = [slugify(name_hint, fallback="trace"), slugify(suffix, fallback="overlay"), timestamp_label()]
    return runtime_output_directory("artifacts/review-overlays", legacy_path=REVIEW_OVERLAYS_DIR, create=True) / ("__".join(parts) + ".png")


def build_recognition_crop_path(*, name_hint: Optional[str] = None, candidate_id: Optional[str] = None) -> Path:
    parts = [slugify(name_hint, fallback="recognition"), slugify(candidate_id, fallback="candidate"), timestamp_label()]
    return runtime_output_directory("artifacts/recognition-crops", legacy_path=RECOGNITION_CROPS_DIR, create=True) / ("__".join(parts) + ".png")


def new_learned_instruction_id() -> str:
    return uuid.uuid4().hex


def learned_instruction_bundle_dir(learned_instruction_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "", learned_instruction_id)
    if not safe_id:
        raise ValueError("learned_instruction_id is empty or invalid")
    return runtime_output_directory("artifacts/local-learning/instructions", legacy_path=LEARNED_INSTRUCTION_ARTIFACTS_DIR, create=True) / safe_id


def learned_instruction_record_path(learned_instruction_id: str) -> Path:
    return learned_instruction_bundle_dir(learned_instruction_id) / "learned_instruction.json"


def write_trace(*, category: str, operation: str, payload: dict[str, Any], name_hint: Optional[str] = None) -> str:
    category_dir = runtime_output_directory("logs/traces", legacy_path=TRACES_DIR, create=True) / slugify(category, fallback="general")
    category_dir.mkdir(parents=True, exist_ok=True)
    parts = [timestamp_label(), slugify(operation, fallback="operation")]
    if name_hint:
        parts.append(slugify(name_hint, fallback="target"))
    path = category_dir / ("__".join(parts) + ".json")
    payload_to_write = _bounded_trace_payload(payload)
    path.write_text(json.dumps(payload_to_write, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def _bounded_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_trace_value(payload)
    encoded = json.dumps(sanitized, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) <= TRACE_MAX_PAYLOAD_BYTES:
        return sanitized
    summary = _summarize_trace_mapping(payload)
    summary["trace_truncated"] = True
    summary["trace_truncation"] = {
        "reason": "trace_payload_exceeded_byte_budget",
        "max_payload_bytes": TRACE_MAX_PAYLOAD_BYTES,
        "sanitized_payload_bytes": len(encoded),
        "policy": "large trace payloads are summarized to avoid embedding recursive history, screenshots, or model dumps",
    }
    return summary


def _sanitize_trace_value(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    if depth > TRACE_MAX_DEPTH:
        return _trace_summary(value, reason="max_depth_exceeded")
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for item_key, item_value in value.items():
            key_text = str(item_key)
            if key_text.lower() in TRACE_BINARY_TEXT_KEYS:
                sanitized[key_text] = _trace_summary(item_value, reason="binary_or_base64_payload_omitted")
                continue
            sanitized[key_text] = _sanitize_trace_value(item_value, key=key_text, depth=depth + 1)
        return sanitized
    if isinstance(value, list):
        limit = 20 if key in TRACE_COMPACT_LIST_KEYS else TRACE_MAX_LIST_ITEMS
        items = [_sanitize_trace_value(item, depth=depth + 1) for item in value[:limit]]
        omitted = len(value) - len(items)
        if omitted > 0:
            items.append({"trace_truncated": True, "omitted_items": omitted, "reason": "list_item_limit"})
        return items
    if isinstance(value, tuple):
        return _sanitize_trace_value(list(value), key=key, depth=depth)
    if isinstance(value, str):
        if len(value) <= TRACE_MAX_STRING_CHARS:
            return value
        digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]
        return {
            "trace_truncated": True,
            "reason": "string_char_limit",
            "original_chars": len(value),
            "sha256_prefix": digest,
            "preview": value[:TRACE_MAX_STRING_CHARS],
        }
    return value


def _summarize_trace_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "bounded_trace_summary_v1",
        "success": payload.get("success") if isinstance(payload, dict) else None,
        "top_level_keys": list(payload.keys()) if isinstance(payload, dict) else [],
        "request": _trace_summary(payload.get("request")) if isinstance(payload, dict) else None,
        "result": _trace_summary(payload.get("result")) if isinstance(payload, dict) else None,
        "error": _sanitize_trace_value(payload.get("error")) if isinstance(payload, dict) else None,
    }


def _trace_summary(value: Any, *, reason: str | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "trace_summary": True,
        "type": type(value).__name__,
    }
    if reason:
        summary["reason"] = reason
    if isinstance(value, dict):
        summary["keys"] = list(value.keys())[:80]
        summary["key_count"] = len(value)
        for path_key in ("trace_path", "image_path", "before_image_path", "after_image_path"):
            if isinstance(value.get(path_key), str):
                summary[path_key] = value[path_key]
    elif isinstance(value, (list, tuple)):
        summary["item_count"] = len(value)
    elif isinstance(value, str):
        summary["chars"] = len(value)
        summary["sha256_prefix"] = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]
        summary["preview"] = value[: min(500, len(value))]
    elif value is None:
        summary["value"] = None
    else:
        summary["repr"] = repr(value)[:500]
    return summary


class RuntimeTimer:
    """Collect lightweight stage timings for API responses and traces."""

    def __init__(self, *, contract_version: str = "runtime_timing_v1") -> None:
        self.contract_version = contract_version
        self.started_at = datetime.now().isoformat()
        self._started_perf = time.perf_counter()
        self.steps: list[dict[str, Any]] = []

    @contextmanager
    def step(self, name: str, **metadata: Any) -> Iterator[None]:
        started_at = datetime.now().isoformat()
        started_perf = time.perf_counter()
        step: dict[str, Any] = {
            "name": name,
            "started_at": started_at,
        }
        for key, value in metadata.items():
            if value is not None:
                step[key] = value
        self.steps.append(step)
        try:
            yield
        finally:
            ended_at = datetime.now().isoformat()
            elapsed_ms = (time.perf_counter() - started_perf) * 1000
            step["ended_at"] = ended_at
            step["elapsed_ms"] = round(elapsed_ms, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "started_at": self.started_at,
            "ended_at": datetime.now().isoformat(),
            "total_ms": round((time.perf_counter() - self._started_perf) * 1000, 3),
            "steps": list(self.steps),
        }
