"""图修订范围内的问题记录、候选比较与显式人工采用。"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .jobs import FacadeJob, make_job


class GraphRelearnDialog(QDialog):
    """只读比较与显式采用；不调用模型、不批准、不发布、不执行。"""

    revisionAdopted = Signal(object)
    errorRaised = Signal(str)

    def __init__(
        self,
        facade: Any,
        snapshot: dict[str, Any],
        selection: tuple[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.facade = facade
        self.snapshot = self._validate_snapshot(snapshot)
        self.selection = self._validate_selection(selection)
        self.feedback: dict[str, Any] | None = None
        self.comparison: dict[str, Any] | None = None
        self._jobs: set[FacadeJob] = set()
        self._request_id = 0
        self._busy = False
        self._job_outcome: tuple[str, object, object] | None = None
        self._updating = False
        self._issue_retry: tuple[tuple[Any, ...], str] | None = None
        self._adopt_retry: tuple[tuple[Any, ...], str] | None = None
        self.setObjectName("graphRelearnDialog")
        self.setWindowTitle("图内标记问题与比较候选")
        self.resize(920, 700)
        self._build_ui()
        self._set_controls()
        self.refresh_feedback()

    @property
    def is_busy(self) -> bool:
        return self._busy

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        kind_text = "节点" if self.selection[0] == "node" else "边"
        self.identity_label = QLabel(
            f"{self.snapshot['logical_workflow_id']} · 图修订 {self.snapshot['revision']}\n"
            f"当前范围：{kind_text} {self.selection[1]}"
        )
        self.identity_label.setObjectName("graphRelearnIdentity")
        self.identity_label.setWordWrap(True)
        layout.addWidget(self.identity_label)
        explanation = QLabel(
            "范围只包含当前所选稳定 ID。提交问题不会调用模型；选择候选只做只读比较，"
            "只有单独点击“采用候选为新草稿”才写入新的图修订。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        issue_row = QHBoxLayout()
        self.issue_message = QPlainTextEdit()
        self.issue_message.setObjectName("graphRelearnIssueMessage")
        self.issue_message.setPlaceholderText("说明这个节点或边哪里需要重新核对（不能为空）")
        self.issue_message.setMaximumHeight(90)
        self.submit_issue_button = QPushButton("提交范围问题")
        self.submit_issue_button.setObjectName("submitGraphRelearnIssueButton")
        self.refresh_button = QPushButton("刷新反馈")
        self.refresh_button.setObjectName("refreshGraphRelearnButton")
        issue_buttons = QVBoxLayout()
        issue_buttons.addWidget(self.submit_issue_button)
        issue_buttons.addWidget(self.refresh_button)
        issue_buttons.addStretch(1)
        issue_row.addWidget(self.issue_message, 1)
        issue_row.addLayout(issue_buttons)
        layout.addLayout(issue_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        issues_panel = QWidget()
        issues_layout = QVBoxLayout(issues_panel)
        issues_layout.setContentsMargins(0, 0, 0, 0)
        issues_layout.addWidget(QLabel("当前范围的问题"))
        self.issue_list = QListWidget()
        self.issue_list.setObjectName("graphRelearnIssueList")
        issues_layout.addWidget(self.issue_list)
        splitter.addWidget(issues_panel)

        candidate_panel = QWidget()
        candidate_layout = QVBoxLayout(candidate_panel)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        candidate_layout.addWidget(QLabel("Agent 候选（选择不会采用）"))
        self.candidate_combo = QComboBox()
        self.candidate_combo.setObjectName("graphRelearnCandidateCombo")
        candidate_layout.addWidget(self.candidate_combo)
        self.comparison_status = QLabel("尚未选择候选")
        self.comparison_status.setObjectName("graphRelearnComparisonStatus")
        self.comparison_status.setWordWrap(True)
        candidate_layout.addWidget(self.comparison_status)
        self.comparison_view = QPlainTextEdit()
        self.comparison_view.setObjectName("graphRelearnComparisonView")
        self.comparison_view.setReadOnly(True)
        self.comparison_view.setPlaceholderText("选择候选后显示每项操作的修改前 / 修改后值。")
        candidate_layout.addWidget(self.comparison_view, 1)
        self.adopt_button = QPushButton("采用候选为新草稿")
        self.adopt_button.setObjectName("adoptGraphRelearnCandidateButton")
        candidate_layout.addWidget(self.adopt_button)
        splitter.addWidget(candidate_panel)
        splitter.setSizes([340, 560])
        layout.addWidget(splitter, 1)

        self.status_label = QLabel("正在读取当前图的反馈…")
        self.status_label.setObjectName("graphRelearnStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.issue_message.textChanged.connect(self._set_controls)
        self.submit_issue_button.clicked.connect(self.submit_issue)
        self.refresh_button.clicked.connect(self.refresh_feedback)
        self.candidate_combo.currentIndexChanged.connect(self._candidate_selected)
        self.adopt_button.clicked.connect(self.adopt_candidate)

    def refresh_feedback(self) -> None:
        if self._busy:
            return
        logical_id, revision, digest = self._graph_identity()
        self._start(
            lambda: self.facade.get_graph_relearn_feedback(
                logical_id, revision, digest,
            ),
            self._feedback_completed,
            "正在读取当前图的最新反馈…",
        )

    def submit_issue(self) -> None:
        if self._busy:
            return
        message = self.issue_message.toPlainText().strip()
        if not message:
            self._error("问题说明不能为空。")
            return
        if self.feedback is None:
            self._error("尚未取得当前图的反馈修订，不能提交。")
            return
        scope = self._scope()
        signature = (
            self.snapshot["logical_workflow_id"],
            self.snapshot["revision"],
            self.snapshot["content_sha256"],
            json.dumps(scope, sort_keys=True, separators=(",", ":")),
            message,
            self.feedback["feedback_revision"],
        )
        if self._issue_retry is None or self._issue_retry[0] != signature:
            self._issue_retry = (signature, f"graph-ui-issue.{uuid4().hex}")
        key = self._issue_retry[1]
        logical_id, revision, digest = self._graph_identity()
        feedback_revision = self.feedback["feedback_revision"]
        self._start(
            lambda: self.facade.request_graph_relearn(
                logical_id,
                revision,
                digest,
                feedback_revision,
                scope,
                message,
                key,
            ),
            lambda result: self._issue_completed(result, message, scope),
            "正在持久化当前范围的问题…",
        )

    def adopt_candidate(self) -> None:
        comparison = self.comparison
        if (
            self._busy
            or comparison is None
            or comparison.get("status") != "current"
            or comparison.get("changed") is not True
            or comparison.get("selection_scope_status") != "exact"
        ):
            return
        signature = (
            comparison["candidate_id"],
            comparison["candidate_sha256"],
            comparison["review_baseline_sha256"],
            self.snapshot["revision"],
            self.snapshot["content_sha256"],
        )
        if self._adopt_retry is None or self._adopt_retry[0] != signature:
            self._adopt_retry = (signature, f"graph-ui-adopt.{uuid4().hex}")
        logical_id, revision, digest = self._graph_identity()
        self._start(
            lambda: self.facade.adopt_graph_relearn_candidate(
                logical_id,
                revision,
                digest,
                comparison["candidate_id"],
                comparison["candidate_sha256"],
                comparison["review_baseline_sha256"],
                self._adopt_retry[1],
            ),
            self._adoption_completed,
            "正在采用候选并创建新的图草稿…",
        )

    def _candidate_selected(self) -> None:
        if self._updating or self._busy:
            return
        candidate_id = self.candidate_combo.currentData()
        self.comparison = None
        self._adopt_retry = None
        self.comparison_view.clear()
        if not isinstance(candidate_id, str):
            self.comparison_status.setText("当前范围没有可比较候选")
            self._set_controls()
            return
        logical_id, revision, digest = self._graph_identity()
        self._start(
            lambda: self.facade.compare_graph_relearn_candidate(
                logical_id, revision, digest, candidate_id,
            ),
            lambda result: self._comparison_completed(result, candidate_id),
            "正在只读比较所选候选…",
        )

    def _feedback_completed(self, result: dict[str, Any]) -> None:
        feedback = self._validated_feedback(result)
        self.feedback = feedback
        issues = [
            item for item in feedback["issues"]
            if self._scope_intersects(item.get("scope"))
        ]
        issue_ids = {item["issue_id"] for item in issues}
        candidates = [
            item for item in feedback["candidates"]
            if item.get("issue_id") in issue_ids
            and self._scope_intersects(item.get("scope"))
        ]
        previous_candidate = self.candidate_combo.currentData()
        self._updating = True
        try:
            self.issue_list.clear()
            for issue in issues:
                item = QListWidgetItem(
                    f"[{self._status_text(issue.get('graph_status'))}] "
                    f"{issue.get('message', '')} · {issue['issue_id']}"
                )
                item.setData(Qt.ItemDataRole.UserRole, deepcopy(issue))
                self.issue_list.addItem(item)
            self.candidate_combo.clear()
            self.candidate_combo.addItem("请选择候选", None)
            for candidate in candidates:
                self.candidate_combo.addItem(
                    f"[{self._status_text(candidate.get('graph_status'))}] "
                    f"{candidate['candidate_id']}",
                    candidate["candidate_id"],
                )
            index = self.candidate_combo.findData(previous_candidate)
            self.candidate_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self._updating = False
        self.comparison = None
        self._adopt_retry = None
        self.comparison_view.clear()
        self.comparison_status.setText("请选择一个候选查看修改前后。")
        self.status_label.setText(
            f"已读取反馈修订 {feedback['feedback_revision']}；"
            f"当前范围有 {len(issues)} 个问题、{len(candidates)} 个候选。"
        )
        self._set_controls()

    def _issue_completed(
        self,
        result: dict[str, Any],
        message: str,
        scope: dict[str, list[str]],
    ) -> None:
        persisted = result.get("issue")
        receipt = result.get("receipt")
        if (
            not isinstance(persisted, dict)
            or persisted.get("message") != message
            or persisted.get("scope") != scope
            or not isinstance(persisted.get("issue_id"), str)
            or not isinstance(receipt, dict)
            or receipt.get("revision") != self.feedback["feedback_revision"] + 1
        ):
            raise ValueError("persisted graph issue is missing")
        self._issue_retry = None
        self.issue_message.clear()
        self.status_label.setText(f"问题已持久化：{persisted['issue_id']}；正在刷新列表。")
        self.refresh_feedback()

    def _comparison_completed(self, result: dict[str, Any], candidate_id: str) -> None:
        comparison = self._validated_comparison(result, candidate_id)
        within_selection = all(
            self._operation_within_selection(operation)
            for operation in comparison["operations"]
        )
        comparison["selection_scope_status"] = (
            "exact" if within_selection else "out_of_scope"
        )
        self.comparison = comparison
        if within_selection:
            self.comparison_status.setText(
                f"候选状态：{self._status_text(comparison['status'])} · "
                f"{'包含实际变化' if comparison['changed'] else '没有实际变化'}"
            )
        else:
            self.comparison_status.setText(
                "候选超出当前单一选择范围；可以查看差异，但不能在此对话框采用。"
            )
        self.comparison_view.setPlainText(
            json.dumps(
                comparison["operation_previews"],
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
        self.status_label.setText("候选仅已比较，尚未采用；当前图没有改变。")
        self._set_controls()

    def _adoption_completed(self, result: dict[str, Any]) -> None:
        adopted = self._validate_snapshot(result)
        if (
            adopted["logical_workflow_id"] != self.snapshot["logical_workflow_id"]
            or adopted["revision"] != self.snapshot["revision"] + 1
            or adopted.get("parent_sha256") != self.snapshot["content_sha256"]
        ):
            raise ValueError("adopted graph revision lineage is invalid")
        self.comparison = None
        self._adopt_retry = None
        self.revisionAdopted.emit(deepcopy(adopted))
        self.accept()

    def _validated_feedback(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("graph feedback response is invalid")
        logical_id, revision, digest = self._graph_identity()
        if (
            value.get("contract_version") != "desktop_graph_relearn_feedback_v1"
            or value.get("logical_workflow_id") != logical_id
            or value.get("graph_revision") != revision
            or value.get("graph_sha256") != digest
            or type(value.get("feedback_revision")) is not int
            or value["feedback_revision"] < 0
            or not isinstance(value.get("issues"), list)
            or not isinstance(value.get("candidates"), list)
            or value.get("staging_only") is not True
            or value.get("artifact_is_authorization") is not False
            or value.get("execute_binding_enabled") is not False
        ):
            raise ValueError("graph feedback identity is invalid")
        for field, identity in (("issues", "issue_id"), ("candidates", "candidate_id")):
            values = value[field]
            if any(
                not isinstance(item, dict)
                or not isinstance(item.get(identity), str)
                or not item[identity]
                for item in values
            ) or len({item[identity] for item in values}) != len(values):
                raise ValueError(f"graph feedback {field} are invalid")
        return deepcopy(value)

    def _validated_comparison(self, value: Any, candidate_id: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("graph comparison response is invalid")
        if (
            value.get("contract_version") != "desktop_graph_relearn_comparison_v1"
            or value.get("logical_workflow_id") != self.snapshot["logical_workflow_id"]
            or value.get("candidate_id") != candidate_id
            or value.get("status") not in {"current", "stale", "withdrawn", "blocked"}
            or value.get("baseline_graph_sha256") != self.snapshot["content_sha256"]
            or (
                value.get("status") == "current"
                and value.get("current_graph_sha256")
                != self.snapshot["content_sha256"]
            )
            or type(value.get("changed")) is not bool
            or not isinstance(value.get("operations"), list)
            or not isinstance(value.get("operation_previews"), list)
            or len(value["operations"]) != len(value["operation_previews"])
        ):
            raise ValueError("graph comparison identity is invalid")
        for field in ("candidate_sha256", "review_baseline_sha256"):
            digest = value.get(field)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("graph comparison digest is invalid")
        return deepcopy(value)

    def _validate_snapshot(self, value: Any) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or value.get("contract_version") != "formal_graph_revision_v1"
            or not isinstance(value.get("logical_workflow_id"), str)
            or type(value.get("revision")) is not int
            or value["revision"] < 1
            or not isinstance(value.get("content_sha256"), str)
            or len(value["content_sha256"]) != 64
            or not isinstance(value.get("graph"), dict)
            or not isinstance(value["graph"].get("nodes"), list)
            or not isinstance(value["graph"].get("edges"), list)
        ):
            raise ValueError("formal graph revision is invalid")
        return deepcopy(value)

    def _validate_selection(self, value: Any) -> tuple[str, str]:
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or value[0] not in {"node", "edge"}
            or not isinstance(value[1], str)
        ):
            raise ValueError("graph relearn selection is invalid")
        collection = self.snapshot["graph"]["nodes" if value[0] == "node" else "edges"]
        identity = "node_id" if value[0] == "node" else "edge_id"
        if sum(item.get(identity) == value[1] for item in collection if isinstance(item, dict)) != 1:
            raise ValueError("graph relearn selection is not present")
        return value

    def _scope(self) -> dict[str, list[str]]:
        return {
            "node_ids": [self.selection[1]] if self.selection[0] == "node" else [],
            "edge_ids": [self.selection[1]] if self.selection[0] == "edge" else [],
        }

    def _scope_intersects(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        field = "node_ids" if self.selection[0] == "node" else "edge_ids"
        return self.selection[1] in value.get(field, [])

    def _operation_within_selection(self, operation: Any) -> bool:
        if not isinstance(operation, dict):
            return False
        operation_type = operation.get("type")
        if operation_type in {
            "update_node_meaning", "update_region_bbox",
            "update_node_recognition_text",
        }:
            return (
                self.selection[0] == "node"
                and operation.get("node_id") == self.selection[1]
            )
        if operation_type in {"update_edge_target", "update_edge_semantics"}:
            return (
                self.selection[0] == "edge"
                and operation.get("edge_id") == self.selection[1]
            )
        return False

    def _graph_identity(self) -> tuple[str, int, str]:
        return (
            self.snapshot["logical_workflow_id"],
            self.snapshot["revision"],
            self.snapshot["content_sha256"],
        )

    def _start(
        self,
        operation: Callable[[], dict[str, Any]],
        completed: Callable[[dict[str, Any]], None],
        status: str,
    ) -> None:
        if self._busy:
            return
        self._request_id += 1
        request_id = self._request_id
        self._busy = True
        self._job_outcome = None
        self.status_label.setText(status)
        self._set_controls()
        job = make_job(request_id, operation, self)
        self._jobs.add(job)
        job.succeeded.connect(
            lambda result_id, result: self._capture_success(
                result_id, result, completed,
            )
        )
        job.failed.connect(self._capture_failure)
        job.finished.connect(lambda: self._job_finished(job, request_id))
        job.start()

    def _capture_success(
        self,
        request_id: int,
        result: object,
        completed: Callable[[dict[str, Any]], None],
    ) -> None:
        if request_id != self._request_id:
            return
        self._job_outcome = ("success", result, completed)

    def _capture_failure(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self._job_outcome = ("failure", message, None)

    def _job_finished(self, job: FacadeJob, request_id: int) -> None:
        self._jobs.discard(job)
        job.deleteLater()
        if request_id != self._request_id:
            return
        outcome = self._job_outcome
        self._job_outcome = None
        self._busy = False
        if outcome is None:
            self._error("图重学后台任务未返回结果；当前状态已保留。")
            self._set_controls()
            return
        kind, result, completed = outcome
        if kind == "failure":
            self._error(f"图重学操作失败；没有采用或覆盖任何内容：{result}")
            self._set_controls()
            return
        if not isinstance(result, dict):
            self._error("图重学操作返回格式无效；当前状态已保留。")
            self._set_controls()
            return
        try:
            if not callable(completed):
                raise ValueError("graph relearn completion callback is invalid")
            completed(result)
        except (KeyError, TypeError, ValueError) as error:
            self._error(f"图重学响应无效；当前状态已保留：{error}")
        self._set_controls()

    def _set_controls(self) -> None:
        ready = self.feedback is not None and not self._busy
        self.issue_message.setEnabled(not self._busy)
        self.submit_issue_button.setEnabled(
            ready and bool(self.issue_message.toPlainText().strip())
        )
        self.refresh_button.setEnabled(not self._busy)
        self.issue_list.setEnabled(not self._busy)
        self.candidate_combo.setEnabled(ready)
        adoptable = (
            self.comparison is not None
            and self.comparison.get("status") == "current"
            and self.comparison.get("changed") is True
            and self.comparison.get("selection_scope_status") == "exact"
        )
        self.adopt_button.setEnabled(ready and adoptable)
        close_button = self.buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setEnabled(not self._busy)

    def _error(self, message: str) -> None:
        self.status_label.setText(message)
        self.errorRaised.emit(message)

    @staticmethod
    def _status_text(value: Any) -> str:
        return {
            "open": "待处理",
            "pending": "待人工比较",
            "current": "当前可采用",
            "stale": "已过期",
            "withdrawn": "已撤回",
            "blocked": "已阻止",
        }.get(value, str(value or "未知"))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy:
            self._error("操作仍在进行，完成前不能关闭此窗口。")
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:
        if self._busy:
            self._error("操作仍在进行，完成前不能关闭此窗口。")
            return
        super().reject()


__all__ = ["GraphRelearnDialog"]
