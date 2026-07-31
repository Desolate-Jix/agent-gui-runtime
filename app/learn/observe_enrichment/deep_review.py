from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from app.operation.observe.contracts import ObserveScreenTaskInput
from app.vision.factory import VisionProviderFactory
from app.vision.model_io import (
    model_io_failure_payload as _model_io_failure_payload,
    model_io_trace as _model_io_trace,
)
from app.vision.schemas import VisionAnalyzeRequest
from app.learn.observe_enrichment.screen_map_builder import (
    _as_list,
    _bbox_overlap_area,
    _bounded_float,
    _first_compact_text,
    _goal_hint_for_candidate,
    _normalize_map_bbox,
    _normalize_map_point,
    _normalize_ocr_candidate_label,
    _screen_map_text_is_noise,
    _screen_map_texts,
    _section_id_for_bbox,
)


def _build_learn_deep_review(
    *,
    result: dict[str, Any],
    screen_map: dict[str, Any],
    request: ObserveScreenTaskInput,
    provider_factory: Any = VisionProviderFactory,
) -> dict[str, Any]:
    candidates = [dict(item) for item in _as_list(screen_map.get("candidates")) if isinstance(item, dict)]
    sections = [item for item in _as_list(screen_map.get("sections")) if isinstance(item, dict)]
    kept: list[dict[str, Any]] = []
    removals: list[dict[str, Any]] = []
    candidate_decisions: list[dict[str, Any]] = []

    for candidate in candidates:
        duplicate_of = _deep_duplicate_candidate(candidate, kept)
        if duplicate_of is not None:
            removals.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "label": candidate.get("label"),
                    "reason": "duplicate_candidate_same_label_and_bbox",
                    "duplicate_of": duplicate_of.get("candidate_id"),
                }
            )
            candidate_decisions.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "label": candidate.get("label"),
                    "action": "remove",
                    "reasons": ["duplicate_candidate_same_label_and_bbox"],
                }
            )
            continue
        kept.append(candidate)
        candidate_decisions.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "label": candidate.get("label"),
                "action": "keep",
                "risk_class": candidate.get("risk_class"),
                "section_id": candidate.get("section_id"),
                "reasons": _deep_candidate_reasons(candidate),
            }
        )

    additions = _deep_missing_text_additions(result=result, candidates=kept, sections=sections)
    for addition in additions:
        candidate_decisions.append(
            {
                "candidate_id": addition.get("candidate_id"),
                "label": addition.get("label"),
                "action": "add",
                "reasons": ["important_ocr_text_missing_from_path_graph"],
            }
        )

    refined_candidates = [*kept, *additions]
    refined_map = dict(screen_map)
    refined_map["candidates"] = refined_candidates
    refined_map["learn_depth"] = "deep"
    refined_map["summary"] = {
        **dict(screen_map.get("summary") if isinstance(screen_map.get("summary"), dict) else {}),
        "candidate_count": len(refined_candidates),
        "safe_candidate_count": len([item for item in refined_candidates if item.get("risk_class") == "safe_click_allowed"]),
        "blocked_candidate_count": len([item for item in refined_candidates if item.get("risk_class") == "blocked"]),
        "deep_addition_count": len(additions),
        "deep_removal_count": len(removals),
    }

    delta = {
        "contract_version": "path_graph_delta_v1",
        "source": "learn_deep_review",
        "state_id": screen_map.get("state_id"),
        "status": "ready",
        "additions": additions,
        "removals": removals,
        "updates": [
            {
                "field": "screen_map.summary",
                "reason": "learn_deep_summary_recomputed",
                "candidate_count": len(refined_candidates),
            }
        ],
        "summary": {
            "addition_count": len(additions),
            "removal_count": len(removals),
            "update_count": 1,
        },
    }
    review = {
        "contract_version": "path_graph_deep_review_v1",
        "status": "ready",
        "state_id": screen_map.get("state_id"),
        "learn_depth": "deep",
        "candidate_decisions": candidate_decisions,
        "summary": {
            "input_candidate_count": len(candidates),
            "output_candidate_count": len(refined_candidates),
            "duplicate_count": len(removals),
            "missing_text_addition_count": len(additions),
            "section_count": len(sections),
        },
    }
    write_policy = request.write_policy.model_dump() if hasattr(request.write_policy, "model_dump") else {}
    deep_result = {
        "screen_map": refined_map,
        "path_graph_deep_review": review,
        "path_graph_delta": delta,
        "element_memory_init_plan": _build_element_memory_init_plan(
            screen_map=refined_map,
            enabled=bool(write_policy.get("element_memory", False)),
        ),
    }
    model_review = _run_learn_deep_model_review(
        result=result,
        screen_map=refined_map,
        deterministic_review=review,
        deterministic_delta=delta,
        request=request,
        provider_factory=provider_factory,
    )
    deep_result = _apply_learn_deep_model_review(
        deep_result=deep_result,
        model_review=model_review,
        element_memory_enabled=bool(write_policy.get("element_memory", False)),
    )
    return deep_result


