"""Sealed public evidence contracts for Benchmark-v2 automatic predictions."""
from __future__ import annotations
import base64
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

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


def _provider_case_index(corpus: Mapping[str, object]) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, str]], str]:
    from app.learn.hybrid.benchmark_v2_contracts import ARM_ORDER
    from app.learn.recognition.uei.canonical import content_sha256

    cases = corpus.get("cases")
    if not isinstance(cases, list):
        raise ValueError("provider corpus cases are unavailable")
    regression = [deepcopy(dict(item)) for item in cases if isinstance(item, Mapping) and item.get("partition") == "regression"]
    if len(regression) != 60:
        raise ValueError("provider corpus regression partition must contain 60 cases")
    by_id: dict[str, dict[str, object]] = {}
    context: dict[str, dict[str, str]] = {}
    multiset: list[dict[str, str]] = []
    groups: dict[str, int] = {}
    for case in regression:
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
    vista_proposals: list[Mapping[str, object]] = []
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
            review = observation.get("review_projection")
            proposals = review.get("proposals") if isinstance(review, Mapping) else None
            if not isinstance(proposals, list):
                raise ValueError("actual screen group VISTA proposals are invalid")
            vista_proposals = proposals
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
        attached = attach_vista_outcomes(selection, list(vista_proposals))
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
        "raw_ledger_prefix_verification_ref",
        "selected_lifecycle_ref",
    ):
        add(f"{outer_version}.{field}", prediction_run[field])
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
    from app.learn.hybrid.benchmark_v2_lifecycle import _s13_public_attempt_ref

    body = _parse_actual_body_bytes(actual_body_bytes)
    _, corpus, manifest_ref, corpus_ref = _parse_provider_inputs(
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    provider_cases, case_context, corpus_digest = _provider_case_index(corpus)
    if not isinstance(actual_body_verified_projection, Mapping):
        raise ValueError("actual body verified projection is required")
    body_projection_ref = pathless_artifact_ref(actual_body_verified_projection)
    raw_attempt_ref = body.get("attempt_ref")
    if not isinstance(raw_attempt_ref, Mapping):
        raise ValueError("actual body attempt ref is invalid")
    public_attempt_ref = _s13_public_attempt_ref(raw_attempt_ref)
    if (
        actual_body_verified_projection.get("contract_version")
        != "benchmark_v2_actual_body_verified_projection_v1"
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
        or lifecycle_bundle_v3.get("partition") != "regression"
        or lifecycle_bundle_v3.get("attempt_ref") != public_attempt_ref
    ):
        raise ValueError("lifecycle bundle lineage differs")
    lifecycle_envelopes = lifecycle_bundle_v3.get("sealed_artifact_envelopes")
    if not isinstance(lifecycle_envelopes, list):
        raise ValueError("lifecycle bundle closure is unavailable")
    runner_and_ledger_envelopes: list[dict[str, object]] = []
    runner_events: list[dict[str, object]] = []
    ledger: dict[str, object] | None = None
    for envelope in lifecycle_envelopes:
        decoded, _ = _decode_canonical_envelope(envelope, name="lifecycle child")
        version = decoded.get("contract_version")
        if version in {
            "benchmark_v2_runner_event_verified_projection_v1",
            "benchmark_v2_projected_attempt_ledger_v1",
        }:
            pathless_artifact_ref(decoded)
            runner_and_ledger_envelopes.append(deepcopy(dict(envelope)))
            if version == "benchmark_v2_runner_event_verified_projection_v1":
                runner_events.append(decoded)
            elif version == "benchmark_v2_projected_attempt_ledger_v1":
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
        partition="regression",
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
            "partition": "regression",
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
