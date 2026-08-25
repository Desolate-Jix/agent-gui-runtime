"""纯函数式 Portfolio Hybrid v1.1 决定性融合。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal
import hashlib
import math
import re
from typing import Any

from app.learn.hybrid.contracts import (
    canonical_semantic_target_key,
    validate_fusion_result,
    validate_omni_inventory,
    validate_qwen_bindings,
)
from app.learn.hybrid.omni_candidates import validate_current_capture_bundle
from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256


_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}
_REVIEW_STATES = frozenset(
    {
        "AMBIGUOUS",
        "CONFLICT",
        "ORPHAN",
        "ORPHAN_SEMANTIC",
        "LOW_CONFIDENCE",
        "UNBOUND",
        "CAPTURE_MISMATCH",
        "REVIEW_REQUIRED",
    }
)
_EXPLICIT_CONFLICT_MARKERS = frozenset({"CONFLICT", "DISAGREEMENT"})
_CONFIG_STATES = [
    "BOUND",
    "AMBIGUOUS",
    "CONFLICT",
    "ORPHAN",
    "ORPHAN_SEMANTIC",
    "LOW_CONFIDENCE",
    "UNBOUND",
    "CAPTURE_MISMATCH",
    "REVIEW_REQUIRED",
]


def fusion_review_policy(state: str) -> dict[str, bool]:
    """返回封闭状态表；只有 BOUND 可进入 VISTA。"""
    if state == "BOUND":
        return {"review_required": False, "vista_eligible": True}
    if state in _REVIEW_STATES:
        return {"review_required": True, "vista_eligible": False}
    raise ValueError(f"unknown fusion state: {state}")


def fuse_hybrid_candidates(
    *,
    config: Mapping[str, Any],
    capture_bundle: Mapping[str, Any],
    omni_inventory: Mapping[str, Any],
    qwen_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """按版本化阈值融合 Omni 几何与 Qwen candidate-ID 语义。"""
    rules, config_sha256 = _validated_config(config)
    inventory = validate_omni_inventory(_require_sealed(omni_inventory, name="Omni inventory"))
    bindings = validate_qwen_bindings(
        _require_sealed(qwen_bindings, name="Qwen bindings"),
        inventory,
        allow_capture_mismatch=True,
    )
    bundle = validate_current_capture_bundle(capture_bundle)
    capture_identity = bundle["capture_identity"]
    identities = (
        canonical_json_bytes(capture_identity),
        canonical_json_bytes(inventory["capture_identity"]),
        canonical_json_bytes(bindings["capture_identity"]),
    )
    if len(set(identities)) != 1:
        return _capture_mismatch_result(
            config_sha256=config_sha256,
            inventory=inventory,
            bindings=bindings,
        )
    if bindings["context_ref"] != bundle["context_ref"]:
        raise ValueError("Qwen context_ref does not match verified capture context")
    bindings = validate_qwen_bindings(bindings, inventory)

    binding_by_id = {
        binding["candidate_id"]: binding for binding in bindings["bindings"]
    }
    candidate_by_id = {
        candidate["candidate_id"]: candidate for candidate in inventory["candidates"]
    }
    relations = _semantic_relations(bindings["bindings"])
    orphan_review = bool(bindings["orphan_semantics"])
    records: list[dict[str, Any]] = []
    for candidate in inventory["candidates"]:
        candidate_id = candidate["candidate_id"]
        binding = binding_by_id.get(candidate_id)
        state, reason = _candidate_decision(
            candidate=candidate,
            binding=binding,
            candidate_by_id=candidate_by_id,
            binding_by_id=binding_by_id,
            related_ids=relations.get(_semantic_target(binding), ()) if binding else (),
            rules=rules,
            orphan_review=orphan_review,
        )
        records.append(
            {
                "candidate_id": candidate_id,
                "bbox_original": deepcopy(candidate["bbox_original"]),
                "coordinate_space": candidate["coordinate_space"],
                "active": candidate["active"],
                "inactive_reason": deepcopy(candidate["inactive_reason"]),
                "state": state,
                **fusion_review_policy(state),
                "reason": reason,
            }
        )

    result = {
        "contract_version": "hybrid_fusion_result_v1",
        "capture_identity": deepcopy(capture_identity),
        "config_sha256": config_sha256,
        "candidates": records,
        **_NON_AUTHORIZING,
    }
    return validate_fusion_result(result, inventory, bindings)


def _candidate_decision(
    *,
    candidate: dict[str, Any],
    binding: dict[str, Any] | None,
    candidate_by_id: dict[str, dict[str, Any]],
    binding_by_id: dict[str, dict[str, Any]],
    related_ids: tuple[str, ...],
    rules: dict[str, Any],
    orphan_review: bool,
) -> tuple[str, str]:
    if not candidate["active"]:
        return "UNBOUND", f"inactive:{candidate['inactive_reason']}"
    if binding is None:
        return "UNBOUND", "missing_qwen_binding"
    ambiguity = binding["ambiguity"]
    if ambiguity is not None:
        if _contains_conflict_marker(ambiguity):
            return "CONFLICT", "explicit_semantic_disagreement"
        return "AMBIGUOUS", "explicit_binding_ambiguity"
    if _decimal(binding["semantic_confidence"]) < _decimal(
        rules["semantic_confidence_threshold"]
    ):
        return "LOW_CONFIDENCE", "semantic_confidence_below_threshold"
    if len(related_ids) != 1:
        related = [
            (candidate_by_id[candidate_id], binding_by_id[candidate_id])
            for candidate_id in related_ids
        ]
        overlaps = [
            _iou(candidate["bbox_original"], other[0]["bbox_original"])
            for other in related
            if other[0]["candidate_id"] != candidate["candidate_id"]
        ]
        confidence_values = [
            _decimal(other_binding["semantic_confidence"])
            for _, other_binding in related
        ]
        confidence_delta = max(confidence_values) - min(confidence_values)
        if (
            overlaps
            and max(overlaps) >= _decimal(rules["overlap_iou_threshold"])
            and confidence_delta <= _decimal(rules["tie_delta"])
        ):
            return "AMBIGUOUS", "overlapping_semantic_tie"
        return "CONFLICT", "semantic_relation_not_unique"
    if orphan_review:
        return "REVIEW_REQUIRED", "orphan_semantic_requires_review"
    return "BOUND", "unique_exact_binding"


def _capture_mismatch_result(
    *,
    config_sha256: str,
    inventory: dict[str, Any],
    bindings: dict[str, Any],
) -> dict[str, Any]:
    policy = fusion_review_policy("CAPTURE_MISMATCH")
    result = {
        "contract_version": "hybrid_fusion_result_v1",
        "capture_identity": deepcopy(inventory["capture_identity"]),
        "config_sha256": config_sha256,
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "bbox_original": deepcopy(candidate["bbox_original"]),
                "coordinate_space": candidate["coordinate_space"],
                "active": candidate["active"],
                "inactive_reason": deepcopy(candidate["inactive_reason"]),
                "state": "CAPTURE_MISMATCH",
                **policy,
                "reason": "capture_identity_mismatch",
            }
            for candidate in inventory["candidates"]
        ],
        **_NON_AUTHORIZING,
    }
    return validate_fusion_result(result, inventory, bindings)


def _validated_config(value: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(value, Mapping):
        raise ValueError("config must be an object")
    config = deepcopy(dict(value))
    declared = config.pop("config_sha256", None)
    if not isinstance(declared, str) or re.fullmatch(r"[0-9a-f]{64}", declared) is None:
        raise ValueError("config_sha256 is invalid")
    actual = hashlib.sha256(canonical_json_bytes(config)).hexdigest()
    if declared != actual:
        raise ValueError("config_sha256 mismatch")
    if config.get("contract_version") != "learn_hybrid_config_v1_1":
        raise ValueError("Hybrid config contract_version is invalid")
    if set(config) != {
        "contract_version",
        "config_id",
        "model_order",
        "rollout_mode",
        "providers",
        "coordinate_space",
        "fusion",
        *_NON_AUTHORIZING,
    }:
        raise ValueError("Hybrid config is not closed")
    if config.get("config_id") != "learn_hybrid_v1_1":
        raise ValueError("Hybrid config config_id is invalid")
    if config.get("model_order") != [
        "capture",
        "omniparser",
        "qwen",
        "deterministic_fusion",
        "vista",
        "human_review",
    ]:
        raise ValueError("Hybrid config model_order is invalid")
    if config.get("rollout_mode") != "opt_in":
        raise ValueError("Hybrid config rollout_mode is invalid")
    providers = config.get("providers")
    if (
        not isinstance(providers, Mapping)
        or set(providers) != {"omni", "qwen", "vista"}
        or not all(isinstance(provider, str) and provider for provider in providers.values())
    ):
        raise ValueError("Hybrid config providers are invalid")
    if config.get("coordinate_space") != "capture_pixel_xyxy":
        raise ValueError("Hybrid config coordinate_space is invalid")
    for field, expected in _NON_AUTHORIZING.items():
        if config.get(field) != expected or type(config.get(field)) is not type(expected):
            raise ValueError(f"Hybrid config violates non-authorizing invariant: {field}")
    fusion = config.get("fusion")
    if not isinstance(fusion, Mapping) or set(fusion) != {
        "rules_version",
        "semantic_confidence_threshold",
        "tie_delta",
        "overlap_iou_threshold",
        "vista_eligible_states",
        "states",
    }:
        raise ValueError("Hybrid config fusion is not closed")
    if fusion.get("rules_version") != "hybrid_fusion_rules_v1":
        raise ValueError("Hybrid config fusion rules_version is invalid")
    if fusion.get("vista_eligible_states") != ["BOUND"]:
        raise ValueError("Hybrid config only permits BOUND VISTA eligibility")
    if fusion.get("states") != _CONFIG_STATES:
        raise ValueError("Hybrid config fusion states are invalid")
    for field in (
        "semantic_confidence_threshold",
        "tie_delta",
        "overlap_iou_threshold",
    ):
        number = fusion.get(field)
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            raise ValueError(f"Hybrid config.fusion.{field} is invalid")
        if _decimal(number) < Decimal("0") or _decimal(number) > Decimal("1"):
            raise ValueError(f"Hybrid config.fusion.{field} is invalid")
    return deepcopy(dict(fusion)), declared


def _require_sealed(value: Mapping[str, Any], *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result = deepcopy(dict(value))
    declared = result.get("content_sha256")
    if not isinstance(declared, str) or declared != content_sha256(result):
        raise ValueError(f"{name} content_sha256 mismatch")
    result.pop("content_sha256")
    return result


def _semantic_relations(
    bindings: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str], tuple[str, ...]]:
    grouped: dict[tuple[str, str, str, str], list[str]] = {}
    for binding in bindings:
        grouped.setdefault(_semantic_target(binding), []).append(binding["candidate_id"])
    return {key: tuple(sorted(candidate_ids)) for key, candidate_ids in grouped.items()}


def _semantic_target(binding: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return canonical_semantic_target_key(binding)


def _contains_conflict_marker(value: str) -> bool:
    normalized = value.upper().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in _EXPLICIT_CONFLICT_MARKERS)


def _iou(left: list[float], right: list[float]) -> Decimal:
    left_x1, left_y1, left_x2, left_y2 = map(_decimal, left)
    right_x1, right_y1, right_x2, right_y2 = map(_decimal, right)
    width = max(Decimal("0"), min(left_x2, right_x2) - max(left_x1, right_x1))
    height = max(Decimal("0"), min(left_y2, right_y2) - max(left_y1, right_y1))
    intersection = width * height
    left_area = (left_x2 - left_x1) * (left_y2 - left_y1)
    right_area = (right_x2 - right_x1) * (right_y2 - right_y1)
    union = left_area + right_area - intersection
    return Decimal("0") if union == 0 else intersection / union


def _decimal(value: int | float) -> Decimal:
    return Decimal(str(value))


__all__ = ["fuse_hybrid_candidates", "fusion_review_policy"]
