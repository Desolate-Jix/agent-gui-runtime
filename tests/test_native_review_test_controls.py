"""审核窗口测试控件的独立回归，不发送真实鼠标或模型请求。"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import native_review_test_click as driver


class ReviewTestControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []

    def control(self, name='刷新流程与窗口', kind='Button'):
        return {'name': name, 'control_type': kind,
                'automation_id': 'QApplication.singleStepDialog.QSplitter.QGroupBox.' + ('QPushButton' if kind == 'Button' else 'QComboBox'),
                'bbox': {'x': 20, 'y': 40, 'w': 120, 'h': 24},
                'enabled': True, 'visible': True, 'patterns': ['Invoke', 'ExpandCollapse', 'Selection']}

    def snapshot(self, control):
        return {'window': {'handle': 123, 'process_id': 42, 'create_time': 1.0,
                           'exe': 'D:/test/AgentReview.exe', 'rect': [0, 0, 800, 600]},
                'viewport_size': [800, 600], 'image_sha256': 'a' * 64,
                'image_path': str(self.root / 'screen.png'),
                'candidate': {**control, 'bbox': [20, 40, 120, 24], 'click_point': [80, 52],
                              'source': 'windows_uia', 'confidence': 1.0}}

    def controller(self, snapshot, **kwargs):
        return driver.TestClickController(observe=lambda: deepcopy(snapshot),
            dispatch=lambda command, authority: self.calls.append((command, authority)) or {'status': 'dispatched'},
            post_capture=lambda: {'image_path': 'after.png', 'single_step_visible': True},
            output_dir=self.root, clock=lambda: 100.0, **kwargs)

    def test_explicit_safe_button_uses_same_gate_without_claiming_formal_success(self):
        controller = self.controller(self.snapshot(self.control()), action='refresh_inventory', enabled=True)
        preview = controller.preview()
        self.assertEqual(preview['action'], 'refresh_inventory')
        self.assertEqual(self.calls, [])
        result = controller.execute(preview, driver.content_sha256(preview))
        self.assertEqual(result['status'], 'dispatched_unverified')
        self.assertFalse(result['production_workflow_approval'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0].click_point, (80, 52))
        with self.assertRaisesRegex(PermissionError, 'already claimed'):
            controller.execute(preview, driver.content_sha256(preview))

    def test_only_declared_non_approval_actions_exist(self):
        expected = {'open_single_step', 'refresh_inventory', 'open_asset_list',
                    'open_window_list', 'prepare_target', 'open_action_list',
                    'request_preview', 'check_environment', 'choose_asset', 'choose_window', 'choose_action'}
        self.assertEqual(set(driver.TEST_ACTIONS), expected)
        for action in ('approve', 'execute', 'publish', 'fill_field', 'close', 'arbitrary_click'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.controller(self.snapshot(self.control()), action=action)

    def test_default_denial_still_applies_to_new_controls(self):
        controller = self.controller(self.snapshot(self.control()), action='refresh_inventory')
        preview = controller.preview()
        with self.assertRaisesRegex(PermissionError, 'explicit test opt-in'):
            controller.execute(preview, driver.content_sha256(preview))
        self.assertEqual(self.calls, [])

    def test_exact_control_role_label_scope_visibility_and_uniqueness(self):
        good = self.control()
        self.assertEqual(driver.select_test_control([good], 'refresh_inventory'), good)
        for changes in ({'name': '批准本次预检'}, {'control_type': 'Text'},
                        {'automation_id': 'QApplication.otherDialog.QPushButton'},
                        {'visible': False}, {'enabled': False}):
            with self.subTest(changes=changes), self.assertRaises(PermissionError):
                driver.select_test_control([{**good, **changes}], 'refresh_inventory')
        with self.assertRaises(PermissionError):
            driver.select_test_control([good, deepcopy(good)], 'refresh_inventory')

    def test_native_popup_list_choices_remain_denied_without_binding_contract(self):
        c = self.control('fresh workflow', 'ListItem')
        c['automation_id'] = 'QApplication.singleStepDialog.QSplitter.QGroupBox.QComboBox.QComboBoxListView'
        for name in (None, '', 'different workflow', 'fresh workflow'):
            with self.subTest(name=name), self.assertRaises((ValueError, PermissionError)):
                driver._candidate(self.snapshot(c), 'choose_asset', name)
        with self.assertRaises(ValueError):
            self.controller(self.snapshot(self.control()), action='refresh_inventory', expected_name='fresh workflow')

    def test_action_and_choice_cannot_be_swapped_after_review(self):
        controller = self.controller(self.snapshot(self.control()), action='refresh_inventory', enabled=True)
        for field, value in [('action', 'prepare_target'), ('expected_name', 'injected')]:
            preview = controller.preview()
            preview[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                controller.execute(preview, driver.content_sha256(preview))
        self.assertEqual(self.calls, [])

    def test_pending_ui_result_has_202_not_verified_200(self):
        from fastapi.testclient import TestClient
        controller = self.controller(self.snapshot(self.control()), action='refresh_inventory', enabled=True)
        preview = controller.preview()
        digest = driver.content_sha256(preview)
        with TestClient(driver.create_test_app(controller, preview, digest)) as client:
            response = client.post('/action/execute_recognition_plan', json={'reviewed_sha256': digest})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['status'], 'dispatched_unverified')


if __name__ == '__main__':
    unittest.main()
