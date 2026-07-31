from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.learn.application_identity import normalize_application_identity
from app.learn.interface_assets import (
    ASSET_ROOT,
    SINGLE_INTERFACE_ASSET_CONTRACT,
    build_single_interface_asset,
    save_single_interface_asset,
)


APPLICATION_INTERFACE_GRAPH_CONTRACT = "application_interface_graph_v1"
_ALLOWED_ACTION_TYPES = {
    "back",
    "click",
    "close_modal",
    "continue_next_step",
    "fill_field",
    "open_apply_flow",
    "open_detail",
    "open_filter",
    "open_link",
    "open_modal",
    "read",
    "scroll",
    "select",
    "select_option",
    "submit_search",
    "unknown_action",
    "wait",
}
_FINAL_ACTION_TYPES = {
    "confirm",
    "final_submit",
    "payment",
    "send",
}
_RUNTIME_GEOMETRY_KEYS = {
    "actual_point",
    "bbox",
    "click_point",
    "clickpoint",
    "confirmed_point",
    "normalized_bbox",
    "screen_point",
    "target_point",
}


def build_application_interface_graph(
    *,
    application_identity: dict[str, Any],
    interfaces: list[dict[str, Any]],
    entry_interface_id: str,
    transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    """把独立界面资产组织为软件级分支图，不授予执行权限。"""

    application = normalize_application_identity(application_identity)
    identity_key = str(application.get("identity_key") or "").strip()
    if application.get("identity_status") != "resolved" or not identity_key:
        raise ValueError("application interface graph requires resolved identity")
    if not isinstance(interfaces, list) or not interfaces:
        raise ValueError("application interface graph requires interfaces")

    interface_records: list[dict[str, Any]] = []
    assets_by_id: dict[str, dict[str, Any]] = {}
    controls_by_interface: dict[str, set[str]] = {}
    for raw in interfaces:
        asset = _validated_interface_asset(raw, identity_key=identity_key)
        interface_id = asset["interface_id"]
        if interface_id in assets_by_id:
            raise ValueError(f"duplicate interface asset: {interface_id}")
        assets_by_id[interface_id] = asset
        controls_by_interface[interface_id] = {
            str(item.get("control_id") or item.get("region_id") or "").strip()
            for item in [
                *(asset.get("controls") or []),
                *(asset.get("regions") or []),
            ]
            if isinstance(item, dict)
        }
        interface_records.append(
            {
                "interface_id": interface_id,
                "display_name": asset.get("display_name") or interface_id,
                "surface_type": asset.get("surface_type") or "unknown_surface",
                "state_signature": asset.get("state_signature") or interface_id,
                "evidence_status": asset.get("evidence_status") or "unknown",
                "review_status": (
                    asset.get("review", {}).get("status")
                    if isinstance(asset.get("review"), dict)
                    else "needs_human_review"
                ),
                "fixed_anchors": _without_runtime_geometry(
                    asset.get("fixed_anchors") or []
                ),
                "dynamic_slots": _without_runtime_geometry(
                    asset.get("dynamic_slots") or []
                ),
                "controls": _without_runtime_geometry(asset.get("controls") or []),
                "action_candidates": _without_runtime_geometry(
                    asset.get("action_candidates") or []
                ),
                "verification_rules": _without_runtime_geometry(
                    asset.get("verification_rules") or []
                ),
                "blockers": _without_runtime_geometry(asset.get("blockers") or []),
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )

    entry_id = str(entry_interface_id or "").strip()
    if entry_id not in assets_by_id:
        raise ValueError("application interface graph entry interface is unknown")
    normalized_transitions = [
        _validated_transition(
            raw,
            interface_ids=set(assets_by_id),
            controls_by_interface=controls_by_interface,
        )
        for raw in transitions
    ]
    transition_ids = [item["transition_id"] for item in normalized_transitions]
    if len(transition_ids) != len(set(transition_ids)):
        raise ValueError("application interface graph has duplicate transition ids")

    return {
        "contract_version": APPLICATION_INTERFACE_GRAPH_CONTRACT,
        "application_identity_key": identity_key,
        "application_identity": deepcopy(application),
        "entry_interface_id": entry_id,
        "interface_ids": sorted(assets_by_id),
        "interfaces": sorted(
            interface_records,
            key=lambda item: str(item["interface_id"]),
        ),
        "transitions": sorted(
            normalized_transitions,
            key=lambda item: str(item["transition_id"]),
        ),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "safety": {
            "current_capture_required": True,
            "fresh_grounding_required": True,
            "historical_coordinates_forbidden": True,
            "gate_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
        },
    }


def build_application_graph_agent_context(
    graph: dict[str, Any],
    *,
    interface_id: str,
) -> dict[str, Any]:
    """输出当前界面与可选路径，真实动作仍需重新识别并经过 Gate。"""

    normalized = _validated_graph(graph)
    current_id = str(interface_id or "").strip()
    current = next(
        (
            item
            for item in normalized["interfaces"]
            if item["interface_id"] == current_id
        ),
        None,
    )
    if current is None:
        raise ValueError(f"application graph interface not found: {current_id}")
    outgoing = [
        {
            **_without_runtime_geometry(item),
            "requires_fresh_grounding": True,
            "automatic_execution_allowed": False,
            "artifact_is_authorization": False,
        }
        for item in normalized["transitions"]
        if item["source_interface_id"] == current_id
    ]
    return {
        "contract_version": "application_interface_graph_agent_context_v1",
        "application_identity_key": normalized["application_identity_key"],
        "current_interface": _without_runtime_geometry(current),
        "outgoing_transitions": outgoing,
        "execution_contract": {
            "current_capture_required": True,
            "current_target_resolution_required": True,
            "historical_coordinates_forbidden": True,
            "gate_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def save_application_interface_graph(
    graph: dict[str, Any],
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    normalized = _validated_graph(graph)
    root = Path(project_root).resolve()
    app_dir = root / ASSET_ROOT / _safe_path_segment(
        normalized["application_identity_key"]
    )
    graph_path = app_dir / "graph.json"
    checksum_path = app_dir / "graph.sha256"
    content = _json_bytes(normalized)
    checksum = hashlib.sha256(content).hexdigest()
    _atomic_write(graph_path, content)
    _atomic_write(checksum_path, f"{checksum}\n".encode("ascii"))
    return {
        "contract_version": "application_interface_graph_save_result_v1",
        "status": "saved",
        "application_identity_key": normalized["application_identity_key"],
        "graph_path": graph_path.relative_to(root).as_posix(),
        "graph_sha256": checksum,
        "checksum_path": checksum_path.relative_to(root).as_posix(),
        "artifact_is_authorization": False,
    }


def load_application_interface_graph(
    application_identity_key: str,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    identity_key = str(application_identity_key or "").strip()
    if not identity_key:
        raise ValueError("application identity key is required")
    root = Path(project_root).resolve()
    app_dir = root / ASSET_ROOT / _safe_path_segment(identity_key)
    graph_path = app_dir / "graph.json"
    checksum_path = app_dir / "graph.sha256"
    if not graph_path.is_file() or not checksum_path.is_file():
        raise ValueError(f"application interface graph not found: {identity_key}")
    raw = graph_path.read_bytes()
    expected = checksum_path.read_text(encoding="ascii").strip().lower()
    actual = hashlib.sha256(raw).hexdigest()
    if expected != actual:
        raise ValueError("application interface graph checksum mismatch")
    payload = json.loads(raw.decode("utf-8-sig"))
    normalized = _validated_graph(payload)
    if normalized["application_identity_key"] != identity_key:
        raise ValueError("application interface graph identity mismatch")
    return normalized


def save_workflow_review_as_application_assets(
    review: dict[str, Any],
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    """把旧流程审核格式冻结为独立界面资产与软件级关系图。"""

    if (
        not isinstance(review, dict)
        or review.get("contract_version") != "single_application_workflow_review_v1"
    ):
        raise ValueError("workflow projection requires single application workflow review")
    workflow = review.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("workflow projection requires workflow metadata")
    application_identity = workflow.get("application_identity")
    if not isinstance(application_identity, dict):
        raise ValueError("workflow projection requires application identity")
    nodes = review.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("workflow projection requires interface nodes")

    assets = [
        build_single_interface_asset(
            node,
            application_identity=application_identity,
        )
        for node in nodes
        if isinstance(node, dict)
    ]
    save_results = [
        save_single_interface_asset(asset, project_root=project_root)
        for asset in assets
    ]
    valid_transitions: list[dict[str, Any]] = []
    invalid_transitions: list[dict[str, Any]] = []
    for raw in review.get("edges") or []:
        if not isinstance(raw, dict):
            invalid_transitions.append(
                {
                    "transition_id": "",
                    "failure_category": "invalid_transition",
                    "reason": "transition must be an object",
                }
            )
            continue
        transition = {
            "transition_id": raw.get("transition_id") or raw.get("edge_id"),
            "source_interface_id": raw.get("source_interface_id")
            or raw.get("source_node_id"),
            "target_interface_id": raw.get("target_interface_id")
            or raw.get("target_node_id"),
            "source_control_id": raw.get("source_control_id")
            or raw.get("target_control_id")
            or raw.get("target_region_id"),
            "action_type": raw.get("action_type") or "unknown_action",
            "display_name": raw.get("display_name"),
            "agent_description": raw.get("agent_description") or raw.get("description"),
            "risk_level": raw.get("risk_level") or "low",
            "review_status": raw.get("review_status") or "needs_human_review",
            "preconditions": raw.get("preconditions"),
            "success_conditions": raw.get("success_conditions"),
            "failure_conditions": raw.get("failure_conditions"),
        }
        try:
            valid_transitions.append(
                _validated_transition(
                    transition,
                    interface_ids={asset["interface_id"] for asset in assets},
                    controls_by_interface={
                        asset["interface_id"]: {
                            str(
                                item.get("control_id")
                                or item.get("region_id")
                                or ""
                            ).strip()
                            for item in [
                                *(asset.get("controls") or []),
                                *(asset.get("regions") or []),
                            ]
                            if isinstance(item, dict)
                        }
                        for asset in assets
                    },
                )
            )
        except ValueError as exc:
            invalid_transitions.append(
                {
                    "transition_id": str(
                        transition.get("transition_id") or ""
                    ),
                    "failure_category": "invalid_transition",
                    "reason": str(exc),
                }
            )

    entry_interface_id = str(
        workflow.get("entry_interface_id")
        or workflow.get("entry_node_id")
        or assets[0]["interface_id"]
    ).strip()
    graph = build_application_interface_graph(
        application_identity=application_identity,
        interfaces=assets,
        entry_interface_id=entry_interface_id,
        transitions=valid_transitions,
    )
    graph_result = save_application_interface_graph(
        graph,
        project_root=project_root,
    )
    from app.learn.agent_evidence import migrate_agent_evidence_assets

    agent_evidence_projection = migrate_agent_evidence_assets(
        project_root=project_root,
        application_identity_key=graph["application_identity_key"],
    )
    return {
        "contract_version": "workflow_review_asset_projection_result_v1",
        "status": "saved",
        "application_identity_key": graph["application_identity_key"],
        "saved_interface_count": len(save_results),
        "saved_transition_count": len(graph["transitions"]),
        "interface_results": save_results,
        "graph_result": graph_result,
        "agent_evidence_projection": agent_evidence_projection,
        "invalid_transitions": invalid_transitions,
        "artifact_is_authorization": False,
    }


def _validated_transition(
    value: Any,
    *,
    interface_ids: set[str],
    controls_by_interface: dict[str, set[str]],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("application interface transition must be an object")
    transition_id = _safe_identifier(value.get("transition_id"))
    source_id = str(value.get("source_interface_id") or "").strip()
    target_id = str(value.get("target_interface_id") or "").strip()
    control_id = str(value.get("source_control_id") or "").strip()
    action_type = str(value.get("action_type") or "").strip()
    risk_level = str(value.get("risk_level") or "low").strip().lower()
    review_status = str(
        value.get("review_status") or "needs_human_review"
    ).strip()
    if not transition_id:
        raise ValueError("application interface transition requires transition_id")
    if source_id not in interface_ids or target_id not in interface_ids:
        raise ValueError("application interface transition references unknown interface")
    if not control_id or control_id not in controls_by_interface[source_id]:
        raise ValueError("application interface transition source control is unknown")
    if action_type in _FINAL_ACTION_TYPES:
        raise ValueError(f"final action cannot be a learned transition: {action_type}")
    if action_type not in _ALLOWED_ACTION_TYPES:
        raise ValueError(f"unsupported transition action_type: {action_type}")
    if risk_level not in {"low", "medium", "high"}:
        raise ValueError("transition risk_level must be low, medium, or high")
    return {
        "transition_id": transition_id,
        "source_interface_id": source_id,
        "target_interface_id": target_id,
        "source_control_id": control_id,
        "action_type": action_type,
        "display_name": str(value.get("display_name") or action_type).strip(),
        "agent_description": str(value.get("agent_description") or "").strip(),
        "risk_level": risk_level,
        "review_status": review_status,
        "preconditions": _string_list(value.get("preconditions")),
        "success_conditions": _string_list(value.get("success_conditions")),
        "failure_conditions": _string_list(value.get("failure_conditions")),
        "requires_fresh_grounding": True,
        "requires_gate": True,
        "automatic_execution_allowed": False,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _validated_interface_asset(
    value: Any,
    *,
    identity_key: str,
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("contract_version") != SINGLE_INTERFACE_ASSET_CONTRACT
    ):
        raise ValueError("application graph requires single interface assets")
    asset = deepcopy(value)
    if asset.get("application_identity_key") != identity_key:
        raise ValueError("single interface asset application identity mismatch")
    interface_id = str(asset.get("interface_id") or "").strip()
    if not interface_id:
        raise ValueError("single interface asset requires interface_id")
    return asset


def _validated_graph(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("contract_version") != APPLICATION_INTERFACE_GRAPH_CONTRACT
    ):
        raise ValueError("application interface graph has an unsupported contract")
    application = value.get("application_identity")
    identity_key = str(value.get("application_identity_key") or "").strip()
    if not isinstance(application, dict) or application.get("identity_key") != identity_key:
        raise ValueError("application interface graph identity is inconsistent")
    interfaces = value.get("interfaces")
    transitions = value.get("transitions")
    if not isinstance(interfaces, list) or not isinstance(transitions, list):
        raise ValueError("application interface graph collections are invalid")
    interface_ids = {
        str(item.get("interface_id") or "")
        for item in interfaces
        if isinstance(item, dict)
    }
    if str(value.get("entry_interface_id") or "") not in interface_ids:
        raise ValueError("application interface graph entry interface is unknown")
    normalized = _without_runtime_geometry(value)
    normalized["display_only"] = True
    normalized["artifact_is_authorization"] = False
    normalized["execute_binding_enabled"] = False
    return normalized


def _without_runtime_geometry(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _without_runtime_geometry(item)
            for key, item in value.items()
            if str(key).replace("-", "_").casefold() not in _RUNTIME_GEOMETRY_KEYS
        }
    if isinstance(value, list):
        return [_without_runtime_geometry(item) for item in value]
    return deepcopy(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _safe_identifier(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return cleaned.strip("._-")[:96]


def _safe_path_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._-")
    if not cleaned:
        raise ValueError("application graph path segment is empty")
    return cleaned[:120]


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