def _run_learn_deep_model_review(
    *,
    result: dict[str, Any],
    screen_map: dict[str, Any],
    deterministic_review: dict[str, Any],
    deterministic_delta: dict[str, Any],
    request: ObserveScreenTaskInput,
    provider_factory: Any = VisionProviderFactory,
) -> dict[str, Any]:
    options = _learn_deep_model_options(request)
    if options.get("enabled") is False:
        return {
            "contract_version": "learn_deep_model_review_v1",
            "status": "disabled",
            "reason": "disabled_by_metadata",
        }
    image_path = str(screen_map.get("image_path") or result.get("image_path") or "").strip()
    if not image_path:
        return {
            "contract_version": "learn_deep_model_review_v1",
            "status": "skipped",
            "reason": "missing_image_path",
        }
    try:
        config = provider_factory.load_config()
        provider_mode = str(options.get("provider_mode") or request.provider_mode or "local_grounding")
        provider = provider_factory.create(mode=provider_mode, config=config)
        provider_response = provider.analyze(
            VisionAnalyzeRequest(
                image_path=image_path,
                task="learn_deep_review",
                app_name=request.app_name,
                goal="Review and refine the whole-screen PathGraph draft without executing actions.",
                state_hint=screen_map.get("state_hint") or result.get("suggested_state_hint") or request.state_hint,
                provider_mode=provider_mode,
                metadata={
                    "max_output_tokens": int(options.get("max_output_tokens") or 2048),
                    "learn_deep_review_context": _learn_deep_model_context(
                        result=result,
                        screen_map=screen_map,
                        deterministic_review=deterministic_review,
                        deterministic_delta=deterministic_delta,
                        max_candidates=int(options.get("max_candidates") or 80),
                        max_texts=int(options.get("max_texts") or 120),
                    ),
                },
            )
        )
        model_json = _extract_provider_model_json(provider_response.raw_response)
        model_json = model_json if isinstance(model_json, dict) else {}
        return {
            "contract_version": "learn_deep_model_review_v1",
            "status": str(model_json.get("status") or "ready"),
            "provider": provider_response.provider,
            "provider_mode": provider_mode,
            "model_name": model_json.get("model_name") or model_json.get("provider") or provider_response.provider,
            "model_io": _model_io_trace(provider_response),
            "screen_summary": model_json.get("screen_summary") or provider_response.screen_summary,
            "state_guess": model_json.get("state_guess") or provider_response.state_guess,
            "candidate_decisions": _as_list(model_json.get("candidate_decisions")),
            "additions": _as_list(model_json.get("additions")),
            "removals": _as_list(model_json.get("removals")),
            "updates": _as_list(model_json.get("updates")),
            "notes": _as_list(model_json.get("notes")) or list(provider_response.notes),
        }
    except Exception as exc:
        model_io = _model_io_failure_payload(exc)
        return {
            "contract_version": "learn_deep_model_review_v1",
            "status": "failed",
            "error": str(exc),
            "provider_mode": str(options.get("provider_mode") or request.provider_mode or "local_grounding"),
            "model_io": model_io,
            "fallback": "deterministic_learn_deep_review",
        }


def _learn_deep_model_options(request: ObserveScreenTaskInput) -> dict[str, Any]:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    raw = metadata.get("learn_deep_model_review")
    if raw is False:
        return {"enabled": False}
    if isinstance(raw, dict):
        return {**raw, "enabled": raw.get("enabled", True) is not False}
    return {"enabled": True}


