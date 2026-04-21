from __future__ import annotations

from typing import Any, Optional

from app.vision.region_standard import (
    bbox_from_any,
    build_content_key,
    build_layout_key,
    build_match_key,
    diagonal_from_bbox,
    normalize_string_list,
    normalized_diagonal_from_bbox,
)
from app.vision.schemas import BBox, ImageSize, VisionAnalyzeResponse, VisionObserver, VisionRegion, VisionTarget


class VisionResultNormalizer:
    def normalize(self, raw: dict[str, Any], provider_name: str, *, image_size: Optional[dict[str, int]] = None) -> VisionAnalyzeResponse:
        resolved_image_size = self._normalize_image_size(raw.get("image_size") or image_size or {})
        width = int(resolved_image_size.width if resolved_image_size is not None else 0)
        height = int(resolved_image_size.height if resolved_image_size is not None else 0)
        regions = [self._normalize_region(item, width=width, height=height) for item in raw.get("regions") or []]
        targets = [self._normalize_target(item, width=width, height=height) for item in raw.get("targets") or []]
        observers = [self._normalize_observer(item, width=width, height=height) for item in raw.get("observers") or []]
        regions = [item for item in regions if item is not None]
        targets = [item for item in targets if item is not None]
        observers = [item for item in observers if item is not None]
        if not regions:
            regions = self._derive_regions_from_targets(targets, width=width, height=height)
        return VisionAnalyzeResponse(
            provider=str(raw.get("provider") or provider_name),
            contract_version=str(raw.get("contract_version") or "vision_regions_v1"),
            image_size=resolved_image_size,
            screen_summary=str(raw.get("screen_summary") or ""),
            state_guess=raw.get("state_guess"),
            regions=regions,
            targets=targets,
            observers=observers,
            notes=[str(item) for item in (raw.get("notes") or []) if str(item).strip()],
            raw_text=raw.get("raw_text"),
            raw_response=raw,
        )

    def _normalize_image_size(self, raw: dict[str, Any]) -> Optional[ImageSize]:
        try:
            width = int(raw.get("width") or 0)
            height = int(raw.get("height") or 0)
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return ImageSize(width=width, height=height)

    def _normalize_region(self, raw: dict[str, Any], *, width: int, height: int) -> Optional[VisionRegion]:
        bbox = bbox_from_any(raw.get("bbox") or raw.get("diagonal") or {}, width=width, height=height)
        if bbox is None:
            return None
        diagonal = diagonal_from_bbox(bbox)
        normalized_diagonal = normalized_diagonal_from_bbox(bbox, width=width, height=height)
        text_lines = normalize_string_list(raw.get("text_lines") or [])
        possible_destinations = normalize_string_list(raw.get("possible_destinations") or raw.get("destinations") or [])
        ocr_text = str(raw.get("ocr_text") or " ".join(text_lines)).strip()
        description = str(raw.get("description") or raw.get("summary") or raw.get("label") or "").strip()
        role = str(raw.get("role") or raw.get("kind") or "other").strip() or "other"
        label = str(raw.get("label") or raw.get("name") or role).strip() or role
        layout_key = build_layout_key(role, normalized_diagonal)
        content_key = build_content_key(
            label=label,
            description=description,
            ocr_text=ocr_text,
            text_lines=text_lines,
            possible_destinations=possible_destinations,
        )
        return VisionRegion(
            region_id=str(raw.get("region_id") or raw.get("id") or label),
            label=label,
            role=role,
            bbox=bbox,
            diagonal=diagonal,
            normalized_diagonal=normalized_diagonal,
            description=description,
            ocr_text=ocr_text,
            text_lines=text_lines,
            possible_destinations=possible_destinations,
            confidence=float(raw.get("confidence") or 0.0),
            layout_key=layout_key,
            content_key=content_key,
            match_key=build_match_key(layout_key, content_key),
        )

    def _normalize_target(self, raw: dict[str, Any], *, width: int, height: int) -> Optional[VisionTarget]:
        bbox = self._normalize_bbox(raw.get("bbox") or raw.get("diagonal") or {}, width=width, height=height)
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
        bbox = self._normalize_bbox(raw.get("bbox") or raw.get("diagonal") or {}, width=width, height=height)
        if bbox is None:
            return None
        return VisionObserver(
            observer_id=str(raw.get("observer_id") or raw.get("id") or "observer"),
            label=str(raw.get("label") or raw.get("name") or "observer"),
            bbox=bbox,
            kind=str(raw.get("kind") or "unknown"),
            observable_confidence=float(raw.get("observable_confidence") or raw.get("confidence") or 0.0),
        )

    def _derive_regions_from_targets(self, targets: list[VisionTarget], *, width: int, height: int) -> list[VisionRegion]:
        regions: list[VisionRegion] = []
        for target in targets:
            diagonal = diagonal_from_bbox(target.bbox)
            normalized_diagonal = normalized_diagonal_from_bbox(target.bbox, width=width, height=height)
            text_lines = normalize_string_list([target.label])
            layout_key = build_layout_key(target.kind, normalized_diagonal)
            content_key = build_content_key(
                label=target.label,
                description=target.expected_effect or target.label,
                ocr_text=target.label,
                text_lines=text_lines,
                possible_destinations=[target.expected_effect] if target.expected_effect else [],
            )
            regions.append(
                VisionRegion(
                    region_id=target.target_id,
                    label=target.label,
                    role=target.kind,
                    bbox=target.bbox,
                    diagonal=diagonal,
                    normalized_diagonal=normalized_diagonal,
                    description=str(target.expected_effect or target.label),
                    ocr_text=target.label,
                    text_lines=text_lines,
                    possible_destinations=normalize_string_list([target.expected_effect] if target.expected_effect else []),
                    confidence=float(target.clickable_confidence),
                    layout_key=layout_key,
                    content_key=content_key,
                    match_key=build_match_key(layout_key, content_key),
                )
            )
        return regions

    def _normalize_bbox(self, raw: dict[str, Any], *, width: int, height: int) -> Optional[BBox]:
        return bbox_from_any(raw, width=width, height=height)


normalizer = VisionResultNormalizer()
