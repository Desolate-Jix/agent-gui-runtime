"""Build the immutable, recall-first Omni candidate ledger."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re
from typing import Any

from app.learn.hybrid.contracts import (
    stable_candidate_id,
    validate_capture_identity,
    validate_omni_inventory,
)
from app.learn.recognition.uei.canonical import (
    canonical_json_bytes,
    content_sha256,
    seal_immutable,
)
from app.learn.recognition.uei.contracts import validate_contract


_OMNI_PROVIDER_ID = "local.runtime/omniparser"
_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}
_BASE_BUNDLE_FIELDS = {
    "contract_version",
    "bundle_id",
    "run_id",
    "workflow_revision",
    "capture_lineage_ref",
    "artifact_ref",
    "context_ref",
    "content_sha256",
    *_NON_AUTHORIZING,
}
_REF_FIELDS = {"id", "content_sha256"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def build_omni_candidate_ledger(
    *, safe_result: Mapping[str, Any], capture_bundle: Mapping[str, Any]
) -> dict[str, Any]:
    """Project every recorded Omni item into one stable, immutable inventory."""
    bundle = validate_current_capture_bundle(capture_bundle)
    if not isinstance(safe_result, Mapping):
        raise ValueError("safe_result must be an immutable object")
    result = deepcopy(dict(safe_result))
    canonical_json_bytes(result)
    validate_contract(result, "provider_safe_result_v1")
    if result.get("content_sha256") != content_sha256(result):
        raise ValueError("provider result content_sha256 mismatch")
    if (
        result.get("provider_id") != _OMNI_PROVIDER_ID
        or result.get("requested_provider_id") != _OMNI_PROVIDER_ID
        or not str(result.get("profile_id") or "").startswith(f"{_OMNI_PROVIDER_ID}/")
        or result.get("requested_profile_id") != result.get("profile_id")
        or result.get("status") != "success"
        or result.get("review_only") is not True
    ):
        raise ValueError("provider result is not a successful review-only Omni result")
    capture_identity = bundle["capture_identity"]
    if result.get("capture_lineage_ref") != capture_identity["capture_lineage_ref"]:
        raise ValueError("provider result capture lineage conflicts with current capture bundle")

    result_ref = {
        "id": result["result_id"],
        "content_sha256": result["content_sha256"],
    }
    items = result.get("items")
    if not isinstance(items, list):
        raise ValueError("provider result items must be a list")
    candidates: list[dict[str, Any]] = []
    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, Mapping):
            raise ValueError(f"provider result item[{index}] must be an object")
        item = deepcopy(dict(raw_item))
        source_item_id = item.get("source_item_id")
        if not isinstance(source_item_id, str) or not source_item_id:
            raise ValueError(f"provider result item[{index}] has no source_item_id")
        provenance = seal_immutable({
            "contract_version": "hybrid_candidate_provenance_v1",
            "provider_result_ref": result_ref,
            "source_item_id": source_item_id,
        })
        candidates.append({
            "candidate_id": stable_candidate_id(
                provider_result_ref=result_ref,
                source_item_id=source_item_id,
            ),
            "provider_result_ref": deepcopy(result_ref),
            "source_item_id": source_item_id,
            "bbox_original": deepcopy(item.get("capture_bbox")),
            "coordinate_space": "capture_pixel_xyxy",
            "confidence": item.get("provider_confidence"),
            "active": True,
            "inactive_reason": None,
            "provenance": provenance,
        })

    return validate_omni_inventory({
        "contract_version": "hybrid_omni_inventory_v1",
        "capture_identity": deepcopy(capture_identity),
        "provider_result_ref": result_ref,
        "provider_result": result,
        "provider_id": _OMNI_PROVIDER_ID,
        "provider_revision": result["provider_version"],
        "candidates": candidates,
        **_NON_AUTHORIZING,
    })


def validate_current_capture_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    """Revalidate the expanded result of Task 2 bundle loading before reuse."""
    if not isinstance(value, Mapping):
        raise ValueError("capture bundle must be an object")
    bundle = deepcopy(dict(value))
    allowed = _BASE_BUNDLE_FIELDS | {"capture_identity", "context", "bundle_ref"}
    actual_fields = set(bundle)
    if actual_fields != _BASE_BUNDLE_FIELDS | {"capture_identity", "context"} and actual_fields != allowed:
        raise ValueError("capture bundle is not a closed verified bundle")
    canonical_json_bytes(bundle)
    if bundle.get("contract_version") != "hybrid_capture_bundle_v1":
        raise ValueError("capture bundle contract_version is invalid")
    if bundle.get("content_sha256") != content_sha256(
        {key: child for key, child in bundle.items() if key not in {"capture_identity", "context", "bundle_ref"}}
    ):
        raise ValueError("capture bundle content_sha256 mismatch")
    _require_non_authorizing(bundle, name="capture bundle")
    capture = validate_capture_identity(bundle.get("capture_identity"))
    context = _validate_context(bundle.get("context"))
    if (
        bundle.get("capture_lineage_ref") != capture["capture_lineage_ref"]
        or bundle.get("artifact_ref") != capture["artifact_ref"]
        or context["capture_lineage_ref"] != capture["capture_lineage_ref"]
        or context["run_id"] != bundle.get("run_id")
        or context["workflow_revision"] != bundle.get("workflow_revision")
        or capture["workflow_revision"] != str(bundle.get("workflow_revision"))
    ):
        raise ValueError("capture bundle current capture identity mismatch")
    expected_context_ref = {"id": context["context_id"], "content_sha256": context["content_sha256"]}
    if bundle.get("context_ref") != expected_context_ref:
        raise ValueError("capture bundle context_ref mismatch")
    if "bundle_ref" in bundle:
        reference = _ref(bundle["bundle_ref"], name="bundle_ref")
        if reference != {"id": bundle.get("bundle_id"), "content_sha256": bundle.get("content_sha256")}:
            raise ValueError("capture bundle_ref mismatch")
    bundle["capture_identity"] = capture
    bundle["context"] = context
    return bundle


def _validate_context(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("capture bundle context must be an object")
    context = deepcopy(dict(value))
    required = {
        "contract_version", "context_id", "run_id", "workflow_revision",
        "capture_lineage_ref", "window_binding", "sources", "derived_views",
        "content_sha256", *_NON_AUTHORIZING,
    }
    if set(context) != required:
        raise ValueError("capture bundle context is not closed")
    if context.get("contract_version") != "hybrid_capture_context_v1":
        raise ValueError("capture bundle context contract_version is invalid")
    if context.get("content_sha256") != content_sha256(context):
        raise ValueError("capture bundle context content_sha256 mismatch")
    if not isinstance(context.get("context_id"), str) or not context["context_id"]:
        raise ValueError("capture bundle context_id is invalid")
    if not isinstance(context.get("run_id"), str) or not context["run_id"]:
        raise ValueError("capture bundle context run_id is invalid")
    if isinstance(context.get("workflow_revision"), bool) or not isinstance(context.get("workflow_revision"), int):
        raise ValueError("capture bundle context workflow_revision is invalid")
    _ref(context.get("capture_lineage_ref"), name="context capture_lineage_ref")
    if not isinstance(context.get("sources"), list) or not isinstance(context.get("derived_views"), list):
        raise ValueError("capture bundle context evidence lists are invalid")
    _require_non_authorizing(context, name="capture bundle context")
    return context


def _ref(value: object, *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _REF_FIELDS:
        raise ValueError(f"{name} must be a closed immutable ref")
    identifier, digest = value.get("id"), value.get("content_sha256")
    if not isinstance(identifier, str) or not identifier or not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{name} is invalid")
    return {"id": identifier, "content_sha256": digest}


def _require_non_authorizing(value: Mapping[str, Any], *, name: str) -> None:
    for field, expected in _NON_AUTHORIZING.items():
        if value.get(field) != expected or type(value.get(field)) is not type(expected):
            raise ValueError(f"{name} violates non-authorizing invariant: {field}")
