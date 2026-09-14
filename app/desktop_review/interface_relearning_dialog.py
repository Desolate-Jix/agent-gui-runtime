"""独立界面 Agent 修正反馈与候选对比；不审核、不执行。"""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4
import json
from typing import Any

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QLineEdit, QPushButton, QPlainTextEdit, QVBoxLayout, QTableWidget, QTableWidgetItem, QGroupBox, QComboBox, QWidget, QSplitter, QHeaderView
from .canvas import ReviewCanvas


class InterfaceRelearningDialog(QDialog):
    adopted = Signal(object)
    errorRaised = Signal(str)

    def __init__(self, facade: Any, snapshot: dict, selected_region_id: str | None = None, parent=None):
        super().__init__(parent)
        self.facade, self.snapshot = facade, deepcopy(snapshot)
        self.selected_region_id = selected_region_id
        self.issue = None
        self.candidate_id = None
        self._compared = False
        self._pending_keys = {}
        self.setWindowTitle("Agent 修正建议")
        self.resize(1120, 760)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("说明需要修正的内容，Agent 会给出建议。比较后可采用；当前内容不会自动改变。"))
        body = QSplitter(Qt.Orientation.Horizontal)
        left, right = QWidget(), QWidget()
        left_layout, right_layout = QVBoxLayout(left), QVBoxLayout(right)
        left.setMinimumWidth(260)
        body.addWidget(left); body.addWidget(right); body.setSizes([280, 810])
        body.setChildrenCollapsible(False)
        root.addWidget(body, 1)
        self.message = QLineEdit(); self.message.setPlaceholderText("说明需要修正的界面或识别框")
        form = QFormLayout(); form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow("反馈说明", self.message)
        self.scope = QComboBox(); self.scope.addItem("整个界面", [])
        if selected_region_id:
            region = next((r for r in snapshot["content"]["regions"] if r["region_id"] == selected_region_id), None)
            if region is not None:
                self.scope.addItem("选中框：" + str(region.get("name") or "识别框"), [selected_region_id])
                self.scope.setCurrentIndex(1)
        form.addRow("反馈范围", self.scope); left_layout.addLayout(form)
        actions = QHBoxLayout()
        self.create_button = QPushButton("提交反馈"); self.refresh_button = QPushButton("刷新反馈")
        actions.addWidget(self.create_button); actions.addWidget(self.refresh_button); left_layout.addLayout(actions)
        left_layout.addWidget(QLabel("反馈记录"))
        self.issues = QListWidget(); self.issues.setWordWrap(True); left_layout.addWidget(self.issues, 2)
        left_layout.addWidget(QLabel("Agent 的修正建议"))
        self.candidates = QListWidget(); left_layout.addWidget(self.candidates, 1)
        self.scope_label = QLabel("选择反馈查看其固定基线和建议"); self.scope_label.setWordWrap(True)
        right_layout.addWidget(self.scope_label)
        previews = QHBoxLayout()
        self.baseline_canvas, self.candidate_canvas = ReviewCanvas(self), ReviewCanvas(self)
        for title, canvas in (("基线（只读）", self.baseline_canvas), ("候选（只读）", self.candidate_canvas)):
            box = QGroupBox(title); box_layout = QVBoxLayout(box); box_layout.addWidget(canvas)
            canvas.setInteractive(False); canvas.setMinimumHeight(220)
            fit = QPushButton("适应窗口"); fit.clicked.connect(canvas.fit_image); actual = QPushButton("原图 100%"); actual.clicked.connect(canvas.show_actual_size)
            controls = QHBoxLayout(); controls.addWidget(fit); controls.addWidget(actual); box_layout.addLayout(controls); previews.addWidget(box)
        right_layout.addLayout(previews, 2)
        self.diff_table = QTableWidget(0, 4); self.diff_table.setHorizontalHeaderLabels(["修改位置", "修改前", "Agent 建议", "变化"]); self.diff_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.diff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.diff_table.setWordWrap(True); right_layout.addWidget(self.diff_table, 1)
        self.baseline = QPlainTextEdit(); self.baseline.setReadOnly(True); self.baseline.hide()
        self.candidate = QPlainTextEdit(); self.candidate.setReadOnly(True); self.candidate.hide()
        root.addWidget(self.baseline); root.addWidget(self.candidate)
        row = QHBoxLayout(); self.compare_button = QPushButton("比较建议"); self.adopt_button = QPushButton("采用这份修正"); self.reject_button = QPushButton("保留当前内容"); self.withdraw_button = QPushButton("撤回反馈"); self.close_button = QPushButton("关闭")
        self.adopt_button.setProperty("primary", True)
        for button in (self.compare_button, self.adopt_button, self.reject_button, self.withdraw_button, self.close_button): row.addWidget(button)
        root.addLayout(row)
        self.status = QLabel("等待 Agent 候选"); self.status.setWordWrap(True); root.addWidget(self.status)
        self.create_button.clicked.connect(self.create_issue); self.refresh_button.clicked.connect(self.refresh)
        self.issues.currentItemChanged.connect(self.select_issue); self.candidates.currentItemChanged.connect(self.select_candidate)
        self.compare_button.clicked.connect(self.compare); self.adopt_button.clicked.connect(self.adopt); self.reject_button.clicked.connect(self.reject_issue); self.withdraw_button.clicked.connect(self.withdraw); self.close_button.clicked.connect(self.reject)
        self.refresh()

    def refresh(self):
        try:
            values = self.facade.list_interface_relearning(self.snapshot["interface_id"])
            self.issues.clear()
            self._reset_comparison()
            for value in values or []:
                label = {"open": "待处理", "adopted": "已采用", "rejected": "已保留当前", "withdrawn": "已撤回"}.get(value["status"], "未知状态")
                item = QListWidgetItem(f"{value['message']}\n{label} · {len(value['candidate_ids'])} 份建议")
                item.setToolTip(value["issue_id"])
                item.setData(Qt.ItemDataRole.UserRole, deepcopy(value)); self.issues.addItem(item)
            self.status.setText("等待 Agent 候选" if not values else "选择反馈查看候选")
        except Exception as error:
            self._error(error)

    def create_issue(self):
        try:
            if not self.message.text().strip():
                self.status.setText("请填写反馈说明。"); return
            args = (
                self.snapshot["interface_id"], self.snapshot["revision"], self.snapshot["content_sha256"],
                self.scope.currentData(), self.message.text().strip())
            key = self._key("create", args)
            result = self.facade.request_interface_relearning(*args, key)
            self.refresh()
            for index in range(self.issues.count()):
                if self.issues.item(index).data(Qt.ItemDataRole.UserRole)["issue_id"] == result["issue_id"]:
                    self.issues.setCurrentRow(index); break
            self.status.setText("反馈已提交，等待 Agent 建议；当前内容未改变。")
        except Exception as error: self._error(error)

    def select_issue(self, current, _previous):
        self.issue = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.candidates.clear(); self.baseline.clear(); self.candidate.clear(); self.candidate_id = None; self._reset_comparison()
        if not self.issue: return
        try:
            detail = self.facade.read_interface_relearning(self.issue["issue_id"])
            self.issue = detail
            self.scope_label.setText(detail["message"] + "\n反馈范围：" + ("整个界面" if not detail["region_ids"] else f"{len(detail['region_ids'])} 个识别框") + f" · 基线版本 {detail['baseline_revision']}")
            ids = detail.get("candidate_ids", []) or []
            for index, candidate_id in enumerate(ids, 1):
                item = QListWidgetItem(f"候选 {index}"); item.setToolTip(str(candidate_id)); item.setData(Qt.ItemDataRole.UserRole, str(candidate_id)); self.candidates.addItem(item)
            self.reject_button.setEnabled(detail["status"] == "open")
            self.withdraw_button.setEnabled(detail["status"] == "open")
            if not self.candidates.count(): self.status.setText("尚无建议；让已连接的 Agent 读取反馈后提交修正。")
        except Exception as error: self._error(error)

    def select_candidate(self, current, _previous):
        self.candidate_id = str(current.data(Qt.ItemDataRole.UserRole)) if current else None
        self._reset_comparison()

    def compare(self):
        if not self.issue or not self.candidate_id: return
        self._reset_comparison()
        try:
            value = self.facade.compare_interface_relearning(self.issue["issue_id"], self.candidate_id)
            baseline, candidate = value["baseline"], value["candidate"]
            if (baseline["content_sha256"] != self.issue["baseline_content_sha256"]
                    or candidate["candidate_id"] != self.candidate_id or candidate["issue_id"] != self.issue["issue_id"]):
                raise ValueError("候选或基线与所选反馈不一致，请重新加载。")
            self.baseline.setPlainText(json.dumps(baseline, ensure_ascii=False, indent=2)); self.candidate.setPlainText(json.dumps(candidate, ensure_ascii=False, indent=2))
            self._render_previews(baseline, candidate)
            self._render_diff(baseline, candidate); self._compared = True
            self._compared_identity = (self.issue["issue_id"], self.candidate_id)
            self.adopt_button.setEnabled(value["status"] == "open")
            self.status.setText("比较框的位置及下方修改内容，满意后点击“采用这份修正”。" if value["status"] == "open" else "这条反馈已处理，仅供查看。")
        except Exception as error: self._error(error)

    def adopt(self):
        if not self.issue or not self.candidate_id: return
        try:
            current = self.facade.load_interface_content(self.snapshot["interface_id"])
            baseline_revision = self.issue["baseline_revision"]
            baseline_sha = self.issue["baseline_content_sha256"]
            key = self._key("adopt", (self.issue["issue_id"], self.candidate_id, baseline_revision, baseline_sha))
            if (current["revision"] != baseline_revision or current["content_sha256"] != baseline_sha) and not getattr(self, "_adoption_pending", False):
                self._error("界面已有新修改，本候选基于旧版本，未覆盖当前内容。请基于最新版本重新反馈。")
                return
            if not self._compared or self._compared_identity != (self.issue["issue_id"], self.candidate_id):
                self.status.setText("请先比较选中的建议，再采用。"); return
            if bool(getattr(self.parent(), "dirty", False)):
                self._error("原界面有未保存修改，请先返回保存或放弃，再采用建议。")
                return
            self._adoption_pending = True
            self.facade.adopt_interface_relearning(self.issue["issue_id"], self.candidate_id, baseline_revision, baseline_sha, key)
            self._adoption_pending = False
            latest = self.facade.load_interface_content(self.snapshot["interface_id"])
            self.adopted.emit(deepcopy(latest)); self.accept()
        except Exception as error: self._error(error)

    def reject_issue(self):
        if not self.issue: return
        try: self.facade.reject_interface_relearning(self.issue["issue_id"], "保留当前界面", self._key("reject", "retain")); self.refresh()
        except Exception as error: self._error(error)

    def withdraw(self):
        if not self.issue: return
        try: self.facade.withdraw_interface_relearning(self.issue["issue_id"], "撤回本次反馈", self._key("withdraw", "withdraw")); self.refresh()
        except Exception as error: self._error(error)

    def _key(self, operation: str, payload) -> str:
        identity = json.dumps([operation, self.snapshot["interface_id"], payload], ensure_ascii=False, sort_keys=True)
        return self._pending_keys.setdefault(identity, "relearn-" + uuid4().hex)

    def _reset_comparison(self):
        self._compared = False; self._compared_identity = None; self._adoption_pending = False
        self.baseline.clear(); self.candidate.clear(); self.diff_table.setRowCount(0); self.baseline_canvas.clear_canvas(); self.candidate_canvas.clear_canvas(); self.adopt_button.setEnabled(False)

    def _render_diff(self, baseline, candidate):
        old = baseline.get("content", baseline); new = candidate.get("content", candidate); rows = []
        labels = {"meaning": "含义", "recognition_text": "识别文字", "name": "名称", "kind": "类型", "bbox": "位置与大小"}
        for field in ("meaning", "recognition_text"):
            if old.get(field) != new.get(field): rows.append(("整个界面 · " + labels[field], old.get(field, ""), new.get(field, ""), "修改"))
        old_regions = {r.get("region_id"): r for r in old.get("regions", [])}; new_regions = {r.get("region_id"): r for r in new.get("regions", [])}
        for rid in sorted(set(old_regions) | set(new_regions)):
            a, b = old_regions.get(rid, {}), new_regions.get(rid, {})
            change = "新增" if rid not in old_regions else "删除" if rid not in new_regions else "修改"
            for field in ("name", "kind", "recognition_text", "meaning", "bbox"):
                if a.get(field) != b.get(field): rows.append((f"{a.get('name') or b.get('name') or '识别框'} · {labels[field]}", a.get(field, ""), b.get(field, ""), change))
        self.diff_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, value in enumerate(values): self.diff_table.setItem(row, col, QTableWidgetItem(str(value)))
        self.diff_table.resizeRowsToContents()

    def _render_previews(self, baseline, candidate):
        evidence = self.facade.load_interface_content_evidence(baseline["interface_id"], baseline["version_id"])
        file = self.facade._artifact_file(evidence["image_path"], "界面修正基线截图")
        raw = file.read_bytes()
        import hashlib
        if hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
            raise ValueError("基线截图校验失败，不能采用建议。")
        for canvas, content in ((self.baseline_canvas, baseline["content"]), (self.candidate_canvas, candidate["content"])):
            canvas.set_image(raw, content.get("regions", []), (baseline["interface_id"], baseline["version_id"], evidence["sha256"]))
            canvas.setInteractive(False)
            canvas.fit_image()

    def _error(self, error):
        detail = str(error)
        if "persistence_failed" in detail:
            detail = "保存过程中断，请保留此窗口并重试同一按钮；重试不会重复保存。"
        elif "adoption_pending" in detail:
            detail = "上次采用尚未完成，请对同一份建议重试采用，再处理其他反馈。"
        elif "stale" in detail:
            detail = "界面已有新修改，本建议未覆盖当前内容。请基于最新版本重新反馈。"
        self.status.setText("操作失败：" + detail); self.errorRaised.emit(detail)


__all__ = ["InterfaceRelearningDialog"]
