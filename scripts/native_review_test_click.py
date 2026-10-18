"""隔离审核窗口的开发测试点击；不提供任意坐标、生产审批或执行旁路。"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ACTION = 'open_single_step'
LABEL = '单步验证'
TEST_ROOT = Path('D:/AgentReviewAcceptance')
TTL_SECONDS = 180
POPUP_ACTIONS = {'choose_asset': '已发布流程', 'choose_window': '目标窗口（HWND / PID）',
                 'choose_action': '服务器提供的动作'}
TEST_ACTIONS = {
    'open_single_step': ('Button', LABEL),
    'refresh_inventory': ('Button', '刷新流程与窗口'),
    'check_environment': ('Button', '检查运行环境'),
    'open_asset_list': ('ComboBox', '已发布流程'),
    'open_window_list': ('ComboBox', '目标窗口（HWND / PID）'),
    'prepare_target': ('Button', '预检选定目标'),
    'open_action_list': ('ComboBox', '服务器提供的动作'),
    'request_preview': ('Button', '生成定位预览'),
    **{action: ('ListItem', None) for action in POPUP_ACTIONS},
}


def _target_spec(action, expected_name=None):
    if action not in TEST_ACTIONS:
        raise ValueError('unsupported developer test action')
    kind, label = TEST_ACTIONS[action]
    if action in POPUP_ACTIONS:
        if (not isinstance(expected_name, str) or not expected_name.strip() or len(expected_name) > 512
                or any(ord(c) < 32 for c in expected_name)):
            raise ValueError('popup choice requires the exact observed item name')
        label = expected_name
    elif expected_name is not None:
        raise ValueError('custom target names and popup list choices are not supported')
    return kind, label


def _control_matches(control, action, expected_name=None):
    kind, label = _target_spec(action, expected_name)
    identifier = control.get('automation_id') or ''
    prefix = 'QApplication.ReviewMainWindow.QToolBar.' if action == ACTION else 'QApplication.singleStepDialog.'
    return (control.get('name') == label and control.get('control_type') == kind
            and identifier.startswith(prefix)
            and (kind != 'ListItem' or identifier.endswith('.QComboBox.QComboBoxListView'))
            and control.get('enabled') is True and control.get('visible') is True)


def select_test_control(controls, action=ACTION, expected_name=None):
    _target_spec(action, expected_name)
    matches = [c for c in controls if _control_matches(c, action, expected_name)]
    if len(matches) != 1:
        raise PermissionError('declared test control is missing or ambiguous')
    return matches[0]


def content_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def _candidate(snapshot, action=ACTION, expected_name=None):
    _target_spec(action, expected_name)
    candidate = snapshot['candidate']
    x, y, w, h = candidate['bbox']
    px, py = candidate['click_point']
    width, height = snapshot['viewport_size']
    values = (x, y, w, h, px, py, width, height)
    if (any(type(v) is not int for v in values) or w <= 0 or h <= 0
            or not (0 <= x <= px < x + w <= width and 0 <= y <= py < y + h <= height)
            or candidate['source'] != 'windows_uia'
            or [px, py] != [x + w // 2, y + h // 2]):
        raise ValueError('only the uniquely observed declared control center is permitted')
    # 保持原入口预览兼容；新动作必须携带角色与可见、启用证据。
    control = candidate if action != ACTION else {**candidate, 'control_type': 'Button', 'enabled': True, 'visible': True}
    if not _control_matches(control, action, expected_name):
        raise ValueError('candidate does not match the declared test control')
    if action in POPUP_ACTIONS:
        if not isinstance(snapshot.get('popup_target'), dict):
            raise ValueError('popup candidate requires native/UIA relationship evidence')
        popup = popup_snapshot(snapshot['popup_target'])
        from app.agent.native_identity import normalize_windows_executable_path
        window = snapshot['window']
        if (popup.combo_name != POPUP_ACTIONS[action] or popup.item_name != expected_name
                or window['handle'] != popup.popup_handle or window['process_id'] != popup.process_id
                or window['create_time'] != popup.process_create_time
                or normalize_windows_executable_path(window['exe']) != normalize_windows_executable_path(popup.executable_path)
                or tuple(window['rect']) != popup.popup_rect or tuple(candidate['bbox']) != popup.item_bbox
                or tuple(candidate['click_point']) != popup.click_point):
            raise ValueError('popup candidate does not match its native/UIA relationship')
    return candidate


def popup_snapshot(value):
    from app.agent.popup_click_guard import PopupTargetSnapshot
    value = dict(value)
    for key in ('parent_rect', 'popup_rect', 'combo_runtime_id', 'item_runtime_id', 'item_bbox', 'click_point'):
        value[key] = tuple(value[key])
    return PopupTargetSnapshot(**value)


def make_popup_guard(snapshot):
    from app.agent.popup_click_guard import PopupClickGuard
    from app.agent.windows_popup_reader import WindowsPopupReader
    before = popup_snapshot(snapshot['popup_target'])
    return PopupClickGuard(before, lambda: WindowsPopupReader().read(parent_handle=before.parent_handle,
                           combo_name=before.combo_name, item_name=before.item_name))


def _stable(snapshot):
    fields = ('client_rect', 'client_sha256') if 'client_sha256' in snapshot else ('image_sha256',)
    result = {key: snapshot[key] for key in ('window', 'viewport_size', 'candidate', *fields)}
    if 'popup_target' in snapshot:
        result['popup_target'] = asdict(popup_snapshot(snapshot['popup_target']))
    return result


def visual_fingerprint(image_path, client_rect):
    from PIL import Image
    x, y, w, h = client_rect
    with Image.open(image_path) as image:
        if (any(type(v) is not int for v in client_rect) or w <= 0 or h <= 0
                or not (0 <= x < x + w <= image.width and 0 <= y < y + h <= image.height)):
            raise ValueError('invalid captured client rectangle')
        # 窗口阴影外沿会透出其他程序；只把真实客户区像素作为内容一致性证据。
        pixels = image.convert('RGB').crop((x, y, x + w, y + h)).tobytes()
    return {'image_sha256': hashlib.sha256(Path(image_path).read_bytes()).hexdigest(),
            'client_sha256': hashlib.sha256(pixels).hexdigest(), 'client_rect': client_rect}


class TestClickController:
    """显式测试许可独立于流程授权；每个声明动作仍使用共用后端的一次性权限。"""

    def __init__(self, *, observe, dispatch, post_capture, output_dir,
                 enabled=False, clock=time.time, action=ACTION, expected_name=None):
        if type(enabled) is not bool:
            raise ValueError('enabled must be boolean')
        self.observe = observe
        self.dispatch = dispatch
        self.post_capture = post_capture
        self.output_dir = Path(output_dir)
        self.enabled = enabled
        self.clock = clock
        _target_spec(action, expected_name)
        self.action = action
        self.expected_name = expected_name

    def preview(self):
        observation = self.observe()
        _candidate(observation, self.action, self.expected_name)
        return {'contract_version': 'native_review_dev_click_preview_v1',
                'action': self.action, 'expected_name': self.expected_name,
                'capture_id': 'dev-capture-' + uuid4().hex,
                'created_at': self.clock(), 'observation': observation,
                'production_workflow_approval': False}

    def execute(self, preview, reviewed_sha256):
        if not self.enabled:
            raise PermissionError('explicit test opt-in is required')
        preview = deepcopy(preview)
        if content_sha256(preview) != reviewed_sha256:
            raise PermissionError('reviewed preview digest mismatch')
        if (preview.get('contract_version') != 'native_review_dev_click_preview_v1'
                or preview.get('action') != self.action
                or preview.get('expected_name') != self.expected_name
                or preview.get('production_workflow_approval') is not False):
            raise ValueError('unsupported developer test action')
        created = preview['created_at']
        if (type(created) not in (int, float) or not math.isfinite(created)
                or not 0 <= self.clock() - created <= TTL_SECONDS):
            raise PermissionError('test preview expired or future dated')
        candidate = _candidate(preview['observation'], self.action, self.expected_name)
        claim = self.output_dir / ('claim-' + reviewed_sha256 + '.json')
        try:
            write_json(claim, {'state': 'claimed_before_dispatch', 'created_at': self.clock()})
        except FileExistsError:
            raise PermissionError('preview already claimed; never automatically retry') from None
        current = self.observe()
        if _stable(current) != _stable(preview['observation']):
            raise PermissionError('current screenshot, target or candidate drift')
        _candidate(current, self.action, self.expected_name)
        from app.agent.desktop_backend import DesktopDispatchCommand, _mint_execution_authority
        identity = preview['capture_id']
        point = tuple(candidate['click_point'])
        handle = current['window']['handle']
        popup_guard = make_popup_guard(current) if self.action in POPUP_ACTIONS else None
        gate = {'contract_version': 'pre_click_decision_v1', 'allowed': True,
                'source': 'explicit_developer_test_only', 'production_workflow_approval': False,
                'action': self.action, 'capture_id': identity, 'confidence': candidate['confidence'],
                'bbox': candidate['bbox'], 'click_point': list(point),
                'reasons': ['explicit_test_opt_in', 'exact_isolated_process', 'unique_declared_control',
                            'fresh_screenshot_unchanged', 'center_inside_bbox', 'one_shot_claim']}
        write_json(self.output_dir / ('gate-' + reviewed_sha256 + '.json'), gate)
        command = DesktopDispatchCommand(semantic_action='open_detail', capture_id=identity,
                                         candidate_id=content_sha256(candidate), click_point=point,
                                         target_window_handle=handle, popup_guard=popup_guard)
        # 测试权限仅操作审核界面控件；不能批准、消费或伪造生产工作流权限。
        authority = _mint_execution_authority(
            session_id='dev-test-' + identity, observation_id=identity, intent_id=reviewed_sha256,
            workflow_revision_hash='dev-test-no-workflow', semantic_action=command.semantic_action,
            selection_sha256=content_sha256(candidate), capture_id=identity,
            candidate_id=command.candidate_id, click_point=point, target_window_handle=handle,
            gate_decision_ref='dev-test-gate:' + content_sha256(gate), popup_guard=popup_guard)
        result = {'contract_version': 'native_review_dev_click_result_v1', 'action': self.action,
                  'production_workflow_approval': False, 'preview_sha256': reviewed_sha256,
                  'pre_click_decision': gate, 'status': 'result_unknown'}
        try:
            result['backend'] = self.dispatch(command, authority)
            result['post_verification'] = self.post_capture()
            if result['backend']['status'] == 'dispatched':
                if self.action == ACTION and result['post_verification'].get('single_step_visible') is True:
                    result['status'] = 'verified'
                elif self.action != ACTION:
                    # 异步预检或菜单点击只证明发送；必须另外观察实际界面与后台结果。
                    result['status'] = 'dispatched_unverified'
        except Exception as error:
            result['error'] = {'type': type(error).__name__, 'message': str(error)}
        write_json(self.output_dir / ('result-' + reviewed_sha256 + '.json'), result)
        return result


def create_test_app(controller, preview, reviewed_sha256):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post('/action/execute_recognition_plan')
    async def execute_recognition_plan(request: Request):
        try:
            payload = await request.json()
            if payload != {'reviewed_sha256': reviewed_sha256}:
                return JSONResponse({'error': 'exact reviewed digest required'}, status_code=400)
            result = controller.execute(preview, reviewed_sha256)
            return JSONResponse(result, status_code={'verified': 200, 'dispatched_unverified': 202}.get(result['status'], 409))
        except (ValueError, PermissionError, KeyError, TypeError) as error:
            return JSONResponse({'error': str(error)}, status_code=409)

    return app


class ExistingReviewWindow:
    def __init__(self, owner_path, output_dir, *, action=ACTION, expected_name=None):
        _target_spec(action, expected_name)
        self.action = action
        self.expected_name = expected_name
        self.owner = json.loads(Path(owner_path).read_text(encoding='utf-8'))
        self.output_dir = Path(output_dir).resolve()
        if not self.output_dir.is_relative_to(TEST_ROOT.resolve()):
            raise ValueError('test output must remain under D:/AgentReviewAcceptance')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def bind(self):
        import psutil
        import win32con
        import win32gui
        from app.core.window_manager import window_manager
        process = psutil.Process(self.owner['pid'])
        if process.create_time() != self.owner['create_time'] or process.cmdline() != self.owner['command']:
            raise PermissionError('test process identity changed')
        command = process.cmdline()
        executable = Path(process.exe()).resolve()
        if (executable.name.lower() != 'agentreview.exe' or command.count('--data-dir') != 1
                or any(arg.startswith('--data-dir=') for arg in command)
                or command.index('--data-dir') + 1 >= len(command)):
            raise PermissionError('only an isolated AgentReview test process is allowed')
        data = Path(command[command.index('--data-dir') + 1]).resolve()
        if not data.is_relative_to(TEST_ROOT.resolve()) or data == TEST_ROOT.resolve():
            raise PermissionError('production review data is forbidden')
        windows = [w for w in window_manager.list_visible_windows() if w['process_id'] == process.pid]
        main = [w for w in windows if w['title'] == '原生审核工作区']
        if len(main) != 1:
            raise PermissionError('test window is not unique')
        target = main[0]
        if self.action != ACTION:
            dialogs = [w for w in windows if w['title'] == '单步验证 · 人工审核后执行']
            if len(dialogs) != 1:
                raise PermissionError('test dialog is missing or ambiguous')
            target = dialogs[0]
            if win32gui.GetWindow(target['handle'], win32con.GW_OWNER) != main[0]['handle']:
                raise PermissionError('test dialog does not belong to the isolated main window')
        bound = window_manager.bind_window_by_handle(target['handle'])
        if bound.handle != target['handle'] or bound.process_id != process.pid:
            raise PermissionError('test window process changed while binding')
        return process, executable, bound

    def observe(self):
        import win32gui
        from app.core.screenshot import screenshot_service
        from app.core.runtime_artifacts import pinned_runtime_output_root
        from app.core.window_manager import window_manager
        from app.operation.screen_reading.uia_provider import uia_provider
        process, executable, bound = self.bind()
        if not bound.is_active:
            raise PermissionError('test window must be foreground before preview/execute')
        def client_rectangle():
            cx, cy = win32gui.ClientToScreen(bound.handle, (0, 0))
            cr = win32gui.GetClientRect(bound.handle)
            return [cx - bound.rect.left, cy - bound.rect.top, cr[2] - cr[0], cr[3] - cr[1]]
        controls = uia_provider.snapshot_bound_window()['controls']
        dialog_visible = any(c['name'] == '单步验证 · 人工审核后执行' and c['control_type'] == 'Window' and c['visible'] is True for c in controls)
        if self.action == ACTION and dialog_visible:
            raise PermissionError('Single-step dialog is already visible')
        if self.action != ACTION and not dialog_visible:
            raise PermissionError('Single-step dialog must be visible for declared controls')
        c = select_test_control(controls, self.action, self.expected_name)
        bbox = [c['bbox'][key] for key in ('x', 'y', 'w', 'h')]
        popup = None
        if self.action in POPUP_ACTIONS:
            from app.agent.windows_popup_reader import WindowsPopupReader
            popup = WindowsPopupReader().read(parent_handle=bound.handle,
                combo_name=POPUP_ACTIONS[self.action], item_name=self.expected_name)
            screen_bbox = c['screen_bbox']
            expected = [popup.popup_rect[0] + popup.item_bbox[0], popup.popup_rect[1] + popup.item_bbox[1],
                        popup.item_bbox[2], popup.item_bbox[3]]
            if [screen_bbox[k] for k in ('x', 'y', 'w', 'h')] != expected:
                raise PermissionError('popup reader and candidate geometry disagree')
            bound = window_manager.bind_window_by_handle(popup.popup_handle)
            if bound.process_id != process.pid:
                raise PermissionError('popup process changed while binding')
            bbox = list(popup.item_bbox)
        client_rect = client_rectangle()
        cx, cy, cw, ch = client_rect
        if not (cx <= bbox[0] < bbox[0] + bbox[2] <= cx + cw
                and cy <= bbox[1] < bbox[1] + bbox[3] <= cy + ch):
            raise PermissionError('test target is outside the captured client area')
        point = [bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2]
        visibility = window_manager.validate_bound_point_visibility(bound=bound, x=point[0], y=point[1])
        if visibility.get('allowed') is not True or visibility['hit_window']['root_handle'] != bound.handle:
            raise PermissionError('test target point is occluded')
        with pinned_runtime_output_root(self.output_dir / ('capture-' + uuid4().hex)):
            image = screenshot_service.capture_window(focus_window=False, purpose='dev-test-preview')
        if asdict(window_manager.get_bound_window()) != asdict(bound) or client_rectangle() != client_rect:
            raise PermissionError('window drift during capture')
        return {'window': {'handle': bound.handle, 'process_id': process.pid,
                           'create_time': process.create_time(), 'exe': str(executable),
                           'rect': [bound.rect.left, bound.rect.top, bound.rect.right, bound.rect.bottom]},
                'viewport_size': [image['image_width'], image['image_height']],
                **visual_fingerprint(image['image_path'], client_rect),
                'image_path': image['image_path'],
                **({'popup_target': asdict(popup)} if popup is not None else {}),
                'candidate': {'name': c['name'], 'control_type': c['control_type'],
                              'enabled': c['enabled'], 'visible': c['visible'],
                              'automation_id': c['automation_id'], 'bbox': bbox,
                              'click_point': point, 'source': 'windows_uia', 'confidence': 1.0}}

    def after(self):
        from app.core.screenshot import screenshot_service
        from app.core.runtime_artifacts import pinned_runtime_output_root
        from app.operation.screen_reading.uia_provider import uia_provider
        self.bind()
        with pinned_runtime_output_root(self.output_dir / ('after-' + uuid4().hex)):
            image = screenshot_service.capture_window(focus_window=False, purpose='dev-test-after')
        snapshot = uia_provider.snapshot_bound_window()
        image.update({'single_step_visible': any(c['name'] == '单步验证 · 人工审核后执行' and c['control_type'] == 'Window' and c['visible'] is True
                                               for c in snapshot.get('controls', [])),
                      'controls': snapshot.get('controls', [])})
        return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--execute-preview', type=Path)
    parser.add_argument('--reviewed-sha256')
    parser.add_argument('--enable-test-input', action='store_true')
    parser.add_argument('--action', choices=tuple(TEST_ACTIONS), default=ACTION)
    parser.add_argument('--expected-name', help='Exact visible item name for choose_* only.')
    args = parser.parse_args()
    target = ExistingReviewWindow(args.owner, args.output_dir, action=args.action, expected_name=args.expected_name)
    from loguru import logger
    logger.add(target.output_dir / 'driver.log', encoding='utf-8')
    from app.agent.desktop_backend import ExistingWindowsBackendAdapter
    backend = ExistingWindowsBackendAdapter(post_dispatch_settle_seconds=0.3)
    controller = TestClickController(observe=target.observe,
        dispatch=lambda command, authority: asdict(backend.dispatch(command, authority=authority)),
        post_capture=target.after, output_dir=target.output_dir, enabled=args.enable_test_input,
        action=args.action, expected_name=args.expected_name)
    if args.execute_preview is None:
        preview = controller.preview()
        path = target.output_dir / ('preview-' + preview['capture_id'] + '.json')
        write_json(path, preview)
        print(json.dumps({'preview_path': str(path), 'reviewed_sha256': content_sha256(preview),
                          'observation': preview['observation']}, ensure_ascii=False))
    else:
        if args.execute_preview.resolve().parent != target.output_dir:
            raise PermissionError('preview and claim must share the same test output directory')
        preview = json.loads(args.execute_preview.read_text(encoding='utf-8'))
        import asyncio
        import httpx
        # 保持在初始化 UIA 的同一线程；仅进程内 ASGI 调用，不监听端口。
        async def post():
            transport = httpx.ASGITransport(app=create_test_app(controller, preview, args.reviewed_sha256))
            async with httpx.AsyncClient(transport=transport, base_url='http://dev-test.local') as client:
                return await client.post('/action/execute_recognition_plan', json={'reviewed_sha256': args.reviewed_sha256})
        response = asyncio.run(post())
        result = response.json()
        if 'status' in result:
            print(json.dumps({'status': result['status'], 'backend': result.get('backend'),
                'post_image': result.get('post_verification', {}).get('image_path'),
                'result_path': str(target.output_dir / ('result-' + args.reviewed_sha256 + '.json'))}, ensure_ascii=False))
        else:
            print(response.text)
        if response.status_code not in (200, 202):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
