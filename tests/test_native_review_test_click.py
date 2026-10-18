"""新版开发测试入口的独立回归；不派发真实输入。"""
from copy import deepcopy
import importlib
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class NativeTestClickTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.native_review_test_click'),
                             'Missing developer-only reviewed click entry')
        self.module = importlib.import_module('scripts.native_review_test_click')
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = {
            'window': {'handle': 123, 'process_id': 42, 'create_time': 1.0,
                       'exe': 'D:/test/AgentReview.exe', 'rect': [0, 0, 800, 600]},
            'viewport_size': [800, 600], 'image_sha256': 'a' * 64,
            'image_path': str(self.root / 'screen.png'),
            'candidate': {'name': '单步验证', 'automation_id': 'QApplication.ReviewMainWindow.QToolBar.QToolButton',
                          'bbox': [100, 30, 80, 24], 'click_point': [140, 42],
                          'source': 'windows_uia', 'confidence': 1.0},
        }
        self.calls = []

    def controller(self, **kwargs):
        return self.module.TestClickController(
            observe=lambda: deepcopy(self.snapshot),
            dispatch=lambda command, authority: self.calls.append((command, authority)) or {'status': 'dispatched'},
            post_capture=lambda: {'image_path': 'after.png', 'single_step_visible': True},
            output_dir=self.root, clock=lambda: 100.0, **kwargs)

    def test_preview_never_dispatches_and_default_denies(self):
        controller = self.controller()
        preview = controller.preview()
        self.assertEqual(self.calls, [])
        with self.assertRaisesRegex(PermissionError, 'explicit test opt-in'):
            controller.execute(preview, self.module.content_sha256(preview))
        self.assertEqual(self.calls, [])

    def test_explicit_preview_one_shot_and_authority_matches(self):
        controller = self.controller(enabled=True)
        preview = controller.preview()
        result = controller.execute(preview, self.module.content_sha256(preview))
        self.assertTrue(result['post_verification']['single_step_visible'])
        self.assertEqual(len(self.calls), 1)
        command, authority = self.calls[0]
        self.assertEqual(command.click_point, (140, 42))
        self.assertEqual(authority.target_window_handle, 123)
        self.assertIn('dev-test', authority.gate_decision_ref)
        with self.assertRaisesRegex(PermissionError, 'already claimed'):
            controller.execute(preview, self.module.content_sha256(preview))
        self.assertEqual(len(self.calls), 1)

    def test_changed_image_window_geometry_and_candidate_deny_before_dispatch(self):
        for kind in ('image', 'pid', 'birth', 'rect', 'candidate'):
            with self.subTest(kind=kind):
                controller = self.controller(enabled=True)
                preview = controller.preview()
                original = deepcopy(self.snapshot)
                if kind == 'image': self.snapshot['image_sha256'] = 'b' * 64
                elif kind == 'pid': self.snapshot['window']['process_id'] = 43
                elif kind == 'birth': self.snapshot['window']['create_time'] = 2.0
                elif kind == 'rect': self.snapshot['window']['rect'][0] = 5
                else: self.snapshot['candidate']['bbox'][0] = 101
                with self.assertRaisesRegex(PermissionError, 'drift'):
                    controller.execute(preview, self.module.content_sha256(preview))
                self.snapshot = original
        self.assertEqual(self.calls, [])

    def test_expired_bad_digest_other_action_and_outside_point_deny(self):
        controller = self.controller(enabled=True)
        original = controller.preview()
        for kind in ('expired', 'future', 'digest', 'action', 'point'):
            with self.subTest(kind=kind):
                preview = deepcopy(original)
                if kind == 'expired': preview['created_at'] = -1000.0
                if kind == 'future': preview['created_at'] = 200.0
                if kind == 'action': preview['action'] = 'publish_workflow'
                if kind == 'point': preview['observation']['candidate']['click_point'] = [799, 599]
                digest = 'x' * 64 if kind == 'digest' else self.module.content_sha256(preview)
                with self.assertRaises((PermissionError, ValueError)):
                    controller.execute(preview, digest)
        self.assertEqual(self.calls, [])

    def test_post_capture_failure_is_unknown_and_never_retried(self):
        controller = self.controller(enabled=True)
        preview = controller.preview()
        controller.post_capture = lambda: (_ for _ in ()).throw(RuntimeError('capture unavailable'))
        result = controller.execute(preview, self.module.content_sha256(preview))
        self.assertEqual(result['status'], 'result_unknown')
        with self.assertRaisesRegex(PermissionError, 'already claimed'):
            controller.execute(preview, self.module.content_sha256(preview))
        self.assertEqual(len(self.calls), 1)

    def test_http_route_is_required_and_rejects_wrong_payload(self):
        from fastapi.testclient import TestClient
        controller = self.controller(enabled=True)
        preview = controller.preview()
        app = self.module.create_test_app(controller, preview, self.module.content_sha256(preview))
        with TestClient(app) as client:
            self.assertEqual(client.get('/action/execute_recognition_plan').status_code, 405)
            self.assertEqual(client.post('/action/execute_recognition_plan', json={'x': 1}).status_code, 400)
            response = client.post('/action/execute_recognition_plan', json={'reviewed_sha256': self.module.content_sha256(preview)})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.calls), 1)

    def test_normal_input_guard_stays_disabled(self):
        from app.core.input_controller import InputController
        from app.core.runtime_input_authority import runtime_backend_input_is_active
        self.assertFalse(runtime_backend_input_is_active())
        with self.assertRaises(PermissionError):
            InputController()._ensure_windows_input()

    def test_existing_backend_consumes_test_authority_and_restores_scope(self):
        from dataclasses import asdict
        from types import SimpleNamespace
        from app.agent.desktop_backend import ExistingWindowsBackendAdapter
        from app.core.runtime_input_authority import runtime_backend_input_is_active
        observed = []
        class RecordingInput:
            def click_point(self, x, y):
                observed.append((x, y, runtime_backend_input_is_active()))
                return {'clicked': True}
        backend = ExistingWindowsBackendAdapter(input_controller=RecordingInput(),
            window_manager=SimpleNamespace(get_bound_window=lambda: SimpleNamespace(handle=123)))
        controller = self.controller(enabled=True)
        controller.dispatch = lambda command, authority: asdict(backend.dispatch(command, authority=authority))
        preview = controller.preview()
        result = controller.execute(preview, self.module.content_sha256(preview))
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(observed, [(140, 42, True)])
        self.assertFalse(runtime_backend_input_is_active())

    def test_duplicate_or_equals_data_dir_is_rejected(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        target = self.module.ExistingReviewWindow.__new__(self.module.ExistingReviewWindow)
        for tail in (['--data-dir', 'D:/AgentReviewAcceptance/safe', '--data-dir', 'D:/real'],
                     ['--data-dir', 'D:/AgentReviewAcceptance/safe', '--data-dir=D:/real']):
            command = ['D:/test/AgentReview.exe', *tail]
            target.owner = {'pid': 42, 'create_time': 1.0, 'command': command}
            process = SimpleNamespace(create_time=lambda: 1.0, cmdline=lambda: command, exe=lambda: command[0])
            with patch('psutil.Process', return_value=process):
                with self.assertRaisesRegex(PermissionError, 'isolated'):
                    target.bind()

    def test_hidden_post_dialog_is_not_success(self):
        from unittest.mock import patch
        target = self.module.ExistingReviewWindow.__new__(self.module.ExistingReviewWindow)
        target.bind = lambda: None
        target.output_dir = self.root
        control = {'name': '单步验证 · 人工审核后执行', 'control_type': 'Window', 'visible': False}
        with patch('app.core.screenshot.screenshot_service.capture_window', return_value={'image_path': 'after.png'}), \
             patch('app.operation.screen_reading.uia_provider.uia_provider.snapshot_bound_window', return_value={'controls': [control]}):
            self.assertFalse(target.after()['single_step_visible'])
            control['visible'] = True
            self.assertTrue(target.after()['single_step_visible'])

    def test_shadow_background_is_excluded_but_client_pixel_drift_rejected(self):
        from PIL import Image
        fingerprint = getattr(self.module, 'visual_fingerprint', None)
        self.assertIsNotNone(fingerprint, 'Need a client-area-bound visual fingerprint')
        path = self.root / 'client.png'
        picture = Image.new('RGB', (20, 20), 'white')
        picture.save(path)
        before = fingerprint(path, [2, 2, 16, 16])
        picture.putpixel((0, 0), (0, 0, 0))
        picture.save(path)
        border = fingerprint(path, [2, 2, 16, 16])
        self.assertNotEqual(before['image_sha256'], border['image_sha256'])
        self.assertEqual(before['client_sha256'], border['client_sha256'])
        picture.putpixel((3, 3), (0, 0, 0))
        picture.save(path)
        self.assertNotEqual(before['client_sha256'], fingerprint(path, [2, 2, 16, 16])['client_sha256'])


if __name__ == '__main__':
    unittest.main()
