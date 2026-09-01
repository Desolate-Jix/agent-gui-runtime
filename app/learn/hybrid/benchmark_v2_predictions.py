"""Sealed public evidence contracts for Benchmark-v2 automatic predictions."""
from __future__ import annotations
import base64
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from app.learn.hybrid.benchmark_v2_pathless import (
    pathless_artifact_ref,
    order_pathless_envelopes,
    seal_pathless_envelope,
    seal_pathless_projection,
    validate_pathless_recursive,
    validate_pathless_ref,
)

SAFETY={"artifact_is_authorization":False,"execute_binding_enabled":False,"display_only":True}
ARMS=("qwen_only","omni_only_discovery","omni_to_qwen","omni_to_qwen_vista")
STATUSES={"selected","missing","failed"}
ELIGIBILITY={"selected":"ELIGIBLE","missing":"INELIGIBLE","failed":"INELIGIBLE"}
_PATHLESS_PROJECTION_CONTRACTS = {
    "benchmark_v2_nested_provider_evidence_ref_v1",
    "sealed_prediction_source_parent_v1",
    "sealed_prediction_bbox_v1",
    "sealed_target_binding_v4",
    "sealed_vista_request_v4",
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")

def artifact_ref(artifact: Mapping[str,object]) -> dict[str,str]:
    if artifact.get("contract_version") in _PATHLESS_PROJECTION_CONTRACTS:
        return pathless_artifact_ref(artifact)
    raw=canonical_bytes(artifact)
    return {"id":str(artifact["artifact_id"]),"content_sha256":hashlib.sha256(raw).hexdigest()}

def sealed_artifact_envelope(artifact: Mapping[str,object]) -> dict[str,object]:
    if artifact.get("contract_version") in _PATHLESS_PROJECTION_CONTRACTS:
        return seal_pathless_envelope(artifact)
    raw=canonical_bytes(artifact)
    return {"ref":artifact_ref(artifact),"canonical_bytes_b64":base64.b64encode(raw).decode("ascii")}

def exact_ref(value: object,name: str) -> dict[str,str]:
    if not isinstance(value,Mapping) or set(value)!={"id","content_sha256"}: raise ValueError(f"{name} must be exact ref")
    result=dict(value)
    if not isinstance(result["id"],str) or not result["id"] or not isinstance(result["content_sha256"],str) or len(result["content_sha256"])!=64: raise ValueError(f"{name} invalid")
    return result


_GOAL_RE = re.compile(r"Select the ([a-z]+) labeled '([^'\r\n]+)'")
_ROLE_ALIASES = {
    "button": {"button"},
    "checkbox": {"checkbox"},
    "combobox": {"combobox", "select", "dropdown"},
    "link": {"link", "hyperlink"},
    "menuitem": {"menuitem", "menu_item"},
    "tab": {"tab", "tab_item"},
    "textbox": {"textbox", "input", "text_input", "search_box", "search_input", "edit"},
}
_RAW_REF_FORMULAS = {
    "omni_inventory": ("omni-inventory", b"benchmark-v2-omni-inventory\0"),
    "qwen_bindings": ("qwen-bindings", b"benchmark-v2-qwen-bindings\0"),
    "fusion_result": ("fusion-result", b"benchmark-v2-fusion-result\0"),
    "submitted_vista_request": ("submitted-vista-request", b"benchmark-v2-submitted-vista-request\0"),
}


def _normalized_text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{name} must be non-empty")
    return normalized


def _public_identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} public identifier is invalid")
    lowered = value.lower()
    segments = value.split("/")
    if (
        value.startswith(("/", "\\"))
        or re.match(r"^[a-zA-Z]:[\\/]", value) is not None
        or lowered.startswith("file:")
        or "\\" in value
        or "%" in value
        or any(ord(character) < 32 for character in value)
        or any(segment in {"", ".", "..", "~"} or segment != segment.strip() for segment in segments)
    ):
        raise ValueError(f"{name} public identifier cannot contain a filesystem path or alias escape")
    return value


def parse_benchmark_v2_goal(goal: object) -> tuple[str, str]:
    """解析冻结的 Benchmark-v2 目标语法，不做大小写或模糊归一化。"""

    if not isinstance(goal, str):
        raise ValueError("benchmark goal grammar is invalid")
    match = _GOAL_RE.fullmatch(goal)
    if match is None or match.group(1) not in _ROLE_ALIASES:
        raise ValueError("benchmark goal grammar is invalid")
    return match.group(1), _normalized_text(match.group(2), "benchmark goal label")


def _s12_ref(value: object, name: str) -> dict[str, str]:
    result = exact_ref(value, name)
    result["id"] = _public_identifier(result["id"], name)
    digest = result["content_sha256"]
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError(f"{name} invalid")
    return result


def _raw_class_ref(value: object, evidence_class: str) -> dict[str, str]:
    try:
        prefix, domain = _RAW_REF_FORMULAS[evidence_class]
    except KeyError as exc:
        raise ValueError("unknown provider evidence class") from exc
    raw = canonical_bytes(value)
    return {
        "id": f"{prefix}/{hashlib.sha256(domain + raw).hexdigest()}",
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _nested_evidence(
    *,
    evidence_kind: str,
    canonical_value: object,
    case_ref: Mapping[str, str],
    actual_screen_group_ref: Mapping[str, str],
) -> dict[str, object]:
    return seal_pathless_projection(
        contract_version="benchmark_v2_nested_provider_evidence_ref_v1",
        semantic_payload={
            "evidence_kind": evidence_kind,
            "case_ref": deepcopy(dict(case_ref)),
            "actual_screen_group_ref": deepcopy(dict(actual_screen_group_ref)),
            "canonical_value_sha256": hashlib.sha256(canonical_bytes(canonical_value)).hexdigest(),
            "safety": deepcopy(SAFETY),
        },
    )


def _xyxy(value: object, name: str) -> list[int]:
    if isinstance(value, Mapping):
        if not {"x", "y", "w", "h"}.issubset(value):
            raise ValueError(f"{name} is invalid")
        components = [value["x"], value["y"], value["w"], value["h"]]
        if any(isinstance(item, bool) or not isinstance(item, int) for item in components):
            raise ValueError(f"{name} is invalid")
        raw = [components[0], components[1], components[0] + components[2], components[1] + components[3]]
    else:
        raw = value
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in raw)
        or raw[2] <= raw[0]
        or raw[3] <= raw[1]
    ):
        raise ValueError(f"{name} is invalid")
    return list(raw)


def _matches_target(value: Mapping[str, object], *, role_field: str, label_field: str, goal_role: str, goal_label: str) -> bool:
    raw_role = value.get(role_field)
    raw_label = value.get(label_field)
    if not isinstance(raw_role, str) or not isinstance(raw_label, str):
        return False
    role = " ".join(raw_role.split())
    label = " ".join(raw_label.split())
    if not role or not label:
        return False
    return role in _ROLE_ALIASES[goal_role] and label == goal_label


def _unique_semantic_match(
    values: object,
    *,
    role_field: str,
    label_field: str,
    goal_role: str,
    goal_label: str,
    name: str,
) -> Mapping[str, object] | None:
    if not isinstance(values, list):
        raise ValueError(f"{name} must be a list")
    matches = []
    for item in values:
        if not isinstance(item, Mapping):
            raise ValueError(f"{name} item is invalid")
        if _matches_target(item, role_field=role_field, label_field=label_field, goal_role=goal_role, goal_label=goal_label):
            matches.append(item)
    if len(matches) > 1:
        raise ValueError(f"duplicate {name} target is ambiguous")
    return matches[0] if matches else None


def _source_parent(
    *,
    case_ref: Mapping[str, str],
    arm_scope: list[str],
    source_kind: str,
    evidence_refs: Mapping[str, Mapping[str, str]],
    actual_screen_group_ref: Mapping[str, str],
    capture_ref: Mapping[str, str],
) -> dict[str, object]:
    required = {
        "incumbent_qwen_action": {"incumbent_response_ref", "available_action_ref"},
        "omni_inventory_item": {"omni_inventory_ref", "omni_item_ref"},
        "hybrid_bound_fusion_candidate": {"omni_inventory_ref", "qwen_bindings_ref", "fusion_result_ref", "fusion_candidate_ref"},
    }
    if source_kind not in required or set(evidence_refs) != required[source_kind]:
        raise ValueError("source parent evidence refs are not closed")
    refs = {key: _s12_ref(value, key) for key, value in evidence_refs.items()}
    return seal_pathless_projection(
        contract_version="sealed_prediction_source_parent_v1",
        semantic_payload={
            "case_ref": deepcopy(dict(case_ref)),
            "arm_scope": list(arm_scope),
            "source_kind": source_kind,
            "evidence_refs": refs,
            "actual_screen_group_ref": deepcopy(dict(actual_screen_group_ref)),
            "capture_ref": deepcopy(dict(capture_ref)),
            "safety": deepcopy(SAFETY),
        },
    )


