from __future__ import annotations

from typing import Any


def new_support_eligibility_summary() -> dict[str, Any]:
    return {
        "contract_version": "learn_support_eligibility_summary_v1",
        "parser_candidate_contract": "parser_candidate_v1",
        "total_candidates": 0,
        "grounding_eligible_candidates": 0,
        "review_only_candidates": 0,
        "interactable_evidence_candidates": 0,
        "same_screenshot_interactable_support": 0,
        "semantic_or_ocr_candidates": 0,
        "semantic_or_ocr_leaked_to_grounding": 0,
        "stale_candidates": 0,
        "missing_parser_candidate_contract": 0,
        "by_source_type": {},
        "by_evidence_kind": {},
        "blocked_reasons": {},
        "interpretation": (
            "parser_candidate_v1 support eligibility is evidence routing only; it is not click permission, "
            "PathGraph promotion, model accuracy, or Execute authorization"
        ),
    }


def summarize_support_eligibility_from_inventory(inventory: Any) -> dict[str, Any]:
    summary = new_support_eligibility_summary()
    for item in inventory if isinstance(inventory, list) else []:
        if not isinstance(item, dict):
            continue
        candidate = item.get("parser_candidate") if isinstance(item.get("parser_candidate"), dict) else {}
        if not candidate:
            summary["missing_parser_candidate_contract"] += 1
            continue
        _accumulate_parser_candidate(summary, candidate)
    return finalize_support_eligibility_summary(summary)


def merge_support_eligibility_summary(total: dict[str, Any], case_summary: dict[str, Any]) -> None:
    for key in (
        "total_candidates",
        "grounding_eligible_candidates",
        "review_only_candidates",
        "interactable_evidence_candidates",
        "same_screenshot_interactable_support",
        "semantic_or_ocr_candidates",
        "semantic_or_ocr_leaked_to_grounding",
        "stale_candidates",
        "missing_parser_candidate_contract",
    ):
        total[key] = int(total.get(key) or 0) + int(case_summary.get(key) or 0)
    for key in ("by_source_type", "by_evidence_kind", "blocked_reasons"):
        _merge_counter_dict(total.setdefault(key, {}), case_summary.get(key))


def finalize_support_eligibility_summary(summary: dict[str, Any]) -> dict[str, Any]:
    total = int(summary.get("total_candidates") or 0)
    eligible = int(summary.get("grounding_eligible_candidates") or 0)
    same_support = int(summary.get("same_screenshot_interactable_support") or 0)
    leaked = int(summary.get("semantic_or_ocr_leaked_to_grounding") or 0)
    summary["grounding_eligible_rate"] = "not_covered" if total == 0 else round(eligible / total, 4)
    summary["same_screenshot_support_rate"] = "not_covered" if total == 0 else round(same_support / total, 4)
    summary["semantic_or_ocr_leakage_safe"] = leaked == 0
    summary["coverage_status"] = "not_covered" if total == 0 else "covered"
    summary["by_source_type"] = dict(sorted((summary.get("by_source_type") or {}).items()))
    summary["by_evidence_kind"] = dict(sorted((summary.get("by_evidence_kind") or {}).items()))
    summary["blocked_reasons"] = dict(sorted((summary.get("blocked_reasons") or {}).items()))
    return summary


def _accumulate_parser_candidate(summary: dict[str, Any], candidate: dict[str, Any]) -> None:
    summary["total_candidates"] += 1
    source_type = str(candidate.get("source_type") or "unknown")
    evidence_kind = str(candidate.get("evidence_kind") or "unknown")
    _inc(summary["by_source_type"], source_type)
    _inc(summary["by_evidence_kind"], evidence_kind)
    if candidate.get("grounding_eligible") is True:
        summary["grounding_eligible_candidates"] += 1
    if candidate.get("review_only") is True:
        summary["review_only_candidates"] += 1
    if candidate.get("is_interactable_evidence") is True:
        summary["interactable_evidence_candidates"] += 1
        freshness = candidate.get("freshness") if isinstance(candidate.get("freshness"), dict) else {}
        if freshness.get("same_screenshot") is True and freshness.get("stale") is not True:
            summary["same_screenshot_interactable_support"] += 1
    if evidence_kind in {"semantic_region", "ocr_text_anchor"}:
        summary["semantic_or_ocr_candidates"] += 1
        if candidate.get("grounding_eligible") is True:
            summary["semantic_or_ocr_leaked_to_grounding"] += 1
    freshness = candidate.get("freshness") if isinstance(candidate.get("freshness"), dict) else {}
    if freshness.get("stale") is True:
        summary["stale_candidates"] += 1
    reason = str(candidate.get("grounding_block_reason") or "").strip()
    if reason:
        _inc(summary["blocked_reasons"], reason)


def _merge_counter_dict(target: dict[str, int], value: Any) -> None:
    for key, count in (value if isinstance(value, dict) else {}).items():
        target[str(key)] = int(target.get(str(key), 0)) + int(count or 0)


def _inc(counter: dict[str, int], key: str) -> None:
    counter[key] = int(counter.get(key, 0)) + 1
