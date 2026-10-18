"""图基线候选共用的纯 scope 与操作校验。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any


class GraphContractError(ValueError):
    pass


_LOGICAL_ID = re.compile(r"workflow-[0-9a-f]{64}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def validate_graph_scope(value: Any, graph: dict[str, Any]) -> dict[str, list[str]]:
    if not isinstance(value, dict) or set(value) != {"node_ids", "edge_ids"}:
        raise GraphContractError("graph scope is invalid")
    result: dict[str, list[str]] = {}
    for key, collection, identity in (
        ("node_ids", graph.get("nodes"), "node_id"),
        ("edge_ids", graph.get("edges"), "edge_id"),
    ):
        values = value[key]
        if not isinstance(values, list) or len(values) > 256 or any(not isinstance(item, str) or not item or len(item) > 512 for item in values) or len(values) != len(set(values)):
            raise GraphContractError("graph scope is invalid")
        known = {item.get(identity) for item in collection if isinstance(item, dict)} if isinstance(collection, list) else set()
        if not set(values) <= known:
            raise GraphContractError("graph scope reference is invalid")
        result[key] = list(values)
    if not result["node_ids"] and not result["edge_ids"]:
        raise GraphContractError("graph scope is empty")
    return result


def graph_issue_id(*, logical_workflow_id: str, graph_revision: int, graph_sha256: str, feedback_revision: int, scope: dict[str, list[str]], message: str) -> str:
    payload = {
        "logical_workflow_id": logical_workflow_id, "expected_revision": graph_revision,
        "expected_graph_sha256": graph_sha256,
        "expected_feedback_revision": feedback_revision,
        "scope": deepcopy(scope), "message": message,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "graph-issue-" + hashlib.sha256(encoded).hexdigest()


def validate_graph_operations(value: Any, graph: dict[str, Any], scope: dict[str, list[str]]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 128:
        raise GraphContractError("graph operations are invalid")
    checked = []
    writes: set[tuple[str, str]] = set()
    for operation in value:
        if not isinstance(operation, dict) or not isinstance(operation.get("type"), str):
            raise GraphContractError("graph operation is invalid")
        kind = operation["type"]
        if kind == "update_edge_target":
            _exact(operation, {"type", "edge_id", "target_node_id"})
            edge = _edge(graph, operation["edge_id"])
            _scoped(scope, "edge_ids", edge["edge_id"])
            _node(graph, operation["target_node_id"])
            key = ("edge_target", edge["edge_id"])
        elif kind == "update_region_bbox":
            _exact(operation, {"type", "node_id", "region_id", "bbox"})
            node = _node(graph, operation["node_id"])
            _scoped(scope, "node_ids", node["node_id"])
            _region(node, operation["region_id"])
            _bbox(operation["bbox"])
            key = ("node_bbox", node["node_id"] + "\0" + operation["region_id"])
        elif kind == "update_node_meaning":
            _exact(operation, {"type", "node_id", "meaning"})
            node = _node(graph, operation["node_id"])
            _scoped(scope, "node_ids", node["node_id"])
            _text(operation["meaning"])
            key = ("node_meaning", node["node_id"])
        elif kind == "update_node_recognition_text":
            _exact(operation, {"type", "node_id", "recognition_text", "source_screenshot_path",
                               "source_screenshot_sha256", "bbox"})
            node = _node(graph, operation["node_id"])
            _scoped(scope, "node_ids", node["node_id"])
            _recognition_binding(node, operation)
            key = ("node_recognition", node["node_id"])
        elif kind == "update_edge_semantics":
            _exact(operation, {"type", "edge_id", "expected_result", "stop_condition", "prerequisites", "relationship_kinds"})
            edge = _edge(graph, operation["edge_id"])
            _scoped(scope, "edge_ids", edge["edge_id"])
            _text(operation["expected_result"]); _text(operation["stop_condition"])
            if not isinstance(operation["prerequisites"], list) or len(operation["prerequisites"]) > 64:
                raise GraphContractError("edge prerequisites are invalid")
            for item in operation["prerequisites"]: _text(item)
            relations = edge.get("external_relationships", [])
            if not isinstance(relations, list) or not isinstance(operation["relationship_kinds"], dict) or set(operation["relationship_kinds"]) != {item.get("relationship_id") for item in relations if isinstance(item, dict)}:
                raise GraphContractError("relationship kinds are invalid")
            for item in operation["relationship_kinds"].values(): _text(item)
            key = ("edge_semantics", edge["edge_id"])
        else:
            raise GraphContractError("graph operation is unsupported")
        if key in writes: raise GraphContractError("graph operation writes conflict")
        writes.add(key); checked.append(deepcopy(operation))
    return checked


def apply_graph_operations(graph: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    result = deepcopy(graph)
    for operation in operations:
        if operation["type"] == "update_edge_target":
            edge = _edge(result, operation["edge_id"])
            target = _node(result, operation["target_node_id"])
            changed = edge.get("target_node_id") != target["node_id"]
            edge["target_node_id"] = target["node_id"]
            for relation in edge.get("external_relationships", []):
                relation["to_interface_id"] = target.get("external_interface_id")
                if changed: _stale(relation)
            for node in result.get("nodes", []):
                for action in node.get("action_candidates", []) if isinstance(node, dict) else []:
                    if action.get("external_step_id") == edge.get("external_step_id"):
                        action["target_node_id"] = target["node_id"]
                        if changed: _stale(action)
            if changed: _stale(edge)
        elif operation["type"] == "update_region_bbox":
            node = _node(result, operation["node_id"])
            _region(node, operation["region_id"])["bbox"] = deepcopy(operation["bbox"])
            for control in node.get("controls", []):
                if control.get("region_id") == operation["region_id"] or control.get("control_id") == operation["region_id"]:
                    control["bbox"] = deepcopy(operation["bbox"])
        elif operation["type"] == "update_node_meaning":
            node = _node(result, operation["node_id"]); meaning = operation["meaning"]
            node["display_name"] = meaning; node["agent_description"] = meaning
            screen = node.get("page_details", {}).get("screen")
            if isinstance(screen, dict): screen["summary"] = meaning
        elif operation["type"] == "update_node_recognition_text":
            node = _node(result, operation["node_id"])
            node["recognition_text"] = operation["recognition_text"]
            node["recognition_anchor"] = {
                "contract_version": "graph_node_recognition_anchor_v1",
                "node_id": node["node_id"], "text": operation["recognition_text"],
                **{key: deepcopy(operation[key]) for key in (
                    "source_screenshot_path", "source_screenshot_sha256", "bbox")},
            }
        else:
            edge = _edge(result, operation["edge_id"])
            edge["success_conditions"] = [operation["expected_result"]]
            edge["failure_conditions"] = [operation["stop_condition"]]
            edge["preconditions"] = deepcopy(operation["prerequisites"])
            edge.pop("target_semantics_status", None); edge.pop("requires_semantic_review", None)
            for relation in edge.get("external_relationships", []):
                relation["kind"] = operation["relationship_kinds"][relation["relationship_id"]]
                relation.pop("target_semantics_status", None); relation.pop("requires_semantic_review", None)
            for node in result.get("nodes", []):
                for action in node.get("action_candidates", []) if isinstance(node, dict) else []:
                    if action.get("external_step_id") == edge.get("external_step_id"):
                        action["expected_result"] = operation["expected_result"]
                        action["stop_condition"] = operation["stop_condition"]
                        action.pop("target_semantics_status", None); action.pop("requires_semantic_review", None)
    return result


def _recognition_binding(node: dict[str, Any], operation: dict[str, Any]) -> None:
    _text(operation["recognition_text"])
    _bbox(operation["bbox"])
    evidence = node.get("evidence")
    if (not isinstance(evidence, dict)
            or operation["node_id"] != node["node_id"]
            or not isinstance(operation["source_screenshot_path"], str)
            or not operation["source_screenshot_path"]
            or not isinstance(operation["source_screenshot_sha256"], str)
            or not _SHA256.fullmatch(operation["source_screenshot_sha256"])
            or any(operation[key] != evidence.get(key) for key in (
                "source_screenshot_path", "source_screenshot_sha256"))):
        raise GraphContractError("recognition anchor source binding is invalid")


def validate_node_recognition_anchor(node: dict[str, Any]) -> None:
    """新增显式锚点必须与节点、文字和原图一致；保留旧输入合同。"""
    if "recognition_anchor" not in node:
        return
    anchor = node["recognition_anchor"]
    if not isinstance(anchor, dict):
        raise GraphContractError("recognition anchor is invalid")
    _exact(anchor, {"contract_version", "node_id", "text", "source_screenshot_path",
                    "source_screenshot_sha256", "bbox"})
    if (anchor["contract_version"] != "graph_node_recognition_anchor_v1"
            or anchor["text"] != node.get("recognition_text")):
        raise GraphContractError("recognition anchor text binding is invalid")
    _recognition_binding(node, {**anchor, "recognition_text": anchor["text"]})


def validate_graph_baseline(value: Any, *, task_id: str, batch_id: str, original_batch_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """校验 AgentLink 可独立复核的不可变图修订基线。"""
    fields = {"contract_version", "task_id", "batch_id", "logical_workflow_id", "revision", "graph_sha256", "snapshot"}
    if not isinstance(value, dict) or set(value) != fields or value.get("contract_version") != "desktop_graph_review_baseline_v1":
        raise GraphContractError("graph baseline is invalid")
    snapshot = value.get("snapshot")
    required = {"contract_version", "logical_workflow_id", "revision", "content_sha256", "parent_sha256", "source_refs", "graph", "change"}
    if not isinstance(snapshot, dict) or set(snapshot) != required or snapshot.get("contract_version") != "formal_graph_revision_v1":
        raise GraphContractError("graph baseline snapshot is invalid")
    content = deepcopy(snapshot); digest = content.pop("content_sha256", None)
    try:
        calculated = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise GraphContractError("graph baseline snapshot is not canonical JSON") from error
    graph = snapshot.get("graph")
    refs = snapshot.get("source_refs")
    if not isinstance(graph, dict) or not isinstance(refs, dict):
        raise GraphContractError("graph baseline binding is invalid")
    source = graph.get("source")
    if not isinstance(source, dict):
        raise GraphContractError("graph baseline binding is invalid")
    if any((not isinstance(value.get("logical_workflow_id"), str), not _LOGICAL_ID.fullmatch(value.get("logical_workflow_id", "")),
            type(value.get("revision")) is not int, value.get("revision", 0) < 1,
            not isinstance(digest, str), not _SHA256.fullmatch(digest or ""),
            value.get("task_id") != task_id, value.get("batch_id") != batch_id,
            value.get("logical_workflow_id") != snapshot.get("logical_workflow_id"),
            value.get("revision") != snapshot.get("revision"), value.get("graph_sha256") != digest,
            digest != calculated, refs.get("task_id") != task_id,
            refs.get("batch_id") != batch_id, refs.get("batch_sha256") != original_batch_sha256,
            source.get("kind") != "untrusted_external", source.get("task_id") != task_id,
            source.get("batch_id") != batch_id, source.get("batch_sha256") != original_batch_sha256,
            graph.get("display_only") is not True, graph.get("artifact_is_authorization") is not False,
            graph.get("execute_binding_enabled") is not False,
            not isinstance(graph.get("nodes"), list), not isinstance(graph.get("edges"), list))):
        raise GraphContractError("graph baseline binding is invalid")
    node_ids = [item.get("node_id") for item in graph["nodes"] if isinstance(item, dict)]
    edge_ids = [item.get("edge_id") for item in graph["edges"] if isinstance(item, dict)]
    if len(node_ids) != len(graph["nodes"]) or len(edge_ids) != len(graph["edges"]) or len(set(node_ids)) != len(node_ids) or len(set(edge_ids)) != len(edge_ids):
        raise GraphContractError("graph baseline identities are invalid")
    return deepcopy(value), deepcopy(snapshot)


def _exact(value: dict[str, Any], fields: set[str]) -> None:
    if set(value) != fields: raise GraphContractError("graph operation fields are invalid")

def _text(value: Any) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000: raise GraphContractError("graph operation text is invalid")

def _scoped(scope: dict[str, list[str]], key: str, value: str) -> None:
    if value not in scope[key]: raise GraphContractError("graph operation is outside scope")

def _node(graph: dict[str, Any], identity: Any) -> dict[str, Any]:
    found = [item for item in graph.get("nodes", []) if isinstance(item, dict) and item.get("node_id") == identity]
    if len(found) != 1: raise GraphContractError("graph node is invalid")
    return found[0]

def _edge(graph: dict[str, Any], identity: Any) -> dict[str, Any]:
    found = [item for item in graph.get("edges", []) if isinstance(item, dict) and item.get("edge_id") == identity]
    if len(found) != 1: raise GraphContractError("graph edge is invalid")
    return found[0]

def _region(node: dict[str, Any], identity: Any) -> dict[str, Any]:
    found = [item for item in node.get("regions", []) if isinstance(item, dict) and item.get("region_id") == identity]
    if len(found) != 1: raise GraphContractError("graph region is invalid")
    return found[0]

def _bbox(value: Any) -> None:
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in value):
        raise GraphContractError("graph bbox is invalid")
    if value[0] < 0 or value[1] < 0 or value[2] <= 0 or value[3] <= 0: raise GraphContractError("graph bbox is invalid")

def _stale(value: dict[str, Any]) -> None:
    value["target_semantics_status"] = "stale_after_retarget"
    value["requires_semantic_review"] = True
