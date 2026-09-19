"""图修订草稿持久化：仅供桌面审核 façade 在其锁内调用。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from app.agent_link.graph_contract import (
    GraphContractError, apply_graph_operations, validate_graph_operations, validate_node_recognition_anchor,
)

from .external_mapping import (
    build_external_workflow_review,
    canonical_json_bytes,
    normalize_agent_link_batch,
    source_image_relative_path,
    source_ref_for_batch,
)
from .workspace import (
    DesktopReviewError,
    _atomic_write_bytes,
    _inside,
    _validate_snapshot,
    _write_immutable,
)


_REVISION_CONTRACT = "formal_graph_revision_v1"
_HEAD_CONTRACT = "formal_graph_draft_head_v1"
_LOGICAL_ID = re.compile(r"workflow-[0-9a-f]{64}\Z")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class GraphRevisionService:
    """复用 façade 的来源物化、锁和原子写入，而不创建第二宿主。"""

    def __init__(self, facade: Any):
        self._facade = facade
        self._root = facade._workspace_root / "graph-revisions"

    def create(
        self,
        task_id: str,
        batch_id: str,
        expected_workspace_revision: int,
        step_relationships: dict[str, list[str]] | None,
    ) -> dict[str, Any]:
        task = _text(task_id, "task_id")
        batch = _text(batch_id, "batch_id")
        _revision(expected_workspace_revision, "expected_workspace_revision", allow_zero=True)
        loaded = self._facade.load_batch(task, batch)
        if loaded["revision"] != expected_workspace_revision:
            raise DesktopReviewError("stale_revision: 工作区修订已过期，请重新加载后创建图草稿")
        original = self._facade._load_source_batch(task, batch)
        source_ref = source_ref_for_batch(original)
        if loaded["source_ref"] != source_ref:
            raise DesktopReviewError("图草稿工作区来源与原始 inbox 批次不一致")
        logical_id = "workflow-" + self._facade._workspace_key(task, batch)
        self._validate_logical_id(logical_id)
        existing = self._load_head(logical_id, required=False)
        if existing is not None:
            self._assert_same_source(existing, task, batch, source_ref)
            return existing
        try:
            self._facade._materialize_source(source_ref, original)
            imported_workspace = self._imported_workspace(
                task, batch, source_ref, loaded,
            )
            source_refs = self._source_refs(
                task, batch, source_ref, original, loaded["batch"],
                imported_workspace,
            )
            graph = build_external_workflow_review(
                batch=loaded["batch"], task_id=task, source_ref=source_ref,
                revision=1, step_relationships=step_relationships,
            )
        except DesktopReviewError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise DesktopReviewError("graph_creation_failed: 图草稿来源无法物化") from error
        snapshot = self._snapshot(
            logical_id=logical_id, revision=1, parent_sha256=None,
            source_refs=source_refs, graph=graph,
            idempotency_key=None, request_sha256=None,
        )
        self._write_committed(snapshot)
        return self._load_head(logical_id, required=True)

    def create_action_only(self, source: dict[str, Any]) -> dict[str, Any]:
        """以首个不可变动作事件为图锚点；不创建或冒充 fresh observation。"""
        from .action_graph_source import ActionGraphSourceReader, action_sequence_metadata, project_action_source

        if not isinstance(source, dict):
            raise DesktopReviewError("动作图锚点无效")
        scope = {key: source.get(key) for key in ("connection_id", "task_id", "segment_id")}
        ActionGraphSourceReader(self._facade).validate(source, scope)
        projected = project_action_source(source)
        if not projected["nodes"]:
            raise DesktopReviewError("动作图锚点没有可审核原图")
        logical_id = "workflow-" + hashlib.sha256(canonical_json_bytes({
            "kind": "recorded_actions", **scope,
        })).hexdigest()
        existing = self._load_head(logical_id, required=False)
        if existing is not None:
            refs = existing["source_refs"]
            if (refs.get("kind") != "recorded_actions"
                    or any(refs.get(key) != value for key, value in scope.items())):
                raise DesktopReviewError("同一动作图身份已绑定冲突来源")
            return existing
        refs = {"kind": "recorded_actions", **scope,
                "anchor_event_id": source["event_id"], "anchor_source_sha256": source["source_sha256"],
                "action_sources": [deepcopy(source)]}
        graph = {
            "display_only": True, "artifact_is_authorization": False, "execute_binding_enabled": False,
            "workflow": {"workflow_id": logical_id, "goal": "Recorded actions",
                         "node_ids": [item["node_id"] for item in projected["nodes"]],
                         "edge_ids": [item["edge_id"] for item in projected["edges"]]},
            "nodes": deepcopy(projected["nodes"]), "edges": deepcopy(projected["edges"]),
            "action_sequence": action_sequence_metadata([source]),
            "invalid_sources": deepcopy(projected["invalid_sources"]),
            "source": {"kind": "recorded_actions", **scope, "anchor_event_id": source["event_id"],
                       "anchor_source_sha256": source["source_sha256"]},
        }
        snapshot = self._snapshot(logical_id=logical_id, revision=1, parent_sha256=None,
                                  source_refs=refs, graph=graph,
                                  idempotency_key=None, request_sha256=None)
        self._write_committed(snapshot)
        return self._load_head(logical_id, required=True)

    def load(self, logical_workflow_id: str, revision: int | None) -> dict[str, Any]:
        logical_id = self._validate_logical_id(logical_workflow_id)
        current = self._load_head(logical_id, required=True)
        if revision is None:
            return current
        requested = _revision(revision, "revision", allow_zero=False)
        if requested > current["revision"]:
            raise DesktopReviewError("请求的图草稿修订不存在")
        item = current
        while item["revision"] > requested:
            parent = item["parent_sha256"]
            if parent is None:
                raise DesktopReviewError("图草稿父修订链不完整")
            item = self._load_revision(logical_id, parent)
        return item

    def load_for_batch(self, task_id: str, batch_id: str) -> dict[str, Any]:
        """将段内任一新观察解析到首个不可变图草稿。"""
        task, batch = _text(task_id, "task_id"), _text(batch_id, "batch_id")
        original = self._facade._load_source_batch(task, batch)
        fresh = self._facade._fresh_source_for_batch(task, batch, original)
        if fresh is None:
            return self.load("workflow-" + self._facade._workspace_key(task, batch), None)
        first = self._first_segment_batch(fresh, task, batch)
        return self.load("workflow-" + self._facade._workspace_key(task, first), None)

    def append_fresh_source(
        self, logical_workflow_id: str, task_id: str, batch_id: str,
    ) -> dict[str, Any]:
        """追加一份同连接、任务和段的 fresh 来源；这不是普通图编辑。"""
        logical_id = self._validate_logical_id(logical_workflow_id)
        task, batch = _text(task_id, "task_id"), _text(batch_id, "batch_id")
        current = self._load_head(logical_id, required=True)
        original = self._facade._load_source_batch(task, batch)
        source_ref = source_ref_for_batch(original)
        existing = self._all_source_refs(current["source_refs"])
        for item in existing:
            if item["batch_id"] == batch and (item["batch_sha256"] != source_ref or item["task_id"] != task):
                raise DesktopReviewError("fresh_source_rewritten: 已绑定批次不得以新内容再次追加")
        self._facade._materialize_source(source_ref, original)
        candidate = self._fresh_source_ref(task, batch, source_ref, original)
        self._assert_append_scope(current, candidate)
        if any(item["batch_id"] == batch and item["batch_sha256"] == source_ref for item in existing):
            return current
        refs = deepcopy(current["source_refs"])
        refs.setdefault("additional_sources", []).append(candidate)
        added_nodes = self._nodes_for_source(candidate, task, current["revision"])
        graph = deepcopy(current["graph"])
        graph["nodes"].extend(added_nodes)
        graph["workflow"]["node_ids"].extend(node["node_id"] for node in added_nodes)
        request_sha = hashlib.sha256(canonical_json_bytes({
            "logical_workflow_id": logical_id,
            "parent_sha256": current["content_sha256"], "source": candidate,
        })).hexdigest()
        snapshot = self._snapshot(
            logical_id=logical_id, revision=current["revision"] + 1,
            parent_sha256=current["content_sha256"], source_refs=refs, graph=graph,
            idempotency_key="source-append-" + source_ref[:32], request_sha256=request_sha,
            source_append=candidate,
        )
        self._write_committed(snapshot)
        return self._load_head(logical_id, required=True)

    def node_evidence(self, logical_workflow_id: str, expected_revision: int,
                      expected_graph_sha256: str, node_id: str) -> dict[str, Any]:
        expected = _revision(expected_revision, "expected_revision", allow_zero=False)
        digest = _sha(expected_graph_sha256, "expected_graph_sha256")
        current = self.load(logical_workflow_id, None)
        if current["revision"] != expected or current["content_sha256"] != digest:
            raise DesktopReviewError("stale_revision: 图截图请求与当前修订不一致")
        node = _one(current["graph"]["nodes"], "node_id", _text(node_id, "node_id"), "节点")
        if "interface_reference" in node:
            ref = node["interface_reference"]
            content = self._facade.load_interface_content(ref["interface_id"], ref["version_id"])
            evidence = self._facade.load_interface_content_evidence(ref["interface_id"], ref["version_id"])
            shot = {"path": evidence["image_path"], "screenshot_id": content["source"]["screenshot_id"],
                    **{key: evidence[key] for key in ("sha256", "width", "height")}}
        else:
            shot = _one(self._source_screenshots(current["source_refs"]), "path",
                        node["evidence"]["source_screenshot_path"], "截图")
        path = self._facade._artifact_file(shot["path"], "图节点截图")
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise DesktopReviewError("图节点截图无法读取") from error
        if hashlib.sha256(raw).hexdigest() != shot["sha256"]:
            raise DesktopReviewError("图节点截图内容摘要已变化")
        return {
            "contract_version": "formal_graph_node_evidence_v1",
            "logical_workflow_id": current["logical_workflow_id"],
            "graph_revision": current["revision"], "graph_sha256": current["content_sha256"],
            "node": deepcopy(node),
            "screenshot": {key: shot[key] for key in ("screenshot_id", "sha256", "width", "height")}
                          | {"png_bytes": raw},
            "artifact_is_authorization": False, "execute_binding_enabled": False,
        }

    def apply(
        self,
        logical_workflow_id: str,
        expected_revision: int,
        expected_graph_sha256: str,
        operation: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        logical_id = self._validate_logical_id(logical_workflow_id)
        expected = _revision(expected_revision, "expected_revision", allow_zero=False)
        expected_sha = _sha(expected_graph_sha256, "expected_graph_sha256")
        key = _key(idempotency_key, "idempotency_key")
        normalized_operation = _operation(operation)
        request_sha = hashlib.sha256(canonical_json_bytes({
            "logical_workflow_id": logical_id,
            "expected_revision": expected,
            "expected_graph_sha256": expected_sha,
            "operation": normalized_operation,
        })).hexdigest()
        current = self._load_head(logical_id, required=True)
        duplicate = self._find_idempotency(current, key, request_sha)
        if duplicate is not None:
            return duplicate
        if current["revision"] != expected or current["content_sha256"] != expected_sha:
            raise DesktopReviewError("stale_revision: 图草稿修订或内容摘要已过期")
        graph = self._apply_checked(current, [normalized_operation], {
            "node_ids": [normalized_operation["node_id"]] if "node_id" in normalized_operation else [],
            "edge_ids": [normalized_operation["edge_id"]] if "edge_id" in normalized_operation else [],
        })
        snapshot = self._snapshot(
            logical_id=logical_id, revision=current["revision"] + 1,
            parent_sha256=current["content_sha256"], source_refs=current["source_refs"],
            graph=graph, idempotency_key=key, request_sha256=request_sha,
        )
        self._write_committed(snapshot)
        return self._load_head(logical_id, required=True)

    def apply_many(
        self, logical_workflow_id: str, expected_revision: int,
        expected_graph_sha256: str, operations: list[dict[str, Any]], idempotency_key: str,
    ) -> dict[str, Any]:
        logical_id = self._validate_logical_id(logical_workflow_id)
        expected = _revision(expected_revision, "expected_revision", allow_zero=False)
        expected_sha = _sha(expected_graph_sha256, "expected_graph_sha256")
        key = _key(idempotency_key, "idempotency_key")
        if not isinstance(operations, list) or not 1 <= len(operations) <= 5:
            raise DesktopReviewError("原子图编辑必须包含 1 至 5 项操作")
        checked = [_operation(item) for item in operations]
        self._validate_atomic_subject(checked)
        request_sha = hashlib.sha256(canonical_json_bytes({
            "logical_workflow_id": logical_id, "expected_revision": expected,
            "expected_graph_sha256": expected_sha, "operations": checked,
        })).hexdigest()
        current = self._load_head(logical_id, required=True)
        duplicate = self._find_idempotency(current, key, request_sha)
        if duplicate is not None:
            return duplicate
        if current["revision"] != expected or current["content_sha256"] != expected_sha:
            raise DesktopReviewError("stale_revision: 图草稿修订或内容摘要已过期")
        scope = {"node_ids": [checked[0]["node_id"]] if "node_id" in checked[0] else [],
                 "edge_ids": [checked[0]["edge_id"]] if "edge_id" in checked[0] else []}
        graph = self._apply_checked(current, checked, scope)
        snapshot = self._snapshot(logical_id=logical_id, revision=current["revision"] + 1,
            parent_sha256=current["content_sha256"], source_refs=current["source_refs"], graph=graph,
            idempotency_key=key, request_sha256=request_sha)
        self._write_committed(snapshot)
        return self._load_head(logical_id, required=True)

    @staticmethod
    def _validate_atomic_subject(operations: list[dict[str, Any]]) -> None:
        first = operations[0]
        subject = ("node", first["node_id"]) if "node_id" in first else ("edge", first["edge_id"])
        seen_types, seen_regions = set(), set()
        for operation in operations:
            candidate = (("node", operation["node_id"]) if "node_id" in operation else ("edge", operation["edge_id"]))
            if candidate != subject or operation["type"] in seen_types:
                raise DesktopReviewError("原子图编辑必须针对同一节点或同一边，且类型不可重复")
            seen_types.add(operation["type"])
            if "region_id" in operation:
                region = operation["region_id"]
                if region in seen_regions:
                    raise DesktopReviewError("原子图编辑不得重复修改同一区域")
                seen_regions.add(region)

    def adopt_candidate(
        self, logical_workflow_id: str, expected_revision: int,
        expected_graph_sha256: str, operations: list[dict[str, Any]],
        scope: dict[str, list[str]], idempotency_key: str,
        adoption: dict[str, Any],
    ) -> dict[str, Any]:
        logical_id = self._validate_logical_id(logical_workflow_id)
        expected = _revision(expected_revision, "expected_revision", allow_zero=False)
        expected_sha = _sha(expected_graph_sha256, "expected_graph_sha256")
        key = _key(idempotency_key, "idempotency_key")
        request_sha = hashlib.sha256(canonical_json_bytes({
            "logical_workflow_id": logical_id, "expected_revision": expected,
            "expected_graph_sha256": expected_sha, "operations": operations,
            "scope": scope, "adoption": adoption,
        })).hexdigest()
        current = self._load_head(logical_id, required=True)
        duplicate = self._find_idempotency(current, key, request_sha)
        if duplicate is not None:
            return duplicate
        if current["revision"] != expected or current["content_sha256"] != expected_sha:
            raise DesktopReviewError("stale_revision: 图草稿修订或内容摘要已过期")
        graph = self._apply_checked(current, operations, scope)
        snapshot = self._snapshot(
            logical_id=logical_id, revision=current["revision"] + 1,
            parent_sha256=current["content_sha256"], source_refs=current["source_refs"],
            graph=graph, idempotency_key=key, request_sha256=request_sha,
            adoption=adoption,
        )
        self._write_committed(snapshot)
        return self._load_head(logical_id, required=True)

    def find_committed_adoption(self, logical_workflow_id: str, idempotency_key: str, request_sha256: str) -> dict[str, Any] | None:
        logical_id = self._validate_logical_id(logical_workflow_id)
        key = _key(idempotency_key, "idempotency_key")
        request_sha = _sha(request_sha256, "adoption request_sha256")
        item = self._load_head(logical_id, required=True)
        while True:
            change = item["change"]
            if change["idempotency_key"] == key:
                adoption = change.get("adoption")
                if not isinstance(adoption, dict) or adoption.get("request_sha256") != request_sha:
                    raise DesktopReviewError("idempotency_key 已用于不同图草稿请求")
                return item
            if item["parent_sha256"] is None:
                return None
            item = self._load_revision(logical_id, item["parent_sha256"])

    def _apply_checked(self, current: dict[str, Any], operations: list[dict[str, Any]], scope: dict[str, list[str]]) -> dict[str, Any]:
        try:
            checked = validate_graph_operations(operations, current["graph"], scope)
            for operation in checked:
                if operation.get("node_id"):
                    node = _one(current["graph"]["nodes"], "node_id", operation["node_id"], "节点")
                    if "interface_reference" in node and operation["type"] in {"update_node_meaning", "update_node_recognition_text", "update_region_bbox"}:
                        raise DesktopReviewError("界面引用节点必须通过独立界面编辑，不能直接修改图字段")
                if operation["type"] in {"update_region_bbox", "update_node_recognition_text"}:
                    self._assert_bbox_in_source(current, operation)
            return apply_graph_operations(current["graph"], checked)
        except GraphContractError as error:
            raise DesktopReviewError(str(error)) from error

    def _assert_bbox_in_source(self, current: dict[str, Any], operation: dict[str, Any]) -> None:
        node = _one(current["graph"]["nodes"], "node_id", operation["node_id"], "节点")
        evidence = node.get("evidence")
        if not isinstance(evidence, dict): raise DesktopReviewError("图草稿节点截图证据无效")
        shot = _one(self._source_screenshots(current["source_refs"]), "path", evidence.get("source_screenshot_path"), "截图")
        if not _valid_bbox(operation["bbox"], shot["width"], shot["height"]):
            raise DesktopReviewError("图草稿区域框必须为图像范围内的有限正尺寸坐标")

    def _source_refs(
        self,
        task_id: str,
        batch_id: str,
        source_ref: str,
        original: dict[str, Any],
        imported_batch: dict[str, Any],
        imported_workspace: dict[str, Any] | None,
    ) -> dict[str, Any]:
        source_path = self._facade._workspace_root / "sources" / source_ref / "original_batch.json"
        if not source_path.is_file():
            raise DesktopReviewError("图草稿原始批次证据缺失")
        references = []
        if source_ref_for_batch(original) != source_ref:
            raise DesktopReviewError("图草稿原始批次摘要不一致")
        for shot in imported_batch["screenshots"]:
            relative = source_image_relative_path(source_ref, shot)
            path = (self._facade._artifact_root / relative).resolve()
            if not _inside(self._facade._artifact_root, path) or not path.is_file():
                raise DesktopReviewError("图草稿截图证据缺失")
            if hashlib.sha256(path.read_bytes()).hexdigest() != shot["sha256"]:
                raise DesktopReviewError("图草稿截图证据摘要不匹配")
            references.append({
                "screenshot_id": shot["screenshot_id"], "path": relative,
                "sha256": shot["sha256"], "width": shot["width"], "height": shot["height"],
            })
        fresh_source = self._facade._fresh_source_for_batch(task_id, batch_id, original)
        return {
            "task_id": task_id,
            "batch_id": batch_id,
            "batch_sha256": source_ref,
            "original_batch_path": (Path("desktop-review") / "sources" / source_ref / "original_batch.json").as_posix(),
            "original_batch_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "screenshots": references,
            "imported_workspace": deepcopy(imported_workspace),
            **({"fresh_learning_source": fresh_source} if fresh_source is not None else {}),
        }

    def _imported_workspace(
        self,
        task_id: str,
        batch_id: str,
        source_ref: str,
        loaded: dict[str, Any],
    ) -> dict[str, Any] | None:
        if loaded["revision"] == 0:
            return None
        relative = self._facade._snapshot_relative_path(loaded)
        path = (self._facade._artifact_root / relative).resolve()
        if not _inside(self._facade._workspace_root, path) or not path.is_file():
            raise DesktopReviewError("图草稿导入的工作区修订文件缺失")
        raw = path.read_bytes()
        try:
            snapshot = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("图草稿导入的工作区修订内容无效") from error
        _validate_snapshot(snapshot, existing_png_sha256=self._facade._source_png_allowlist(task_id, batch_id, source_ref))
        if snapshot != loaded or any((
            snapshot["task_id"] != task_id,
            snapshot["batch_id"] != batch_id,
            snapshot["source_ref"] != source_ref,
            snapshot["revision"] != loaded["revision"],
        )):
            raise DesktopReviewError("图草稿导入的工作区修订身份不一致")
        self._facade._validated_revision_chain(snapshot)
        return {
            "revision": snapshot["revision"],
            "workspace_path": relative.as_posix(),
            "workspace_sha256": hashlib.sha256(raw).hexdigest(),
        }

    def append_action_source(
        self, logical_workflow_id: str, source: dict[str, Any],
    ) -> dict[str, Any]:
        """追加一份权威动作投影，且不改写已有人工编辑。"""

        logical_id = self._validate_logical_id(logical_workflow_id)
        current = self._load_head(logical_id, required=True)
        base_fresh = current["source_refs"].get("fresh_learning_source")
        scope_anchor = base_fresh if isinstance(base_fresh, dict) else (
            current["source_refs"] if current["source_refs"].get("kind") == "recorded_actions" else None)
        if not isinstance(scope_anchor, dict):
            raise DesktopReviewError("missing_observation_anchor: 动作来源需要同段首个 fresh 观察")
        from .action_graph_source import ActionGraphSourceReader, action_sequence_metadata, project_action_source

        reader = ActionGraphSourceReader(self._facade)
        reader.validate(source, scope_anchor)
        source = deepcopy(source)
        event_id = source["event_id"]
        existing = current["source_refs"].get("action_sources", [])
        if not isinstance(existing, list):
            raise DesktopReviewError("图草稿动作来源引用无效")
        same_event = [item for item in existing if item.get("event_id") == event_id]
        if same_event:
            if len(same_event) != 1 or same_event[0] != source:
                raise DesktopReviewError("action_source_rewritten: 已绑定动作事件不得改写")
            return current
        projected = project_action_source(source)
        if not isinstance(projected, dict) or set(projected) != {"nodes", "edges", "invalid_sources"}:
            raise DesktopReviewError("动作来源投影无效")
        nodes, edges = projected["nodes"], projected["edges"]
        if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(projected["invalid_sources"], list):
            raise DesktopReviewError("动作来源投影无效")
        refs = deepcopy(current["source_refs"])
        refs.setdefault("action_sources", []).append(source)
        graph = deepcopy(current["graph"])
        graph["nodes"].extend(deepcopy(nodes))
        graph["edges"].extend(deepcopy(edges))
        graph["invalid_sources"].extend(deepcopy(projected["invalid_sources"]))
        graph["action_sequence"] = action_sequence_metadata(refs["action_sources"])
        graph["workflow"]["node_ids"].extend(item["node_id"] for item in nodes)
        graph["workflow"]["edge_ids"].extend(item["edge_id"] for item in edges)
        request_sha = hashlib.sha256(canonical_json_bytes({
            "logical_workflow_id": logical_id,
            "parent_sha256": current["content_sha256"], "source": source,
        })).hexdigest()
        snapshot = self._snapshot(
            logical_id=logical_id, revision=current["revision"] + 1,
            parent_sha256=current["content_sha256"], source_refs=refs, graph=graph,
            idempotency_key="action-append-" + event_id.split(".")[-1][:32],
            request_sha256=request_sha, action_append=source, action_sequence_version=1,
        )
        self._write_committed(snapshot)
        return self._load_head(logical_id, required=True)

    def _snapshot(self, *, logical_id: str, revision: int, parent_sha256: str | None, source_refs: dict[str, Any], graph: dict[str, Any], idempotency_key: str | None, request_sha256: str | None, adoption: dict[str, Any] | None = None, source_append: dict[str, Any] | None = None, action_append: dict[str, Any] | None = None, action_invalid_sources_version: int | None = 1, action_sequence_version: int | None = None, interface_append: dict[str, Any] | None = None, interface_batch: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        value = {
            "contract_version": _REVISION_CONTRACT,
            "logical_workflow_id": logical_id,
            "revision": revision,
            "content_sha256": "",
            "parent_sha256": parent_sha256,
            "source_refs": deepcopy(source_refs),
            "graph": deepcopy(graph),
            "change": {"idempotency_key": idempotency_key, "request_sha256": request_sha256},
        }
        if adoption is not None:
            value["change"]["adoption"] = deepcopy(adoption)
        if source_append is not None:
            value["change"]["source_append"] = deepcopy(source_append)
        if action_append is not None:
            value["change"]["action_append"] = deepcopy(action_append)
            if action_invalid_sources_version is not None:
                value["change"]["action_invalid_sources_version"] = action_invalid_sources_version
            if action_sequence_version is not None:
                value["change"]["action_sequence_version"] = action_sequence_version
        if interface_append is not None:
            value["change"]["interface_append"] = deepcopy(interface_append)
        if interface_batch is not None:
            value["change"]["interface_batch"] = deepcopy(interface_batch)
        value["content_sha256"] = self._content_sha(value)
        return value

    def _write_committed(self, snapshot: dict[str, Any]) -> None:
        self._validate_snapshot(snapshot)
        logical_id = snapshot["logical_workflow_id"]
        path = self._revision_path(logical_id, snapshot["content_sha256"])
        payload = canonical_json_bytes(snapshot) + b"\n"
        _write_immutable(path, payload)
        relative = (Path("desktop-review") / "graph-revisions" / logical_id / "revisions" / f"{snapshot['content_sha256']}.json").as_posix()
        head = {
            "contract_version": _HEAD_CONTRACT,
            "logical_workflow_id": logical_id,
            "revision": snapshot["revision"],
            "content_sha256": snapshot["content_sha256"],
            "revision_path": relative,
            "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
        }
        _atomic_write_bytes(self._head_path(logical_id), canonical_json_bytes(head) + b"\n")

    def _load_head(self, logical_id: str, *, required: bool) -> dict[str, Any] | None:
        # 同一次历史读取只核验一次相同父来源；绝不跨读取缓存文件真实性。
        previous = getattr(self, "_verified_source_reads", None)
        previous_actions = getattr(self, "_verified_action_source_reads", None)
        self._verified_source_reads = set()
        self._verified_action_source_reads = set()
        try:
            return self._load_head_verified(logical_id, required=required)
        finally:
            self._verified_source_reads = previous
            self._verified_action_source_reads = previous_actions

    def _load_head_verified(self, logical_id: str, *, required: bool) -> dict[str, Any] | None:
        path = self._head_path(logical_id)
        if not path.exists():
            # 已有修订时丢头不能被 create 当成全新图，否则会悄悄回退人工修改。
            if required or (path.parent / "revisions").exists():
                raise DesktopReviewError("图草稿头指针缺失，未自动重建")
            return None
        try:
            head = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("图草稿头指针损坏，未自动重建") from error
        required_fields = {"contract_version", "logical_workflow_id", "revision", "content_sha256", "revision_path", "snapshot_sha256"}
        if not isinstance(head, dict) or set(head) != required_fields or head.get("contract_version") != _HEAD_CONTRACT:
            raise DesktopReviewError("图草稿头指针契约无效")
        if head.get("logical_workflow_id") != logical_id:
            raise DesktopReviewError("图草稿头指针身份不一致")
        sha = _sha(head.get("content_sha256"), "图草稿头摘要")
        revision = _revision(head.get("revision"), "图草稿头修订", allow_zero=False)
        expected_relative = (Path("desktop-review") / "graph-revisions" / logical_id / "revisions" / f"{sha}.json").as_posix()
        if head.get("revision_path") != expected_relative or _sha(head.get("snapshot_sha256"), "图草稿文件摘要") is None:
            raise DesktopReviewError("图草稿头指针路径或摘要无效")
        snapshot = self._load_revision(logical_id, sha)
        if snapshot["revision"] != revision:
            raise DesktopReviewError("图草稿头指针修订不一致")
        raw = self._revision_path(logical_id, sha).read_bytes()
        if hashlib.sha256(raw).hexdigest() != head["snapshot_sha256"]:
            raise DesktopReviewError("图草稿文件摘要不匹配")
        self._validate_chain(snapshot)
        return snapshot

    def _load_revision(self, logical_id: str, sha: str) -> dict[str, Any]:
        path = self._revision_path(logical_id, _sha(sha, "图草稿摘要"))
        if not path.is_file():
            raise DesktopReviewError("图草稿修订文件缺失，未自动重建")
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("图草稿修订内容无效") from error
        self._validate_snapshot(value)
        if value["logical_workflow_id"] != logical_id or value["content_sha256"] != sha:
            raise DesktopReviewError("图草稿修订身份或摘要不一致")
        return value

    def _validate_chain(self, current: dict[str, Any]) -> None:
        child = current
        while child["parent_sha256"] is not None:
            parent = self._load_revision(child["logical_workflow_id"], child["parent_sha256"])
            if parent["revision"] != child["revision"] - 1:
                raise DesktopReviewError("图草稿父修订链不连续或来源不一致")
            if "interface_append" in child["change"]:
                from .workflow_membership import validate_membership_change
                validate_membership_change(self._facade, parent, child)
            elif "interface_batch" in child["change"]:
                from .workflow_membership import validate_membership_batch_change
                validate_membership_batch_change(self._facade, parent, child)
            elif parent["source_refs"] != child["source_refs"]:
                if "action_append" in child["change"]:
                    self._validate_action_append(parent, child)
                else:
                    self._validate_source_append(parent, child)
            child = parent
        if child["revision"] != 1:
            raise DesktopReviewError("图草稿首修订链不完整")

    def _validate_snapshot(self, value: Any) -> None:
        fields = {"contract_version", "logical_workflow_id", "revision", "content_sha256", "parent_sha256", "source_refs", "graph", "change"}
        if not isinstance(value, dict) or set(value) != fields or value.get("contract_version") != _REVISION_CONTRACT:
            raise DesktopReviewError("图草稿修订契约无效")
        self._validate_logical_id(value["logical_workflow_id"])
        revision = _revision(value.get("revision"), "图草稿修订", allow_zero=False)
        sha = _sha(value.get("content_sha256"), "图草稿内容摘要")
        if sha != self._content_sha(value):
            raise DesktopReviewError("图草稿内容摘要不匹配")
        parent = value.get("parent_sha256")
        if (revision == 1 and parent is not None) or (revision > 1 and _sha(parent, "图草稿父摘要") is None):
            raise DesktopReviewError("图草稿父修订引用无效")
        change = value.get("change")
        permitted_changes = (
            {"idempotency_key", "request_sha256"},
            {"idempotency_key", "request_sha256", "adoption"},
            {"idempotency_key", "request_sha256", "source_append"},
            {"idempotency_key", "request_sha256", "action_append"},
            {"idempotency_key", "request_sha256", "action_append", "action_invalid_sources_version"},
            {"idempotency_key", "request_sha256", "action_append", "action_invalid_sources_version", "action_sequence_version"},
            {"idempotency_key", "request_sha256", "interface_append"},
            {"idempotency_key", "request_sha256", "interface_batch"},
        )
        if not isinstance(change, dict) or set(change) not in permitted_changes:
            raise DesktopReviewError("图草稿变更元数据无效")
        if revision == 1:
            if set(change) != {"idempotency_key", "request_sha256"} or change["idempotency_key"] is not None or change["request_sha256"] is not None:
                raise DesktopReviewError("图草稿创建变更元数据无效")
        else:
            _key(change.get("idempotency_key"), "图草稿幂等键")
            _sha(change.get("request_sha256"), "图草稿请求摘要")
            if "adoption" in change:
                self._validate_adoption(value, change["adoption"])
            if "source_append" in change:
                self._validate_source_ref(change["source_append"], allow_additional=False)
            if "action_append" in change:
                if ("action_invalid_sources_version" in change
                        and (type(change["action_invalid_sources_version"]) is not int
                             or change["action_invalid_sources_version"] != 1)):
                    raise DesktopReviewError("图草稿动作无效来源版本不受支持")
                anchor = value["source_refs"].get("fresh_learning_source")
                if anchor is None and value["source_refs"].get("kind") == "recorded_actions":
                    anchor = value["source_refs"]
                self._validate_action_source(change["action_append"], anchor)
                if ("action_sequence_version" in change
                        and (type(change["action_sequence_version"]) is not int
                             or change["action_sequence_version"] != 1)):
                    raise DesktopReviewError("图草稿动作顺序版本不受支持")
        self._validate_source_refs(value["source_refs"])
        self._validate_graph(value["graph"], value["source_refs"])

    def _validate_adoption(self, child: dict[str, Any], adoption: Any) -> None:
        fields = {"candidate", "candidate_sha256", "issue_id", "baseline_graph_sha256", "review_baseline_sha256", "request_sha256", "issue"}
        if not isinstance(adoption, dict) or set(adoption) != fields:
            raise DesktopReviewError("图草稿采用血缘无效")
        from app.agent_link.contracts import canonical_hash, validate_candidate
        from app.agent_link.graph_contract import graph_issue_id, validate_graph_scope
        from app.agent_link.review_baseline import candidate_content_sha256
        candidate = adoption.get("candidate")
        stored_fields = {"candidate_id", "connection_id", "status", "candidate_sha256"}
        if not isinstance(candidate, dict) or not stored_fields <= set(candidate):
            raise DesktopReviewError("图草稿采用候选摘要无效")
        wire = {key: deepcopy(value) for key, value in candidate.items() if key not in stored_fields}
        try:
            normalized = validate_candidate(wire)
        except Exception as error:
            raise DesktopReviewError("图草稿采用候选契约无效") from error
        if normalized != wire or set(candidate) != set(wire) | stored_fields:
            raise DesktopReviewError("图草稿采用候选字段无效")
        candidate_sha = candidate_content_sha256(candidate)
        if any((candidate_sha != adoption.get("candidate_sha256"),
                candidate.get("candidate_sha256") != candidate_sha,
                candidate.get("status") != "pending_review_proposal",
                not isinstance(candidate.get("candidate_id"), str), not candidate["candidate_id"].startswith("candidate-"),
                not isinstance(candidate.get("connection_id"), str), not candidate["connection_id"])):
            raise DesktopReviewError("图草稿采用候选摘要无效")
        if candidate.get("issue_id") != adoption.get("issue_id") or candidate.get("review_baseline_sha256") != adoption.get("review_baseline_sha256"):
            raise DesktopReviewError("图草稿采用候选身份无效")
        parent = self._load_revision(child["logical_workflow_id"], child["parent_sha256"])
        refs = parent["source_refs"]
        baseline = {
            "contract_version": "desktop_graph_review_baseline_v1",
            "task_id": refs["task_id"], "batch_id": refs["batch_id"],
            "logical_workflow_id": parent["logical_workflow_id"],
            "revision": parent["revision"], "graph_sha256": parent["content_sha256"],
            "snapshot": deepcopy(parent),
        }
        baseline_sha = canonical_hash(baseline)
        if any((parent["content_sha256"] != adoption.get("baseline_graph_sha256"),
                candidate.get("baseline_graph_sha256") != parent["content_sha256"],
                candidate.get("logical_workflow_id") != child["logical_workflow_id"],
                candidate.get("batch_id") != refs["batch_id"],
                candidate.get("review_baseline_sha256") != baseline_sha,
                adoption.get("review_baseline_sha256") != baseline_sha)):
            raise DesktopReviewError("图草稿采用父基线无效")
        issue = adoption.get("issue")
        issue_fields = {"issue_id", "scope", "message", "baseline_revision"}
        if not isinstance(issue, dict) or set(issue) != issue_fields or issue.get("issue_id") != candidate["issue_id"] or issue.get("scope") != candidate["scope"] or issue.get("baseline_revision") != candidate["baseline_revision"] or not isinstance(issue.get("message"), str) or not issue["message"]:
            raise DesktopReviewError("图草稿采用问题血缘无效")
        try:
            scope = validate_graph_scope(candidate["scope"], parent["graph"])
            expected_issue_id = graph_issue_id(
                logical_workflow_id=parent["logical_workflow_id"], graph_revision=parent["revision"],
                graph_sha256=parent["content_sha256"], feedback_revision=issue["baseline_revision"] - 1,
                scope=scope, message=issue["message"],
            )
        except (GraphContractError, TypeError, ValueError) as error:
            raise DesktopReviewError("图草稿采用问题血缘无效") from error
        if issue["baseline_revision"] < 1 or expected_issue_id != issue["issue_id"]:
            raise DesktopReviewError("图草稿采用问题身份无效")
        user_request = {
            "logical_workflow_id": child["logical_workflow_id"], "expected_revision": parent["revision"],
            "expected_graph_sha256": parent["content_sha256"], "candidate_id": candidate["candidate_id"],
            "expected_candidate_sha256": candidate_sha,
            "expected_review_baseline_sha256": baseline_sha,
            "idempotency_key": child["change"]["idempotency_key"],
        }
        if canonical_hash(user_request) != adoption.get("request_sha256"):
            raise DesktopReviewError("图草稿采用请求摘要无效")
        commit_request = {
            "logical_workflow_id": child["logical_workflow_id"], "expected_revision": parent["revision"],
            "expected_graph_sha256": parent["content_sha256"], "operations": candidate["changes"],
            "scope": candidate["scope"], "adoption": adoption,
        }
        if hashlib.sha256(canonical_json_bytes(commit_request)).hexdigest() != child["change"]["request_sha256"]:
            raise DesktopReviewError("图草稿采用提交摘要无效")
        try:
            checked = validate_graph_operations(candidate["changes"], parent["graph"], scope)
            if apply_graph_operations(parent["graph"], checked) != child["graph"]:
                raise DesktopReviewError("图草稿采用语义与子修订不一致")
        except GraphContractError as error:
            raise DesktopReviewError("图草稿采用操作无效") from error

    def _validate_source_refs(self, refs: Any) -> None:
        if isinstance(refs, dict) and refs.get("kind") == "recorded_actions":
            fields = {"kind", "connection_id", "task_id", "segment_id", "anchor_event_id",
                      "anchor_source_sha256", "action_sources"}
            if set(refs) != fields:
                raise DesktopReviewError("动作图来源引用字段无效")
            for key in ("connection_id", "task_id", "segment_id", "anchor_event_id"):
                if not isinstance(refs.get(key), str) or not refs[key]:
                    raise DesktopReviewError("动作图来源身份无效")
            _sha(refs.get("anchor_source_sha256"), "动作图锚点摘要")
            actions = refs.get("action_sources")
            if not isinstance(actions, list) or not actions:
                raise DesktopReviewError("动作图至少需要一个权威动作来源")
            if (actions[0].get("event_id") != refs["anchor_event_id"]
                    or actions[0].get("source_sha256") != refs["anchor_source_sha256"]):
                raise DesktopReviewError("动作图首事件与锚点不一致")
            seen = set()
            for action in actions:
                self._validate_action_source(action, refs)
                event_id = action.get("event_id")
                if not isinstance(event_id, str) or event_id in seen:
                    raise DesktopReviewError("动作图来源事件重复")
                seen.add(event_id)
            return
        if isinstance(refs, dict) and refs.get("kind") == "interface_composition":
            if set(refs) != {"kind", "task_id", "interfaces"}:
                raise DesktopReviewError("界面组合来源引用字段无效")
            if not isinstance(refs["task_id"], str) or not refs["task_id"]:
                raise DesktopReviewError("界面组合来源 task_id 无效")
            if not isinstance(refs["interfaces"], list):
                raise DesktopReviewError("界面组合来源列表无效")
            for item in refs["interfaces"]:
                if not isinstance(item, dict) or set(item) != {"interface_id", "version_id", "content_sha256"}:
                    raise DesktopReviewError("界面组合引用字段无效")
                if any(not isinstance(item[key], str) or not item[key] for key in item):
                    raise DesktopReviewError("界面组合引用值无效")
            return
        fields = {"task_id", "batch_id", "batch_sha256", "original_batch_path", "original_batch_sha256", "screenshots", "imported_workspace"}
        if isinstance(refs, dict) and "interface_composition" in refs:
            fields.add("interface_composition")
        if isinstance(refs, dict) and "fresh_learning_source" in refs:
            fields.add("fresh_learning_source")
        if isinstance(refs, dict) and "additional_sources" in refs:
            fields.add("additional_sources")
        if isinstance(refs, dict) and "action_sources" in refs:
            fields.add("action_sources")
        if not isinstance(refs, dict) or set(refs) != fields:
            raise DesktopReviewError("图草稿来源引用无效")
        self._validate_source_ref(refs, allow_additional=True)
        composition = refs.get("interface_composition", [])
        if not isinstance(composition, list):
            raise DesktopReviewError("界面组合来源引用无效")
        for item in composition:
            if not isinstance(item, dict) or set(item) != {"interface_id", "version_id", "content_sha256"}:
                raise DesktopReviewError("界面组合引用字段无效")
        additional = refs.get("additional_sources", [])
        if not isinstance(additional, list):
            raise DesktopReviewError("图草稿追加来源引用无效")
        if not additional:
            if "additional_sources" in refs:
                raise DesktopReviewError("图草稿追加来源引用无效")
        base_fresh = refs.get("fresh_learning_source")
        if additional and base_fresh is None:
            raise DesktopReviewError("图草稿追加来源必须建立在 fresh 学习观察上")
        seen = {refs["batch_id"]}
        for extra in additional:
            self._validate_source_ref(extra, allow_additional=False)
            if (extra["task_id"] != refs["task_id"]
                    or extra.get("fresh_learning_source", {}).get("connection_id") != base_fresh["connection_id"]
                    or extra.get("fresh_learning_source", {}).get("segment_id") != base_fresh["segment_id"]):
                raise DesktopReviewError("图草稿追加来源不属于同一学习段")
            identity = extra["batch_id"]
            if identity in seen:
                raise DesktopReviewError("图草稿追加来源重复")
            seen.add(identity)
        actions = refs.get("action_sources", [])
        if not isinstance(actions, list) or not actions:
            if "action_sources" in refs:
                raise DesktopReviewError("图草稿动作来源引用无效")
            return
        if base_fresh is None:
            raise DesktopReviewError("missing_observation_anchor: 动作来源需要 fresh 学习观察")
        seen_events: set[str] = set()
        for action in actions:
            self._validate_action_source(action, base_fresh)
            event_id = action.get("event_id") if isinstance(action, dict) else None
            if not isinstance(event_id, str) or event_id in seen_events:
                raise DesktopReviewError("图草稿动作来源事件重复")
            seen_events.add(event_id)

    def _validate_action_source(self, source: Any, base_fresh: Any) -> None:
        if not isinstance(base_fresh, dict):
            raise DesktopReviewError("missing_observation_anchor: 动作来源需要 fresh 学习观察")
        from .action_graph_source import ActionGraphSourceReader

        if not isinstance(source, dict):
            raise DesktopReviewError("图草稿动作来源引用无效")
        if not isinstance(source.get("source_sha256"), str):
            raise DesktopReviewError("图草稿动作来源摘要无效")
        key = canonical_json_bytes({"source": source, "base_fresh": base_fresh})
        verified = getattr(self, "_verified_action_source_reads", None)
        if verified is not None and key in verified:
            return
        try:
            ActionGraphSourceReader(self._facade).validate(source, base_fresh)
        except (TypeError, ValueError, OSError) as error:
            raise DesktopReviewError("图草稿动作来源无法验证") from error
        if verified is not None:
            verified.add(key)

    def _validate_source_ref(self, refs: Any, *, allow_additional: bool) -> None:
        if not isinstance(refs, dict):
            raise DesktopReviewError("图草稿来源引用无效")
        if "node_id_scheme" in refs and (
            allow_additional or refs["node_id_scheme"] != "sha256_v2"
        ):
            raise DesktopReviewError("图草稿追加来源 node_id_scheme 无效")
        if not allow_additional and (
            "additional_sources" in refs or "action_sources" in refs
        ):
            raise DesktopReviewError("图草稿追加来源不得嵌套")
        key = canonical_json_bytes({
            name: value for name, value in refs.items()
            if name not in {"additional_sources", "action_sources"}
        })
        verified = getattr(self, "_verified_source_reads", None)
        if verified is not None and key in verified:
            return
        self._validate_source_ref_bytes(refs)
        if verified is not None:
            verified.add(key)

    def _validate_source_ref_bytes(self, refs: dict[str, Any]) -> None:
        task, batch = _text(refs.get("task_id"), "图草稿来源 task_id"), _text(refs.get("batch_id"), "图草稿来源 batch_id")
        source_ref = _sha(refs.get("batch_sha256"), "图草稿来源摘要")
        relative = (Path("desktop-review") / "sources" / source_ref / "original_batch.json").as_posix()
        if refs.get("original_batch_path") != relative or _sha(refs.get("original_batch_sha256"), "图草稿原始批次摘要") is None:
            raise DesktopReviewError("图草稿原始批次路径或摘要无效")
        path = (self._facade._artifact_root / relative).resolve()
        if not _inside(self._facade._workspace_root, path) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != refs["original_batch_sha256"]:
            raise DesktopReviewError("图草稿原始批次证据缺失或被篡改")
        try:
            original = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("图草稿原始批次证据无效") from error
        if not isinstance(original, dict) or original.get("batch_id") != batch or source_ref_for_batch(original) != source_ref:
            raise DesktopReviewError("图草稿原始批次身份或摘要不一致")
        fresh_source = self._facade._fresh_source_for_batch(task, batch, original)
        if refs.get("fresh_learning_source") != fresh_source:
            raise DesktopReviewError("图草稿原始学习观察引用不一致，不能降级为普通外部来源")
        # 已有归档校验先于大图规范化；同次读取不重复获取权威来源。
        allowed = frozenset({fresh_source["reference"]["screenshot_sha256"]}) if fresh_source is not None else frozenset()
        try:
            original = normalize_agent_link_batch(original, existing_png_sha256=allowed)
        except ValueError as error:
            raise DesktopReviewError("图草稿原始批次不满足来源契约") from error
        if original["batch_id"] != batch or source_ref_for_batch(original) != source_ref:
            raise DesktopReviewError("图草稿原始批次身份或摘要不一致")
        imported = self._validate_imported_workspace(refs, original)
        expected_batch = original if imported is None else imported["batch"]
        screenshots = refs.get("screenshots")
        if not isinstance(screenshots, list) or len(screenshots) != len(expected_batch["screenshots"]):
            raise DesktopReviewError("图草稿截图来源引用无效")
        expected = {item["screenshot_id"]: item for item in expected_batch["screenshots"]}
        for item in screenshots:
            if not isinstance(item, dict) or set(item) != {"screenshot_id", "path", "sha256", "width", "height"}:
                raise DesktopReviewError("图草稿截图引用字段无效")
            source = expected.get(item.get("screenshot_id"))
            if source is None or any(item.get(field) != source[field] for field in ("sha256", "width", "height")):
                raise DesktopReviewError("图草稿截图引用与原始证据不一致")
            relative_image = source_image_relative_path(source_ref, source)
            if item.get("path") != relative_image:
                raise DesktopReviewError("图草稿截图路径不是规范持久路径")
            image = (self._facade._artifact_root / relative_image).resolve()
            if not _inside(self._facade._workspace_root, image) or not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != source["sha256"]:
                raise DesktopReviewError("图草稿截图证据缺失或被篡改")

    def _validate_imported_workspace(
        self, refs: dict[str, Any], original: dict[str, Any],
    ) -> dict[str, Any] | None:
        imported = refs["imported_workspace"]
        if imported is None:
            return None
        if not isinstance(imported, dict) or set(imported) != {"revision", "workspace_path", "workspace_sha256"}:
            raise DesktopReviewError("图草稿导入工作区引用无效")
        revision = _revision(imported.get("revision"), "图草稿导入工作区修订", allow_zero=False)
        workspace_sha = _sha(imported.get("workspace_sha256"), "图草稿导入工作区摘要")
        relative = Path("desktop-review") / "workspaces" / self._facade._workspace_key(refs["task_id"], refs["batch_id"])
        supplied = imported.get("workspace_path")
        if not isinstance(supplied, str) or not supplied.startswith(relative.as_posix() + "/"):
            raise DesktopReviewError("图草稿导入工作区路径无效")
        path = (self._facade._artifact_root / supplied).resolve()
        if not _inside(self._facade._workspace_root, path) or not path.is_file():
            raise DesktopReviewError("图草稿导入工作区修订文件缺失")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != workspace_sha:
            raise DesktopReviewError("图草稿导入工作区修订摘要不匹配")
        try:
            snapshot = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("图草稿导入工作区修订内容无效") from error
        _validate_snapshot(snapshot, existing_png_sha256=frozenset(item["sha256"] for item in original["screenshots"]))
        expected_relative = self._facade._snapshot_relative_path(snapshot).as_posix()
        if supplied != expected_relative or any((
            snapshot["task_id"] != refs["task_id"],
            snapshot["batch_id"] != refs["batch_id"],
            snapshot["source_ref"] != refs["batch_sha256"],
            snapshot["revision"] != revision,
        )):
            raise DesktopReviewError("图草稿导入工作区修订身份不一致")
        self._facade._validated_revision_chain(snapshot)
        return snapshot

    def _all_source_refs(self, refs: dict[str, Any]) -> list[dict[str, Any]]:
        return [refs, *refs.get("additional_sources", [])]

    def _source_screenshots(self, refs: dict[str, Any]) -> list[dict[str, Any]]:
        all_shots = [] if refs.get("kind") == "recorded_actions" else [
            shot for source in self._all_source_refs(refs) for shot in source["screenshots"]]
        for source in refs.get("action_sources", []):
            if not isinstance(source, dict) or not isinstance(source.get("screenshots"), list):
                raise DesktopReviewError("图草稿动作截图来源无效")
            all_shots.extend(source["screenshots"])
        by_path: dict[str, dict[str, Any]] = {}
        for shot in all_shots:
            if not isinstance(shot, dict) or not isinstance(shot.get("path"), str):
                raise DesktopReviewError("图草稿截图来源无效")
            previous = by_path.get(shot["path"])
            if previous is not None and previous != shot:
                raise DesktopReviewError("图草稿相同截图路径引用不一致")
            by_path[shot["path"]] = shot
        return list(by_path.values())

    def _fresh_source_ref(self, task: str, batch: str, source_ref: str, original: dict[str, Any]) -> dict[str, Any]:
        loaded = self._facade.load_batch(task, batch)
        if loaded["revision"] != 0:
            raise DesktopReviewError("追加 fresh 来源不得导入可编辑工作区修订")
        refs = self._source_refs(task, batch, source_ref, original, loaded["batch"], None)
        refs["node_id_scheme"] = "sha256_v2"
        return refs

    def _first_segment_batch(self, fresh: dict[str, Any], task: str, requested_batch: str) -> str:
        store = getattr(self._facade._service, "_store", None)
        if store is None or not hasattr(store, "read"):
            raise DesktopReviewError("fresh_source_unavailable: 无法读取同段观察元数据")
        try:
            observations = store.read(lambda state: deepcopy(
                state["connections"][fresh["connection_id"]]["learning_segments"][fresh["segment_id"]].get("observations", [])
            ))
        except (KeyError, TypeError, ValueError) as error:
            raise DesktopReviewError("fresh_source_unavailable: 同段观察元数据缺失") from error
        if not isinstance(observations, list) or not observations:
            raise DesktopReviewError("fresh_source_unavailable: 同段观察元数据无效")
        for item in observations:
            if (not isinstance(item, dict) or set(item) != {"batch_id", "source"}
                    or not isinstance(item["source"], dict)
                    or item["source"].get("connection_id") != fresh["connection_id"]
                    or item["source"].get("task_id") != task
                    or item["source"].get("segment_id") != fresh["segment_id"]):
                raise DesktopReviewError("fresh_source_unavailable: 同段观察范围无效")
        matches = [item for item in observations if item["batch_id"] == requested_batch]
        if len(matches) != 1 or matches[0]["source"] != fresh:
            raise DesktopReviewError("fresh_source_unavailable: 请求批次不是段内确切来源成员")
        first = observations[0]
        first_id = _text(first["batch_id"], "首个 fresh batch_id")
        original = self._facade._load_source_batch(task, first_id)
        if self._facade._fresh_source_for_batch(task, first_id, original) != first["source"]:
            raise DesktopReviewError("fresh_source_unavailable: 首批来源与段清单不一致")
        return first_id

    def _assert_append_scope(self, current: dict[str, Any], candidate: dict[str, Any]) -> None:
        base = current["source_refs"]
        fresh = base.get("fresh_learning_source")
        target = candidate.get("fresh_learning_source")
        if fresh is None or target is None or any((
            candidate["task_id"] != base["task_id"],
            target["connection_id"] != fresh["connection_id"],
            target["task_id"] != fresh["task_id"],
            target["segment_id"] != fresh["segment_id"],
        )):
            raise DesktopReviewError("fresh_source_scope_mismatch: 追加来源不属于图的同一连接、任务和段")
        if self._first_segment_batch(target, candidate["task_id"], candidate["batch_id"]) != base["batch_id"]:
            raise DesktopReviewError("fresh_source_scope_mismatch: 追加来源未绑定到段首图")

    def _nodes_for_source(self, refs: dict[str, Any], task_id: str, revision: int) -> list[dict[str, Any]]:
        path = self._facade._artifact_root / refs["original_batch_path"]
        try:
            batch = self._facade._normalize_source_copy(
                json.loads(path.read_text(encoding="utf-8-sig")), refs["task_id"], refs["batch_id"], refs["batch_sha256"],
            )
            graph = build_external_workflow_review(batch=batch, task_id=task_id, source_ref=refs["batch_sha256"], revision=revision)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise DesktopReviewError("图草稿追加来源无法重放") from error
        nodes = deepcopy(graph["nodes"])
        if refs.get("node_id_scheme") == "sha256_v2":
            # 完整摘要保留来源隔离，避免两个摘要拼接后超过审核目录组件上限。
            node_ids = {node["node_id"]: "interface-" + hashlib.sha256(canonical_json_bytes({
                "node_id": node["node_id"], "batch_sha256": refs["batch_sha256"],
            })).hexdigest() for node in nodes}
        elif "node_id_scheme" not in refs:
            # 旧不可变图按原算法重放，不以修复代码静默改写其节点身份。
            node_ids = {node["node_id"]: f"{node['node_id']}-{refs['batch_sha256']}" for node in nodes}
        else:
            raise DesktopReviewError("图草稿追加来源 node_id_scheme 无效")
        for node in nodes:
            node["node_id"] = node_ids[node["node_id"]]
            for action in node.get("action_candidates", []):
                if action.get("target_node_id") in node_ids:
                    action["target_node_id"] = node_ids[action["target_node_id"]]
        return nodes

    def _validate_source_append(self, parent: dict[str, Any], child: dict[str, Any]) -> None:
        change = child["change"]
        added = change.get("source_append")
        if not isinstance(added, dict):
            raise DesktopReviewError("图草稿来源变更未明确标记为 source_append")
        before, after = parent["source_refs"], child["source_refs"]
        if {key: value for key, value in after.items() if key != "additional_sources"} != {key: value for key, value in before.items() if key != "additional_sources"}:
            raise DesktopReviewError("图草稿 source_append 不得改写既有来源")
        old = before.get("additional_sources", [])
        new = after.get("additional_sources", [])
        if not isinstance(old, list) or not isinstance(new, list) or new != [*old, added]:
            raise DesktopReviewError("图草稿 source_append 必须只追加一个来源")
        expected_nodes = self._nodes_for_source(added, after["task_id"], parent["revision"])
        expected_graph = deepcopy(parent["graph"])
        expected_graph["nodes"].extend(expected_nodes)
        expected_graph["workflow"]["node_ids"].extend(item["node_id"] for item in expected_nodes)
        if child["graph"] != expected_graph:
            raise DesktopReviewError("图草稿 source_append 重放结果不一致")
        expected_request = hashlib.sha256(canonical_json_bytes({
            "logical_workflow_id": child["logical_workflow_id"], "parent_sha256": parent["content_sha256"], "source": added,
        })).hexdigest()
        if change.get("request_sha256") != expected_request:
            raise DesktopReviewError("图草稿 source_append 请求摘要无效")

    def _validate_action_append(self, parent: dict[str, Any], child: dict[str, Any]) -> None:
        change = child["change"]
        added = change.get("action_append")
        if not isinstance(added, dict):
            raise DesktopReviewError("图草稿动作来源变更未明确标记为 action_append")
        before, after = parent["source_refs"], child["source_refs"]
        if {key: value for key, value in after.items() if key != "action_sources"} != {
            key: value for key, value in before.items() if key != "action_sources"
        }:
            raise DesktopReviewError("图草稿 action_append 不得改写既有来源")
        old, new = before.get("action_sources", []), after.get("action_sources", [])
        if not isinstance(old, list) or not isinstance(new, list) or new != [*old, added]:
            raise DesktopReviewError("图草稿 action_append 必须只追加一个动作来源")
        from .action_graph_source import action_sequence_metadata, project_action_source

        projected = project_action_source(added)
        if not isinstance(projected, dict) or set(projected) != {"nodes", "edges", "invalid_sources"}:
            raise DesktopReviewError("图草稿 action_append 投影无效")
        expected_graph = deepcopy(parent["graph"])
        expected_graph["nodes"].extend(deepcopy(projected["nodes"]))
        expected_graph["edges"].extend(deepcopy(projected["edges"]))
        sequence_version = change.get("action_sequence_version")
        if sequence_version is not None and sequence_version != 1:
            raise DesktopReviewError("图草稿动作顺序版本不受支持")
        if sequence_version == 1:
            expected_graph["action_sequence"] = action_sequence_metadata(new)
        if "action_invalid_sources_version" in change:
            if (type(change["action_invalid_sources_version"]) is not int
                    or change["action_invalid_sources_version"] != 1):
                raise DesktopReviewError("图草稿动作无效来源版本不受支持")
            expected_graph["invalid_sources"].extend(deepcopy(projected["invalid_sources"]))
        expected_graph["workflow"]["node_ids"].extend(item["node_id"] for item in projected["nodes"])
        expected_graph["workflow"]["edge_ids"].extend(item["edge_id"] for item in projected["edges"])
        if child["graph"] != expected_graph:
            raise DesktopReviewError("图草稿 action_append 重放结果不一致")
        expected_request = hashlib.sha256(canonical_json_bytes({
            "logical_workflow_id": child["logical_workflow_id"],
            "parent_sha256": parent["content_sha256"], "source": added,
        })).hexdigest()
        if change.get("request_sha256") != expected_request:
            raise DesktopReviewError("图草稿 action_append 请求摘要无效")

    def _validate_graph(self, graph: Any, refs: dict[str, Any]) -> None:
        if not isinstance(graph, dict) or graph.get("display_only") is not True or graph.get("artifact_is_authorization") is not False or graph.get("execute_binding_enabled") is not False:
            raise DesktopReviewError("图草稿不得获得执行或批准权限")
        source = graph.get("source")
        if refs.get("kind") == "interface_composition":
            if not isinstance(source, dict) or source.get("kind") != "interface_composition" or source.get("task_id") != refs["task_id"]:
                raise DesktopReviewError("界面组合图来源与 task 不一致")
        elif refs.get("kind") == "recorded_actions":
            expected = {key: refs[key] for key in ("connection_id", "task_id", "segment_id",
                                                   "anchor_event_id", "anchor_source_sha256")}
            if (not isinstance(source, dict) or source.get("kind") != "recorded_actions"
                    or any(source.get(key) != value for key, value in expected.items())):
                raise DesktopReviewError("动作图来源与权威首事件不一致")
        elif not isinstance(source, dict) or any(source.get(key) != expected for key, expected in (("kind", "untrusted_external"), ("task_id", refs["task_id"]), ("batch_id", refs["batch_id"]), ("batch_sha256", refs["batch_sha256"]))):
            raise DesktopReviewError("图草稿来源与不可变证据不一致")
        if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
            raise DesktopReviewError("图草稿节点或边无效")
        from .workflow_membership import validate_reference_projection
        validate_reference_projection(self._facade, graph, refs)
        shots = {item["path"]: item for item in self._source_screenshots(refs)} if refs.get("kind") != "interface_composition" else {}
        node_ids = []
        for node in graph["nodes"]:
            if not isinstance(node, dict) or not isinstance(node.get("node_id"), str):
                raise DesktopReviewError("图草稿节点无效")
            node_ids.append(node["node_id"])
            if refs.get("kind") == "interface_composition":
                reference = node.get("interface_reference")
                if not isinstance(reference, dict) or set(reference) != {"interface_id", "version_id", "content_sha256"}:
                    raise DesktopReviewError("界面组合节点引用无效")
                if reference not in refs["interfaces"]:
                    raise DesktopReviewError("界面组合节点引用未登记")
                continue
            if "interface_reference" in node:
                reference = node.get("interface_reference")
                if not isinstance(reference, dict) or reference not in refs.get("interface_composition", []):
                    raise DesktopReviewError("界面组合节点引用未登记")
                continue
            evidence = node.get("evidence", {})
            shot = shots.get(evidence.get("source_screenshot_path"))
            if shot is None or evidence.get("source_screenshot_sha256") != shot["sha256"]:
                raise DesktopReviewError("图草稿节点截图来源无效")
            try:
                validate_node_recognition_anchor(node)
            except GraphContractError as error:
                raise DesktopReviewError(str(error)) from error
            if "recognition_anchor" in node and not _valid_bbox(
                    node["recognition_anchor"]["bbox"], shot["width"], shot["height"]):
                raise DesktopReviewError("识别文字区域必须在绑定原图范围内")
        if len(node_ids) != len(set(node_ids)) or graph.get("workflow", {}).get("node_ids") != node_ids:
            raise DesktopReviewError("图草稿 workflow 节点列表无效")

    def _assert_same_source(self, snapshot: dict[str, Any], task: str, batch: str, source_ref: str) -> None:
        refs = snapshot["source_refs"]
        if refs["task_id"] != task or refs["batch_id"] != batch or refs["batch_sha256"] != source_ref:
            raise DesktopReviewError("同一逻辑图草稿已绑定冲突来源")

    def _find_idempotency(self, current: dict[str, Any], key: str, request_sha: str) -> dict[str, Any] | None:
        item = current
        while True:
            change = item["change"]
            if change["idempotency_key"] == key:
                if change["request_sha256"] != request_sha:
                    raise DesktopReviewError("idempotency_key 已用于不同图草稿请求")
                return item
            parent = item["parent_sha256"]
            if parent is None:
                return None
            item = self._load_revision(item["logical_workflow_id"], parent)

    def _update_edge_target(self, graph: dict[str, Any], operation: dict[str, Any]) -> None:
        edge = _one(graph["edges"], "edge_id", operation["edge_id"], "edge")
        node = _one(graph["nodes"], "node_id", operation["target_node_id"], "目标节点")
        target_changed = edge["target_node_id"] != node["node_id"]
        edge["target_node_id"] = node["node_id"]
        if target_changed:
            _mark_retargeted(edge)
        relationships = edge.get("external_relationships", [])
        if relationships is not None:
            if not isinstance(relationships, list) or any(not isinstance(item, dict) for item in relationships):
                raise DesktopReviewError("图草稿边关系绑定无效")
            for relation in relationships:
                relation["to_interface_id"] = node["external_interface_id"]
                if target_changed:
                    _mark_retargeted(relation)
        external_step = edge.get("external_step_id")
        for candidate_node in graph["nodes"]:
            actions = candidate_node.get("action_candidates", [])
            if not isinstance(actions, list):
                raise DesktopReviewError("图草稿动作候选无效")
            for action in actions:
                if isinstance(action, dict) and action.get("external_step_id") == external_step:
                    action["target_node_id"] = node["node_id"]
                    if target_changed:
                        _mark_retargeted(action)

    def _update_region_bbox(self, graph: dict[str, Any], refs: dict[str, Any], operation: dict[str, Any]) -> None:
        node = _one(graph["nodes"], "node_id", operation["node_id"], "节点")
        evidence = node.get("evidence")
        if not isinstance(evidence, dict):
            raise DesktopReviewError("图草稿节点截图证据无效")
        source_path = evidence.get("source_screenshot_path")
        if not isinstance(source_path, str) or not source_path:
            raise DesktopReviewError("图草稿节点截图路径无效")
        shot = _one(self._source_screenshots(refs), "path", source_path, "截图")
        if evidence.get("source_screenshot_sha256") != shot["sha256"]:
            raise DesktopReviewError("图草稿节点截图路径与摘要不一致")
        bbox = operation["bbox"]
        if not _valid_bbox(bbox, shot["width"], shot["height"]):
            raise DesktopReviewError("图草稿区域框必须为图像范围内的有限正尺寸坐标")
        region = _one(node.get("regions"), "region_id", operation["region_id"], "区域")
        region["bbox"] = deepcopy(bbox)
        controls = node.get("controls", [])
        if not isinstance(controls, list):
            raise DesktopReviewError("图草稿控件无效")
        for control in controls:
            if isinstance(control, dict) and (control.get("region_id") == operation["region_id"] or control.get("control_id") == operation["region_id"]):
                control["bbox"] = deepcopy(bbox)

    def _content_sha(self, snapshot: dict[str, Any]) -> str:
        content = deepcopy(snapshot)
        content.pop("content_sha256", None)
        return hashlib.sha256(canonical_json_bytes(content)).hexdigest()

    def _validate_logical_id(self, value: Any) -> str:
        if not isinstance(value, str) or not _LOGICAL_ID.fullmatch(value):
            raise DesktopReviewError("logical_workflow_id 必须是受限的规范 ASCII 标识")
        return value

    def _revision_path(self, logical_id: str, sha: str) -> Path:
        path = self._root / self._validate_logical_id(logical_id) / "revisions" / f"{_sha(sha, '图草稿摘要')}.json"
        resolved = path.resolve()
        if not _inside(self._facade._workspace_root, resolved):
            raise DesktopReviewError("图草稿修订路径越界")
        return resolved

    def _head_path(self, logical_id: str) -> Path:
        path = self._root / self._validate_logical_id(logical_id) / "draft_head.json"
        resolved = path.resolve()
        if not _inside(self._facade._workspace_root, resolved):
            raise DesktopReviewError("图草稿头指针路径越界")
        return resolved


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512 or any(ord(char) < 32 for char in value):
        raise DesktopReviewError(f"{label} 无效")
    return value.strip()


def _key(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _KEY.fullmatch(value) or value.casefold() in {"con", "prn", "aux", "nul"}:
        raise DesktopReviewError(f"{label} 必须是受限的非保留 ASCII 标识")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise DesktopReviewError(f"{label} 必须是 SHA-256 十六进制摘要")
    return value


def _revision(value: Any, label: str, *, allow_zero: bool) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise DesktopReviewError(f"{label} 必须是{'非负' if allow_zero else '正'}整数")
    return value


def _operation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise DesktopReviewError("图草稿操作无效")
    if value["type"] == "update_edge_target":
        if set(value) != {"type", "edge_id", "target_node_id"}:
            raise DesktopReviewError("update_edge_target 操作字段无效")
        return {"type": "update_edge_target", "edge_id": _text(value["edge_id"], "edge_id"), "target_node_id": _text(value["target_node_id"], "target_node_id")}
    if value["type"] == "update_region_bbox":
        if set(value) != {"type", "node_id", "region_id", "bbox"}:
            raise DesktopReviewError("update_region_bbox 操作字段无效")
        bbox = value["bbox"]
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise DesktopReviewError("bbox 必须为四个数值")
        return {"type": "update_region_bbox", "node_id": _text(value["node_id"], "node_id"), "region_id": _text(value["region_id"], "region_id"), "bbox": deepcopy(bbox)}
    if value["type"] == "update_node_meaning":
        if set(value) != {"type", "node_id", "meaning"}:
            raise DesktopReviewError("update_node_meaning 操作字段无效")
        return {"type": "update_node_meaning", "node_id": _text(value["node_id"], "node_id"), "meaning": _text(value["meaning"], "meaning")}
    if value["type"] == "update_node_recognition_text":
        fields = {"type", "node_id", "recognition_text", "source_screenshot_path",
                  "source_screenshot_sha256", "bbox"}
        if set(value) != fields:
            raise DesktopReviewError("update_node_recognition_text 操作字段无效")
        return deepcopy(value)
    if value["type"] == "update_edge_semantics":
        fields = {"type", "edge_id", "expected_result", "stop_condition", "prerequisites", "relationship_kinds"}
        if set(value) != fields:
            raise DesktopReviewError("update_edge_semantics 操作字段无效")
        return deepcopy(value)
    raise DesktopReviewError("不支持的图草稿操作")


def _one(items: Any, key: str, expected: Any, label: str) -> dict[str, Any]:
    if not isinstance(items, list):
        raise DesktopReviewError(f"图草稿{label}集合无效")
    found = [item for item in items if isinstance(item, dict) and item.get(key) == expected]
    if len(found) != 1:
        raise DesktopReviewError(f"图草稿{label}引用不存在或不唯一")
    return found[0]


def _mark_retargeted(value: dict[str, Any]) -> None:
    """改目标后保留原语义文本，仅明确要求人工重新核对。"""
    value["target_semantics_status"] = "stale_after_retarget"
    value["requires_semantic_review"] = True


def _valid_bbox(value: list[Any], width: Any, height: Any) -> bool:
    if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return False
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in value):
        return False
    x, y, box_width, box_height = value
    return x >= 0 and y >= 0 and box_width > 0 and box_height > 0 and x + box_width <= width and y + box_height <= height