def _selection_artifacts(
    *,
    case_id: str,
    arm_scope: list[str],
    candidate_id: str,
    bbox: list[int],
    capture_ref: Mapping[str, str],
    source_parent: Mapping[str, object],
    submitted_request_ref: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    candidate_id = _public_identifier(candidate_id, "candidate")
    parent_ref = validate_pathless_ref(
        role="source_parent_ref",
        value=pathless_artifact_ref(source_parent),
        context={"contract_version": "sealed_prediction_bbox_v1"},
    )
    bbox_artifact = seal_pathless_projection(
        contract_version="sealed_prediction_bbox_v1",
        semantic_payload={
            "case_id": case_id,
            "arm_scope": list(arm_scope),
            "candidate_id": candidate_id,
            "coordinate_space": "capture_pixel_xyxy",
            "xyxy": list(bbox),
            "capture_ref": deepcopy(dict(capture_ref)),
            "source_parent_ref": parent_ref,
            "safety": deepcopy(SAFETY),
        },
    )
    bbox_ref = pathless_artifact_ref(bbox_artifact)
    binding = seal_pathless_projection(
        contract_version="sealed_target_binding_v4",
        semantic_payload={
            "case_id": case_id,
            "arm_scope": list(arm_scope),
            "candidate_id": candidate_id,
            "source_parent_ref": parent_ref,
            "capture_ref": deepcopy(dict(capture_ref)),
            "bbox_ref": bbox_ref,
            "safety": deepcopy(SAFETY),
        },
    )
    result = [deepcopy(dict(source_parent)), bbox_artifact, binding]
    if submitted_request_ref is not None:
        if arm_scope != ["omni_to_qwen", "omni_to_qwen_vista"]:
            raise ValueError("only the paired hybrid scope may create a VISTA request")
        request = seal_pathless_projection(
            contract_version="sealed_vista_request_v4",
            semantic_payload={
                "case_id": case_id,
                "arm_scope": list(arm_scope),
                "candidate_id": candidate_id,
                "target_binding_ref": pathless_artifact_ref(binding),
                "source_parent_ref": parent_ref,
                "capture_ref": deepcopy(dict(capture_ref)),
                "bbox_ref": bbox_ref,
                "submitted_request_ref": deepcopy(dict(submitted_request_ref)),
                "submission_status": "SUBMITTED",
                "safety": deepcopy(SAFETY),
            },
        )
        result.append(request)
    return result


def _selected_row(case_id: str, arm_id: str, artifacts: list[Mapping[str, object]]) -> dict[str, object]:
    source, bbox, binding = artifacts[:3]
    row = {
        "case_id": case_id,
        "arm_id": arm_id,
        "selection_status": "selected",
        "eligibility": "ELIGIBLE",
        "candidate_id": binding["candidate_id"],
        "source_parent_ref": pathless_artifact_ref(source),
        "bbox_ref": pathless_artifact_ref(bbox),
        "target_binding_ref": pathless_artifact_ref(binding),
    }
    if len(artifacts) == 4:
        row["vista_request_ref"] = pathless_artifact_ref(artifacts[3])
    return row


def _missing_row(case_id: str, arm_id: str, reason: str) -> dict[str, object]:
    return {"case_id": case_id, "arm_id": arm_id, "selection_status": "missing", "eligibility": "INELIGIBLE", "failure_reason": reason}


def select_pre_vista_prediction_rows(
    *,
    provider_case: Mapping[str, object],
    incumbent_response: Mapping[str, object],
    omni_inventory: Mapping[str, object],
    qwen_bindings: Mapping[str, object],
    fusion_result: Mapping[str, object],
    submitted_vista_requests: list[Mapping[str, object]],
    actual_screen_group_ref: Mapping[str, str],
    capture_ref: Mapping[str, str],
) -> dict[str, object]:
    """只用 pre-VISTA 原始证据确定四臂目标；VISTA 结果不能参与选择。"""

    if not isinstance(provider_case, Mapping) or set(provider_case) != {"case_id", "partition", "screen_group", "goal", "image", "layout"}:
        raise ValueError("provider case is not closed")
    case_id = _public_identifier(provider_case.get("case_id"), "provider case")
    goal_role, goal_label = parse_benchmark_v2_goal(provider_case.get("goal"))
    case_ref = {"case_id": case_id, "case_content_sha256": hashlib.sha256(canonical_bytes(provider_case)).hexdigest()}
    group_ref = _s12_ref(actual_screen_group_ref, "actual screen group ref")
    capture = _s12_ref(capture_ref, "capture ref")
    artifacts: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []

    if not isinstance(submitted_vista_requests, list):
        raise ValueError("submitted VISTA requests must be a list")
    request_ids = [_public_identifier(item.get("candidate_id"), "submitted VISTA request candidate") for item in submitted_vista_requests if isinstance(item, Mapping)]
    if (
        len(request_ids) != len(submitted_vista_requests)
        or len(set(request_ids)) != len(request_ids)
        or any(item.get("submission_status") != "SUBMITTED" for item in submitted_vista_requests)
    ):
        raise ValueError("duplicate or invalid submitted VISTA request")
    fusion_candidates = fusion_result.get("candidates") if isinstance(fusion_result, Mapping) else None
    if not isinstance(fusion_candidates, list):
        raise ValueError("fusion result is incomplete")
    fusion_ids = [_public_identifier(item.get("candidate_id"), "fusion candidate") for item in fusion_candidates if isinstance(item, Mapping)]
    if (
        len(fusion_ids) != len(fusion_candidates)
        or len(set(fusion_ids)) != len(fusion_ids)
    ):
        raise ValueError("duplicate fusion candidate identity")

    if not isinstance(incumbent_response, Mapping):
        raise ValueError("incumbent response is missing")
    screen = incumbent_response.get("screen_reading")
    inventory_view = screen.get("screen_inventory") if isinstance(screen, Mapping) else None
    actions = inventory_view.get("available_actions") if isinstance(inventory_view, Mapping) else None
    if not isinstance(actions, list):
        raise ValueError("incumbent available actions are missing")
    action_ids = [_public_identifier(item.get("id"), "incumbent action") for item in actions if isinstance(item, Mapping)]
    if len(action_ids) != len(actions) or len(set(action_ids)) != len(action_ids):
        raise ValueError("duplicate incumbent action identity")
    action = _unique_semantic_match(actions, role_field="role", label_field="label", goal_role=goal_role, goal_label=goal_label, name="incumbent action")
    if action is None:
        rows.append(_missing_row(case_id, "qwen_only", "target_not_present_pre_vista"))
    else:
        response_nested = _nested_evidence(evidence_kind="incumbent_response", canonical_value=incumbent_response, case_ref=case_ref, actual_screen_group_ref=group_ref)
        action_nested = _nested_evidence(evidence_kind="incumbent_available_action", canonical_value=action, case_ref=case_ref, actual_screen_group_ref=group_ref)
        artifacts.extend([response_nested, action_nested])
        parent = _source_parent(case_ref=case_ref, arm_scope=["qwen_only"], source_kind="incumbent_qwen_action", evidence_refs={"incumbent_response_ref": pathless_artifact_ref(response_nested), "available_action_ref": pathless_artifact_ref(action_nested)}, actual_screen_group_ref=group_ref, capture_ref=capture)
        selected = _selection_artifacts(case_id=case_id, arm_scope=["qwen_only"], candidate_id=str(action["id"]), bbox=_xyxy(action.get("bbox"), "incumbent action bbox"), capture_ref=capture, source_parent=parent)
        artifacts.extend(selected); rows.append(_selected_row(case_id, "qwen_only", selected))

    if not isinstance(omni_inventory, Mapping):
        raise ValueError("Omni inventory is missing")
    provider_result = omni_inventory.get("provider_result")
    items = provider_result.get("items") if isinstance(provider_result, Mapping) else None
    candidates = omni_inventory.get("candidates")
    if not isinstance(items, list) or not isinstance(candidates, list):
        raise ValueError("Omni inventory is incomplete")
    source_ids = [item.get("source_item_id") for item in items if isinstance(item, Mapping)]
    candidate_ids = [_public_identifier(item.get("candidate_id"), "Omni candidate") for item in candidates if isinstance(item, Mapping)]
    if len(source_ids) != len(items) or len(set(source_ids)) != len(source_ids) or len(candidate_ids) != len(candidates) or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("duplicate Omni candidate identity")
    omni_item = _unique_semantic_match(items, role_field="safe_role", label_field="safe_text", goal_role=goal_role, goal_label=goal_label, name="Omni item")
    omni_candidate = None
    if omni_item is not None:
        joined = [candidate for candidate in candidates if candidate.get("source_item_id") == omni_item.get("source_item_id")]
        if len(joined) != 1:
            raise ValueError("conflicting Omni item/candidate join")
        omni_candidate = joined[0]
        item_bbox = _xyxy(omni_item.get("capture_bbox"), "Omni item bbox")
        candidate_bbox = _xyxy(omni_candidate.get("bbox_original"), "Omni candidate bbox")
        if item_bbox != candidate_bbox or omni_candidate.get("coordinate_space") != "capture_pixel_xyxy":
            raise ValueError("conflicting Omni candidate geometry")
    if omni_item is None:
        rows.append(_missing_row(case_id, "omni_only_discovery", "target_not_present_pre_vista"))
    else:
        item_nested = _nested_evidence(evidence_kind="omni_inventory_item", canonical_value=omni_item, case_ref=case_ref, actual_screen_group_ref=group_ref)
        artifacts.append(item_nested)
        parent = _source_parent(case_ref=case_ref, arm_scope=["omni_only_discovery"], source_kind="omni_inventory_item", evidence_refs={"omni_inventory_ref": _raw_class_ref(omni_inventory, "omni_inventory"), "omni_item_ref": pathless_artifact_ref(item_nested)}, actual_screen_group_ref=group_ref, capture_ref=capture)
        selected = _selection_artifacts(case_id=case_id, arm_scope=["omni_only_discovery"], candidate_id=str(omni_candidate["candidate_id"]), bbox=_xyxy(omni_candidate.get("bbox_original"), "Omni candidate bbox"), capture_ref=capture, source_parent=parent)
        artifacts.extend(selected); rows.append(_selected_row(case_id, "omni_only_discovery", selected))

    if not isinstance(qwen_bindings, Mapping) or not isinstance(qwen_bindings.get("bindings"), list) or not isinstance(qwen_bindings.get("ambiguity_sets"), list):
        raise ValueError("Qwen bindings are incomplete")
    bindings = qwen_bindings["bindings"]
    binding_ids = [_public_identifier(item.get("candidate_id"), "Qwen binding candidate") for item in bindings if isinstance(item, Mapping)]
    if len(binding_ids) != len(bindings) or len(set(binding_ids)) != len(binding_ids):
        raise ValueError("duplicate Qwen binding candidate")
    memberships: set[str] = set()
    declared_sets: set[tuple[str, ...]] = set()
    for raw_set in qwen_bindings["ambiguity_sets"]:
        ids = raw_set.get("candidate_ids") if isinstance(raw_set, Mapping) else None
        if not isinstance(ids, list) or len(ids) < 2 or any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("ambiguous Qwen set is non-unique")
        identity = tuple(ids)
        if identity in declared_sets or memberships.intersection(ids):
            raise ValueError("ambiguous Qwen set is duplicated")
        declared_sets.add(identity); memberships.update(ids)
    qwen_binding = _unique_semantic_match(bindings, role_field="role", label_field="label", goal_role=goal_role, goal_label=goal_label, name="Qwen binding")
    if qwen_binding is None:
        rows.extend([_missing_row(case_id, arm, "target_not_present_pre_vista") for arm in ("omni_to_qwen", "omni_to_qwen_vista")])
    else:
        hybrid_candidate_id = qwen_binding.get("candidate_id")
        if qwen_binding.get("ambiguity") is not None or hybrid_candidate_id in memberships:
            raise ValueError("matching Qwen binding is ambiguous")
        matching_fusion = [item for item in fusion_candidates if item.get("candidate_id") == hybrid_candidate_id]
        if len(matching_fusion) != 1:
            raise ValueError("conflicting Qwen/fusion candidate join")
        fusion_candidate = matching_fusion[0]
        joined_omni = [candidate for candidate in candidates if candidate.get("candidate_id") == hybrid_candidate_id]
        if len(joined_omni) != 1:
            raise ValueError("conflicting fusion/Omni candidate join")
        if _xyxy(fusion_candidate.get("bbox_original"), "fusion bbox") != _xyxy(joined_omni[0].get("bbox_original"), "Omni bbox"):
            raise ValueError("conflicting fusion candidate geometry")
        if fusion_candidate.get("state") != "BOUND":
            rows.extend([_missing_row(case_id, arm, "fusion_not_bound") for arm in ("omni_to_qwen", "omni_to_qwen_vista")])
        else:
            selected_requests = [item for item in submitted_vista_requests if item.get("candidate_id") == hybrid_candidate_id]
            if len(selected_requests) != 1 or selected_requests[0].get("submission_status") != "SUBMITTED":
                raise ValueError("conflicting submitted VISTA request coverage")
            submitted = selected_requests[0]
            request_bbox = submitted.get("candidate_bbox_ref")
            if isinstance(request_bbox, Mapping) and "xyxy" in request_bbox and _xyxy(request_bbox.get("xyxy"), "submitted request bbox") != _xyxy(fusion_candidate.get("bbox_original"), "fusion bbox"):
                raise ValueError("conflicting submitted request geometry")
            fusion_nested = _nested_evidence(evidence_kind="hybrid_fusion_candidate", canonical_value=fusion_candidate, case_ref=case_ref, actual_screen_group_ref=group_ref)
            artifacts.append(fusion_nested)
            scope = ["omni_to_qwen", "omni_to_qwen_vista"]
            parent = _source_parent(case_ref=case_ref, arm_scope=scope, source_kind="hybrid_bound_fusion_candidate", evidence_refs={"omni_inventory_ref": _raw_class_ref(omni_inventory, "omni_inventory"), "qwen_bindings_ref": _raw_class_ref(qwen_bindings, "qwen_bindings"), "fusion_result_ref": _raw_class_ref(fusion_result, "fusion_result"), "fusion_candidate_ref": pathless_artifact_ref(fusion_nested)}, actual_screen_group_ref=group_ref, capture_ref=capture)
            selected = _selection_artifacts(case_id=case_id, arm_scope=scope, candidate_id=str(hybrid_candidate_id), bbox=_xyxy(fusion_candidate.get("bbox_original"), "fusion bbox"), capture_ref=capture, source_parent=parent, submitted_request_ref=_raw_class_ref(submitted, "submitted_vista_request"))
            artifacts.extend(selected)
            rows.extend([_selected_row(case_id, arm, selected) for arm in ("omni_to_qwen", "omni_to_qwen_vista")])

    by_id: dict[str, dict[str, object]] = {}
    for artifact in artifacts:
        prior = by_id.get(str(artifact["artifact_id"]))
        if prior is not None and prior != artifact:
            raise ValueError("conflicting sealed artifact identity")
        by_id[str(artifact["artifact_id"])] = artifact
    return {"rows": rows, "sealed_artifacts": list(by_id.values())}


def attach_vista_outcomes(selection: Mapping[str, object], vista_proposals: list[Mapping[str, object]]) -> dict[str, object]:
    """把 VISTA 结果附到已选行；不允许重选 candidate 或重铸任何父引用。"""

    if not isinstance(selection, Mapping) or set(selection) != {"rows", "sealed_artifacts"}:
        raise ValueError("pre-VISTA selection bundle is invalid")
    result = deepcopy(dict(selection))
    if not isinstance(result["rows"], list) or not isinstance(result["sealed_artifacts"], list) or not isinstance(vista_proposals, list):
        raise ValueError("VISTA outcome inputs are invalid")
    validated_artifacts = []
    for item in result["sealed_artifacts"]:
        if not isinstance(item, Mapping):
            raise ValueError("sealed prediction artifact is invalid")
        pathless_artifact_ref(item)
        validated_artifacts.append(deepcopy(dict(item)))
    artifacts = {(item["artifact_id"], item["content_sha256"]): item for item in validated_artifacts}
    if len(artifacts) != len(validated_artifacts):
        raise ValueError("duplicate sealed prediction artifact")
    vista_rows = [row for row in result["rows"] if isinstance(row, Mapping) and row.get("arm_id") == "omni_to_qwen_vista" and row.get("selection_status") == "selected"]
    if len(vista_rows) > 1:
        raise ValueError("duplicate selected VISTA row")
    if not vista_rows:
        return result
    row = vista_rows[0]
    request_ref = _s12_ref(row.get("vista_request_ref"), "selected VISTA request ref")
    request = artifacts.get((request_ref["id"], request_ref["content_sha256"]))
    binding_ref = _s12_ref(row.get("target_binding_ref"), "selected target binding ref")
    bbox_ref = _s12_ref(row.get("bbox_ref"), "selected bbox ref")
    bbox_artifact = artifacts.get((bbox_ref["id"], bbox_ref["content_sha256"]))
    if not isinstance(request, Mapping) or request.get("contract_version") != "sealed_vista_request_v4" or not isinstance(bbox_artifact, Mapping):
        raise ValueError("selected VISTA lineage is unresolved")
    if (
        request.get("candidate_id") != row.get("candidate_id")
        or request.get("target_binding_ref") != binding_ref
        or request.get("bbox_ref") != bbox_ref
        or request.get("submission_status") != "SUBMITTED"
        or bbox_artifact.get("candidate_id") != row.get("candidate_id")
    ):
        raise ValueError("selected VISTA lineage is conflicting")
    baseline_rows = [candidate for candidate in result["rows"] if isinstance(candidate, Mapping) and candidate.get("arm_id") == "omni_to_qwen"]
    if len(baseline_rows) != 1 or any(baseline_rows[0].get(name) != row.get(name) for name in ("candidate_id", "source_parent_ref", "bbox_ref", "target_binding_ref", "vista_request_ref")):
        raise ValueError("paired hybrid selection lineage is conflicting")
    submitted_ref = request.get("submitted_request_ref")
    candidate_id = row.get("candidate_id")
    matches = []
    for proposal in vista_proposals:
        if not isinstance(proposal, Mapping):
            raise ValueError("VISTA proposal is invalid")
        proposal_request_ref = proposal.get("submitted_request_ref")
        if proposal_request_ref is None and proposal.get("contract_version") == "hybrid_vista_refinement_proposal_v1":
            proposal_bbox = proposal.get("candidate_bbox_ref")
            proposal_request_ref = submitted_ref if isinstance(proposal_bbox, Mapping) and proposal_bbox.get("xyxy") == bbox_artifact.get("xyxy") else None
        same_request = proposal_request_ref == submitted_ref
        same_candidate = proposal.get("candidate_id") == candidate_id
        if same_request != same_candidate:
            raise ValueError("VISTA result refers to a different candidate or request")
        if same_request:
            matches.append(proposal)
    if len(matches) > 1:
        raise ValueError("multiple VISTA results for selected request")
    outcome: dict[str, object] = {"request_ref": request_ref, "target_binding_ref": binding_ref}
    if not matches:
        outcome["status"] = "missing"
    else:
        proposal = matches[0]
        status = proposal.get("status")
        if status == "PROPOSED":
            point = proposal.get("canonical_point")
            if not isinstance(point, Mapping) or point.get("coordinate_space") != "capture_pixel_xyxy":
                raise ValueError("VISTA proposed point is not canonical")
            xy = point.get("xy")
            bbox = _xyxy(bbox_artifact.get("xyxy"), "selected bbox")
            if not isinstance(xy, list) or len(xy) != 2 or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in xy) or not (bbox[0] <= xy[0] <= bbox[2] and bbox[1] <= xy[1] <= bbox[3]):
                raise ValueError("VISTA proposed point is outside the selected bbox")
            outcome["status"] = "validated"
            outcome["canonical_capture_pixel_point"] = deepcopy(xy)
        elif status == "VISTA_FAILED":
            raw_provider = proposal.get("raw_provider_result")
            failure_category = proposal.get("failure_category")
            if failure_category is None and isinstance(raw_provider, Mapping):
                failure_category = raw_provider.get("failure_category")
            outcome["status"] = "timeout" if failure_category == "request_timeout" else "failed"
        elif status == "VISTA_OUT_OF_BOUNDS":
            outcome["status"] = "out_of_bounds"
        elif status == "TRANSFORM_INVALID":
            outcome["status"] = "failed"
        else:
            raise ValueError("unknown VISTA proposal state")
    row["vista_result"] = outcome
    return result


@dataclass(frozen=True)
class PredictionRunV3Materialization:
    automatic_prediction: dict[str, object]
    prediction_run: dict[str, object]
    prediction_run_envelope: dict[str, object]


def _decode_canonical_envelope(value: object, *, name: str) -> tuple[dict[str, object], bytes]:
    if not isinstance(value, Mapping) or set(value) != {"ref", "canonical_bytes_b64"}:
        raise ValueError(f"{name} envelope is invalid")
    encoded = value.get("canonical_bytes_b64")
    if not isinstance(encoded, str):
        raise ValueError(f"{name} envelope bytes are invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} envelope bytes are invalid") from exc
    if not isinstance(decoded, Mapping) or canonical_bytes(decoded) != raw:
        raise ValueError(f"{name} envelope bytes are not canonical")
    return deepcopy(dict(decoded)), raw


