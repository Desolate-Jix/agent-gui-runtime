"""新建键盘回归：只读审核表不能困住焦点或把导航变成编辑。"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetItem
from app.desktop_review.exact_dialog import ExactReviewDialog
from app.desktop_review.window import ReviewMainWindow


class EmptyFacade:
    """不启动存储或 Agent；实际键盘路由仍由生产窗口提供。"""

    def list_batches(self):
        return []

    def close(self):
        pass


class NativeReviewKeyboardNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = ReviewMainWindow(EmptyFacade())
        self.window.show()
        self.application.processEvents()
        for table in (self.window.step_table, self.window.relationship_table):
            table.setRowCount(2)
            for row in range(2):
                for column in range(table.columnCount()):
                    table.setItem(row, column, QTableWidgetItem(f"row-{row}-column-{column}"))

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()

    def test_tab_leaves_each_readonly_table_in_both_directions(self):
        for table in (self.window.step_table, self.window.relationship_table):
            for key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                with self.subTest(table=table.objectName(), key=key):
                    table.setCurrentCell(0, 1)
                    table.setFocus()
                    self.application.processEvents()
                    self.assertIs(self.application.focusWidget(), table)
                    QTest.keyClick(table, key)
                    self.application.processEvents()
                    focus = self.application.focusWidget()
                    self.assertIsNotNone(focus)
                    self.assertFalse(focus is table or table.isAncestorOf(focus),
                                     f"keyboard focus remains trapped in {table.objectName()}")
                    self.assertEqual(table.currentRow(), 0)
                    self.assertFalse(self.window.is_dirty)

    def test_arrow_selection_remains_available_without_editing(self):
        for table in (self.window.step_table, self.window.relationship_table):
            with self.subTest(table=table.objectName()):
                table.setCurrentCell(0, 0)
                table.setFocus()
                self.application.processEvents()
                QTest.keyClick(table, Qt.Key.Key_Down)
                self.application.processEvents()
                self.assertIs(self.application.focusWidget(), table)
                self.assertEqual(table.currentRow(), 1)
                self.assertEqual(table.item(1, 0).text(), "row-1-column-0")
                self.assertFalse(self.window.is_dirty)

    def test_exact_review_keyboard_marks_subjects_and_reaches_save_without_recording(self):
        workspace = {"task_id": "keyboard-task", "batch_id": "keyboard-batch", "revision": 1,
                     "source": "untrusted_external", "source_ref": "keyboard-source",
                     "batch": {"interfaces": [], "steps": [], "relationships": []}}
        dialog = ExactReviewDialog(EmptyFacade(), workspace)
        review = {"task_id": "keyboard-task", "batch_id": "keyboard-batch", "workspace_revision": 1,
                  "source_ref": "keyboard-source", "review_ref": "keyboard-review", "approval_revision": 0,
                  "status": "prepared", "subjects": [
                      {"subject_id": "application", "kind": "application", "label": "Test app", "content": {}, "confirmed": False},
                      {"subject_id": "step:one", "kind": "step", "label": "Test step", "content": {}, "confirmed": False},
                  ]}
        dialog._prepared(review)
        dialog._set_controls()
        dialog.show()
        self.application.processEvents()
        try:
            table = dialog.subject_table
            table.setCurrentCell(0, 1)
            table.setFocus()
            QTest.keyClick(table, Qt.Key.Key_Home)
            self.application.processEvents()
            QTest.keyClick(self.application.focusWidget(), Qt.Key.Key_Space)
            self.application.processEvents()
            self.assertTrue(table.cellWidget(0, 0).isChecked())
            QTest.keyClick(self.application.focusWidget(), Qt.Key.Key_Down)
            self.application.processEvents()
            QTest.keyClick(self.application.focusWidget(), Qt.Key.Key_Space)
            self.application.processEvents()
            self.assertTrue(table.cellWidget(1, 0).isChecked())
            table.setCurrentCell(0, 1)
            table.setFocus()
            visited_names = []
            reached_save = False
            for _ in range(24):
                focus = self.application.focusWidget()
                visited_names.append(focus.objectName() if focus else "none")
                if focus is dialog.record_button:
                    reached_save = True
                    break
                QTest.keyClick(focus, Qt.Key.Key_Tab)
                self.application.processEvents()
            self.assertTrue(reached_save, visited_names)
            self.assertTrue(dialog._decision_dirty)
            self.assertEqual(dialog.review["approval_revision"], 0)
            self.assertFalse(dialog.publish_button.isEnabled())
        finally:
            dialog.hide()
            dialog.deleteLater()
            self.application.processEvents()


if __name__ == "__main__":
    unittest.main()
