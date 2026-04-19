from __future__ import annotations

from typing import Any, Optional

from app.vision.schemas import BBox, VisionAnalyzeResponse, VisionObserver, VisionTarget


class VisionResultNormalizer:
    def normalize(self, raw: dict[str, Any], provider_name: str, *, image_size: Optional[dict[str, int]] = None) -> VisionAnalyzeResponse:
        width = int((image_size or {}).get("width") or 0)
        height = int((image_size or {}).get("height") or 0)
        targets = [self._normalize_target(item, width=width, height=height) for item in raw.get("targets") or []]
        observers = [self._normalize_observer(item, width=width, height=height) for item in raw.get("observers") or []]
        targets = [item for item in targets if item is not None]
        observers = [item for item in observers if item is not None]
        return VisionAnalyzeResponse(
            provider=str(raw.get("provider") or provider_name),
            screen_summary=str(raw.get("screen_summary") or ""),
            state_guess=raw.get("state_guess"),
            targets=targets,
            observers=observers,
            notes=[str(item) for item in (raw.get("notes") or []) if str(item).strip()],
            raw_text=raw.get("raw_text"),
            raw_response=raw,
        )

    def _normalize_target(self, raw: dict[str, Any], *, width: int, height: int) -> Optional[VisionTarget]:
        bbox = self._normalize_bbox(raw.get("bbox") or {}, width=width, height=height)
        if bbox is None:
            return None
        return VisionTarget(
            target_id=str(raw.get("target_id") or raw.get("id") or "target"),
            label=str(raw.get("label") or raw.get("name") or "target"),
            bbox=bbox,
            kind=str(raw.get("kind") or "unknown"),
            clickable_confidence=float(raw.get("clickable_confidence") or raw.get("confidence") or 0.0),
            expected_effect=raw.get("expected_effect"),
        )

    def _normalize_observer(self, raw: dict[str, Any], *, width: int, height: int) -> Optional[VisionObserver]:
        bbox = self._normalize_bbox(raw.get("bbox") or {}, width=width, height=height)
        if bbox is None:
            return None
        return VisionObserver(
            observer_id=str(raw.get("observer_id") or raw.get("id") or "observer"),
            label=str(raw.get("label") or raw.get("name") or "observer"),
            bbox=bbox,
            kind=str(raw.get("kind") or "unknown"),
            observable_confidence=float(raw.get("observable_confidence") or raw.get("confidence") or 0.0),
        )

    def _normalize_bbox(self, raw: dict[str, Any], *, width: int, height: int) -> Optional[BBox]:
        try:
            x = int(raw.get("x", 0))
            y = int(raw.get("y", 0))
            w = int(raw.get("w", raw.get("width", 0)))
            h = int(raw.get("h", raw.get("height", 0)))
        except Exception:
            return None
        if w <= 0 or h <= 0:
            return None
        if width > 0:
            x = max(0, min(x, width - 1))
            w = max(1, min(w, max(1, width - x)))
        if height > 0:
            y = max(0, min(y, height - 1))
            h = max(1, min(h, max(1, height - y)))
        return BBox(x=x, y=y, w=w, h=h)


normalizer = VisionResultNormalizer()
