"""有 owner 的顶层弹窗不能被误认作子控件；不发送真实输入。"""
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

import app.core.window_manager as module


class OwnedDialogTests(TestCase):
    def setUp(self):
        self.manager = module.WindowManager()
        self.windows = {
            100: {'title': 'Main', 'root': 100, 'owner': 0, 'visible': True},
            200: {'title': 'Dialog', 'root': 200, 'owner': 100, 'visible': True},
            201: {'title': 'Child', 'root': 200, 'owner': 200, 'visible': True},
            300: {'title': 'Hidden', 'root': 300, 'owner': 100, 'visible': False},
            400: {'title': '', 'root': 400, 'owner': 100, 'visible': True},
        }
        self.gui = SimpleNamespace(
            IsWindow=lambda h: h in self.windows,
            IsWindowVisible=lambda h: self.windows[h]['visible'],
            GetParent=lambda h: self.windows[h]['owner'],
            GetAncestor=lambda h, flag: self.windows[h]['root'] if flag == 2 else self.windows[h]['owner'],
            GetWindowRect=lambda h: (10, 20, 810, 620),
            GetClientRect=lambda h: (0, 0, 800, 600), ClientToScreen=lambda h, p: (10 + p[0], 20 + p[1]),
            GetForegroundWindow=lambda: 200,
        )
        self.wrapper = lambda h: SimpleNamespace(handle=h, window_text=lambda: self.windows[h]['title'])
        for name, value in [('WINDOWS_BACKEND_AVAILABLE', True), ('win32gui', self.gui),
                            ('win32con', SimpleNamespace(GA_ROOT=2)), ('HwndWrapper', self.wrapper),
                            ('Desktop', lambda **_: SimpleNamespace(windows=lambda: [self.wrapper(h) for h in self.windows]))]:
            change = patch.object(module, name, value)
            change.start()
            self.addCleanup(change.stop)
        for name, result in [('_get_process_id', 42), ('_get_process_name', 'review.exe')]:
            change = patch.object(self.manager, name, return_value=result)
            change.start()
            self.addCleanup(change.stop)

    def test_inventory_includes_owned_top_level_but_not_children_hidden_or_untitled(self):
        self.assertEqual([w['handle'] for w in self.manager.list_visible_windows()], [100, 200])

    def test_owned_dialog_can_bind_and_remain_current_with_its_own_foreground(self):
        bound = self.manager.bind_window_by_handle(200)
        self.assertEqual((bound.handle, bound.process_id, bound.is_active), (200, 42, True))
        self.assertEqual(self.manager.get_bound_window().handle, 200)
        self.windows[200]['root'] = 100
        self.assertIsNone(self.manager.get_bound_window())

    def test_child_hidden_untitled_and_missing_handles_cannot_bind(self):
        for handle in (201, 300, 400, 999):
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                self.manager.bind_window_by_handle(handle)

    def test_ancestry_failure_denies_instead_of_assuming_top_level(self):
        self.gui.GetAncestor = lambda *args: 0
        self.assertFalse(self.manager._is_candidate_window(self.wrapper(200)))
        self.assertFalse(self.manager._is_bound_handle_valid(200))


if __name__ == '__main__':
    main()
