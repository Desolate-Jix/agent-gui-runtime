from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BBox:
    x: int
    y: int
    w: int
    h: int

    def to_dict(self) -> dict[str, int]:
        return {"x": int(self.x), "y": int(self.y), "w": int(self.w), "h": int(self.h)}


@dataclass
class ImageSize:
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {"width": int(self.width), "height": int(self.height)}


@dataclass
class Diagonal:
    x1: int
    y1: int
    x2: int
    y2: int

    def to_dict(self) -> dict[str, int]:
        return {
            "x1": int(self.x1),
            "y1": int(self.y1),
            "x2": int(self.x2),
            "y2": int(self.y2),
        }


@dataclass
class NormalizedDiagonal:
    nx1: float
    ny1: float
    nx2: float
    ny2: float

    def to_dict(self) -> dict[str, float]:
        return {
            "nx1": float(self.nx1),
            "ny1": float(self.ny1),
            "nx2": float(self.nx2),
            "ny2": float(self.ny2),
        }


@dataclass
class VisionRegion:
    region_id: str
    label: str
    role: str
    bbox: BBox
    diagonal: Diagonal
    normalized_diagonal: NormalizedDiagonal
    description: str
    ocr_text: str = ""
    text_lines: list[str] = field(default_factory=list)
    possible_destinations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    layout_key: str = ""
    content_key: str = ""
    match_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "label": self.label,
            "role": self.role,
            "bbox": self.bbox.to_dict(),
            "diagonal": self.diagonal.to_dict(),
            "normalized_diagonal": self.normalized_diagonal.to_dict(),
            "description": self.description,
            "ocr_text": self.ocr_text,
            "text_lines": list(self.text_lines),
            "possible_destinations": list(self.possible_destinations),
            "confidence": float(self.confidence),
            "layout_key": self.layout_key,
            "content_key": self.content_key,
            "match_key": self.match_key,
        }


@dataclass
class VisionTarget:
    target_id: str
    label: str
    bbox: BBox
    kind: str
    clickable_confidence: float
    expected_effect: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "label": self.label,
            "bbox": self.bbox.to_dict(),
            "kind": self.kind,
            "clickable_confidence": float(self.clickable_confidence),
            "expected_effect": self.expected_effect,
        }


@dataclass
class VisionObserver:
    observer_id: str
    label: str
    bbox: BBox
    kind: str
    observable_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "observer_id": self.observer_id,
            "label": self.label,
            "bbox": self.bbox.to_dict(),
            "kind": self.kind,
            "observable_confidence": float(self.observable_confidence),
        }


@dataclass
class VisionAnalyzeRequest:
    image_path: str
    task: str = "analyze_ui"
    app_name: Optional[str] = None
    goal: Optional[str] = None
    state_hint: Optional[str] = None
    provider_mode: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VisionAnalyzeResponse:
    provider: str
    screen_summary: str
    state_guess: Optional[str]
    contract_version: str = "vision_regions_v1"
    image_size: Optional[ImageSize] = None
    regions: list[VisionRegion] = field(default_factory=list)
    targets: list[VisionTarget] = field(default_factory=list)
    observers: list[VisionObserver] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    raw_text: Optional[str] = None
    raw_response: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "contract_version": self.contract_version,
            "image_size": self.image_size.to_dict() if self.image_size is not None else None,
            "screen_summary": self.screen_summary,
            "state_guess": self.state_guess,
            "regions": [item.to_dict() for item in self.regions],
            "targets": [item.to_dict() for item in self.targets],
            "observers": [item.to_dict() for item in self.observers],
            "notes": list(self.notes),
            "artifacts": dict(self.artifacts),
            "raw_text": self.raw_text,
            "raw_response": self.raw_response,
        }