def _learn_deep_model_context(
    *,
    result: dict[str, Any],
    screen_map: dict[str, Any],
    deterministic_review: dict[str, Any],
    deterministic_delta: dict[str, Any],
    max_candidates: int,
    max_texts: int,
) -> dict[str, Any]:
    return {
        "contract_version": "learn_deep_review_context_v1",
        "state_id": screen_map.get("state_id"),
        "app_name": screen_map.get("app_name"),
        "state_hint": screen_map.get("state_hint"),
        "summary": screen_map.get("summary"),
        "sections": _compact_map_items(screen_map.get("sections"), limit=40),
        "candidates": _compact_map_items(screen_map.get("candidates"), limit=max_candidates),
        "ocr_texts": _compact_map_items(_screen_map_texts(result), limit=max_texts),
        "uia": _compact_uia_for_learn_deep(result),
        "deterministic_review_summary": deterministic_review.get("summary"),
        "deterministic_delta_summary": deterministic_delta.get("summary"),
        "safety": {
            "path_graph_coordinates_are_observation_only": True,
            "execution_requires_pre_click_decision_v1": True,
        },
    }


def _compact_map_items(value: Any, *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(value)[: max(0, int(limit))]:
        if isinstance(item, dict):
            items.append(
                {
                    key: item.get(key)
                    for key in (
                        "id",
                        "candidate_id",
                        "section_id",
                        "label",
                        "text",
                        "role",
                        "type",
                        "risk_class",
                        "expected_effect",
                        "bbox",
                        "click_point",
                        "confidence",
                        "source",
                    )
                    if key in item
                }
            )
    return items


def _compact_uia_for_learn_deep(result: dict[str, Any]) -> dict[str, Any]:
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    source_layers = screen_reading.get("source_layers") if isinstance(screen_reading.get("source_layers"), dict) else {}
    uia = source_layers.get("windows_uia") if isinstance(source_layers.get("windows_uia"), dict) else {}
    return {
        "status": uia.get("status"),
        "control_count": uia.get("control_count"),
        "available": uia.get("available"),
    }


def _extract_provider_model_json(raw_response: Any) -> dict[str, Any]:
    if not isinstance(raw_response, dict):
        return {}
    model_json = raw_response.get("model_json")
    if isinstance(model_json, dict):
        return model_json
    if raw_response.get("contract_version") == "learn_deep_model_review_v1":
        return raw_response
    nested = raw_response.get("raw_response")
    if isinstance(nested, dict):
        return _extract_provider_model_json(nested)
    return {}


def _apply_learn_deep_model_review(
    *,
    deep_result: dict[str, Any],
    model_review: dict[str, Any],
    element_memory_enabled: bool,
) -> dict[str, Any]:
    review = dict(deep_result.get("path_graph_deep_review") or {})
    delta = dict(deep_result.get("path_graph_delta") or {})
    screen_map = dict(deep_result.get("screen_map") or {})
    candidates = [dict(item) for item in _as_list(screen_map.get("candidates")) if isinstance(item, dict)]
    model_status = str(model_review.get("status") or "")
    review["model_review"] = model_review
    if model_status != "ready":
        deep_result["path_graph_deep_review"] = review
        return deep_result

    existing_by_id = {str(item.get("candidate_id")): item for item in candidates if item.get("candidate_id")}
    remove_ids: set[str] = set()
    model_decisions: list[dict[str, Any]] = []
    additions: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []

    review_items = [item for item in _as_list(model_review.get("candidate_decisions")) if isinstance(item, dict)]
    review_items.extend({"action": "remove", **item} for item in _as_list(model_review.get("removals")) if isinstance(item, dict))
    review_items.extend({"action": "add", "candidate": item} for item in _as_list(model_review.get("additions")) if isinstance(item, dict))
    review_items.extend({"action": "update", **item} for item in _as_list(model_review.get("updates")) if isinstance(item, dict))

    for index, item in enumerate(review_items):
        action = str(item.get("action") or "").strip().lower()
        candidate_id = str(item.get("candidate_id") or "").strip()
        reasons = [str(reason) for reason in _as_list(item.get("reasons")) if str(reason).strip()]
        if action == "remove" and candidate_id in existing_by_id and reasons:
            remove_ids.add(candidate_id)
            model_decisions.append(
                {
                    "candidate_id": candidate_id,
                    "label": item.get("label") or existing_by_id[candidate_id].get("label"),
                    "action": "remove",
                    "source": "learn_deep_model_review",
                    "reasons": reasons,
                }
            )
        elif action == "add":
            candidate = _normalize_learn_deep_model_candidate(
                item.get("candidate") if isinstance(item.get("candidate"), dict) else item,
                index=index,
                screen_map=screen_map,
            )
            if candidate and not _deep_duplicate_candidate(candidate, candidates + additions):
                additions.append(candidate)
                model_decisions.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "label": candidate.get("label"),
                        "action": "add",
                        "source": "learn_deep_model_review",
                        "reasons": reasons or ["model_identified_missing_candidate"],
                    }
                )
        elif action == "update" and candidate_id in existing_by_id:
            update = _normalize_learn_deep_model_update(item, existing_by_id[candidate_id])
            if update:
                updates.append(update)
                existing_by_id[candidate_id].update(update["fields"])
                model_decisions.append(
                    {
                        "candidate_id": candidate_id,
                        "label": existing_by_id[candidate_id].get("label"),
                        "action": "update",
                        "source": "learn_deep_model_review",
                        "reasons": reasons or ["model_refined_candidate_semantics"],
                        "fields": sorted(update["fields"].keys()),
                    }
                )
        elif action == "keep" and candidate_id in existing_by_id:
            model_decisions.append(
                {
                    "candidate_id": candidate_id,
                    "label": item.get("label") or existing_by_id[candidate_id].get("label"),
                    "action": "keep",
                    "source": "learn_deep_model_review",
                    "reasons": reasons or ["model_kept_candidate"],
                }
            )

    refined_candidates = [item for item in candidates if str(item.get("candidate_id") or "") not in remove_ids]
    refined_candidates.extend(additions)
    screen_map["candidates"] = refined_candidates
    screen_map["summary"] = {
        **dict(screen_map.get("summary") if isinstance(screen_map.get("summary"), dict) else {}),
        "candidate_count": len(refined_candidates),
        "safe_candidate_count": len([item for item in refined_candidates if item.get("risk_class") == "safe_click_allowed"]),
        "blocked_candidate_count": len([item for item in refined_candidates if item.get("risk_class") == "blocked"]),
        "model_addition_count": len(additions),
        "model_removal_count": len(remove_ids),
        "model_update_count": len(updates),
    }

    delta_removals = [item for item in _as_list(delta.get("removals")) if isinstance(item, dict)]
    for candidate_id in sorted(remove_ids):
        delta_removals.append(
            {
                "candidate_id": candidate_id,
                "label": existing_by_id.get(candidate_id, {}).get("label"),
                "reason": "model_review_remove",
                "source": "learn_deep_model_review",
            }
        )
    delta["additions"] = [*([item for item in _as_list(delta.get("additions")) if isinstance(item, dict)]), *additions]
    delta["removals"] = delta_removals
    delta["updates"] = [*([item for item in _as_list(delta.get("updates")) if isinstance(item, dict)]), *updates]
    delta["summary"] = {
        "addition_count": len(delta["additions"]),
        "removal_count": len(delta["removals"]),
        "update_count": len(delta["updates"]),
    }

    review["candidate_decisions"] = [*([item for item in _as_list(review.get("candidate_decisions")) if isinstance(item, dict)]), *model_decisions]
    review["summary"] = {
        **dict(review.get("summary") if isinstance(review.get("summary"), dict) else {}),
        "output_candidate_count": len(refined_candidates),
        "model_decision_count": len(model_decisions),
        "model_addition_count": len(additions),
        "model_removal_count": len(remove_ids),
        "model_update_count": len(updates),
    }

    deep_result["screen_map"] = screen_map
    deep_result["path_graph_deep_review"] = review
    deep_result["path_graph_delta"] = delta
    deep_result["element_memory_init_plan"] = _build_element_memory_init_plan(
        screen_map=screen_map,
        enabled=element_memory_enabled,
    )
    return deep_result


