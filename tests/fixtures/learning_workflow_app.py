"""全新原生基准界面；验收真值保留在界面之外。"""

from __future__ import annotations

from hashlib import sha256
import json

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)


class LearningWorkflowWindow(QWidget):
    def __init__(self, records: list[dict], *, event_sink=None):
        super().__init__()
        self.setWindowTitle("Record Desk")
        self.setObjectName("learningWorkflowWindow")
        self.resize(640, 480)
        self._records = [self._validate_record(record) for record in records]
        self._event_sink = event_sink
        if len({record["id"] for record in self._records}) != len(self._records):
            raise ValueError("record IDs must be unique")
        self._visible_ids = [record["id"] for record in self._records]
        self._selected_id = None
        self._current_case_id = None
        self._event_index = 0
        self._reset_event_index = 0
        self._layout_variant = "default"
        layout = QVBoxLayout(self)
        self.main_layout = layout
        # 独立页面锚点不与任何可点击目标共用控件身份。
        self.page_anchor = QLabel("Record Desk workspace")
        self.page_anchor.setObjectName("pageAnchor")
        self.page_anchor.setAccessibleName("Record Desk workspace")
        layout.addWidget(self.page_anchor)
        self.search_area = QWidget()
        self.search_area.setObjectName("searchArea")
        search = QHBoxLayout(self.search_area)
        self.search_layout = search
        self.query_field = QLineEdit()
        self.query_field.setObjectName("queryField")
        self.query_field.setAccessibleName("Record ID search field")
        self.query_field.setPlaceholderText("Record ID")
        self.query_field.textChanged.connect(self._query_changed)
        self.search_button = QPushButton("Find")
        self.search_button.setObjectName("searchButton")
        self.search_button.setAccessibleName("Find records")
        self.search_button.clicked.connect(self._filter)
        search.addWidget(self.query_field)
        search.addWidget(self.search_button)
        layout.addWidget(self.search_area)
        self.rows_container = QWidget()
        self.rows_container.setObjectName("resultRows")
        self.rows_layout = QVBoxLayout(self.rows_container)
        layout.addWidget(self.rows_container)
        self.detail_output = QLabel("No record selected")
        self.detail_output.setObjectName("detailOutput")
        self.detail_output.setAccessibleName("Current record detail")
        layout.addWidget(self.detail_output)
        self.controlled_field = QLineEdit()
        self.controlled_field.setObjectName("controlledField")
        self.controlled_field.setAccessibleName("Controlled value field")
        self.controlled_field.setPlaceholderText("Enter the current detail value")
        self.controlled_field.textChanged.connect(self._field_changed)
        layout.addWidget(self.controlled_field)
        self.verify_button = QPushButton("Verify value")
        self.verify_button.setObjectName("verifyValueButton")
        self.verify_button.setAccessibleName("Verify controlled value")
        self.verify_button.clicked.connect(self._verify_field)
        layout.addWidget(self.verify_button)
        self.verification_output = QLabel("Not verified")
        self.verification_output.setObjectName("verificationOutput")
        self.verification_output.setAccessibleName("Controlled value verification")
        layout.addWidget(self.verification_output)
        self.notice_button = QPushButton("Show notice")
        self.notice_button.setObjectName("noticeButton")
        self.notice_button.clicked.connect(self.show_notice)
        layout.addWidget(self.notice_button)
        self.notice_dialog = None
        self._render_rows()

    @staticmethod
    def _validate_record(record: dict) -> dict:
        if not isinstance(record, dict) or set(record) != {"id", "name", "detail"}:
            raise ValueError("record requires id, name and detail")
        if any(not isinstance(record[key], str) or not record[key] for key in record):
            raise ValueError("record values must be non-empty strings")
        return dict(record)

    def _render_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        by_id = {record["id"]: record for record in self._records}
        for record_id in self._visible_ids:
            record = by_id[record_id]
            row = QWidget()
            row.setObjectName(f"recordRow_{record_id}")
            row_layout = QHBoxLayout(row)
            label = QLabel(f"{record_id} · {record['name']}")
            label.setObjectName("recordLabel")
            button = QPushButton("Open detail")
            button.setObjectName("openDetailButton")
            button.clicked.connect(lambda checked=False, value=record_id: self._open_detail(value))
            row_layout.addWidget(label)
            row_layout.addWidget(button)
            self.rows_layout.addWidget(row)

    def _filter(self) -> None:
        needle = self.query_field.text().strip().casefold()
        self._visible_ids = [record["id"] for record in self._records if not needle or needle in record["id"].casefold()]
        self._render_rows()
        self._emit({"action": "filter", "query": self.query_field.text(),
                    "visible_ids": list(self._visible_ids)})

    def _query_changed(self, value: str) -> None:
        self._emit({"action": "query_changed", "query": value})

    def _open_detail(self, record_id: str) -> None:
        record = next(record for record in self._records if record["id"] == record_id)
        self._selected_id = record_id
        self.detail_output.setText(f"ID: {record_id} | Detail: {record['detail']}")
        self.verification_output.setText("Not verified")
        self._emit({"action": "open_detail", "record_id": record_id,
                    "actual_detail": self.detail_output.text()})

    def _field_changed(self, value: str) -> None:
        self.verification_output.setText("Not verified")
        self._emit({"action": "controlled_field_changed", "actual_value": value})

    def _verify_field(self) -> None:
        record = next((row for row in self._records if row["id"] == self._selected_id), None)
        actual = self.controlled_field.text()
        expected = record["detail"] if record is not None else None
        matched = expected is not None and actual == expected
        self.verification_output.setText("Matches current detail" if matched else "Value does not match current detail")
        self._emit({"action": "verify_field", "record_id": self._selected_id,
                    "actual_value": actual, "expected_detail": expected, "matched": matched})

    def update_detail(self, record_id: str, detail: str) -> None:
        if not isinstance(detail, str) or not detail:
            raise ValueError("detail must be a non-empty string")
        record = next((row for row in self._records if row["id"] == record_id), None)
        if record is None:
            raise ValueError("record_id must identify an existing record")
        record["detail"] = detail
        if self._selected_id == record_id:
            self.detail_output.setText(f"ID: {record_id} | Detail: {detail}")
            self.verification_output.setText("Not verified")
        self._emit({"action": "set_detail", "record_id": record_id, "detail": detail,
                    "actual_detail": self.detail_output.text() if self._selected_id == record_id else None})

    def records_snapshot(self) -> list[dict]:
        return [dict(record) for record in self._records]

    def reorder_rows(self, ordered_ids: list[str]) -> None:
        if (not isinstance(ordered_ids, list) or any(not isinstance(item, str) for item in ordered_ids)
                or len(ordered_ids) != len(self._records)
                or len(set(ordered_ids)) != len(ordered_ids)
                or set(ordered_ids) != {record["id"] for record in self._records}):
            raise ValueError("ordered_ids must contain each record exactly once")
        by_id = {record["id"]: record for record in self._records}
        self._records = [by_id[record_id] for record_id in ordered_ids]
        self._visible_ids = list(ordered_ids)
        self._render_rows()
        self._emit({"action": "reorder_rows", "visible_ids": list(self._visible_ids)})

    def _emit(self, row: dict) -> int:
        self._event_index += 1
        event = {**row, "case_id": self._current_case_id, "event_index": self._event_index}
        if self._event_sink is not None:
            self._event_sink(event)
        return self._event_index

    def _arrange_core(self, variant: str) -> None:
        layouts = {
            "default": [self.search_area, self.rows_container, self.detail_output],
            "search_below_rows": [self.rows_container, self.search_area, self.detail_output],
            "detail_above_rows": [self.search_area, self.detail_output, self.rows_container],
        }
        for widget in (self.search_area, self.rows_container, self.detail_output):
            self.main_layout.removeWidget(widget)
        for index, widget in enumerate(layouts[variant], 1):
            self.main_layout.insertWidget(index, widget)
        self._layout_variant = variant

    def reset_case(self, *, case_id: str, records: list[dict], ordered_ids: list[str], layout_variant: str) -> None:
        if not isinstance(case_id, str) or not case_id.strip() or not case_id.isascii() or len(case_id) > 128:
            raise ValueError("case_id must be non-empty ASCII with at most 128 characters")
        if not isinstance(records, list):
            raise ValueError("records must be a list")
        accepted = [self._validate_record(record) for record in records]
        ids = [record["id"] for record in accepted]
        if len(set(ids)) != len(ids):
            raise ValueError("record IDs must be unique")
        if (not isinstance(ordered_ids, list) or any(not isinstance(item, str) for item in ordered_ids)
                or len(ordered_ids) != len(ids) or len(set(ordered_ids)) != len(ordered_ids)
                or set(ordered_ids) != set(ids)):
            raise ValueError("ordered_ids must contain each record exactly once")
        if not isinstance(layout_variant, str) or layout_variant not in {"default", "search_below_rows", "detail_above_rows"}:
            raise ValueError("layout_variant must be default, search_below_rows or detail_above_rows")
        by_id = {record["id"]: record for record in accepted}
        self._records = [by_id[record_id] for record_id in ordered_ids]
        self._visible_ids = list(ordered_ids)
        self._selected_id = None
        self._current_case_id = case_id
        if self.notice_dialog is not None:
            with QSignalBlocker(self.notice_dialog):
                self.notice_dialog.close()
            self.notice_dialog.deleteLater()
            self.notice_dialog = None
        with QSignalBlocker(self.query_field), QSignalBlocker(self.controlled_field):
            self.query_field.clear()
            self.controlled_field.clear()
        self.detail_output.setText("No record selected")
        self.verification_output.setText("Not verified")
        self._arrange_core(layout_variant)
        self._render_rows()
        digest = sha256(json.dumps(self._records, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8")).hexdigest()
        self._reset_event_index = self._emit({"action": "case_reset", "records_sha256": digest,
                                              "order": list(self._visible_ids), "layout_variant": layout_variant})

    def state_snapshot(self) -> dict:
        return {"case_id": self._current_case_id, "event_index": self._event_index,
                "reset_event_index": self._reset_event_index,
                "records": self.records_snapshot(), "visible_ids": list(self._visible_ids),
                "selected_id": self._selected_id, "query": self.query_field.text(),
                "detail_text": self.detail_output.text(), "controlled_value": self.controlled_field.text(),
                "verification_text": self.verification_output.text(), "layout_variant": self._layout_variant,
                "notice_visible": bool(self.notice_dialog and self.notice_dialog.isVisible())}

    def show_notice(self) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("noticeDialog")
        dialog.setWindowTitle("Notice")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Review this notice before continuing."))
        close = QPushButton("Close")
        close.setObjectName("closeNoticeButton")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        self.notice_dialog = dialog
        dialog.finished.connect(lambda _: self._emit({"action": "notice_closed"}))
        dialog.show()
        self._emit({"action": "show_notice"})

    def closeEvent(self, event):
        self._emit({"action": "fixture_closed"})
        super().closeEvent(event)
