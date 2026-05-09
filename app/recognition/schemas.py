from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.page_structure.schemas import PageElement, PageStructure
from modules.ocr.contracts import OCRResult


@dataclass
class CandidateRankRequest:
    goal: str
    page_structure: PageStructure
    top_k: int = 5
    state_hint: str | None = None


@dataclass
class ScoreBreakdown:
    text_similarity: float = 0.0
    role_score: float = 0.0
    policy_score: float = 0.0
    confidence_score: float = 0.0
    state_score: float = 0.0
    ad_penalty: float = 0.0
    blocked_penalty: float = 0.0

    def total(self) -> float:
        value = (
            (self.text_similarity * 0.38)
            + (self.role_score * 0.16)
            + (self.policy_score * 0.18)
            + (self.confidence_score * 0.14)
            + (self.state_score * 0.08)
            - (self.ad_penalty * 0.18)
            - (self.blocked_penalty * 0.35)
        )
        return round(max(0.0, min(1.0, value)), 4)

    def to_dict(self) -> dict[str, float]:
        return {
            "text_similarity": round(float(self.text_similarity), 4),
            "role_score": round(float(self.role_score), 4),
            "policy_score": round(float(self.policy_score), 4),
            "confidence_score": round(float(self.confidence_score), 4),
            "state_score": round(float(self.state_score), 4),
            "ad_penalty": round(float(self.ad_penalty), 4),
            "blocked_penalty": round(float(self.blocked_penalty), 4),
            "total": self.total(),
        }


@dataclass
class RecognitionCandidate:
    candidate_id: str
    rank: int
    element_id: str
    label: str
    role: str
    text: str
    score: float
    eligible: bool
    reasons: list[str]
    score_breakdown: ScoreBreakdown
    element: PageElement
    refined_bbox: dict[str, int] | None = None
    bbox_refine_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "rank": int(self.rank),
            "element_id": self.element_id,
            "label": self.label,
            "role": self.role,
            "text": self.text,
            "score": round(float(self.score), 4),
            "eligible": bool(self.eligible),
            "reasons": list(self.reasons),
            "score_breakdown": self.score_breakdown.to_dict(),
            "element": self.element.to_dict(),
            "refined_bbox": dict(self.refined_bbox) if self.refined_bbox is not None else None,
            "bbox_refine_reason": self.bbox_refine_reason,
        }


@dataclass
class CandidateRankResult:
    contract_version: str = "candidate_rank_v1"
    goal: str = ""
    top_k: int = 5
    candidates: list[RecognitionCandidate] = field(default_factory=list)
    rejected: list[RecognitionCandidate] = field(default_factory=list)
    recommended_candidate_id: str | None = None
    margin_to_second: float | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "goal": self.goal,
            "top_k": int(self.top_k),
            "candidates": [item.to_dict() for item in self.candidates],
            "rejected": [item.to_dict() for item in self.rejected],
            "recommended_candidate_id": self.recommended_candidate_id,
            "margin_to_second": self.margin_to_second,
            "summary": dict(self.summary),
        }


@dataclass
class LocalGroundingRequest:
    image_path: str
    goal: str
    candidates: list[RecognitionCandidate]
    ocr_scan: Callable[[str], OCRResult]
    app_name: str | None = None
    crop_padding: int = 24


@dataclass
class LocalGroundingCandidateResult:
    candidate_id: str
    element_id: str
    status: str
    crop_path: str | None
    crop_bbox: dict[str, int] | None
    refined_click_point: dict[str, int] | None
    coordinate_source: str
    confidence: float
    matched_text: str | None
    matched_text_bbox: dict[str, int] | None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "element_id": self.element_id,
            "status": self.status,
            "crop_path": self.crop_path,
            "crop_bbox": dict(self.crop_bbox) if self.crop_bbox is not None else None,
            "refined_click_point": dict(self.refined_click_point) if self.refined_click_point is not None else None,
            "coordinate_source": self.coordinate_source,
            "confidence": round(float(self.confidence), 4),
            "matched_text": self.matched_text,
            "matched_text_bbox": dict(self.matched_text_bbox) if self.matched_text_bbox is not None else None,
            "reasons": list(self.reasons),
        }


@dataclass
class LocalGroundingResult:
    contract_version: str = "narrow_search_v1"
    goal: str = ""
    results: list[LocalGroundingCandidateResult] = field(default_factory=list)
    recommended_candidate_id: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "goal": self.goal,
            "results": [item.to_dict() for item in self.results],
            "recommended_candidate_id": self.recommended_candidate_id,
            "summary": dict(self.summary),
        }


@dataclass
class PreClickCandidateDecision:
    candidate_id: str
    element_id: str
    allowed: bool
    score: float
    click_point: dict[str, int] | None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "element_id": self.element_id,
            "allowed": bool(self.allowed),
            "score": round(float(self.score), 4),
            "click_point": dict(self.click_point) if self.click_point is not None else None,
            "reasons": list(self.reasons),
        }


@dataclass
class PreClickDecisionResult:
    contract_version: str = "pre_click_decision_v1"
    allowed: bool = False
    selected_candidate_id: str | None = None
    selected_element_id: str | None = None
    selected_click_point: dict[str, int] | None = None
    reasons: list[str] = field(default_factory=list)
    candidate_decisions: list[PreClickCandidateDecision] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "allowed": bool(self.allowed),
            "selected_candidate_id": self.selected_candidate_id,
            "selected_element_id": self.selected_element_id,
            "selected_click_point": dict(self.selected_click_point) if self.selected_click_point is not None else None,
            "reasons": list(self.reasons),
            "candidate_decisions": [item.to_dict() for item in self.candidate_decisions],
            "summary": dict(self.summary),
        }
