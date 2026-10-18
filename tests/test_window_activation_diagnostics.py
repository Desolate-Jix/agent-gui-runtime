"""激活拒绝保留附件来源，不把未保证的错误码当权限证明。"""
from types import SimpleNamespace as NS
import json
import pytest
from app.core import window_manager as module
from app.core import window_preparation as preparation


@pytest.fixture
def scene(monkeypatch):
    manager = module.WindowManager()
    state = NS(foreground=200, code=5, events=[], fail=True)
    attachment = Exception(5, 'AttachThreadInput', 'denied')
    def attach(current, target, enabled):
        state.events.append(('attach', current, target, enabled))
        if target == 20 and enabled:
            raise attachment
    def foreground(handle):
        state.events.append(('foreground', state.code))
        if state.fail:
            raise Exception(state.code, 'SetForegroundWindow', 'unverified')
        state.foreground = handle
    monkeypatch.setattr(module, 'win32api', NS(GetCurrentThreadId=lambda: 10, SetLastError=lambda value: setattr(state, 'code', value)))
    monkeypatch.setattr(module, 'win32process', NS(GetWindowThreadProcessId=lambda h: (20 if h == 200 else 30, 99), AttachThreadInput=attach))
    monkeypatch.setattr(module, 'win32gui', NS(IsIconic=lambda h: False, GetForegroundWindow=lambda: state.foreground,
        BringWindowToTop=lambda h: None, SetWindowPos=lambda *a: None, SetForegroundWindow=foreground))
    monkeypatch.setattr(module, 'win32con', NS(HWND_TOPMOST=-1, HWND_NOTOPMOST=-2, SWP_NOMOVE=2, SWP_NOSIZE=1, SWP_SHOWWINDOW=64))
    monkeypatch.setattr(manager, '_ensure_window_mutation_authority', lambda **k: None)
    monkeypatch.setattr(manager, '_ensure_windows_backend', lambda: None)
    monkeypatch.setattr(preparation, '_window_preparation_is_active', lambda: True)
    monkeypatch.setattr(manager, '_retry_foreground_activation_with_alt_unlock', lambda h: pytest.fail('synthetic input'))
    monkeypatch.setattr(manager, '_cycle_past_shell_notification_foreground', lambda h: pytest.fail('synthetic input'))
    monkeypatch.setattr(manager, 'get_owned_foreground_popup_handle', lambda b: None)
    bound = module.BoundWindow(100, 'target', 99, 'app.exe', module.WindowRect(0, 0, 100, 100), False)
    monkeypatch.setattr(manager, 'get_bound_window', lambda: bound)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    return manager, state, attachment


@pytest.mark.parametrize('code', [0, 5])
def test_foreground_code_is_not_permission_proof_and_attachment_is_retained(scene, monkeypatch, code):
    manager, state, attachment = scene
    def fail(handle):
        state.events.append(('foreground', state.code))
        raise Exception(code, 'SetForegroundWindow', 'unverified')
    monkeypatch.setattr(module.win32gui, 'SetForegroundWindow', fail)
    with pytest.raises(RuntimeError) as caught:
        manager.focus_bound_window()
    assert caught.value.__cause__.args[1] == 'SetForegroundWindow'
    details = preparation.window_preparation_failure_details(caught.value)
    assert details['access_denied'] is False and details['privilege_mismatch_possible'] is False
    assert details['winerror_reliable'] is False
    assert details['activation']['current_thread'] == 10
    assert details['activation']['foreground_thread'] == 20 and details['activation']['target_thread'] == 30
    assert details['activation']['attachment_failures'][0]['winerror'] == 5
    assert caught.value.__cause__.activation_attachment_errors == (attachment,)
    assert ('foreground', 0) in state.events
    assert ('attach', 10, 30, False) in state.events
    assert 'privilege mismatch' not in preparation.window_preparation_failure_message(details)


def test_successful_foreground_ignores_prior_attachment_warning(scene):
    manager, state, _ = scene
    state.fail = False
    assert manager.focus_bound_window().handle == 100
    assert sum(event[0] == 'foreground' for event in state.events) == 1


def test_other_win32_error_keeps_reliable_access_denied():
    details = preparation.window_preparation_failure_details(Exception(5, 'AttachThreadInput', 'denied'))
    assert details['access_denied'] is True and details['privilege_mismatch_possible'] is True


def test_api_return_without_actual_foreground_still_refuses(scene, monkeypatch):
    manager, _, _ = scene
    monkeypatch.setattr(module.win32gui, 'SetForegroundWindow', lambda handle: None)
    with pytest.raises(RuntimeError, match='foreground verification failed'):
        manager.focus_bound_window()


def test_real_pywintypes_errors_keep_identity_and_json_diagnostics(scene, monkeypatch):
    pywintypes = pytest.importorskip('pywintypes')
    manager, _, _ = scene
    attachment = pywintypes.error(5, 'AttachThreadInput', 'denied')
    foreground_error = pywintypes.error(5, 'SetForegroundWindow', 'unverified')

    def attach(current, target, enabled):
        if enabled and target == 20:
            raise attachment

    def activate(handle):
        raise foreground_error

    monkeypatch.setattr(module.win32process, 'AttachThreadInput', attach)
    monkeypatch.setattr(module.win32gui, 'SetForegroundWindow', activate)
    with pytest.raises(RuntimeError) as caught:
        manager.focus_bound_window()
    assert caught.value.__cause__ is foreground_error
    assert foreground_error.activation_attachment_errors == (attachment,)
    details = preparation.window_preparation_failure_details(caught.value)
    restored = json.loads(json.dumps(details, ensure_ascii=False, allow_nan=False))
    assert restored['winerror'] == 5 and restored['winerror_reliable'] is False
    assert restored['activation']['attachment_failures'][0]['win32_function'] == 'AttachThreadInput'
