"""离屏运行环境检查窗口；只验证 coordinator 边界，不接触真实 Runtime。"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import pytest

from app.desktop_review.window import ensure_application
from tests.test_desktop_single_step_dialog import _Coordinator, _click, _wait


def _environment(*, status="metadata_present_unverified"):
    return {
        "contract_version": "native_environment_metadata_v1",
        "profile": "all",
        "status": status,
        "missing_modules": ["win32api"] if status == "blocked" else [],
        "missing_distributions": ["pywin32"] if status == "blocked" else [],
        "probe_errors": [],
        "checks": [{"module": "win32api", "distribution": "pywin32", "version": "311",
                    "module_discoverable": status != "blocked", "status": "metadata_present_unverified"}],
        "runtime_verified": False,
        "imports_exercised": False,
        "model_assets_checked": False,
        "artifact_is_authorization": False,
        "interpreter": "C:/Python311/python.exe",
        "python_version": "3.11.0",
        "platform": "win32",
        "python_supported": True,
        "platform_supported": True,
        "required_python": ">=3.11,<3.12",
        "limitations": ["仅检查元数据，不导入 Runtime 或模型。"],
    }


class _EnvironmentCoordinator(_Coordinator):
    def __init__(self, result=None):
        super().__init__()
        self.environment_result = _environment() if result is None else result
        self.environment_calls = 0

    def environment(self):
        self.environment_calls += 1
        return deepcopy(self.environment_result)


def _dialog(result=None):
    from app.desktop_review.single_step_dialog import SingleStepDialog

    ensure_application()
    coordinator = _EnvironmentCoordinator(result)
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    return coordinator, dialog


def test_environment_action_is_idle_only_and_never_runs_on_open():
    coordinator, dialog = _dialog()
    try:
        assert coordinator.environment_calls == 0
        assert dialog.environment_button.isEnabled()
        dialog._has_owner = True
        dialog._phase = "approved"
        dialog._update_controls()
        assert not dialog.environment_button.isEnabled()
        assert coordinator.environment_calls == 0
    finally:
        dialog._has_owner = False
        dialog.close()


def test_environment_report_is_readonly_and_explicitly_unverified():
    coordinator, dialog = _dialog()
    try:
        _click(dialog.environment_button, dialog)
        assert coordinator.environment_calls == 1
        assert dialog.environment_report.isReadOnly()
        text = dialog.environment_report.toPlainText()
        assert "native_environment_metadata_v1" in text
        assert "不证明" in text and "不构成授权" in text
        report = json.loads(text[text.index("{"):])
        assert report["runtime_verified"] is False
        assert report["imports_exercised"] is False
        assert report["model_assets_checked"] is False
        assert report["artifact_is_authorization"] is False
        assert dialog._phase == "idle"
        assert not dialog._has_owner
    finally:
        dialog.close()


def test_invalid_environment_envelope_fails_closed_without_raw_exception():
    invalid = _environment()
    invalid["runtime_verified"] = True
    coordinator, dialog = _dialog(invalid)
    try:
        _click(dialog.environment_button, dialog)
        assert coordinator.environment_calls == 1
        assert "invalid_native_environment_response" in dialog.status_label.text()
        assert "RuntimeError" not in dialog.status_label.text()
        assert dialog._phase == "idle"
        assert not dialog._has_owner
    finally:
        dialog.close()


def test_missing_dependency_error_keeps_existing_owner_and_has_actionable_hint():
    class MissingDependencies(_EnvironmentCoordinator):
        def environment(self):
            self.environment_calls += 1
            error = RuntimeError("private-runtime-trace")
            error.code = "runtime_dependencies_missing"
            raise error

    from app.desktop_review.single_step_dialog import SingleStepDialog

    ensure_application()
    coordinator = MissingDependencies()
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    try:
        dialog._has_owner = True
        dialog._phase = "approved"
        dialog._launch("environment", coordinator.environment)
        _wait(lambda: not dialog._jobs)
        assert dialog._has_owner
        assert "依赖" in dialog.status_label.text()
        assert "private-runtime-trace" not in dialog.status_label.text()
    finally:
        dialog._has_owner = False
        dialog.close()


def test_actual_metadata_report_does_not_start_owner_or_write_state(tmp_path):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from app.desktop_review.single_step_dialog import SingleStepDialog
    from tests.test_native_single_step_coordinator import _Facade, _Host

    def forbidden(*_args, **_kwargs):
        raise AssertionError("environment check must not initialize a Runtime owner")

    ensure_application()
    coordinator = NativeSingleStepCoordinator(
        tmp_path, _Facade(), _Host(), runtime_factory=forbidden,
        thread_initializer=forbidden, thread_finalizer=forbidden,
    )
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    try:
        _click(dialog.environment_button, dialog)
        report = dialog.environment_report.toPlainText()
        assert "native_environment_metadata_v1" in report
        assert "required_python" in report
        assert dialog._phase == "idle" and not dialog._has_owner
        assert coordinator._owner.thread_id is None and coordinator._runtime is None
        assert not list(tmp_path.iterdir())
        qa_dir = os.environ.get("R6B8_QA_DIR")
        if qa_dir:
            target = Path(qa_dir)
            target.mkdir(parents=True, exist_ok=True)
            assert dialog.grab().save(str(target / "native-environment-dialog.png"))
    finally:
        dialog.close()
        coordinator.shutdown()


def test_prepare_error_code_alone_cannot_prove_factory_ownership_was_never_acquired(tmp_path):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
    from app.desktop_review.single_step_dialog import SingleStepDialog
    from tests.test_native_single_step_coordinator import _Facade, _Host, _Windows
    attempts = []

    def factory(**kwargs):
        attempts.append(kwargs["selection"])
        raise NativeSingleStepCoordinatorError("runtime_dependencies_missing", "private-factory-detail", result_unknown=False)

    factory.window_manager = _Windows()
    ensure_application()
    coordinator = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), runtime_factory=factory,
                                             thread_initializer=lambda: None, thread_finalizer=lambda: None)
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    try:
        _click(dialog.refresh_button, dialog)
        dialog.asset_selector.setCurrentIndex(0)
        dialog.window_selector.setCurrentIndex(0)
        _click(dialog.prepare_button, dialog)
        assert len(attempts) == 1 and coordinator._factory_outcome_unknown is True
        assert dialog._has_owner is True and dialog._phase == "recovery_required"
        assert not dialog.environment_button.isEnabled()
        assert not dialog.prepare_button.isEnabled()
        assert "private-factory-detail" not in dialog.status_label.text()
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            coordinator.cancel()
        assert error.value.code == "runtime_cleanup_pending"
    finally:
        # 仅关闭测试中的虚拟实例；生产界面仍须取得清理证明。
        dialog._has_owner = False
        dialog.close()
        coordinator._owner.close()
