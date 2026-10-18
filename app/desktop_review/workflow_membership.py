"""只读界面内容与图草稿的受限组合。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import uuid
from typing import Any

from .graph_revision import GraphRevisionService, DesktopReviewError, canonical_json_bytes, _revision, _sha, _key


def _id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise DesktopReviewError(f"{name} 无效")
    return value


class WorkflowMembershipService:
    def __init__(self, facade: Any) -> None:
        self.facade = facade
        self.graphs = GraphRevisionService(facade)

    def list_workflow_graphs(self) -> list[dict[str, Any]]:
        root = self.graphs._root
        result = []
        if not root.exists():
            return result
        for head in sorted(root.glob("*/draft_head.json")):
            logical = head.parent.name
            snapshot = self.graphs.load(logical, None)
            graph = snapshot["graph"]
            result.append({
                "logical_workflow_id": logical,
                "title": graph.get("workflow", {}).get("goal", logical),
                "task_id": snapshot["source_refs"].get("task_id"),
                "revision": snapshot["revision"],
                "content_sha256": snapshot["content_sha256"],
                "node_count": len(graph.get("nodes", [])),
            })
        return result

    def create_workflow_graph(self, *, title: str, task_id: str) -> dict[str, Any]:
        title, task_id = _id(title, "title"), _id(task_id, "task_id")
        logical = "workflow-" + hashlib.sha256(canonical_json_bytes({"title": title, "task_id": task_id, "nonce": uuid.uuid4().hex})).hexdigest()
        refs = {"kind": "interface_composition", "task_id": task_id, "interfaces": []}
        graph = {"display_only": True, "artifact_is_authorization": False, "execute_binding_enabled": False,
                 "workflow": {"workflow_id": logical, "goal": title, "node_ids": [], "edge_ids": []},
                 "nodes": [], "edges": [], "source": {"kind": "interface_composition", "task_id": task_id},
                 "invalid_sources": []}
        snapshot = self.graphs._snapshot(logical_id=logical, revision=1, parent_sha256=None,
                                         source_refs=refs, graph=graph, idempotency_key=None, request_sha256=None)
        self.graphs._write_committed(snapshot)
        return self.graphs.load(logical, None)

    def _change(self, *, workflow_id: str, interface_id: str, version_id: str,
                expected_revision: int, expected_sha256: str, idempotency_key: str,
                detach: bool) -> dict[str, Any]:
        logical = self.graphs._validate_logical_id(workflow_id)
        expected_revision = _revision(expected_revision, "expected_revision", allow_zero=False)
        expected_sha256 = _sha(expected_sha256, "expected_sha256")
        current = self.graphs.load(logical, None)
        content = self.facade.load_interface_content(interface_id, version_id)
        if content.get("interface_id") != interface_id or content.get("version_id") != version_id:
            raise DesktopReviewError("界面版本身份不一致")
        graph_task = current["source_refs"].get("task_id")
        if content.get("source", {}).get("task_id") != graph_task:
            raise DesktopReviewError("界面内容与目标图 task 不一致")
        ref = {"interface_id": interface_id, "version_id": version_id,
               "content_sha256": content.get("content_sha256")}
        if not isinstance(ref["content_sha256"], str) or not ref["content_sha256"]:
            raise DesktopReviewError("界面内容摘要无效")
        key = _key(idempotency_key, "idempotency_key")
        request_sha = membership_request_sha(logical, expected_revision, expected_sha256, ref, detach)
        duplicate = self.graphs._find_idempotency(current, key, request_sha)
        if duplicate is not None:
            return duplicate
        if current["revision"] != expected_revision or current["content_sha256"] != expected_sha256:
            raise DesktopReviewError("stale_revision: 图草稿修订或内容摘要已过期")
        refs = current["source_refs"].setdefault("interfaces" if current["source_refs"].get("kind") == "interface_composition" else "interface_composition", [])
        exists = [item for item in refs if item["interface_id"] == interface_id and item["version_id"] == version_id]
        if detach:
            if not exists:
                raise DesktopReviewError("界面版本未附加")
            refs[:] = [item for item in refs if item != ref]
            removed = {item["node_id"] for item in current["graph"]["nodes"] if item.get("interface_reference") == ref}
            current["graph"]["nodes"] = [item for item in current["graph"]["nodes"] if item.get("node_id") not in removed]
            current["graph"]["workflow"]["node_ids"] = [item for item in current["graph"]["workflow"]["node_ids"] if item not in removed]
            current["graph"]["edges"] = [item for item in current["graph"]["edges"] if item.get("source_node_id") not in removed and item.get("target_node_id") not in removed]
        else:
            if exists:
                raise DesktopReviewError("该界面版本已经加入流程；无需重复加入")
            refs.append(ref)
            node = reference_node(self.facade, ref, graph_task)
            current["graph"]["nodes"].append(node)
            current["graph"]["workflow"]["node_ids"].append(node["node_id"])
        current["graph"]["workflow"]["edge_ids"] = [edge["edge_id"] for edge in current["graph"].get("edges", [])]
        snapshot = self.graphs._snapshot(logical_id=logical, revision=current["revision"] + 1, parent_sha256=current["content_sha256"], source_refs=current["source_refs"], graph=current["graph"], idempotency_key=key, request_sha256=request_sha, interface_append={"interface_id": interface_id, "version_id": version_id, "content_sha256": ref["content_sha256"], "detach": detach})
        self.graphs._write_committed(snapshot)
        return self.graphs.load(logical, None)

    def attach_interface_to_workflow(self, **kwargs: Any) -> dict[str, Any]:
        return self._change(detach=False, **kwargs)

    def attach_interfaces_to_workflow(self, *, workflow_id: str, interfaces: list[dict[str, Any]],
                                      expected_revision: int, expected_sha256: str,
                                      idempotency_key: str) -> dict[str, Any]:
        """单个图修订内原子加入多个已保存界面，不生成跳转。"""

        logical = self.graphs._validate_logical_id(workflow_id)
        expected_revision = _revision(expected_revision, "expected_revision", allow_zero=False)
        expected_sha256 = _sha(expected_sha256, "expected_sha256")
        key = _key(idempotency_key, "idempotency_key")
        current = self.graphs.load(logical, None)
        refs = _batch_refs(self.facade, interfaces, current["source_refs"].get("task_id"))
        request_sha = membership_batch_request_sha(logical, expected_revision, expected_sha256, refs)
        duplicate = self.graphs._find_idempotency(current, key, request_sha)
        if duplicate is not None:
            return duplicate
        if current["revision"] != expected_revision or current["content_sha256"] != expected_sha256:
            raise DesktopReviewError("stale_revision: 图草稿修订或内容摘要已过期")
        _assert_current_interface_refs(self.facade, refs)
        refs_key = "interfaces" if current["source_refs"].get("kind") == "interface_composition" else "interface_composition"
        source_refs = deepcopy(current["source_refs"])
        existing = source_refs.setdefault(refs_key, [])
        if not isinstance(existing, list):
            raise DesktopReviewError("interface_batch_existing_refs_invalid")
        existing_ids = {item.get("interface_id") for item in existing if isinstance(item, dict)}
        if len(existing_ids) != len(existing) or any(not isinstance(item, str) for item in existing_ids):
            raise DesktopReviewError("interface_batch_existing_refs_invalid")
        if len(existing) + len(refs) > 256:
            raise DesktopReviewError("interface_batch_limit_exceeded")
        if any(ref["interface_id"] in existing_ids for ref in refs):
            raise DesktopReviewError("interface_batch_already_attached")
        graph = deepcopy(current["graph"])
        nodes = [reference_node(self.facade, ref, source_refs["task_id"]) for ref in refs]
        node_ids = [item["node_id"] for item in nodes]
        if len(node_ids) != len(set(node_ids)) or any(item["node_id"] in graph["workflow"]["node_ids"] for item in nodes):
            raise DesktopReviewError("interface_batch_node_duplicate")
        existing.extend(deepcopy(refs))
        graph["nodes"].extend(nodes)
        graph["workflow"]["node_ids"].extend(node_ids)
        graph["workflow"]["edge_ids"] = [edge["edge_id"] for edge in graph.get("edges", [])]
        snapshot = self.graphs._snapshot(
            logical_id=logical, revision=current["revision"] + 1,
            parent_sha256=current["content_sha256"], source_refs=source_refs, graph=graph,
            idempotency_key=key, request_sha256=request_sha, interface_batch=refs,
        )
        self.graphs._write_committed(snapshot)
        return self.graphs.load(logical, None)

    def detach_interface_from_workflow(self, **kwargs: Any) -> dict[str, Any]:
        return self._change(detach=True, **kwargs)

    def request_interface_membership(self, *, allowed_task_id: str, **kwargs: Any) -> dict[str, Any]:
        task = _id(allowed_task_id, "allowed_task_id")
        logical = _id(kwargs["workflow_id"], "workflow_id")
        current = self.graphs.load(logical, None)
        if current["source_refs"].get("task_id") != task:
            raise DesktopReviewError("目标图不属于允许的 task")
        content = self.facade.load_interface_content(kwargs["interface_id"], kwargs["version_id"])
        if content.get("source", {}).get("task_id") != task:
            raise DesktopReviewError("界面内容不属于允许的 task")
        snapshot = self.attach_interface_to_workflow(**kwargs)
        ref = {"workflow_id": logical, "revision": snapshot["revision"], "content_sha256": snapshot["content_sha256"], "interface_id": kwargs["interface_id"], "version_id": kwargs["version_id"], "status": "saved", "review_required": False, "artifact_is_authorization": False, "execute_binding_enabled": False}
        return ref


def membership_request_sha(logical: str, revision: int, digest: str, ref: dict, detach: bool) -> str:
    return hashlib.sha256(canonical_json_bytes({
        "workflow_id": logical, "expected_revision": revision,
        "parent_sha256": digest, "ref": ref, "detach": detach,
    })).hexdigest()


def membership_batch_request_sha(logical: str, revision: int, digest: str, refs: list[dict]) -> str:
    return hashlib.sha256(canonical_json_bytes({
        "workflow_id": logical, "expected_revision": revision,
        "parent_sha256": digest, "interfaces": refs,
    })).hexdigest()


def _batch_refs(facade: Any, value: Any, task_id: Any) -> list[dict]:
    if not isinstance(value, list) or not value or len(value) > 256:
        raise DesktopReviewError("interface_batch_invalid")
    if not isinstance(task_id, str) or not task_id:
        raise DesktopReviewError("interface_batch_task_invalid")
    refs, identities = [], set()
    for item in value:
        ref = _interface_ref(item)
        if ref["interface_id"] in identities:
            raise DesktopReviewError("interface_batch_duplicate_interface")
        identities.add(ref["interface_id"])
        content = facade.load_interface_content(ref["interface_id"], ref["version_id"])
        if any(content.get(key) != ref[key] for key in ref):
            raise DesktopReviewError("interface_batch_identity_invalid")
        if content.get("source", {}).get("task_id") != task_id:
            raise DesktopReviewError("interface_batch_task_invalid")
        refs.append(ref)
    return refs


def _assert_current_interface_refs(facade: Any, refs: list[dict]) -> None:
    for ref in refs:
        latest = facade.load_interface_content(ref["interface_id"])
        if latest.get("version_id") != ref["version_id"] or latest.get("content_sha256") != ref["content_sha256"]:
            raise DesktopReviewError("stale_interface: 界面不是当前最新保存版本")


def _interface_ref(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != {"interface_id", "version_id", "content_sha256"}:
        raise DesktopReviewError("interface_batch_identity_invalid")
    return {
        "interface_id": _id(value["interface_id"], "interface_id"),
        "version_id": _id(value["version_id"], "version_id"),
        "content_sha256": _sha(value["content_sha256"], "content_sha256"),
    }


def reference_node(facade: Any, ref: dict, task_id: str) -> dict:
    if not isinstance(ref, dict) or set(ref) != {"interface_id", "version_id", "content_sha256"}:
        raise DesktopReviewError("界面组合引用字段无效")
    content = facade.load_interface_content(ref["interface_id"], ref["version_id"])
    if (content["source"]["task_id"] != task_id
            or any(content[key] != ref[key] for key in ref)):
        raise DesktopReviewError("界面组合引用身份、来源或摘要不一致")
    evidence = facade.load_interface_content_evidence(ref["interface_id"], ref["version_id"])
    value = content["content"]
    return {
        "node_id": "interface-" + hashlib.sha256(canonical_json_bytes(ref)).hexdigest(),
        "display_name": value["meaning"], "agent_description": value["meaning"],
        "external_interface_id": content["source"]["external_interface_id"],
        "interface_reference": deepcopy(ref), "interface_evidence": evidence,
        "evidence": {"source_screenshot_path": evidence["image_path"],
                     "source_screenshot_id": content["source"]["screenshot_id"],
                     "source_screenshot_sha256": evidence["sha256"]},
        "regions": deepcopy(value["regions"]), "controls": [], "action_candidates": [],
        **({"recognition_text": value["recognition_text"]} if "recognition_text" in value else {}),
        "review_status": "needs_review", "display_only": True,
        "artifact_is_authorization": False, "execute_binding_enabled": False,
    }


def validate_reference_projection(facade: Any, graph: dict, refs: dict) -> None:
    composition = refs.get("kind") == "interface_composition"
    values = refs.get("interfaces" if composition else "interface_composition", [])
    if not isinstance(values, list) or len(values) > 256:
        raise DesktopReviewError("界面组合引用列表无效")
    expected = [reference_node(facade, ref, refs["task_id"]) for ref in values]
    identities = [node["node_id"] for node in expected]
    if len(identities) != len(set(identities)):
        raise DesktopReviewError("界面组合引用重复")
    actual = [node for node in graph["nodes"] if "interface_reference" in node]
    if actual != expected:
        raise DesktopReviewError("图内界面必须等于所引用的精确版本，不能修改副本")
    if composition and (len(graph["nodes"]) != len(expected) or graph["edges"]):
        raise DesktopReviewError("独立界面组合尚无学习到的跳转证据，不能伪造连线")


def validate_membership_change(facade: Any, parent: dict, child: dict) -> None:
    change = child["change"]["interface_append"]
    if (not isinstance(change, dict)
            or set(change) != {"interface_id", "version_id", "content_sha256", "detach"}
            or type(change["detach"]) is not bool):
        raise DesktopReviewError("界面组合变更元数据无效")
    ref = {key: value for key, value in change.items() if key != "detach"}
    expected_refs, expected_graph = deepcopy(parent["source_refs"]), deepcopy(parent["graph"])
    key = "interfaces" if expected_refs.get("kind") == "interface_composition" else "interface_composition"
    values = expected_refs.setdefault(key, [])
    node = reference_node(facade, ref, expected_refs["task_id"])
    if change["detach"]:
        if ref not in values:
            raise DesktopReviewError("移除的界面版本未在父修订登记")
        values.remove(ref)
        expected_graph["nodes"] = [item for item in expected_graph["nodes"] if item["node_id"] != node["node_id"]]
        expected_graph["edges"] = [item for item in expected_graph["edges"]
            if item.get("source_node_id") != node["node_id"] and item.get("target_node_id") != node["node_id"]]
    else:
        if ref in values:
            raise DesktopReviewError("重复的界面版本加入变更")
        values.append(ref)
        expected_graph["nodes"].append(node)
    expected_graph["workflow"]["node_ids"] = [item["node_id"] for item in expected_graph["nodes"]]
    expected_graph["workflow"]["edge_ids"] = [item["edge_id"] for item in expected_graph["edges"]]
    digest = membership_request_sha(parent["logical_workflow_id"], parent["revision"], parent["content_sha256"], ref, change["detach"])
    if (expected_refs != child["source_refs"] or expected_graph != child["graph"]
            or child["change"]["request_sha256"] != digest):
        raise DesktopReviewError("界面归属变更与父修订不一致，不得夹带其他修改")


def validate_membership_batch_change(facade: Any, parent: dict, child: dict) -> None:
    refs = _batch_refs(facade, child["change"]["interface_batch"], parent["source_refs"].get("task_id"))
    expected_refs, expected_graph = deepcopy(parent["source_refs"]), deepcopy(parent["graph"])
    key = "interfaces" if expected_refs.get("kind") == "interface_composition" else "interface_composition"
    values = expected_refs.setdefault(key, [])
    existing_ids = {item.get("interface_id") for item in values if isinstance(item, dict)}
    if len(existing_ids) != len(values) or any(ref["interface_id"] in existing_ids for ref in refs):
        raise DesktopReviewError("interface_batch_already_attached")
    nodes = [reference_node(facade, ref, expected_refs["task_id"]) for ref in refs]
    node_ids = [node["node_id"] for node in nodes]
    if len(node_ids) != len(set(node_ids)) or any(node_id in expected_graph["workflow"]["node_ids"] for node_id in node_ids):
        raise DesktopReviewError("interface_batch_node_duplicate")
    values.extend(deepcopy(refs))
    expected_graph["nodes"].extend(nodes)
    expected_graph["workflow"]["node_ids"].extend(node_ids)
    expected_graph["workflow"]["edge_ids"] = [edge["edge_id"] for edge in expected_graph.get("edges", [])]
    digest = membership_batch_request_sha(parent["logical_workflow_id"], parent["revision"], parent["content_sha256"], refs)
    if (expected_refs != child["source_refs"] or expected_graph != child["graph"]
            or child["change"]["request_sha256"] != digest):
        raise DesktopReviewError("interface_batch_change_invalid")
