"""原生审核 façade：只读取 inbox，并把人工草稿保存为不可覆盖修订。"""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any
from uuid import uuid4
from .observation_timing import observation_span, timed_observation

from app.learn.interface_workflow_review import (
    build_interface_node_review_source_payload,
    save_interface_workflow_review_candidate,
)

from .external_mapping import (
    ExternalMappingError,
    assert_source_identity,
    build_external_workflow_review,
    canonical_json_bytes,
    normalize_agent_link_batch,
    source_image_relative_path,
    source_ref_for_batch,
)


_WORKSPACE_CONTRACT = "desktop_review_workspace_v1"
_WORKSPACE_CONTRACT_V2 = "desktop_review_workspace_v2"
_CURRENT_CONTRACT = "desktop_review_current_v1"


class DesktopReviewError(RuntimeError):
    """不泄露 reviewer 密钥的桌面审核失败。"""


class NativeReviewFacade:
    def __init__(self, inbox_service, reviewer_token: str, artifact_root: Path):
        if not hasattr(inbox_service, "reviewer_call"):
            raise TypeError("inbox_service 必须提供 reviewer_call")
        if not isinstance(reviewer_token, str) or not reviewer_token:
            raise ValueError("reviewer_token is required")
        self._service = inbox_service
        self._reviewer_token = reviewer_token
        self._artifact_root = Path(artifact_root).resolve()
        self._workspace_root = self._artifact_root / "desktop-review"
        self._guard = RLock()
        self._closed = False
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._lock_handle = (self._workspace_root / ".owner.lock").open("a+b")
        try:
            self._acquire_owner_lock()
        except Exception:
            self._lock_handle.close()
            raise

    def list_batches(self) -> list[dict]:
        with self._guard:
            self._require_open()
            result = self._reviewer("list_batches", {})
            batches = result.get("batches") if isinstance(result, dict) else None
            if not isinstance(batches, list):
                raise DesktopReviewError("inbox 返回的批次摘要无效")
            return deepcopy(batches)

    def load_batch(self, task_id: str, batch_id: str) -> dict:
        with self._guard:
            self._require_open()
            task, batch = _required_text(task_id, "task_id"), _required_text(batch_id, "batch_id")
            original = self._load_source_batch(task, batch)
            source_ref = source_ref_for_batch(original)
            current = self._load_current(task, batch, source_ref)
            if current is None:
                return _snapshot(
                    task_id=task,
                    batch_id=batch,
                    revision=0,
                    source_ref=source_ref,
                    batch=original,
                    workflow_review_path=None,
                )
            return current

    def create_graph_revision(
        self,
        task_id: str,
        batch_id: str,
        expected_workspace_revision: int,
        step_relationships: dict[str, list[str]] | None = None,
    ) -> dict:
        with self._guard:
            self._require_open()
            from .graph_revision import GraphRevisionService
            return GraphRevisionService(self).create(
                task_id, batch_id, expected_workspace_revision, step_relationships,
            )

    def ensure_learning_graph_revision(self, task_id: str, batch_id: str) -> dict:
        """同锁内取得当前工作区；已有图保持原修订，不把人工保存当成过期请求。"""
        with self._guard:
            self._require_open()
            current = self.load_batch(task_id, batch_id)
            return self.create_graph_revision(task_id, batch_id, current["revision"])

    def create_action_only_graph(self, source: dict) -> dict:
        """从首个权威动作事件创建独立待审核图，不合成 fresh 批次。"""
        with self._guard:
            self._require_open()
            from .graph_revision import GraphRevisionService
            return GraphRevisionService(self).create_action_only(source)

    def load_graph_revision(
        self, logical_workflow_id: str, revision: int | None = None,
    ) -> dict:
        with self._guard:
            self._require_open()
            from .graph_revision import GraphRevisionService
            return GraphRevisionService(self).load(logical_workflow_id, revision)

    def load_graph_node_evidence(self, logical_workflow_id: str, expected_revision: int,
                                 expected_graph_sha256: str, node_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .graph_revision import GraphRevisionService
            return GraphRevisionService(self).node_evidence(
                logical_workflow_id, expected_revision, expected_graph_sha256, node_id,
            )

    @timed_observation("interface_import")
    def import_interface_content(self, task_id: str, batch_id: str, external_interface_id: str) -> dict:
        with self._guard:
            with observation_span("interface_import.lock_held"):
                self._require_open()
                from .interface_content import InterfaceContentService
                return InterfaceContentService(self).import_content(task_id, batch_id, external_interface_id)

    def get_submitted_interface_refs(self, task_id: str, batch_id: str) -> list[dict]:
        from .interface_content import InterfaceContentService
        with self._guard:
            self._require_open()
            batch = self._load_source_batch(task_id, batch_id)
            service = InterfaceContentService(self)
            references = []
            for item in batch["interfaces"]:
                current = service.import_content(task_id, batch_id, item["interface_id"])
                original = service._versions(current["interface_id"])[0]
                references.append({
                    "external_interface_id": item["interface_id"],
                    **{key: original[key] for key in ("interface_id", "version_id", "content_sha256", "revision")},
                })
            return references

    def list_interface_contents(self, reviewed_only: bool = False, task_id: str | None = None) -> list[dict]:
        with self._guard:
            self._require_open()
            from .interface_content import InterfaceContentService
            return InterfaceContentService(self).list(reviewed_only, task_id)

    def load_interface_content(self, interface_id: str, version_id: str | None = None) -> dict:
        with self._guard:
            self._require_open()
            from .interface_content import InterfaceContentService
            return InterfaceContentService(self).load(interface_id, version_id)

    def list_interface_contents_for_reference(self, task_id: str | None = None) -> list[dict]:
        """仅供已有图解析引用，保留已从界面库删除的不可变内容。"""
        with self._guard:
            self._require_open()
            from .interface_content import InterfaceContentService
            return InterfaceContentService(self).list(False, task_id, include_deleted=True)

    def preview_interface_content_deletion(self, interfaces: list[dict]) -> dict:
        with self._guard:
            self._require_open()
            from .interface_deletion import InterfaceDeletionService
            return InterfaceDeletionService(self).preview(interfaces)

    def delete_interface_content(self, interface_id: str, expected_revision: int, expected_sha256: str) -> dict:
        return self.delete_interface_contents([{"interface_id": interface_id,
            "expected_revision": expected_revision, "expected_sha256": expected_sha256}])

    def delete_interface_contents(self, interfaces: list[dict]) -> dict:
        with self._guard:
            self._require_open()
            from .interface_deletion import InterfaceDeletionService
            return InterfaceDeletionService(self).delete(interfaces)

    def save_interface_content(self, interface_id: str, expected_revision: int, expected_sha256: str,
                               changes: dict, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_content import InterfaceContentService
            return InterfaceContentService(self).save(interface_id, expected_revision, expected_sha256, changes, idempotency_key)

    def review_interface_content(self, interface_id: str, expected_revision: int, expected_sha256: str,
                                 application_binding: dict) -> dict:
        with self._guard:
            self._require_open()
            from .interface_content import InterfaceContentService
            return InterfaceContentService(self).review(interface_id, expected_revision, expected_sha256, application_binding)

    def load_interface_content_evidence(self, interface_id: str, version_id: str | None = None) -> dict:
        with self._guard:
            self._require_open()
            from .interface_content import InterfaceContentService
            return InterfaceContentService(self).evidence(interface_id, version_id)

    def get_interface_memory(self, allowed_task_id: str, interface_id: str, version_id: str | None = None) -> dict:
        with self._guard:
            self._require_open()
            from .interface_content import InterfaceContentService
            return InterfaceContentService(self).memory(allowed_task_id, interface_id, version_id)

    def search_interface_memory(self, allowed_task_id: str, query: str = "") -> list[dict]:
        with self._guard:
            self._require_open()
            from .interface_content import InterfaceContentService
            return InterfaceContentService(self).search_memory(allowed_task_id, query)

    def request_interface_relearning(self, interface_id: str, expected_revision: int,
                                     expected_sha256: str, region_ids: list[str],
                                     message: str, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_relearning import InterfaceRelearningService
            return InterfaceRelearningService(self).request(interface_id, expected_revision,
                expected_sha256, region_ids, message, idempotency_key)

    def list_interface_relearning(self, interface_id: str | None = None) -> list[dict]:
        with self._guard:
            self._require_open()
            from .interface_relearning import InterfaceRelearningService
            values = InterfaceRelearningService(self).list()
            return [value for value in values if interface_id is None or value["interface_id"] == interface_id]

    def read_interface_relearning(self, issue_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_relearning import InterfaceRelearningService
            return InterfaceRelearningService(self).read(issue_id)

    def compare_interface_relearning(self, issue_id: str, candidate_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_relearning import InterfaceRelearningService
            return InterfaceRelearningService(self).compare(issue_id, candidate_id)

    def adopt_interface_relearning(self, issue_id: str, candidate_id: str, expected_revision: int,
                                   expected_sha256: str, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_relearning import InterfaceRelearningService
            return InterfaceRelearningService(self).adopt(issue_id, candidate_id,
                expected_revision, expected_sha256, idempotency_key)

    def reject_interface_relearning(self, issue_id: str, message: str, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_relearning import InterfaceRelearningService
            return InterfaceRelearningService(self).reject(issue_id, message, idempotency_key)

    def withdraw_interface_relearning(self, issue_id: str, message: str, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_relearning import InterfaceRelearningService
            return InterfaceRelearningService(self).withdraw(issue_id, message, idempotency_key)

    def list_interface_relearning_feedback(self, allowed_task_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_relearning_gateway import InterfaceRelearningGateway
            return InterfaceRelearningGateway(self).list(allowed_task_id)

    def get_interface_relearning_feedback(self, allowed_task_id: str, issue_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_relearning_gateway import InterfaceRelearningGateway
            return InterfaceRelearningGateway(self).get(allowed_task_id, issue_id)

    def submit_interface_relearning_candidate(self, allowed_task_id: str, issue_id: str,
                                             expected_baseline_sha256: str, changes: dict,
                                             idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .interface_relearning_gateway import InterfaceRelearningGateway
            return InterfaceRelearningGateway(self).submit(allowed_task_id, issue_id,
                expected_baseline_sha256, changes, idempotency_key)

    def list_workflow_projects(self) -> list[dict]:
        with self._guard:
            self._require_open()
            from .workflow_project import WorkflowProjectService
            return WorkflowProjectService(self).list_projects()

    def list_workflow_project_summaries(self) -> list[dict]:
        with self._guard:
            self._require_open()
            from .workflow_project import WorkflowProjectService
            return WorkflowProjectService(self).list_summaries()

    def load_workflow_project(self, workflow_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .workflow_project import WorkflowProjectService
            return WorkflowProjectService(self).load(workflow_id)

    def save_workflow_project(self, workflow_id: str, expected_sha256: str,
                              changes: dict, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .workflow_project import WorkflowProjectService
            return WorkflowProjectService(self).save(workflow_id, expected_sha256, changes, idempotency_key)

    def get_workflow_project_memory(self, allowed_task_id: str, workflow_id: str,
                                    snapshot_id: str | None = None) -> dict:
        with self._guard:
            self._require_open()
            from .workflow_project import WorkflowProjectService
            return WorkflowProjectService(self).memory(allowed_task_id, workflow_id, snapshot_id)

    def search_workflow_projects(self, allowed_task_id: str, query: str = "") -> list[dict]:
        with self._guard:
            self._require_open()
            if not isinstance(query, str) or len(query) > 4000:
                raise DesktopReviewError("invalid project query")
            from .workflow_project import WorkflowProjectService
            result = []
            for item in WorkflowProjectService(self).list_projects():
                if item.get("task_id") != allowed_task_id or query.casefold() not in str(item.get("title", "")).casefold():
                    continue
                result.append({key: item[key] for key in ("logical_workflow_id", "title", "node_count")})
            return result

    def load_batch_graph_revision(self, task_id: str, batch_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .graph_revision import GraphRevisionService
            return GraphRevisionService(self).load_for_batch(task_id, batch_id)

    def append_fresh_graph_source(
        self, logical_workflow_id: str, task_id: str, batch_id: str,
    ) -> dict:
        """在同一把 façade 锁内追加已验证的同段新观察来源。"""
        with self._guard:
            self._require_open()
            from .graph_revision import GraphRevisionService
            return GraphRevisionService(self).append_fresh_source(
                logical_workflow_id, task_id, batch_id,
            )

    def append_learning_action_source(
        self, logical_workflow_id: str, source: dict,
    ) -> dict:
        """在 façade 锁内提交一份已验证的动作证据图投影。"""

        with self._guard:
            self._require_open()
            from .graph_revision import GraphRevisionService
            return GraphRevisionService(self).append_action_source(
                logical_workflow_id, source,
            )

    def search_workflow_memory(self, allowed_workflow_ids: list[str], application_scope: dict,
                               query: str = "", cursor: str | None = None) -> dict:
        with self._guard:
            self._require_open()
            from .workflow_memory import WorkflowMemoryReader
            return WorkflowMemoryReader(self).search(allowed_workflow_ids, application_scope, query, cursor)

    def get_workflow_memory(self, allowed_workflow_ids: list[str], workflow_id: str,
                            version: str | None = None) -> dict:
        with self._guard:
            self._require_open()
            from .workflow_memory import WorkflowMemoryReader
            return WorkflowMemoryReader(self).get(allowed_workflow_ids, workflow_id, version)

    def apply_graph_edit(
        self,
        logical_workflow_id: str,
        expected_revision: int,
        expected_graph_sha256: str,
        operation: dict,
        idempotency_key: str,
    ) -> dict:
        with self._guard:
            self._require_open()
            from .graph_revision import GraphRevisionService
            return GraphRevisionService(self).apply(
                logical_workflow_id, expected_revision, expected_graph_sha256,
                operation, idempotency_key,
            )

    def apply_graph_edits(self, logical_workflow_id: str, expected_revision: int,
                          expected_graph_sha256: str, operations: list[dict], idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .graph_revision import GraphRevisionService
            return GraphRevisionService(self).apply_many(
                logical_workflow_id, expected_revision, expected_graph_sha256, operations, idempotency_key)

    def request_graph_relearn(self, logical_workflow_id: str, expected_revision: int, expected_graph_sha256: str, expected_feedback_revision: int, scope: dict, message: str, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .graph_relearn import GraphRelearnService
            return GraphRelearnService(self).request(logical_workflow_id, expected_revision, expected_graph_sha256, expected_feedback_revision, scope, message, idempotency_key)

    def get_graph_relearn_feedback(
        self,
        logical_workflow_id: str,
        expected_revision: int,
        expected_graph_sha256: str,
    ) -> dict:
        with self._guard:
            self._require_open()
            from .graph_relearn import GraphRelearnService
            return GraphRelearnService(self).feedback(
                logical_workflow_id,
                expected_revision,
                expected_graph_sha256,
            )

    def compare_graph_relearn_candidate(self, logical_workflow_id: str, expected_revision: int, expected_graph_sha256: str, candidate_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .graph_relearn import GraphRelearnService
            return GraphRelearnService(self).compare(logical_workflow_id, expected_revision, expected_graph_sha256, candidate_id)

    def adopt_graph_relearn_candidate(self, logical_workflow_id: str, expected_revision: int, expected_graph_sha256: str, candidate_id: str, expected_candidate_sha256: str, expected_review_baseline_sha256: str, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            transaction = getattr(self._service, "reviewer_transaction", None)
            if not callable(transaction): raise DesktopReviewError("inbox 不支持本地 reviewer 原子事务")
            from .graph_relearn import GraphRelearnService
            try:
                return transaction(self._reviewer_token, lambda: GraphRelearnService(self).adopt(
                    logical_workflow_id, expected_revision, expected_graph_sha256, candidate_id,
                    expected_candidate_sha256, expected_review_baseline_sha256, idempotency_key,
                ))
            except DesktopReviewError: raise
            except Exception as error: raise DesktopReviewError("inbox 原子图采用操作失败") from error

    def save_revision(
        self,
        task_id: str,
        batch_id: str,
        expected_revision: int,
        batch: dict,
    ) -> dict:
        with self._guard:
            self._require_open()
            return self._save_revision_locked(task_id, batch_id, expected_revision, batch)

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
            try:
                self._lock_handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._lock_handle.close()

    def prepare_exact_review(self, task_id: str, batch_id: str, expected_revision: int, application_binding: dict, step_relationships=None, stop_interface_ids=None) -> dict:
        with self._guard:
            self._require_open()
            from .exact_review import ExactReviewService
            return ExactReviewService(self).prepare(task_id, batch_id, expected_revision, application_binding, step_relationships, stop_interface_ids)

    def prepare_graph_exact_review(self, logical_workflow_id: str, expected_revision: int, expected_graph_sha256: str, application_binding: dict, stop_node_ids=None) -> dict:
        with self._guard:
            self._require_open()
            from .exact_review import ExactReviewService
            return ExactReviewService(self).prepare_graph(logical_workflow_id, expected_revision, expected_graph_sha256, application_binding, stop_node_ids)

    def record_review_decisions(self, review_ref: str, expected_approval_revision: int, confirmed_subject_ids: list[str]) -> dict:
        with self._guard:
            self._require_open()
            from .exact_review import ExactReviewService
            return ExactReviewService(self).record(review_ref, expected_approval_revision, confirmed_subject_ids)

    def compile_exact_review(self, review_ref: str, expected_approval_revision: int) -> dict:
        with self._guard:
            self._require_open()
            from .exact_review import ExactReviewService
            return ExactReviewService(self).compile(review_ref, expected_approval_revision)

    def publish_exact_review(self, compile_receipt_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .exact_review import ExactReviewService
            return ExactReviewService(self).publish(compile_receipt_id)

    def list_reviewed_assets(self) -> list[dict]:
        with self._guard:
            self._require_open()
            from .exact_review import ExactReviewService
            return ExactReviewService(self).assets()

    def load_relearn_review(self, task_id: str, batch_id: str, expected_revision: int) -> dict:
        with self._guard:
            self._require_open()
            from .relearn import RelearnReviewService
            return RelearnReviewService(self).load(task_id, batch_id, expected_revision)

    def request_relearn(self, task_id: str, batch_id: str, expected_revision: int, expected_feedback_revision: int, scope: dict, message: str, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .relearn import RelearnReviewService
            return RelearnReviewService(self).request(task_id, batch_id, expected_revision, expected_feedback_revision, scope, message, idempotency_key)

    def withdraw_relearn(self, task_id: str, batch_id: str, expected_revision: int, issue_id: str, expected_feedback_revision: int, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            from .relearn import RelearnReviewService
            return RelearnReviewService(self).withdraw(task_id, batch_id, expected_revision, issue_id, expected_feedback_revision, idempotency_key)

    def compare_relearn_candidate(self, task_id: str, batch_id: str, expected_revision: int, candidate_id: str) -> dict:
        with self._guard:
            self._require_open()
            from .relearn import RelearnReviewService
            return RelearnReviewService(self).compare(task_id, batch_id, expected_revision, candidate_id)

    def adopt_relearn_candidate(self, task_id: str, batch_id: str, expected_revision: int, candidate_id: str, expected_candidate_sha256: str, expected_review_baseline_sha256: str, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            transaction = getattr(self._service, "reviewer_transaction", None)
            if not callable(transaction):
                raise DesktopReviewError("inbox 不支持本地 reviewer 原子事务")
            from .relearn_adoption import RelearnAdoptionService
            try:
                return transaction(
                    self._reviewer_token,
                    lambda: RelearnAdoptionService(self).adopt(
                        task_id, batch_id, expected_revision, candidate_id,
                        expected_candidate_sha256, expected_review_baseline_sha256,
                        idempotency_key,
                    ),
                )
            except DesktopReviewError:
                raise
            except Exception as error:
                raise DesktopReviewError("inbox 原子采用操作失败") from error

    def reject_relearn_candidate(self, task_id: str, batch_id: str, expected_revision: int, candidate_id: str, expected_candidate_sha256: str, expected_review_baseline_sha256: str | None, expected_decision_revision: int, reason: str, idempotency_key: str) -> dict:
        with self._guard:
            self._require_open()
            transaction = getattr(self._service, "reviewer_transaction", None)
            if not callable(transaction):
                raise DesktopReviewError("inbox 不支持本地 reviewer 原子事务")
            from .candidate_decisions import CandidateDecisionService
            try:
                return transaction(
                    self._reviewer_token,
                    lambda: CandidateDecisionService(self).reject(
                        task_id, batch_id, expected_revision, candidate_id,
                        expected_candidate_sha256,
                        expected_review_baseline_sha256,
                        expected_decision_revision, reason, idempotency_key,
                    ),
                )
            except DesktopReviewError:
                raise
            except Exception as error:
                raise DesktopReviewError("inbox 原子拒绝操作失败") from error

    def _save_revision_locked(self, task_id: str, batch_id: str, expected_revision: int, batch: dict, *, relearn_adoption: dict[str, Any] | None = None) -> dict:
        task, batch_id_value = _required_text(task_id, "task_id"), _required_text(batch_id, "batch_id")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise DesktopReviewError("expected_revision 必须是非负整数")
        original = self._load_source_batch(task, batch_id_value)
        source_ref = source_ref_for_batch(original)
        current = self._load_current(task, batch_id_value, source_ref)
        current_revision = 0 if current is None else current["revision"]
        if expected_revision != current_revision:
            raise DesktopReviewError("stale_revision: 工作区修订已过期，请重新加载后保存")
        try:
            edited = normalize_agent_link_batch(
                batch, existing_png_sha256=frozenset(item["sha256"] for item in original["screenshots"]),
            )
            # 原始证据始终不变；只有采用路径可在原接口尾部引入新区域。
            assert_source_identity(original, edited, allow_region_additions=current is not None or relearn_adoption is not None, allow_step_additions=current is not None or relearn_adoption is not None, allow_relationship_additions=current is not None or relearn_adoption is not None, allow_interface_additions=current is not None or relearn_adoption is not None)
            if current is not None:
                assert_source_identity(current["batch"], edited, allow_region_additions=relearn_adoption is not None, allow_step_additions=relearn_adoption is not None, allow_relationship_additions=relearn_adoption is not None, allow_interface_additions=relearn_adoption is not None)
        except ExternalMappingError as error:
            raise DesktopReviewError(str(error)) from error
        if relearn_adoption is not None and current is None:
            raise DesktopReviewError("采用必须绑定已保存的父人工修订")
        if relearn_adoption is not None:
            from .relearn_adoption import validate_adoption_origin
            validate_adoption_origin(self, {**current, "batch": edited, "relearn_adoption": relearn_adoption}, current)

        next_revision = current_revision + 1
        parent = None if current is None else self._parent_reference(current)
        try:
            self._materialize_source(source_ref, original)
            if relearn_adoption is not None:
                # 先验证完整采用血缘，再物化补充证据；绝不覆盖原批次。
                self._materialize_adopted_images(source_ref, current["batch"], edited)
            workflow = build_external_workflow_review(
                batch=edited, task_id=task, source_ref=source_ref, revision=next_revision,
            )
            out_dir = self._workflow_out_dir(task, batch_id_value, next_revision, edited)
            save_result = save_interface_workflow_review_candidate(
                workflow, project_root=self._artifact_root, out_dir=out_dir,
            )
            workflow_path = Path(save_result["path"]).resolve()
            if not _inside(self._artifact_root, workflow_path) or not workflow_path.is_file():
                raise DesktopReviewError("既有审核保存器返回了无效路径")
            snapshot = _snapshot_v2(
                task_id=task, batch_id=batch_id_value, revision=next_revision,
                source_ref=source_ref, batch=edited,
                workflow_review_path=str(workflow_path), parent_revision=parent,
                relearn_adoption=relearn_adoption,
            )
            self._persist_revision(snapshot)
            self._publish_current(snapshot)
            return self._load_current(task, batch_id_value, source_ref) or snapshot
        except DesktopReviewError:
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("persistence_failed: 审核修订未持久化：" + str(error)) from error

    def _reviewer(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service.reviewer_call(
                self._reviewer_token, operation, arguments
            )
        except Exception as error:
            raise DesktopReviewError("inbox 审核操作失败") from error
        if not isinstance(result, dict) or result.get("staging_only") is not True:
            raise DesktopReviewError("inbox 返回了非暂存审核响应")
        return result

    def _load_source_batch(self, task_id: str, batch_id: str) -> dict[str, Any]:
        detail = self._reviewer(
            "get_batch", {"task_id": task_id, "batch_id": batch_id}
        )
        if detail.get("source") != "untrusted_external":
            raise DesktopReviewError("桌面审核只接受 untrusted_external 暂存来源")
        raw = detail.get("batch")
        allowed = frozenset()
        if _has_large_png(raw):
            source = self._verified_fresh_source(detail, task_id, raw)
            if source is not None:
                allowed = frozenset({source["reference"]["screenshot_sha256"]})
        try:
            normalized = normalize_agent_link_batch(raw, existing_png_sha256=allowed)
        except ExternalMappingError as error:
            raise DesktopReviewError(str(error)) from error
        if normalized.get("batch_id") != batch_id:
            raise DesktopReviewError("inbox 批次身份不匹配")
        return normalized

    def _source_png_allowlist(self, task_id: str, batch_id: str, source_ref: str) -> frozenset[str]:
        original = self._load_source_batch(task_id, batch_id)
        if source_ref_for_batch(original) != source_ref:
            raise DesktopReviewError("原始 inbox 批次与持久来源摘要不一致")
        return frozenset(item["sha256"] for item in original["screenshots"])

    def _normalize_source_copy(self, raw: Any, task_id: str, batch_id: str, source_ref: str) -> dict:
        # 先固定完整原批次；大图预算只来自权威 inbox 与其已验证归档。
        if not isinstance(raw, dict) or source_ref_for_batch(raw) != source_ref:
            raise DesktopReviewError("持久原始来源摘要不一致")
        allowed = self._source_png_allowlist(task_id, batch_id, source_ref) if _has_large_png(raw) else frozenset()
        normalized = normalize_agent_link_batch(raw, existing_png_sha256=allowed)
        if normalized["batch_id"] != batch_id or source_ref_for_batch(normalized) != source_ref:
            raise DesktopReviewError("持久原始来源身份或摘要不一致")
        return normalized

    def _materialize_source(self, source_ref: str, batch: dict[str, Any]) -> None:
        source_dir = self._workspace_root / "sources" / source_ref
        source_bytes = canonical_json_bytes(batch) + b"\n"
        _write_immutable(source_dir / "original_batch.json", source_bytes)
        for screenshot in batch["screenshots"]:
            try:
                image_bytes = base64.b64decode(screenshot["png_base64"], validate=True)
            except (TypeError, ValueError) as error:
                raise DesktopReviewError("已校验截图无法解码") from error
            digest = hashlib.sha256(image_bytes).hexdigest()
            if digest != screenshot["sha256"]:
                raise DesktopReviewError("截图摘要与 inbox 已校验摘要不一致")
            relative = source_image_relative_path(source_ref, screenshot)
            _write_immutable(self._artifact_root / relative, image_bytes)

    def _fresh_source_for_batch(self, task_id: str, batch_id: str, original: dict) -> dict | None:
        detail = self._reviewer("get_batch", {"task_id": task_id, "batch_id": batch_id})
        return self._verified_fresh_source(detail, task_id, original)

    def _verified_fresh_source(self, detail: dict, task_id: str, original: dict) -> dict | None:
        from app.agent_link.fresh_source_contract import validate_fresh_source_metadata
        from app.agent.fresh_learning_archive import FreshLearningObservationArchive

        if "fresh_learning_source" not in detail:
            return None
        try:
            source = validate_fresh_source_metadata(detail["fresh_learning_source"])
            if source["task_id"] != task_id or len(original["screenshots"]) != 1:
                raise ValueError("fresh source batch scope differs")
            packet = FreshLearningObservationArchive(self._artifact_root).read(
                source["reference"], **{key: source[key] for key in ("connection_id", "task_id", "segment_id")})
            screenshot = original["screenshots"][0]
            if screenshot["sha256"] != source["reference"]["screenshot_sha256"] or base64.b64decode(screenshot["png_base64"], validate=True) != packet.png_bytes:
                raise ValueError("fresh source screenshot differs")
            return source
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise DesktopReviewError("fresh_source_unavailable: 原始学习观察缺失或不一致") from error

    def _materialize_adopted_images(self, source_ref: str, parent: dict, edited: dict) -> None:
        """仅供已核验采用调用，补充图像与原来源锚点共享不可变内容路径。"""
        images = []
        for screenshot in edited["screenshots"][len(parent["screenshots"]):]:
            try:
                raw = base64.b64decode(screenshot["png_base64"], validate=True)
            except (TypeError, ValueError) as error:
                raise DesktopReviewError("补充截图无法解码") from error
            if hashlib.sha256(raw).hexdigest() != screenshot["sha256"]:
                raise DesktopReviewError("补充截图与已核验候选摘要不一致")
            images.append((self._artifact_root / source_image_relative_path(source_ref, screenshot), raw))
        for path, raw in images:
            _write_immutable(path, raw)

    def _workspace_key(self, task_id: str, batch_id: str) -> str:
        return hashlib.sha256(f"{task_id}\0{batch_id}".encode("utf-8")).hexdigest()

    def _workspace_dir(self, task_id: str, batch_id: str) -> Path:
        return self._workspace_root / "workspaces" / self._workspace_key(task_id, batch_id)

    def _workflow_out_dir(self, task_id: str, batch_id: str, revision: int, batch: dict[str, Any]) -> str:
        content = hashlib.sha256(canonical_json_bytes(batch)).hexdigest()[:16]
        attempt = uuid4().hex
        return (
            Path("desktop-review")
            / "workflow-revisions"
            / self._workspace_key(task_id, batch_id)
            / f"r{revision}-{content}-{attempt}"
        ).as_posix()

    def _persist_revision(self, snapshot: dict[str, Any]) -> None:
        workspace = self._workspace_dir(snapshot["task_id"], snapshot["batch_id"])
        content = hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()[:16]
        path = workspace / "revisions" / f"r{snapshot['revision']}-{content}" / "workspace.json"
        _write_immutable(path, canonical_json_bytes(snapshot) + b"\n")

    def _publish_current(self, snapshot: dict[str, Any]) -> None:
        workspace = self._workspace_dir(snapshot["task_id"], snapshot["batch_id"])
        content = hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()[:16]
        relative = (
            Path("desktop-review")
            / "workspaces"
            / self._workspace_key(snapshot["task_id"], snapshot["batch_id"])
            / "revisions"
            / f"r{snapshot['revision']}-{content}"
            / "workspace.json"
        ).as_posix()
        payload = {
            "contract_version": _CURRENT_CONTRACT,
            "task_id": snapshot["task_id"],
            "batch_id": snapshot["batch_id"],
            "revision": snapshot["revision"],
            "source_ref": snapshot["source_ref"],
            "workspace_path": relative,
            "workspace_sha256": hashlib.sha256(
                canonical_json_bytes(snapshot) + b"\n"
            ).hexdigest(),
            "workflow_review_sha256": hashlib.sha256(
                Path(str(snapshot["workflow_review_path"])).read_bytes()
            ).hexdigest(),
        }
        _atomic_write_bytes(workspace / "current.json", canonical_json_bytes(payload) + b"\n")

    def _parent_reference(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        relative = self._snapshot_relative_path(snapshot)
        workspace_path = (self._artifact_root / relative).resolve()
        if not _inside(self._workspace_root, workspace_path) or not workspace_path.is_file():
            raise DesktopReviewError("父工作区修订文件缺失")
        workflow_path = Path(str(snapshot["workflow_review_path"])).resolve()
        return {
            "revision": snapshot["revision"],
            "workspace_path": relative.as_posix(),
            "workspace_sha256": hashlib.sha256(workspace_path.read_bytes()).hexdigest(),
            "workflow_review_sha256": hashlib.sha256(workflow_path.read_bytes()).hexdigest(),
        }

    def _snapshot_relative_path(self, snapshot: dict[str, Any]) -> Path:
        content = hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()[:16]
        return (
            Path("desktop-review") / "workspaces"
            / self._workspace_key(snapshot["task_id"], snapshot["batch_id"])
            / "revisions" / f"r{snapshot['revision']}-{content}" / "workspace.json"
        )

    def _load_current(self, task_id: str, batch_id: str, source_ref: str) -> dict[str, Any] | None:
        path = self._workspace_dir(task_id, batch_id) / "current.json"
        if not path.exists():
            return None
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("当前工作区清单损坏，未自动重置") from error
        required = {"contract_version", "task_id", "batch_id", "revision", "source_ref", "workspace_path", "workspace_sha256", "workflow_review_sha256"}
        if not isinstance(manifest, dict) or set(manifest) != required or manifest.get("contract_version") != _CURRENT_CONTRACT:
            raise DesktopReviewError("当前工作区清单契约无效，未自动重置")
        if manifest["task_id"] != task_id or manifest["batch_id"] != batch_id or manifest["source_ref"] != source_ref:
            raise DesktopReviewError("当前工作区来源与 inbox 批次不一致")
        if isinstance(manifest["revision"], bool) or not isinstance(manifest["revision"], int) or manifest["revision"] < 1:
            raise DesktopReviewError("当前工作区修订无效")
        relative = Path(str(manifest["workspace_path"]))
        target = (self._artifact_root / relative).resolve()
        if not _inside(self._workspace_root, target) or not target.is_file():
            raise DesktopReviewError("当前工作区修订文件缺失")
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["workspace_sha256"]:
            raise DesktopReviewError("当前工作区修订摘要不匹配")
        try:
            snapshot = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("当前工作区修订内容无效") from error
        allowed = self._source_png_allowlist(task_id, batch_id, source_ref) if isinstance(snapshot, dict) and _has_large_png(snapshot.get("batch")) else frozenset()
        _validate_snapshot(snapshot, existing_png_sha256=allowed)
        if (
            snapshot["task_id"] != task_id
            or snapshot["batch_id"] != batch_id
            or snapshot["source_ref"] != source_ref
            or snapshot["revision"] != manifest["revision"]
        ):
            raise DesktopReviewError("当前工作区修订与清单不一致")
        workflow = snapshot["workflow_review_path"]
        if not isinstance(workflow, str) or not _inside(self._artifact_root, Path(workflow).resolve()) or not Path(workflow).is_file():
            raise DesktopReviewError("当前工作区审核文件缺失")
        workflow_path = Path(workflow).resolve()
        workflow_bytes = workflow_path.read_bytes()
        if hashlib.sha256(workflow_bytes).hexdigest() != manifest["workflow_review_sha256"]:
            raise DesktopReviewError("当前工作区审核文件摘要不匹配")
        try:
            persisted_workflow = json.loads(workflow_bytes.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("当前工作区审核文件内容无效") from error
        self._verify_source_evidence(snapshot, persisted_workflow, workflow_path)
        self._validated_revision_chain(snapshot)
        return deepcopy(snapshot)

    def _validated_revision_chain(self, current: dict[str, Any]) -> list[dict[str, Any]]:
        original = self._load_source_batch(current["task_id"], current["batch_id"])
        if source_ref_for_batch(original) != current["source_ref"]:
            raise DesktopReviewError("工作区修订链来源与 inbox 不一致")
        allowed = frozenset(item["sha256"] for item in original["screenshots"])
        chain = [deepcopy(current)]
        child = current
        while child.get("contract_version") == _WORKSPACE_CONTRACT_V2 and child.get("parent_revision") is not None:
            reference = child["parent_revision"]
            relative = Path(reference["workspace_path"])
            path = (self._artifact_root / relative).resolve()
            if not _inside(self._workspace_root, path) or not path.is_file():
                raise DesktopReviewError("父工作区修订路径缺失或越界")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != reference["workspace_sha256"]:
                raise DesktopReviewError("父工作区修订摘要不匹配")
            try:
                parent = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise DesktopReviewError("父工作区修订内容无效") from error
            _validate_snapshot(parent, existing_png_sha256=allowed)
            if relative != self._snapshot_relative_path(parent):
                raise DesktopReviewError("父工作区修订路径不是规范持久路径")
            if any((
                parent["task_id"] != child["task_id"],
                parent["batch_id"] != child["batch_id"],
                parent["source_ref"] != child["source_ref"],
                parent["revision"] != child["revision"] - 1,
                reference["revision"] != parent["revision"],
            )):
                raise DesktopReviewError("父工作区修订身份或相邻修订关系无效")
            workflow_path = Path(str(parent["workflow_review_path"])).resolve()
            if not _inside(self._artifact_root, workflow_path) or not workflow_path.is_file():
                raise DesktopReviewError("父工作区审核文件缺失")
            workflow_bytes = workflow_path.read_bytes()
            if hashlib.sha256(workflow_bytes).hexdigest() != reference["workflow_review_sha256"]:
                raise DesktopReviewError("父工作区审核文件摘要不匹配")
            try:
                workflow = json.loads(workflow_bytes.decode("utf-8-sig"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise DesktopReviewError("父工作区审核文件内容无效") from error
            self._verify_source_evidence(parent, workflow, workflow_path)
            chain.append(deepcopy(parent))
            child = parent
        try:
            assert_source_identity(original, chain[-1]["batch"])
            for index, snapshot in enumerate(chain):
                adoption = snapshot.get("relearn_adoption")
                if index + 1 >= len(chain):
                    continue
                parent = chain[index + 1]
                assert_source_identity(parent["batch"], snapshot["batch"], allow_region_additions=adoption is not None, allow_step_additions=adoption is not None, allow_relationship_additions=adoption is not None, allow_interface_additions=adoption is not None)
                if adoption is not None:
                    from .relearn_adoption import validate_adoption_origin
                    validate_adoption_origin(self, snapshot, parent)
        except ExternalMappingError as error:
            raise DesktopReviewError("工作区修订实体身份链无效") from error
        if chain[-1].get("relearn_adoption") is not None:
            raise DesktopReviewError("采用修订缺少已验证父修订")
        return chain

    def _verify_source_evidence(
        self,
        snapshot: dict[str, Any],
        workflow: Any,
        workflow_path: Path,
    ) -> None:
        source_path = (
            self._workspace_root
            / "sources"
            / snapshot["source_ref"]
            / "original_batch.json"
        )
        if not source_path.is_file():
            raise DesktopReviewError("当前工作区原始来源文件缺失")
        try:
            original = self._normalize_source_copy(
                json.loads(source_path.read_text(encoding="utf-8-sig")),
                snapshot["task_id"], snapshot["batch_id"], snapshot["source_ref"],
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ExternalMappingError) as error:
            raise DesktopReviewError("当前工作区原始来源文件无效") from error
        if source_ref_for_batch(original) != snapshot["source_ref"]:
            raise DesktopReviewError("当前工作区原始来源摘要不匹配")
        for screenshot in snapshot["batch"]["screenshots"]:
            image_path = self._artifact_root / source_image_relative_path(
                snapshot["source_ref"], screenshot
            )
            if not image_path.is_file():
                raise DesktopReviewError("当前工作区截图证据缺失")
            if hashlib.sha256(image_path.read_bytes()).hexdigest() != screenshot["sha256"]:
                raise DesktopReviewError("当前工作区截图证据摘要不匹配")
        self._verify_materialized_workflow_evidence(snapshot, workflow, workflow_path)

    def _verify_materialized_workflow_evidence(
        self,
        snapshot: dict[str, Any],
        workflow: Any,
        workflow_path: Path,
    ) -> None:
        if not isinstance(workflow, dict) or workflow.get("contract_version") != "single_application_workflow_review_v1":
            raise DesktopReviewError("当前工作区审核契约无效")
        source = workflow.get("source")
        if not isinstance(source, dict) or any(
            source.get(key) != expected
            for key, expected in (
                ("kind", "untrusted_external"),
                ("task_id", snapshot["task_id"]),
                ("batch_id", snapshot["batch_id"]),
                ("batch_sha256", snapshot["source_ref"]),
            )
        ):
            raise DesktopReviewError("当前工作区审核来源与不可变批次不一致")
        workflow_meta = workflow.get("workflow")
        nodes = workflow.get("nodes")
        if not isinstance(workflow_meta, dict) or not isinstance(nodes, list):
            raise DesktopReviewError("当前工作区审核结构无效")
        workflow_id = str(workflow_meta.get("workflow_id") or "").strip()
        if not workflow_id:
            raise DesktopReviewError("当前工作区审核工作流身份无效")
        evidence_root = workflow_path.parent / "node-evidence"
        editable_root = workflow_path.parent / "node-review-sources"
        for node in nodes:
            if not isinstance(node, dict):
                raise DesktopReviewError("当前工作区审核节点无效")
            node_id = str(node.get("node_id") or "").strip()
            evidence = node.get("evidence")
            if not node_id or not isinstance(evidence, dict):
                raise DesktopReviewError("当前工作区审核节点证据无效")
            self._verify_materialized_node_images(evidence, evidence_root)
            self._verify_editable_review_source(
                node=node,
                workflow_id=workflow_id,
                editable_root=editable_root,
            )

    def _verify_materialized_node_images(
        self,
        evidence: dict[str, Any],
        evidence_root: Path,
    ) -> Path:
        source_image: Path | None = None
        for key in (
            "source_screenshot_path",
            "numbered_overlay_path",
            "fused_overlay_path",
            "human_review_overlay_path",
        ):
            value = evidence.get(key)
            if not isinstance(value, str) or not value.strip():
                if key == "source_screenshot_path":
                    raise DesktopReviewError("当前工作区审核源截图引用缺失")
                continue
            materialized = self._artifact_file(value, "当前工作区审核图片证据")
            if not _inside(evidence_root, materialized):
                raise DesktopReviewError("当前工作区审核图片未使用持久化证据")
            revision_value = evidence.get(f"review_revision_{key}")
            original = self._artifact_file(revision_value, "当前工作区审核原始图片证据")
            materialized_digest = hashlib.sha256(materialized.read_bytes()).hexdigest()
            if materialized_digest != hashlib.sha256(original.read_bytes()).hexdigest():
                raise DesktopReviewError("当前工作区审核图片证据摘要不匹配")
            if key == "source_screenshot_path":
                expected_digest = evidence.get("source_screenshot_sha256")
                if not isinstance(expected_digest, str) or expected_digest != materialized_digest:
                    raise DesktopReviewError("当前工作区审核源截图摘要不匹配")
                source_image = materialized
        if source_image is None:
            raise DesktopReviewError("当前工作区审核源截图未持久化")
        return source_image

    def _verify_editable_review_source(
        self,
        *,
        node: dict[str, Any],
        workflow_id: str,
        editable_root: Path,
    ) -> None:
        editable = self._artifact_file(
            node.get("editable_review_source_path"), "当前工作区可编辑审核来源"
        )
        if not _inside(editable_root, editable):
            raise DesktopReviewError("当前工作区可编辑审核来源未持久化")
        try:
            payload = json.loads(editable.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("当前工作区可编辑审核来源无效") from error
        expected = build_interface_node_review_source_payload(
            node,
            workflow_id=workflow_id,
            project_root=self._artifact_root,
        )
        if payload != expected:
            raise DesktopReviewError("当前工作区可编辑审核来源与父流程节点不一致")

    def _artifact_file(self, value: Any, label: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise DesktopReviewError(f"{label}引用无效")
        path = Path(value)
        target = path.resolve() if path.is_absolute() else (self._artifact_root / path).resolve()
        if not _inside(self._artifact_root, target) or not target.is_file():
            raise DesktopReviewError(f"{label}缺失或越出工作区")
        return target

    def _acquire_owner_lock(self) -> None:
        try:
            self._lock_handle.seek(0, os.SEEK_END)
            if self._lock_handle.tell() == 0:
                self._lock_handle.write(b"0")
                self._lock_handle.flush()
            self._lock_handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise DesktopReviewError("另一桌面审核宿主已占用该工作区") from error

    def list_workflow_graphs(self) -> list[dict]:
        from .workflow_membership import WorkflowMembershipService
        with self._guard:
            self._require_open()
            return WorkflowMembershipService(self).list_workflow_graphs()

    def create_workflow_graph(self, title: str, task_id: str) -> dict:
        from .workflow_membership import WorkflowMembershipService
        with self._guard:
            self._require_open()
            return WorkflowMembershipService(self).create_workflow_graph(title=title, task_id=task_id)

    def attach_interface_to_workflow(self, workflow_id: str, interface_id: str,
                                    version_id: str, expected_revision: int,
                                    expected_sha256: str, idempotency_key: str) -> dict:
        from .workflow_membership import WorkflowMembershipService
        with self._guard:
            self._require_open()
            return WorkflowMembershipService(self).attach_interface_to_workflow(
                workflow_id=workflow_id, interface_id=interface_id, version_id=version_id,
                expected_revision=expected_revision, expected_sha256=expected_sha256,
                idempotency_key=idempotency_key,
            )

    def attach_interfaces_to_workflow(self, workflow_id: str, interfaces: list[dict],
                                      expected_revision: int, expected_sha256: str,
                                      idempotency_key: str) -> dict:
        from .workflow_membership import WorkflowMembershipService
        with self._guard:
            self._require_open()
            return WorkflowMembershipService(self).attach_interfaces_to_workflow(
                workflow_id=workflow_id, interfaces=interfaces,
                expected_revision=expected_revision, expected_sha256=expected_sha256,
                idempotency_key=idempotency_key,
            )

    def detach_interface_from_workflow(self, workflow_id: str, interface_id: str,
                                      version_id: str, expected_revision: int,
                                      expected_sha256: str, idempotency_key: str) -> dict:
        from .workflow_membership import WorkflowMembershipService
        with self._guard:
            self._require_open()
            return WorkflowMembershipService(self).detach_interface_from_workflow(
                workflow_id=workflow_id, interface_id=interface_id, version_id=version_id,
                expected_revision=expected_revision, expected_sha256=expected_sha256,
                idempotency_key=idempotency_key,
            )

    def request_interface_membership(self, allowed_task_id: str, workflow_id: str,
                                     interface_id: str, version_id: str,
                                     expected_revision: int, expected_sha256: str,
                                     idempotency_key: str) -> dict:
        from .workflow_membership import WorkflowMembershipService
        with self._guard:
            self._require_open()
            return WorkflowMembershipService(self).request_interface_membership(
                allowed_task_id=allowed_task_id, workflow_id=workflow_id,
                interface_id=interface_id, version_id=version_id,
                expected_revision=expected_revision, expected_sha256=expected_sha256,
                idempotency_key=idempotency_key,
            )

    def _require_open(self) -> None:
        if self._closed:
            raise DesktopReviewError("桌面审核工作区已关闭")


def _snapshot(*, task_id: str, batch_id: str, revision: int, source_ref: str, batch: dict[str, Any], workflow_review_path: str | None) -> dict[str, Any]:
    return {
        "contract_version": _WORKSPACE_CONTRACT,
        "task_id": task_id,
        "batch_id": batch_id,
        "revision": revision,
        "source_ref": source_ref,
        "source": "untrusted_external",
        "batch": deepcopy(batch),
        "workflow_review_path": workflow_review_path,
        "review_status": "needs_human_review",
    }


def _snapshot_v2(*, task_id: str, batch_id: str, revision: int, source_ref: str, batch: dict[str, Any], workflow_review_path: str, parent_revision: dict[str, Any] | None, relearn_adoption: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "contract_version": _WORKSPACE_CONTRACT_V2,
        "task_id": task_id,
        "batch_id": batch_id,
        "revision": revision,
        "source_ref": source_ref,
        "source": "untrusted_external",
        "batch": deepcopy(batch),
        "workflow_review_path": workflow_review_path,
        "review_status": "needs_human_review",
        "parent_revision": deepcopy(parent_revision),
        "relearn_adoption": deepcopy(relearn_adoption),
    }


def _has_large_png(value: Any) -> bool:
    from app.agent_link.contracts import MAX_PNG_BYTES

    if not isinstance(value, dict) or not isinstance(value.get("screenshots"), list):
        return False
    # 长度只触发权威证据检查，绝不把待审图像的自报摘要提升为许可。
    for item in value["screenshots"]:
        if not isinstance(item, dict) or not isinstance(item.get("png_base64"), str):
            continue
        encoded = item["png_base64"]
        padding = 2 if encoded.endswith("==") else 1 if encoded.endswith("=") else 0
        if len(encoded) // 4 * 3 - padding > MAX_PNG_BYTES:
            return True
    return False


def _validate_snapshot(value: Any, *, existing_png_sha256: frozenset[str] = frozenset()) -> None:
    base = {"contract_version", "task_id", "batch_id", "revision", "source_ref", "source", "batch", "workflow_review_path", "review_status"}
    if not isinstance(value, dict) or value.get("contract_version") not in {_WORKSPACE_CONTRACT, _WORKSPACE_CONTRACT_V2}:
        raise DesktopReviewError("工作区修订契约无效")
    required = base if value["contract_version"] == _WORKSPACE_CONTRACT else base | {"parent_revision", "relearn_adoption"}
    if set(value) != required:
        raise DesktopReviewError("工作区修订字段无效")
    if value.get("source") != "untrusted_external" or value.get("review_status") != "needs_human_review":
        raise DesktopReviewError("工作区修订来源或审核状态无效")
    if isinstance(value.get("revision"), bool) or not isinstance(value.get("revision"), int) or value["revision"] < 1:
        raise DesktopReviewError("工作区修订号无效")
    if not all(isinstance(value.get(name), str) and value[name] for name in ("task_id", "batch_id", "source_ref")):
        raise DesktopReviewError("工作区修订身份无效")
    try:
        normalized = normalize_agent_link_batch(value["batch"], existing_png_sha256=existing_png_sha256)
    except ExternalMappingError as error:
        raise DesktopReviewError("工作区修订批次无效") from error
    if normalized != value["batch"]:
        raise DesktopReviewError("工作区修订批次没有规范化")
    if value["contract_version"] == _WORKSPACE_CONTRACT_V2:
        parent = value["parent_revision"]
        adoption = value["relearn_adoption"]
        if value["revision"] == 1:
            if parent is not None:
                raise DesktopReviewError("首个工作区修订不能声明父修订")
        elif not isinstance(parent, dict) or set(parent) != {"revision", "workspace_path", "workspace_sha256", "workflow_review_sha256"}:
            raise DesktopReviewError("工作区父修订引用无效")
        if parent is not None:
            if type(parent.get("revision")) is not int or parent["revision"] != value["revision"] - 1:
                raise DesktopReviewError("工作区父修订号无效")
            if not all(isinstance(parent.get(name), str) and parent[name] for name in ("workspace_path", "workspace_sha256", "workflow_review_sha256")):
                raise DesktopReviewError("工作区父修订摘要引用无效")
            if any(len(parent[name]) != 64 or any(character not in "0123456789abcdef" for character in parent[name]) for name in ("workspace_sha256", "workflow_review_sha256")):
                raise DesktopReviewError("工作区父修订摘要格式无效")
        if adoption is not None:
            if parent is None:
                raise DesktopReviewError("采用修订必须声明父修订")
            from .relearn_adoption import validate_adoption_origin_shape
            validate_adoption_origin_shape(adoption)


def _write_immutable(path: Path, payload: bytes) -> None:
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise DesktopReviewError("不可变审核文件无法读取") from error
        if existing != payload:
            raise DesktopReviewError("不可变审核文件冲突，拒绝覆盖")
        return
    _atomic_write_bytes(path, payload)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError:
        raise
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DesktopReviewError(f"{name} is required")
    return text


def _inside(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
