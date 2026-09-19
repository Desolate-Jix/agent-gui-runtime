from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.desktop_review import window_preparation as module
from app.desktop_review.window_preparation import WindowPreparationMixin


IDENTITY = {
    "contract_version": "windows_native_identity_observation_v1",
    "provider": "windows_native_identity",
    "status": "observed",
    "target_window_handle": 101,
    "process_id": 202,
    "process_create_time": 12.5,
    "executable_path": "c:\\program files\\demo\\demo.exe",
}


class Windows:
    def __init__(self):
        self.visible = True

    def bind_window_by_handle(self, handle):
        assert handle == 101
        return SimpleNamespace(handle=handle, process_id=202, title="Demo")

    def list_visible_windows(self):
        return [{"handle": 101}] if self.visible else []


class Coordinator(WindowPreparationMixin):
    def __init__(self, windows):
        self.windows = windows
        self._owner = SimpleNamespace(call=lambda fn: fn())
        self._launched_window_identities = {(101, 202): deepcopy(IDENTITY)}
        self._cancel_wait = __import__("threading").Event()

    def _windows(self):
        return self.windows

    def _begin(self, *args, **kwargs):
        return None

    def _end(self):
        return None

    def _require_host_ready(self, **kwargs):
        return None

    @staticmethod
    def _error(code, message, **kwargs):
        error = RuntimeError(message)
        error.code = code
        return error


def test_close_launched_window_posts_close_and_confirms_disappearance(monkeypatch):
    windows = Windows()
    coordinator = Coordinator(windows)
    posted = []

    monkeypatch.setattr(module, "post_window_close", lambda handle: posted.append(handle))
    monkeypatch.setattr(module, "window_handle_exists", lambda handle: False)
    monkeypatch.setattr(module.WindowsNativeIdentityReader, "read_identity", lambda self, handle: deepcopy(IDENTITY))

    def disappear(_):
        posted.append("sent")
        windows.visible = False

    monkeypatch.setattr(module, "post_window_close", disappear)
    result = coordinator.close_launched_window(target_window_handle=101, target_process_id=202)

    assert result == {
        "status": "window_closed", "success": True, "close_requested": True,
        "automatic_retry_allowed": False,
    }
    assert posted == ["sent"]


def test_launch_observation_registers_identity_for_later_close(monkeypatch):
    windows = Windows()
    coordinator = Coordinator(windows)
    coordinator._launched_window_identities.clear()
    monkeypatch.setattr(module.WindowsNativeIdentityReader, "read_identity", lambda self, handle: deepcopy(IDENTITY))
    intent = {"executable_path": IDENTITY["executable_path"], "source": "app_catalog"}
    result = coordinator._await_launched_window(intent, SimpleNamespace(pid=202), set())
    assert result["status"] == "launched_window_ready"
    assert coordinator._launched_window_identities[(101, 202)] == IDENTITY


def test_close_launched_window_rejects_window_not_launched_by_this_coordinator():
    coordinator = Coordinator(Windows())
    with pytest.raises(Exception) as exc:
        coordinator.close_launched_window(target_window_handle=999, target_process_id=202)
    assert getattr(exc.value, "code", None) == "window_close_not_launched"


def test_pending_close_can_later_confirm_disappearance_without_rebinding(monkeypatch):
    coordinator = Coordinator(Windows())
    coordinator._launched_window_close_state = {(101, 202): True}
    def gone(_):
        raise ValueError('window no longer exists')
    monkeypatch.setattr(coordinator.windows, 'bind_window_by_handle', gone)
    monkeypatch.setattr(module, 'window_handle_exists', lambda _: False)
    monkeypatch.setattr(module, 'post_window_close', lambda _: pytest.fail('must not send again'))
    result = coordinator.close_launched_window(target_window_handle=101, target_process_id=202)
    assert result['status'] == 'window_closed' and result['success']
    assert not coordinator._launched_window_identities


@pytest.mark.parametrize('field,value', [('process_create_time', 99.0), ('executable_path', 'c:\\other.exe')])
def test_close_rejects_reused_identity_without_dispatch(monkeypatch, field, value):
    coordinator = Coordinator(Windows())
    changed = {**IDENTITY, field: value}
    monkeypatch.setattr(module.WindowsNativeIdentityReader, 'read_identity', lambda *_: changed)
    monkeypatch.setattr(module, 'post_window_close', lambda _: pytest.fail('wrong target'))
    with pytest.raises(RuntimeError) as exc:
        coordinator.close_launched_window(target_window_handle=101, target_process_id=202)
    assert exc.value.code == 'window_close_identity_changed'


def test_hidden_window_is_pending_and_second_call_does_not_repeat_close(monkeypatch):
    coordinator = Coordinator(Windows())
    coordinator.windows.visible = False
    posted = []
    monkeypatch.setattr(module.WindowsNativeIdentityReader, 'read_identity', lambda *_: deepcopy(IDENTITY))
    monkeypatch.setattr(module, 'window_handle_exists', lambda _: True)
    monkeypatch.setattr(module, 'post_window_close', lambda handle: posted.append(handle))
    for _ in range(2):
        result = coordinator.close_launched_window(target_window_handle=101, target_process_id=202)
        assert result['status'] == 'window_close_pending' and not result['success']
    assert posted == [101]
