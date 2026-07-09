from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.learn.recognition.contracts import LEARN_CANDIDATE_CLASSIFICATION_CONTRACT
from app.learn.recognition.eligibility import evaluate_grounding_eligibility


def classify_inventory_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    danger: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        decision = _classification_decision(item)
        entry = deepcopy(item)
        entry["classification_decision"] = decision
        entry["grounding_eligible"] = bool(decision.get("grounding_eligible"))
        entry["review_only"] = bool(decision.get("review_only"))
        entry["grounding_block_reason"] = str(decision.get("grounding_block_reason") or "")
        entry["evidence_strength"] = str(decision.get("evidence_strength") or "")
        entry["eligible_for"] = list(decision.get("eligible_for") or [])
        if decision["outcome"] == "accepted_for_grounding":
            accepted.append(entry)
        elif decision["outcome"] == "danger_zone":
            danger.append(entry)
        elif decision["outcome"] == "needs_human_review":
            review.append(entry)
        else:
            rejected.append(entry)
    return {
        "contract_version": LEARN_CANDIDATE_CLASSIFICATION_CONTRACT,
        "accepted_for_grounding": accepted,
        "rejected_non_actionable": rejected,
        "needs_human_review": review,
        "danger_zones": danger,
        "summary": {
            "input_count": len([item for item in items if isinstance(item, dict)]),
            "accepted_for_grounding_count": len(accepted),
            "rejected_non_actionable_count": len(rejected),
            "needs_human_review_count": len(review),
            "danger_zone_count": len(danger),
        },
    }


def _classification_decision(item: dict[str, Any]) -> dict[str, Any]:
    label = str(item.get("label") or item.get("text") or "").strip()
    role = str(item.get("role") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    evidence_level = str(item.get("evidence_level") or "").casefold()
    sources = {str(value).casefold() for value in item.get("source_evidence", []) if str(value or "").strip()} if isinstance(item.get("source_evidence"), list) else set()
    interactable = item.get("interactable_evidence") if isinstance(item.get("interactable_evidence"), dict) else {}
    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    eligibility = evaluate_grounding_eligibility(item)

    if _looks_like_danger_action(label):
        return _decision("danger_zone", "dangerous_action_text", eligibility=eligibility)
    if item_type == "danger_zone":
        return _decision("danger_zone", "declared_danger_zone", eligibility=eligibility)
    if item_type in {"actionable", "form_field"} and _looks_like_tiny_noise_bbox(bbox):
        return _decision(
            "rejected_non_actionable",
            "tiny_noise_bbox",
            eligibility={
                **eligibility,
                "grounding_eligible": False,
                "review_only": True,
                "grounding_block_reason": "tiny_noise_bbox",
                "eligible_for": [],
            },
        )
    if evidence_level == "ocr_text_only" and item_type != "form_field":
        return _decision(
            "rejected_non_actionable",
            "ocr_text_only_without_interactable_evidence",
            eligibility=eligibility,
        )
    if evidence_level == "semantic_region_only" and not _has_strong_interactable_evidence(interactable):
        return _decision(
            "rejected_non_actionable",
            "semantic_region_only_without_grounding_evidence",
            eligibility=eligibility,
        )
    if _looks_like_open_detail_card(item) and _has_grounding_evidence(sources, interactable) and eligibility["grounding_eligible"]:
        return _decision("accepted_for_grounding", "open_detail_card_with_grounding_evidence", eligibility=eligibility)
    if _looks_like_non_actionable_text(label, role=role, item_type=item_type):
        return _decision("rejected_non_actionable", "readable_or_code_content", eligibility=eligibility)
    if item_type in {"actionable", "form_field"} and _has_grounding_evidence(sources, interactable) and eligibility["grounding_eligible"]:
        return _decision("accepted_for_grounding", "actionable_with_grounding_evidence", eligibility=eligibility)
    if item_type in {"actionable", "form_field"}:
        return _decision(
            "needs_human_review",
            "actionable_without_sufficient_grounding_evidence",
            eligibility=eligibility,
        )
    return _decision("rejected_non_actionable", "not_actionable_type", eligibility=eligibility)


def _decision(
    outcome: str,
    reason: str,
    *,
    grounding_eligible: bool = False,
    review_only: bool = False,
    grounding_block_reason: str = "",
    eligibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(eligibility, dict):
        grounding_eligible = bool(eligibility.get("grounding_eligible"))
        review_only = bool(eligibility.get("review_only"))
        grounding_block_reason = str(eligibility.get("grounding_block_reason") or "")
        evidence_strength = str(eligibility.get("evidence_strength") or "")
        eligible_for = list(eligibility.get("eligible_for") or [])
    else:
        evidence_strength = ""
        eligible_for = ["roi_grounding"] if grounding_eligible else []
    return {
        "outcome": outcome,
        "reason": reason,
        "grounding_eligible": grounding_eligible,
        "review_only": review_only,
        "grounding_block_reason": "" if grounding_eligible else grounding_block_reason or reason,
        "evidence_strength": evidence_strength,
        "eligible_for": eligible_for,
    }


def _has_grounding_evidence(sources: set[str], interactable: dict[str, Any]) -> bool:
    if _has_strong_interactable_evidence(interactable):
        return True
    return len(sources.intersection({"ocr", "uia", "dom", "omniparser"})) >= 2


def _has_strong_interactable_evidence(interactable: dict[str, Any]) -> bool:
    return any(
        bool(interactable.get(key))
        for key in (
            "uia_invokable",
            "dom_clickable",
            "omniparser_interactable",
            "calibrated_target_validated",
            "execute_candidate_ranked",
            "cross_evidence_overlap",
        )
    )


def _looks_like_non_actionable_text(label: str, *, role: str, item_type: str) -> bool:
    text = str(label or "").strip()
    lowered = text.casefold()
    if item_type in {"readable", "layout"}:
        return True
    if role in {"text", "card", "section", "group", "news_card", "recommendation_item"}:
        return True
    return bool(re.search(r"(^>>>|\bprint\(|\bdef\s+|\bclass\s+|\bimport\s+)", lowered))


def _looks_like_open_detail_card(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    if role != "card" and item_type != "card":
        return False
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    text_parts = [
        str(item.get("label") or ""),
        str(item.get("text") or ""),
        str(metadata.get("description") or ""),
    ]
    if isinstance(metadata.get("text_lines"), list):
        text_parts.extend(str(value) for value in metadata.get("text_lines", []))
    text = " ".join(text_parts).casefold()
    return any(term in text for term in ("job", "listing", "result", "company"))


def _looks_like_danger_action(label: str) -> bool:
    text = str(label or "").casefold()
    return any(
        token in text
        for token in (
            "submit application",
            "send application",
            "complete application",
            "review and submit",
            "confirm",
            "payment",
            "delete",
        )
    )


def _looks_like_tiny_noise_bbox(bbox: dict[str, Any]) -> bool:
    if not any(key in bbox for key in ("w", "h", "width", "height")):
        return False
    try:
        width = int(round(float(bbox.get("w", bbox.get("width", 0)))))
        height = int(round(float(bbox.get("h", bbox.get("height", 0)))))
    except (TypeError, ValueError):
        return True
    return width < 4 or height < 4
