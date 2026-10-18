"""独立浮窗点击绑定的纯离线回归。"""
from dataclasses import FrozenInstanceError, replace
import unittest

from app.agent.popup_click_guard import PopupClickGuard, PopupTargetSnapshot


def target():
    return PopupTargetSnapshot(parent_handle=100, popup_handle=200, process_id=42,
        process_create_time=1.0, executable_path='c:/test/app.exe', thread_id=7,
        parent_rect=(0, 0, 800, 600), popup_rect=(20, 100, 220, 140),
        combo_name='Workflow', item_name='New workflow',
        combo_runtime_id=(1, 2), item_runtime_id=(1, 3),
        item_bbox=(2, 2, 196, 20), click_point=(100, 12))


class PopupGuardTests(unittest.TestCase):
    def test_current_exact_target_and_command_are_required(self):
        before = target()
        guard = PopupClickGuard(before, lambda: before)
        guard.validate_command(window_handle=200, click_point=(100, 12))
        guard.verify_current()
        for handle, point in [(100, (100, 12)), (200, (101, 12))]:
            with self.subTest(handle=handle, point=point), self.assertRaises(ValueError):
                guard.validate_command(window_handle=handle, click_point=point)

    def test_drift_in_each_binding_field_rejects(self):
        before = target()
        for field, value in [('parent_handle', 101), ('popup_handle', 201), ('process_id', 43),
                             ('process_create_time', 2.0), ('executable_path', 'c:/test/other.exe'),
                             ('thread_id', 8), ('parent_rect', (1, 0, 801, 600)),
                             ('popup_rect', (21, 100, 221, 140)), ('combo_name', 'Window'),
                             ('item_name', 'Other item'), ('combo_runtime_id', (1, 4)),
                             ('item_runtime_id', (1, 5)), ('item_bbox', (1, 2, 198, 20))]:
            current = replace(before, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                PopupClickGuard(before, lambda: current).verify_current()

    def test_unreadable_or_untyped_current_snapshot_denies(self):
        def broken():
            raise OSError('popup closed')
        for reader in [broken, lambda: {}, lambda: None]:
            with self.subTest(reader=reader), self.assertRaises(ValueError):
                PopupClickGuard(target(), reader).verify_current()

    def test_invalid_geometry_and_identity_cannot_create_guard(self):
        for field, value in [('popup_handle', 100), ('process_id', True), ('process_create_time', float('nan')),
                             ('popup_rect', (20, 100, 20, 140)), ('item_bbox', (2, 2, 300, 20)),
                             ('click_point', (100, 50)), ('combo_runtime_id', ()),
                             ('item_name', ''), ('parent_rect', (0, 0, 0, 0))]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(target(), **{field: value})

    def test_target_and_guard_bindings_are_immutable(self):
        before = target()
        guard = PopupClickGuard(before, lambda: before)
        with self.assertRaises(FrozenInstanceError):
            before.popup_handle = 300
        with self.assertRaises(FrozenInstanceError):
            guard.expectation = before


if __name__ == '__main__':
    unittest.main()
