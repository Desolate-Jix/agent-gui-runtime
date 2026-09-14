"""固定人工修订的原生重学、候选比较与明确采用。"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from .jobs import FacadeJob, make_job
from .external_mapping import canonical_json_bytes
from .workspace import DesktopReviewError, _validate_snapshot
from .candidate_rejection_dialog import RejectionReasonDialog
from .geometry_comparison import GeometryComparisonWidget


_FLOW_FIELD_LABELS = {
    "start_state": "起始界面", "arrival_state": "到达界面",
    "prerequisites": "前置条件", "stop_condition": "停止条件",
    "from_interface_id": "关系来源界面", "to_interface_id": "关系目的界面",
    "step_order": "步骤审核顺序", "entity": "新增控件",
}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def _display_without_png(value):
    """仅隐藏展示副本中的二进制编码，原候选仍完整参与摘要和采用。"""
    if isinstance(value, dict):
        return {key: "（PNG 内容已隐藏，请打开新界面截图检查）" if key == "png_base64" else _display_without_png(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_display_without_png(item) for item in value]
    return value


def _comparison_display_rows(diffs: list[dict]) -> list[dict]:
    """仅展开新增流程实体的展示字段，不改变原候选或授权依据。"""
    from app.agent_link.contracts import AgentLinkError, InterfaceInput, RelationshipInput, StepInput, parse
    from .geometry_comparison import _validated_png

    rows = []
    for diff in diffs:
        target_type = diff["target_type"]
        if diff["field"] != "entity" or target_type not in {"step", "relationship", "screenshot", "interface"}:
            rows.append(copy.deepcopy(diff))
            continue
        label = {"step": "新增步骤", "relationship": "新增关系", "screenshot": "新增截图", "interface": "新增界面"}[target_type]
        if diff["baseline"] is not None or diff["current"] is not None:
            rows.append({**copy.deepcopy(diff), "_display_label": label})
            continue
        proposed = diff["proposed"]
        try:
            if target_type == "screenshot":
                if (not isinstance(proposed, dict) or set(proposed) != {"screenshot_id", "png_base64", "sha256", "width", "height"}
                        or proposed["screenshot_id"] != diff["target_id"]):
                    raise ValueError("新增截图身份或字段无效")
                _validated_png(proposed)
                fields = [("标识", proposed["screenshot_id"]), ("SHA-256", proposed["sha256"]),
                          ("尺寸", f"{proposed['width']} × {proposed['height']} px")]
            elif target_type == "interface":
                if (not isinstance(proposed, dict) or set(proposed) != {"anchor_interface_id", "interface"}
                        or not isinstance(proposed["anchor_interface_id"], str) or not proposed["anchor_interface_id"].strip()):
                    raise ValueError("新增界面包装无效")
                entity = parse(InterfaceInput, proposed["interface"], "新增界面")
                if entity["interface_id"] != diff["target_id"]:
                    raise ValueError("新增界面身份不一致")
                fields = [("标识", entity["interface_id"]), ("关联既有界面", proposed["anchor_interface_id"]),
                          ("截图", entity["screenshot_id"]), ("含义", entity["meaning"]), ("识别框", entity["regions"])]
            elif target_type == "step":
                if not isinstance(proposed, dict) or set(proposed) != {"after_step_id", "step"}:
                    raise ValueError("新增步骤包装无效")
                anchor = proposed["after_step_id"]
                if anchor is not None and (not isinstance(anchor, str) or not anchor.strip()):
                    raise ValueError("新增步骤位置无效")
                entity = parse(StepInput, proposed["step"], "新增步骤")
                if entity["step_id"] != diff["target_id"]:
                    raise ValueError("新增步骤身份不一致")
                fields = [("标识", entity["step_id"]), ("插入位置", "流程开头" if anchor is None else f"步骤 {anchor} 之后"),
                          ("操作", entity["action_type"]), ("目标控件", entity["target_region_id"] or "无（观察／停止）"),
                          ("起始界面", entity["start_state"]), ("到达界面", entity["arrival_state"]),
                          ("前置条件", entity["prerequisites"]), ("预期结果", entity["expected_result"]),
                          ("停止条件", entity["stop_condition"])]
            else:
                entity = parse(RelationshipInput, proposed, "新增关系")
                if entity["relationship_id"] != diff["target_id"]:
                    raise ValueError("新增关系身份不一致")
                fields = [("标识", entity["relationship_id"]), ("来源界面", entity["from_interface_id"]),
                          ("目的界面", entity["to_interface_id"]), ("类别", entity["kind"])]
        except (AgentLinkError, ValueError):
            rows.append({**copy.deepcopy(diff), "_display_label": label + "（格式无效）"})
            continue
        rows.extend({**copy.deepcopy(diff), "_display_label": label + " · " + field, "proposed": value}
                    for field, value in fields)
    return rows


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


class RelearnReviewDialog(QDialog):
    def __init__(self, facade: Any, workspace: dict, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.workspace = copy.deepcopy(workspace)
        self.review: dict | None = None
        self.comparison: dict | None = None
        self._jobs: set[FacadeJob] = set()
        self._busy = False
        self._request_id = 0
        self._pending: tuple[str, Any] | None = None
        self._submission: tuple[Any, str] | None = None
        self.adoption_receipt: dict | None = None
        self.requires_workspace_reload = False
        self.rejection_receipt: dict | None = None
        self._rejection_reason = ""
        self.setWindowTitle("问题重学与候选比较")
        self.resize(1120, 800)
        self._build()
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        pin = QLabel(f"固定人工修订 {self.workspace['revision']} · {self.workspace['task_id']} / {self.workspace['batch_id']}\n原始来源：{self.workspace['source_ref']}")
        pin.setWordWrap(True)
        layout.addWidget(pin)
        hint = QLabel("先圈定界面/关系，再提交重学问题。修改流程连接需包含原来和新的两端界面；调整顺序覆盖选定界面的全部起始步骤，范围外位置不变。不会启动 Agent、自动采用、批准或执行。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        inputs = QSplitter(Qt.Orientation.Horizontal)
        self.scope_list = QListWidget()
        self.scope_list.setObjectName("relearnScopeList")
        batch = self.workspace["batch"]
        for field, identifier, label in (("interfaces", "interface_id", "界面"), ("relationships", "relationship_id", "关系")):
            for value in batch[field]:
                item = QListWidgetItem(f"{label}：{value.get('meaning') or value.get('kind') or value[identifier]} · {value[identifier]}")
                item.setData(Qt.ItemDataRole.UserRole, (field, value[identifier]))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.scope_list.addItem(item)
        self.scope_list.itemChanged.connect(self._controls)
        self.message = QPlainTextEdit()
        self.message.setObjectName("relearnMessage")
        self.message.setPlaceholderText("哪里不对？希望 Agent 重新核对什么？（最多 4000 字）")
        self.message.textChanged.connect(self._controls)
        inputs.addWidget(self.scope_list); inputs.addWidget(self.message)
        inputs.setMaximumHeight(160)
        layout.addWidget(inputs)
        controls = QHBoxLayout()
        self.request_button = QPushButton("提交重学问题")
        self.request_button.setObjectName("requestRelearnButton")
        self.request_button.clicked.connect(self.request_relearn)
        self.refresh_button = QPushButton("刷新反馈与候选")
        self.refresh_button.setObjectName("refreshRelearnButton")
        self.refresh_button.clicked.connect(self.refresh)
        self.withdraw_button = QPushButton("撤回所选问题")
        self.withdraw_button.setObjectName("withdrawRelearnButton")
        self.withdraw_button.clicked.connect(self.withdraw_issue)
        self.compare_button = QPushButton("比较所选候选（只读）")
        self.compare_button.setObjectName("compareRelearnButton")
        self.compare_button.clicked.connect(self.compare_candidate)
        for button in (self.request_button, self.refresh_button, self.withdraw_button, self.compare_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        tabs = QTabWidget()
        self.tabs = tabs
        tabs.setObjectName("relearnRecordTabs")
        self.issue_table = self._table(["问题说明", "状态", "范围"])
        self.issue_table.setObjectName("relearnIssueTable")
        self.candidate_table = self._table(["候选", "对应问题", "Agent 状态", "人工决定"])
        self.candidate_table.setObjectName("relearnCandidateTable")
        tabs.addTab(self.issue_table, "问题记录")
        tabs.addTab(self.candidate_table, "Agent 候选")
        tabs.setMaximumHeight(220)
        layout.addWidget(tabs)
        self.issue_table.itemSelectionChanged.connect(self._controls)
        self.candidate_table.itemSelectionChanged.connect(self._controls)
        layout.addWidget(QLabel("三方比较：重学基线 / 当前人工版本 / Agent 候选。比较不写入；需下方单独确认采用为待审版本。"))
        self.diff_table = self._table(["对象", "字段", "重学基线", "当前人工版本", "Agent 候选"])
        self.diff_table.setObjectName("relearnDiffTable")
        layout.addWidget(self.diff_table, 1)
        self.detail = QPlainTextEdit()
        self.detail.setObjectName("relearnComparisonDetail")
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(135)
        layout.addWidget(self.detail)
        self.geometry_button = QPushButton("查看截图上的框对照（只读）")
        self.geometry_button.setObjectName("showGeometryComparisonButton")
        self.geometry_button.clicked.connect(self.show_geometry_comparison)
        layout.addWidget(self.geometry_button)
        self.interface_button = QPushButton("查看新界面截图与识别框（只读）")
        self.interface_button.setObjectName("showNewInterfaceEvidenceButton")
        self.interface_button.clicked.connect(self.show_interface_comparison)
        layout.addWidget(self.interface_button)
        self.adopt_button = QPushButton("明确采用此候选为新的待审版本…")
        self.adopt_button.setObjectName("adoptRelearnCandidateButton")
        self.adopt_button.clicked.connect(self.adopt_candidate)
        layout.addWidget(self.adopt_button)
        self.reject_candidate_button = QPushButton("拒绝此候选…")
        self.reject_candidate_button.setObjectName("rejectRelearnCandidateButton")
        self.reject_candidate_button.clicked.connect(self.reject_candidate)
        layout.addWidget(self.reject_candidate_button)
        self.status = QLabel("尚未读取反馈。")
        self.status.setObjectName("relearnStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._controls()

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _pin(self):
        return (self.workspace["task_id"], self.workspace["batch_id"], self.workspace["revision"])

    def _scope(self):
        result = {"interface_ids": [], "relationship_ids": []}
        for index in range(self.scope_list.count()):
            item = self.scope_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                field, identifier = item.data(Qt.ItemDataRole.UserRole)
                result["interface_ids" if field == "interfaces" else "relationship_ids"].append(identifier)
        return result

    @staticmethod
    def _selected(table):
        rows = table.selectionModel().selectedRows()
        return table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None

    def refresh(self):
        pin = self._pin()
        self._start("load", None, lambda: self.facade.load_relearn_review(*pin))

    def request_relearn(self):
        if self._busy or self.review is None:
            return
        scope, message = self._scope(), self.message.toPlainText().strip()
        if not any(scope.values()) or not 1 <= len(message) <= 4000:
            self.status.setText("请选择至少一个范围，并填写 1–4000 字的问题说明。")
            return
        feedback_revision = self.review["feedback_revision"]
        request = (self._pin(), feedback_revision, scope, message)
        if self._submission is None or self._submission[0] != request:
            self._submission = (copy.deepcopy(request), "relearn-ui-" + uuid4().hex)
        key, pin = self._submission[1], self._pin()
        self._start("request", {"revision": feedback_revision, "scope": scope, "message": message}, lambda: self.facade.request_relearn(*pin, feedback_revision, scope, message, key))

    def withdraw_issue(self):
        issue = self._selected(self.issue_table)
        if self._busy or self.review is None or not issue or issue.get("status") != "open":
            return
        if QMessageBox.question(self, "撤回重学问题", "撤回后，该问题的候选不能采用。是否撤回？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        revision, issue_id, pin = self.review["feedback_revision"], issue["issue_id"], self._pin()
        key = "withdraw-ui-" + hashlib.sha256(json.dumps([pin, issue_id, revision], ensure_ascii=False).encode("utf-8")).hexdigest()
        self._start("withdraw", {"revision": revision, "issue_id": issue_id}, lambda: self.facade.withdraw_relearn(*pin, issue_id, revision, key))

    def compare_candidate(self):
        candidate = self._selected(self.candidate_table)
        if self._busy or not candidate:
            return
        candidate_id, pin = candidate["candidate_id"], self._pin()
        self._clear_comparison()
        self._start("compare", candidate_id, lambda: self.facade.compare_relearn_candidate(*pin, candidate_id))

    def _can_adopt(self):
        selected, compared = self._selected(self.candidate_table), self.comparison
        return bool(
            not self._busy and self.adoption_receipt is None and selected and compared
            and selected.get("candidate_id") == compared.get("candidate_id")
            and self._valid_comparison(compared, selected["candidate_id"])
            and compared.get("status") == "current" and not compared.get("blocked_reasons")
            and not any(item.get("candidate_id") == compared["candidate_id"] for item in (self.review or {}).get("candidate_decisions", []))
            and compared.get("diffs")
            and self._project_comparison(compared) is not None
            and all(isinstance(compared.get(key), str) and len(compared[key]) == 64
                    and all(char in "0123456789abcdef" for char in compared[key])
                    for key in ("candidate_sha256", "review_baseline_sha256"))
            and not self.message.toPlainText().strip() and not any(self._scope().values())
        )

    def _can_show_geometry(self):
        selected, compared = self._selected(self.candidate_table), self.comparison
        return bool(
            not self._busy and not self.requires_workspace_reload and selected and compared
            and self._valid_comparison(compared, selected["candidate_id"])
            and any(diff.get("target_type") == "region" and diff.get("field") in {"bbox", "entity"} for diff in compared["diffs"])
        )

    def show_geometry_comparison(self):
        if not self._can_show_geometry():
            return
        try:
            widget = GeometryComparisonWidget(self.workspace, self.comparison)
        except ValueError as error:
            self.status.setText("框对照证据无效，未显示：" + str(error))
            return
        dialog = QDialog(self)
        dialog.setObjectName("geometryComparisonDialog")
        dialog.setWindowTitle("截图框三方对照（只读）")
        dialog.resize(1200, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def _can_show_interface(self):
        selected, compared = self._selected(self.candidate_table), self.comparison
        return bool(not self._busy and not self.requires_workspace_reload and selected and compared
                    and self._valid_comparison(compared, selected["candidate_id"])
                    and any(diff.get("target_type") == "interface" and diff.get("field") == "entity" for diff in compared["diffs"]))

    def show_interface_comparison(self):
        if not self._can_show_interface(): return
        from .interface_comparison import InterfaceComparisonWidget
        try:
            widget = InterfaceComparisonWidget(self.workspace, self.comparison)
        except ValueError as error:
            self.status.setText("新界面证据无效，未显示：" + str(error))
            return
        dialog = QDialog(self)
        dialog.setObjectName("interfaceComparisonDialog")
        dialog.setWindowTitle("新界面候选证据（只读）")
        dialog.resize(1200, 760)
        layout = QVBoxLayout(dialog); layout.addWidget(widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        dialog.exec(); dialog.deleteLater()

    def _can_reject_candidate(self):
        selected, compared = self._selected(self.candidate_table), self.comparison
        return bool(
            not self._busy and not self.requires_workspace_reload and self.review is not None
            and selected and compared and selected.get("candidate_id") == compared.get("candidate_id")
            and self._valid_comparison(compared, selected["candidate_id"])
            and compared["status"] != "withdrawn"
            and "locally_rejected" not in compared["blocked_reasons"]
            and not any(item.get("candidate_id") == selected["candidate_id"] for item in self.review.get("candidate_decisions", []))
            and _sha256(compared.get("candidate_sha256"))
            and (compared.get("review_baseline_sha256") is None or _sha256(compared["review_baseline_sha256"]))
            and not self.message.toPlainText().strip() and not any(self._scope().values())
        )

    def reject_candidate(self):
        if not self._can_reject_candidate():
            return
        compared = copy.deepcopy(self.comparison)
        prompt = RejectionReasonDialog(compared, self._rejection_reason, self)
        result = prompt.exec()
        self._rejection_reason = prompt.reason
        prompt.deleteLater()
        if result != QDialog.DialogCode.Accepted or not self._can_reject_candidate() or compared != self.comparison:
            return
        reason = self._rejection_reason
        if not 1 <= len(reason) <= 4000:
            self.status.setText("拒绝原因须为 1–4000 字。")
            return
        revision = self.review.get("decision_revision", 0)
        args = (*self._pin(), compared["candidate_id"], compared["candidate_sha256"], compared["review_baseline_sha256"], revision, reason)
        key = "reject-ui-" + hashlib.sha256(json.dumps(args, ensure_ascii=False).encode("utf-8")).hexdigest()
        self._start("reject_candidate", {"comparison": compared, "decision_revision": revision, "reason": reason}, lambda: self.facade.reject_relearn_candidate(*args, key))

    def _valid_rejection(self, result, binding):
        compared = binding["comparison"]
        if not isinstance(result, dict) or result.get("contract_version") != "desktop_candidate_rejection_receipt_v1" or result.get("staging_only") is not True:
            return False
        if any(result.get(key) != compared.get(key) for key in ("task_id", "batch_id", "source_ref", "candidate_id", "candidate_sha256", "review_baseline_sha256")):
            return False
        if any(type(result.get(key)) is not int for key in ("workspace_revision", "decision_revision", "current_revision", "current_decision_revision")):
            return False
        return (
            result["workspace_revision"] == self.workspace["revision"]
            and result["decision_revision"] == binding["decision_revision"] + 1
            and result["current_revision"] >= result["workspace_revision"]
            and result["current_decision_revision"] >= result["decision_revision"]
            and result.get("reason") == binding["reason"] and _sha256(result.get("record_sha256"))
        )

    def _render_candidates(self):
        rejected = {item["candidate_id"]: item for item in self.review.get("candidate_decisions", [])}
        self._rows(self.candidate_table, self.review["candidates"], lambda row: [row["candidate_id"], row.get("issue_id", ""), row.get("status", "未知"), "已拒绝：" + rejected[row["candidate_id"]]["reason"] if row["candidate_id"] in rejected else "未决定"])

    def adopt_candidate(self):
        if not self._can_adopt():
            return
        compared = copy.deepcopy(self.comparison)
        if QMessageBox.question(
            self, "采用候选并重新审核",
            f"将候选的 {len(compared['diffs'])} 项候选变更保存为人工修订 {self.workspace['revision'] + 1}。\n"
            "旧版本与 Agent 原始候选保留；新版本需要重新审核，不会批准、入库或执行外部操作。是否采用？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Yes:
            return
        if not self._can_adopt() or compared != self.comparison:
            return
        args = (*self._pin(), compared["candidate_id"], compared["candidate_sha256"], compared["review_baseline_sha256"])
        key = "adopt-ui-" + hashlib.sha256(json.dumps(args, ensure_ascii=False).encode("utf-8")).hexdigest()
        self.requires_workspace_reload = True
        self._start("adopt", compared, lambda: self.facade.adopt_relearn_candidate(*args, key))

    def _valid_adoption(self, result, compared):
        if not isinstance(result, dict) or result.get("contract_version") != "desktop_relearn_adoption_receipt_v1" or result.get("staging_only") is not True:
            return False
        if any(result.get(key) != compared.get(key) for key in ("task_id", "batch_id", "source_ref", "candidate_id", "candidate_sha256", "review_baseline_sha256")):
            return False
        if any(type(result.get(key)) is not int for key in ("previous_revision", "adopted_revision", "current_revision")):
            return False
        previous, adopted, current = (result[key] for key in ("previous_revision", "adopted_revision", "current_revision"))
        if previous != self.workspace["revision"] or adopted != previous + 1 or current < adopted or type(result.get("is_current")) is not bool or result["is_current"] != (current == adopted):
            return False
        snapshot = result.get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("contract_version") != "desktop_review_workspace_v2" or any(snapshot.get(key) != self.workspace.get(key) for key in ("task_id", "batch_id", "source_ref", "source")):
            return False
        try:
            _validate_snapshot(snapshot, existing_png_sha256=frozenset(
                shot["sha256"] for shot in self.workspace["batch"]["screenshots"]))
        except DesktopReviewError:
            return False
        if type(snapshot.get("revision")) is not int or snapshot["revision"] != adopted or snapshot.get("review_status") != "needs_human_review" or not isinstance(snapshot.get("workflow_review_path"), str) or not snapshot["workflow_review_path"]:
            return False
        parent, origin = snapshot["parent_revision"], snapshot["relearn_adoption"]
        if not isinstance(parent, dict) or parent.get("revision") != previous or parent.get("workspace_sha256") != hashlib.sha256(canonical_json_bytes(self.workspace) + b"\n").hexdigest():
            return False
        if not isinstance(origin, dict) or origin.get("comparison") != compared or any(origin.get(key) != compared.get(key) for key in ("candidate_id", "candidate_sha256", "issue_id", "review_baseline_sha256")):
            return False
        expected = self._project_comparison(compared)
        return expected is not None and snapshot.get("batch") == expected

    def _project_comparison(self, compared):
        from app.agent_link.candidate_projection import CandidateProjectionError, apply_candidate_diffs
        if not isinstance(compared, dict) or not isinstance(compared.get("diffs"), list):
            return None
        if any(not isinstance(diff, dict) or "baseline" not in diff or diff["baseline"] != diff.get("current") for diff in compared["diffs"]):
            return None
        try:
            return apply_candidate_diffs(self.workspace["batch"], compared["diffs"])
        except CandidateProjectionError:
            return None

    def _start(self, kind, binding, operation):
        if self._busy:
            return
        self._busy = True
        self._request_id += 1
        self._pending = (kind, binding)
        self._controls()
        self.status.setText("正在处理本地重学记录…")
        job = make_job(self._request_id, operation, self)
        job.succeeded.connect(self._succeeded)
        job.failed.connect(self._failed)
        self._jobs.add(job)
        job.finished.connect(lambda: self._jobs.discard(job))
        job.finished.connect(job.deleteLater)
        job.start()

    def _identity(self, result):
        return isinstance(result, dict) and all(result.get(key) == value for key, value in (
            ("task_id", self.workspace["task_id"]), ("batch_id", self.workspace["batch_id"]),
            ("source_ref", self.workspace["source_ref"]), ("workspace_revision", self.workspace["revision"]),
        )) and type(result.get("workspace_revision")) is int

    def _valid_view(self, result, kind, binding):
        if not self._identity(result) or result.get("contract_version") != "desktop_relearn_review_v1" or result.get("staging_only") is not True:
            return False
        revision = result.get("feedback_revision")
        if type(revision) is not int or revision < 0 or self.review and revision < self.review["feedback_revision"]:
            return False
        if kind in ("request", "withdraw") and revision != binding["revision"] + 1:
            return False
        for field, identifier in (("issues", "issue_id"), ("candidates", "candidate_id")):
            items = result.get(field)
            if not isinstance(items, list) or any(not isinstance(item, dict) or not isinstance(item.get(identifier), str) or not item[identifier] for item in items):
                return False
            if len({item[identifier] for item in items}) != len(items):
                return False
        if kind == "request" and not any(issue.get("message") == binding["message"] and issue.get("scope") == binding["scope"] and issue.get("baseline_revision") == revision and issue.get("status") == "open" for issue in result["issues"]):
            return False
        if kind == "withdraw" and not any(issue["issue_id"] == binding["issue_id"] and issue.get("status") == "withdrawn" for issue in result["issues"]):
            return False
        decision_revision, decisions = result.get("decision_revision", 0), result.get("candidate_decisions", [])
        if type(decision_revision) is not int or decision_revision < 0 or not isinstance(decisions, list) or decision_revision != len(decisions):
            return False
        if self.review and decision_revision < self.review.get("decision_revision", 0):
            return False
        candidate_ids = {item["candidate_id"] for item in result["candidates"]}
        decided = set()
        for index, decision in enumerate(decisions, 1):
            if not isinstance(decision, dict) or not isinstance(decision.get("candidate_id"), str) or not isinstance(decision.get("reason"), str) or not decision["reason"] or not _sha256(decision.get("record_sha256")) or not _sha256(decision.get("candidate_sha256")):
                return False
            if type(decision.get("decision_revision")) is not int or decision["decision_revision"] != index:
                return False
            if any(decision.get(key) != result.get(key) for key in ("task_id", "batch_id", "source_ref")):
                return False
            if type(decision.get("workspace_revision")) is not int or not 1 <= decision["workspace_revision"] <= result["workspace_revision"]:
                return False
            if decision["candidate_id"] not in candidate_ids or decision["candidate_id"] in decided:
                return False
            decided.add(decision["candidate_id"])
        return True

    def _valid_comparison(self, result, candidate_id):
        if not self._identity(result) or result.get("contract_version") != "desktop_relearn_comparison_v1" or result.get("candidate_id") != candidate_id:
            return False
        diffs, reasons = result.get("diffs"), result.get("blocked_reasons")
        return (result.get("status") in {"current", "stale", "withdrawn", "legacy_unbound", "blocked"}
                and isinstance(diffs, list) and all(isinstance(item, dict) and {"target_type", "target_id", "field", "baseline", "current", "proposed"} <= set(item) for item in diffs)
                and isinstance(reasons, list) and all(isinstance(reason, str) for reason in reasons))

    def _succeeded(self, request_id, result):
        if request_id != self._request_id or self._pending is None:
            return
        kind, binding = self._pending
        self._pending = None
        self._busy = False
        if kind == "reject_candidate":
            if not self._valid_rejection(result, binding):
                self.status.setText("拒绝回执的身份、原因或修订不匹配；原因保留，请同键重试或刷新核验。")
            else:
                self.rejection_receipt = copy.deepcopy(result)
                self.review["decision_revision"] = result["current_decision_revision"]
                self.review.setdefault("candidate_decisions", []).append(copy.deepcopy(result))
                self._clear_comparison()
                self._render_candidates()
                self._rejection_reason = ""
                self.requires_workspace_reload = result["current_revision"] != self.workspace["revision"]
                self.status.setText("已记录拒绝此候选；人工修订、原始提议和旧审核不变，未启动重学或执行。" + ("已有后续人工版本，请关闭后重载。" if self.requires_workspace_reload else "可刷新查看持久记录。"))
        elif kind == "adopt":
            if not self._valid_adoption(result, binding):
                self.status.setText("采用回执的内容或身份不匹配，未替换当前显示。可用同一请求重试，或关闭后重新加载核验。")
            else:
                self.adoption_receipt = copy.deepcopy(result)
                self.status.setText(
                    f"已采用为修订 {result['adopted_revision']}（待审）。"
                    + ("已有后续人工修订，将重新加载最新版本。" if not result["is_current"] else "关闭此窗口返回主界面复审。")
                    + " 未批准、入库或执行。"
                )
        elif kind == "compare":
            if not self._valid_comparison(result, binding):
                self.status.setText("候选比较返回的格式或身份不匹配，未显示提议。")
            else:
                self.comparison = copy.deepcopy(result)
                self._rows(self.diff_table, _comparison_display_rows(result["diffs"]), lambda row: [
                    f"{row['target_type']} · {row['target_id']}",
                    row.get("_display_label", _FLOW_FIELD_LABELS.get(row["field"], row["field"])),
                    "不存在" if row["field"] == "entity" and row["baseline"] is None else _display_without_png(row["baseline"]),
                    "不存在" if row["field"] == "entity" and row["current"] is None else _display_without_png(row["current"]),
                    _display_without_png(row["proposed"]),
                ])
                self.detail.setPlainText(json.dumps(_display_without_png(result), ensure_ascii=False, indent=2))
                self.status.setText(f"只读比较：{result['status']}。" + "；".join(result["blocked_reasons"]) + " 未采用或修改人工版本。")
        elif not self._valid_view(result, kind, binding):
            self.status.setText("反馈返回的格式、身份或修订不匹配；问题草稿保留，请刷新核验。")
        else:
            self.review = copy.deepcopy(result)
            self._clear_comparison()
            self._rows(self.issue_table, result["issues"], lambda row: [row.get("message", row["issue_id"]), row.get("status", "未知"), row.get("scope", {})])
            self._render_candidates()
            if kind == "request":
                self.message.clear()
                for index in range(self.scope_list.count()):
                    self.scope_list.item(index).setCheckState(Qt.CheckState.Unchecked)
                self._submission = None
            self.status.setText(f"反馈版本 {result['feedback_revision']} · {len(result['issues'])} 个问题 · {len(result['candidates'])} 个候选。" + ("问题已提交，等待 Agent 读取；未自动启动 Agent。" if kind == "request" else "未修改人工版本。"))
        self._controls()

    @staticmethod
    def _rows(table, rows, values):
        table.setRowCount(0)
        for index, row in enumerate(rows):
            table.insertRow(index)
            for column, value in enumerate(values(row)):
                item = QTableWidgetItem(_text(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(_text(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, copy.deepcopy(row))
                table.setItem(index, column, item)

    def _failed(self, request_id, message):
        if request_id != self._request_id or self._pending is None:
            return
        kind = self._pending[0]
        self._pending = None
        self._busy = False
        self.status.setText(("采用结果未确认；可重试同一请求或关闭后重载核验：" if kind == "adopt" else "重学操作失败，草稿保留：") + message)
        self._controls()

    def _clear_comparison(self):
        self.comparison = None
        self.diff_table.setRowCount(0)
        self.detail.clear()

    def _controls(self, *_):
        if not hasattr(self, "request_button"):
            return
        idle = not self._busy and not self.requires_workspace_reload
        self.scope_list.setEnabled(idle)
        self.message.setEnabled(idle)
        self.refresh_button.setEnabled(idle)
        self.request_button.setEnabled(idle and self.review is not None and any(self._scope().values()) and 1 <= len(self.message.toPlainText().strip()) <= 4000)
        self.issue_table.setEnabled(idle)
        self.candidate_table.setEnabled(idle)
        selected = self._selected(self.issue_table)
        self.withdraw_button.setEnabled(idle and self.review is not None and bool(selected and selected.get("status") == "open"))
        self.compare_button.setEnabled(idle and self._selected(self.candidate_table) is not None)
        if hasattr(self, "adopt_button"):
            self.adopt_button.setEnabled(self._can_adopt())
        if hasattr(self, "reject_candidate_button"):
            self.reject_candidate_button.setEnabled(self._can_reject_candidate())
        if hasattr(self, "geometry_button"):
            self.geometry_button.setEnabled(self._can_show_geometry())
        if hasattr(self, "interface_button"):
            self.interface_button.setEnabled(self._can_show_interface())

    def _can_close(self):
        if self._busy or self._jobs:
            self.status.setText("本地重学操作仍在处理，请等待结束再关闭。")
            return False
        if self.message.toPlainText().strip() or any(self._scope().values()):
            return QMessageBox.question(self, "尚未提交重学问题", "关闭将丢弃尚未提交的问题和范围。是否关闭？", QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard
        return True

    def reject(self):
        self.done(QDialog.DialogCode.Rejected)

    def done(self, result):
        if self._can_close():
            super().done(result)

    def closeEvent(self, event):
        event.accept() if self._can_close() else event.ignore()
