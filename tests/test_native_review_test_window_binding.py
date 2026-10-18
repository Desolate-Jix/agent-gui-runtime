"""开发测试必须绑定独立弹窗，而不是它的主窗口 owner。"""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

from scripts.native_review_test_click import ExistingReviewWindow
from app.core.window_manager import window_manager


class TestWindowBinding(TestCase):
    def setUp(self):
        self.command = ['D:/test/AgentReview.exe', '--data-dir', 'D:/AgentReviewAcceptance/test/data']
        self.process = SimpleNamespace(pid=42, create_time=lambda: 1.0,
                                       cmdline=lambda: self.command, exe=lambda: self.command[0])
        self.target = object.__new__(ExistingReviewWindow)
        self.target.owner = {'pid': 42, 'create_time': 1.0, 'command': self.command}
        self.target.action = 'refresh_inventory'
        self.windows = [
            {'handle': 100, 'title': '原生审核工作区', 'process_id': 42},
            {'handle': 200, 'title': '单步验证 · 人工审核后执行', 'process_id': 42},
        ]
        self.owner = 100
        for change in [patch('psutil.Process', return_value=self.process),
                       patch.object(window_manager, 'list_visible_windows', side_effect=lambda: self.windows),
                       patch.object(window_manager, 'bind_window_by_handle', side_effect=lambda h: SimpleNamespace(handle=h, process_id=42)),
                       patch('win32gui.GetWindow', side_effect=lambda h, flag: self.owner)]:
            change.start()
            self.addCleanup(change.stop)

    def test_dialog_action_binds_distinct_owned_modal(self):
        self.assertEqual(self.target.bind()[2].handle, 200)

    def test_entry_action_still_binds_main(self):
        self.target.action = 'open_single_step'
        self.assertEqual(self.target.bind()[2].handle, 100)

    def test_missing_duplicate_foreign_or_unowned_dialog_denies(self):
        original = list(self.windows)
        for windows, owner in [(original[:1], 100), (original + [original[1]], 100),
                               ([original[0], {**original[1], 'process_id': 99}], 100),
                               (original, 0), (original, 900)]:
            self.windows, self.owner = windows, owner
            with self.subTest(windows=windows, owner=owner), self.assertRaises(PermissionError):
                self.target.bind()

    def test_rebound_process_drift_denies(self):
        with patch.object(window_manager, 'bind_window_by_handle', return_value=SimpleNamespace(handle=200, process_id=99)):
            with self.assertRaises(PermissionError):
                self.target.bind()


if __name__ == '__main__':
    main()
