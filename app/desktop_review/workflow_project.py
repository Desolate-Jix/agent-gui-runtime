"""持续编辑流程项目的独立叠加层；不写入正式图修订或执行合同。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .external_mapping import canonical_json_bytes
from .workspace import DesktopReviewError, _atomic_write_bytes, _write_immutable


_CONTRACT = "workflow_project_view_v1"
_OVERLAY = "workflow_project_overlay_v1"
_HEAD = "workflow_project_head_v1"
_INDEX = "workflow_project_snapshot_index_v1"
_WORKFLOW = re.compile(r"workflow-[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")
_SNAPSHOT = re.compile(r"workflow-project-snapshot-[0-9a-f]{64}\Z")
_EDITORIAL_FIELDS = {"edge_id", "source_node_id", "target_node_id", "action_type", "target_region_id", "expected_result", "condition"}


class WorkflowProjectService:
    """从已验证图生成可编辑项目视图，叠加层始终不授予执行权限。"""

    def __init__(self, facade: Any) -> None:
        self.facade = facade
        self.root = facade._workspace_root / "workflow-projects"
        self.index_path = self.root / "snapshot-index.json"

    def list_projects(self) -> list[dict]:
        values = self.facade.list_workflow_graphs()
        if not isinstance(values, list):
            raise DesktopReviewError("workflow_project_list_invalid")
        result = []
        for value in values:
            if not isinstance(value, dict):
                raise DesktopReviewError("workflow_project_list_invalid")
            item = deepcopy(value)
            view = self.load(_workflow_id(item.get("logical_workflow_id")))
            item["title"] = view["graph"]["workflow"]["goal"]
            item["project_revision"] = view["revision"]
            item["project_content_sha256"] = view["content_sha256"]
            result.append(item)
        return result

    def list_summaries(self) -> list[dict]:
        """目录只读已校验图摘要和项目标题，不提前物化每个界面。"""
        values = self.facade.list_workflow_graphs()
        if not isinstance(values, list):
            raise DesktopReviewError("workflow_project_list_invalid")
        result = []
        for value in values:
            if not isinstance(value, dict):
                raise DesktopReviewError("workflow_project_list_invalid")
            item = deepcopy(value)
            overlay = self._head_overlay(_workflow_id(item.get("logical_workflow_id")))
            if overlay is not None:
                item["title"] = overlay["title"]
            item["project_revision"] = overlay["revision"] if overlay is not None else 0
            item["detail_loaded"] = False
            result.append(item)
        return result

    def load(self, workflow_id: str) -> dict:
        workflow = _workflow_id(workflow_id)
        source = self.facade.load_graph_revision(workflow)
        _source_snapshot(source, workflow)
        overlay = self._head_overlay(workflow)
        return self._build_view(source, overlay, pinned_interfaces=None, fixed=False)

    def load_snapshot(self, snapshot_id: str) -> dict:
        identifier = _snapshot_id(snapshot_id)
        index = self._index()
        entry = index.get("snapshots", {}).get(identifier)
        if not isinstance(entry, dict) or set(entry) != {"workflow_id", "overlay_sha256"}:
            raise DesktopReviewError("workflow_project_snapshot_not_found")
        workflow = _workflow_id(entry["workflow_id"])
        overlay = self._load_overlay(workflow, _sha(entry["overlay_sha256"], "overlay_sha256"))
        source = self.facade.load_graph_revision(workflow, overlay["source_revision"])
        _source_snapshot(source, workflow)
        if source["content_sha256"] != overlay["source_sha256"]:
            raise DesktopReviewError("workflow_project_snapshot_source_changed")
        view = self._build_view(source, overlay, pinned_interfaces=overlay["interface_versions"], fixed=True)
        if view["content_sha256"] != overlay["view_content_sha256"] or view["snapshot_id"] != identifier:
            raise DesktopReviewError("workflow_project_snapshot_invalid")
        return view

    def save(self, workflow_id: str, expected_sha256: str, changes: dict, idempotency_key: str) -> dict:
        workflow, expected, key = _workflow_id(workflow_id), _sha(expected_sha256, "expected_sha256"), _key(idempotency_key, "idempotency_key")
        current = self.load(workflow)
        head = self._head(workflow)
        request_sha = _request_sha(expected, changes)
        prior = head["requests"].get(key)
        if prior is not None:
            if prior.get("request_sha256") != request_sha:
                raise DesktopReviewError("idempotency_conflict")
            return self.load_snapshot(prior["snapshot_id"])
        if current["content_sha256"] != expected:
            raise DesktopReviewError("stale_workflow_project")
        source = self.facade.load_graph_revision(workflow)
        action_only = source.get("source_refs", {}).get("kind") == "recorded_actions"
        if (not action_only
                and not any(isinstance(node, dict) and isinstance(node.get("interface_reference"), dict)
                            for node in current["graph"]["nodes"])):
            raise DesktopReviewError("workflow_project_legacy_read_only")
        base_overlay = self._head_overlay(workflow)
        title, editorial, removed = _changes(changes, current["graph"], base_overlay)
        _source_snapshot(source, workflow)
        if source["revision"] != current["source_revision"] or source["content_sha256"] != current["source_sha256"]:
            raise DesktopReviewError("stale_workflow_project")
        revision = int(head["revision"]) + 1
        provisional = {
            "contract_version": _OVERLAY,
            "workflow_id": workflow,
            "revision": revision,
            "parent_overlay_sha256": head["overlay_sha256"],
            "source_revision": source["revision"],
            "source_sha256": source["content_sha256"],
            "title": title,
            "editorial_edges": editorial,
            "removed_original_edge_ids": removed,
            "interface_versions": _interface_versions(current["graph"]),
            "request_sha256": request_sha,
            "overlay_sha256": "",
            "snapshot_id": "",
            "view_content_sha256": "",
        }
        provisional["overlay_sha256"] = _digest({key: value for key, value in provisional.items() if key not in {"overlay_sha256", "snapshot_id", "view_content_sha256"}})
        provisional["snapshot_id"] = "workflow-project-snapshot-" + provisional["overlay_sha256"]
        view = self._build_view(source, provisional, pinned_interfaces=provisional["interface_versions"], fixed=True)
        provisional["view_content_sha256"] = view["content_sha256"]
        self._write_overlay(provisional)
        requests = deepcopy(head["requests"])
        requests[key] = {"request_sha256": request_sha, "snapshot_id": provisional["snapshot_id"]}
        index = self._index()
        index["snapshots"][provisional["snapshot_id"]] = {"workflow_id": workflow, "overlay_sha256": provisional["overlay_sha256"]}
        _atomic_write_bytes(self.index_path, canonical_json_bytes(index) + b"\n")
        self._write_head(workflow, revision, provisional["overlay_sha256"], requests)
        return self.load_snapshot(provisional["snapshot_id"])

    def memory(self, allowed_task_id: str, workflow_id: str, snapshot_id: str | None = None) -> dict:
        task = _text(allowed_task_id, "allowed_task_id")
        workflow = _workflow_id(workflow_id)
        if snapshot_id is None:
            dynamic = self.load(workflow)
            self._require_memory_task(task, dynamic)
            view = self._capture_memory_snapshot(workflow, dynamic)
        else:
            view = self.load_snapshot(snapshot_id)
            if view["logical_workflow_id"] != workflow:
                raise DesktopReviewError("workflow_project_memory_not_found")
            self._require_memory_task(task, view)
        # Agent 只接收明确的语义字段；原图证据与本机路径留在本地视图。
        graph = _memory_graph(view["graph"])
        # 原动作记录来自同一固定图修订；项目编辑边不能改写历史，也不从最新图补齐旧快照。
        source = self.facade.load_graph_revision(workflow, view["source_revision"])
        _source_snapshot(source, workflow)
        if source["content_sha256"] != view["source_sha256"]:
            raise DesktopReviewError("workflow_project_snapshot_source_changed")
        from .workflow_action_memory import project_recorded_action_memory
        graph["action_memory"] = project_recorded_action_memory(source)
        return {
            "contract_version": "agent_workflow_project_memory_v1",
            "logical_workflow_id": view["logical_workflow_id"],
            "snapshot_id": view["snapshot_id"],
            "revision": view["revision"],
            "content_sha256": view["content_sha256"],
            "source_revision": view["source_revision"],
            "source_sha256": view["source_sha256"],
            "graph": graph,
            "warnings": deepcopy(view["warnings"]),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }

    def _require_memory_task(self, allowed_task_id: str, view: dict) -> None:
        source_task = view["graph"].get("source", {}).get("task_id")
        if source_task is None:
            source_task = self.facade.load_graph_revision(view["logical_workflow_id"], view["source_revision"])["source_refs"].get("task_id")
        if source_task != allowed_task_id:
            raise DesktopReviewError("workflow_project_memory_not_found")

    def _build_view(self, source: dict, overlay: dict | None, pinned_interfaces: dict[str, dict] | None, *, fixed: bool) -> dict:
        graph = deepcopy(source["graph"])
        candidates_by_task = {}
        warnings: list[str] = []
        source_refs = source.get("source_refs", {})
        if source_refs.get("kind") == "recorded_actions":
            warnings.append("每条连线只证明该动作自己的操作前后画面；不同动作之间的先后与衔接尚未证明，画面排列不是执行顺序。")
        for node in graph["nodes"]:
            reference = node.get("interface_reference")
            if not isinstance(reference, dict):
                self._project_observed_interface(node, source_refs, pinned_interfaces, fixed=fixed,
                                                 candidates_by_task=candidates_by_task)
                reference = node.get("interface_reference")
            if not isinstance(reference, dict) or set(reference) != {"interface_id", "version_id", "content_sha256"}:
                continue
            pin = pinned_interfaces.get(node["node_id"]) if isinstance(pinned_interfaces, dict) else None
            interface_id = pin["interface_id"] if isinstance(pin, dict) else reference["interface_id"]
            version_id = pin.get("version_id") if isinstance(pin, dict) else None
            content = self.facade.load_interface_content(interface_id, version_id)
            if isinstance(pin, dict) and (
                content.get("interface_id") != pin.get("interface_id")
                or content.get("version_id") != pin.get("version_id")
                or content.get("content_sha256") != pin.get("content_sha256")
            ):
                raise DesktopReviewError("workflow_project_snapshot_interface_changed")
            evidence = self.facade.load_interface_content_evidence(interface_id, content["version_id"])
            node["interface_reference"] = {"interface_id": content["interface_id"], "version_id": content["version_id"], "content_sha256": content["content_sha256"]}
            node["display_name"] = content["content"]["meaning"]
            node["agent_description"] = content["content"]["meaning"]
            node["regions"] = deepcopy(content["content"]["regions"])
            node["interface_evidence"] = evidence
            node["editorial"] = False
        if overlay is not None:
            graph["workflow"]["goal"] = overlay["title"]
            source_edges = {edge["edge_id"]: edge for edge in graph["edges"]}
            graph["edges"] = [edge for edge in graph["edges"] if edge["edge_id"] not in set(overlay["removed_original_edge_ids"])]
            graph["edges"].extend(_project_editorial_edge(edge) for edge in overlay["editorial_edges"])
            for edge_id in overlay["removed_original_edge_ids"]:
                if edge_id not in source_edges:
                    warnings.append("removed_source_edge_missing:" + edge_id)
        node_map = {node["node_id"]: node for node in graph["nodes"]}
        for edge in graph["edges"]:
            if edge.get("editorial") is not True:
                continue
            origin = node_map.get(edge["source_node_id"])
            region_ids = {item.get("region_id") for item in origin.get("regions", [])} if isinstance(origin, dict) else set()
            if edge.get("target_region_id") is not None and edge.get("target_region_id") not in region_ids:
                edge["warning"] = "target_region_missing"
                warnings.append("target_region_missing")
        graph["workflow"]["edge_ids"] = [edge["edge_id"] for edge in graph["edges"]]
        graph["workflow"]["node_ids"] = [node["node_id"] for node in graph["nodes"]]
        graph["display_only"] = True
        graph["artifact_is_authorization"] = False
        graph["execute_binding_enabled"] = False
        revision = 0 if overlay is None else overlay["revision"]
        snapshot_id = overlay["snapshot_id"] if overlay is not None and fixed else None
        value = {
            "contract_version": _CONTRACT,
            "logical_workflow_id": source["logical_workflow_id"],
            "revision": revision,
            "content_sha256": "",
            "source_revision": source["revision"],
            "source_sha256": source["content_sha256"],
            "snapshot_id": snapshot_id,
            "graph": graph,
            "warnings": sorted(warnings),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        value["content_sha256"] = _view_digest(value)
        validate_project_view(value)
        return value

    def _project_observed_interface(self, node: dict, source_refs: dict, pins: dict | None, *, fixed: bool,
                                    candidates_by_task: dict | None = None) -> None:
        """将已完成的 observed-screen 投影回原节点；只读，不创建节点或修改来源。"""
        if not isinstance(source_refs, dict) or not source_refs.get("fresh_learning_source"):
            return
        node_id = node.get("node_id")
        external_id = node.get("external_interface_id")
        if not isinstance(node_id, str) or not isinstance(external_id, str):
            return
        pin = pins.get(node_id) if isinstance(pins, dict) else None
        scopes = [source_refs, *source_refs.get("additional_sources", [])]
        evidence = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}
        screenshot_sha = evidence.get("source_screenshot_sha256")
        screenshot_path = evidence.get("source_screenshot_path")
        screenshot_id = evidence.get("source_screenshot_id")

        def matches(value: dict, scope: dict) -> bool:
            source = value.get("source") if isinstance(value.get("source"), dict) else {}
            if (evidence.get("source_sha256") != scope.get("batch_sha256")
                    or not scope.get("fresh_learning_source")
                    or source.get("task_id") != scope.get("task_id")
                    or source.get("batch_id") != scope.get("batch_id")
                    or source.get("source_ref") != scope.get("batch_sha256")
                    or source.get("external_interface_id") != external_id
                    or source.get("screenshot_sha256") != screenshot_sha):
                return False
            if screenshot_id is not None and source.get("screenshot_id") != screenshot_id:
                return False
            # 身份已经匹配时，证据损坏必须暴露，不能静默退回旧的空节点。
            checked = self.facade.load_interface_content_evidence(value["interface_id"], value["version_id"])
            if checked.get("image_path") != screenshot_path or checked.get("sha256") != screenshot_sha:
                raise DesktopReviewError("workflow_project_observed_evidence_mismatch")
            return True

        if isinstance(pin, dict):
            if set(pin) != {"interface_id", "version_id", "content_sha256"}:
                raise DesktopReviewError("workflow_project_snapshot_interface_changed")
            content = self.facade.load_interface_content(pin["interface_id"], pin["version_id"])
            if (content.get("content_sha256") != pin["content_sha256"]
                    or not any(matches(content, scope) for scope in scopes)):
                raise DesktopReviewError("workflow_project_snapshot_interface_changed")
        elif fixed:
            return
        else:
            candidates = []
            seen_candidates = set()
            if candidates_by_task is None:
                candidates_by_task = {}
            for scope in scopes:
                task = scope.get("task_id")
                if task not in candidates_by_task:
                    candidates_by_task[task] = self.facade.list_interface_contents_for_reference(task)
                for value in candidates_by_task[task]:
                    if isinstance(value, dict) and matches(value, scope):
                        identity = tuple(value[key] for key in ("interface_id", "version_id", "content_sha256"))
                        if identity not in seen_candidates:
                            seen_candidates.add(identity)
                            candidates.append(value)
            if len(candidates) != 1:
                return
            content = candidates[0]

        checked = self.facade.load_interface_content_evidence(content["interface_id"], content["version_id"])
        node["interface_reference"] = {key: content[key] for key in ("interface_id", "version_id", "content_sha256")}
        node["display_name"] = content["content"]["meaning"]
        node["agent_description"] = content["content"]["meaning"]
        node["regions"] = deepcopy(content["content"].get("regions", []))
        if "recognition_text" in content["content"]:
            node["recognition_text"] = content["content"]["recognition_text"]
        else:
            node.pop("recognition_text", None)
        node["interface_evidence"] = checked

    def _capture_memory_snapshot(self, workflow: str, dynamic: dict) -> dict:
        head_overlay = self._head_overlay(workflow)
        source = self.facade.load_graph_revision(workflow, dynamic["source_revision"])
        _source_snapshot(source, workflow)
        base = head_overlay or {
            "revision": 0, "overlay_sha256": None, "title": dynamic["graph"]["workflow"]["goal"],
            "editorial_edges": [], "removed_original_edge_ids": [],
        }
        value = {
            "contract_version": _OVERLAY,
            "workflow_id": workflow,
            "revision": base["revision"],
            "parent_overlay_sha256": base["overlay_sha256"],
            "source_revision": source["revision"],
            "source_sha256": source["content_sha256"],
            "title": base["title"],
            "editorial_edges": deepcopy(base["editorial_edges"]),
            "removed_original_edge_ids": deepcopy(base["removed_original_edge_ids"]),
            "interface_versions": _interface_versions(dynamic["graph"]),
            "request_sha256": _digest({"capture": dynamic["content_sha256"]}),
            "overlay_sha256": "", "snapshot_id": "", "view_content_sha256": "",
        }
        value["overlay_sha256"] = _digest({key: item for key, item in value.items() if key not in {"overlay_sha256", "snapshot_id", "view_content_sha256"}})
        value["snapshot_id"] = "workflow-project-snapshot-" + value["overlay_sha256"]
        fixed = self._build_view(source, value, pinned_interfaces=value["interface_versions"], fixed=True)
        value["view_content_sha256"] = fixed["content_sha256"]
        self._write_overlay(value)
        index = self._index()
        index["snapshots"][value["snapshot_id"]] = {"workflow_id": workflow, "overlay_sha256": value["overlay_sha256"]}
        _atomic_write_bytes(self.index_path, canonical_json_bytes(index) + b"\n")
        return fixed

    def _directory(self, workflow_id: str) -> Path:
        workflow = _workflow_id(workflow_id)
        path = (self.root / workflow).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError as error:
            raise DesktopReviewError("workflow_project_path_invalid") from error
        return path

    def _head(self, workflow_id: str) -> dict:
        path = self._directory(workflow_id) / "head.json"
        if not path.exists():
            return {"contract_version": _HEAD, "workflow_id": workflow_id, "revision": 0, "overlay_sha256": None, "requests": {}}
        value = _json(path, "workflow project head")
        if (set(value) != {"contract_version", "workflow_id", "revision", "overlay_sha256", "requests"}
                or value.get("contract_version") != _HEAD or value.get("workflow_id") != workflow_id
                or type(value.get("revision")) is not int or value["revision"] < 0
                or (value["revision"] == 0 and value.get("overlay_sha256") is not None)
                or (value["revision"] > 0 and not _SHA.fullmatch(str(value.get("overlay_sha256"))))
                or not _valid_requests(value.get("requests"))):
            raise DesktopReviewError("workflow_project_head_invalid")
        return value

    def _head_overlay(self, workflow_id: str) -> dict | None:
        head = self._head(workflow_id)
        return None if head["overlay_sha256"] is None else self._load_overlay(workflow_id, head["overlay_sha256"])

    def _load_overlay(self, workflow_id: str, digest: str) -> dict:
        value = _json(self._directory(workflow_id) / "revisions" / f"{digest}.json", "workflow project overlay")
        _validate_overlay(value, workflow_id, digest)
        return value

    def _write_overlay(self, value: dict) -> None:
        _write_immutable(self._directory(value["workflow_id"]) / "revisions" / f"{value['overlay_sha256']}.json", canonical_json_bytes(value) + b"\n")

    def _write_head(self, workflow_id: str, revision: int, digest: str, requests: dict) -> None:
        value = {"contract_version": _HEAD, "workflow_id": workflow_id, "revision": revision, "overlay_sha256": digest, "requests": requests}
        _atomic_write_bytes(self._directory(workflow_id) / "head.json", canonical_json_bytes(value) + b"\n")

    def _index(self) -> dict:
        if not self.index_path.exists():
            return {"contract_version": _INDEX, "snapshots": {}}
        value = _json(self.index_path, "workflow project snapshot index")
        if value.get("contract_version") != _INDEX or not isinstance(value.get("snapshots"), dict):
            raise DesktopReviewError("workflow_project_index_invalid")
        return value


def validate_project_view(value: Any) -> dict:
    required = {"contract_version", "logical_workflow_id", "revision", "content_sha256", "source_revision", "source_sha256", "snapshot_id", "graph", "warnings", "artifact_is_authorization", "execute_binding_enabled"}
    if not isinstance(value, dict) or set(value) != required or value.get("contract_version") != _CONTRACT:
        raise ValueError("invalid workflow project view")
    if (not _WORKFLOW.fullmatch(str(value.get("logical_workflow_id"))) or type(value.get("revision")) is not int or value["revision"] < 0
            or not _SHA.fullmatch(str(value.get("content_sha256"))) or type(value.get("source_revision")) is not int or value["source_revision"] < 1
            or not _SHA.fullmatch(str(value.get("source_sha256"))) or (value["snapshot_id"] is not None and not _SNAPSHOT.fullmatch(str(value["snapshot_id"])))
            or value.get("artifact_is_authorization") is not False or value.get("execute_binding_enabled") is not False):
        raise ValueError("invalid workflow project identity")
    if _view_digest(value) != value["content_sha256"]:
        raise ValueError("workflow project digest mismatch")
    graph = value.get("graph")
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise ValueError("invalid workflow project graph")
    nodes = {node.get("node_id") for node in graph["nodes"] if isinstance(node, dict)}
    if len(nodes) != len(graph["nodes"]) or not all(isinstance(item, str) and item for item in nodes):
        raise ValueError("invalid workflow project nodes")
    edges = set()
    for edge in graph["edges"]:
        if not isinstance(edge, dict) or not isinstance(edge.get("edge_id"), str) or edge["edge_id"] in edges:
            raise ValueError("invalid workflow project edges")
        edges.add(edge["edge_id"])
        if edge.get("source_node_id") not in nodes or edge.get("target_node_id") not in nodes:
            raise ValueError("workflow project edge endpoint invalid")
    return deepcopy(value)


def _changes(value: Any, graph: dict, overlay: dict | None) -> tuple[str, list[dict], list[str]]:
    if not isinstance(value, dict) or not value or set(value) - {"title", "edges"}:
        raise DesktopReviewError("workflow_project_changes_invalid")
    title = value.get("title", graph.get("workflow", {}).get("goal"))
    title = _limited_text(title, "title", 4000)
    previous_editorial = deepcopy(overlay.get("editorial_edges", [])) if isinstance(overlay, dict) else []
    previous_removed = set(overlay.get("removed_original_edge_ids", [])) if isinstance(overlay, dict) else set()
    if not all(isinstance(edge, dict) for edge in previous_editorial) or not all(isinstance(edge, str) for edge in previous_removed):
        raise DesktopReviewError("workflow_project_overlay_invalid")
    if "edges" not in value:
        return title, previous_editorial, sorted(previous_removed)
    raw_edges = value["edges"]
    if not isinstance(raw_edges, list) or len(raw_edges) > 256:
        raise DesktopReviewError("workflow_project_edges_invalid")
    nodes = {node["node_id"]: node for node in graph["nodes"] if isinstance(node, dict) and isinstance(node.get("node_id"), str)}
    source = {edge["edge_id"]: edge for edge in graph["edges"] if isinstance(edge, dict) and isinstance(edge.get("edge_id"), str) and edge.get("editorial") is not True}
    editorial, seen = [], set()
    for edge in raw_edges:
        checked = _editorial_input(edge, nodes)
        if checked["edge_id"] in seen:
            raise DesktopReviewError("workflow_project_edge_duplicate")
        seen.add(checked["edge_id"])
        original = source.get(checked["edge_id"])
        if original is not None:
            if checked == _source_editable(original):
                continue
        editorial.append(checked)
    removed = sorted(previous_removed | (set(source) - seen) | {item["edge_id"] for item in editorial if item["edge_id"] in source})
    return title, editorial, removed


def _editorial_input(value: Any, nodes: dict[str, dict]) -> dict:
    if not isinstance(value, dict) or set(value) != _EDITORIAL_FIELDS:
        raise DesktopReviewError("workflow_project_edge_fields_invalid")
    result = {}
    for key in _EDITORIAL_FIELDS:
        if key == "target_region_id" and value[key] is None:
            result[key] = None
        elif key in {"expected_result", "condition"}:
            result[key] = _editable_text(value[key], key, 4000)
        else:
            result[key] = _limited_text(value[key], key, 512)
    if result["source_node_id"] not in nodes or result["target_node_id"] not in nodes:
        raise DesktopReviewError("workflow_project_edge_endpoint_invalid")
    regions = {item.get("region_id") for item in nodes[result["source_node_id"]].get("regions", []) if isinstance(item, dict)}
    if result["target_region_id"] is not None and result["target_region_id"] not in regions:
        raise DesktopReviewError("workflow_project_target_region_invalid")
    return result


def _source_editable(edge: dict) -> dict:
    return {
        "edge_id": edge["edge_id"], "source_node_id": edge["source_node_id"], "target_node_id": edge["target_node_id"],
        "action_type": str(edge.get("action_type") or "unknown"),
        "target_region_id": edge.get("target_region_id") if isinstance(edge.get("target_region_id"), str) else None,
        "expected_result": str(edge.get("expected_result") or ""), "condition": str(edge.get("condition") or edge.get("stop_condition") or ""),
    }


def _project_editorial_edge(value: dict) -> dict:
    return {
        "edge_id": value["edge_id"], "source_node_id": value["source_node_id"], "target_node_id": value["target_node_id"],
        "action_type": value["action_type"], "target_region_id": value["target_region_id"],
        "expected_result": value["expected_result"], "condition": value["condition"], "editorial": True,
        "unverified": True, "artifact_is_authorization": False, "execute_binding_enabled": False,
    }


def _memory_graph(graph: dict) -> dict:
    node_fields = {"node_id", "display_name", "agent_description", "external_interface_id",
                   "interface_reference", "recognition_text", "editorial"}
    region_fields = {"region_id", "bbox", "name", "label", "kind", "type", "meaning", "recognition_text"}
    edge_fields = {"edge_id", "source_node_id", "target_node_id", "action_type", "target_region_id",
                   "expected_result", "condition", "stop_condition", "prerequisites", "label", "editorial", "unverified", "warning"}
    nodes = []
    for node in graph["nodes"]:
        item = {key: deepcopy(node[key]) for key in node_fields if key in node}
        item["regions"] = [{key: deepcopy(region[key]) for key in region_fields if key in region}
                           for region in node.get("regions", [])]
        nodes.append(item)
    return {"workflow": {key: deepcopy(graph.get("workflow", {}).get(key))
                         for key in ("workflow_id", "goal", "node_ids", "edge_ids")},
            "nodes": nodes,
            "edges": [{key: deepcopy(edge[key]) for key in edge_fields if key in edge} for edge in graph["edges"]],
            "display_only": True, "artifact_is_authorization": False, "execute_binding_enabled": False}


def _interface_versions(graph: dict) -> dict[str, dict]:
    result = {}
    for node in graph.get("nodes", []):
        reference = node.get("interface_reference") if isinstance(node, dict) else None
        if isinstance(reference, dict) and set(reference) == {"interface_id", "version_id", "content_sha256"}:
            result[node["node_id"]] = deepcopy(reference)
    return result


def _source_snapshot(value: Any, workflow_id: str) -> None:
    if not isinstance(value, dict) or value.get("logical_workflow_id") != workflow_id or not isinstance(value.get("graph"), dict):
        raise DesktopReviewError("workflow_project_source_invalid")


def _validate_overlay(value: Any, workflow_id: str, digest: str) -> None:
    required = {"contract_version", "workflow_id", "revision", "parent_overlay_sha256", "source_revision", "source_sha256", "title", "editorial_edges", "removed_original_edge_ids", "interface_versions", "request_sha256", "overlay_sha256", "snapshot_id", "view_content_sha256"}
    if not isinstance(value, dict) or set(value) != required or value.get("contract_version") != _OVERLAY or value.get("workflow_id") != workflow_id or value.get("overlay_sha256") != digest:
        raise DesktopReviewError("workflow_project_overlay_invalid")
    if (type(value.get("revision")) is not int or value["revision"] < 0 or not _SHA.fullmatch(str(value.get("source_sha256")))
            or not _SHA.fullmatch(str(value.get("request_sha256"))) or not _SHA.fullmatch(str(value.get("view_content_sha256")))
            or value.get("snapshot_id") != "workflow-project-snapshot-" + digest):
        raise DesktopReviewError("workflow_project_overlay_invalid")
    parent = value.get("parent_overlay_sha256")
    if parent is not None and not _SHA.fullmatch(str(parent)):
        raise DesktopReviewError("workflow_project_overlay_invalid")
    calculated = _digest({key: item for key, item in value.items() if key not in {"overlay_sha256", "snapshot_id", "view_content_sha256"}})
    if calculated != digest:
        raise DesktopReviewError("workflow_project_overlay_invalid")


def _valid_requests(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and _KEY.fullmatch(key) and isinstance(item, dict)
        and set(item) == {"request_sha256", "snapshot_id"} and _SHA.fullmatch(str(item.get("request_sha256")))
        and _SNAPSHOT.fullmatch(str(item.get("snapshot_id")))
        for key, item in value.items()
    )


def _request_sha(expected: str, changes: Any) -> str:
    try:
        return _digest({"expected_sha256": expected, "changes": changes})
    except Exception as error:
        raise DesktopReviewError("workflow_project_changes_invalid") from error


def _workflow_id(value: Any) -> str:
    text = _text(value, "workflow_id")
    if not _WORKFLOW.fullmatch(text):
        raise DesktopReviewError("workflow_project_id_invalid")
    return text


def _snapshot_id(value: Any) -> str:
    text = _text(value, "snapshot_id")
    if not _SNAPSHOT.fullmatch(text):
        raise DesktopReviewError("workflow_project_snapshot_invalid")
    return text


def _sha(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _SHA.fullmatch(text):
        raise DesktopReviewError(f"{name}_invalid")
    return text


def _key(value: Any, name: str) -> str:
    text = _text(value, name)
    if not _KEY.fullmatch(text):
        raise DesktopReviewError(f"{name}_invalid")
    return text


def _limited_text(value: Any, name: str, maximum: int) -> str:
    text = _text(value, name)
    if len(text) > maximum:
        raise DesktopReviewError(f"{name}_too_long")
    return text


def _editable_text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise DesktopReviewError(f"{name}_invalid")
    text = value.strip()
    if len(text) > maximum:
        raise DesktopReviewError(f"{name}_too_long")
    return text


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DesktopReviewError(f"{name}_invalid")
    return value.strip()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _view_digest(value: dict) -> str:
    return _digest({key: item for key, item in value.items() if key not in {"content_sha256", "snapshot_id"}})


def _json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise DesktopReviewError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise DesktopReviewError(f"{label}_invalid")
    return value


__all__ = ["WorkflowProjectService", "validate_project_view"]
