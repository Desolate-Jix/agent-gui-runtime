from __future__ import annotations

from typing import Any


def make_layer(layer: str, result: dict[str, Any], validation: dict[str, Any], *, summary: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "layer": layer,
        "ok": bool(validation.get("ok")),
        "summary": summary or {},
        "validation": validation,
        "result": result,
    }


def validate_input_layer(result: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in ["image_path", "image_exists", "image_size"] if key not in result]
    errors: list[str] = []
    if result.get("image_exists") is not True:
        errors.append("image_path_does_not_exist")
    if not isinstance(result.get("image_size"), dict):
        errors.append("image_size_missing")
    return _validation(missing_fields=missing, errors=errors)


def validate_provider_layer(result: dict[str, Any]) -> dict[str, Any]:
    required = ["provider", "contract_version", "image_size", "screen_summary", "state_guess", "regions", "targets", "observers", "notes"]
    missing = [key for key in required if key not in result]
    warnings: list[str] = []
    if result.get("contract_version") != "vision_regions_v1":
        warnings.append("provider_contract_version_is_not_vision_regions_v1")
    return _validation(missing_fields=missing, warnings=warnings)


def validate_vision_regions_layer(result: dict[str, Any]) -> dict[str, Any]:
    required = ["provider", "contract_version", "image_size", "screen_summary", "state_guess", "regions", "targets", "observers", "notes"]
    region_required = [
        "region_id",
        "label",
        "role",
        "bbox",
        "diagonal",
        "normalized_diagonal",
        "description",
        "ocr_text",
        "text_lines",
        "possible_destinations",
        "anchor_relations",
        "grounding_constraints",
        "confidence",
        "layout_key",
        "content_key",
        "match_key",
    ]
    missing = [key for key in required if key not in result]
    region_errors = _collection_missing_fields(result.get("regions") or [], region_required, id_field="region_id")
    warnings: list[str] = []
    if result.get("contract_version") != "vision_regions_v1":
        warnings.append("contract_version_is_not_vision_regions_v1")
    if not result.get("regions"):
        warnings.append("no_regions_returned")
    return _validation(missing_fields=missing, item_errors=region_errors, warnings=warnings)


def validate_ocr_layer(result: dict[str, Any]) -> dict[str, Any]:
    required = ["image_path", "matches", "metadata"]
    match_required = ["text", "score", "bbox"]
    missing = [key for key in required if key not in result]
    match_errors = _collection_missing_fields(result.get("matches") or [], match_required, id_field="text")
    warnings: list[str] = []
    if not result.get("matches"):
        warnings.append("no_ocr_matches_returned")
    return _validation(missing_fields=missing, item_errors=match_errors, warnings=warnings)


def validate_page_structure_layer(result: dict[str, Any]) -> dict[str, Any]:
    required = [
        "contract_version",
        "image_size",
        "screen_summary",
        "state_guess",
        "regions",
        "elements",
        "texts",
        "links",
        "learning_summary",
        "raw_ocr",
        "raw_vision_regions",
    ]
    element_required = [
        "element_id",
        "label",
        "role",
        "interaction_type",
        "description",
        "text",
        "bbox",
        "semantic_bbox",
        "click_point",
        "click_strategy",
        "possible_destinations",
        "verification_hints",
        "interaction_policy",
        "fusion_confidence",
        "coordinate_confidence",
        "memory_key",
        "sources",
        "source_region_ids",
        "source_text_ids",
        "evidence",
    ]
    missing = [key for key in required if key not in result]
    element_errors = _collection_missing_fields(result.get("elements") or [], element_required, id_field="element_id")
    warnings: list[str] = []
    if result.get("contract_version") != "page_structure_v1":
        warnings.append("contract_version_is_not_page_structure_v1")
    if not result.get("elements"):
        warnings.append("no_elements_returned")
    return _validation(missing_fields=missing, item_errors=element_errors, warnings=warnings)


def summarize_vision(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": result.get("provider"),
        "contract_version": result.get("contract_version"),
        "region_count": len(result.get("regions") or []),
        "target_count": len(result.get("targets") or []),
        "observer_count": len(result.get("observers") or []),
    }


def summarize_ocr(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine": (result.get("metadata") or {}).get("engine"),
        "match_count": len(result.get("matches") or []),
        "texts": [item.get("text") for item in (result.get("matches") or [])],
    }


def summarize_page_structure(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": result.get("contract_version"),
        "region_count": len(result.get("regions") or []),
        "element_count": len(result.get("elements") or []),
        "allowed_element_count": len([item for item in (result.get("elements") or []) if ((item.get("interaction_policy") or {}).get("allowed"))]),
        "blocked_element_count": len([item for item in (result.get("elements") or []) if not ((item.get("interaction_policy") or {}).get("allowed", True))]),
        "text_count": len(result.get("texts") or []),
        "link_count": len(result.get("links") or []),
        "element_labels": [item.get("label") for item in (result.get("elements") or [])],
    }


def failure_layer(layer: str, exc: Exception) -> dict[str, Any]:
    return make_layer(
        layer,
        result={},
        validation={
            "ok": False,
            "missing_fields": [],
            "item_errors": [],
            "warnings": [],
            "errors": [str(exc)],
        },
        summary={"error": type(exc).__name__},
    )


def _validation(
    *,
    missing_fields: list[str],
    item_errors: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    item_errors = item_errors or []
    warnings = warnings or []
    errors = errors or []
    return {
        "ok": not missing_fields and not item_errors and not errors,
        "missing_fields": missing_fields,
        "item_errors": item_errors,
        "warnings": warnings,
        "errors": errors,
    }


def _collection_missing_fields(items: list[Any], required_fields: list[str], *, id_field: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append({"index": index, "id": None, "missing_fields": required_fields, "error": "item_is_not_object"})
            continue
        missing = [field for field in required_fields if field not in item]
        if missing:
            errors.append({"index": index, "id": item.get(id_field), "missing_fields": missing})
    return errors
