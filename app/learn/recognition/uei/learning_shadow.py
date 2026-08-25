"""Immutable-ref-only UEI Shadow summaries and safe Learning Review regions."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
from app.learn.hybrid.omni_candidates import build_omni_candidate_ledger
from app.learn.hybrid.review_projection import (
    build_hybrid_review_projection,
    render_full_parent_hybrid_review_candidates,
    render_hybrid_review_candidates,
    validate_hybrid_review_projection,
)
from app.learn.recognition.bbox_alignment import bbox_overlap, cross_evidence_overlap_is_acceptable
from app.learn.recognition.uei.canonical import canonical_json_bytes
from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.store import UEIObjectStore


_STORE_RELATIVE_PATH = Path("artifacts") / "uei-shadow-store"
_REF_KEYS = frozenset({"id", "content_sha256"})


def load_hybrid_large_review_projection(
    projection_ref: object,
    *,
    project_root: Path,
    expected_hybrid_run_id: str | None,
    expected_hybrid_workflow_revision: int | None,
    expected_current_capture_lineage_ref: dict[str, str] | None,
    current_capture_lineage_ref: dict[str, str] | None,
    displayed_source_sha256: str | None,
    displayed_source_size: dict[str, int] | None,
    existing_region_ids: set[str],
) -> dict[str, object] | None:
    """Resolve every Hybrid parent from UEI storage before rendering regions."""
    if projection_ref is None:
        return None
    if (
        not isinstance(expected_hybrid_run_id, str)
        or not expected_hybrid_run_id
        or isinstance(expected_hybrid_workflow_revision, bool)
        or not isinstance(expected_hybrid_workflow_revision, int)
        or expected_hybrid_workflow_revision < 0
    ):
        return _invalid_hybrid_review("hybrid_expectations_missing")
    if (
        not isinstance(displayed_source_sha256, str)
        or not isinstance(displayed_source_size, dict)
    ):
        return _invalid_hybrid_review("hybrid_projection_context_invalid")
    try:
        if (
            isinstance(projection_ref, dict)
            and projection_ref.get("contract_version") == "hybrid_review_projection_v2"
        ):
            if not _is_ref(expected_current_capture_lineage_ref):
                return _invalid_hybrid_review("hybrid_expectations_missing")
            stored_projection = validate_hybrid_review_projection(projection_ref)
            parent_bundle = stored_projection["parent_evidence"]["capture_bundle"]
            screen = stored_projection["screen_facts"]
            displayed = screen["displayed_image"]
            projected_lineage = screen["capture_lineage_ref"]
            if (
                not _is_ref(current_capture_lineage_ref)
                or current_capture_lineage_ref != expected_current_capture_lineage_ref
                or projected_lineage != expected_current_capture_lineage_ref
            ):
                return _invalid_hybrid_review("hybrid_current_capture_lineage_mismatch")
            if (
                parent_bundle.get("run_id") != expected_hybrid_run_id
                or parent_bundle.get("workflow_revision")
                != expected_hybrid_workflow_revision
                or displayed.get("sha256") != displayed_source_sha256
                or displayed.get("image_size") != displayed_source_size
            ):
                return _invalid_hybrid_review("hybrid_projection_evidence_mismatch")
            regions = render_full_parent_hybrid_review_candidates(stored_projection)
            generated = [str(region.get("region_id") or "") for region in regions]
            if len(generated) != len(set(generated)) or set(generated) & existing_region_ids:
                return _invalid_hybrid_review("hybrid_region_id_collision")
            return {
                "projection": deepcopy(stored_projection),
                "status": _hybrid_review_status(status="projected", reason=None),
                "regions": deepcopy(regions),
            }
        if not _is_ref(projection_ref):
            return _invalid_hybrid_review("hybrid_projection_context_invalid")
        store = UEIObjectStore(root=project_root / _STORE_RELATIVE_PATH)
        stored_projection = validate_hybrid_review_projection(store.get(
            projection_ref,
            contract_version="hybrid_review_projection_v1",
        ))
        bundle_ref = deepcopy(stored_projection["hybrid_capture_bundle_ref"])
        bundle = load_and_verify_hybrid_capture_bundle(
            project_root=project_root,
            bundle_ref=bundle_ref,
            expected_run_id=expected_hybrid_run_id,
            expected_workflow_revision=expected_hybrid_workflow_revision,
        )
        bundle["bundle_ref"] = bundle_ref
        provider_result = store.get(
            stored_projection["provider_result_ref"],
            contract_version="provider_safe_result_v1",
        )
        ledger = build_omni_candidate_ledger(
            safe_result=provider_result,
            capture_bundle=bundle,
        )
        rebuilt_projection = build_hybrid_review_projection(
            omni_ledger=ledger,
            displayed_image_sha256=displayed_source_sha256,
            displayed_image_size=displayed_source_size,
        )
        if canonical_json_bytes(rebuilt_projection) != canonical_json_bytes(stored_projection):
            return _invalid_hybrid_review("hybrid_projection_evidence_mismatch")
        regions = render_hybrid_review_candidates(omni_ledger=ledger)
        generated = [str(region.get("region_id") or "") for region in regions]
        if len(generated) != len(set(generated)) or set(generated) & existing_region_ids:
            return _invalid_hybrid_review("hybrid_region_id_collision")
        return {
            "projection_ref": deepcopy(dict(projection_ref)),
            "projection": deepcopy(rebuilt_projection),
            "status": _hybrid_review_status(status="projected", reason=None),
            "regions": deepcopy(regions),
        }
    except (OSError, TypeError, ValueError):
        return _invalid_hybrid_review("hybrid_projection_evidence_mismatch")


def _invalid_hybrid_review(reason: str) -> dict[str, object]:
    return {
        "status": _hybrid_review_status(status="rejected", reason=reason),
        "regions": [],
    }


def _hybrid_review_status(*, status: str, reason: str | None) -> dict[str, object]:
    return {
        "contract_version": "hybrid_large_review_projection_status_v1",
        "status": status,
        "reason": reason,
        "display_only": True,
        "review_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "authorization_scope": "display_and_review_only",
        "action_candidates": [],
    }


def load_uei_shadow_provider_summary(
    draft: dict[str, Any], *, project_root: Path,
    current_capture_lineage_ref: dict[str, str] | None = None,
) -> dict[str, object] | None:
    """Revalidate the only accepted cached ref against the fixed Shadow store."""
    review = load_uei_shadow_provider_review(
        draft,
        project_root=project_root,
        current_capture_lineage_ref=current_capture_lineage_ref,
    )
    return None if review is None else review["summary"]


def load_uei_shadow_provider_review(
    draft: dict[str, Any],
    *,
    project_root: Path,
    current_capture_lineage_ref: dict[str, str] | None = None,
    current_capture_lineage_error: str | None = None,
    existing_region_ids: set[str] | None = None,
    uia_support_items: list[dict[str, object]] | None = None,
    displayed_source_sha256: str | None = None,
    displayed_source_size: dict[str, int] | None = None,
) -> dict[str, object] | None:
    """Project revalidated current-capture safe items into review-only regions."""
    reference = _result_ref_from_draft(draft)
    if reference is None:
        return None
    if not _is_ref(reference):
        return _invalid_review(reason="immutable_result_ref_invalid")
    store_path = project_root / _STORE_RELATIVE_PATH
    if not store_path.is_dir():
        return _invalid_review(status="unavailable", reason="immutable_store_unavailable")
    try:
        store = UEIObjectStore(root=store_path)
        result = store.get(reference, contract_version="provider_safe_result_v1")
        capture = _validated_capture(store=store, result=result)
        summary = _summary_from_result(
            store=store,
            result=result,
            current_capture_lineage_ref=current_capture_lineage_ref,
            capture=capture,
        )
        regions, projection = _project_review_regions(
            result=result,
            capture=capture,
            current_capture_lineage_ref=current_capture_lineage_ref,
            current_capture_lineage_error=current_capture_lineage_error,
            existing_region_ids=existing_region_ids or set(),
            uia_support_items=uia_support_items or [],
            displayed_source_sha256=displayed_source_sha256,
            displayed_source_size=displayed_source_size,
        )
        return {"summary": summary, "projection": projection, "regions": regions}
    except (UEIValidationError, OSError, TypeError, ValueError):
        return _invalid_review(reason="immutable_result_invalid")


def strip_uei_shadow_review_cache(draft: dict[str, Any]) -> None:
    """Remove cached refs and summaries before returning a draft to the panel."""
    draft.pop("uei_shadow_result_ref", None)
    draft.pop("uei_shadow_provider_summary", None)
    page_details = draft.get("page_details")
    if isinstance(page_details, dict):
        page_details.pop("uei_shadow_result_ref", None)
        page_details.pop("uei_shadow_provider_summary", None)


def _result_ref_from_draft(draft: dict[str, Any]) -> object | None:
    direct = draft.get("uei_shadow_result_ref")
    if direct is not None:
        return direct
    page_details = draft.get("page_details")
    return page_details.get("uei_shadow_result_ref") if isinstance(page_details, dict) else None


def _is_ref(value: object) -> bool:
    return (
        isinstance(value, dict) and set(value) == _REF_KEYS
        and isinstance(value.get("id"), str) and bool(value["id"])
        and isinstance(value.get("content_sha256"), str) and len(value["content_sha256"]) == 64
    )


def _summary_from_result(
    *, store: UEIObjectStore, result: dict[str, object],
    current_capture_lineage_ref: dict[str, str] | None,
    capture: dict[str, object] | None = None,
) -> dict[str, object]:
    status = result.get("status")
    if status not in {"success", "failed"}:
        raise UEIValidationError("shadow_result_status_invalid")
    capture_ref = result.get("capture_lineage_ref")
    if not _is_ref(capture_ref):
        raise UEIValidationError("shadow_capture_ref_invalid")
    capture = capture or _validated_capture(store=store, result=result)
    error_summary: dict[str, str] | None = None
    if status == "failed":
        error_ref = result.get("error_ref")
        if not _is_ref(error_ref):
            raise UEIValidationError("shadow_error_ref_invalid")
        error = store.get(error_ref, contract_version="provider_error_v1")
        stage, code = error.get("stage"), error.get("code")
        if not isinstance(stage, str) or not isinstance(code, str):
            raise UEIValidationError("shadow_error_invalid")
        error_summary = {"stage": stage, "code": code}
    redaction = result.get("redaction_summary")
    if not isinstance(redaction, dict):
        raise UEIValidationError("shadow_redaction_invalid")
    content_hash = result.get("content_sha256")
    if not isinstance(content_hash, str) or len(content_hash) != 64:
        raise UEIValidationError("shadow_identity_invalid")
    summary = {
        "contract_version": "uei_shadow_provider_summary_v1",
        "status": status,
        "provider_id": result.get("provider_id"),
        "profile_id": result.get("profile_id"),
        "provider_version": result.get("provider_version"),
        "item_count": len(result.get("items") if isinstance(result.get("items"), list) else []),
        "registration_resolution": result.get("registration_resolution"),
        "manifest_resolution": result.get("manifest_resolution"),
        "capture_match_status": _capture_status(capture_ref, current_capture_lineage_ref),
        "redaction": {
            "redacted_item_count": redaction.get("redacted_item_count"),
            "redacted_field_count": redaction.get("redacted_field_count"),
            "secret_detected": redaction.get("secret_detected"),
            "sensitive_category_count": len(redaction.get("sensitive_categories") if isinstance(redaction.get("sensitive_categories"), list) else []),
        },
        "safe_error": error_summary,
        "immutable_identity": f"sha256:{content_hash[:12]}",
        **_safety_fields(),
    }
    return summary


def _validated_capture(
    *, store: UEIObjectStore, result: dict[str, object],
) -> dict[str, object]:
    capture_ref = result.get("capture_lineage_ref")
    if not _is_ref(capture_ref):
        raise UEIValidationError("shadow_capture_ref_invalid")
    capture = store.get(capture_ref, contract_version="capture_lineage_v1")
    artifact_ref = capture.get("artifact_ref")
    if not _is_ref(artifact_ref):
        raise UEIValidationError("shadow_artifact_ref_invalid")
    artifact = store.get(artifact_ref, contract_version="artifact_ref_v1")
    if (capture.get("artifact_sha256") != artifact.get("artifact_sha256")
            or not isinstance(artifact.get("byte_length"), int)
            or artifact["byte_length"] < 1):
        raise UEIValidationError("shadow_capture_artifact_invalid")
    return capture


def _project_review_regions(
    *,
    result: dict[str, object],
    capture: dict[str, object],
    current_capture_lineage_ref: dict[str, str] | None,
    current_capture_lineage_error: str | None,
    existing_region_ids: set[str],
    uia_support_items: list[dict[str, object]],
    displayed_source_sha256: str | None,
    displayed_source_size: dict[str, int] | None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    capture_ref = result.get("capture_lineage_ref")
    base = _projection_metadata(result=result)
    if result.get("status") != "success":
        return [], {**base, "status": "rejected", "reason": "result_not_success"}
    if result.get("review_only") is not True:
        return [], {**base, "status": "rejected", "reason": "result_not_review_only"}
    if current_capture_lineage_error == "current_capture_lineage_ambiguous":
        return [], {
            **base,
            "status": "rejected",
            "reason": "current_capture_lineage_ambiguous",
        }
    if not _is_ref(current_capture_lineage_ref):
        return [], {**base, "status": "rejected", "reason": "current_capture_lineage_missing"}
    if current_capture_lineage_ref != capture_ref:
        return [], {
            **base,
            "status": "rejected",
            "reason": "capture_lineage_mismatch",
            "capture_match_status": "mismatch",
        }
    base = {**base, "capture_match_status": "match"}
    image_size = capture.get("image_size")
    if not isinstance(image_size, dict):
        return [], {**base, "status": "rejected", "reason": "capture_image_size_invalid"}
    width, height = image_size.get("width"), image_size.get("height")
    if not all(isinstance(edge, int) and not isinstance(edge, bool) and edge > 0 for edge in (width, height)):
        return [], {**base, "status": "rejected", "reason": "capture_image_size_invalid"}
    if (
        not isinstance(displayed_source_sha256, str)
        or not displayed_source_sha256
        or not isinstance(displayed_source_size, dict)
    ):
        return [], {**base, "status": "rejected", "reason": "displayed_source_image_missing"}
    displayed_width = displayed_source_size.get("width")
    displayed_height = displayed_source_size.get("height")
    if (displayed_width, displayed_height) != (width, height):
        return [], {
            **base,
            "status": "rejected",
            "reason": "displayed_source_image_dimensions_mismatch",
        }
    if displayed_source_sha256 != capture.get("artifact_sha256"):
        return [], {
            **base,
            "status": "rejected",
            "reason": "displayed_source_image_hash_mismatch",
        }
    items = result.get("items")
    if not isinstance(items, list):
        return [], {**base, "status": "rejected", "reason": "result_items_invalid"}

    regions: list[dict[str, object]] = []
    source_ids: set[str] = set()
    semantic_boxes: set[tuple[object, ...]] = set()
    generated_ids: set[str] = set()
    skipped_item_count = 0
    for item in items:
        if not isinstance(item, dict):
            return [], {**base, "status": "rejected", "reason": "result_item_invalid"}
        source_item_id = item.get("source_item_id")
        if not isinstance(source_item_id, str) or not source_item_id:
            return [], {**base, "status": "rejected", "reason": "source_item_id_invalid"}
        if source_item_id in source_ids:
            return [], {**base, "status": "rejected", "reason": "duplicate_source_item_id"}
        source_ids.add(source_item_id)
        text = item.get("safe_text")
        role = item.get("safe_role")
        states = item.get("safe_states")
        kind = item.get("kind")
        if (
            not isinstance(text, (str, type(None)))
            or not isinstance(role, (str, type(None)))
            or not isinstance(states, list)
            or not all(isinstance(state, str) for state in states)
            or not isinstance(kind, str)
        ):
            return [], {**base, "status": "rejected", "reason": "item_semantics_invalid"}
        bbox = item.get("capture_bbox")
        if bbox is None:
            skipped_item_count += 1
            continue
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(edge, int) and not isinstance(edge, bool) for edge in bbox)
        ):
            return [], {**base, "status": "rejected", "reason": "item_review_box_invalid"}
        left, top, right, bottom = bbox
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            return [], {**base, "status": "rejected", "reason": "item_review_box_out_of_range"}
        semantic_box = (
            text.strip().casefold() if isinstance(text, str) else "",
            role.strip().casefold() if isinstance(role, str) else "",
            kind.casefold(),
            *bbox,
        )
        if semantic_box in semantic_boxes:
            return [], {**base, "status": "rejected", "reason": "ambiguous_duplicate_semantic_box"}
        semantic_boxes.add(semantic_box)
        region_id = _review_region_id(
            result=result,
            source_item_id=source_item_id,
            semantic_box=semantic_box,
        )
        if region_id in existing_region_ids or region_id in generated_ids:
            return [], {**base, "status": "rejected", "reason": "region_id_collision"}
        generated_ids.add(region_id)
        confidence = item.get("provider_confidence")
        label = text.strip() if isinstance(text, str) and text.strip() else (
            role.strip() if isinstance(role, str) and role.strip() else kind
        )
        provider_evidence = {
            "provider_id": result.get("provider_id"),
            "profile_id": result.get("profile_id"),
            "provider_version": result.get("provider_version"),
            "confidence": confidence,
            "safe_role": role,
            "safe_states": list(states),
        }
        cross_evidence = _uia_cross_evidence(
            bbox={"x": left, "y": top, "w": right - left, "h": bottom - top},
            support_items=uia_support_items,
        )
        if cross_evidence is not None:
            provider_evidence["cross_evidence"] = cross_evidence
            if cross_evidence.get("status") == "uia_supported":
                provider_evidence["canonical_role"] = cross_evidence["support_role"]
        regions.append({
            "region_id": region_id,
            "label": label,
            "role": "review_only",
            "kind": kind,
            "bbox": {"x": left, "y": top, "w": right - left, "h": bottom - top},
            "provider_evidence": provider_evidence,
            "source": "uei_provider_safe_result_v1",
            "candidate_only": True,
            "requires_human_review": True,
            "review_only": True,
            "grounding_eligible": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "action_candidates": [],
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
        })
    return regions, {
        **base,
        "status": "projected",
        "reason": None,
        "region_count": len(regions),
        "skipped_item_count": skipped_item_count,
        "safe_reason_counts": (
            {"ungrounded_item": skipped_item_count}
            if skipped_item_count
            else {}
        ),
    }


def _uia_cross_evidence(
    *, bbox: dict[str, int], support_items: list[dict[str, object]],
) -> dict[str, object] | None:
    matches: list[tuple[dict[str, object], dict[str, float]]] = []
    for item in support_items:
        if not isinstance(item, dict):
            continue
        sources = item.get("source_evidence")
        if not isinstance(sources, list) or "uia" not in {str(source).casefold() for source in sources}:
            continue
        support_bbox = item.get("bbox")
        role = str(item.get("role") or "").strip().casefold()
        item_id = str(item.get("item_id") or item.get("id") or "").strip()
        if (
            not isinstance(support_bbox, dict)
            or role not in {"button", "link", "input", "checkbox", "menu_item", "tab"}
            or not item_id
        ):
            continue
        overlap = bbox_overlap(bbox, support_bbox)
        if cross_evidence_overlap_is_acceptable(overlap):
            matches.append((item, overlap))
    if not matches:
        return None
    if len(matches) != 1:
        return {"status": "ambiguous"}
    support, overlap = matches[0]
    return {
        "status": "uia_supported",
        "support_item_id": str(support.get("item_id") or support.get("id")),
        "support_sources": ["uia"],
        "support_role": str(support.get("role") or "").strip().casefold(),
        "iou": overlap["iou"],
        "candidate_coverage": overlap["vision_coverage"],
        "support_coverage": overlap["support_coverage"],
    }


def _review_region_id(
    *, result: dict[str, object], source_item_id: str, semantic_box: tuple[object, ...],
) -> str:
    identity = {
        "provider_id": result.get("provider_id"),
        "profile_id": result.get("profile_id"),
        "provider_version": result.get("provider_version"),
        "capture_lineage_ref": result.get("capture_lineage_ref"),
        "source_item_id": source_item_id,
        "semantic_box": list(semantic_box),
    }
    digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return f"uei_review_region_{digest[:24]}"


def _projection_metadata(*, result: dict[str, object]) -> dict[str, object]:
    return {
        "contract_version": "uei_shadow_review_projection_v1",
        "status": "rejected",
        "reason": None,
        "provider_id": result.get("provider_id"),
        "profile_id": result.get("profile_id"),
        "provider_version": result.get("provider_version"),
        "capture_match_status": "unknown",
        "region_count": 0,
        "skipped_item_count": 0,
        "safe_reason_counts": {},
        "display_only": True,
        "review_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "action_candidates": [],
    }


def _invalid_review(
    *, status: str = "invalid", reason: str,
) -> dict[str, object]:
    return {
        "summary": _empty_summary(status=status),
        "projection": {
            "contract_version": "uei_shadow_review_projection_v1",
            "status": "rejected",
            "reason": reason,
            "capture_match_status": "unknown",
            "region_count": 0,
            "skipped_item_count": 0,
            "safe_reason_counts": {},
            "display_only": True,
            "review_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "action_candidates": [],
        },
        "regions": [],
    }


def _capture_status(result_ref: dict[str, str], current_ref: dict[str, str] | None) -> str:
    if current_ref is None or not _is_ref(current_ref):
        return "historical"
    return "match" if current_ref == result_ref else "mismatch"


def _empty_summary(*, status: str) -> dict[str, object]:
    return {
        "contract_version": "uei_shadow_provider_summary_v1", "status": status,
        "capture_match_status": "unknown", "item_count": 0,
        **_safety_fields(),
    }


def _safety_fields() -> dict[str, object]:
    return {
        "display_only": True, "review_only": True, "execution_authorized": False,
        "artifact_is_authorization": False, "execute_binding_enabled": False,
        "action_candidates": [],
    }
