"""把已验证图修订直接投影到既有人审/编译格式。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def project_graph_exact_review(snapshot: dict[str, Any], application_identity: dict[str, Any], stop_node_ids: list[str], safe_actions: set[str], declarations: set[str]) -> dict[str, Any]:
    review = deepcopy(snapshot["graph"])
    if _has_stale_semantics(review):
        raise ValueError("unresolved_target_semantics")
    review["workflow"]["application_identity"] = deepcopy(application_identity)
    nodes = {item["node_id"]: item for item in review["nodes"]}
    for node in review["nodes"]:
        for region in node.get("regions", []):
            region.update(review_status="needs_human_review", reviewed_by_human=False,
                          display_only=True, artifact_is_authorization=False,
                          execute_binding_enabled=False)
        node["action_candidates"] = [
            action for action in node.get("action_candidates", [])
            if _declared(action) not in declarations
        ]
        if node["node_id"] in stop_node_ids:
            node["review_status"] = "needs_learning"
    edges = []
    for edge in review["edges"]:
        action = _declared(edge)
        if action in declarations:
            continue
        if action in safe_actions:
            edge.update(action_type=action, semantic_action=action, external_stop_boundary=False)
            source = nodes.get(edge.get("source_node_id"))
            if source is None:
                raise ValueError("graph edge source is missing")
            matching = [item for item in source.get("action_candidates", []) if item.get("external_step_id") == edge.get("external_step_id")]
            if not matching:
                candidate = _recorded_action_candidate(source, edge, action)
                if candidate is not None:
                    source.setdefault("action_candidates", []).append(candidate)
                    matching = [candidate]
            if len(matching) != 1:
                raise ValueError("graph action candidate binding is invalid")
            edge["action_template_id"] = matching[0]["action_template_id"]
            matching[0].update(semantic_action=action, action_type=action, target_node_id=edge["target_node_id"])
        else:
            edge.setdefault("blocked_reason", "unsafe_or_unknown_external_action")
        edges.append(edge)
    review["edges"] = edges
    review["workflow"]["edge_ids"] = [item["edge_id"] for item in edges]
    return review


def _recorded_action_candidate(source: dict[str, Any], edge: dict[str, Any], action: str) -> dict[str, Any] | None:
    """只适配有已核验事件来源的记录边，不改历史图或推断成功。"""
    event = edge.get("recorded_event")
    evidence = source.get("evidence", {})
    if not isinstance(event, dict) or evidence.get("external_source_kind") != "recorded_action":
        return None
    event_id = event.get("event_id")
    source_sha = event.get("source_sha256")
    region_id = edge.get("target_region_id")
    regions = [item for item in source.get("regions", []) if item.get("region_id") == region_id]
    if (not event_id or event_id != edge.get("external_step_id")
            or not source_sha or source_sha != evidence.get("source_sha256")
            or not region_id or edge.get("target_control_id") or len(regions) != 1):
        raise ValueError("recorded action candidate source binding is invalid")
    identity = edge["edge_id"] + ".action"
    return {
        "action_template_id": identity, "action_id": identity,
        "display_name": edge.get("display_name") or action,
        "external_step_id": event_id, "external_declared_action_type": action,
        "semantic_action": action, "action_type": action,
        "target_region_id": region_id, "target_control_id": "",
        "target_node_id": edge["target_node_id"],
        **{key: deepcopy(edge[key]) for key in (
            "scroll_parameters", "text_parameters", "text_parameters_ref") if key in edge},
        "expected_result": "\n".join(edge.get("success_conditions", [])),
        "stop_condition": "\n".join(edge.get("failure_conditions", [])),
        "review_status": "needs_human_review", "reviewed_by_human": False,
        "display_only": True, "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def graph_subjects(review: dict[str, Any], stop_node_ids: list[str]) -> list[dict[str, Any]]:
    identity = review["workflow"]["application_identity"]
    result = [_subject("application", "application", identity.get("display_name") or "Application", identity)]
    for node in review["nodes"]:
        node_id = node["node_id"]
        label = node.get("display_name") or node.get("external_interface_id") or node_id
        result.append(_subject(f"node:{node_id}", "node", label, node))
        result.append(_subject(f"observation:{node_id}", "observation", f"{label} observation", node.get("evidence", {})))
        for key, kind, id_key in (("regions", "region", "region_id"), ("controls", "control", "control_id"), ("action_candidates", "action", "action_template_id")):
            for item in node.get(key, []):
                identity_value = item[id_key]
                item_label = item.get("display_name") or item.get("semantic_name") or item.get("name") or item.get("label") or item.get("external_step_id") or identity_value
                result.append(_subject(f"{kind}:{node_id}:{identity_value}", kind, item_label, item))
    for edge in review["edges"]:
        edge_id = edge["edge_id"]
        result.append(_subject(f"edge:{edge_id}", "edge", edge.get("display_name") or edge.get("external_step_id") or edge_id, edge))
        for relationship in edge.get("external_relationships", []):
            relationship_id = relationship["relationship_id"]
            result.append(_subject(f"relationship:{edge_id}:{relationship_id}", "relationship", relationship.get("kind") or relationship_id, relationship))
    for node_id in stop_node_ids:
        result.append(_subject(f"stop:{node_id}", "stop", node_id, {"node_id": node_id}))
    return result


def _subject(subject_id: str, kind: str, label: Any, content: Any) -> dict[str, Any]:
    return {"subject_id": subject_id, "kind": kind, "label": str(label), "content": deepcopy(content), "confirmed": False}


def _declared(value: dict[str, Any]) -> str:
    return str(value.get("external_declared_action_type") or value.get("action_type") or "").strip().casefold()


def _has_stale_semantics(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("target_semantics_status") == "stale_after_retarget" or value.get("requires_semantic_review") is True:
            return True
        return any(_has_stale_semantics(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_stale_semantics(item) for item in value)
    return False
