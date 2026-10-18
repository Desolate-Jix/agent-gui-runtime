"""首次配置工具栏复用已有主窗口，不改变审核草稿或忙碌边界。"""
from app.desktop_review import window as module
from tests.test_desktop_review_window import _Facade, _wait_workers
from tests.test_native_model_setup_dialog import C


def test_setup_action_uses_exact_coordinator_and_respects_workspace_busy(monkeypatch):
    app = module.ensure_application(); coordinator = C()
    window = module.ReviewMainWindow(_Facade([]), single_step=coordinator)
    calls = []
    monkeypatch.setattr(module.ModelSetupDialog, "exec", lambda self: calls.append(self.coordinator) or 0)
    try:
        _wait_workers(window)
        assert window.model_setup_action.isEnabled()
        window._operation = "saving"
        window._set_busy(True)
        assert not window.model_setup_action.isEnabled()
        window.open_model_setup()
        assert calls == []
        window._operation = "idle"; window._set_busy(False)
        window.model_setup_action.trigger()
        assert calls == [coordinator]
        assert window.workspace is None and not window.is_dirty
    finally:
        window._operation = "idle"; _wait_workers(window); window.close()


def test_legacy_coordinator_without_setup_is_not_given_new_action():
    app = module.ensure_application()
    window = module.ReviewMainWindow(_Facade([]), single_step=object())
    try:
        _wait_workers(window)
        assert not window.model_setup_action.isEnabled()
        window.open_model_setup()
    finally:
        _wait_workers(window); window.close()
