"""只读关联前台组合框、UIA 列表项及独立非激活原生浮窗。"""
from .native_identity import normalize_windows_executable_path
from .popup_click_guard import PopupTargetSnapshot


class WindowsPopupReader:
    def __init__(self, *, desktop=None, gui=None, threads=None, process_factory=None):
        if desktop is None:
            from pywinauto import Desktop
            desktop = Desktop(backend='uia')
        if gui is None:
            import win32gui as gui
        if threads is None:
            import win32process as threads
        if process_factory is None:
            import psutil
            process_factory = psutil.Process
        self.desktop, self.gui, self.threads = desktop, gui, threads
        self.process_factory = process_factory

    @staticmethod
    def _rid(node):
        value = node.element_info.runtime_id
        if type(value) not in (list, tuple) or not value or any(type(v) is not int for v in value):
            raise ValueError('popup UIA runtime identity unavailable')
        return tuple(value)

    @staticmethod
    def _available(node, pid):
        return (node.is_visible() is True and node.is_enabled() is True
                and node.element_info.process_id == pid)

    def _native(self, parent, popup, screen_point):
        import win32con
        from app.core.window_manager import WindowManager
        g = self.gui
        if parent == popup or int(g.GetForegroundWindow()) != parent:
            raise PermissionError('popup foreground parent is not exact')
        for h in (parent, popup):
            if (not g.IsWindow(h) or not g.IsWindowVisible(h) or not g.IsWindowEnabled(h)
                    or g.GetAncestor(h, win32con.GA_ROOT) != h):
                raise PermissionError('popup or parent is not a live enabled top-level window')
        style = g.GetWindowLong(popup, win32con.GWL_STYLE)
        if not style & win32con.WS_POPUP or style & win32con.WS_CHILD:
            raise PermissionError('target is not a distinct native popup')
        thread, pid = self.threads.GetWindowThreadProcessId(parent)
        if tuple(self.threads.GetWindowThreadProcessId(popup)) != (thread, pid):
            raise PermissionError('popup and parent thread/process differ')
        hit = g.WindowFromPoint(screen_point)
        if g.GetAncestor(hit, win32con.GA_ROOT) != popup:
            raise PermissionError('popup item point is occluded')
        process = self.process_factory(pid)
        executable = normalize_windows_executable_path(process.exe())
        if executable is None:
            raise ValueError('popup process executable identity unavailable')
        return (pid, thread, process.create_time(), executable,
                WindowManager._capture_surface_rect(parent, gui=g),
                WindowManager._capture_surface_rect(popup, gui=g))

    def read(self, *, parent_handle, combo_name, item_name):
        import win32con
        if type(parent_handle) is not int or parent_handle <= 0:
            raise ValueError('exact popup parent handle required')
        pid = self.threads.GetWindowThreadProcessId(parent_handle)[1]
        root = self.desktop.window(handle=parent_handle).wrapper_object()
        combos = [c for c in root.descendants(control_type='ComboBox')
                  if c.window_text() == combo_name and self._available(c, pid)]
        if len(combos) != 1 or combos[0].get_expand_state() != 1:
            raise PermissionError('exact expanded combo is missing or ambiguous')
        combo = combos[0]
        items = [i for i in combo.descendants(control_type='ListItem')
                 if i.window_text() == item_name and self._available(i, pid)]
        if len(items) != 1:
            raise PermissionError('exact visible popup item is missing or ambiguous')
        item = items[0]
        parent_list = item.parent()
        if parent_list.element_info.control_type != 'List' or self._rid(parent_list.parent()) != self._rid(combo):
            raise PermissionError('item does not belong to the exact combo list')
        r = item.rectangle()
        screen_point = ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        hit = self.gui.WindowFromPoint(screen_point)
        popup = int(self.gui.GetAncestor(hit, win32con.GA_ROOT))
        before = self._native(parent_handle, popup, screen_point)
        if self._rid(self.desktop.from_point(*screen_point)) != self._rid(item):
            raise PermissionError('UIA point and selected popup item disagree')
        if combo.get_expand_state() != 1 or not self._available(item, pid):
            raise PermissionError('popup collapsed or became unavailable during read')
        after = self._native(parent_handle, popup, screen_point)
        if before != after:
            raise PermissionError('popup native identity or geometry changed during read')
        process_id, thread_id, created, executable, parent_rect, popup_rect = after
        left, top, _, _ = popup_rect
        return PopupTargetSnapshot(parent_handle=parent_handle, popup_handle=popup,
            process_id=process_id, process_create_time=created, executable_path=executable,
            thread_id=thread_id, parent_rect=parent_rect, popup_rect=popup_rect,
            combo_name=combo_name, item_name=item_name,
            combo_runtime_id=self._rid(combo), item_runtime_id=self._rid(item),
            item_bbox=(r.left-left, r.top-top, r.right-r.left, r.bottom-r.top),
            click_point=(screen_point[0]-left, screen_point[1]-top))
