"""维护鼠标点击的最后一刻绑定与按钮释放回归，不调用 Windows 输入。"""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.core import input_controller as module
from app.core.window_manager import BoundWindow, WindowRect


class MouseClickLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.bound = BoundWindow(123, 'test', 42, 'AgentReview.exe', WindowRect(10, 20, 810, 620), True)
        self.current = deepcopy(self.bound)
        self.cursor = (150, 62)
        self.manager = SimpleNamespace(get_bound_window=lambda: self.current,
                                      validate_bound_point_visibility=lambda **kw: {'allowed': True})
        self.gui = SimpleNamespace(GetForegroundWindow=lambda: 123)
        self.api = SimpleNamespace(GetCursorPos=lambda: self.cursor)
        self.controller = module.InputController()
        self.controller._ensure_windows_input = lambda: None
        self.controller._require_bound_window = lambda: self.bound
        self.controller._resolve_window_and_screen_point = lambda **kw: {'window_x': 140, 'window_y': 42, 'screen_x': 150, 'screen_y': 62}
        self.controller._focus_window = lambda hwnd: True
        self.controller._send_move = lambda x, y: None
        self.controller.mouse_down = Mock(return_value={'down': True})
        self.controller.mouse_up = Mock(return_value={'up': True})
        for name, value in [('window_manager', self.manager), ('win32gui', self.gui), ('win32api', self.api)]:
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def click(self):
        return self.controller.click_point(140, 42, settle_ms=0, hold_ms=0)

    def test_cursor_movement_rejects_before_down(self):
        self.cursor = (151, 62)
        with self.assertRaisesRegex(RuntimeError, 'cursor.*changed'):
            self.click()
        self.controller.mouse_down.assert_not_called()

    def test_window_rect_process_or_foreground_drift_rejects_before_down(self):
        for kind in ('rect', 'pid', 'foreground'):
            with self.subTest(kind=kind):
                self.current = deepcopy(self.bound)
                self.gui.GetForegroundWindow = lambda: 123
                if kind == 'rect': self.current.rect.left = 11
                if kind == 'pid': self.current.process_id = 43
                if kind == 'foreground': self.gui.GetForegroundWindow = lambda: 999
                with self.assertRaisesRegex(RuntimeError, 'window.*changed'):
                    self.click()
        self.controller.mouse_down.assert_not_called()

    def test_down_uncertainty_still_attempts_release(self):
        self.controller.mouse_down.side_effect = RuntimeError('down outcome unknown')
        with self.assertRaisesRegex(RuntimeError, 'down outcome unknown'):
            self.click()
        self.controller.mouse_up.assert_called_once_with('left')

    def test_hold_interruption_releases_button(self):
        with patch.object(module.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.controller.click_point(140, 42, settle_ms=0, hold_ms=60)
        self.controller.mouse_up.assert_called_once_with('left')

    def test_release_failure_surfaces_unknown_outcome(self):
        self.controller.mouse_up.side_effect = RuntimeError('release failed')
        with self.assertRaisesRegex(RuntimeError, 'release.*unknown'):
            self.click()

    def test_ordinary_click_keeps_existing_result(self):
        self.assertTrue(self.click()['clicked'])
        self.controller.mouse_down.assert_called_once_with('left')
        self.controller.mouse_up.assert_called_once_with('left')


if __name__ == '__main__':
    unittest.main()
