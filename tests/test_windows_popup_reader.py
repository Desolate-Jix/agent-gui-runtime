"""用完整的局部 UIA/Win32 替身验证浮窗归属，不发送输入。"""
from types import SimpleNamespace as NS
import unittest

from app.agent.windows_popup_reader import WindowsPopupReader


class Node:
    def __init__(self, name, role, rid, children=(), parent=None):
        self.element_info = NS(name=name, control_type=role, runtime_id=rid, process_id=42)
        self.children = list(children)
        self.owner = parent
        self.visible = self.enabled = True
        self.expanded = 1
        for child in children:
            child.owner = self
    def window_text(self): return self.element_info.name
    def is_visible(self): return self.visible
    def is_enabled(self): return self.enabled
    def parent(self): return self.owner
    def get_expand_state(self): return self.expanded
    def rectangle(self): return NS(left=22, top=102, right=218, bottom=122)
    def descendants(self, control_type):
        result = []
        for c in self.children:
            if c.element_info.control_type == control_type:
                result.append(c)
            result.extend(c.descendants(control_type))
        return result


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.item = Node('New workflow', 'ListItem', [1, 3])
        self.list = Node('', 'List', [1, 4], [self.item])
        self.combo = Node('Workflow', 'ComboBox', [1, 2], [self.list])
        self.root = Node('Dialog', 'Window', [1, 1], [self.combo])
        self.foreground = 100
        self.hit = 200
        self.pid = 42
        self.popup_thread = 7
        self.popup_style = 0x80000000
        self.desktop = NS(window=lambda handle: NS(wrapper_object=lambda: self.root), from_point=lambda x, y: self.item)
        self.gui = NS(IsWindow=lambda h: h in (100, 200), IsWindowVisible=lambda h: True,
            IsWindowEnabled=lambda h: True, GetForegroundWindow=lambda: self.foreground,
            GetAncestor=lambda h, flag: h, GetWindowLong=lambda h, flag: self.popup_style,
            GetWindowRect=lambda h: (0, 0, 800, 600) if h == 100 else (20, 100, 220, 140),
            GetClientRect=lambda h: (0, 0, 800, 600) if h == 100 else (0, 0, 200, 40),
            ClientToScreen=lambda h, p: p if h == 100 else (20 + p[0], 100 + p[1]),
            WindowFromPoint=lambda point: self.hit)
        self.threads = NS(GetWindowThreadProcessId=lambda h: [7, 42] if h == 100 else [self.popup_thread, self.pid])
        self.reader = WindowsPopupReader(desktop=self.desktop, gui=self.gui, threads=self.threads,
            process_factory=lambda pid: NS(create_time=lambda: 1.0, exe=lambda: 'c:/test/app.exe'))

    def read(self): return self.reader.read(parent_handle=100, combo_name='Workflow', item_name='New workflow')

    def test_exact_expanded_combo_item_binds_distinct_popup(self):
        result = self.read()
        self.assertEqual((result.parent_handle, result.popup_handle, result.click_point), (100, 200, (100, 12)))
        self.assertEqual(result.combo_runtime_id, (1, 2))

    def test_same_pid_alone_never_proves_popup_relationship(self):
        for mutate in [lambda: setattr(self, 'popup_thread', 8), lambda: setattr(self, 'popup_style', 0),
                       lambda: setattr(self, 'hit', 100), lambda: setattr(self, 'pid', 99),
                       lambda: setattr(self, 'foreground', 200), lambda: setattr(self.combo, 'expanded', 0),
                       lambda: setattr(self.item, 'owner', self.root)]:
            self.setUp()
            mutate()
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, PermissionError)):
                self.read()

    def test_ambiguous_hidden_or_foreign_uia_item_rejects(self):
        for mutate in [lambda: self.list.children.append(self.item), lambda: setattr(self.item, 'visible', False),
                       lambda: setattr(self.combo, 'enabled', False), lambda: setattr(self.item.element_info, 'process_id', 99),
                       lambda: setattr(self.desktop, 'from_point', lambda x, y: self.combo)]:
            self.setUp()
            mutate()
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, PermissionError)):
                self.read()

    def test_native_recheck_catches_window_drift_during_uia_read(self):
        def changed(x, y):
            self.foreground = 900
            return self.item
        self.desktop.from_point = changed
        with self.assertRaises((ValueError, PermissionError)):
            self.read()


if __name__ == '__main__':
    unittest.main()