def _pre_vista_evidence_ref(value: Mapping[str, object]) -> dict[str, str]:
    raw = canonical_bytes(value)
    return {
        "id": "pre-vista-evidence/"
        + hashlib.sha256(
            b"benchmark_v2_actual_pre_vista_evidence_v1\0" + raw
        ).hexdigest(),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _seal_automatic_prediction_v3(
    *,
    benchmark_release_id: str,
    partition: str,
    source_parent_ref: Mapping[str, object],
    case_arm_multiset_sha256: str,
    provider_group_dependencies: list[Mapping[str, object]],
    rows: list[Mapping[str, object]],
) -> dict[str, object]:
    identity_source = {
        "benchmark_release_id": benchmark_release_id,
        "partition": partition,
        "source_parent_ref": deepcopy(dict(source_parent_ref)),
        "case_arm_multiset_sha256": case_arm_multiset_sha256,
        "provider_group_dependencies": [deepcopy(dict(item)) for item in provider_group_dependencies],
        "rows": [deepcopy(dict(item)) for item in rows],
        "safety": deepcopy(SAFETY),
    }
    prediction_id = "prediction/" + hashlib.sha256(
        b"benchmark-v2-automatic-prediction-v3\0"
        + canonical_bytes(identity_source)
    ).hexdigest()
    return seal_pathless_projection(
        contract_version="automatic_prediction_v3",
        semantic_payload={"prediction_id": prediction_id, **identity_source},
    )


def _parse_actual_body_bytes(actual_body_bytes: bytes) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import content_sha256

    if not isinstance(actual_body_bytes, bytes):
        raise ValueError("actual body bytes are required")
    try:
        decoded = json.loads(actual_body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("actual body is not UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping) or actual_body_bytes != canonical_bytes(decoded) + b"\n":
        raise ValueError("actual body bytes are not canonical")
    body = deepcopy(dict(decoded))
    expected_fields = {
        "contract_version",
        "attempt_ref",
        "partition",
        "screen_group_results",
        "body_status",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if (
        set(body) != expected_fields
        or body.get("contract_version") != "benchmark_v2_runner_actual_body_v1"
        or body.get("partition") != "regression"
        or body.get("body_status") != "complete"
        or body.get("artifact_is_authorization") is not False
        or body.get("execute_binding_enabled") is not False
        or not isinstance(body.get("screen_group_results"), list)
        or len(body["screen_group_results"]) != 12
        or body.get("content_sha256") != content_sha256(body)
    ):
        raise ValueError("actual body contract is invalid")
    return body


def _parse_holdout_actual_body_bytes(actual_body_bytes: bytes) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import content_sha256

    if not isinstance(actual_body_bytes, bytes):
        raise ValueError("holdout actual body bytes are required")
    try:
        decoded = json.loads(actual_body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("holdout actual body is not UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping) or actual_body_bytes != canonical_bytes(decoded):
        raise ValueError("holdout actual body bytes are not canonical")
    body = deepcopy(dict(decoded))
    expected_fields = {
        "contract_version",
        "attempt_ref",
        "partition",
        "screen_group_results",
        "body_status",
        "safety",
        "content_sha256",
    }
    if (
        set(body) != expected_fields
        or body.get("contract_version") != "benchmark_v2_holdout_runner_actual_body_v1"
        or body.get("partition") != "holdout"
        or body.get("body_status") != "complete"
        or body.get("safety") != SAFETY
        or not isinstance(body.get("screen_group_results"), list)
        or len(body["screen_group_results"]) != 12
        or body.get("content_sha256") != content_sha256(body)
    ):
        raise ValueError("holdout actual body contract is invalid")
    return body


def _parse_provider_inputs(
    *, provider_manifest_bytes: bytes, provider_corpus_bytes: bytes
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    from app.learn.hybrid.benchmark_v2_contracts import (
        PARENT_REF,
        canonical_json_bytes,
    )
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        validate_preloaded_provider_corpus,
        validate_provider_manifest,
    )

    if not isinstance(provider_manifest_bytes, bytes) or not isinstance(provider_corpus_bytes, bytes):
        raise ValueError("provider manifest and corpus bytes are required")
    try:
        manifest_value = json.loads(provider_manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("provider manifest is not UTF-8 JSON") from exc
    if (
        not isinstance(manifest_value, Mapping)
        or provider_manifest_bytes != canonical_json_bytes(manifest_value, pretty=True)
    ):
        raise ValueError("provider manifest bytes are not canonical")
    manifest = validate_provider_manifest(manifest_value)
    corpus_file_sha = hashlib.sha256(provider_corpus_bytes).hexdigest()
    corpus = validate_preloaded_provider_corpus(
        raw=provider_corpus_bytes, expected_sha256=corpus_file_sha
    )
    corpus_ref = {
        "contract_version": "portfolio_hybrid_v1_1_provider_corpus_v2",
        "relative_path": "provider-corpus.v2.json",
        "file_sha256": corpus_file_sha,
        "content_sha256": str(corpus["content_sha256"]),
        "source_parent_ref": deepcopy(PARENT_REF),
    }
    if manifest.get("provider_corpus_ref") != corpus_ref:
        raise ValueError("provider manifest/corpus lineage differs")
    manifest_ref = {
        "contract_version": "portfolio_hybrid_v1_1_provider_manifest_v2_1",
        "relative_path": "benchmark-v2-provider-manifest.json",
        "file_sha256": hashlib.sha256(provider_manifest_bytes).hexdigest(),
    }
    return manifest, corpus, manifest_ref, corpus_ref


def _provider_case_index(
    corpus: Mapping[str, object], *, partition: str = "regression"
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, str]], str]:
    from app.learn.hybrid.benchmark_v2_contracts import ARM_ORDER
    from app.learn.recognition.uei.canonical import content_sha256

    cases = corpus.get("cases")
    if not isinstance(cases, list):
        raise ValueError("provider corpus cases are unavailable")
    if partition not in {"regression", "holdout"}:
        raise ValueError("provider corpus partition is invalid")
    selected = [
        deepcopy(dict(item))
        for item in cases
        if isinstance(item, Mapping) and item.get("partition") == partition
    ]
    if len(selected) != 60:
        raise ValueError(f"provider corpus {partition} partition must contain 60 cases")
    by_id: dict[str, dict[str, object]] = {}
    context: dict[str, dict[str, str]] = {}
    multiset: list[dict[str, str]] = []
    groups: dict[str, int] = {}
    for case in selected:
        case_id = str(case.get("case_id") or "")
        group_id = str(case.get("screen_group") or "")
        if not case_id or not group_id or case_id in by_id:
            raise ValueError("provider corpus regression case identity is invalid")
        case_sha = content_sha256(case)
        by_id[case_id] = case
        context[case_id] = {
            "provider_group_id": group_id,
            "case_content_sha256": case_sha,
        }
        groups[group_id] = groups.get(group_id, 0) + 1
        for arm_id in ARM_ORDER:
            multiset.append(
                {
                    "case_id": case_id,
                    "case_content_sha256": case_sha,
                    "arm_id": arm_id,
                }
            )
    if len(groups) != 12 or set(groups.values()) != {5}:
        raise ValueError("provider corpus regression group multiset is invalid")
    arm_rank = {arm: index for index, arm in enumerate(ARM_ORDER)}
    multiset.sort(key=lambda item: (item["case_id"], arm_rank[item["arm_id"]]))
    return by_id, context, hashlib.sha256(canonical_bytes(multiset)).hexdigest()


def _screen_group_material(
    *,
    screen: Mapping[str, object],
    raw_attempt_ref: Mapping[str, object],
    provider_cases: Mapping[str, Mapping[str, object]],
    case_context: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    from app.learn.hybrid.benchmark_v2_lifecycle import _s13_screen_group_parent

    _, _, actual_group_ref, provider_group_ref = _s13_screen_group_parent(
        screen, attempt_ref=raw_attempt_ref
    )
    shared = screen.get("shared_parent_refs")
    evidence = screen.get("pre_vista_evidence")
    rows = screen.get("rows")
    if not isinstance(shared, Mapping) or not isinstance(evidence, Mapping) or not isinstance(rows, list):
        raise ValueError("actual screen group material is incomplete")
    evidence_ref = _pre_vista_evidence_ref(evidence)
    decoded_raw: dict[str, dict[str, object]] = {}
    raw_envelopes: list[dict[str, object]] = []
    for field, key in (
        ("omni_inventory_envelope", "omni_inventory"),
        ("qwen_bindings_envelope", "qwen_bindings"),
        ("fusion_result_envelope", "fusion_result"),
    ):
        decoded, _ = _decode_canonical_envelope(evidence[field], name=field)
        decoded_raw[key] = decoded
        raw_envelopes.append(deepcopy(dict(evidence[field])))
    submitted: list[dict[str, object]] = []
    submitted_envelopes = evidence.get("submitted_vista_request_envelopes")
    if not isinstance(submitted_envelopes, list):
        raise ValueError("submitted VISTA request envelopes are unavailable")
    for envelope in submitted_envelopes:
        decoded, _ = _decode_canonical_envelope(envelope, name="submitted VISTA request")
        submitted.append(decoded)
        raw_envelopes.append(deepcopy(dict(envelope)))
    request_ids = [str(item.get("candidate_id") or "") for item in submitted]
    if request_ids != sorted(request_ids) or any(not item for item in request_ids):
        raise ValueError("submitted VISTA request order differs")
    group_id = str(provider_group_ref["id"])
    group_case_ids = sorted(
        case_id for case_id, item in case_context.items() if item["provider_group_id"] == group_id
    )
    qwen_by_case: dict[str, Mapping[str, object]] = {}
    vista_proposals: list[Mapping[str, object]] | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("actual screen group row is invalid")
        case_ref = row.get("case_ref")
        observation = row.get("observation")
        if not isinstance(case_ref, Mapping) or not isinstance(observation, Mapping):
            raise ValueError("actual screen group row evidence is invalid")
        case_id = str(case_ref.get("case_id") or "")
        expected_case = case_context.get(case_id)
        if (
            expected_case is None
            or expected_case["provider_group_id"] != group_id
            or case_ref.get("case_content_sha256") != expected_case["case_content_sha256"]
        ):
            raise ValueError("actual screen group case/corpus lineage differs")
        if row.get("arm_id") == "qwen_only":
            response = observation.get("response")
            if not isinstance(response, Mapping) or case_id in qwen_by_case:
                raise ValueError("actual screen group Qwen response is invalid")
            qwen_by_case[case_id] = response
        elif row.get("arm_id") == "omni_to_qwen_vista":
            proposals = _actual_vista_proposals(
                observation=observation,
                submitted_vista_requests=submitted,
            )
            if vista_proposals is None:
                vista_proposals = proposals
            elif canonical_bytes(vista_proposals) != canonical_bytes(proposals):
                raise ValueError("actual screen group VISTA proposals differ across rows")
    if sorted(qwen_by_case) != group_case_ids:
        raise ValueError("actual screen group case coverage differs")
    selected_rows: list[dict[str, object]] = []
    sealed_artifacts: list[dict[str, object]] = []
    for case_id in group_case_ids:
        selection = select_pre_vista_prediction_rows(
            provider_case=provider_cases[case_id],
            incumbent_response=qwen_by_case[case_id],
            omni_inventory=decoded_raw["omni_inventory"],
            qwen_bindings=decoded_raw["qwen_bindings"],
            fusion_result=decoded_raw["fusion_result"],
            submitted_vista_requests=submitted,
            actual_screen_group_ref=actual_group_ref,
            capture_ref=shared["capture_ref"],
        )
        attached = attach_vista_outcomes(selection, list(vista_proposals or []))
        selected_rows.extend(deepcopy(attached["rows"]))
        sealed_artifacts.extend(deepcopy(attached["sealed_artifacts"]))
    dependency = {
        "actual_screen_group_ref": actual_group_ref,
        "provider_group_ref": provider_group_ref,
        "capture_ref": deepcopy(dict(shared["capture_ref"])),
        "pre_vista_evidence_ref": evidence_ref,
        "omni_inventory_ref": deepcopy(dict(evidence["omni_inventory_envelope"]["ref"])),
        "qwen_bindings_ref": deepcopy(dict(evidence["qwen_bindings_envelope"]["ref"])),
        "fusion_result_ref": deepcopy(dict(evidence["fusion_result_envelope"]["ref"])),
        "submitted_vista_request_refs": [deepcopy(dict(item["ref"])) for item in submitted_envelopes],
    }
    return dependency, selected_rows, sealed_artifacts, {"raw_envelopes": raw_envelopes}


def _actual_vista_proposals(
    *,
    observation: Mapping[str, object],
    submitted_vista_requests: list[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    review = observation.get("review_projection")
    if not isinstance(review, Mapping):
        raise ValueError("actual screen group VISTA review projection is invalid")
    proposals = review.get("proposals")
    if submitted_vista_requests:
        if not isinstance(proposals, list):
            raise ValueError("actual screen group VISTA proposals are invalid")
        return deepcopy(proposals)
    expected = {
        "contract_version": "benchmark_v2_quality_safe_stop_review_projection_v1",
        "outcome": "quality_safe_stop",
        "reason": "no_vista_eligible_bound_candidates",
        "proposals": [],
        "automatic_acceptance": False,
        "execute_binding_enabled": False,
        "no_live_click_authorization": True,
    }
    if dict(review) != expected:
        raise ValueError("actual screen group zero-VISTA quality safe-stop is invalid")
    return []


def _prediction_external_refs(
    *,
    prediction_run: Mapping[str, object],
    automatic: Mapping[str, object],
    artifacts: list[Mapping[str, object]],
    runner_and_ledger_envelopes: list[Mapping[str, object]],
) -> dict[str, object]:
    collected: dict[str, list[object]] = {}

    def add(role: str, value: object) -> None:
        if value is not None:
            collected.setdefault(role, []).append(deepcopy(value))

    outer_version = "benchmark_v2_prediction_run_v3"
    for field in (
        "corpus_parent_ref",
        "provider_manifest_ref",
        "provider_corpus_ref",
        "attempt_ref",
        "selected_lifecycle_ref",
    ):
        add(f"{outer_version}.{field}", prediction_run[field])
    if prediction_run.get("partition") != "holdout":
        add(
            f"{outer_version}.raw_ledger_prefix_verification_ref",
            prediction_run["raw_ledger_prefix_verification_ref"],
        )
    automatic_version = "automatic_prediction_v3"
    add(f"{automatic_version}.source_parent_ref", automatic["source_parent_ref"])
    for dependency in automatic["provider_group_dependencies"]:
        assert isinstance(dependency, Mapping)
        for field in (
            "actual_screen_group_ref",
            "provider_group_ref",
            "capture_ref",
            "pre_vista_evidence_ref",
        ):
            add(f"{automatic_version}.provider_group_dependencies.{field}", dependency[field])
    for artifact in artifacts:
        version = str(artifact["contract_version"])
        if version == "benchmark_v2_nested_provider_evidence_ref_v1":
            add(f"{version}.case_ref", artifact["case_ref"])
            add(f"{version}.actual_screen_group_ref", artifact["actual_screen_group_ref"])
        elif version == "sealed_prediction_source_parent_v1":
            add(f"{version}.case_ref", artifact["case_ref"])
            add(f"{version}.actual_screen_group_ref", artifact["actual_screen_group_ref"])
            add(f"{version}.capture_ref", artifact["capture_ref"])
        elif version in {"sealed_prediction_bbox_v1", "sealed_target_binding_v4", "sealed_vista_request_v4"}:
            add(f"{version}.capture_ref", artifact["capture_ref"])
    for envelope in runner_and_ledger_envelopes:
        item, _ = _decode_canonical_envelope(envelope, name="prediction lifecycle child")
        version = str(item["contract_version"])
        if version == "benchmark_v2_runner_event_verified_projection_v1":
            add(f"{version}.attempt_ref", item["attempt_ref"])
            refs = item["load_bearing_refs"]
            assert isinstance(refs, Mapping)
            for field in (
                "attempt_ref",
                "body_file_ref",
                "cleanup_receipt_ref",
                "cleanup_projection_ref",
                "result_file_ref",
                "attempt_ledger_pre_result_ref",
            ):
                if field in refs:
                    add(f"{version}.load_bearing_refs.{field}", refs[field])
        elif version == "benchmark_v2_projected_attempt_ledger_v1":
            add(f"{version}.raw_ledger_prefix_verification_ref", item["raw_ledger_prefix_verification_ref"])
            add(f"{version}.selected_attempt_ref", item["selected_attempt_ref"])
            add(f"{version}.selected_lifecycle_ref", item["selected_lifecycle_ref"])
            for entry in item["entries"]:
                assert isinstance(entry, Mapping)
                add(f"{version}.entries.attempt_ref", entry["attempt_ref"])
                add(f"{version}.entries.lifecycle_ref", entry["lifecycle_ref"])
        elif version == "benchmark_v2_holdout_runner_event_verified_projection_v1":
            refs = item["load_bearing_refs"]
            assert isinstance(refs, Mapping)
            for field in (
                "attempt_ref",
                "body_file_ref",
                "cleanup_receipt_ref",
                "cleanup_projection_ref",
                "result_file_ref",
            ):
                if field in refs:
                    add(f"{version}.load_bearing_refs.{field}", refs[field])
        elif version == "benchmark_v2_holdout_projected_attempt_ledger_v1":
            add(f"{version}.selected_lifecycle_ref", item["selected_lifecycle_ref"])
            for entry in item["entries"]:
                assert isinstance(entry, Mapping)
                add(f"{version}.entries.lifecycle_ref", entry["lifecycle_ref"])
        elif version == "benchmark_v2_holdout_actual_result_verified_projection_v1":
            add(f"{version}.body_projection_ref", item["body_projection_ref"])
            add(f"{version}.cleanup_projection_ref", item["cleanup_projection_ref"])
    result: dict[str, object] = {}
    for role, values in collected.items():
        unique: list[object] = []
        seen: set[bytes] = set()
        for value in values:
            key = canonical_bytes(value)
            if key not in seen:
                seen.add(key)
                unique.append(value)
        result[role] = unique[0] if len(unique) == 1 else unique
    return result


def materialize_prediction_run_v3(
    *,
    actual_body_bytes: bytes,
    provider_manifest_bytes: bytes,
    provider_corpus_bytes: bytes,
    actual_body_verified_projection: Mapping[str, object],
    lifecycle_bundle_v3: Mapping[str, object],
) -> PredictionRunV3Materialization:
    """从已验证原始字节离线生成 production Prediction-run-v3。"""

    from app.learn.hybrid.benchmark_v2_contracts import BENCHMARK_RELEASE_ID, PARENT_REF
    from app.learn.hybrid.benchmark_v2_lifecycle import _s13_public_any_attempt_ref

    try:
        preview = json.loads(actual_body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("actual body is not UTF-8 JSON") from error
    holdout = (
        isinstance(preview, Mapping)
        and preview.get("contract_version")
        == "benchmark_v2_holdout_runner_actual_body_v1"
    )
    body = (
        _parse_holdout_actual_body_bytes(actual_body_bytes)
        if holdout
        else _parse_actual_body_bytes(actual_body_bytes)
    )
    partition = "holdout" if holdout else "regression"
    _, corpus, manifest_ref, corpus_ref = _parse_provider_inputs(
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    provider_cases, case_context, corpus_digest = _provider_case_index(
        corpus, partition=partition
    )
    if not isinstance(actual_body_verified_projection, Mapping):
        raise ValueError("actual body verified projection is required")
    body_projection_ref = pathless_artifact_ref(actual_body_verified_projection)
    raw_attempt_ref = body.get("attempt_ref")
    if not isinstance(raw_attempt_ref, Mapping):
        raise ValueError("actual body attempt ref is invalid")
    public_attempt_ref = _s13_public_any_attempt_ref(raw_attempt_ref)
    if (
        actual_body_verified_projection.get("contract_version")
        != "benchmark_v2_actual_body_verified_projection_v1"
        or actual_body_verified_projection.get("body_contract_version")
        != body.get("contract_version")
        or actual_body_verified_projection.get("attempt_ref") != public_attempt_ref
        or actual_body_verified_projection.get("raw_file_sha256")
        != hashlib.sha256(actual_body_bytes).hexdigest()
        or actual_body_verified_projection.get("body_content_sha256")
        != body.get("content_sha256")
        or actual_body_verified_projection.get("case_arm_multiset_sha256") != corpus_digest
    ):
        raise ValueError("actual body verified projection lineage differs")

    pathless_artifact_ref(lifecycle_bundle_v3)
    if (
        lifecycle_bundle_v3.get("contract_version") != "benchmark_v2_lifecycle_bundle_v3"
        or lifecycle_bundle_v3.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
        or lifecycle_bundle_v3.get("partition") != partition
        or lifecycle_bundle_v3.get("attempt_ref") != public_attempt_ref
    ):
        raise ValueError("lifecycle bundle lineage differs")
    lifecycle_envelopes = lifecycle_bundle_v3.get("sealed_artifact_envelopes")
    if not isinstance(lifecycle_envelopes, list):
        raise ValueError("lifecycle bundle closure is unavailable")
    runner_and_ledger_envelopes: list[dict[str, object]] = []
    runner_events: list[dict[str, object]] = []
    ledger: dict[str, object] | None = None
    event_contract = (
        "benchmark_v2_holdout_runner_event_verified_projection_v1"
        if holdout
        else "benchmark_v2_runner_event_verified_projection_v1"
    )
    ledger_contract = (
        "benchmark_v2_holdout_projected_attempt_ledger_v1"
        if holdout
        else "benchmark_v2_projected_attempt_ledger_v1"
    )
    holdout_shared_contracts = {
        "benchmark_v2_holdout_attempt_ledger_pre_result_verified_projection_v1",
        "benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1",
        "benchmark_v2_holdout_actual_result_verified_projection_v1",
    }
    for envelope in lifecycle_envelopes:
        decoded, _ = _decode_canonical_envelope(envelope, name="lifecycle child")
        version = decoded.get("contract_version")
        if version in {event_contract, ledger_contract, *holdout_shared_contracts}:
            pathless_artifact_ref(decoded)
            runner_and_ledger_envelopes.append(deepcopy(dict(envelope)))
            if version == event_contract:
                runner_events.append(decoded)
            elif version == ledger_contract:
                if ledger is not None:
                    raise ValueError("lifecycle bundle projected ledger is duplicated")
                ledger = decoded
    if ledger is None:
        raise ValueError("lifecycle bundle projected ledger is missing")
    ledger_ref = pathless_artifact_ref(ledger)
    if (
        ledger_ref != lifecycle_bundle_v3.get("projected_attempt_ledger_ref")
        or ledger.get("selected_attempt_ref") != public_attempt_ref
        or ledger.get("selected_lifecycle_ref") != lifecycle_bundle_v3.get("selected_lifecycle_ref")
        or ledger.get("raw_ledger_prefix_verification_ref")
        != lifecycle_bundle_v3.get("raw_ledger_prefix_verification_ref")
    ):
        raise ValueError("lifecycle bundle ledger lineage differs")
    selected_body_events = [
        event
        for event in runner_events
        if event.get("event_kind") == "body_complete"
        and event.get("attempt_ref") == public_attempt_ref
    ]
    if len(selected_body_events) != 1:
        raise ValueError("selected lifecycle body_complete event is not unique")
    expected_body_file_ref = {
        "file_sha256": hashlib.sha256(actual_body_bytes).hexdigest(),
        "content_sha256": str(body["content_sha256"]),
    }
    load_bearing_refs = selected_body_events[0].get("load_bearing_refs")
    if (
        not isinstance(load_bearing_refs, Mapping)
        or load_bearing_refs.get("body_file_ref") != expected_body_file_ref
    ):
        raise ValueError("selected lifecycle body_file_ref differs from actual body bytes")

    dependencies: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    artifacts_by_ref: dict[bytes, dict[str, object]] = {}
    raw_envelopes: list[dict[str, object]] = []
    screens = body["screen_group_results"]
    assert isinstance(screens, list)
    for raw_screen in screens:
        if not isinstance(raw_screen, Mapping):
            raise ValueError("actual body screen group is invalid")
        dependency, group_rows, group_artifacts, material = _screen_group_material(
            screen=raw_screen,
            raw_attempt_ref=raw_attempt_ref,
            provider_cases=provider_cases,
            case_context=case_context,
        )
        dependencies.append(dependency)
        rows.extend(group_rows)
        for artifact in group_artifacts:
            ref = pathless_artifact_ref(artifact)
            key = canonical_bytes(ref)
            prior = artifacts_by_ref.get(key)
            if prior is not None and prior != artifact:
                raise ValueError("prediction sealed artifact identity conflicts")
            artifacts_by_ref[key] = artifact
        raw_envelopes.extend(material["raw_envelopes"])
    dependencies.sort(key=lambda item: str(item["provider_group_ref"]["id"]))
    arm_rank = {arm: index for index, arm in enumerate(ARMS)}
    rows.sort(key=lambda item: (str(item["case_id"]), arm_rank[str(item["arm_id"])]))
    pre_refs = [deepcopy(item["pre_vista_evidence_ref"]) for item in dependencies]
    if (
        actual_body_verified_projection.get("pre_vista_evidence_refs") != pre_refs
        or len({str(item["provider_group_ref"]["id"]) for item in dependencies}) != 12
        or len(rows) != 240
    ):
        raise ValueError("actual body dependency/row multiset differs")
    automatic = _seal_automatic_prediction_v3(
        benchmark_release_id=BENCHMARK_RELEASE_ID,
        partition=partition,
        source_parent_ref=body_projection_ref,
        case_arm_multiset_sha256=corpus_digest,
        provider_group_dependencies=dependencies,
        rows=rows,
    )

    child_envelopes = [
        *raw_envelopes,
        *[seal_pathless_envelope(item) for item in artifacts_by_ref.values()],
        seal_pathless_envelope(automatic),
        *runner_and_ledger_envelopes,
    ]
    ordered_children = order_pathless_envelopes(
        registry_name="prediction_run_v3", envelopes=child_envelopes, context={}
    )
    prediction_run = seal_pathless_projection(
        contract_version="benchmark_v2_prediction_run_v3",
        semantic_payload={
            "benchmark_release_id": BENCHMARK_RELEASE_ID,
            "partition": partition,
            "corpus_parent_ref": deepcopy(PARENT_REF),
            "provider_manifest_ref": manifest_ref,
            "provider_corpus_ref": corpus_ref,
            "attempt_ref": public_attempt_ref,
            "projected_attempt_ledger_ref": ledger_ref,
            "raw_ledger_prefix_verification_ref": deepcopy(
                lifecycle_bundle_v3["raw_ledger_prefix_verification_ref"]
            ),
            "automatic_prediction_ref": pathless_artifact_ref(automatic),
            "selected_lifecycle_ref": deepcopy(lifecycle_bundle_v3["selected_lifecycle_ref"]),
            "sealed_artifact_envelopes": ordered_children,
            "safety": deepcopy(SAFETY),
        },
    )
    prediction_run_envelope = seal_pathless_envelope(prediction_run)
    provider_group_context = {
        str(item["provider_group_ref"]["id"]): deepcopy(item) for item in dependencies
    }
    external_refs = _prediction_external_refs(
        prediction_run=prediction_run,
        automatic=automatic,
        artifacts=list(artifacts_by_ref.values()),
        runner_and_ledger_envelopes=runner_and_ledger_envelopes,
    )
    context = {
        "provider_groups": provider_group_context,
        "cases": deepcopy(case_context),
        "actual_body_projection_ref": body_projection_ref,
        "attempt_ref": public_attempt_ref,
        "raw_ledger_prefix_verification_ref": deepcopy(
            lifecycle_bundle_v3["raw_ledger_prefix_verification_ref"]
        ),
        "projected_attempt_ledger_ref": ledger_ref,
        "selected_lifecycle_ref": deepcopy(lifecycle_bundle_v3["selected_lifecycle_ref"]),
    }
    validate_pathless_recursive(
        registry_name="prediction_run_v3",
        roots=[pathless_artifact_ref(prediction_run)],
        envelopes=[prediction_run_envelope, *ordered_children],
        external_refs=external_refs,
        context=context,
    )
    return PredictionRunV3Materialization(
        automatic_prediction=automatic,
        prediction_run=prediction_run,
        prediction_run_envelope=prediction_run_envelope,
    )


def project_benchmark_v2_actual_body(
    *,
    actual_body_bytes: bytes,
    provider_manifest_bytes: bytes,
    provider_corpus_bytes: bytes,
) -> dict[str, object]:
    """从 canonical production body 与 Task 10 provider bytes 派生无路径投影。"""

    from app.learn.hybrid.benchmark_v2_lifecycle import _s13_public_attempt_ref

    body = _parse_actual_body_bytes(actual_body_bytes)
    _, corpus, _, _ = _parse_provider_inputs(
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    provider_cases, case_context, corpus_digest = _provider_case_index(corpus)
    raw_attempt_ref = body.get("attempt_ref")
    if not isinstance(raw_attempt_ref, Mapping):
        raise ValueError("actual body attempt ref is invalid")
    dependencies: list[dict[str, object]] = []
    row_count = 0
    screens = body.get("screen_group_results")
    assert isinstance(screens, list)
    for screen in screens:
        if not isinstance(screen, Mapping):
            raise ValueError("actual body screen group is invalid")
        dependency, rows, _, _ = _screen_group_material(
            screen=screen,
            raw_attempt_ref=raw_attempt_ref,
            provider_cases=provider_cases,
            case_context=case_context,
        )
        dependencies.append(dependency)
        row_count += len(rows)
    dependencies.sort(key=lambda item: str(item["provider_group_ref"]["id"]))
    if (
        len(dependencies) != 12
        or len({str(item["provider_group_ref"]["id"]) for item in dependencies}) != 12
        or row_count != 240
    ):
        raise ValueError("actual body dependency/row multiset differs")
    return seal_pathless_projection(
        contract_version="benchmark_v2_actual_body_verified_projection_v1",
        semantic_payload={
            "attempt_ref": _s13_public_attempt_ref(raw_attempt_ref),
            "body_contract_version": "benchmark_v2_runner_actual_body_v1",
            "raw_file_sha256": hashlib.sha256(actual_body_bytes).hexdigest(),
            "body_content_sha256": str(body["content_sha256"]),
            "screen_group_count": 12,
            "case_arm_multiset_sha256": corpus_digest,
            "pre_vista_evidence_refs": [
                deepcopy(item["pre_vista_evidence_ref"]) for item in dependencies
            ],
            "verified": True,
            "safety": deepcopy(SAFETY),
        },
    )


def project_benchmark_v2_holdout_actual_body(
    *,
    actual_body_bytes: bytes,
    provider_manifest_bytes: bytes,
    provider_corpus_bytes: bytes,
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        _s13_public_holdout_attempt_ref,
    )

    body = _parse_holdout_actual_body_bytes(actual_body_bytes)
    _, corpus, _, _ = _parse_provider_inputs(
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    provider_cases, case_context, corpus_digest = _provider_case_index(
        corpus, partition="holdout"
    )
    raw_attempt_ref = body.get("attempt_ref")
    if not isinstance(raw_attempt_ref, Mapping):
        raise ValueError("holdout actual body attempt ref is invalid")
    dependencies: list[dict[str, object]] = []
    row_count = 0
    screens = body["screen_group_results"]
    assert isinstance(screens, list)
    for screen in screens:
        if not isinstance(screen, Mapping):
            raise ValueError("holdout actual body screen group is invalid")
        dependency, rows, _, _ = _screen_group_material(
            screen=screen,
            raw_attempt_ref=raw_attempt_ref,
            provider_cases=provider_cases,
            case_context=case_context,
        )
        dependencies.append(dependency)
        row_count += len(rows)
    dependencies.sort(key=lambda item: str(item["provider_group_ref"]["id"]))
    if (
        len(dependencies) != 12
        or len({str(item["provider_group_ref"]["id"]) for item in dependencies}) != 12
        or row_count != 240
    ):
        raise ValueError("holdout actual body dependency/row multiset differs")
    return seal_pathless_projection(
        contract_version="benchmark_v2_actual_body_verified_projection_v1",
        semantic_payload={
            "attempt_ref": _s13_public_holdout_attempt_ref(raw_attempt_ref),
            "body_contract_version": "benchmark_v2_holdout_runner_actual_body_v1",
            "raw_file_sha256": hashlib.sha256(actual_body_bytes).hexdigest(),
            "body_content_sha256": str(body["content_sha256"]),
            "screen_group_count": 12,
            "case_arm_multiset_sha256": corpus_digest,
            "pre_vista_evidence_refs": [
                deepcopy(item["pre_vista_evidence_ref"]) for item in dependencies
            ],
            "verified": True,
            "safety": deepcopy(SAFETY),
        },
    )


def _parse_actual_result_bytes(
    actual_result_bytes: bytes, *, expected_attempt_dir: Path
) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import content_sha256

    if not isinstance(actual_result_bytes, bytes):
        raise ValueError("actual result bytes are required")
    try:
        decoded = json.loads(actual_result_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("actual result is not UTF-8 JSON") from exc
    if (
        not isinstance(decoded, Mapping)
        or actual_result_bytes != canonical_bytes(decoded) + b"\n"
    ):
        raise ValueError("actual result bytes are not canonical")
    result = deepcopy(dict(decoded))
    expected = {
        "contract_version",
        "attempt_ref",
        "attempt_dir",
        "body_ref",
        "cleanup_receipt_ref",
        "attempt_ledger_pre_result_ref",
        "screen_group_count",
        "status",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    attempt_dir = Path(expected_attempt_dir).resolve()
    if (
        set(result) != expected
        or result.get("contract_version") != "benchmark_v2_runner_actual_result_v2"
        or result.get("attempt_dir") != str(attempt_dir)
        or result.get("screen_group_count") != 12
        or result.get("status") != "terminal"
        or result.get("artifact_is_authorization") is not False
        or result.get("execute_binding_enabled") is not False
        or result.get("content_sha256") != content_sha256(result)
    ):
        raise ValueError("actual result contract is invalid")
    for name, filename in (("body_ref", "body.json"), ("cleanup_receipt_ref", "cleanup.json")):
        ref = result.get(name)
        if (
            not isinstance(ref, Mapping)
            or set(ref) != {"path", "file_sha256", "content_sha256"}
            or ref.get("path") != str((attempt_dir / filename).resolve())
            or any(
                not isinstance(ref.get(field), str)
                or re.fullmatch(r"[0-9a-f]{64}", str(ref[field])) is None
                for field in ("file_sha256", "content_sha256")
            )
        ):
            raise ValueError(f"actual result {name} is invalid")
    return result


def project_benchmark_v2_actual_result(
    *,
    actual_result_bytes: bytes,
    cleanup_receipt_bytes: bytes,
    expected_attempt_dir: Path,
    actual_body_projection: Mapping[str, object],
    cleanup_projection: Mapping[str, object],
    runner_ledger_prefix_projection: Mapping[str, object],
    result_event_projection: Mapping[str, object],
) -> dict[str, object]:
    """投影固定 result.json，并闭合 body/cleanup/prefix/result-event 链。"""

    from app.learn.hybrid.benchmark_v2_lifecycle import (
        _s13_cleanup_receipt,
        _s13_public_attempt_ref,
        derive_benchmark_v2_cleanup_receipt_ref,
    )

    result = _parse_actual_result_bytes(
        actual_result_bytes, expected_attempt_dir=expected_attempt_dir
    )
    raw_attempt_ref = result.get("attempt_ref")
    if not isinstance(raw_attempt_ref, Mapping):
        raise ValueError("actual result attempt ref is invalid")
    if not isinstance(cleanup_receipt_bytes, bytes):
        raise ValueError("cleanup receipt bytes are required")
    try:
        raw_cleanup_receipt = json.loads(cleanup_receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("cleanup receipt is not UTF-8 JSON") from exc
    if (
        not isinstance(raw_cleanup_receipt, Mapping)
        or cleanup_receipt_bytes
        != canonical_bytes(raw_cleanup_receipt) + b"\n"
    ):
        raise ValueError("cleanup receipt bytes are not canonical")
    cleanup_receipt = _s13_cleanup_receipt(
        raw_cleanup_receipt, attempt_ref=raw_attempt_ref
    )
    attempt_ref = _s13_public_attempt_ref(raw_attempt_ref)
    body_ref = pathless_artifact_ref(actual_body_projection)
    cleanup_ref = pathless_artifact_ref(cleanup_projection)
    prefix_ref = pathless_artifact_ref(runner_ledger_prefix_projection)
    event_ref = pathless_artifact_ref(result_event_projection)
    native_pre_result = result.get("attempt_ledger_pre_result_ref")
    if not isinstance(native_pre_result, Mapping):
        raise ValueError("actual result pre-result ref is invalid")
    public_pre_result = deepcopy(dict(native_pre_result))
    public_pre_result["attempt_ref"] = attempt_ref
    event_parents = result_event_projection.get("load_bearing_refs")
    raw_body_ref = result["body_ref"]
    assert isinstance(raw_body_ref, Mapping)
    expected_body_file_ref = {
        "file_sha256": raw_body_ref["file_sha256"],
        "content_sha256": raw_body_ref["content_sha256"],
    }
    expected_result_file_ref = {
        "file_sha256": hashlib.sha256(actual_result_bytes).hexdigest(),
        "content_sha256": result["content_sha256"],
    }
    expected_cleanup_file_ref = {
        "path": str((Path(expected_attempt_dir).resolve() / "cleanup.json").resolve()),
        "file_sha256": hashlib.sha256(cleanup_receipt_bytes).hexdigest(),
        "content_sha256": cleanup_receipt["content_sha256"],
    }
    cleanup_parents = cleanup_projection.get("parent_refs")
    expected_cleanup_parent = derive_benchmark_v2_cleanup_receipt_ref(
        cleanup_receipt=cleanup_receipt
    )
    if (
        result.get("cleanup_receipt_ref") != expected_cleanup_file_ref
        or cleanup_projection.get("attempt_ref") != attempt_ref
        or cleanup_projection.get("lifecycle_kind") != "cleanup"
        or not isinstance(cleanup_parents, Mapping)
        or set(cleanup_parents) != {"cleanup_receipt_ref"}
        or cleanup_parents.get("cleanup_receipt_ref") != expected_cleanup_parent
    ):
        raise ValueError("actual result cleanup receipt lineage differs")
    if (
        native_pre_result.get("attempt_ref") != raw_attempt_ref
        or actual_body_projection.get("attempt_ref") != attempt_ref
        or actual_body_projection.get("raw_file_sha256") != expected_body_file_ref["file_sha256"]
        or actual_body_projection.get("body_content_sha256")
        != expected_body_file_ref["content_sha256"]
        or runner_ledger_prefix_projection.get("attempt_ref") != attempt_ref
        or runner_ledger_prefix_projection.get("body_file_ref") != expected_body_file_ref
        or runner_ledger_prefix_projection.get("result_file_ref") != expected_result_file_ref
        or runner_ledger_prefix_projection.get("attempt_ledger_pre_result_ref")
        != public_pre_result
        or runner_ledger_prefix_projection.get("result_event_projection_ref") != event_ref
        or result_event_projection.get("attempt_ref") != attempt_ref
        or result_event_projection.get("event_kind") != "result"
        or not isinstance(event_parents, Mapping)
        or event_parents.get("result_file_ref") != expected_result_file_ref
        or event_parents.get("attempt_ledger_pre_result_ref") != public_pre_result
    ):
        raise ValueError("actual result verified parent lineage differs")
    return seal_pathless_projection(
        contract_version="benchmark_v2_actual_result_verified_projection_v1",
        semantic_payload={
            "attempt_ref": attempt_ref,
            "result_contract_version": "benchmark_v2_runner_actual_result_v2",
            "raw_file_sha256": hashlib.sha256(actual_result_bytes).hexdigest(),
            "result_content_sha256": str(result["content_sha256"]),
            "body_projection_ref": body_ref,
            "cleanup_projection_ref": cleanup_ref,
            "attempt_ledger_pre_result_ref": public_pre_result,
            "runner_ledger_prefix_projection_ref": prefix_ref,
            "result_event_projection_ref": event_ref,
            "verified": True,
            "safety": deepcopy(SAFETY),
        },
    )


def _accepted_envelope(value: object, *, name: str) -> tuple[dict[str, object], dict[str, object]]:
    decoded, raw = _decode_canonical_envelope(value, name=name)
    raw_classes = {
        "hybrid_omni_inventory_v1": ("omni-inventory", b"benchmark-v2-omni-inventory\0"),
        "hybrid_qwen_bindings_v1": ("qwen-bindings", b"benchmark-v2-qwen-bindings\0"),
        "hybrid_fusion_result_v1": ("fusion-result", b"benchmark-v2-fusion-result\0"),
        "hybrid_vista_refinement_request_v1": (
            "submitted-vista-request",
            b"benchmark-v2-submitted-vista-request\0",
        ),
    }
    raw_spec = raw_classes.get(str(decoded.get("contract_version")))
    if raw_spec is None:
        ref = pathless_artifact_ref(decoded)
    else:
        prefix, domain = raw_spec
        ref = {
            "id": prefix + "/" + hashlib.sha256(domain + raw).hexdigest(),
            "content_sha256": hashlib.sha256(raw).hexdigest(),
        }
    if not isinstance(value, Mapping) or value.get("ref") != ref:
        raise ValueError(f"{name} envelope ref differs")
    return decoded, ref


def _accepted_closure_index(
    outer: Mapping[str, object], *, name: str
) -> tuple[dict[bytes, tuple[dict[str, object], dict[str, object]]], list[dict[str, object]]]:
    envelopes = outer.get("sealed_artifact_envelopes")
    if not isinstance(envelopes, list):
        raise ValueError(f"{name} closure is unavailable")
    by_ref: dict[bytes, tuple[dict[str, object], dict[str, object]]] = {}
    ordered: list[dict[str, object]] = []
    for index, envelope in enumerate(envelopes):
        decoded, ref = _accepted_envelope(envelope, name=f"{name} child {index}")
        key = canonical_bytes(ref)
        if key in by_ref:
            raise ValueError(f"{name} closure ref is duplicated")
        by_ref[key] = (decoded, deepcopy(dict(envelope)))
        ordered.append(decoded)
    return by_ref, ordered


def _accepted_prediction_validation_material(
    *,
    prediction: Mapping[str, object],
    prediction_by_ref: Mapping[
        bytes, tuple[dict[str, object], dict[str, object]]
    ],
    automatic: Mapping[str, object],
    body_projection: Mapping[str, object],
    actual_body_bytes: bytes,
    provider_manifest_bytes: bytes,
    provider_corpus_bytes: bytes,
) -> dict[str, object]:
    """从可信原始 body/provider 字节重建 prediction graph 的权威上下文。"""

    from app.learn.hybrid.benchmark_v2_lifecycle import _s13_public_attempt_ref

    body = _parse_actual_body_bytes(actual_body_bytes)
    _, corpus, manifest_ref, corpus_ref = _parse_provider_inputs(
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    provider_cases, case_context, corpus_digest = _provider_case_index(corpus)
    derived_body_projection = project_benchmark_v2_actual_body(
        actual_body_bytes=actual_body_bytes,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    if dict(body_projection) != derived_body_projection:
        raise ValueError("accepted actual body projection differs from trusted bytes")
    if (
        prediction.get("provider_manifest_ref") != manifest_ref
        or prediction.get("provider_corpus_ref") != corpus_ref
        or automatic.get("case_arm_multiset_sha256") != corpus_digest
    ):
        raise ValueError("accepted trusted provider lineage differs")
    raw_attempt_ref = body.get("attempt_ref")
    if not isinstance(raw_attempt_ref, Mapping):
        raise ValueError("accepted actual body attempt ref is invalid")
    public_attempt_ref = _s13_public_attempt_ref(raw_attempt_ref)
    if prediction.get("attempt_ref") != public_attempt_ref:
        raise ValueError("accepted actual body attempt lineage differs")

    dependencies: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    trusted_raw_envelopes: list[dict[str, object]] = []
    screens = body.get("screen_group_results")
    if not isinstance(screens, list):
        raise ValueError("accepted actual body screen groups are unavailable")
    for screen in screens:
        if not isinstance(screen, Mapping):
            raise ValueError("accepted actual body screen group is invalid")
        dependency, group_rows, _, material = _screen_group_material(
            screen=screen,
            raw_attempt_ref=raw_attempt_ref,
            provider_cases=provider_cases,
            case_context=case_context,
        )
        dependencies.append(dependency)
        rows.extend(group_rows)
        trusted_raw_envelopes.extend(material["raw_envelopes"])
    dependencies.sort(key=lambda item: str(item["provider_group_ref"]["id"]))
    arm_rank = {arm: index for index, arm in enumerate(ARMS)}
    rows.sort(key=lambda item: (str(item["case_id"]), arm_rank[str(item["arm_id"])]))
    expected_automatic = _seal_automatic_prediction_v3(
        benchmark_release_id=str(prediction["benchmark_release_id"]),
        partition=str(prediction["partition"]),
        source_parent_ref=pathless_artifact_ref(derived_body_projection),
        case_arm_multiset_sha256=corpus_digest,
        provider_group_dependencies=dependencies,
        rows=rows,
    )
    if dict(automatic) != expected_automatic:
        raise ValueError("accepted prediction differs from trusted actual body evidence")
    for envelope in trusted_raw_envelopes:
        decoded, ref = _accepted_envelope(
            envelope, name="trusted actual body provider evidence"
        )
        resolved = prediction_by_ref.get(canonical_bytes(ref))
        if resolved is None or resolved[0] != decoded or resolved[1] != envelope:
            raise ValueError("accepted prediction raw provider closure differs from body")
    return {
        "provider_groups": {
            str(item["provider_group_ref"]["id"]): deepcopy(item)
            for item in dependencies
        },
        "cases": deepcopy(case_context),
        "actual_body_projection_ref": pathless_artifact_ref(
            derived_body_projection
        ),
        "attempt_ref": public_attempt_ref,
        "raw_ledger_prefix_verification_ref": deepcopy(
            prediction["raw_ledger_prefix_verification_ref"]
        ),
        "projected_attempt_ledger_ref": deepcopy(
            prediction["projected_attempt_ledger_ref"]
        ),
        "selected_lifecycle_ref": deepcopy(
            prediction["selected_lifecycle_ref"]
        ),
    }


def validate_benchmark_v2_accepted_regression_score_input_v2(
    value: object,
    *,
    actual_body_bytes: bytes,
    actual_result_bytes: bytes,
    cleanup_receipt_bytes: bytes,
    expected_attempt_dir: Path,
    provider_manifest_bytes: bytes,
    provider_corpus_bytes: bytes,
) -> dict[str, object]:
    """验证 scorer 可消费的无路径 accepted regression 根。"""

    from app.learn.hybrid.benchmark_v2_contracts import BENCHMARK_RELEASE_ID, PARENT_REF

    if not isinstance(value, Mapping):
        raise ValueError("accepted regression score input must be an object")
    accepted = deepcopy(dict(value))
    expected = {
        "contract_version", "content_sha256", "benchmark_release_id", "partition",
        "corpus_parent_ref", "provider_manifest_ref", "provider_corpus_ref",
        "selection_policy", "attempt_ref", "attempt_ledger_ref",
        "automatic_prediction_ref", "selected_lifecycle_ref",
        "verified_parent_projections", "prediction_run_envelope",
        "lifecycle_bundle_envelope", "safety",
    }
    if (
        set(accepted) != expected
        or accepted.get("contract_version")
        != "benchmark_v2_accepted_regression_score_input_v2"
        or accepted.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
        or accepted.get("partition") != "regression"
        or accepted.get("selection_policy")
        != "first_complete_lifecycle_verified_attempt"
        or accepted.get("corpus_parent_ref") != PARENT_REF
        or accepted.get("safety") != SAFETY
        or accepted.get("content_sha256")
        != hashlib.sha256(
            canonical_bytes({k: v for k, v in accepted.items() if k != "content_sha256"})
        ).hexdigest()
    ):
        raise ValueError("accepted regression score input contract is invalid")
    prediction, prediction_ref = _accepted_envelope(
        accepted["prediction_run_envelope"], name="accepted prediction run"
    )
    lifecycle, lifecycle_ref = _accepted_envelope(
        accepted["lifecycle_bundle_envelope"], name="accepted lifecycle bundle"
    )
    del lifecycle_ref
    if (
        prediction.get("contract_version") != "benchmark_v2_prediction_run_v3"
        or lifecycle.get("contract_version") != "benchmark_v2_lifecycle_bundle_v3"
    ):
        raise ValueError("accepted regression v3 bundle contract differs")
    prediction_by_ref, prediction_children = _accepted_closure_index(
        prediction, name="accepted prediction run"
    )
    lifecycle_by_ref, lifecycle_children = _accepted_closure_index(
        lifecycle, name="accepted lifecycle bundle"
    )
    shared_versions = {
        "benchmark_v2_runner_event_verified_projection_v1",
        "benchmark_v2_projected_attempt_ledger_v1",
    }
    prediction_shared = {
        key: envelope
        for key, (item, envelope) in prediction_by_ref.items()
        if item.get("contract_version") in shared_versions
    }
    lifecycle_shared = {
        key: envelope
        for key, (item, envelope) in lifecycle_by_ref.items()
        if item.get("contract_version") in shared_versions
    }
    if prediction_shared != lifecycle_shared:
        raise ValueError("accepted prediction/lifecycle shared closure differs")
    parents = accepted.get("verified_parent_projections")
    parent_fields = {
        "runner_ledger_prefix_projection_envelope",
        "attempt_journal_projection_envelope",
        "actual_body_projection_envelope",
        "actual_result_projection_envelope",
    }
    if not isinstance(parents, Mapping) or set(parents) != parent_fields:
        raise ValueError("accepted verified parent projection set differs")
    decoded_parents: dict[str, dict[str, object]] = {}
    parent_refs: dict[str, dict[str, object]] = {}
    expected_contracts = {
        "runner_ledger_prefix_projection_envelope": "benchmark_v2_runner_ledger_prefix_verified_projection_v1",
        "attempt_journal_projection_envelope": "benchmark_v2_attempt_journal_verified_projection_v1",
        "actual_body_projection_envelope": "benchmark_v2_actual_body_verified_projection_v1",
        "actual_result_projection_envelope": "benchmark_v2_actual_result_verified_projection_v1",
    }
    for field, contract in expected_contracts.items():
        decoded, ref = _accepted_envelope(parents[field], name=field)
        if decoded.get("contract_version") != contract:
            raise ValueError("accepted verified parent contract differs")
        decoded_parents[field] = decoded
        parent_refs[field] = ref
    prefix = decoded_parents["runner_ledger_prefix_projection_envelope"]
    journal = decoded_parents["attempt_journal_projection_envelope"]
    body = decoded_parents["actual_body_projection_envelope"]
    result = decoded_parents["actual_result_projection_envelope"]
    validate_pathless_recursive(
        registry_name="verified_parents_v1",
        roots=[
            parent_refs["attempt_journal_projection_envelope"],
            parent_refs["actual_result_projection_envelope"],
        ],
        envelopes=[deepcopy(dict(parents[field])) for field in expected_contracts],
        external_refs={
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.attempt_ledger_pre_result_ref": prefix["attempt_ledger_pre_result_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.attempt_ref": prefix["attempt_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.body_file_ref": prefix["body_file_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.cleanup_event_projection_ref": prefix["cleanup_event_projection_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.result_file_ref": prefix["result_file_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.result_event_projection_ref": prefix["result_event_projection_ref"],
            "benchmark_v2_attempt_journal_verified_projection_v1.attempt_ref": journal["attempt_ref"],
            "benchmark_v2_attempt_journal_verified_projection_v1.terminal_event_ref": journal["terminal_event_ref"],
            "benchmark_v2_attempt_journal_verified_projection_v1.cleanup_projection_ref": journal["cleanup_projection_ref"],
            "benchmark_v2_actual_body_verified_projection_v1.attempt_ref": body["attempt_ref"],
            "benchmark_v2_actual_body_verified_projection_v1.pre_vista_evidence_refs": body["pre_vista_evidence_refs"],
            "benchmark_v2_actual_result_verified_projection_v1.attempt_ref": result["attempt_ref"],
            "benchmark_v2_actual_result_verified_projection_v1.cleanup_projection_ref": result["cleanup_projection_ref"],
            "benchmark_v2_actual_result_verified_projection_v1.attempt_ledger_pre_result_ref": result["attempt_ledger_pre_result_ref"],
            "benchmark_v2_actual_result_verified_projection_v1.result_event_projection_ref": result["result_event_projection_ref"],
        },
        context={},
    )
    attempt_ref = accepted.get("attempt_ref")
    projected_ledger_ref = accepted.get("attempt_ledger_ref")
    automatic_ref = accepted.get("automatic_prediction_ref")
    selected_lifecycle_ref = accepted.get("selected_lifecycle_ref")
    if (
        prediction.get("benchmark_release_id") != accepted["benchmark_release_id"]
        or lifecycle.get("benchmark_release_id") != accepted["benchmark_release_id"]
        or prediction.get("partition") != "regression"
        or lifecycle.get("partition") != "regression"
        or prediction.get("corpus_parent_ref") != accepted["corpus_parent_ref"]
        or prediction.get("provider_manifest_ref") != accepted["provider_manifest_ref"]
        or prediction.get("provider_corpus_ref") != accepted["provider_corpus_ref"]
        or prediction.get("attempt_ref") != attempt_ref
        or lifecycle.get("attempt_ref") != attempt_ref
        or prediction.get("projected_attempt_ledger_ref") != projected_ledger_ref
        or lifecycle.get("projected_attempt_ledger_ref") != projected_ledger_ref
        or prediction.get("automatic_prediction_ref") != automatic_ref
        or prediction.get("selected_lifecycle_ref") != selected_lifecycle_ref
        or lifecycle.get("selected_lifecycle_ref") != selected_lifecycle_ref
        or prediction.get("raw_ledger_prefix_verification_ref")
        != parent_refs["runner_ledger_prefix_projection_envelope"]
        or lifecycle.get("raw_ledger_prefix_verification_ref")
        != parent_refs["runner_ledger_prefix_projection_envelope"]
        or any(item.get("attempt_ref") != attempt_ref for item in (prefix, journal, body, result))
        or result.get("body_projection_ref")
        != parent_refs["actual_body_projection_envelope"]
        or result.get("runner_ledger_prefix_projection_ref")
        != parent_refs["runner_ledger_prefix_projection_envelope"]
        or result.get("result_event_projection_ref") != prefix.get("result_event_projection_ref")
        or result.get("attempt_ledger_pre_result_ref") != prefix.get("attempt_ledger_pre_result_ref")
        or result.get("cleanup_projection_ref") != journal.get("cleanup_projection_ref")
        or prefix.get("body_file_ref")
        != {"file_sha256": body.get("raw_file_sha256"), "content_sha256": body.get("body_content_sha256")}
        or prefix.get("result_file_ref")
        != {"file_sha256": result.get("raw_file_sha256"), "content_sha256": result.get("result_content_sha256")}
    ):
        raise ValueError("accepted regression top-level or verified-parent lineage differs")

    def resolve(index: Mapping[bytes, tuple[dict[str, object], dict[str, object]]], ref: object, contract: str) -> dict[str, object]:
        if not isinstance(ref, Mapping):
            raise ValueError("accepted child ref is invalid")
        found = index.get(canonical_bytes(ref))
        if found is None or found[0].get("contract_version") != contract:
            raise ValueError("accepted child ref is unresolved")
        return found[0]

    automatic = resolve(
        prediction_by_ref, automatic_ref, "automatic_prediction_v3"
    )
    ledger = resolve(
        prediction_by_ref, projected_ledger_ref, "benchmark_v2_projected_attempt_ledger_v1"
    )
    prediction_context = _accepted_prediction_validation_material(
        prediction=prediction,
        prediction_by_ref=prediction_by_ref,
        automatic=automatic,
        body_projection=body,
        actual_body_bytes=actual_body_bytes,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    prediction_child_envelopes = prediction.get("sealed_artifact_envelopes")
    if not isinstance(prediction_child_envelopes, list):
        raise ValueError("accepted prediction closure is unavailable")
    runner_and_ledger_envelopes = [
        deepcopy(dict(envelope))
        for envelope, item in zip(
            prediction_child_envelopes, prediction_children, strict=True
        )
        if item.get("contract_version")
        in {
            "benchmark_v2_runner_event_verified_projection_v1",
            "benchmark_v2_projected_attempt_ledger_v1",
        }
    ]
    prediction_external_refs = _prediction_external_refs(
        prediction_run=prediction,
        automatic=automatic,
        artifacts=prediction_children,
        runner_and_ledger_envelopes=runner_and_ledger_envelopes,
    )
    validate_pathless_recursive(
        registry_name="prediction_run_v3",
        roots=[prediction_ref],
        envelopes=[
            deepcopy(dict(accepted["prediction_run_envelope"])),
            *[deepcopy(dict(item)) for item in prediction_child_envelopes],
        ],
        external_refs=prediction_external_refs,
        context=prediction_context,
    )
    selected_lifecycle = resolve(
        lifecycle_by_ref, selected_lifecycle_ref, "benchmark_v2_lifecycle_verified_projection_v1"
    )
    result_event = resolve(
        lifecycle_by_ref,
        result["result_event_projection_ref"],
        "benchmark_v2_runner_event_verified_projection_v1",
    )
    cleanup_event = resolve(
        lifecycle_by_ref,
        prefix["cleanup_event_projection_ref"],
        "benchmark_v2_runner_event_verified_projection_v1",
    )
    terminal_event = resolve(
        lifecycle_by_ref,
        journal["terminal_event_ref"],
        "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",
    )
    cleanup = resolve(
        lifecycle_by_ref,
        result["cleanup_projection_ref"],
        "benchmark_v2_lifecycle_verified_projection_v1",
    )
    derived_result_projection = project_benchmark_v2_actual_result(
        actual_result_bytes=actual_result_bytes,
        cleanup_receipt_bytes=cleanup_receipt_bytes,
        expected_attempt_dir=expected_attempt_dir,
        actual_body_projection=body,
        cleanup_projection=cleanup,
        runner_ledger_prefix_projection=prefix,
        result_event_projection=result_event,
    )
    if result != derived_result_projection:
        raise ValueError(
            "accepted actual result projection differs from trusted raw bytes"
        )
    event_refs = result_event.get("load_bearing_refs")
    cleanup_event_refs = cleanup_event.get("load_bearing_refs")
    cleanup_parents = cleanup.get("parent_refs")
    lifecycle_parents = selected_lifecycle.get("parent_refs")
    if (
        automatic.get("source_parent_ref") != parent_refs["actual_body_projection_envelope"]
        or ledger.get("selected_attempt_ref") != attempt_ref
        or ledger.get("selected_lifecycle_ref") != selected_lifecycle_ref
        or ledger.get("raw_ledger_prefix_verification_ref")
        != parent_refs["runner_ledger_prefix_projection_envelope"]
        or not isinstance(lifecycle_parents, Mapping)
        or lifecycle_parents.get("attempt_journal_projection_ref")
        != parent_refs["attempt_journal_projection_envelope"]
        or lifecycle_parents.get("cleanup_projection_ref") != result["cleanup_projection_ref"]
        or cleanup.get("attempt_ref") != attempt_ref
        or cleanup.get("lifecycle_kind") != "cleanup"
        or terminal_event.get("cleanup_projection_ref") != result["cleanup_projection_ref"]
        or not isinstance(cleanup_event_refs, Mapping)
        or cleanup_event_refs.get("cleanup_projection_ref")
        != result["cleanup_projection_ref"]
        or not isinstance(cleanup_parents, Mapping)
        or cleanup_event_refs.get("cleanup_receipt_ref")
        != cleanup_parents.get("cleanup_receipt_ref")
        or terminal_event.get("cleanup_receipt_ref")
        != cleanup_parents.get("cleanup_receipt_ref")
        or not isinstance(event_refs, Mapping)
        or event_refs.get("result_file_ref") != prefix.get("result_file_ref")
        or event_refs.get("attempt_ledger_pre_result_ref")
        != prefix.get("attempt_ledger_pre_result_ref")
    ):
        raise ValueError("accepted regression transitive lineage differs")
    del lifecycle_children
    return accepted


def _accepted_holdout_authority_envelope(
    value: object, *, name: str
) -> tuple[dict[str, object], dict[str, str]]:
    specs = {
        "benchmark_v2_holdout_authorization_public_projection_v1": (
            "holdout-authorization-public-projection",
            {
                "contract_version",
                "artifact_id",
                "authorization_id",
                "envelope_sha256",
                "claim_id",
                "safety",
                "content_sha256",
            },
        ),
        "benchmark_v2_holdout_claim_public_projection_v1": (
            "holdout-claim-public-projection",
            {
                "contract_version",
                "artifact_id",
                "claim_ref",
                "claim_id",
                "attempt_id",
                "authorization_projection_ref",
                "state",
                "safety",
                "content_sha256",
            },
        ),
        "benchmark_v2_holdout_file_anchor_public_projection_v1": (
            "holdout-file-anchor-public-projection",
            {
                "contract_version",
                "artifact_id",
                "anchor_kind",
                "claim_id",
                "authorization_envelope_sha256",
                "size_bytes",
                "verified",
                "safety",
                "content_sha256",
            },
        ),
        "benchmark_v2_holdout_registry_anchor_public_projection_v1": (
            "holdout-registry-anchor-public-projection",
            {
                "contract_version",
                "artifact_id",
                "anchor_kind",
                "claim_id",
                "authorization_envelope_sha256",
                "claim_ref",
                "envelope_verified",
                "state",
                "safety",
                "content_sha256",
            },
        ),
    }
    decoded, raw = _decode_canonical_envelope(value, name=name)
    version = decoded.get("contract_version")
    spec = specs.get(str(version))
    if spec is None or set(decoded) != spec[1] or decoded.get("safety") != SAFETY:
        raise ValueError("accepted holdout authority projection contract differs")
    payload = {
        key: deepcopy(child)
        for key, child in decoded.items()
        if key not in {"artifact_id", "content_sha256"}
    }
    semantic_sha = hashlib.sha256(
        str(version).encode("utf-8") + b"\0" + canonical_bytes(payload)
    ).hexdigest()
    if (
        decoded.get("artifact_id") != f"{spec[0]}/{semantic_sha}"
        or decoded.get("content_sha256")
        != hashlib.sha256(
            canonical_bytes(
                {key: child for key, child in decoded.items() if key != "content_sha256"}
            )
        ).hexdigest()
    ):
        raise ValueError("accepted holdout authority projection identity differs")
    ref = {
        "id": str(decoded["artifact_id"]),
        "content_sha256": str(decoded["content_sha256"]),
    }
    if not isinstance(value, Mapping) or value.get("ref") != ref:
        raise ValueError("accepted holdout authority projection envelope differs")
    del raw
    return decoded, ref


def _accepted_regression_precondition_envelope(
    value: object,
) -> tuple[dict[str, object], dict[str, str]]:
    from app.learn.hybrid.benchmark_v2_public_score import (
        validate_private_scorer_public_ref_v3,
    )

    decoded, raw = _decode_canonical_envelope(
        value, name="regression score precondition"
    )
    validated = validate_private_scorer_public_ref_v3(decoded)
    binding = validated.get("score_input_binding")
    if (
        validated.get("status") != "PASS"
        or not isinstance(binding, Mapping)
        or binding.get("partition") != "regression"
    ):
        raise ValueError("regression score precondition is not regression PASS")
    ref = {
        "contract_version": "private_scorer_public_ref_v3",
        "file_sha256": hashlib.sha256(raw + b"\n").hexdigest(),
        "content_sha256": str(validated["content_sha256"]),
    }
    if not isinstance(value, Mapping) or value.get("ref") != ref:
        raise ValueError("regression score precondition ref differs")
    return validated, ref


def _validate_holdout_public_authority_lineage(
    *,
    authorization_ref: Mapping[str, object],
    claim_ref: Mapping[str, object],
    attempt_ref: Mapping[str, object],
    authority_evidence: Mapping[str, object],
) -> str:
    authority_fields = {
        "authorization_public_projection_envelope",
        "claim_public_projection_envelope",
        "file_anchor_public_projection_envelope",
        "registry_anchor_public_projection_envelope",
    }
    if set(authority_evidence) != authority_fields:
        raise ValueError("accepted holdout authority lineage differs")
    decoded = {
        field: _accepted_holdout_authority_envelope(
            authority_evidence[field], name=field
        )[0]
        for field in authority_fields
    }
    authorization = decoded["authorization_public_projection_envelope"]
    claim = decoded["claim_public_projection_envelope"]
    file_anchor = decoded["file_anchor_public_projection_envelope"]
    registry_anchor = decoded["registry_anchor_public_projection_envelope"]
    authorization_projection_ref = authority_evidence[
        "authorization_public_projection_envelope"
    ]["ref"]
    claim_id = str(authorization.get("claim_id") or "")
    attempt_id = str(claim.get("attempt_id") or "")
    authorization_id = str(authorization_ref.get("authorization_id") or "")
    authorization_envelope_sha256 = str(
        authorization_ref.get("envelope_sha256") or ""
    )
    claim_envelope_sha256 = str(claim_ref.get("envelope_sha256") or "")
    expected_attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + claim_id
            + "\0"
            + authorization_envelope_sha256
        ).encode("utf-8")
    ).hexdigest()
    if (
        set(authorization_ref) != {"authorization_id", "envelope_sha256"}
        or set(claim_ref) != {"id", "envelope_sha256"}
        or set(attempt_ref) != {"id", "content_sha256"}
        or not all(
            isinstance(value, str)
            for value in (
                authorization_ref.get("authorization_id"),
                authorization_ref.get("envelope_sha256"),
                claim_ref.get("id"),
                claim_ref.get("envelope_sha256"),
                attempt_ref.get("id"),
                attempt_ref.get("content_sha256"),
                authorization.get("claim_id"),
                claim.get("attempt_id"),
            )
        )
        or re.fullmatch(r"holdout-authorization/[0-9a-f]{64}", authorization_id)
        is None
        or re.fullmatch(r"[0-9a-f]{64}", authorization_envelope_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", claim_id) is None
        or authorization_id != "holdout-authorization/" + claim_id
        or claim_ref.get("id") != "holdout-claim/" + claim_id
        or re.fullmatch(r"[0-9a-f]{64}", claim_envelope_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", attempt_id) is None
        or attempt_id != expected_attempt_id
        or attempt_ref.get("id") != "holdout-runner-attempt/" + attempt_id
        or re.fullmatch(r"[0-9a-f]{64}", str(attempt_ref.get("content_sha256") or ""))
        is None
        or authorization_ref
        != {
            "authorization_id": authorization.get("authorization_id"),
            "envelope_sha256": authorization.get("envelope_sha256"),
        }
        or claim_ref != claim.get("claim_ref")
        or registry_anchor.get("claim_ref") != claim_ref
        or claim.get("authorization_projection_ref")
        != authorization_projection_ref
        or claim.get("claim_id") != claim_id
        or file_anchor.get("claim_id") != claim_id
        or registry_anchor.get("claim_id") != claim_id
        or file_anchor.get("authorization_envelope_sha256")
        != authorization_envelope_sha256
        or registry_anchor.get("authorization_envelope_sha256")
        != authorization_envelope_sha256
        or claim.get("state") != "consumed"
        or registry_anchor.get("state") != "consumed"
        or file_anchor.get("anchor_kind") != "win32_zero_byte_claim_sentinel"
        or isinstance(file_anchor.get("size_bytes"), bool)
        or not isinstance(file_anchor.get("size_bytes"), int)
        or file_anchor.get("size_bytes") != 0
        or file_anchor.get("verified") is not True
        or registry_anchor.get("anchor_kind") != "hkcu_claim_registry_envelope"
        or registry_anchor.get("envelope_verified") is not True
    ):
        raise ValueError("accepted holdout authority lineage differs")
    return attempt_id


def validate_benchmark_v2_accepted_holdout_score_input_v1(
    value: object,
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_v2_contracts import BENCHMARK_RELEASE_ID, PARENT_REF

    if not isinstance(value, Mapping):
        raise ValueError("accepted holdout score input must be an object")
    accepted = deepcopy(dict(value))
    expected = {
        "contract_version",
        "content_sha256",
        "benchmark_release_id",
        "partition",
        "corpus_parent_ref",
        "provider_manifest_ref",
        "provider_corpus_ref",
        "selection_policy",
        "attempt_ref",
        "attempt_ledger_ref",
        "automatic_prediction_ref",
        "selected_lifecycle_ref",
        "verified_parent_projections",
        "prediction_run_envelope",
        "lifecycle_bundle_envelope",
        "regression_score_precondition_envelope",
        "holdout_authority_evidence",
        "holdout_authorization_ref",
        "holdout_claim_ref",
        "safety",
    }
    if (
        set(accepted) != expected
        or accepted.get("contract_version")
        != "benchmark_v2_accepted_holdout_score_input_v1"
        or accepted.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
        or accepted.get("partition") != "holdout"
        or accepted.get("selection_policy")
        != "unique_claim_bound_holdout_attempt"
        or accepted.get("corpus_parent_ref") != PARENT_REF
        or accepted.get("safety") != SAFETY
        or accepted.get("content_sha256")
        != hashlib.sha256(
            canonical_bytes(
                {key: child for key, child in accepted.items() if key != "content_sha256"}
            )
        ).hexdigest()
    ):
        raise ValueError("accepted holdout score input contract is invalid")
    _accepted_regression_precondition_envelope(
        accepted["regression_score_precondition_envelope"]
    )
    authorization_ref = accepted.get("holdout_authorization_ref")
    claim_ref = accepted.get("holdout_claim_ref")
    if (
        not isinstance(authorization_ref, Mapping)
        or set(authorization_ref) != {"authorization_id", "envelope_sha256"}
        or not isinstance(claim_ref, Mapping)
        or set(claim_ref) != {"id", "envelope_sha256"}
    ):
        raise ValueError("accepted holdout pathless authority refs are invalid")
    authority = accepted.get("holdout_authority_evidence")
    if not isinstance(authority, Mapping):
        raise ValueError("accepted holdout authority evidence differs")
    if not isinstance(accepted.get("attempt_ref"), Mapping):
        raise ValueError("accepted holdout claim-bound attempt differs")
    _validate_holdout_public_authority_lineage(
        authorization_ref=authorization_ref,
        claim_ref=claim_ref,
        attempt_ref=accepted["attempt_ref"],
        authority_evidence=authority,
    )

    prediction, prediction_ref = _accepted_envelope(
        accepted["prediction_run_envelope"], name="accepted holdout prediction run"
    )
    lifecycle, lifecycle_ref = _accepted_envelope(
        accepted["lifecycle_bundle_envelope"], name="accepted holdout lifecycle bundle"
    )
    del lifecycle_ref
    if (
        prediction.get("contract_version") != "benchmark_v2_prediction_run_v3"
        or lifecycle.get("contract_version") != "benchmark_v2_lifecycle_bundle_v3"
        or prediction.get("partition") != "holdout"
        or lifecycle.get("partition") != "holdout"
    ):
        raise ValueError("accepted holdout v3 bundle contract differs")
    prediction_by_ref, prediction_children = _accepted_closure_index(
        prediction, name="accepted holdout prediction run"
    )
    lifecycle_by_ref, lifecycle_children = _accepted_closure_index(
        lifecycle, name="accepted holdout lifecycle bundle"
    )
    shared_versions = {
        "benchmark_v2_holdout_runner_event_verified_projection_v1",
        "benchmark_v2_holdout_attempt_ledger_pre_result_verified_projection_v1",
        "benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1",
        "benchmark_v2_holdout_projected_attempt_ledger_v1",
        "benchmark_v2_holdout_actual_result_verified_projection_v1",
    }
    prediction_shared = {
        key: envelope
        for key, (item, envelope) in prediction_by_ref.items()
        if item.get("contract_version") in shared_versions
    }
    lifecycle_shared = {
        key: envelope
        for key, (item, envelope) in lifecycle_by_ref.items()
        if item.get("contract_version") in shared_versions
    }
    shared_counts = {
        version: sum(
            item.get("contract_version") == version for item in prediction_children
        )
        for version in shared_versions
    }
    if (
        prediction_shared != lifecycle_shared
        or shared_counts.get(
            "benchmark_v2_holdout_runner_event_verified_projection_v1"
        )
        != 4
        or any(
            shared_counts[version] != 1
            for version in shared_versions
            if version != "benchmark_v2_holdout_runner_event_verified_projection_v1"
        )
    ):
        raise ValueError("accepted holdout shared closure differs")

    parents = accepted.get("verified_parent_projections")
    parent_contracts = {
        "runner_ledger_prefix_projection_envelope": "benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1",
        "attempt_journal_projection_envelope": "benchmark_v2_attempt_journal_verified_projection_v1",
        "actual_body_projection_envelope": "benchmark_v2_actual_body_verified_projection_v1",
        "actual_result_projection_envelope": "benchmark_v2_holdout_actual_result_verified_projection_v1",
    }
    if not isinstance(parents, Mapping) or set(parents) != set(parent_contracts):
        raise ValueError("accepted holdout verified parents differ")
    decoded_parents: dict[str, dict[str, object]] = {}
    parent_refs: dict[str, dict[str, object]] = {}
    for field, contract in parent_contracts.items():
        decoded, ref = _accepted_envelope(parents[field], name=field)
        if decoded.get("contract_version") != contract:
            raise ValueError("accepted holdout verified parent contract differs")
        decoded_parents[field] = decoded
        parent_refs[field] = ref
    prefix = decoded_parents["runner_ledger_prefix_projection_envelope"]
    journal = decoded_parents["attempt_journal_projection_envelope"]
    body = decoded_parents["actual_body_projection_envelope"]
    result = decoded_parents["actual_result_projection_envelope"]

    def resolve(
        index: Mapping[bytes, tuple[dict[str, object], dict[str, object]]],
        ref: object,
        contract: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        if not isinstance(ref, Mapping):
            raise ValueError("accepted holdout child ref is invalid")
        found = index.get(canonical_bytes(ref))
        if found is None or found[0].get("contract_version") != contract:
            raise ValueError("accepted holdout child ref is unresolved")
        return found

    ledger, _ = resolve(
        prediction_by_ref,
        accepted["attempt_ledger_ref"],
        "benchmark_v2_holdout_projected_attempt_ledger_v1",
    )
    automatic, _ = resolve(
        prediction_by_ref,
        accepted["automatic_prediction_ref"],
        "automatic_prediction_v3",
    )
    pre_result, pre_result_envelope = resolve(
        prediction_by_ref,
        ledger["pre_result_verification_ref"],
        "benchmark_v2_holdout_attempt_ledger_pre_result_verified_projection_v1",
    )
    events = sorted(
        (
            item
            for item in prediction_children
            if item.get("contract_version")
            == "benchmark_v2_holdout_runner_event_verified_projection_v1"
        ),
        key=lambda item: int(item["sequence"]),
    )
    event_refs = [pathless_artifact_ref(item) for item in events]
    cleanup_lifecycle, _ = resolve(
        lifecycle_by_ref,
        events[2]["load_bearing_refs"]["cleanup_projection_ref"],
        "benchmark_v2_lifecycle_verified_projection_v1",
    )
    selected_lifecycle, _ = resolve(
        lifecycle_by_ref,
        accepted["selected_lifecycle_ref"],
        "benchmark_v2_lifecycle_verified_projection_v1",
    )
    if (
        prediction.get("benchmark_release_id") != accepted["benchmark_release_id"]
        or lifecycle.get("benchmark_release_id") != accepted["benchmark_release_id"]
        or prediction.get("corpus_parent_ref") != accepted["corpus_parent_ref"]
        or prediction.get("provider_manifest_ref") != accepted["provider_manifest_ref"]
        or prediction.get("provider_corpus_ref") != accepted["provider_corpus_ref"]
        or any(
            outer.get("attempt_ref") != accepted["attempt_ref"]
            for outer in (prediction, lifecycle)
        )
        or any(
            outer.get("projected_attempt_ledger_ref")
            != accepted["attempt_ledger_ref"]
            for outer in (prediction, lifecycle)
        )
        or prediction.get("automatic_prediction_ref")
        != accepted["automatic_prediction_ref"]
        or any(
            outer.get("selected_lifecycle_ref")
            != accepted["selected_lifecycle_ref"]
            for outer in (prediction, lifecycle)
        )
        or any(
            outer.get("raw_ledger_prefix_verification_ref")
            != parent_refs["runner_ledger_prefix_projection_envelope"]
            for outer in (prediction, lifecycle)
        )
        or prefix.get("authorization_ref") != authorization_ref
        or prefix.get("claim_ref") != claim_ref
        or prefix.get("attempt_ref") != accepted["attempt_ref"]
        or prefix.get("pre_result_verification_ref")
        != pathless_artifact_ref(pre_result)
        or prefix.get("event_projection_refs") != event_refs
        or prefix.get("terminal_event_projection_ref") != event_refs[-1]
        or prefix.get("selection_eligible") is not True
        or pre_result.get("authorization_ref") != authorization_ref
        or pre_result.get("claim_ref") != claim_ref
        or pre_result.get("attempt_ref") != accepted["attempt_ref"]
        or ledger.get("authorization_ref") != authorization_ref
        or ledger.get("claim_ref") != claim_ref
        or ledger.get("selected_attempt_ref") != accepted["attempt_ref"]
        or len(ledger.get("entries", [])) != 1
        or ledger["entries"][0].get("event_projection_refs") != event_refs
        or result.get("attempt_ref") != accepted["attempt_ref"]
        or result.get("pre_result_verification_ref") != pathless_artifact_ref(pre_result)
        or result.get("runner_ledger_prefix_projection_ref")
        != parent_refs["runner_ledger_prefix_projection_envelope"]
        or result.get("result_event_projection_ref") != event_refs[-1]
        or prediction_shared.get(canonical_bytes(pathless_artifact_ref(pre_result)))
        != pre_result_envelope
        or lifecycle_shared.get(canonical_bytes(pathless_artifact_ref(pre_result)))
        != pre_result_envelope
        or prediction_shared.get(
            canonical_bytes(parent_refs["runner_ledger_prefix_projection_envelope"])
        )
        != parents["runner_ledger_prefix_projection_envelope"]
        or lifecycle_shared.get(
            canonical_bytes(parent_refs["runner_ledger_prefix_projection_envelope"])
        )
        != parents["runner_ledger_prefix_projection_envelope"]
        or prediction_shared.get(
            canonical_bytes(parent_refs["actual_result_projection_envelope"])
        )
        != parents["actual_result_projection_envelope"]
        or lifecycle_shared.get(
            canonical_bytes(parent_refs["actual_result_projection_envelope"])
        )
        != parents["actual_result_projection_envelope"]
        or any(event.get("authorization_ref") != authorization_ref for event in events)
        or any(event.get("claim_ref") != claim_ref for event in events)
        or any(event.get("attempt_ref") != accepted["attempt_ref"] for event in events)
        or [event.get("event_kind") for event in events]
        != ["opened", "body_complete", "cleanup", "result"]
        or [event.get("sequence") for event in events] != [0, 1, 2, 3]
        or cleanup_lifecycle.get("cleanup_stable_zero") is not True
        or cleanup_lifecycle.get("resource_counts")
        != {
            "service_operations": 0,
            "windows": 0,
            "providers": 0,
            "listeners": 0,
            "leases": 0,
        }
        or selected_lifecycle.get("cleanup_stable_zero") is not True
        or selected_lifecycle.get("attempt_ref") != accepted["attempt_ref"]
        or journal.get("attempt_ref") != accepted["attempt_ref"]
        or body.get("attempt_ref") != accepted["attempt_ref"]
        or automatic.get("source_parent_ref")
        != parent_refs["actual_body_projection_envelope"]
        or result.get("body_projection_ref")
        != parent_refs["actual_body_projection_envelope"]
        or result.get("cleanup_projection_ref")
        != pathless_artifact_ref(cleanup_lifecycle)
    ):
        raise ValueError("accepted holdout transitive lineage differs")

    prediction_external = _prediction_external_refs(
        prediction_run=prediction,
        automatic=automatic,
        artifacts=prediction_children,
        runner_and_ledger_envelopes=[
            envelope
            for _, envelope in prediction_by_ref.values()
            if envelope["ref"] in [item["ref"] for item in prediction["sealed_artifact_envelopes"]]
        ],
    )
    validate_pathless_recursive(
        registry_name="prediction_run_v3",
        roots=[prediction_ref],
        envelopes=[
            deepcopy(dict(accepted["prediction_run_envelope"])),
            *[deepcopy(dict(item)) for item in prediction["sealed_artifact_envelopes"]],
        ],
        external_refs=prediction_external,
        context={"public_holdout": True},
    )
    verified_parent_external = {
        "benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1.pre_result_verification_ref": prefix["pre_result_verification_ref"],
        "benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1.terminal_event_projection_ref": prefix["terminal_event_projection_ref"],
        "benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1.event_projection_refs": prefix["event_projection_refs"],
        "benchmark_v2_attempt_journal_verified_projection_v1.attempt_ref": journal["attempt_ref"],
        "benchmark_v2_attempt_journal_verified_projection_v1.terminal_event_ref": journal["terminal_event_ref"],
        "benchmark_v2_attempt_journal_verified_projection_v1.cleanup_projection_ref": journal["cleanup_projection_ref"],
        "benchmark_v2_actual_body_verified_projection_v1.attempt_ref": body["attempt_ref"],
        "benchmark_v2_actual_body_verified_projection_v1.pre_vista_evidence_refs": body["pre_vista_evidence_refs"],
        "benchmark_v2_holdout_actual_result_verified_projection_v1.cleanup_projection_ref": result["cleanup_projection_ref"],
        "benchmark_v2_holdout_actual_result_verified_projection_v1.pre_result_verification_ref": result["pre_result_verification_ref"],
        "benchmark_v2_holdout_actual_result_verified_projection_v1.result_event_projection_ref": result["result_event_projection_ref"],
    }
    validate_pathless_recursive(
        registry_name="verified_parents_v1",
        roots=[parent_refs[field] for field in parent_contracts],
        envelopes=[deepcopy(dict(parents[field])) for field in parent_contracts],
        external_refs=verified_parent_external,
        context={},
    )
    terminal = next(
        (
            item
            for item in lifecycle_children
            if item.get("contract_version")
            == "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1"
        ),
        None,
    )
    screen_lifecycles = [
        item
        for item in lifecycle_children
        if item.get("contract_version")
        == "benchmark_v2_lifecycle_verified_projection_v1"
        and item.get("lifecycle_kind") == "screen_group"
    ]
    if not isinstance(terminal, Mapping) or len(screen_lifecycles) != 12:
        raise ValueError("accepted holdout lifecycle closure differs")
    lifecycle_external = {
        "benchmark_v2_lifecycle_bundle_v3.attempt_ref": accepted["attempt_ref"],
        "benchmark_v2_lifecycle_verified_projection_v1.attempt_ref": accepted["attempt_ref"],
        "benchmark_v2_lifecycle_verified_projection_v1.parent_refs.cleanup_receipt_ref": cleanup_lifecycle["parent_refs"]["cleanup_receipt_ref"],
        "benchmark_v2_lifecycle_verified_projection_v1.parent_refs.actual_screen_group_ref": [
            item["parent_refs"]["actual_screen_group_ref"]
            for item in screen_lifecycles
        ],
        "benchmark_v2_lifecycle_verified_projection_v1.parent_refs.provider_group_ref": [
            item["parent_refs"]["provider_group_ref"] for item in screen_lifecycles
        ],
        "benchmark_v2_lifecycle_verified_projection_v1.parent_refs.attempt_journal_projection_ref": selected_lifecycle["parent_refs"]["attempt_journal_projection_ref"],
        "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1.attempt_ref": accepted["attempt_ref"],
        "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1.cleanup_receipt_ref": terminal["cleanup_receipt_ref"],
        "benchmark_v2_holdout_runner_event_verified_projection_v1.load_bearing_refs.attempt_ref": accepted["attempt_ref"],
        "benchmark_v2_holdout_runner_event_verified_projection_v1.load_bearing_refs.body_file_ref": events[1]["load_bearing_refs"]["body_file_ref"],
        "benchmark_v2_holdout_runner_event_verified_projection_v1.load_bearing_refs.cleanup_receipt_ref": events[2]["load_bearing_refs"]["cleanup_receipt_ref"],
        "benchmark_v2_holdout_runner_event_verified_projection_v1.load_bearing_refs.result_file_ref": events[3]["load_bearing_refs"]["result_file_ref"],
        "benchmark_v2_holdout_actual_result_verified_projection_v1.body_projection_ref": result["body_projection_ref"],
    }
    validate_pathless_recursive(
        registry_name="lifecycle_bundle_v3",
        roots=[pathless_artifact_ref(lifecycle)],
        envelopes=[
            deepcopy(dict(accepted["lifecycle_bundle_envelope"])),
            *[deepcopy(dict(item)) for item in lifecycle["sealed_artifact_envelopes"]],
        ],
        external_refs=lifecycle_external,
        context={},
    )
    return accepted


def materialize_benchmark_v2_accepted_holdout_score_input_v1(
    *,
    actual_body_bytes: bytes,
    actual_result_bytes: bytes,
    cleanup_receipt_bytes: bytes,
    expected_attempt_dir: Path,
    provider_manifest_bytes: bytes,
    provider_corpus_bytes: bytes,
    attempt_events: Sequence[Mapping[str, object]],
    attempt_events_jsonl_bytes: bytes,
    attempt_journal_events: Sequence[Mapping[str, object]],
    attempt_journal_jsonl_bytes: bytes,
    native_authorization_ref: Mapping[str, object],
    holdout_anchor_verification_result: Mapping[str, object],
    regression_score_precondition_envelope: Mapping[str, object],
) -> dict[str, object]:
    """从固定 H1-H4 原始证据重新派生唯一可公开的 holdout 图。"""

    from app.learn.hybrid.benchmark_v2_contracts import BENCHMARK_RELEASE_ID
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        compose_benchmark_v2_holdout_lifecycle_bundle_v3,
        materialize_benchmark_v2_holdout_attempt_projections,
        _parse_exact_canonical_jsonl_snapshot,
        project_benchmark_v2_attempt_journal,
        project_benchmark_v2_attempt_journal_terminal_event,
        project_benchmark_v2_attempt_lifecycle,
        project_benchmark_v2_cleanup_lifecycle,
        project_benchmark_v2_screen_group_lifecycles,
    )
    from app.learn.recognition.uei.canonical import content_sha256

    _accepted_regression_precondition_envelope(
        regression_score_precondition_envelope
    )
    if (
        not isinstance(native_authorization_ref, Mapping)
        or set(native_authorization_ref)
        != {"authorization_id", "envelope_sha256", "fixed_authorization_path"}
        or not isinstance(native_authorization_ref.get("fixed_authorization_path"), str)
        or not Path(str(native_authorization_ref["fixed_authorization_path"])).is_absolute()
    ):
        raise ValueError("holdout native authorization ref is invalid")
    public_native_authorization_ref = {
        "authorization_id": str(native_authorization_ref["authorization_id"]),
        "envelope_sha256": str(native_authorization_ref["envelope_sha256"]),
    }
    anchor = deepcopy(dict(holdout_anchor_verification_result))
    anchor_fields = {
        "contract_version",
        "authorization_ref",
        "claim_ref",
        "attempt_id",
        "authority_projection_envelopes",
        "safety",
        "content_sha256",
    }
    if (
        set(anchor) != anchor_fields
        or anchor.get("contract_version")
        != "benchmark_v2_holdout_anchor_verification_result_v1"
        or anchor.get("authorization_ref") != public_native_authorization_ref
        or anchor.get("safety") != SAFETY
        or anchor.get("content_sha256")
        != content_sha256(anchor)
    ):
        raise ValueError("holdout anchor verification result is invalid")
    authority = anchor.get("authority_projection_envelopes")
    authority_fields = {
        "authorization_public_projection_envelope",
        "claim_public_projection_envelope",
        "file_anchor_public_projection_envelope",
        "registry_anchor_public_projection_envelope",
    }
    if not isinstance(authority, Mapping) or set(authority) != authority_fields:
        raise ValueError("holdout anchor authority projections differ")
    for field in authority_fields:
        _accepted_holdout_authority_envelope(authority[field], name=field)

    body = _parse_holdout_actual_body_bytes(actual_body_bytes)
    raw_attempt = body.get("attempt_ref")
    if not isinstance(raw_attempt, Mapping):
        raise ValueError("holdout body attempt ref is invalid")
    claim_ref = anchor.get("claim_ref")
    attempt_id = anchor.get("attempt_id")
    claim_id = (
        str(claim_ref.get("id")).split("/", 1)[1]
        if isinstance(claim_ref, Mapping)
        and isinstance(claim_ref.get("id"), str)
        and str(claim_ref["id"]).startswith("holdout-claim/")
        else ""
    )
    expected_attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + claim_id
            + "\0"
            + str(native_authorization_ref.get("envelope_sha256") or "")
        ).encode("utf-8")
    ).hexdigest()
    if (
        raw_attempt.get("authorization_ref") != dict(native_authorization_ref)
        or raw_attempt.get("claim_ref") != claim_ref
        or raw_attempt.get("attempt_id") != attempt_id
        or attempt_id != expected_attempt_id
    ):
        raise ValueError("holdout unique claim-bound attempt differs")

    try:
        cleanup_value = json.loads(cleanup_receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("holdout cleanup receipt is not UTF-8 JSON") from error
    if (
        not isinstance(cleanup_value, Mapping)
        or cleanup_receipt_bytes != canonical_bytes(cleanup_value) + b"\n"
    ):
        raise ValueError("holdout cleanup receipt bytes are not canonical")
    cleanup = deepcopy(dict(cleanup_value))

    verified_journal_events, raw_journal_lines = (
        _parse_exact_canonical_jsonl_snapshot(
            attempt_journal_jsonl_bytes,
            expected_events=attempt_journal_events,
            name="holdout attempt journal JSONL",
        )
    )

    actual_body_projection = project_benchmark_v2_holdout_actual_body(
        actual_body_bytes=actual_body_bytes,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    cleanup_projection = project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=raw_attempt, cleanup_receipt=cleanup
    )
    terminal_projection = project_benchmark_v2_attempt_journal_terminal_event(
        attempt_ref=raw_attempt,
        journal_events=verified_journal_events,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )
    journal_projection = project_benchmark_v2_attempt_journal(
        attempt_ref=raw_attempt,
        journal_events=verified_journal_events,
        terminal_event_projection=terminal_projection,
        cleanup_projection=cleanup_projection,
    )
    screen_lifecycles = project_benchmark_v2_screen_group_lifecycles(
        attempt_ref=raw_attempt,
        screen_group_projections=body["screen_group_results"],
    )
    selected_lifecycle = project_benchmark_v2_attempt_lifecycle(
        attempt_ref=raw_attempt,
        journal_events=verified_journal_events,
        attempt_journal_projection=journal_projection,
        cleanup_projection=cleanup_projection,
        terminal_event_projection=terminal_projection,
        screen_group_lifecycle_projections=screen_lifecycles,
    )
    materialization = materialize_benchmark_v2_holdout_attempt_projections(
        benchmark_release_id=BENCHMARK_RELEASE_ID,
        attempt_events=attempt_events,
        attempt_events_jsonl_bytes=attempt_events_jsonl_bytes,
        actual_body_bytes=actual_body_bytes,
        actual_result_bytes=actual_result_bytes,
        cleanup_receipt_bytes=cleanup_receipt_bytes,
        expected_attempt_dir=expected_attempt_dir,
        actual_body_projection=actual_body_projection,
        cleanup_projection=cleanup_projection,
        selected_lifecycle_projection=selected_lifecycle,
    )
    exact_journal_sha256 = hashlib.sha256(attempt_journal_jsonl_bytes).hexdigest()
    if (
        terminal_projection.get("raw_event_sha256")
        != hashlib.sha256(raw_journal_lines[-1]).hexdigest()
        or journal_projection.get("raw_journal_sha256") != exact_journal_sha256
        or selected_lifecycle.get("raw_evidence_sha256") != exact_journal_sha256
    ):
        raise ValueError("holdout attempt journal JSONL hashes differ")
    lifecycle_bundle = compose_benchmark_v2_holdout_lifecycle_bundle_v3(
        benchmark_release_id=BENCHMARK_RELEASE_ID,
        materialization=materialization,
        attempt_ref=raw_attempt,
        cleanup_lifecycle_projection=cleanup_projection,
        journal_terminal_event_projection=terminal_projection,
        selected_attempt_lifecycle_projection=selected_lifecycle,
        screen_group_lifecycle_projections=screen_lifecycles,
    )
    prediction = materialize_prediction_run_v3(
        actual_body_bytes=actual_body_bytes,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
        actual_body_verified_projection=actual_body_projection,
        lifecycle_bundle_v3=lifecycle_bundle,
    )
    run = prediction.prediction_run
    parents = {
        "runner_ledger_prefix_projection_envelope": seal_pathless_envelope(
            materialization.runner_ledger_prefix_projection
        ),
        "attempt_journal_projection_envelope": seal_pathless_envelope(
            journal_projection
        ),
        "actual_body_projection_envelope": seal_pathless_envelope(
            actual_body_projection
        ),
        "actual_result_projection_envelope": seal_pathless_envelope(
            materialization.actual_result_projection
        ),
    }
    accepted: dict[str, object] = {
        "contract_version": "benchmark_v2_accepted_holdout_score_input_v1",
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "partition": "holdout",
        "corpus_parent_ref": deepcopy(run["corpus_parent_ref"]),
        "provider_manifest_ref": deepcopy(run["provider_manifest_ref"]),
        "provider_corpus_ref": deepcopy(run["provider_corpus_ref"]),
        "selection_policy": "unique_claim_bound_holdout_attempt",
        "attempt_ref": deepcopy(run["attempt_ref"]),
        "attempt_ledger_ref": deepcopy(run["projected_attempt_ledger_ref"]),
        "automatic_prediction_ref": deepcopy(run["automatic_prediction_ref"]),
        "selected_lifecycle_ref": deepcopy(run["selected_lifecycle_ref"]),
        "verified_parent_projections": parents,
        "prediction_run_envelope": deepcopy(prediction.prediction_run_envelope),
        "lifecycle_bundle_envelope": seal_pathless_envelope(lifecycle_bundle),
        "regression_score_precondition_envelope": deepcopy(
            dict(regression_score_precondition_envelope)
        ),
        "holdout_authority_evidence": deepcopy(dict(authority)),
        "holdout_authorization_ref": {
            **public_native_authorization_ref,
        },
        "holdout_claim_ref": deepcopy(dict(claim_ref)),
        "safety": deepcopy(SAFETY),
    }
    accepted["content_sha256"] = hashlib.sha256(canonical_bytes(accepted)).hexdigest()
    return validate_benchmark_v2_accepted_holdout_score_input_v1(accepted)


def materialize_benchmark_v2_accepted_regression_score_input_v2(
    *,
    actual_body_bytes: bytes,
    actual_result_bytes: bytes,
    cleanup_receipt_bytes: bytes,
    expected_attempt_dir: Path,
    provider_manifest_bytes: bytes,
    provider_corpus_bytes: bytes,
    runner_ledger_prefix_projection: Mapping[str, object],
    attempt_journal_projection: Mapping[str, object],
    actual_body_projection: Mapping[str, object],
    actual_result_projection: Mapping[str, object],
    lifecycle_bundle_v3: Mapping[str, object],
) -> dict[str, object]:
    """最后构造 accepted regression root；prediction identity 仅由 C3 派生。"""

    from app.learn.hybrid.benchmark_v2_contracts import BENCHMARK_RELEASE_ID

    derived_body_projection = project_benchmark_v2_actual_body(
        actual_body_bytes=actual_body_bytes,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    if derived_body_projection != dict(actual_body_projection):
        raise ValueError("accepted actual body projection differs from raw bytes")
    prediction = materialize_prediction_run_v3(
        actual_body_bytes=actual_body_bytes,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
        actual_body_verified_projection=derived_body_projection,
        lifecycle_bundle_v3=lifecycle_bundle_v3,
    )
    prediction_run = prediction.prediction_run
    lifecycle_by_ref, _ = _accepted_closure_index(
        lifecycle_bundle_v3, name="accepted materializer lifecycle bundle"
    )

    def resolve_lifecycle_child(
        ref: object, contract_version: str
    ) -> dict[str, object]:
        if not isinstance(ref, Mapping):
            raise ValueError("accepted materializer lifecycle ref is invalid")
        resolved = lifecycle_by_ref.get(canonical_bytes(ref))
        if (
            resolved is None
            or resolved[0].get("contract_version") != contract_version
        ):
            raise ValueError("accepted materializer lifecycle ref is unresolved")
        return resolved[0]

    result_event_projection = resolve_lifecycle_child(
        runner_ledger_prefix_projection.get("result_event_projection_ref"),
        "benchmark_v2_runner_event_verified_projection_v1",
    )
    selected_lifecycle = resolve_lifecycle_child(
        lifecycle_bundle_v3.get("selected_lifecycle_ref"),
        "benchmark_v2_lifecycle_verified_projection_v1",
    )
    selected_parents = selected_lifecycle.get("parent_refs")
    if not isinstance(selected_parents, Mapping):
        raise ValueError("accepted materializer selected lifecycle parents are invalid")
    cleanup_projection = resolve_lifecycle_child(
        selected_parents.get("cleanup_projection_ref"),
        "benchmark_v2_lifecycle_verified_projection_v1",
    )
    derived_result_projection = project_benchmark_v2_actual_result(
        actual_result_bytes=actual_result_bytes,
        cleanup_receipt_bytes=cleanup_receipt_bytes,
        expected_attempt_dir=expected_attempt_dir,
        actual_body_projection=derived_body_projection,
        cleanup_projection=cleanup_projection,
        runner_ledger_prefix_projection=runner_ledger_prefix_projection,
        result_event_projection=result_event_projection,
    )
    if derived_result_projection != dict(actual_result_projection):
        raise ValueError("accepted actual result projection differs from raw bytes")
    parents = {
        "runner_ledger_prefix_projection_envelope": seal_pathless_envelope(runner_ledger_prefix_projection),
        "attempt_journal_projection_envelope": seal_pathless_envelope(attempt_journal_projection),
        "actual_body_projection_envelope": seal_pathless_envelope(derived_body_projection),
        "actual_result_projection_envelope": seal_pathless_envelope(actual_result_projection),
    }
    body: dict[str, object] = {
        "contract_version": "benchmark_v2_accepted_regression_score_input_v2",
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "partition": "regression",
        "corpus_parent_ref": deepcopy(prediction_run["corpus_parent_ref"]),
        "provider_manifest_ref": deepcopy(prediction_run["provider_manifest_ref"]),
        "provider_corpus_ref": deepcopy(prediction_run["provider_corpus_ref"]),
        "selection_policy": "first_complete_lifecycle_verified_attempt",
        "attempt_ref": deepcopy(prediction_run["attempt_ref"]),
        "attempt_ledger_ref": deepcopy(prediction_run["projected_attempt_ledger_ref"]),
        "automatic_prediction_ref": deepcopy(prediction_run["automatic_prediction_ref"]),
        "selected_lifecycle_ref": deepcopy(prediction_run["selected_lifecycle_ref"]),
        "verified_parent_projections": parents,
        "prediction_run_envelope": deepcopy(prediction.prediction_run_envelope),
        "lifecycle_bundle_envelope": seal_pathless_envelope(lifecycle_bundle_v3),
        "safety": deepcopy(SAFETY),
    }
    body["content_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    return validate_benchmark_v2_accepted_regression_score_input_v2(
        body,
        actual_body_bytes=actual_body_bytes,
        actual_result_bytes=actual_result_bytes,
        cleanup_receipt_bytes=cleanup_receipt_bytes,
        expected_attempt_dir=expected_attempt_dir,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )

def seal_target_binding(*,artifact_id:str,case_id:str,candidate_id:str,fusion_ref:Mapping[str,str],capture_ref:Mapping[str,str],bbox_ref:Mapping[str,str],bbox:list[int],source_parent_ref:Mapping[str,str])->dict[str,object]:
    if len(bbox)!=4 or not all(isinstance(v,int) for v in bbox): raise ValueError("bbox invalid")
    value={"contract_version":"sealed_target_binding_v3","artifact_id":artifact_id,"case_id":case_id,"candidate_id":candidate_id,"fusion_ref":exact_ref(fusion_ref,"fusion"),"capture_ref":exact_ref(capture_ref,"capture"),"bbox_ref":exact_ref(bbox_ref,"bbox"),"bbox":list(bbox),"source_parent_ref":exact_ref(source_parent_ref,"parent"),"safety":deepcopy(SAFETY)}
    if not all(isinstance(value[k],str) and value[k] for k in ("artifact_id","case_id","candidate_id")): raise ValueError("binding identity invalid")
    return value

def seal_vista_request(*,artifact_id:str,case_id:str,target_binding_ref:Mapping[str,str],candidate_id:str,fusion_ref:Mapping[str,str],capture_ref:Mapping[str,str],bbox_ref:Mapping[str,str],source_parent_ref:Mapping[str,str])->dict[str,object]:
    if not all(isinstance(value,str) and value for value in (artifact_id,case_id,candidate_id)): raise ValueError("request identity invalid")
    return {"contract_version":"sealed_vista_request_v3","artifact_id":artifact_id,"case_id":case_id,"target_binding_ref":exact_ref(target_binding_ref,"binding"),"candidate_id":candidate_id,"fusion_ref":exact_ref(fusion_ref,"fusion"),"capture_ref":exact_ref(capture_ref,"capture"),"bbox_ref":exact_ref(bbox_ref,"bbox"),"submission_status":"SUBMITTED","source_parent_ref":exact_ref(source_parent_ref,"parent"),"safety":deepcopy(SAFETY)}

def _validate_pre(pre: Mapping[str,object])->dict[str,object]:
    if set(pre)!={"contract_version","artifact_id","prediction_id","source_parent_ref","partition","release_id","rows","safety"} or pre["contract_version"]!="automatic_prediction_v2" or pre["safety"]!=SAFETY: raise ValueError("automatic prediction artifact not closed")
    exact_ref(pre["source_parent_ref"],"prediction parent")
    if pre["partition"] not in {"regression","holdout"}: raise ValueError("partition invalid")
    rows=pre["rows"]
    if not isinstance(rows,list) or not rows: raise ValueError("automatic rows empty")
    keys=set(); checked=[]
    for raw in rows:
        if not isinstance(raw,Mapping): raise ValueError("automatic row invalid")
        row=deepcopy(dict(raw)); base={"case_id","arm_id","selection_status","eligibility"}
        if not base.issubset(row) or row["arm_id"] not in ARMS or row["selection_status"] not in STATUSES: raise ValueError("automatic row identity invalid")
        if row["eligibility"]!=ELIGIBILITY[row["selection_status"]]: raise ValueError("automatic row eligibility invalid")
        key=(row["case_id"],row["arm_id"])
        if key in keys: raise ValueError("duplicate automatic arm/case")
        keys.add(key)
        if row["selection_status"]=="selected":
            allowed=base|{"target_binding_ref","vista_request_ref","vista_result"}
            exact_ref(row.get("target_binding_ref"),"row binding")
            if row["arm_id"] in {"omni_to_qwen","omni_to_qwen_vista"}: exact_ref(row.get("vista_request_ref"),"row request")
            elif "vista_request_ref" in row: raise ValueError("non-pair arm cannot carry VISTA request")
            if row["arm_id"]=="omni_to_qwen_vista":
                result=row.get("vista_result")
                if not isinstance(result,Mapping) or set(result)-{"status","request_ref","target_binding_ref","canonical_capture_pixel_point"} or result.get("status") not in {"validated","failed","timeout","out_of_bounds","missing"}: raise ValueError("VISTA result invalid")
                exact_ref(result.get("request_ref"),"result request"); exact_ref(result.get("target_binding_ref"),"result binding")
            elif "vista_result" in row: raise ValueError("only VISTA arm may carry result")
        else:
            allowed=base|{"failure_reason"}
            if not isinstance(row.get("failure_reason"),str) or not row["failure_reason"]: raise ValueError("missing/failed selection requires reason")
        if set(row)-allowed: raise ValueError("automatic row has extra fields")
        checked.append(row)
    by={(row["case_id"],row["arm_id"]):row for row in checked}
    for case_id in {row["case_id"] for row in checked}:
        baseline=by.get((case_id,"omni_to_qwen")); vista=by.get((case_id,"omni_to_qwen_vista"))
        if baseline is None or vista is None: continue
        if baseline["selection_status"]!=vista["selection_status"] or baseline["eligibility"]!=vista["eligibility"]: raise ValueError("paired arm eligibility mismatch")
        if baseline["selection_status"]=="selected":
            if baseline["target_binding_ref"]!=vista["target_binding_ref"] or baseline["vista_request_ref"]!=vista["vista_request_ref"]: raise ValueError("selected pair evidence mismatch")
        elif baseline["failure_reason"]!=vista["failure_reason"]:
            raise ValueError("ineligible pair reason mismatch")
    value=deepcopy(dict(pre)); value["rows"]=checked
    return value

def seal_automatic_prediction(*,request_ref:Mapping[str,str],pre_review:Mapping[str,object],execution_refs:list[Mapping[str,str]],lifecycle_ref:Mapping[str,str])->dict[str,object]:
    artifact=_validate_pre(pre_review); pre_ref=artifact_ref(artifact)
    record={"contract_version":"automatic_prediction_record_v2","prediction_id":artifact["prediction_id"],"request_ref":exact_ref(request_ref,"request"),"pre_review_ref":pre_ref,"execution_refs":[exact_ref(x,"execution") for x in execution_refs],"lifecycle_ref":exact_ref(lifecycle_ref,"lifecycle"),"decisions":[],"post_review_ref":pre_ref,"safety":deepcopy(SAFETY)}
    record["revision_ref"]={"id":"prediction-revision/0","content_sha256":hashlib.sha256(canonical_bytes(record)).hexdigest()}
    return {"record":record,"record_ref":prediction_record_ref(record),"pre_review_artifact":sealed_artifact_envelope(artifact)}

def prediction_record_ref(record:Mapping[str,object])->dict[str,str]:
    prediction_id=record.get("prediction_id")
    if not isinstance(prediction_id,str) or not prediction_id: raise ValueError("prediction record identity invalid")
    return {"id":f"prediction-record/{prediction_id}","content_sha256":hashlib.sha256(canonical_bytes(record)).hexdigest()}

def seal_review_decision(*,predecessor_ref:Mapping[str,str],target_binding_ref:Mapping[str,str],disposition:str,replacement_candidate_id:str|None)->dict[str,object]:
    if disposition not in {"accepted","corrected","rejected"}: raise ValueError("review disposition invalid")
    if (disposition=="corrected") != (isinstance(replacement_candidate_id,str) and bool(replacement_candidate_id)): raise ValueError("review replacement semantics invalid")
    payload={"contract_version":"automatic_review_decision_v2","decision_type":"candidate_review","predecessor_ref":exact_ref(predecessor_ref,"decision predecessor"),"target_binding_ref":exact_ref(target_binding_ref,"decision binding"),"disposition":disposition,"replacement_candidate_id":replacement_candidate_id}
    digest=hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return {**payload,"decision_id":f"review-decision/{digest}","content_sha256":digest}

def _validate_decision(raw:object,predecessor_ref:Mapping[str,str],allowed_bindings:set[bytes])->dict[str,object]:
    if not isinstance(raw,Mapping): raise ValueError("decision invalid")
    fields={"contract_version","decision_id","decision_type","predecessor_ref","target_binding_ref","disposition","replacement_candidate_id","content_sha256"}
    item=deepcopy(dict(raw))
    if set(item)!=fields or item["contract_version"]!="automatic_review_decision_v2" or item["decision_type"]!="candidate_review" or item["predecessor_ref"]!=predecessor_ref: raise ValueError("decision schema/type/predecessor invalid")
    if canonical_bytes(exact_ref(item["target_binding_ref"],"decision binding")) not in allowed_bindings: raise ValueError("decision binding is not in pre-review")
    if item["disposition"] not in {"accepted","corrected","rejected"} or (item["disposition"]=="corrected") != (isinstance(item["replacement_candidate_id"],str) and bool(item["replacement_candidate_id"])): raise ValueError("decision semantics invalid")
    payload={k:item[k] for k in ("contract_version","decision_type","predecessor_ref","target_binding_ref","disposition","replacement_candidate_id")}
    digest=hashlib.sha256(canonical_bytes(payload)).hexdigest()
    if item["content_sha256"]!=digest or item["decision_id"]!=f"review-decision/{digest}": raise ValueError("decision content identity invalid")
    return item

def _advance_review_record(value:dict[str,object],item:dict[str,object],expected_pre:Mapping[str,str])->None:
    value["decisions"].append(item)
    index=len(value["decisions"])
    value["post_review_ref"]={"id":f"post-review/{index}","content_sha256":hashlib.sha256(canonical_bytes({"pre_review_ref":expected_pre,"decisions":value["decisions"]})).hexdigest()}
    value["revision_ref"]={"id":f"prediction-revision/{index}","content_sha256":hashlib.sha256(canonical_bytes({k:v for k,v in value.items() if k!="revision_ref"})).hexdigest()}

def _validate_existing_record(record:Mapping[str,object],artifact:Mapping[str,object],expected_pre:Mapping[str,str])->dict[str,object]:
    fields={"contract_version","prediction_id","request_ref","pre_review_ref","execution_refs","lifecycle_ref","decisions","post_review_ref","safety","revision_ref"}
    if set(record)!=fields or record["contract_version"]!="automatic_prediction_record_v2" or record["prediction_id"]!=artifact["prediction_id"] or record["pre_review_ref"]!=expected_pre or record["safety"]!=SAFETY: raise ValueError("prediction record not closed")
    exact_ref(record["request_ref"],"request"); exact_ref(record["lifecycle_ref"],"lifecycle")
    if not isinstance(record["execution_refs"],list): raise ValueError("execution refs invalid")
    for item in record["execution_refs"]: exact_ref(item,"execution")
    allowed_bindings={canonical_bytes(row["target_binding_ref"]) for row in artifact["rows"] if row["selection_status"]=="selected"}
    current={k:deepcopy(v) for k,v in record.items() if k not in {"decisions","post_review_ref","revision_ref"}}
    current["decisions"]=[]; current["post_review_ref"]=deepcopy(expected_pre)
    current["revision_ref"]={"id":"prediction-revision/0","content_sha256":hashlib.sha256(canonical_bytes({k:v for k,v in current.items() if k!="revision_ref"})).hexdigest()}
    seen=set()
    raw_decisions=record["decisions"]
    if not isinstance(raw_decisions,list): raise ValueError("decision chain invalid")
    for index,raw in enumerate(raw_decisions,1):
        item=_validate_decision(raw,current["revision_ref"],allowed_bindings)
        if item["decision_id"] in seen: raise ValueError("duplicate decision identity")
        seen.add(item["decision_id"]); _advance_review_record(current,item,expected_pre)
    if current!=record: raise ValueError("existing prediction record derived state invalid")
    return current

def append_review_decisions(record:Mapping[str,object],decisions:list[Mapping[str,object]],*,pre_review_artifact_bytes:bytes,expected_pre_review_ref:Mapping[str,str],expected_record_ref:Mapping[str,str])->dict[str,object]:
    value=deepcopy(dict(record)); expected=exact_ref(expected_pre_review_ref,"expected pre-review")
    if prediction_record_ref(value)!=exact_ref(expected_record_ref,"expected record"): raise ValueError("external attempt record anchor mismatch")
    if value.get("pre_review_ref")!=expected or hashlib.sha256(pre_review_artifact_bytes).hexdigest()!=expected["content_sha256"]: raise ValueError("external pre-review anchor mismatch")
    artifact=json.loads(pre_review_artifact_bytes.decode("utf-8"))
    if canonical_bytes(artifact)!=pre_review_artifact_bytes or artifact_ref(artifact)!=expected: raise ValueError("pre-review CAS bytes invalid")
    artifact=_validate_pre(artifact)
    value=_validate_existing_record(value,artifact,expected)
    existing={d["decision_id"]:d for d in value["decisions"]}
    allowed_bindings={canonical_bytes(row["target_binding_ref"]) for row in artifact["rows"] if row["selection_status"]=="selected"}
    for raw in decisions:
        prior=existing.get(raw.get("decision_id")) if isinstance(raw,Mapping) else None
        item=_validate_decision(raw,prior["predecessor_ref"] if prior is not None else value["revision_ref"],allowed_bindings)
        if prior is not None:
            if prior!=item: raise ValueError("decision rewrite")
            continue
        _advance_review_record(value,item,expected); existing[item["decision_id"]]=item
    return _validate_existing_record(value,artifact,expected)
