"""原生精确人审对话框；只调用本地 NativeReviewFacade。"""
from __future__ import annotations

import copy
import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.agent.workflow_versions import PUBLICATION_FIELDS, make_record
from .jobs import FacadeJob, make_job


class ExactReviewDialog(QDialog):
    """固定工作区修订的逐项审核、编译和入库界面。"""


    def __init__(self, facade: Any, workspace: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self.workspace = copy.deepcopy(workspace)
        self._graph_mode = workspace.get("contract_version") == "formal_graph_revision_v1"
        self.review: dict[str, Any] | None = None
        self._decision_dirty = False
        self._prepared_stop_ids: list[str] = []
        self._busy = False
        self._request_id = 0
        self._jobs: set[FacadeJob] = set()
        self.setWindowTitle("精确人工审核")
        self.resize(980, 720)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        if self._graph_mode:
            pin_text = (f"固定流程图：{self.workspace['logical_workflow_id']} / 修订 {self.workspace['revision']}\n"
                        f"图摘要：{self.workspace['content_sha256']}")
        else:
            pin_text = (f"固定工作区：{self.workspace['task_id']} / {self.workspace['batch_id']} / 修订 {self.workspace['revision']}\n"
                        f"来源：{self.workspace['source']} · {self.workspace['source_ref']}")
        self.pin_label = QLabel(pin_text)
        self.pin_label.setWordWrap(True)
        layout.addWidget(self.pin_label)
        form = QFormLayout()
        self.application_kind = QComboBox()
        self.application_kind.setObjectName("applicationKindField")
        self.application_kind.addItem("native", "native")
        self.application_kind.addItem("web", "web")
        self.application_display_name = QLineEdit()
        self.application_display_name.setObjectName("applicationDisplayNameField")
        self.application_identity = QLineEdit()
        self.application_identity.setObjectName("applicationIdentityField")
        self.application_identity.setPlaceholderText("native: executable_identity；web: canonical_origin")
        self.application_product_name = QLineEdit()
        self.application_product_name.setObjectName("applicationProductNameField")
        form.addRow("应用类型", self.application_kind)
        form.addRow("显示名称", self.application_display_name)
        form.addRow("可验证身份", self.application_identity)
        form.addRow("产品名（可选）", self.application_product_name)
        layout.addLayout(form)
        self.relationship_summary = QLabel("步骤/关系绑定：请逐项明确选择；不会自动推断。")
        self.relationship_summary.setWordWrap(True)
        layout.addWidget(self.relationship_summary)
        self.step_relationship_table = QTableWidget(0, 4)
        self.step_relationship_table.setObjectName("stepRelationshipTable")
        self.step_relationship_table.setHorizontalHeaderLabels(["步骤", "起始", "到达", "明确关系"])
        self.step_relationship_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Tab 离开关系表，避免内嵌下拉框与单元格之间的焦点循环。
        self.step_relationship_table.setTabKeyNavigation(False)
        self.step_relationship_table.setMaximumHeight(105)
        layout.addWidget(self.step_relationship_table)
        self.stop_box = QVBoxLayout()
        stop_widget = QWidget()
        stop_widget.setLayout(self.stop_box)
        layout.addWidget(QLabel("明确停止/缺知识界面（不会删除危险动作）"))
        layout.addWidget(stop_widget)
        self.prepare_button = QPushButton("准备精确审核")
        self.prepare_button.setObjectName("prepareExactReviewButton")
        self.prepare_button.clicked.connect(self.prepare)
        layout.addWidget(self.prepare_button)
        self.subject_table = QTableWidget(0, 5)
        self.subject_table.setObjectName("exactSubjectTable")
        self.subject_table.setHorizontalHeaderLabels(["确认", "类别", "标签", "内部项目 ID", "内容摘要"])
        self.subject_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.subject_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Tab 切换审核控件，方向键和空格用于逐项勾选。
        self.subject_table.setTabKeyNavigation(False)
        self.subject_table.itemSelectionChanged.connect(self._show_subject_detail)
        layout.addWidget(self.subject_table, 1)
        layout.addWidget(QLabel("所选审核项目完整内容（只读）"))
        self.subject_detail = QPlainTextEdit()
        self.subject_detail.setObjectName("exactSubjectDetail")
        self.subject_detail.setReadOnly(True)
        self.subject_detail.setMaximumBlockCount(4000)
        self.subject_detail.setFixedHeight(130)
        layout.addWidget(self.subject_detail)
        buttons = QHBoxLayout()
        self.record_button = QPushButton("保存审核决定")
        self.record_button.setObjectName("recordDecisionsButton")
        self.compile_button = QPushButton("编译检查")
        self.compile_button.setObjectName("compileExactReviewButton")
        self.publish_button = QPushButton("入工作流库")
        self.publish_button.setObjectName("publishExactReviewButton")
        self.record_button.clicked.connect(self.record_decisions)
        self.compile_button.clicked.connect(self.compile_review)
        self.publish_button.clicked.connect(self.publish_review)
        buttons.addWidget(self.record_button)
        buttons.addWidget(self.compile_button)
        buttons.addWidget(self.publish_button)
        layout.addLayout(buttons)
        self.status_label = QLabel("尚未准备；不会自动批准、编译或发布。")
        self.status_label.setObjectName("exactReviewStatusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)
        layout.addWidget(close_buttons)
        self._build_stop_boxes()
        self._populate_relationship_choices()
        self._set_controls()

    def _application_binding(self) -> dict[str, Any]:
        kind = str(self.application_kind.currentData())
        binding: dict[str, Any] = {"kind": kind, "display_name": self.application_display_name.text().strip()}
        if kind == "native":
            binding["executable_identity"] = self.application_identity.text().strip()
            product = self.application_product_name.text().strip()
            if product:
                binding["product_name"] = product
        else:
            binding["canonical_origin"] = self.application_identity.text().strip()
        return binding

    def _step_relationships(self) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for row in range(self.step_relationship_table.rowCount()):
            identifier = self.step_relationship_table.item(row, 0)
            choice = self.step_relationship_table.cellWidget(row, 3)
            if identifier is None:
                continue
            relation_id = choice.currentData() if isinstance(choice, QComboBox) else None
            mapping[str(identifier.data(Qt.ItemDataRole.UserRole))] = [str(relation_id)] if relation_id else []
        return mapping

    def _stop_interface_ids(self) -> list[str]:
        return [box.property("interface_id") for box in self.findChildren(QCheckBox, "exactStopInterface") if box.isChecked()]

    def prepare(self) -> None:
        if self._busy or self.review is not None:
            if self.review is not None:
                self.status_label.setText("当前精确审核已固定；关闭后重新打开才能准备另一绑定。")
            return
        binding = copy.deepcopy(self._application_binding())
        step_relationships = copy.deepcopy(self._step_relationships())
        stop_interface_ids = list(self._stop_interface_ids())
        self._prepared_stop_ids = stop_interface_ids
        if self._graph_mode:
            self._start(
                lambda: self.facade.prepare_graph_exact_review(
                    self.workspace["logical_workflow_id"], self.workspace["revision"],
                    self.workspace["content_sha256"], binding, stop_interface_ids,
                ), self._prepared,
            )
            return
        self._start(
            lambda: self.facade.prepare_exact_review(
                self.workspace["task_id"], self.workspace["batch_id"], self.workspace["revision"], binding, step_relationships, stop_interface_ids,
            ),
            self._prepared,
        )

    def record_decisions(self) -> None:
        if self.review is None or self._busy:
            return
        confirmed = [
            self.subject_table.cellWidget(row, 0).property("subject_id")
            for row in range(self.subject_table.rowCount())
            if isinstance(self.subject_table.cellWidget(row, 0), QCheckBox) and self.subject_table.cellWidget(row, 0).isChecked()
        ]
        review_ref = self.review["review_ref"]
        expected_revision = self.review["approval_revision"]
        wanted = [str(subject_id) for subject_id in confirmed]
        self._start(
            lambda: self.facade.record_review_decisions(review_ref, expected_revision, wanted),
            lambda response: self._recorded(response, expected_revision, wanted),
        )

    def compile_review(self) -> None:
        if self.review is None or self._busy:
            return
        if self._decision_dirty:
            self.status_label.setText("复选框有未保存修改；请先保存审核决定。")
            return
        review_ref = self.review["review_ref"]
        expected_revision = self.review["approval_revision"]
        self._start(
            lambda: self.facade.compile_exact_review(review_ref, expected_revision),
            lambda response: self._compiled(response, expected_revision),
        )

    def publish_review(self) -> None:
        if self.review is None or self._busy:
            return
        if self._decision_dirty:
            self.status_label.setText("复选框有未保存修改；请先保存审核决定。")
            return
        receipt = self.review.get("compile_receipt_id")
        if not receipt:
            self.status_label.setText("没有可信编译回执，不能入库。")
            return
        self._start(lambda: self.facade.publish_exact_review(receipt), self._published)

    def _start(self, operation: Any, completed: Any) -> None:
        self._busy = True
        self._request_id += 1
        request_id = self._request_id
        self._set_controls()
        job = make_job(request_id, operation, self)
        job.succeeded.connect(lambda result_id, result: self._completed(result_id, result, completed))
        job.failed.connect(self._failed)
        self._jobs.add(job)
        job.finished.connect(lambda: self._jobs.discard(job))
        job.finished.connect(job.deleteLater)
        job.start()

    def _completed(self, request_id: int, result: object, completed: Any) -> None:
        if request_id != self._request_id:
            return
        self._busy = False
        if not isinstance(result, dict):
            self.status_label.setText("操作返回格式无效；输入和勾选仍保留。")
            self._set_controls()
            return
        completed(result)
        self._set_controls()

    def _failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self._busy = False
        self.status_label.setText(f"操作失败；输入和勾选仍保留：{message}")
        self._set_controls()

    def _prepared(self, review: dict[str, Any]) -> None:
        if not self._valid_review_identity(review, require_workspace=True):
            self.status_label.setText("准备响应身份不匹配；保留输入且未加载审核内容。")
            return
        self.review = copy.deepcopy(review)
        self._decision_dirty = False
        self._build_stop_boxes()
        self._render_review()

    def _recorded(self, review: dict[str, Any], expected_revision: int, wanted: list[str]) -> None:
        if not self._valid_review_identity(review, require_workspace=True) or not self._valid_record_response(review, expected_revision, wanted):
            self.status_label.setText("审核决定响应身份或修订不匹配；当前勾选未替换。")
            return
        self.review = copy.deepcopy(review)
        self._decision_dirty = False
        self._render_review()

    def _compiled(self, review: dict[str, Any], expected_revision: int) -> None:
        if self.review is None or not self._valid_compile_response(review, expected_revision):
            self.status_label.setText("编译响应身份或修订不匹配；当前审核未替换。")
            return
        merged = copy.deepcopy(self.review)
        merged.update(review)
        self.review = merged
        self._render_review()

    def _published(self, receipt: dict[str, Any]) -> None:
        if self._graph_mode:
            valid = self.review is not None and bool(self.review.get("compile_receipt_id"))
            if valid:
                try:
                    expected = make_record(
                        {key: self.review.get(key) for key in PUBLICATION_FIELDS},
                        self.review.get("asset_id"), self.review.get("asset_sha256"),
                    )
                except ValueError:
                    valid = False
                else:
                    valid = all(type(receipt.get(key)) is type(value) and receipt.get(key) == value
                                for key, value in expected.items())
            status = receipt.get("status")
            valid = (valid and status in ("current", "superseded", "withdrawn")
                     and receipt.get("current") is (status == "current")
                     and receipt.get("artifact_is_authorization") is False
                     and receipt.get("execute_binding_enabled") is False)
            if not valid:
                self.status_label.setText("入库回执身份、修订或权限标记不匹配；未确认发布结果，请重新核验。")
                return
        self.status_label.setText(f"已收到入库回执：{receipt.get('status', 'unknown')}；不会启动运行时会话。")

    def _build_stop_boxes(self) -> None:
        while self.stop_box.count():
            item = self.stop_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if self._graph_mode:
            interfaces = [{"interface_id": node["node_id"], "meaning": node.get("display_name", "")}
                          for node in self.workspace["graph"]["nodes"]]
        else:
            interfaces = self.workspace["batch"].get("interfaces", [])
        for interface in interfaces:
            box = QCheckBox(f"{interface['interface_id']} · {interface.get('meaning', '')}")
            box.setObjectName("exactStopInterface")
            box.setProperty("interface_id", interface["interface_id"])
            box.setChecked(interface["interface_id"] in self._prepared_stop_ids)
            self.stop_box.addWidget(box)

    def _populate_relationship_choices(self) -> None:
        self.step_relationship_table.setRowCount(0)
        if self._graph_mode:
            self.step_relationship_table.hide()
            self.relationship_summary.setText("关系、动作与证据取自当前流程图；需要修改时请返回图上修正。")
            return
        relationships = self.workspace["batch"].get("relationships", [])
        for row, step in enumerate(self.workspace["batch"].get("steps", [])):
            self.step_relationship_table.insertRow(row)
            for column, value in enumerate((step.get("step_id", ""), step.get("start_state", ""), step.get("arrival_state", ""))):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, step.get("step_id"))
                self.step_relationship_table.setItem(row, column, item)
            choice = QComboBox()
            choice.addItem("仅审核关系，不绑定步骤", None)
            for relation in relationships:
                if relation.get("from_interface_id") == step.get("start_state") and relation.get("to_interface_id") == step.get("arrival_state"):
                    choice.addItem(str(relation.get("relationship_id", "")), relation.get("relationship_id"))
            self.step_relationship_table.setCellWidget(row, 3, choice)
        self.step_relationship_table.resizeColumnsToContents()

    def _render_review(self) -> None:
        if self.review is None:
            return
        self.subject_table.setRowCount(0)
        for row, subject in enumerate(self.review.get("subjects", [])):
            self.subject_table.insertRow(row)
            box = QCheckBox()
            box.setProperty("subject_id", subject.get("subject_id"))
            box.blockSignals(True)
            box.setChecked(bool(subject.get("confirmed")))
            box.blockSignals(False)
            box.toggled.connect(self._decisions_changed)
            self.subject_table.setCellWidget(row, 0, box)
            values = (subject.get("kind", ""), subject.get("label", ""), subject.get("subject_id", ""), self._summary(subject.get("content")))
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.subject_table.setItem(row, column, item)
        self.subject_table.setColumnHidden(3, True)
        self.subject_table.setColumnWidth(0, 48)
        self.subject_table.setColumnWidth(1, 110)
        self.subject_table.setColumnWidth(2, 180)
        self.subject_table.setColumnWidth(4, 280)
        blocked = self.review.get("blocked_reasons", [])
        messages = "; ".join(str(item.get("message", item)) for item in blocked) if isinstance(blocked, list) else str(blocked)
        self.status_label.setText(f"状态：{self.review.get('status', 'unknown')}；审核修订：{self.review.get('approval_revision', 0)}。{messages}")

    def _summary(self, content: Any) -> str:
        if isinstance(content, dict):
            action = content.get("semantic_action") or content.get("action_type")
            text_parameters = content.get("text_parameters")
            if action == "fill_field" and isinstance(text_parameters, dict):
                source = text_parameters.get("content", {})
                value = ("执行前变量：" + str(source.get("name", "?"))) if source.get("kind") == "variable" else ("敏感固定内容" if text_parameters.get("sensitive") else "固定内容：" + str(source.get("text", "")))
                return f"填写字段 {text_parameters.get('target_field_id', '?')}；{value}；不提交"
            parameters = content.get("scroll_parameters")
            if action == "scroll_region" and isinstance(parameters, dict):
                return "scroll: {container}; vertical {direction}; {clicks} wheel detents".format(
                    container=parameters.get("target_container_id", "?"),
                    direction=parameters.get("direction", "?"),
                    clicks=parameters.get("wheel_clicks", "?"),
                )
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True)
        return text.replace("\n", " ")[:160]

    def _show_subject_detail(self) -> None:
        rows = self.subject_table.selectionModel().selectedRows() if self.subject_table.selectionModel() else []
        if self.review is None or not rows:
            return
        subject_id = self.subject_table.cellWidget(rows[0].row(), 0).property("subject_id")
        subject = next((item for item in self.review.get("subjects", []) if item.get("subject_id") == subject_id), None)
        if subject is not None:
            self.subject_detail.setPlainText(json.dumps(subject, ensure_ascii=False, indent=2, sort_keys=True))

    def _decisions_changed(self, _: bool) -> None:
        if self.review is not None and not self._busy:
            self._decision_dirty = True
            self.status_label.setText("复选框有未保存修改；请显式保存审核决定。")
            self._set_controls()

    def _valid_review_identity(self, result: dict[str, Any], *, require_workspace: bool = False) -> bool:
        review_ref = result.get("review_ref")
        if not isinstance(review_ref, str):
            return False
        if self.review is not None and review_ref != self.review["review_ref"]:
            return False
        if not require_workspace:
            return True
        return all(result.get(key) == expected for key, expected in self._pinned_source_fields().items())

    def _pinned_source_fields(self) -> dict[str, Any]:
        if self._graph_mode:
            refs = self.workspace["source_refs"]
            return {"contract_version": "desktop_graph_exact_review_v1",
                    "logical_workflow_id": self.workspace["logical_workflow_id"],
                    "graph_revision": self.workspace["revision"],
                    "graph_sha256": self.workspace["content_sha256"],
                    "task_id": refs["task_id"], "batch_id": refs["batch_id"],
                    "source_ref": refs["batch_sha256"]}
        return {"task_id": self.workspace["task_id"], "batch_id": self.workspace["batch_id"],
                "source_ref": self.workspace["source_ref"], "workspace_revision": self.workspace["revision"]}

    def _valid_record_response(self, result: dict[str, Any], expected_revision: int, wanted: list[str]) -> bool:
        revision = result.get("approval_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision not in (expected_revision, expected_revision + 1):
            return False
        subjects = result.get("subjects")
        if not isinstance(subjects, list) or self.review is None:
            return False
        current_ids = {item.get("subject_id") for item in self.review.get("subjects", []) if isinstance(item, dict)}
        returned_ids: set[Any] = set()
        returned_confirmed: set[str] = set()
        for subject in subjects:
            if not isinstance(subject, dict) or not isinstance(subject.get("subject_id"), str) or not isinstance(subject.get("confirmed"), bool):
                return False
            subject_id = subject["subject_id"]
            if subject_id in returned_ids:
                return False
            returned_ids.add(subject_id)
            if subject["confirmed"]:
                returned_confirmed.add(subject_id)
        return returned_ids == current_ids and returned_confirmed == set(wanted)

    def _valid_compile_response(self, result: dict[str, Any], expected_revision: int) -> bool:
        if not isinstance(result.get("status"), str):
            return False
        if self.review is None:
            return False
        if self._graph_mode and (not self._valid_review_identity(result, require_workspace=True)
                                 or "approval_revision" not in result):
            return False
        for field, expected in (
            ("review_ref", self.review["review_ref"]),
            *self._pinned_source_fields().items(),
        ):
            if field in result and result[field] != expected:
                return False
        if "approval_revision" in result:
            revision = result["approval_revision"]
            if isinstance(revision, bool) or not isinstance(revision, int) or revision != expected_revision:
                return False
        return True

    def _set_controls(self) -> None:
        prepared = self.review is not None
        input_enabled = not self._busy and not prepared
        for widget in (self.application_kind, self.application_display_name, self.application_identity, self.application_product_name, self.step_relationship_table):
            widget.setEnabled(input_enabled)
        for box in self.findChildren(QCheckBox, "exactStopInterface"):
            box.setEnabled(input_enabled)
        self.prepare_button.setEnabled(not self._busy and not prepared)
        self.subject_table.setEnabled(not self._busy and prepared)
        self.record_button.setEnabled(not self._busy and prepared)
        self.compile_button.setEnabled(not self._busy and prepared and not self._decision_dirty)
        self.publish_button.setEnabled(not self._busy and prepared and not self._decision_dirty and bool(self.review and self.review.get("compile_receipt_id")))

    def _confirm_discard_decisions(self) -> bool:
        if not self._decision_dirty:
            return True
        result = QMessageBox.question(
            self, "未保存审核决定", "关闭将放弃未保存的审核撤回或确认。是否关闭？",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Discard

    def reject(self) -> None:
        if self._busy or self._jobs:
            QMessageBox.information(self, "精确审核仍在运行", "请等待当前本地审核操作结束后关闭。")
            return
        if not self._confirm_discard_decisions():
            return
        super().done(QDialog.DialogCode.Rejected)

    def done(self, result: int) -> None:
        if self._busy or self._jobs:
            QMessageBox.information(self, "精确审核仍在运行", "请等待当前本地审核操作结束后关闭。")
            return
        if not self._confirm_discard_decisions():
            return
        super().done(result)

    def closeEvent(self, event: Any) -> None:
        if self._busy or self._jobs:
            QMessageBox.information(self, "精确审核仍在运行", "请等待当前本地审核操作结束后关闭。")
            event.ignore()
            return
        if not self._confirm_discard_decisions():
            event.ignore()
            return
        event.accept()
