"""UEI-native persistence and read-only projection of Hybrid candidates."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
from app.learn.hybrid.omni_candidates import (
    build_omni_candidate_ledger,
    validate_omni_candidate_ledger,
)
from app.learn.recognition.uei.canonical import (
    canonical_json_bytes,
    content_sha256,
    seal_immutable,
)
from app.learn.recognition.uei.contracts import validate_contract
from app.learn.recognition.uei.store import UEIObjectStore


_STORE_RELATIVE_PATH = Path("artifacts") / "uei-shadow-store"
_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}


def project_hybrid_review(
    *,
    project_root: Path,
    omni_ledger: Mapping[str, Any],
    displayed_image_sha256: str,
    displayed_image_size: Mapping[str, int],
) -> dict[str, Any]:
    """Persist one closed projection after resolving all authoritative parents."""
    root = _project_root(project_root)
    ledger = validate_omni_candidate_ledger(omni_ledger)
    store = UEIObjectStore(root=root / _STORE_RELATIVE_PATH)
    bundle_ref = deepcopy(ledger["hybrid_capture_bundle_ref"])
    bundle_record = store.get(bundle_ref, contract_version="hybrid_capture_bundle_v1")
    bundle = load_and_verify_hybrid_capture_bundle(
        project_root=root,
        bundle_ref=bundle_ref,
        expected_run_id=bundle_record["run_id"],
        expected_workflow_revision=bundle_record["workflow_revision"],
    )
    bundle["bundle_ref"] = bundle_ref
    provider_result = store.get(
        ledger["provider_result_ref"], contract_version="provider_safe_result_v1"
    )
    rebuilt = build_omni_candidate_ledger(
        safe_result=provider_result,
        capture_bundle=bundle,
    )
    if canonical_json_bytes(rebuilt) != canonical_json_bytes(ledger):
        raise ValueError("Omni ledger does not match persisted evidence")
    projection = build_hybrid_review_projection(
        omni_ledger=rebuilt,
        displayed_image_sha256=displayed_image_sha256,
        displayed_image_size=displayed_image_size,
    )
    projection_ref = store.put(projection)
    return {**deepcopy(projection), "projection_ref": projection_ref}


def build_hybrid_review_projection(
    *,
    omni_ledger: Mapping[str, Any],
    displayed_image_sha256: str,
    displayed_image_size: Mapping[str, int],
) -> dict[str, Any]:
    """Deterministically rebuild the stored projection from verified parents."""
    ledger = validate_omni_candidate_ledger(omni_ledger)
    capture = ledger["capture_identity"]
    _require_display_binding(
        capture=capture,
        displayed_image_sha256=displayed_image_sha256,
        displayed_image_size=displayed_image_size,
    )
    warnings = _projection_warnings(ledger["candidates"])
    base: dict[str, Any] = {
        "contract_version": "hybrid_review_projection_v1",
        "projection_id": "",
        "hybrid_capture_bundle_ref": deepcopy(ledger["hybrid_capture_bundle_ref"]),
        "provider_result_ref": deepcopy(ledger["provider_result_ref"]),
        "capture_lineage_ref": deepcopy(capture["capture_lineage_ref"]),
        "displayed_image": {
            "sha256": displayed_image_sha256,
            "image_size": deepcopy(dict(displayed_image_size)),
        },
        "candidates": deepcopy(ledger["candidates"]),
        "warnings": warnings,
        "display_only": True,
        "review_only": True,
        "action_candidates": [],
        **_NON_AUTHORIZING,
    }
    base["projection_id"] = "hybrid-review-projection/" + sha256(
        canonical_json_bytes(base)
    ).hexdigest()
    return validate_hybrid_review_projection(seal_immutable(base))


def validate_hybrid_review_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one closed stored projection without trusting draft-derived data."""
    if not isinstance(value, Mapping):
        raise ValueError("Hybrid review projection must be an object")
    projection = deepcopy(dict(value))
    canonical_json_bytes(projection)
    validate_contract(projection, "hybrid_review_projection_v1")
    if projection.get("content_sha256") != content_sha256(projection):
        raise ValueError("Hybrid review projection content_sha256 mismatch")
    _require_non_authorizing(projection)
    if (
        projection.get("display_only") is not True
        or projection.get("review_only") is not True
        or projection.get("action_candidates") != []
    ):
        raise ValueError("Hybrid review projection is not read-only")
    expected_id = deepcopy(projection)
    expected_id.pop("content_sha256", None)
    expected_id["projection_id"] = ""
    if projection["projection_id"] != "hybrid-review-projection/" + sha256(
        canonical_json_bytes(expected_id)
    ).hexdigest():
        raise ValueError("Hybrid review projection_id mismatch")
    return projection


def render_hybrid_review_candidates(
    *, omni_ledger: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Create non-authorizing Large Review regions from a rebuilt ledger."""
    ledger = validate_omni_candidate_ledger(omni_ledger)
    items = {
        item["source_item_id"]: item
        for item in ledger["provider_result"]["items"]
    }
    return [
        _candidate_projection(
            ledger=ledger,
            candidate=candidate,
            item=items[candidate["source_item_id"]],
        )
        for candidate in ledger["candidates"]
    ]


def _candidate_projection(
    *, ledger: Mapping[str, Any], candidate: Mapping[str, Any], item: Mapping[str, Any]
) -> dict[str, Any]:
    bbox = deepcopy(candidate["bbox_original"])
    warnings: list[str] = []
    if candidate["confidence"] < 0.5:
        warnings.append("low_provider_confidence")
    if not candidate["active"]:
        warnings.append("inactive_candidate_visible_for_audit")
    return {
        "candidate_id": candidate["candidate_id"],
        "region_id": candidate["candidate_id"],
        "source_item_id": candidate["source_item_id"],
        "label": item.get("safe_text") or item.get("safe_role") or item["kind"],
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
            "provider_id": ledger["provider_id"],
            "profile_id": ledger["provider_result"]["profile_id"],
            "provider_revision": ledger["provider_revision"],
            "provider_result_ref": deepcopy(ledger["provider_result_ref"]),
            "capture_lineage_ref": deepcopy(ledger["capture_identity"]["capture_lineage_ref"]),
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


def _projection_warnings(candidates: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if any(candidate["confidence"] < 0.5 for candidate in candidates):
        warnings.append("low_provider_confidence")
    if any(not candidate["active"] for candidate in candidates):
        warnings.append("inactive_candidate_visible_for_audit")
    return warnings


def _require_display_binding(
    *, capture: Mapping[str, Any], displayed_image_sha256: str,
    displayed_image_size: Mapping[str, int],
) -> None:
    if displayed_image_sha256 != capture["screenshot_sha256"]:
        raise ValueError("displayed image SHA mismatch")
    if (
        not isinstance(displayed_image_size, Mapping)
        or dict(displayed_image_size) != capture["image_size"]
    ):
        raise ValueError("displayed image dimensions mismatch")


def _require_non_authorizing(value: Mapping[str, Any]) -> None:
    for field, expected in _NON_AUTHORIZING.items():
        if value.get(field) != expected or type(value.get(field)) is not type(expected):
            raise ValueError(f"non-authorizing invariant violated: {field}")


def _project_root(project_root: Path) -> Path:
    if not isinstance(project_root, Path):
        raise ValueError("project_root must be a Path")
    root = project_root.resolve()
    if not root.is_dir():
        raise ValueError("project_root must be a directory")
    return root
