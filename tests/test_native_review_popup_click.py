"""浮窗测试调用须同时冻结语义、原生关系及独立窗口坐标。"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

from scripts import native_review_test_click as driver
from app.agent.popup_click_guard import PopupClickGuard
from tests.test_popup_click_guard import target


class PopupDriverTests(TestCase):
    def setUp(self):
        from dataclasses import replace
        self.popup = replace(target(), combo_name='已发布流程', item_name='New workflow')
        p = self.popup
        self.observed = {'window': {'handle': 200, 'process_id': 42, 'create_time': 1.0,
            'exe': 'c:/test/app.exe', 'rect': list(p.popup_rect)}, 'viewport_size': [200, 40],
            'image_path': 'popup.png', 'image_sha256': 'a'*64, 'popup_target': asdict(p),
            'candidate': {'name': 'New workflow', 'control_type': 'ListItem', 'enabled': True,
                'visible': True, 'automation_id': 'QApplication.singleStepDialog.QSplitter.QGroupBox.QComboBox.QComboBoxListView',
                'bbox': list(p.item_bbox), 'click_point': list(p.click_point), 'source': 'windows_uia', 'confidence': 1.0}}

    def test_popup_choice_has_one_shot_guard_bound_to_exact_observation(self):
        with TemporaryDirectory() as folder:
            calls = []
            guard = PopupClickGuard(self.popup, lambda: self.popup)
            controller = driver.TestClickController(action='choose_asset', expected_name='New workflow',
                observe=lambda: deepcopy(self.observed), dispatch=lambda c,a: calls.append((c,a)) or {'status':'dispatched'},
                post_capture=lambda: {'image_path':'after.png'}, output_dir=Path(folder), enabled=True)
            p = controller.preview()
            with patch.object(driver, 'make_popup_guard', return_value=guard):
                result = controller.execute(p, driver.content_sha256(p))
            self.assertEqual(result['status'], 'dispatched_unverified')
            self.assertIs(calls[0][0].popup_guard, guard)
            self.assertIs(calls[0][1].popup_guard, guard)
            self.assertEqual(calls[0][0].target_window_handle, 200)
            with self.assertRaises(PermissionError):
                controller.execute(p, driver.content_sha256(p))

    def test_missing_or_mismatched_popup_relationship_is_not_a_choice_candidate(self):
        for mutate in [lambda o:o.pop('popup_target'),
                       lambda o:o['popup_target'].update(combo_name='目标窗口（HWND / PID）'),
                       lambda o:o['window'].update(handle=100),
                       lambda o:o['candidate'].update(bbox=[2, 3, 196, 20]),
                       lambda o:o['popup_target'].update(item_name='other')]:
            o = deepcopy(self.observed)
            mutate(o)
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, KeyError)):
                driver._candidate(o, 'choose_asset', 'New workflow')

    def test_popup_relationship_changes_participate_in_freshness_check(self):
        before = deepcopy(self.observed)
        self.observed['popup_target']['combo_runtime_id'] = [1, 999]
        self.assertNotEqual(driver._stable(before), driver._stable(self.observed))

    def test_saved_json_preview_preserves_typed_popup_freshness(self):
        import json
        saved = json.loads(json.dumps(self.observed))
        self.assertEqual(driver._stable(saved), driver._stable(self.observed))


if __name__ == '__main__':
    main()
