"""绑定刷新失败必须记录具体子条件，不只报告身份不可用。"""
from types import SimpleNamespace

import pytest
import app.core.window_manager as module


@pytest.mark.parametrize('visible,root,title,reason', [
    (False, 100, 'Page', 'not_visible'),
    (True, 200, 'Page', 'not_top_level'),
    (True, 100, '', 'empty_title'),
])
def test_bound_candidate_rejection_identifies_condition(monkeypatch, visible, root, title, reason):
    manager = module.WindowManager()
    manager._bound_window = SimpleNamespace(handle=100)
    monkeypatch.setattr(module, 'WINDOWS_BACKEND_AVAILABLE', True)
    monkeypatch.setattr(module, 'win32gui', SimpleNamespace(
        IsWindowVisible=lambda _: visible, GetAncestor=lambda *_: root))
    warnings = []
    monkeypatch.setattr(module.logger, 'warning', lambda *args: warnings.append(args))
    assert not manager._is_candidate_window(SimpleNamespace(handle=100, window_text=lambda: title))
    assert any(reason in str(entry) for entry in warnings)


def test_discovery_rejection_does_not_flood_binding_diagnostics(monkeypatch):
    manager = module.WindowManager()
    monkeypatch.setattr(module, 'WINDOWS_BACKEND_AVAILABLE', True)
    monkeypatch.setattr(module, 'win32gui', SimpleNamespace(IsWindowVisible=lambda _: False))
    warnings = []
    monkeypatch.setattr(module.logger, 'warning', lambda *args: warnings.append(args))
    assert not manager._is_candidate_window(SimpleNamespace(handle=100))
    assert not warnings
