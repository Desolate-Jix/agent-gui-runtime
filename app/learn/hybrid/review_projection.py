"""Read-only Large Review projection for immutable Hybrid candidates."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.learn.hybrid.contracts import validate_omni_inventory
from app.learn.hybrid.omni_candidates import validate_current_capture_bundle
from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256, seal_immutable


_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}
_PROJECTION_FIELDS = {
    "contract_version", "status", "capture_lineage_ref", "displayed_image",
    "omni_inventory", "candidates", "warnings", "display_only", "review_only",
    "action_candidates", "content_sha256", *_NON_AUTHORIZING,
}


def project_hybrid_review(
    *,
    omni_inventory: Mapping[str, Any],
    capture_bundle: Mapping[str, Any],
    current_capture_lineage_ref: Mapping[str, str],
    displayed_image_sha256: str,
    displayed_image_size: Mapping[str, int],
) -> dict[str, Any]:
    """Create a closed, non-authorizing projection without dropping candidates."""
    bundle = validate_current_capture_bundle(capture_bundle)
    inventory = validate_omni_inventory(omni_inventory)
    capture = bundle["capture_identity"]
    if canonical_json_bytes(inventory["capture_identity"]) != canonical_json_bytes(capture):
        raise ValueError("Omni inventory conflicts with current capture bundle")
    _require_display_binding(
        capture=capture,
        current_capture_lineage_ref=current_capture_lineage_ref,
        displayed_image_sha256=displayed_image_sha256,
        displayed_image_size=displayed_image_size,
    )

    items_by_id = {
        item["source_item_id"]: item
        for item in inventory["provider_result"]["items"]
    }
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    for candidate in inventory["candidates"]:
        item = items_by_id[candidate["source_item_id"]]
        projected_candidate = _candidate_projection(
            inventory=inventory,
            candidate=candidate,
            item=item,
        )
        candidate_warnings = projected_candidate["warnings"]
        warnings.extend(
            warning for warning in candidate_warnings if warning not in warnings
        )
        candidates.append(projected_candidate)
    projection = seal_immutable({
        "contract_version": "hybrid_large_review_projection_v1",
        "status": "projected",
        "capture_lineage_ref": deepcopy(capture["capture_lineage_ref"]),
        "displayed_image": {
            "sha256": displayed_image_sha256,
            "image_size": deepcopy(dict(displayed_image_size)),
        },
        "omni_inventory": inventory,
        "candidates": candidates,
        "warnings": warnings,
        "display_only": True,
        "review_only": True,
        "action_candidates": [],
        **_NON_AUTHORIZING,
    })
    return validate_hybrid_review_projection(
        projection,
        current_capture_lineage_ref=current_capture_lineage_ref,
        displayed_image_sha256=displayed_image_sha256,
        displayed_image_size=displayed_image_size,
    )


def validate_hybrid_review_projection(
    value: Mapping[str, Any],
    *,
    current_capture_lineage_ref: Mapping[str, str],
    displayed_image_sha256: str,
    displayed_image_size: Mapping[str, int],
) -> dict[str, Any]:
    """Revalidate a persisted projection before Large Review renders it."""
    if not isinstance(value, Mapping):
        raise ValueError("Hybrid review projection must be an object")
    projection = deepcopy(dict(value))
    if set(projection) != _PROJECTION_FIELDS:
        raise ValueError("Hybrid review projection is not closed")
    canonical_json_bytes(projection)
    if projection.get("content_sha256") != content_sha256(projection):
        raise ValueError("Hybrid review projection content_sha256 mismatch")
    if projection.get("contract_version") != "hybrid_large_review_projection_v1" or projection.get("status") != "projected":
        raise ValueError("Hybrid review projection identity is invalid")
    _require_non_authorizing(projection)
    if projection.get("display_only") is not True or projection.get("review_only") is not True or projection.get("action_candidates") != []:
        raise ValueError("Hybrid review projection is not read-only")
    inventory = validate_omni_inventory(projection.get("omni_inventory"))
    capture = inventory["capture_identity"]
    _require_display_binding(
        capture=capture,
        current_capture_lineage_ref=current_capture_lineage_ref,
        displayed_image_sha256=displayed_image_sha256,
        displayed_image_size=displayed_image_size,
    )
    if projection.get("capture_lineage_ref") != capture["capture_lineage_ref"]:
        raise ValueError("Hybrid review projection capture lineage mismatch")
    if projection.get("displayed_image") != {
        "sha256": displayed_image_sha256,
        "image_size": dict(displayed_image_size),
    }:
        raise ValueError("Hybrid review projection displayed image mismatch")
    projected = projection.get("candidates")
    if not isinstance(projected, list) or len(projected) != len(inventory["candidates"]):
        raise ValueError("Hybrid review projection candidate omission")
    items_by_id = {
        item["source_item_id"]: item
        for item in inventory["provider_result"]["items"]
    }
    expected_candidates = [
        _candidate_projection(
            inventory=inventory,
            candidate=candidate,
            item=items_by_id[candidate["source_item_id"]],
        )
        for candidate in inventory["candidates"]
    ]
    if canonical_json_bytes(projected) != canonical_json_bytes(expected_candidates):
        raise ValueError("Hybrid review projection mutated or omitted a candidate")
    expected_warnings: list[str] = []
    for candidate in expected_candidates:
        expected_warnings.extend(
            warning for warning in candidate["warnings"] if warning not in expected_warnings
        )
    if projection.get("warnings") != expected_warnings:
        raise ValueError("Hybrid review projection warnings are invalid")
    projection["omni_inventory"] = inventory
    return projection


def _require_display_binding(
    *, capture: Mapping[str, Any], current_capture_lineage_ref: Mapping[str, str],
    displayed_image_sha256: str, displayed_image_size: Mapping[str, int],
) -> None:
    if dict(current_capture_lineage_ref) != capture["capture_lineage_ref"]:
        raise ValueError("current capture lineage mismatch")
    if displayed_image_sha256 != capture["screenshot_sha256"]:
        raise ValueError("displayed image SHA mismatch")
    if not isinstance(displayed_image_size, Mapping) or dict(displayed_image_size) != capture["image_size"]:
        raise ValueError("displayed image dimensions mismatch")


def _candidate_projection(
    *, inventory: Mapping[str, Any], candidate: Mapping[str, Any], item: Mapping[str, Any]
) -> dict[str, Any]:
    bbox = deepcopy(candidate["bbox_original"])
    warnings: list[str] = []
    if candidate["confidence"] < 0.5:
        warnings.append("low_provider_confidence")
    if not candidate["active"]:
        warnings.append("inactive_candidate_visible_for_audit")
    label = item.get("safe_text") or item.get("safe_role") or item["kind"]
    return {
        "candidate_id": candidate["candidate_id"],
        "region_id": candidate["candidate_id"],
        "source_item_id": candidate["source_item_id"],
        "label": label,
        "role": "review_only",
        "kind": item["kind"],
        "bbox": {
            "x": bbox[0], "y": bbox[1],
            "w": bbox[2] - bbox[0], "h": bbox[3] - bbox[1],
        },
        "bbox_original": bbox,
        "coordinate_space": candidate["coordinate_space"],
        "confidence": candidate["confidence"],
        "active": candidate["active"],
        "inactive_reason": candidate["inactive_reason"],
        "provider_provenance": {
            "provider_id": inventory["provider_id"],
            "profile_id": inventory["provider_result"]["profile_id"],
            "provider_revision": inventory["provider_revision"],
            "provider_result_ref": deepcopy(inventory["provider_result_ref"]),
            "capture_lineage_ref": deepcopy(inventory["capture_identity"]["capture_lineage_ref"]),
            "candidate_provenance": deepcopy(candidate["provenance"]),
            "raw_provider_item": deepcopy(dict(item)),
        },
        "warnings": warnings,
        "candidate_only": True,
        "requires_human_review": True,
        "review_only": True,
        "grounding_eligible": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "action_candidates": [],
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "authorization_scope": "display_and_review_only",
    }


def _require_non_authorizing(value: Mapping[str, Any]) -> None:
    for field, expected in _NON_AUTHORIZING.items():
        if value.get(field) != expected or type(value.get(field)) is not type(expected):
            raise ValueError(f"non-authorizing invariant violated: {field}")
