from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Optional

from app.vision.schemas import BBox, Diagonal, NormalizedDiagonal


def _hash_text(value: str, *, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _normalize_space(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return normalized


def normalize_string_list(values: Iterable[Any]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def clamp_bbox(bbox: BBox, *, width: int, height: int) -> Optional[BBox]:
    x = int(bbox.x)
    y = int(bbox.y)
    w = int(bbox.w)
    h = int(bbox.h)
    if w <= 0 or h <= 0:
        return None
    if width > 0:
        x = max(0, min(x, width - 1))
        w = max(1, min(w, max(1, width - x)))
    if height > 0:
        y = max(0, min(y, height - 1))
        h = max(1, min(h, max(1, height - y)))
    return BBox(x=x, y=y, w=w, h=h)


def bbox_from_any(raw: Any, *, width: int, height: int) -> Optional[BBox]:
    if not isinstance(raw, dict):
        return None
    if {"x", "y"} <= set(raw.keys()) and ("w" in raw or "width" in raw) and ("h" in raw or "height" in raw):
        try:
            bbox = BBox(
                x=int(raw.get("x", 0)),
                y=int(raw.get("y", 0)),
                w=int(raw.get("w", raw.get("width", 0))),
                h=int(raw.get("h", raw.get("height", 0))),
            )
        except Exception:
            return None
        return clamp_bbox(bbox, width=width, height=height)

    if {"x1", "y1", "x2", "y2"} <= set(raw.keys()):
        try:
            x1 = int(raw.get("x1", 0))
            y1 = int(raw.get("y1", 0))
            x2 = int(raw.get("x2", 0))
            y2 = int(raw.get("y2", 0))
        except Exception:
            return None
        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        return clamp_bbox(BBox(x=x, y=y, w=w, h=h), width=width, height=height)

    return None


def diagonal_from_bbox(bbox: BBox) -> Diagonal:
    return Diagonal(
        x1=int(bbox.x),
        y1=int(bbox.y),
        x2=int(bbox.x + bbox.w),
        y2=int(bbox.y + bbox.h),
    )


def normalized_diagonal_from_bbox(bbox: BBox, *, width: int, height: int) -> NormalizedDiagonal:
    safe_width = max(1, int(width))
    safe_height = max(1, int(height))
    diagonal = diagonal_from_bbox(bbox)
    return NormalizedDiagonal(
        nx1=round(diagonal.x1 / safe_width, 4),
        ny1=round(diagonal.y1 / safe_height, 4),
        nx2=round(diagonal.x2 / safe_width, 4),
        ny2=round(diagonal.y2 / safe_height, 4),
    )


def build_layout_key(role: str, normalized_diagonal: NormalizedDiagonal) -> str:
    source = "|".join(
        [
            _normalize_space(role),
            f"{normalized_diagonal.nx1:.4f}",
            f"{normalized_diagonal.ny1:.4f}",
            f"{normalized_diagonal.nx2:.4f}",
            f"{normalized_diagonal.ny2:.4f}",
        ]
    )
    return _hash_text(source)


def build_content_key(
    *,
    label: str,
    description: str,
    ocr_text: str,
    text_lines: Iterable[str],
    possible_destinations: Iterable[str],
) -> str:
    parts = [
        _normalize_space(label),
        _normalize_space(description),
        _normalize_space(ocr_text),
        "||".join(_normalize_space(item) for item in normalize_string_list(text_lines)),
        "||".join(_normalize_space(item) for item in normalize_string_list(possible_destinations)),
    ]
    return _hash_text("|".join(parts))


def build_match_key(layout_key: str, content_key: str) -> str:
    return f"{layout_key}:{content_key}"