def _normalize_learn_deep_model_candidate(raw: Any, *, index: int, screen_map: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    label = _first_compact_text(raw.get("label"), raw.get("text"), raw.get("name"))
    bbox = _normalize_map_bbox(raw.get("bbox") or raw.get("diagonal"))
    if not label or not bbox:
        return None
    candidate_id = str(raw.get("candidate_id") or raw.get("id") or f"learn_deep_model_{index}").strip()
    role = _first_compact_text(raw.get("role"), raw.get("type")) or "model_candidate"
    risk_class = str(raw.get("risk_class") or "safe_dry_run_only").strip()
    if risk_class not in {"safe_click_allowed", "safe_dry_run_only", "requires_user_confirmation", "blocked"}:
        risk_class = "safe_dry_run_only"
    return {
        "contract_version": "screen_map_candidate_v1",
        "candidate_id": candidate_id,
        "label": label,
        "role": role,
        "goal_hint": _first_compact_text(raw.get("goal_hint")) or _goal_hint_for_candidate(label=label, role=role),
        "expected_effect": _first_compact_text(raw.get("expected_effect"), raw.get("description")) or "click may change the current interface",
        "risk_class": risk_class,
        "risk_reasons": [str(item) for item in _as_list(raw.get("risk_reasons") or raw.get("reasons")) if str(item).strip()],
        "section_id": raw.get("section_id") or _section_id_for_bbox(bbox, _as_list(screen_map.get("sections"))),
        "bbox": bbox,
        "click_point": _normalize_map_point(raw.get("click_point"), bbox),
        "confidence": _bounded_float(raw.get("confidence")) or 0.55,
        "source": "learn_deep_model_review",
        "screen_map_rule": "learn_deep_model_added",
        "evidence": {
            "model_review": {
                "reason": _first_compact_text(raw.get("reason"), raw.get("description")),
                "coordinates_are_observation_only": True,
            }
        },
    }


def _normalize_learn_deep_model_update(raw: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any] | None:
    fields: dict[str, Any] = {}
    for key in ("label", "role", "section_id", "expected_effect", "risk_class", "description"):
        value = raw.get(key)
        if value is not None and str(value).strip() and value != existing.get(key):
            fields[key] = str(value).strip()
    bbox = _normalize_map_bbox(raw.get("bbox") or raw.get("bounding_box") or raw.get("bounds"))
    if bbox and bbox != _normalize_map_bbox(existing.get("bbox")):
        fields["bbox"] = bbox
    point = _normalize_map_point(raw.get("click_point") or raw.get("clickPoint"), bbox or _normalize_map_bbox(existing.get("bbox")))
    if point and point != _normalize_map_point(existing.get("click_point") or existing.get("clickPoint"), _normalize_map_bbox(existing.get("bbox"))):
        fields["click_point"] = point
    confidence = _bounded_float(raw.get("confidence"))
    if confidence is not None and confidence != existing.get("confidence"):
        fields["confidence"] = confidence
    if not fields:
        return None
    return {
        "candidate_id": existing.get("candidate_id"),
        "source": "learn_deep_model_review",
        "fields": fields,
    }


def _deep_duplicate_candidate(candidate: dict[str, Any], kept: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate_label = _path_label_key(candidate.get("label"))
    candidate_bbox = _normalize_map_bbox(candidate.get("bbox"))
    if not candidate_label or not candidate_bbox:
        return None
    for existing in kept:
        existing_label = _path_label_key(existing.get("label"))
        existing_bbox = _normalize_map_bbox(existing.get("bbox"))
        if not existing_label or not existing_bbox:
            continue
        if _path_label_similarity(candidate_label, existing_label) >= 0.92 and _path_bbox_similarity(candidate_bbox, existing_bbox) >= 0.82:
            return existing
    return None


def _deep_candidate_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons = ["candidate_retained"]
    if candidate.get("source") in {"ocr_card_groups", "ocr_text_actions", "nav_text_action"}:
        reasons.append("ocr_backed_candidate")
    if candidate.get("section_id"):
        reasons.append("section_assigned")
    if candidate.get("risk_class") == "safe_click_allowed":
        reasons.append("safe_click_candidate")
    return reasons


def _deep_missing_text_additions(
    *,
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    additions: list[dict[str, Any]] = []
    existing_labels = {_path_label_key(item.get("label")) for item in candidates}
    existing_boxes = [_normalize_map_bbox(item.get("bbox")) for item in candidates]
    for index, text_item in enumerate(_screen_map_texts(result)):
        text = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text")))
        if not text or _screen_map_text_is_noise(text, allow_short=False):
            continue
        text_key = _path_label_key(text)
        bbox = _normalize_map_bbox(text_item.get("bbox"))
        if not text_key or not bbox:
            continue
        if any(_path_label_similarity(text_key, existing) >= 0.92 for existing in existing_labels if existing):
            continue
        if any(box and _bbox_contains_center(box, bbox) for box in existing_boxes):
            continue
        section_id = _section_id_for_bbox(bbox, sections)
        addition = {
            "contract_version": "screen_map_candidate_v1",
            "candidate_id": f"learn_deep_text_{index}",
            "label": text,
            "role": "ocr_text_action",
            "goal_hint": _goal_hint_for_candidate(label=text, role="ocr_text_action"),
            "expected_effect": "click may change the current interface",
            "risk_class": "safe_dry_run_only",
            "risk_reasons": ["learn_deep_missing_text_requires_locate"],
            "section_id": section_id,
            "bbox": bbox,
            "click_point": _normalize_map_point(None, bbox),
            "confidence": _bounded_float(text_item.get("confidence") or text_item.get("score")) or 0.5,
            "source": "learn_deep_missing_ocr_text",
            "source_id": text_item.get("id") or text_item.get("text_id"),
            "screen_map_rule": "learn_deep_missing_text_added",
            "evidence": {
                "source_text": text_item,
                "screen_map_rule": "learn_deep_missing_text_added",
            },
        }
        additions.append(addition)
        existing_labels.add(text_key)
        existing_boxes.append(bbox)
    return additions[:20]


def _bbox_contains_center(container: dict[str, int], inner: dict[str, int]) -> bool:
    cx = inner["x"] + inner["w"] / 2
    cy = inner["y"] + inner["h"] / 2
    return container["x"] <= cx <= container["x"] + container["w"] and container["y"] <= cy <= container["y"] + container["h"]


def _build_element_memory_init_plan(*, screen_map: dict[str, Any], enabled: bool) -> dict[str, Any]:
    candidates = [item for item in _as_list(screen_map.get("candidates")) if isinstance(item, dict)]
    entries = [
        {
            "candidate_id": item.get("candidate_id"),
            "memory_key": f"{screen_map.get('state_id')}::{item.get('candidate_id')}",
            "label": item.get("label"),
            "role": item.get("role"),
            "section_id": item.get("section_id"),
            "risk_class": item.get("risk_class"),
            "write_status": "planned_not_written",
        }
        for item in candidates
        if item.get("candidate_id") and item.get("label")
    ]
    return {
        "contract_version": "element_memory_init_plan_v1",
        "status": "planned" if enabled else "disabled_by_write_policy",
        "write_policy_element_memory": bool(enabled),
        "state_id": screen_map.get("state_id"),
        "entry_count": len(entries) if enabled else 0,
        "entries": entries if enabled else [],
    }


def _path_bbox_similarity(a: dict[str, int] | None, b: dict[str, int] | None) -> float:
    if not a or not b:
        return 0.0
    overlap = _bbox_overlap_area(a, b)
    union = a["w"] * a["h"] + b["w"] * b["h"] - overlap
    iou = overlap / union if union > 0 else 0.0
    acx = a["x"] + a["w"] / 2
    acy = a["y"] + a["h"] / 2
    bcx = b["x"] + b["w"] / 2
    bcy = b["y"] + b["h"] / 2
    distance = ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5
    max_size = max(a["w"], a["h"], b["w"], b["h"], 1)
    center_score = max(0.0, 1.0 - distance / max_size)
    return max(iou, center_score * 0.8)


def _path_label_key(value: Any) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _path_label_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    return SequenceMatcher(None, a, b).ratio()


def apply_deep_review(
    *,
    result: dict[str, Any],
    screen_map: dict[str, Any],
    task: ObserveScreenTaskInput,
    provider_factory: Any = VisionProviderFactory,
) -> dict[str, Any]:
    return _build_learn_deep_review(
        result=result,
        screen_map=screen_map,
        request=task,
        provider_factory=provider_factory,
    )
