"""将 Qwen 语义严格绑定到同一截图的不可变 Omni candidate ID。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
from app.learn.hybrid.contracts import (
    SEMANTIC_TARGET_IDENTITY_VERSION,
    canonical_semantic_target_key,
    validate_capture_identity,
    validate_omni_inventory,
    validate_qwen_bindings,
)
from app.learn.recognition.uei.canonical import content_sha256, seal_immutable
from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.provider_capabilities import (
    SemanticBindingItemV1,
    SemanticBindingResultV1,
    reject_authority_shaped_payload,
)


_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}
_PAYLOAD_FIELDS = {
    "project_root",
    "run_id",
    "workflow_revision",
    "hybrid_capture_bundle_ref",
    "capture_image_path",
    "omni_inventory",
}
_WIRE_BINDING_FIELDS = {
    "candidate_id",
    "role",
    "label",
    "binding_status",
    "confidence",
}
_WIRE_BINDING_STATUSES = {"BOUND", "UNBOUND", "AMBIGUOUS", "CONFLICT"}
_LEGACY_WIRE_BINDING_FIELDS = {
    "candidate_id",
    "role",
    "label",
    "description",
    "semantic_confidence",
    "task_relevance",
    "relation",
    "ambiguity",
}
_LEGACY_WIRE_FIELDS = {"bindings", "ambiguity_sets", "orphan_semantics"}
_ORPHAN_FIELDS = {"semantic_id", "role", "label", "description", "reason"}
_AMBIGUITY_SET_FIELDS = {"contract_version", "candidate_ids"}
_MAX_ORPHAN_SEMANTICS = 64
_MAX_WIRE_ROLE_CHARS = 64
_MAX_WIRE_LABEL_CHARS = 256
_FORBIDDEN_FIELDS = {
    "action_authorized",
    "approved_to_click",
    "approved_to_execute",
    "bbox",
    "bbox_original",
    "candidate_bbox",
    "candidate_bbox_ref",
    "click_authorized",
    "coordinate_space",
    "execute",
    "final_submit",
    "geometry",
    "new_candidate",
    "point",
    "refined_point",
    "roi",
    "roi_ref",
    "submit_authorized",
    "xy",
    "xyxy",
}
_MAX_JSON_DEPTH = 16
_MAX_MODEL_STRING_BYTES = 4096
_MAX_MODEL_JSON_BYTES = 1024 * 1024


class QwenBindingCancelled(ValueError):
    """受管 Qwen 绑定在产生新 artifact 前被取消。"""


class QwenBindingTimeout(ValueError):
    """受管 Qwen 模型调用超时。"""


def validate_sealed_omni_inventory(value: object) -> dict[str, Any]:
    """在模型获取前验证 Task 3 inventory 的精确不可变密封。"""
    return _validated_inventory(value)


def build_qwen_binding_request(
    capture_bundle: Mapping[str, Any],
    omni_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    """构造只含权威截图、Omni 几何和同源 OCR/UIA 的封闭请求。"""
    if not isinstance(capture_bundle, Mapping):
        raise ValueError("capture_bundle must be an object")
    bundle = deepcopy(dict(capture_bundle))
    inventory = _validated_inventory(omni_inventory)
    capture_identity = validate_capture_identity(bundle.get("capture_identity"))
    if capture_identity != inventory["capture_identity"]:
        raise ValueError("Qwen request capture identity mismatch")
    context = _sealed_context(bundle.get("context"), capture_identity)
    request = {
        "contract_version": "hybrid_qwen_binding_request_v1",
        "capture_identity": capture_identity,
        "screenshot": {
            "artifact_ref": deepcopy(capture_identity["artifact_ref"]),
            "screenshot_sha256": capture_identity["screenshot_sha256"],
            "image_size": deepcopy(capture_identity["image_size"]),
            "coordinate_space": "capture_pixel_xyxy",
        },
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "bbox_original": deepcopy(candidate["bbox_original"]),
                "coordinate_space": candidate["coordinate_space"],
                "active": candidate["active"],
                "inactive_reason": candidate["inactive_reason"],
            }
            for candidate in inventory["candidates"]
        ],
        "ocr_uia_context": context,
        "context_ref": deepcopy(bundle.get("context_ref")),
        "semantic_target_identity_version": SEMANTIC_TARGET_IDENTITY_VERSION,
        "allowed_output_fields": sorted(
            _WIRE_BINDING_FIELDS | {"bindings"}
        ),
    }
    return seal_immutable(request)


_LEGACY_QWEN_SEMANTIC_BUNDLE_REF = {
    "id": "bundle/legacy.qwen.semantic-binding",
    "content_sha256": "0" * 64,
}


def normalize_qwen_semantic_result(
    *,
    raw: Mapping[str, Any] | str,
    inventory: Mapping[str, Any],
    bundle_ref: dict[str, str],
    invocation_id: str,
    context_ref: Mapping[str, Any],
) -> SemanticBindingResultV1:
    """将 Qwen wire result 验证为临时语义绑定，不持久化。"""
    validated_inventory = _validated_inventory(inventory)
    verified_context_ref = _immutable_context_ref(context_ref)
    bindings, compatibility_payload = _parse_qwen_wire_bindings(
        raw, validated_inventory, verified_context_ref,
    )
    try:
        return SemanticBindingResultV1(
            bundle_ref=deepcopy(bundle_ref),
            invocation_id=invocation_id,
            capture_lineage_ref=deepcopy(
                validated_inventory["capture_identity"]["capture_lineage_ref"]
            ),
            bindings=tuple(
                SemanticBindingItemV1(
                    candidate_id=binding["candidate_id"],
                    role=binding["role"],
                    label=binding["label"],
                    binding_status=binding["binding_status"],
                    confidence=binding["confidence"],
                )
                for binding in bindings
            ),
            duration_ms=0,
            resource_units=0,
            compatibility_payload=compatibility_payload,
        )
    except UEIValidationError as error:
        raise ValueError(str(error)) from error

def project_semantic_result_to_hybrid_qwen_v1(
    *,
    result: SemanticBindingResultV1,
    inventory: Mapping[str, Any],
    context_ref: Mapping[str, Any],
) -> dict[str, Any]:
    """生成与现有 hybrid_qwen_bindings_v1 完全兼容的 artifact。"""
    if not isinstance(result, SemanticBindingResultV1):
        raise ValueError("Qwen semantic result is invalid")
    validated_inventory = _validated_inventory(inventory)
    try:
        reject_authority_shaped_payload(vars(result))
        for binding in result.bindings:
            reject_authority_shaped_payload(vars(binding))
    except UEIValidationError as error:
        raise ValueError("forbidden Qwen field") from error
    expected_ids = [
        candidate["candidate_id"] for candidate in validated_inventory["candidates"]
    ]
    actual_ids = [binding.candidate_id for binding in result.bindings]
    if actual_ids != expected_ids:
        raise ValueError("Qwen binding candidate order is invalid")
    if dict(result.capture_lineage_ref) != validated_inventory["capture_identity"]["capture_lineage_ref"]:
        raise ValueError("Qwen semantic result capture mismatch")
    if result.compatibility_payload is not None:
        return _project_legacy_compatibility_payload(
            result=result,
            inventory=validated_inventory,
            context_ref=context_ref,
        )
    projected_bindings = [
        {
            "candidate_id": binding.candidate_id,
            "role": binding.role,
            "label": binding.label,
            "description": "",
            "semantic_confidence": binding.confidence if binding.binding_status == "BOUND" else 0.0,
            "task_relevance": binding.confidence if binding.binding_status == "BOUND" else 0.0,
            "relation": "candidate_binding",
            "ambiguity": {
                "BOUND": None,
                "UNBOUND": None,
                "AMBIGUOUS": "qwen_binding_ambiguous",
                "CONFLICT": "qwen_binding_conflict",
            }[binding.binding_status],
        }
        for binding in result.bindings
    ]
    artifact = {
        "contract_version": "hybrid_qwen_bindings_v1",
        "capture_identity": deepcopy(validated_inventory["capture_identity"]),
        "context_ref": _immutable_context_ref(context_ref),
        "semantic_target_identity_version": SEMANTIC_TARGET_IDENTITY_VERSION,
        "bindings": projected_bindings,
        "ambiguity_sets": _complete_missing_ambiguity_sets(projected_bindings, []),
        "orphan_semantics": [],
        **_NON_AUTHORIZING,
    }
    return validate_qwen_bindings(artifact, validated_inventory)


def parse_qwen_candidate_bindings(
    raw: Mapping[str, Any] | str,
    omni_inventory: Mapping[str, Any],
    *,
    context_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """将紧凑的 candidate-ID-closed wire 输出投影到既有 artifact。"""
    if context_ref is None:
        raise ValueError("Qwen context_ref is missing or invalid")
    neutral = normalize_qwen_semantic_result(
        raw=raw,
        inventory=omni_inventory,
        bundle_ref=deepcopy(_LEGACY_QWEN_SEMANTIC_BUNDLE_REF),
        invocation_id="legacy/qwen-candidate-binding",
        context_ref=context_ref,
    )
    projected = project_semantic_result_to_hybrid_qwen_v1(
        result=neutral, inventory=omni_inventory, context_ref=context_ref,
    )
    return validate_qwen_bindings(projected, _validated_inventory(omni_inventory))


def _parse_qwen_wire_bindings(
    raw: Mapping[str, Any] | str,
    inventory: Mapping[str, Any],
    context_ref: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, object] | None]:
    if isinstance(raw, str):
        if len(raw.encode("utf-8")) > _MAX_MODEL_JSON_BYTES:
            raise ValueError("Qwen model JSON exceeds byte limit")
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, RecursionError) as error:
            raise ValueError("unbound Qwen prose or invalid JSON") from error
    if not isinstance(raw, Mapping):
        raise ValueError("unbound Qwen prose or non-closed output")
    _validate_model_json_bounds(raw)
    _reject_qwen_authority_aliases(raw)
    if set(raw) == _LEGACY_WIRE_FIELDS:
        return _parse_legacy_qwen_wire_bindings(raw, inventory, context_ref)
    if set(raw) != {"bindings"}:
        raise ValueError("unbound Qwen prose or non-closed output")
    value = deepcopy(dict(raw))
    forbidden = _first_forbidden_field(value)
    if forbidden is not None:
        raise ValueError(f"forbidden Qwen field: {forbidden}")
    if not isinstance(value["bindings"], list):
        raise ValueError("Qwen bindings must be a list")
    if len(value["bindings"]) != len(inventory["candidates"]):
        raise ValueError("candidate omission in Qwen bindings")
    expected_ids = [candidate["candidate_id"] for candidate in inventory["candidates"]]
    seen_ids: set[str] = set()
    bindings: list[dict[str, Any]] = []
    for index, binding in enumerate(value["bindings"]):
        if not isinstance(binding, Mapping) or set(binding) != _WIRE_BINDING_FIELDS:
            raise ValueError(f"binding[{index}] is not closed")
        candidate_id = binding["candidate_id"]
        if candidate_id not in expected_ids:
            raise ValueError("unknown candidate_id in Qwen bindings")
        if candidate_id in seen_ids:
            raise ValueError("duplicate candidate_id in Qwen bindings")
        seen_ids.add(candidate_id)
        role = binding["role"]
        label = binding["label"]
        if not isinstance(role, str) or not role.strip():
            raise ValueError(f"binding[{index}].role must be a non-empty string")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"binding[{index}].label must be a non-empty string")
        if len(role) > _MAX_WIRE_ROLE_CHARS:
            raise ValueError(f"binding[{index}].role exceeds maximum length")
        if len(label) > _MAX_WIRE_LABEL_CHARS:
            raise ValueError(f"binding[{index}].label exceeds maximum length")
        status = binding["binding_status"]
        if not isinstance(status, str) or status not in _WIRE_BINDING_STATUSES:
            raise ValueError(f"binding[{index}].binding_status is invalid")
        confidence = binding["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or confidence < 0
            or confidence > 1
        ):
            raise ValueError(f"binding[{index}].confidence must be between 0 and 1")
        bindings.append({
            "candidate_id": candidate_id,
            "role": role,
            "label": label,
            "binding_status": status,
            "confidence": confidence,
        })
    if [binding["candidate_id"] for binding in bindings] != expected_ids:
        raise ValueError("Qwen binding candidate order is invalid")
    return bindings, None


def _reject_qwen_authority_aliases(value: object) -> None:
    try:
        reject_authority_shaped_payload(value)
    except UEIValidationError as error:
        raise ValueError("forbidden Qwen field") from error


def _parse_legacy_qwen_wire_bindings(
    raw: Mapping[str, Any],
    inventory: Mapping[str, Any],
    context_ref: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    """按 pre-compact contract 验证并显式携带 legacy 投影。"""
    value = deepcopy(dict(raw))
    forbidden = _first_forbidden_field(value)
    if forbidden is not None:
        raise ValueError(f"forbidden Qwen field: {forbidden}")
    if not isinstance(value["bindings"], list):
        raise ValueError("Qwen bindings must be a list")
    if not isinstance(value["orphan_semantics"], list):
        raise ValueError("Qwen orphan_semantics must be a list")
    if not isinstance(value["ambiguity_sets"], list):
        raise ValueError("Qwen ambiguity_sets must be a list")
    if len(value["bindings"]) != len(inventory["candidates"]):
        raise ValueError("candidate omission in Qwen bindings")
    if len(value["orphan_semantics"]) > _MAX_ORPHAN_SEMANTICS:
        raise ValueError("Qwen orphan count exceeds limit")
    for index, binding in enumerate(value["bindings"]):
        if not isinstance(binding, Mapping) or set(binding) != _LEGACY_WIRE_BINDING_FIELDS:
            raise ValueError(f"binding[{index}] is not closed")
    for index, orphan in enumerate(value["orphan_semantics"]):
        if not isinstance(orphan, Mapping) or set(orphan) != _ORPHAN_FIELDS:
            raise ValueError(f"orphan_semantic[{index}] is not closed")
        semantic_id = orphan.get("semantic_id")
        if not isinstance(semantic_id, str) or not semantic_id.startswith("semantic/"):
            raise ValueError("orphan semantic cannot use a fabricated candidate identity")
        if orphan.get("reason") != "ORPHAN_SEMANTIC":
            raise ValueError("orphan semantic reason must be ORPHAN_SEMANTIC")
    for index, ambiguity in enumerate(value["ambiguity_sets"]):
        if not isinstance(ambiguity, Mapping) or set(ambiguity) != _AMBIGUITY_SET_FIELDS:
            raise ValueError(f"ambiguity_set[{index}] is not closed")
    value["ambiguity_sets"] = _complete_missing_ambiguity_sets(
        value["bindings"], value["ambiguity_sets"],
    )
    artifact = {
        "contract_version": "hybrid_qwen_bindings_v1",
        "capture_identity": deepcopy(inventory["capture_identity"]),
        "context_ref": deepcopy(context_ref),
        "semantic_target_identity_version": SEMANTIC_TARGET_IDENTITY_VERSION,
        "bindings": value["bindings"],
        "ambiguity_sets": value["ambiguity_sets"],
        "orphan_semantics": value["orphan_semantics"],
        **_NON_AUTHORIZING,
    }
    validated = validate_qwen_bindings(artifact, inventory)
    _validate_legacy_candidate_and_orphan_coverage(validated, inventory)
    compact_bindings: list[dict[str, Any]] = []
    for binding in validated["bindings"]:
        ambiguity = binding["ambiguity"]
        if ambiguity is None:
            status = "BOUND" if binding["semantic_confidence"] > 0 else "UNBOUND"
        elif ambiguity == "qwen_binding_ambiguous":
            status = "AMBIGUOUS"
        else:
            status = "CONFLICT"
        compact_bindings.append({
            "candidate_id": binding["candidate_id"],
            "role": binding["role"],
            "label": binding["label"],
            "binding_status": status,
            "confidence": binding["semantic_confidence"],
        })
    return compact_bindings, {
        "contract_version": "qwen_legacy_semantic_projection_v1",
        "bindings": deepcopy(validated["bindings"]),
        "ambiguity_sets": deepcopy(validated["ambiguity_sets"]),
        "orphan_semantics": deepcopy(validated["orphan_semantics"]),
    }


def _validate_legacy_candidate_and_orphan_coverage(
    artifact: Mapping[str, Any], inventory: Mapping[str, Any],
) -> None:
    expected_ids = [candidate["candidate_id"] for candidate in inventory["candidates"]]
    actual_ids = [binding["candidate_id"] for binding in artifact["bindings"]]
    if actual_ids != expected_ids:
        raise ValueError("Qwen binding candidate order is invalid")
    semantic_targets = {
        canonical_semantic_target_key(binding) for binding in artifact["bindings"]
    }
    orphan_targets: set[tuple[str, str, str, str]] = set()
    for orphan in artifact["orphan_semantics"]:
        target = canonical_semantic_target_key(orphan)
        if target in semantic_targets:
            raise ValueError("semantic target bound and orphaned")
        if target in orphan_targets:
            raise ValueError("duplicate orphan semantic target")
        orphan_targets.add(target)


def _project_legacy_compatibility_payload(
    *,
    result: SemanticBindingResultV1,
    inventory: Mapping[str, Any],
    context_ref: Mapping[str, Any],
) -> dict[str, Any]:
    payload = result.compatibility_payload
    if payload is None:
        raise ValueError("Qwen legacy compatibility payload is missing")
    artifact = {
        "contract_version": "hybrid_qwen_bindings_v1",
        "capture_identity": deepcopy(inventory["capture_identity"]),
        "context_ref": _immutable_context_ref(context_ref),
        "semantic_target_identity_version": SEMANTIC_TARGET_IDENTITY_VERSION,
        "bindings": deepcopy(payload["bindings"]),
        "ambiguity_sets": deepcopy(payload["ambiguity_sets"]),
        "orphan_semantics": deepcopy(payload["orphan_semantics"]),
        **_NON_AUTHORIZING,
    }
    validated = validate_qwen_bindings(artifact, inventory)
    _validate_legacy_candidate_and_orphan_coverage(validated, inventory)
    expected_compact = []
    for binding in validated["bindings"]:
        ambiguity = binding["ambiguity"]
        status = (
            "BOUND" if ambiguity is None and binding["semantic_confidence"] > 0
            else "UNBOUND" if ambiguity is None
            else "AMBIGUOUS" if ambiguity == "qwen_binding_ambiguous"
            else "CONFLICT"
        )
        expected_compact.append((
            binding["candidate_id"], binding["role"], binding["label"],
            status, binding["semantic_confidence"],
        ))
    actual_compact = [(
        binding.candidate_id, binding.role, binding.label,
        binding.binding_status, binding.confidence,
    ) for binding in result.bindings]
    if actual_compact != expected_compact:
        raise ValueError("Qwen legacy compatibility payload conflicts with semantic result")
    return validated

def _complete_missing_ambiguity_sets(
    bindings: list[object],
    ambiguity_sets: list[object],
) -> list[dict[str, object]]:
    binding_ids: set[str] = set()
    semantic_groups: dict[tuple[str, str, str, str], list[str]] = {}
    for index, binding in enumerate(bindings):
        if not isinstance(binding, Mapping):
            raise ValueError(f"binding[{index}] is not closed")
        candidate_id = binding.get("candidate_id")
        if not isinstance(candidate_id, str):
            raise ValueError(f"binding[{index}].candidate_id is invalid")
        binding_ids.add(candidate_id)
        semantic_groups.setdefault(canonical_semantic_target_key(binding), []).append(
            candidate_id
        )

    expected_sets = {
        tuple(sorted(candidate_ids))
        for candidate_ids in semantic_groups.values()
        if len(candidate_ids) > 1
    }
    completed = [deepcopy(dict(item)) for item in ambiguity_sets]
    declared_sets: set[tuple[str, ...]] = set()
    declared_memberships: set[str] = set()
    for ambiguity in completed:
        if ambiguity.get("contract_version") != "hybrid_semantic_ambiguity_set_v1":
            raise ValueError("Qwen ambiguity set contract_version is invalid")
        candidate_ids = ambiguity.get("candidate_ids")
        if (
            not isinstance(candidate_ids, list)
            or len(candidate_ids) < 2
            or any(not isinstance(candidate_id, str) for candidate_id in candidate_ids)
            or candidate_ids != sorted(candidate_ids)
            or len(set(candidate_ids)) != len(candidate_ids)
            or any(candidate_id not in binding_ids for candidate_id in candidate_ids)
        ):
            raise ValueError("Qwen ambiguity set candidate_ids are invalid")
        declared = tuple(candidate_ids)
        if declared in declared_sets:
            raise ValueError("duplicate Qwen ambiguity set")
        if any(candidate_id in declared_memberships for candidate_id in candidate_ids):
            raise ValueError("Qwen candidate belongs to multiple ambiguity sets")
        if declared not in expected_sets:
            raise ValueError(
                "Qwen ambiguity set semantic target mismatch; "
                "must be a complete exact duplicate semantic target group"
            )
        declared_sets.add(declared)
        declared_memberships.update(candidate_ids)

    for missing in sorted(expected_sets - declared_sets):
        completed.append({
            "contract_version": "hybrid_semantic_ambiguity_set_v1",
            "candidate_ids": list(missing),
        })
    return completed


def run_qwen_candidate_binding(
    payload: dict[str, Any],
    *,
    model_runner: Callable[..., object],
    cancellation_event: Any | None = None,
    model_lease: dict[str, Any] | None = None,
    model_completion_notifier: Callable[[], object] | None = None,
) -> dict[str, Any]:
    """重新验证 Task 2/3 artifact，调用 Qwen，并在返回前密封绑定。"""
    request_payload = _validated_payload(payload)
    if cancellation_event is not None and cancellation_event.is_set():
        raise QwenBindingCancelled("Qwen candidate binding cancelled")
    root = Path(request_payload["project_root"]).resolve()
    bundle = load_and_verify_hybrid_capture_bundle(
        project_root=root,
        bundle_ref=deepcopy(request_payload["hybrid_capture_bundle_ref"]),
        expected_run_id=request_payload["run_id"],
        expected_workflow_revision=request_payload["workflow_revision"],
    )
    image_path = _capture_path(root, request_payload["capture_image_path"])
    sealed_inventory = deepcopy(request_payload["omni_inventory"])
    inventory = _validated_inventory(sealed_inventory)
    model_request = build_qwen_binding_request(bundle, sealed_inventory)
    screenshot_bytes, screenshot_media_type, screenshot_sha256 = _read_verified_capture(
        image_path,
        inventory["capture_identity"],
    )
    try:
        raw = model_runner(
            request=deepcopy(model_request),
            screenshot_bytes=screenshot_bytes,
            screenshot_media_type=screenshot_media_type,
            screenshot_sha256=screenshot_sha256,
            cancellation_event=cancellation_event,
            model_lease=deepcopy(model_lease),
        )
    except TimeoutError as error:
        raise QwenBindingTimeout("Qwen model timeout") from error
    except RuntimeError as error:
        if cancellation_event is not None and cancellation_event.is_set():
            raise QwenBindingCancelled("Qwen candidate binding cancelled") from error
        raise
    if model_completion_notifier is not None:
        model_completion_notifier()
    if cancellation_event is not None and cancellation_event.is_set():
        raise QwenBindingCancelled("Qwen candidate binding cancelled")
    if isinstance(raw, str):
        if len(raw.encode("utf-8")) > _MAX_MODEL_JSON_BYTES:
            raise ValueError("Qwen model JSON exceeds byte limit")
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, RecursionError) as error:
            raise ValueError("unbound Qwen prose or invalid JSON") from error
    parsed = parse_qwen_candidate_bindings(
        raw,
        sealed_inventory,
        context_ref=model_request["context_ref"],
    )
    return seal_immutable(parsed)


def _validated_inventory(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("omni_inventory must be an object")
    candidate = deepcopy(dict(value))
    declared = candidate.pop("content_sha256", None)
    if (
        not isinstance(declared, str)
        or re.fullmatch(r"[0-9a-f]{64}", declared) is None
        or declared != content_sha256(dict(value))
    ):
        raise ValueError("sealed Omni inventory content_sha256 mismatch")
    return validate_omni_inventory(candidate)


def _sealed_context(value: object, capture_identity: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("sealed OCR/UIA context is missing")
    context = deepcopy(dict(value))
    if context.get("content_sha256") != content_sha256(context):
        raise ValueError("OCR/UIA context content_sha256 mismatch")
    if (
        context.get("contract_version") != "hybrid_capture_context_v1"
        or context.get("capture_lineage_ref") != capture_identity["capture_lineage_ref"]
    ):
        raise ValueError("OCR/UIA context capture mismatch")
    sources = context.get("sources")
    if not isinstance(sources, list) or len(sources) != 2 or {
        source.get("source_kind") for source in sources if isinstance(source, Mapping)
    } != {"ocr", "uia"}:
        raise ValueError("OCR/UIA context requires sealed OCR and UIA sources")
    if any(
        not isinstance(source, Mapping)
        or source.get("capture_lineage_ref") != capture_identity["capture_lineage_ref"]
        for source in sources
    ):
        raise ValueError("OCR/UIA context source capture mismatch")
    return context


def _validated_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PAYLOAD_FIELDS:
        raise ValueError("Hybrid Qwen payload is not closed")
    payload = deepcopy(dict(value))
    for field in ("project_root", "run_id", "capture_image_path"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise ValueError(f"{field} is invalid")
    revision = payload["workflow_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("workflow_revision is invalid")
    reference = payload["hybrid_capture_bundle_ref"]
    if (
        not isinstance(reference, Mapping)
        or set(reference) != {"id", "content_sha256"}
        or not isinstance(reference.get("id"), str)
        or not isinstance(reference.get("content_sha256"), str)
    ):
        raise ValueError("hybrid_capture_bundle_ref is invalid")
    return payload


def _capture_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("capture_image_path escapes project_root") from None
    if not resolved.is_file():
        raise ValueError("capture_image_path is not a file")
    return resolved


def _read_verified_capture(
    path: Path,
    identity: dict[str, Any],
) -> tuple[bytes, str, str]:
    try:
        raw = path.read_bytes()
        with Image.open(BytesIO(raw)) as image:
            image_format = str(image.format or "").upper()
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            size = {"width": image.width, "height": image.height}
    except (OSError, SyntaxError, UnidentifiedImageError):
        raise ValueError("canonical screenshot is unreadable") from None
    digest = sha256(raw).hexdigest()
    if digest != identity["screenshot_sha256"] or size != identity["image_size"]:
        raise ValueError("canonical screenshot capture mismatch")
    media_types = {"PNG": "image/png", "JPEG": "image/jpeg"}
    media_type = media_types.get(image_format)
    if media_type is None:
        raise ValueError("canonical screenshot media type is unsupported")
    return raw, media_type, digest


def _immutable_context_ref(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "content_sha256"}:
        raise ValueError("Qwen context_ref is missing or invalid")
    identifier = value.get("id")
    digest = value.get("content_sha256")
    if (
        not isinstance(identifier, str)
        or not identifier
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise ValueError("Qwen context_ref is missing or invalid")
    return {"id": identifier, "content_sha256": digest}


def _validate_model_json_bounds(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > _MAX_JSON_DEPTH:
            raise ValueError("Qwen output exceeds maximum JSON depth")
        if isinstance(current, str):
            if len(current.encode("utf-8")) > _MAX_MODEL_STRING_BYTES:
                raise ValueError("Qwen model string exceeds UTF-8 byte limit")
            continue
        if isinstance(current, Mapping):
            for key, child in current.items():
                if len(str(key).encode("utf-8")) > _MAX_MODEL_STRING_BYTES:
                    raise ValueError("Qwen model string exceeds UTF-8 byte limit")
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)


def _first_forbidden_field(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in _FORBIDDEN_FIELDS:
                return str(key)
            found = _first_forbidden_field(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_forbidden_field(child)
            if found is not None:
                return found
    return None
