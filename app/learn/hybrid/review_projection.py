"""UEI-native persistence and read-only projection of Hybrid candidates."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
from app.learn.hybrid.contracts import (
    validate_fusion_result,
    validate_omni_inventory,
    validate_qwen_bindings,
    validate_vista_proposals,
)
from app.learn.hybrid.omni_candidates import (
    build_omni_candidate_ledger,
    validate_omni_candidate_ledger,
    validate_current_capture_bundle,
)
from app.learn.recognition.roi import build_roi_crop_metadata
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
    capture_bundle: Mapping[str, Any] | None = None,
    omni_inventory: Mapping[str, Any] | None = None,
    qwen_bindings: Mapping[str, Any] | None = None,
    fusion_result: Mapping[str, Any] | None = None,
    vista_proposals: Mapping[str, Any] | None = None,
    project_root: Path | None = None,
    omni_ledger: Mapping[str, Any] | None = None,
    displayed_image_sha256: str | None = None,
    displayed_image_size: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """投影完整 Hybrid 父证据；旧 UEI 调用继续使用封闭兼容路径。"""
    full_parent_values = (
        capture_bundle,
        omni_inventory,
        qwen_bindings,
        fusion_result,
        vista_proposals,
    )
    if any(value is not None for value in full_parent_values):
        if not all(value is not None for value in full_parent_values):
            raise ValueError("Hybrid review requires every full parent")
        if any(
            value is not None
            for value in (
                project_root,
                omni_ledger,
                displayed_image_sha256,
                displayed_image_size,
            )
        ):
            raise ValueError("Hybrid review projection entrypoints cannot be mixed")
        return _project_full_parent_hybrid_review(
            capture_bundle=capture_bundle,
            omni_inventory=omni_inventory,
            qwen_bindings=qwen_bindings,
            fusion_result=fusion_result,
            vista_proposals=vista_proposals,
        )
    if (
        project_root is None
        or omni_ledger is None
        or displayed_image_sha256 is None
        or displayed_image_size is None
    ):
        raise ValueError("legacy Hybrid review projection inputs are incomplete")
    return _project_legacy_hybrid_review(
        project_root=project_root,
        omni_ledger=omni_ledger,
        displayed_image_sha256=displayed_image_sha256,
        displayed_image_size=displayed_image_size,
    )


def _project_legacy_hybrid_review(
    *,
    project_root: Path,
    omni_ledger: Mapping[str, Any],
    displayed_image_sha256: str,
    displayed_image_size: Mapping[str, int],
) -> dict[str, Any]:
    """持久化旧版 Omni-only UEI 投影，供既有引用继续重建。"""
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


def _project_full_parent_hybrid_review(
    *,
    capture_bundle: Mapping[str, Any],
    omni_inventory: Mapping[str, Any],
    qwen_bindings: Mapping[str, Any],
    fusion_result: Mapping[str, Any],
    vista_proposals: Mapping[str, Any],
) -> dict[str, Any]:
    bundle = validate_current_capture_bundle(capture_bundle)
    inventory = validate_omni_inventory(omni_inventory)
    bindings = validate_qwen_bindings(qwen_bindings, inventory)
    fusion = validate_fusion_result(fusion_result, inventory, bindings)
    if bindings["context_ref"] != bundle["context_ref"]:
        raise ValueError("Qwen context does not match current capture bundle")
    if canonical_json_bytes(inventory["capture_identity"]) != canonical_json_bytes(
        bundle["capture_identity"]
    ):
        raise ValueError("Omni inventory does not match current capture bundle")
    raw_vista = deepcopy(dict(vista_proposals))
    permitted_rois = _trusted_permitted_vista_rois(bundle=bundle, fusion=fusion)
    vista = validate_vista_proposals(
        raw_vista,
        fusion,
        inventory,
        bindings,
        permitted_rois,
    )
    bindings_by_id = {item["candidate_id"]: item for item in bindings["bindings"]}
    fusion_by_id = {item["candidate_id"]: item for item in fusion["candidates"]}
    vista_by_id = {item["candidate_id"]: item for item in vista["proposals"]}
    provider_items = {
        item["source_item_id"]: item for item in inventory["provider_result"]["items"]
    }
    candidates = [
        _full_parent_candidate_projection(
            inventory=inventory,
            candidate=candidate,
            provider_item=provider_items[candidate["source_item_id"]],
            qwen_binding=bindings_by_id.get(candidate["candidate_id"]),
            fusion_decision=fusion_by_id[candidate["candidate_id"]],
            vista_proposal=vista_by_id.get(candidate["candidate_id"]),
        )
        for candidate in inventory["candidates"]
    ]
    screen_warnings = sorted(
        {
            warning
            for candidate in candidates
            for warning in candidate["warnings"]
            if warning.startswith("capture_")
        }
    )
    base = {
        "contract_version": "hybrid_review_projection_v2",
        "projection_id": "",
        "screen_facts": {
            "capture_id": bundle["capture_identity"]["capture_id"],
            "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
            "displayed_image": {
                "sha256": bundle["capture_identity"]["screenshot_sha256"],
                "image_size": deepcopy(bundle["capture_identity"]["image_size"]),
            },
            "coordinate_space": bundle["capture_identity"]["capture_coordinate_space"],
            "workflow_revision": bundle["workflow_revision"],
            "warnings": screen_warnings,
        },
        "parent_refs": {
            "hybrid_capture_bundle_ref": deepcopy(bundle.get("bundle_ref")),
            "provider_result_ref": deepcopy(inventory["provider_result_ref"]),
            "qwen_context_ref": deepcopy(bindings["context_ref"]),
            "fusion_config_sha256": fusion["config_sha256"],
        },
        "parent_evidence": {
            "capture_bundle": deepcopy(bundle),
            "omni_inventory": deepcopy(inventory),
            "qwen_bindings": deepcopy(bindings),
            "fusion_result": deepcopy(fusion),
            "vista_proposals": deepcopy(vista),
        },
        "candidates": candidates,
        "warnings": sorted({warning for item in candidates for warning in item["warnings"]}),
        "review_decisions": [],
        "review_only": True,
        "display_only": True,
        "action_candidates": [],
        **_NON_AUTHORIZING,
    }
    base["projection_id"] = "hybrid-review-projection/v2/" + sha256(
        canonical_json_bytes(base)
    ).hexdigest()
    return seal_immutable(base)


def _trusted_permitted_vista_rois(
    *, bundle: Mapping[str, Any], fusion: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """按 Task 7 的确定性裁剪策略重建许可 ROI，不采信 proposal 自述。"""

    image_size = bundle["capture_identity"]["image_size"]
    lineage_ref = bundle["capture_lineage_ref"]
    permitted: dict[str, dict[str, Any]] = {}
    for candidate in fusion["candidates"]:
        if candidate["state"] != "BOUND":
            continue
        candidate_id = candidate["candidate_id"]
        bbox = candidate["bbox_original"]
        bbox_dict = {
            "x": bbox[0],
            "y": bbox[1],
            "w": bbox[2] - bbox[0],
            "h": bbox[3] - bbox[1],
        }
        roi_metadata = build_roi_crop_metadata(
            source_image_size=image_size,
            candidate_bbox=bbox_dict,
            crop_size={
                "width": max(1, bbox_dict["w"] * 2),
                "height": max(1, bbox_dict["h"] * 2),
            },
            expand_scale=2.0,
        )
        roi_bbox = roi_metadata["coordinate_transform"]["roi_bbox"]
        permitted[candidate_id] = seal_immutable(
            {
                "contract_version": "hybrid_permitted_roi_v1",
                "roi_id": f"roi/{candidate_id}",
                "candidate_id": candidate_id,
                "capture_lineage_ref": deepcopy(lineage_ref),
                "coordinate_space": "capture_pixel_xyxy",
                "xyxy": [
                    roi_bbox["x"],
                    roi_bbox["y"],
                    roi_bbox["x"] + roi_bbox["w"],
                    roi_bbox["y"] + roi_bbox["h"],
                ],
                "permitted_for_refinement": True,
            }
        )
    return permitted


def _full_parent_candidate_projection(
    *,
    inventory: Mapping[str, Any],
    candidate: Mapping[str, Any],
    provider_item: Mapping[str, Any],
    qwen_binding: Mapping[str, Any] | None,
    fusion_decision: Mapping[str, Any],
    vista_proposal: Mapping[str, Any] | None,
) -> dict[str, Any]:
    bbox = deepcopy(candidate["bbox_original"])
    semantics = qwen_binding or {
        "role": "review_only",
        "label": provider_item.get("safe_text") or provider_item.get("safe_role") or provider_item["kind"],
        "description": "",
    }
    warnings: list[str] = []
    if candidate["confidence"] is None:
        warnings.append("provider_confidence_unavailable")
    elif candidate["confidence"] < 0.5:
        warnings.append("low_provider_confidence")
    if not candidate["active"]:
        warnings.append("inactive_candidate_visible_for_audit")
    if fusion_decision["state"] != "BOUND":
        warnings.append(f"fusion_{str(fusion_decision['state']).casefold()}")
    if fusion_decision["state"] == "BOUND" and vista_proposal is None:
        warnings.append("vista_proposal_missing")
    return {
        "candidate_id": candidate["candidate_id"],
        "origin_id": candidate["candidate_id"],
        "model_proposal": {
            "bbox_original": bbox,
            "coordinate_space": candidate["coordinate_space"],
            "omni_candidate": deepcopy(dict(candidate)),
            "provider_item": deepcopy(dict(provider_item)),
            "qwen_binding": deepcopy(dict(qwen_binding)) if qwen_binding is not None else None,
            "fusion_decision": deepcopy(dict(fusion_decision)),
            "vista_proposal": deepcopy(dict(vista_proposal)) if vista_proposal is not None else None,
            "compact_provenance": {
                "provider_id": inventory["provider_id"],
                "provider_revision": inventory["provider_revision"],
                "provider_result_ref": deepcopy(inventory["provider_result_ref"]),
                "source_item_id": candidate["source_item_id"],
                "candidate_provenance": deepcopy(candidate["provenance"]),
            },
        },
        "review_decisions": [],
        "reviewed_geometry": {
            "bbox": bbox,
            "coordinate_space": candidate["coordinate_space"],
            "source": "model_original",
            "revision": 0,
        },
        "reviewed_semantics": {
            "role": str(semantics.get("role") or "review_only"),
            "label": str(semantics.get("label") or ""),
            "description": str(semantics.get("description") or ""),
            "revision": 0,
        },
        "human_point_proposal": None,
        "tombstone": None,
        "warnings": warnings,
        "reviewed_by_human": False,
        "candidate_only": True,
        "requires_human_review": True,
        "review_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "action_candidates": [],
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "authorization_scope": "display_and_review_only",
    }


def apply_hybrid_review_decisions(
    projection: Mapping[str, Any], decisions: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """追加人工决定并重建派生视图，绝不改写模型父证据。"""
    if not isinstance(projection, Mapping):
        raise ValueError("Hybrid review projection must be an object")
    if isinstance(decisions, list) and len(decisions) > 1:
        current = deepcopy(dict(projection))
        for decision in decisions:
            current = apply_hybrid_review_decisions(current, [decision])
        return current
    result = deepcopy(dict(projection))
    if result.get("contract_version") != "hybrid_review_projection_v2":
        raise ValueError("Hybrid review projection contract is invalid")
    declared_hash = result.pop("content_sha256", None)
    if declared_hash is not None and declared_hash != content_sha256(projection):
        raise ValueError("Hybrid review projection content_sha256 mismatch")
    if not isinstance(result.get("candidates"), list):
        raise ValueError("Hybrid review projection candidates are invalid")
    if not isinstance(decisions, list):
        raise ValueError("Hybrid review decisions must be a list")
    candidate_by_id = {
        candidate.get("candidate_id"): candidate
        for candidate in result["candidates"]
        if isinstance(candidate, dict) and isinstance(candidate.get("candidate_id"), str)
    }
    if len(candidate_by_id) != len(result["candidates"]):
        raise ValueError("Hybrid review candidate identity set is invalid")
    existing_decision_ids = {
        decision.get("decision_id")
        for candidate in result["candidates"]
        for decision in candidate.get("review_decisions", [])
        if isinstance(candidate, dict) and isinstance(decision, dict)
    }
    top_level = result.get("review_decisions")
    if not isinstance(top_level, list):
        raise ValueError("Hybrid review decision ledger is invalid")
    for raw_decision in decisions:
        decision = _validated_review_decision(raw_decision)
        decision_id = decision["decision_id"]
        if decision_id in existing_decision_ids:
            raise ValueError("duplicate review decision_id")
        existing_decision_ids.add(decision_id)
        if decision["decision_type"] == "add":
            candidate = _human_candidate_from_add(
                projection=result,
                decision=decision,
                sequence=sum(
                    1
                    for item in result["candidates"]
                    if isinstance(item.get("origin_id"), str)
                    and item["origin_id"].startswith("human/")
                )
                + 1,
            )
            result["candidates"].append(candidate)
            candidate_by_id[candidate["candidate_id"]] = candidate
        else:
            candidate_id = decision["candidate_id"]
            candidate = candidate_by_id.get(candidate_id)
            if candidate is None:
                raise ValueError(f"unknown Hybrid review candidate: {candidate_id}")
            _apply_review_decision(candidate, decision, result["screen_facts"])
        recorded = deepcopy(decision)
        recorded["candidate_id"] = candidate["candidate_id"]
        recorded["decision_index"] = len(top_level) + 1
        recorded["revokes_current_approval"] = True
        candidate.setdefault("review_decisions", []).append(deepcopy(recorded))
        candidate["reviewed_by_human"] = False
        top_level.append(recorded)
    base_for_id = deepcopy(result)
    base_for_id["projection_id"] = ""
    result["projection_id"] = "hybrid-review-projection/v2/" + sha256(
        canonical_json_bytes(base_for_id)
    ).hexdigest()
    return seal_immutable(result)


def _validated_review_decision(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Hybrid review decision must be an object")
    decision = deepcopy(dict(value))
    decision_type = decision.get("decision_type")
    fields_by_type = {
        "rebox": {"decision_id", "decision_type", "candidate_id", "bbox"},
        "semantic_edit": {"decision_id", "decision_type", "candidate_id", "semantics"},
        "human_point": {
            "decision_id",
            "decision_type",
            "candidate_id",
            "human_point_proposal",
        },
        "tombstone": {"decision_id", "decision_type", "candidate_id", "reason"},
        "mark_unavailable": {"decision_id", "decision_type", "candidate_id", "reason"},
        "add": {"decision_id", "decision_type", "candidate_id", "bbox", "semantics"},
    }
    expected = fields_by_type.get(decision_type)
    if expected is None or set(decision) != expected:
        raise ValueError("Hybrid review decision is not closed")
    decision_id = decision.get("decision_id")
    if not isinstance(decision_id, str) or not decision_id.startswith("decision/"):
        raise ValueError("Hybrid review decision_id is invalid")
    if decision_type != "add" and not isinstance(decision.get("candidate_id"), str):
        raise ValueError("Hybrid review candidate_id is invalid")
    if decision_type == "add" and decision.get("candidate_id") is not None:
        candidate_id = decision.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.startswith("human/"):
            raise ValueError("Human candidate_id is invalid")
    if "bbox" in decision:
        decision["bbox"] = _review_bbox(decision["bbox"])
    if "semantics" in decision:
        semantics = decision["semantics"]
        if not isinstance(semantics, Mapping) or set(semantics) != {
            "role",
            "label",
            "description",
        }:
            raise ValueError("Hybrid review semantics are not closed")
        decision["semantics"] = {
            key: str(semantics[key]).strip() for key in ("role", "label", "description")
        }
        if not decision["semantics"]["role"] or not decision["semantics"]["label"]:
            raise ValueError("Hybrid review role and label are required")
    if "human_point_proposal" in decision:
        point = decision["human_point_proposal"]
        if (
            not isinstance(point, Mapping)
            or set(point) != {"coordinate_space", "xy"}
            or point.get("coordinate_space") != "capture_pixel_xyxy"
            or not isinstance(point.get("xy"), list)
            or len(point["xy"]) != 2
            or not all(isinstance(edge, (int, float)) and not isinstance(edge, bool) for edge in point["xy"])
        ):
            raise ValueError("Human point proposal is invalid")
        decision["human_point_proposal"] = deepcopy(dict(point))
    if "reason" in decision and (
        not isinstance(decision["reason"], str) or not decision["reason"].strip()
    ):
        raise ValueError("Hybrid review tombstone reason is required")
    return decision


def _apply_review_decision(
    candidate: dict[str, Any], decision: dict[str, Any], screen_facts: Mapping[str, Any]
) -> None:
    decision_type = decision["decision_type"]
    if decision_type == "rebox":
        _require_geometry_inside_capture(decision["bbox"], screen_facts)
        candidate["reviewed_geometry"] = {
            "bbox": deepcopy(decision["bbox"]),
            "coordinate_space": "capture_pixel_xyxy",
            "source": "human_rebox",
            "revision": len(candidate.get("review_decisions", [])) + 1,
        }
    elif decision_type == "semantic_edit":
        candidate["reviewed_semantics"] = {
            **deepcopy(decision["semantics"]),
            "revision": len(candidate.get("review_decisions", [])) + 1,
        }
    elif decision_type == "human_point":
        xy = decision["human_point_proposal"]["xy"]
        bbox = candidate["reviewed_geometry"]["bbox"]
        if not (bbox[0] <= xy[0] <= bbox[2] and bbox[1] <= xy[1] <= bbox[3]):
            raise ValueError("Human point proposal must remain inside reviewed geometry")
        candidate["human_point_proposal"] = {
            **deepcopy(decision["human_point_proposal"]),
            "source": "human_review",
            "revision": len(candidate.get("review_decisions", [])) + 1,
        }
    elif decision_type in {"tombstone", "mark_unavailable"}:
        candidate["tombstone"] = {
            "reason": decision["reason"].strip(),
            "decision_type": decision_type,
            "revision": len(candidate.get("review_decisions", [])) + 1,
        }


def _human_candidate_from_add(
    *, projection: Mapping[str, Any], decision: dict[str, Any], sequence: int
) -> dict[str, Any]:
    _require_geometry_inside_capture(decision["bbox"], projection["screen_facts"])
    requested_id = decision.get("candidate_id")
    projection_token = str(projection["projection_id"]).rstrip("/").rsplit("/", 1)[-1]
    candidate_id = (
        requested_id
        if isinstance(requested_id, str)
        else f"human/{projection_token}/{sequence}"
    )
    if any(
        isinstance(item, Mapping) and item.get("candidate_id") == candidate_id
        for item in projection["candidates"]
    ):
        raise ValueError("Human candidate_id is already present")
    return {
        "candidate_id": candidate_id,
        "origin_id": candidate_id,
        "model_proposal": None,
        "human_origin": {
            "bbox_initial": deepcopy(decision["bbox"]),
            "semantics_initial": deepcopy(decision["semantics"]),
            "coordinate_space": "capture_pixel_xyxy",
        },
        "review_decisions": [],
        "reviewed_geometry": {
            "bbox": deepcopy(decision["bbox"]),
            "coordinate_space": "capture_pixel_xyxy",
            "source": "human_add",
            "revision": 1,
        },
        "reviewed_semantics": {**deepcopy(decision["semantics"]), "revision": 1},
        "human_point_proposal": None,
        "tombstone": None,
        "warnings": [],
        "reviewed_by_human": False,
        "candidate_only": True,
        "requires_human_review": True,
        "review_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "action_candidates": [],
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "authorization_scope": "display_and_review_only",
    }


def _review_bbox(value: Any) -> list[int | float]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(isinstance(edge, (int, float)) and not isinstance(edge, bool) for edge in value)
        or value[0] >= value[2]
        or value[1] >= value[3]
    ):
        raise ValueError("Hybrid review bbox is invalid")
    return deepcopy(value)


def _require_geometry_inside_capture(
    bbox: list[int | float], screen_facts: Mapping[str, Any]
) -> None:
    displayed = screen_facts.get("displayed_image")
    size = displayed.get("image_size") if isinstance(displayed, Mapping) else None
    if (
        not isinstance(size, Mapping)
        or bbox[0] < 0
        or bbox[1] < 0
        or bbox[2] > size.get("width", -1)
        or bbox[3] > size.get("height", -1)
    ):
        raise ValueError("Hybrid review bbox must remain inside capture bounds")


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
    if projection.get("contract_version") == "hybrid_review_projection_v2":
        return _validate_full_parent_review_projection(projection)
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


def _validate_full_parent_review_projection(projection: dict[str, Any]) -> dict[str, Any]:
    if projection.get("content_sha256") != content_sha256(projection):
        raise ValueError("Hybrid review projection content_sha256 mismatch")
    _require_non_authorizing(projection)
    if (
        projection.get("display_only") is not True
        or projection.get("review_only") is not True
        or projection.get("action_candidates") != []
    ):
        raise ValueError("Hybrid review projection is not read-only")
    parents = projection.get("parent_evidence")
    if not isinstance(parents, Mapping) or set(parents) != {
        "capture_bundle",
        "omni_inventory",
        "qwen_bindings",
        "fusion_result",
        "vista_proposals",
    }:
        raise ValueError("Hybrid review full parent evidence is invalid")
    rebuilt = _project_full_parent_hybrid_review(
        capture_bundle=parents["capture_bundle"],
        omni_inventory=parents["omni_inventory"],
        qwen_bindings=parents["qwen_bindings"],
        fusion_result=parents["fusion_result"],
        vista_proposals=parents["vista_proposals"],
    )
    for decision in projection.get("review_decisions", []):
        rebuilt = apply_hybrid_review_decisions(
            rebuilt,
            [_decision_replay_input(decision)],
        )
    if canonical_json_bytes(rebuilt) != canonical_json_bytes(projection):
        raise ValueError("Hybrid review projection evidence mismatch")
    return projection


def _decision_replay_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Hybrid review decision ledger is invalid")
    result = deepcopy(dict(value))
    result.pop("decision_index", None)
    result.pop("revokes_current_approval", None)
    return result


def render_full_parent_hybrid_review_candidates(
    projection: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """把已复验的完整父投影转换为现有 Large Review 区域。"""
    reviewed = validate_hybrid_review_projection(projection)
    if reviewed["contract_version"] != "hybrid_review_projection_v2":
        raise ValueError("full-parent Hybrid review projection is required")
    regions: list[dict[str, Any]] = []
    for candidate in reviewed["candidates"]:
        geometry = candidate.get("reviewed_geometry")
        bbox = geometry.get("bbox") if isinstance(geometry, Mapping) else None
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("Hybrid reviewed geometry is invalid")
        model = candidate.get("model_proposal")
        model = model if isinstance(model, Mapping) else {}
        semantics = candidate.get("reviewed_semantics")
        semantics = semantics if isinstance(semantics, Mapping) else {}
        compact = model.get("compact_provenance")
        compact = compact if isinstance(compact, Mapping) else {
            "provider_id": "human",
            "provider_revision": "human_review",
            "source_item_id": candidate["origin_id"],
        }
        regions.append(
            {
                "candidate_id": candidate["candidate_id"],
                "region_id": candidate["candidate_id"],
                "origin_id": candidate["origin_id"],
                "label": str(semantics.get("label") or ""),
                "role": str(semantics.get("role") or "review_only"),
                "kind": "hybrid_review_candidate",
                "bbox": {
                    "x": bbox[0],
                    "y": bbox[1],
                    "w": bbox[2] - bbox[0],
                    "h": bbox[3] - bbox[1],
                },
                "bbox_original": deepcopy(model.get("bbox_original")),
                "reviewed_geometry": deepcopy(dict(geometry)),
                "reviewed_semantics": deepcopy(dict(semantics)),
                "human_point_proposal": deepcopy(candidate.get("human_point_proposal")),
                "tombstone": deepcopy(candidate.get("tombstone")),
                "review_decisions": deepcopy(candidate.get("review_decisions", [])),
                "model_proposal": deepcopy(candidate.get("model_proposal")),
                "provider_provenance": deepcopy(dict(compact)),
                "warnings": deepcopy(candidate.get("warnings", [])),
                "active": candidate.get("tombstone") is None,
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
        )
    return regions


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
    if candidate["confidence"] is None:
        warnings.append("provider_confidence_unavailable")
    elif candidate["confidence"] < 0.5:
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
    if any(candidate["confidence"] is None for candidate in candidates):
        warnings.append("provider_confidence_unavailable")
    if any(
        candidate["confidence"] is not None and candidate["confidence"] < 0.5
        for candidate in candidates
    ):
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
