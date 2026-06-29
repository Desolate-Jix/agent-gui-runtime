from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.vision.schemas import BBox, ImageSize


@dataclass
class VerificationHints:
    expected_changes: list[str] = field(default_factory=list)
    target_scope: str = "local"

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_changes": list(self.expected_changes),
            "target_scope": self.target_scope,
        }


@dataclass
class InteractionPolicy:
    allowed: bool = True
    zone_type: str = "general_action"
    priority: str = "normal"
    ad_risk: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": bool(self.allowed),
            "zone_type": self.zone_type,
            "priority": self.priority,
            "ad_risk": float(self.ad_risk),
            "reasons": list(self.reasons),
        }


@dataclass
class PageText:
    text_id: str
    text: str
    bbox: BBox
    score: float
    source: str
    source_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "text_id": self.text_id,
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "score": float(self.score),
            "source": self.source,
            "source_index": int(self.source_index),
        }


@dataclass
class PageLink:
    link_id: str
    relation: str
    region_id: Optional[str] = None
    element_id: Optional[str] = None
    text_ids: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "relation": self.relation,
            "region_id": self.region_id,
            "element_id": self.element_id,
            "text_ids": list(self.text_ids),
            "score": float(self.score),
            "reasons": list(self.reasons),
        }


@dataclass
class PageElement:
    element_id: str
    label: str
    role: str
    interaction_type: str
    description: str
    text: str
    bbox: BBox
    semantic_bbox: Optional[BBox]
    click_point: dict[str, int]
    click_strategy: str
    possible_destinations: list[str]
    verification_hints: VerificationHints
    interaction_policy: InteractionPolicy
    fusion_confidence: float
    coordinate_confidence: str
    memory_key: str
    sources: list[str]
    source_region_ids: list[str] = field(default_factory=list)
    source_text_ids: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "label": self.label,
            "role": self.role,
            "interaction_type": self.interaction_type,
            "description": self.description,
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "semantic_bbox": self.semantic_bbox.to_dict() if self.semantic_bbox is not None else None,
            "click_point": dict(self.click_point),
            "click_strategy": self.click_strategy,
            "possible_destinations": list(self.possible_destinations),
            "verification_hints": self.verification_hints.to_dict(),
            "interaction_policy": self.interaction_policy.to_dict(),
            "fusion_confidence": float(self.fusion_confidence),
            "coordinate_confidence": self.coordinate_confidence,
            "memory_key": self.memory_key,
            "sources": list(self.sources),
            "source_region_ids": list(self.source_region_ids),
            "source_text_ids": list(self.source_text_ids),
            "evidence": dict(self.evidence),
        }


@dataclass
class PageStructure:
    image_size: Optional[ImageSize]
    screen_summary: str
    state_guess: Optional[str]
    regions: list[dict[str, Any]] = field(default_factory=list)
    elements: list[PageElement] = field(default_factory=list)
    texts: list[PageText] = field(default_factory=list)
    links: list[PageLink] = field(default_factory=list)
    learning_summary: dict[str, Any] = field(default_factory=dict)
    raw_ocr: dict[str, Any] = field(default_factory=dict)
    raw_vision_regions: list[dict[str, Any]] = field(default_factory=list)
    contract_version: str = "page_structure_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "image_size": self.image_size.to_dict() if self.image_size is not None else None,
            "screen_summary": self.screen_summary,
            "state_guess": self.state_guess,
            "regions": list(self.regions),
            "elements": [item.to_dict() for item in self.elements],
            "texts": [item.to_dict() for item in self.texts],
            "links": [item.to_dict() for item in self.links],
            "learning_summary": dict(self.learning_summary),
            "raw_ocr": dict(self.raw_ocr),
            "raw_vision_regions": list(self.raw_vision_regions),
        }
