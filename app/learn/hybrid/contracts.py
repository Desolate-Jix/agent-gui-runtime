"""Closed, non-authorizing Portfolio Hybrid v1.1 evidence contracts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256
from app.learn.recognition.uei.contracts import validate_contract


CAPTURE_CONTRACT = "hybrid_capture_identity_v1"
OMNI_CONTRACT = "hybrid_omni_inventory_v1"
QWEN_CONTRACT = "hybrid_qwen_bindings_v1"
FUSION_CONTRACT = "hybrid_fusion_result_v1"
VISTA_CONTRACT = "hybrid_vista_proposals_v1"
COORDINATE_SPACE = "capture_pixel_xyxy"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}
_NON_AUTHORIZING_FIELDS = frozenset(_NON_AUTHORIZING)
_AUTHORITY_SHAPED_FIELDS = frozenset(
    {
        "action_authorized",
        "approved_to_click",
        "approved_to_execute",
        "click_authorized",
        "execute",
        "final_submit",
        "submit_authorized",
    }
)
_GEOMETRY_FIELDS = frozenset(
    {
        "bbox",
        "bbox_original",
        "candidate_bbox",
        "candidate_bbox_ref",
        "coordinate_space",
        "geometry",
        "point",
        "refined_point",
        "roi",
        "roi_ref",
        "xy",
        "xyxy",
    }
)
_FUSION_STATE_ORDER = (
    "BOUND",
    "AMBIGUOUS",
    "CONFLICT",
    "ORPHAN",
    "ORPHAN_SEMANTIC",
    "LOW_CONFIDENCE",
    "UNBOUND",
    "CAPTURE_MISMATCH",
    "REVIEW_REQUIRED",
)
_FUSION_STATES = frozenset(_FUSION_STATE_ORDER)


def _object(value: Any, *, name: str, fields: set[str] | frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result = deepcopy(dict(value))
    actual = set(result)
    if actual != set(fields):
        missing = sorted(set(fields) - actual)
        unknown = sorted(actual - set(fields))
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        raise ValueError(f"{name} is not closed ({'; '.join(details)})")
    return result


def _string(value: Any, *, name: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _sha256(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _finite_number(value: Any, *, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _confidence(value: Any, *, name: str) -> int | float:
    result = _finite_number(value, name=name)
    if result < 0 or result > 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _image_size(value: Any, *, name: str) -> dict[str, int]:
    result = _object(value, name=name, fields={"width", "height"})
    for field in ("width", "height"):
        child = result[field]
        if isinstance(child, bool) or not isinstance(child, int) or child <= 0:
            raise ValueError(f"{name}.{field} must be a positive integer")
    return result


def _coordinate_space(value: Any, *, name: str) -> str:
    if value != COORDINATE_SPACE:
        raise ValueError(f"{name} must be {COORDINATE_SPACE}")
    return COORDINATE_SPACE


def _xyxy(value: Any, *, name: str) -> list[int | float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{name} must be a four-number xyxy list")
    result = [_finite_number(child, name=f"{name}[{index}]") for index, child in enumerate(value)]
    if result[0] >= result[2] or result[1] >= result[3]:
        raise ValueError(f"{name} must have x1 < x2 and y1 < y2")
    return result


def _point(value: Any, *, name: str) -> list[int | float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be a two-number xy list")
    return [_finite_number(child, name=f"{name}[{index}]") for index, child in enumerate(value)]


def _ref(value: Any, *, name: str) -> dict[str, str]:
    result = _object(value, name=name, fields={"id", "content_sha256"})
    _string(result["id"], name=f"{name}.id")
    _sha256(result["content_sha256"], name=f"{name}.content_sha256")
    return result


def _non_authorizing(value: Mapping[str, Any], *, name: str) -> None:
    for field, expected in _NON_AUTHORIZING.items():
        if value.get(field) != expected or type(value.get(field)) is not type(expected):
            raise ValueError(f"{name} violates non-authorizing invariant: {field}")


def _same_capture(left: Mapping[str, Any], right: Mapping[str, Any]) -> None:
    if canonical_json_bytes(left) != canonical_json_bytes(right):
        raise ValueError("conflicting capture identity")


def _canonical_return(value: dict[str, Any], *, name: str) -> dict[str, Any]:
    try:
        canonical_json_bytes(value)
    except ValueError as error:
        raise ValueError(f"{name} is not canonical JSON: {error}") from error
    return value


def _sealed_content(value: Mapping[str, Any], *, name: str) -> str:
    declared = _sha256(value.get("content_sha256"), name=f"{name}.content_sha256")
    try:
        actual = content_sha256(dict(value))
    except ValueError as error:
        raise ValueError(f"{name} is not canonical JSON: {error}") from error
    if declared != actual:
        raise ValueError(f"{name} content_sha256 mismatch")
    return declared


def _reject_authority_shaped(value: Any, *, name: str) -> None:
    if isinstance(value, Mapping):
        forbidden = set(value) & _AUTHORITY_SHAPED_FIELDS
        if forbidden:
            raise ValueError(
                f"{name} contains authority-shaped field: {sorted(forbidden)[0]}"
            )
        for child in value.values():
            _reject_authority_shaped(child, name=name)
    elif isinstance(value, list):
        for child in value:
            _reject_authority_shaped(child, name=name)


def stable_candidate_id(
    *, provider_result_ref: Mapping[str, str], source_item_id: str
) -> str:
    reference = _ref(provider_result_ref, name="provider_result_ref")
    _string(source_item_id, name="source_item_id")
    payload = {"provider_result_ref": reference, "source_item_id": source_item_id}
    return "candidate/" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def validate_capture_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "contract_version",
        "capture_id",
        "capture_lineage_ref",
        "capture_lineage",
        "artifact_ref",
        "artifact",
        "artifact_sha256",
        "screenshot_sha256",
        "image_size",
        "capture_coordinate_space",
        "captured_at",
        "workflow_revision",
    }
    result = _object(value, name="capture identity", fields=fields)
    if result["contract_version"] != CAPTURE_CONTRACT:
        raise ValueError(f"capture identity contract_version must be {CAPTURE_CONTRACT}")
    for field in ("capture_id", "captured_at", "workflow_revision"):
        _string(result[field], name=f"capture identity.{field}")
    artifact_sha = _sha256(result["artifact_sha256"], name="capture identity.artifact_sha256")
    screenshot_sha = _sha256(
        result["screenshot_sha256"], name="capture identity.screenshot_sha256"
    )
    if artifact_sha != screenshot_sha:
        raise ValueError("artifact_sha256 must equal screenshot_sha256")
    size = _image_size(result["image_size"], name="capture identity.image_size")
    _coordinate_space(
        result["capture_coordinate_space"], name="capture identity.capture_coordinate_space"
    )
    reference = _ref(result["capture_lineage_ref"], name="capture_lineage_ref")
    lineage_fields = {
        "contract_version",
        "capture_id",
        "artifact_ref",
        "artifact_sha256",
        "image_size",
        "capture_coordinate_space",
        "captured_at",
        "content_sha256",
    }
    lineage = _object(result["capture_lineage"], name="capture lineage", fields=lineage_fields)
    if lineage["contract_version"] != "capture_lineage_v1":
        raise ValueError("capture lineage contract_version must be capture_lineage_v1")
    validate_contract(lineage, "capture_lineage_v1")
    _string(lineage["capture_id"], name="capture lineage.capture_id")
    declared_hash = _sha256(lineage["content_sha256"], name="capture lineage.content_sha256")
    if declared_hash != content_sha256(lineage):
        raise ValueError("capture lineage content_sha256 mismatch")
    if reference != {"id": lineage["capture_id"], "content_sha256": declared_hash}:
        raise ValueError("capture_lineage_ref does not resolve to capture lineage")
    lineage_artifact_ref = _ref(
        lineage["artifact_ref"], name="capture lineage.artifact_ref"
    )
    artifact_ref = _ref(result["artifact_ref"], name="capture identity.artifact_ref")
    if lineage_artifact_ref != artifact_ref:
        raise ValueError("lineage artifact_ref mismatch")
    artifact_fields = {
        "contract_version",
        "artifact_id",
        "artifact_sha256",
        "media_type",
        "byte_length",
        "restricted",
        "content_sha256",
    }
    artifact = _object(result["artifact"], name="capture artifact", fields=artifact_fields)
    if artifact["contract_version"] != "artifact_ref_v1":
        raise ValueError("capture artifact contract_version must be artifact_ref_v1")
    validate_contract(artifact, "artifact_ref_v1")
    artifact_id = _string(artifact["artifact_id"], name="capture artifact.artifact_id")
    artifact_content_sha = _sha256(
        artifact["content_sha256"], name="capture artifact.content_sha256"
    )
    if artifact_content_sha != content_sha256(artifact):
        raise ValueError("capture artifact content_sha256 mismatch")
    if artifact_ref != {"id": artifact_id, "content_sha256": artifact_content_sha}:
        raise ValueError("artifact_ref does not resolve to capture artifact")
    resolved_artifact_sha = _sha256(
        artifact["artifact_sha256"], name="capture artifact.artifact_sha256"
    )
    media_type = _string(artifact["media_type"], name="capture artifact.media_type")
    if not media_type.startswith("image/"):
        raise ValueError("capture artifact.media_type must be an image")
    byte_length = artifact["byte_length"]
    if isinstance(byte_length, bool) or not isinstance(byte_length, int) or byte_length <= 0:
        raise ValueError("capture artifact.byte_length must be a positive integer")
    if artifact["restricted"] is not True:
        raise ValueError("capture artifact must remain restricted")
    lineage_artifact_sha = _sha256(
        lineage["artifact_sha256"], name="capture lineage.artifact_sha256"
    )
    if {lineage_artifact_sha, resolved_artifact_sha} != {screenshot_sha}:
        raise ValueError("lineage artifact SHA mismatch")
    lineage_size = _image_size(lineage["image_size"], name="capture lineage.image_size")
    if lineage_size != size:
        raise ValueError("lineage image_size mismatch")
    _coordinate_space(
        lineage["capture_coordinate_space"], name="capture lineage.capture_coordinate_space"
    )
    for field in ("capture_id", "captured_at"):
        if lineage[field] != result[field]:
            raise ValueError(f"lineage {field} mismatch")
    return _canonical_return(result, name="capture identity")


def validate_omni_inventory(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "contract_version",
        "capture_identity",
        "provider_result_ref",
        "provider_result",
        "provider_id",
        "provider_revision",
        "candidates",
    } | set(_NON_AUTHORIZING_FIELDS)
    result = _object(value, name="Omni inventory", fields=fields)
    if result["contract_version"] != OMNI_CONTRACT:
        raise ValueError(f"Omni inventory contract_version must be {OMNI_CONTRACT}")
    _non_authorizing(result, name="Omni inventory")
    result["capture_identity"] = validate_capture_identity(result["capture_identity"])
    provider_ref = _ref(result["provider_result_ref"], name="provider_result_ref")
    provider_id = _string(result["provider_id"], name="provider_id")
    provider_revision = _string(result["provider_revision"], name="provider_revision")
    if not isinstance(result["provider_result"], Mapping):
        raise ValueError("provider_result must be an immutable object")
    provider_result = deepcopy(dict(result["provider_result"]))
    validate_contract(provider_result, "provider_safe_result_v1")
    _reject_authority_shaped(provider_result, name="provider result")
    provider_hash = _sealed_content(provider_result, name="provider result")
    if provider_ref != {
        "id": provider_result.get("result_id"),
        "content_sha256": provider_hash,
    }:
        raise ValueError("provider_result_ref does not resolve to provider result")
    if (
        provider_result.get("capture_lineage_ref")
        != result["capture_identity"]["capture_lineage_ref"]
    ):
        raise ValueError("provider result capture identity mismatch")
    if (
        provider_result.get("provider_id") != provider_id
        or provider_result.get("requested_provider_id") != provider_id
        or provider_result.get("provider_version") != provider_revision
        or provider_result.get("status") != "success"
        or provider_result.get("review_only") is not True
    ):
        raise ValueError("provider result identity or review boundary mismatch")
    result["provider_result"] = provider_result
    provider_items = provider_result.get("items")
    if not isinstance(provider_items, list):
        raise ValueError("provider result items must be a list")
    provider_items_by_id: dict[str, dict[str, Any]] = {}
    for item in provider_items:
        if not isinstance(item, dict):
            raise ValueError("provider result item must be an object")
        source_id = _string(item.get("source_item_id"), name="provider source_item_id")
        if source_id in provider_items_by_id:
            raise ValueError("duplicate provider source_item_id")
        provider_items_by_id[source_id] = item
    if not isinstance(result["candidates"], list):
        raise ValueError("Omni inventory.candidates must be a list")
    candidate_fields = {
        "candidate_id",
        "provider_result_ref",
        "source_item_id",
        "bbox_original",
        "coordinate_space",
        "confidence",
        "active",
        "inactive_reason",
        "provenance",
    }
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    for index, child in enumerate(result["candidates"]):
        candidate = _object(child, name=f"candidate[{index}]", fields=candidate_fields)
        candidate_id = _string(candidate["candidate_id"], name=f"candidate[{index}].candidate_id")
        if candidate_id in seen_ids:
            raise ValueError("duplicate candidate_id")
        seen_ids.add(candidate_id)
        candidate_ref = _ref(
            candidate["provider_result_ref"], name=f"candidate[{index}].provider_result_ref"
        )
        if candidate_ref != provider_ref:
            raise ValueError("conflicting provider_result_ref")
        source_item_id = _string(
            candidate["source_item_id"], name=f"candidate[{index}].source_item_id"
        )
        if source_item_id in seen_sources:
            raise ValueError("duplicate source_item_id")
        seen_sources.add(source_item_id)
        if candidate_id != stable_candidate_id(
            provider_result_ref=candidate_ref, source_item_id=source_item_id
        ):
            raise ValueError("candidate_id does not match stable identity")
        bbox = _xyxy(candidate["bbox_original"], name=f"candidate[{index}].bbox_original")
        provider_item = provider_items_by_id.get(source_item_id)
        if provider_item is None:
            raise ValueError("candidate source_item_id is absent from provider result")
        if provider_item.get("capture_bbox") != bbox:
            raise ValueError("candidate bbox_original does not match immutable provider result")
        image_size = result["capture_identity"]["image_size"]
        if bbox[0] < 0 or bbox[1] < 0 or bbox[2] > image_size["width"] or bbox[3] > image_size["height"]:
            raise ValueError(f"candidate[{index}].bbox_original must be inside capture bounds")
        _coordinate_space(candidate["coordinate_space"], name=f"candidate[{index}].coordinate_space")
        confidence = _confidence(candidate["confidence"], name=f"candidate[{index}].confidence")
        if provider_item.get("provider_confidence") != confidence:
            raise ValueError("candidate confidence does not match immutable provider result")
        if not isinstance(candidate["active"], bool):
            raise ValueError(f"candidate[{index}].active must be a boolean")
        if candidate["active"] and candidate["inactive_reason"] is not None:
            raise ValueError("active candidate cannot have inactive_reason")
        if not candidate["active"]:
            _string(candidate["inactive_reason"], name=f"candidate[{index}].inactive_reason")
        provenance = _object(
            candidate["provenance"],
            name="candidate provenance",
            fields={
                "contract_version",
                "provider_result_ref",
                "source_item_id",
                "content_sha256",
            },
        )
        if provenance["contract_version"] != "hybrid_candidate_provenance_v1":
            raise ValueError("candidate provenance contract_version is invalid")
        _sealed_content(provenance, name="candidate provenance")
        if (
            provenance["provider_result_ref"] != provider_ref
            or provenance["source_item_id"] != source_item_id
        ):
            raise ValueError("candidate provenance identity mismatch")
        candidate["provenance"] = provenance
        result["candidates"][index] = candidate
    if seen_sources != set(provider_items_by_id):
        raise ValueError("Omni candidates must cover every provider result item")
    return _canonical_return(result, name="Omni inventory")


def validate_qwen_bindings(
    value: Mapping[str, Any], omni_inventory: Mapping[str, Any]
) -> dict[str, Any]:
    inventory = validate_omni_inventory(omni_inventory)
    fields = {
        "contract_version",
        "capture_identity",
        "bindings",
        "orphan_semantics",
    } | set(_NON_AUTHORIZING_FIELDS)
    result = _object(value, name="Qwen bindings", fields=fields)
    if result["contract_version"] != QWEN_CONTRACT:
        raise ValueError(f"Qwen bindings contract_version must be {QWEN_CONTRACT}")
    result["capture_identity"] = validate_capture_identity(result["capture_identity"])
    _same_capture(result["capture_identity"], inventory["capture_identity"])
    _non_authorizing(result, name="Qwen bindings")
    if not isinstance(result["bindings"], list):
        raise ValueError("Qwen bindings.bindings must be a list")
    known_ids = {candidate["candidate_id"] for candidate in inventory["candidates"]}
    binding_fields = {
        "candidate_id",
        "role",
        "label",
        "description",
        "semantic_confidence",
        "task_relevance",
        "relation",
        "ambiguity",
    }
    seen_ids: set[str] = set()
    for index, child in enumerate(result["bindings"]):
        if isinstance(child, Mapping) and set(child) & _GEOMETRY_FIELDS:
            raise ValueError("geometry is forbidden in Qwen output")
        binding = _object(child, name=f"binding[{index}]", fields=binding_fields)
        candidate_id = _string(binding["candidate_id"], name=f"binding[{index}].candidate_id")
        if candidate_id not in known_ids:
            raise ValueError(f"unknown candidate_id: {candidate_id}")
        if candidate_id in seen_ids:
            raise ValueError("duplicate candidate_id in Qwen bindings")
        seen_ids.add(candidate_id)
        for field in ("role", "label", "relation"):
            _string(binding[field], name=f"binding[{index}].{field}")
        _string(binding["description"], name=f"binding[{index}].description", allow_empty=True)
        _confidence(
            binding["semantic_confidence"], name=f"binding[{index}].semantic_confidence"
        )
        _confidence(binding["task_relevance"], name=f"binding[{index}].task_relevance")
        if binding["ambiguity"] is not None:
            _string(binding["ambiguity"], name=f"binding[{index}].ambiguity")
        result["bindings"][index] = binding
    if not isinstance(result["orphan_semantics"], list):
        raise ValueError("Qwen bindings.orphan_semantics must be a list")
    orphan_fields = {"semantic_id", "role", "label", "description", "reason"}
    orphan_ids: set[str] = set()
    for index, child in enumerate(result["orphan_semantics"]):
        if isinstance(child, Mapping) and set(child) & _GEOMETRY_FIELDS:
            raise ValueError("geometry is forbidden in Qwen output")
        orphan = _object(child, name=f"orphan_semantic[{index}]", fields=orphan_fields)
        semantic_id = _string(orphan["semantic_id"], name=f"orphan_semantic[{index}].semantic_id")
        if semantic_id in orphan_ids:
            raise ValueError("duplicate semantic_id in Qwen orphan semantics")
        orphan_ids.add(semantic_id)
        for field in ("role", "label", "reason"):
            _string(orphan[field], name=f"orphan_semantic[{index}].{field}")
        _string(orphan["description"], name=f"orphan_semantic[{index}].description", allow_empty=True)
        result["orphan_semantics"][index] = orphan
    return _canonical_return(result, name="Qwen bindings")


def validate_fusion_result(
    value: Mapping[str, Any],
    omni_inventory: Mapping[str, Any],
    qwen_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    inventory = validate_omni_inventory(omni_inventory)
    bindings = validate_qwen_bindings(qwen_bindings, inventory)
    fields = {
        "contract_version",
        "capture_identity",
        "config_sha256",
        "candidates",
    } | set(_NON_AUTHORIZING_FIELDS)
    result = _object(value, name="fusion result", fields=fields)
    if result["contract_version"] != FUSION_CONTRACT:
        raise ValueError(f"fusion result contract_version must be {FUSION_CONTRACT}")
    result["capture_identity"] = validate_capture_identity(result["capture_identity"])
    _same_capture(result["capture_identity"], inventory["capture_identity"])
    _same_capture(result["capture_identity"], bindings["capture_identity"])
    _sha256(result["config_sha256"], name="fusion result.config_sha256")
    _non_authorizing(result, name="fusion result")
    if not isinstance(result["candidates"], list):
        raise ValueError("fusion result.candidates must be a list")
    omni_by_id = {candidate["candidate_id"]: candidate for candidate in inventory["candidates"]}
    known_ids = set(omni_by_id)
    qwen_by_id = {binding["candidate_id"]: binding for binding in bindings["bindings"]}
    candidate_fields = {
        "candidate_id",
        "bbox_original",
        "coordinate_space",
        "state",
        "vista_eligible",
        "review_required",
        "reason",
    }
    seen_ids: set[str] = set()
    for index, child in enumerate(result["candidates"]):
        candidate = _object(child, name=f"fusion candidate[{index}]", fields=candidate_fields)
        candidate_id = _string(
            candidate["candidate_id"], name=f"fusion candidate[{index}].candidate_id"
        )
        if candidate_id in seen_ids:
            raise ValueError("duplicate candidate_id in fusion result")
        seen_ids.add(candidate_id)
        if candidate_id not in known_ids:
            raise ValueError(f"unknown candidate_id: {candidate_id}")
        omni_candidate = omni_by_id[candidate_id]
        bbox = _xyxy(
            candidate["bbox_original"], name=f"fusion candidate[{index}].bbox_original"
        )
        if bbox != omni_candidate["bbox_original"]:
            raise ValueError("fusion candidate geometry must match immutable Omni bbox_original")
        _coordinate_space(
            candidate["coordinate_space"], name=f"fusion candidate[{index}].coordinate_space"
        )
        state = candidate["state"]
        if state not in _FUSION_STATES:
            raise ValueError(f"unknown fusion state: {state}")
        if not isinstance(candidate["vista_eligible"], bool):
            raise ValueError("vista_eligible must be a boolean")
        if candidate["vista_eligible"] and state != "BOUND":
            raise ValueError("non-BOUND candidate cannot be VISTA eligible")
        if state == "BOUND" and not candidate["vista_eligible"]:
            raise ValueError("BOUND candidate must be VISTA eligible")
        if state == "BOUND" and (
            omni_candidate["active"] is not True or candidate_id not in qwen_by_id
        ):
            raise ValueError("BOUND requires one valid Qwen binding on an active Omni candidate")
        if not isinstance(candidate["review_required"], bool):
            raise ValueError("review_required must be a boolean")
        if state != "BOUND" and not candidate["review_required"]:
            raise ValueError("non-BOUND candidate must require review")
        _string(candidate["reason"], name=f"fusion candidate[{index}].reason")
        result["candidates"][index] = candidate
    if seen_ids != known_ids:
        raise ValueError("fusion result must preserve exact Omni candidate coverage")
    return _canonical_return(result, name="fusion result")


def validate_vista_proposals(
    value: Mapping[str, Any],
    fusion_result: Mapping[str, Any],
    omni_inventory: Mapping[str, Any],
    qwen_bindings: Mapping[str, Any],
    permitted_roi_refs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    inventory = validate_omni_inventory(omni_inventory)
    bindings = validate_qwen_bindings(qwen_bindings, inventory)
    fusion = validate_fusion_result(fusion_result, inventory, bindings)
    fields = {
        "contract_version",
        "capture_identity",
        "proposals",
    } | set(_NON_AUTHORIZING_FIELDS)
    result = _object(value, name="VISTA proposals", fields=fields)
    if result["contract_version"] != VISTA_CONTRACT:
        raise ValueError(f"VISTA proposals contract_version must be {VISTA_CONTRACT}")
    result["capture_identity"] = validate_capture_identity(result["capture_identity"])
    _same_capture(result["capture_identity"], fusion["capture_identity"])
    _same_capture(result["capture_identity"], inventory["capture_identity"])
    _non_authorizing(result, name="VISTA proposals")
    if not isinstance(result["proposals"], list):
        raise ValueError("VISTA proposals.proposals must be a list")
    fusion_by_id = {candidate["candidate_id"]: candidate for candidate in fusion["candidates"]}
    omni_by_id = {candidate["candidate_id"]: candidate for candidate in inventory["candidates"]}
    if not isinstance(permitted_roi_refs, Mapping):
        raise ValueError("permitted ROI context must be an object")
    permitted_rois = deepcopy(dict(permitted_roi_refs))
    bound_ids = {
        candidate_id
        for candidate_id, candidate in fusion_by_id.items()
        if candidate["state"] == "BOUND"
    }
    if set(permitted_rois) != bound_ids:
        raise ValueError("permitted ROI context must cover exact BOUND candidates")
    proposal_fields = {
        "candidate_id",
        "fusion_state",
        "candidate_bbox_ref",
        "roi_ref",
        "point",
        "confidence",
        "evidence",
        "status",
        "review_required",
    }
    seen_ids: set[str] = set()
    for index, child in enumerate(result["proposals"]):
        proposal = _object(child, name=f"VISTA proposal[{index}]", fields=proposal_fields)
        candidate_id = _string(
            proposal["candidate_id"], name=f"VISTA proposal[{index}].candidate_id"
        )
        if candidate_id in seen_ids:
            raise ValueError("duplicate candidate_id in VISTA proposals")
        seen_ids.add(candidate_id)
        fused = fusion_by_id.get(candidate_id)
        if fused is None:
            raise ValueError(f"unknown candidate_id: {candidate_id}")
        if fused["state"] != "BOUND" or proposal["fusion_state"] != "BOUND":
            raise ValueError("VISTA requires BOUND fusion state")
        omni_candidate = omni_by_id[candidate_id]
        bbox_ref = _object(
            proposal["candidate_bbox_ref"],
            name="candidate bbox ref",
            fields={
                "contract_version",
                "candidate_id",
                "provider_result_ref",
                "coordinate_space",
                "xyxy",
                "content_sha256",
            },
        )
        if bbox_ref["contract_version"] != "hybrid_candidate_bbox_ref_v1":
            raise ValueError("candidate bbox ref contract_version is invalid")
        _sealed_content(bbox_ref, name="candidate bbox ref")
        _coordinate_space(bbox_ref["coordinate_space"], name="candidate bbox ref.coordinate_space")
        candidate_bbox = _xyxy(bbox_ref["xyxy"], name="candidate bbox ref.xyxy")
        if (
            bbox_ref["candidate_id"] != candidate_id
            or bbox_ref["provider_result_ref"] != omni_candidate["provider_result_ref"]
            or candidate_bbox != omni_candidate["bbox_original"]
            or candidate_bbox != fused["bbox_original"]
        ):
            raise ValueError("candidate bbox substitution is forbidden")
        roi_ref = _object(
            proposal["roi_ref"],
            name="ROI",
            fields={
                "contract_version",
                "roi_id",
                "candidate_id",
                "capture_lineage_ref",
                "coordinate_space",
                "xyxy",
                "permitted_for_refinement",
                "content_sha256",
            },
        )
        if roi_ref["contract_version"] != "hybrid_permitted_roi_v1":
            raise ValueError("ROI contract_version is invalid")
        _sealed_content(roi_ref, name="ROI")
        _string(roi_ref["roi_id"], name="ROI.roi_id")
        _coordinate_space(roi_ref["coordinate_space"], name="ROI.coordinate_space")
        roi = _xyxy(roi_ref["xyxy"], name="ROI.xyxy")
        if (
            roi_ref["candidate_id"] != candidate_id
            or roi_ref["capture_lineage_ref"]
            != result["capture_identity"]["capture_lineage_ref"]
            or roi_ref["permitted_for_refinement"] is not True
        ):
            raise ValueError("ROI is not sealed and permitted for this candidate/capture")
        if canonical_json_bytes(roi_ref) != canonical_json_bytes(permitted_rois[candidate_id]):
            raise ValueError("proposal ROI does not match permitted ROI context")
        point_value = _object(
            proposal["point"],
            name=f"VISTA proposal[{index}].point",
            fields={"coordinate_space", "xy"},
        )
        _coordinate_space(
            point_value["coordinate_space"],
            name=f"VISTA proposal[{index}].point.coordinate_space",
        )
        point = _point(point_value["xy"], name=f"VISTA proposal[{index}].point.xy")
        image_size = result["capture_identity"]["image_size"]
        for geometry_name, geometry in (("candidate bbox", candidate_bbox), ("ROI", roi)):
            if (
                geometry[0] < 0
                or geometry[1] < 0
                or geometry[2] > image_size["width"]
                or geometry[3] > image_size["height"]
            ):
                raise ValueError(f"VISTA {geometry_name} must be inside capture bounds")
        if not (
            roi[0] <= point[0] <= roi[2]
            and roi[1] <= point[1] <= roi[3]
            and candidate_bbox[0] <= point[0] <= candidate_bbox[2]
            and candidate_bbox[1] <= point[1] <= candidate_bbox[3]
        ):
            raise ValueError("VISTA point must be inside ROI and candidate bbox")
        _confidence(proposal["confidence"], name=f"VISTA proposal[{index}].confidence")
        if not isinstance(proposal["evidence"], list) or not all(
            isinstance(item, str) and item for item in proposal["evidence"]
        ):
            raise ValueError(f"VISTA proposal[{index}].evidence must be a string list")
        if proposal["status"] not in {
            "PROPOSED",
            "VISTA_FAILED",
            "VISTA_OUT_OF_BOUNDS",
            "TRANSFORM_INVALID",
        }:
            raise ValueError("unknown VISTA status")
        if proposal["review_required"] is not True:
            raise ValueError("VISTA proposal must remain review_required")
        result["proposals"][index] = proposal
    return _canonical_return(result, name="VISTA proposals")


def load_hybrid_config(project_root: Path) -> dict[str, Any]:
    if not isinstance(project_root, Path):
        raise ValueError("project_root must be a Path")
    path = project_root / "configs" / "learn_hybrid_v1_1.json"
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Hybrid config not found: {path}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Hybrid config is not valid UTF-8 JSON: {path}") from error
    fields = {
        "contract_version",
        "config_id",
        "model_order",
        "rollout_mode",
        "providers",
        "coordinate_space",
        "fusion",
    } | set(_NON_AUTHORIZING_FIELDS)
    result = _object(parsed, name="Hybrid config", fields=fields)
    if result["contract_version"] != "learn_hybrid_config_v1_1":
        raise ValueError("Hybrid config contract_version must be learn_hybrid_config_v1_1")
    if result["config_id"] != "learn_hybrid_v1_1":
        raise ValueError("Hybrid config config_id must be learn_hybrid_v1_1")
    expected_order = [
        "capture",
        "omniparser",
        "qwen",
        "deterministic_fusion",
        "vista",
        "human_review",
    ]
    if result["model_order"] != expected_order:
        raise ValueError("Hybrid config model_order is fixed")
    if result["rollout_mode"] != "opt_in":
        raise ValueError("Hybrid config rollout_mode must be opt_in")
    providers = _object(
        result["providers"], name="Hybrid config.providers", fields={"omni", "qwen", "vista"}
    )
    for field in providers:
        _string(providers[field], name=f"Hybrid config.providers.{field}")
    _coordinate_space(result["coordinate_space"], name="Hybrid config.coordinate_space")
    fusion = _object(
        result["fusion"],
        name="Hybrid config.fusion",
        fields={
            "rules_version",
            "semantic_confidence_threshold",
            "tie_delta",
            "overlap_iou_threshold",
            "vista_eligible_states",
            "states",
        },
    )
    if fusion["rules_version"] != "hybrid_fusion_rules_v1":
        raise ValueError("Hybrid config fusion rules_version is invalid")
    for field in ("semantic_confidence_threshold", "tie_delta", "overlap_iou_threshold"):
        _confidence(fusion[field], name=f"Hybrid config.fusion.{field}")
    if fusion["vista_eligible_states"] != ["BOUND"]:
        raise ValueError("Hybrid config only permits BOUND VISTA eligibility")
    if fusion["states"] != list(_FUSION_STATE_ORDER):
        raise ValueError("Hybrid config fusion states must use the exact canonical order")
    _non_authorizing(result, name="Hybrid config")
    result["config_sha256"] = hashlib.sha256(canonical_json_bytes(result)).hexdigest()
    return _canonical_return(result, name="Hybrid config")
