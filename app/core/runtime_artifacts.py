from __future__ import annotations

import hashlib
import json
import re
import time
from contextlib import contextmanager
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

for path in (LOGS_DIR, TRACES_DIR, ARTIFACTS_DIR, SCREENSHOTS_DIR, VERIFICATION_DIR, REVIEW_OVERLAYS_DIR, RECOGNITION_CROPS_DIR):
    path.mkdir(parents=True, exist_ok=True)


def slugify(value: Optional[str], *, fallback: str = "item") -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if text:
        return text

    source = (value or "").strip()
    if source:
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
        return f"{fallback}-{digest}"
    return fallback


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
    return SCREENSHOTS_DIR / ("__".join(parts) + ".png")


def build_verification_image_path(*, action_name: str, suffix: str = "diff") -> Path:
    name = "__".join([slugify(action_name, fallback="action"), slugify(suffix, fallback="artifact"), timestamp_label()])
    return VERIFICATION_DIR / f"{name}.png"


def build_review_overlay_path(*, name_hint: Optional[str] = None, suffix: str = "review-overlay") -> Path:
    parts = [slugify(name_hint, fallback="trace"), slugify(suffix, fallback="overlay"), timestamp_label()]
    return REVIEW_OVERLAYS_DIR / ("__".join(parts) + ".png")


def build_recognition_crop_path(*, name_hint: Optional[str] = None, candidate_id: Optional[str] = None) -> Path:
    parts = [slugify(name_hint, fallback="recognition"), slugify(candidate_id, fallback="candidate"), timestamp_label()]
    return RECOGNITION_CROPS_DIR / ("__".join(parts) + ".png")


def write_trace(*, category: str, operation: str, payload: dict[str, Any], name_hint: Optional[str] = None) -> str:
    category_dir = TRACES_DIR / slugify(category, fallback="general")
    category_dir.mkdir(parents=True, exist_ok=True)
    parts = [timestamp_label(), slugify(operation, fallback="operation")]
    if name_hint:
        parts.append(slugify(name_hint, fallback="target"))
    path = category_dir / ("__".join(parts) + ".json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


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
