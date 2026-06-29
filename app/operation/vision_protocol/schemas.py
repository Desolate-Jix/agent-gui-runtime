from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    point_strategy: str
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "label": self.label,
            "bbox": self.bbox.to_dict(),
            "point_strategy": self.point_strategy,
            "priority": int(self.priority),
        }


@dataclass
class VisionValidator:
    type: str
    observer_id: str
    roi: BBox
    expected_change: str
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "observer_id": self.observer_id,
            "roi": self.roi.to_dict(),
            "expected_change": self.expected_change,
            "threshold": float(self.threshold),
        }


@dataclass
class VisionAction:
    action_id: str
    action_type: str
    target: VisionTarget
    validator: VisionValidator
    expected_effect: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target": self.target.to_dict(),
            "validator": self.validator.to_dict(),
            "expected_effect": self.expected_effect,
            "confidence": float(self.confidence),
        }


@dataclass
class VisionState:
    state_id: str
    screen_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "screen_summary": self.screen_summary,
        }


@dataclass
class VisionResponse:
    state: VisionState
    actions: list[VisionAction] = field(default_factory=list)
    observers: list[Any] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.to_dict(),
            "actions": [item.to_dict() for item in self.actions],
            "observers": self.observers,
            "meta": self.meta,
        }
