"""新建原生回归：长审核说明不能挤垮导航与属性面板。"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from app.desktop_review.window import ReviewMainWindow


class EmptyFacade:
    """只隔离外部存储；实际布局仍由生产窗口构造。"""

    def list_batches(self):
        return []

    def close(self):
        pass


class NativeReviewHeadingLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def settle(self):
        for _ in range(5):
            self.application.processEvents()

    def test_long_meaning_preserves_usable_panes_and_visible_heading(self):
        meanings = {
            "chinese": "界面含义用于审核识别框与流程，不应挤压其他面板。" * 60,
            "english": "Review the interface meaning and linked workflow steps. " * 40,
            "unbroken": "UNBROKEN_INTERFACE_MEANING_" * 80,
        }
        for width, height in ((1456, 939), (1100, 760)):
            window = ReviewMainWindow(EmptyFacade())
            window.resize(width, height)
            window.show()
            self.settle()
            splitter = window.centralWidget()
            baseline = splitter.sizes()
            try:
                for name, meaning in meanings.items():
                    with self.subTest(size=(width, height), language=name):
                        title = "截图审核画布 · " + meaning
                        window.canvas_title.setText(title)
                        self.settle()
                        sizes = splitter.sizes()
                        self.assertGreaterEqual(sizes[0], 180, sizes)
                        self.assertGreaterEqual(sizes[2], 280, sizes)
                        for actual, original in zip(sizes, baseline):
                            self.assertLessEqual(abs(actual - original), 3, sizes)
                        self.assertGreaterEqual(window.canvas_title.width(), 80)
                        self.assertEqual(window.canvas_title.text(), title)
                        self.assertTrue(window.canvas.isVisible())
                        self.assertTrue(window.batch_tree.isVisible())
                        self.assertFalse(window.is_dirty)
            finally:
                window.close()
                window.deleteLater()
                self.settle()


if __name__ == "__main__":
    unittest.main()
