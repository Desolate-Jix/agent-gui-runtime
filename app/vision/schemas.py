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
    targets: list[VisionTarget] = field(default_factory=list)
    observers: list[VisionObserver] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_text: Optional[str] = None
    raw_response: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "screen_summary": self.screen_summary,
            "state_guess": self.state_guess,
            "targets": [item.to_dict() for item in self.targets],
            "observers": [item.to_dict() for item in self.observers],
            "notes": list(self.notes),
            "raw_text": self.raw_text,
            "raw_response": self.raw_response,
        }
