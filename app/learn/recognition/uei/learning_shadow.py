"""Immutable-ref-only UEI Shadow summaries for Learning Draft review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.store import UEIObjectStore


_STORE_RELATIVE_PATH = Path("artifacts") / "uei-shadow-store"
_REF_KEYS = frozenset({"id", "content_sha256"})


def load_uei_shadow_provider_summary(
    draft: dict[str, Any], *, project_root: Path,
    current_capture_lineage_ref: dict[str, str] | None = None,
) -> dict[str, object] | None:
    """Revalidate the only accepted cached ref against the fixed Shadow store."""
    reference = _result_ref_from_draft(draft)
    if reference is None:
        return None
    if not _is_ref(reference):
        return _empty_summary(status="invalid")
    store_path = project_root / _STORE_RELATIVE_PATH
    if not store_path.is_dir():
        return _empty_summary(status="unavailable")
    try:
        store = UEIObjectStore(root=store_path)
        result = store.get(reference, contract_version="provider_safe_result_v1")
        return _summary_from_result(store=store, result=result, current_capture_lineage_ref=current_capture_lineage_ref)
    except (UEIValidationError, OSError, TypeError, ValueError):
        return _empty_summary(status="invalid")


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
) -> dict[str, object]:
    status = result.get("status")
    if status not in {"success", "failed"}:
        raise UEIValidationError("shadow_result_status_invalid")
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
