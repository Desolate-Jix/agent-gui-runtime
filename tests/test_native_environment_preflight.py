import pytest

from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from tests.test_native_single_step_coordinator import _Facade, _Host, _Runtime, _Windows


def test_missing_runtime_dependencies_are_rejected_before_binding_or_factory(tmp_path, monkeypatch):
    import app.desktop_review.single_step_coordinator as module
    from app.runtime_environment import inspect_environment
    blocked = inspect_environment(profile="windows_runtime", find_spec=lambda name: None, version=lambda name: "1")
    monkeypatch.setattr(module, "inspect_environment", lambda **kwargs: blocked)

    def forbidden(**kwargs):
        pytest.fail("missing metadata must block before runtime construction")

    monkeypatch.setattr(module, "_production_runtime_factory", forbidden)
    co = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), thread_initializer=lambda: None, thread_finalizer=lambda: None)
    monkeypatch.setattr(co, "_windows", lambda: pytest.fail("preflight must not enumerate or bind windows"))
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.inventory()
        assert error.value.code == "runtime_dependencies_missing"
        assert co._owner.thread_id is None
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.prepare(asset_id="asset-1", asset_content_sha256="a" * 64, target_window_handle=41, target_process_id=7)
        assert error.value.code == "runtime_dependencies_missing"
        assert co._runtime is None and co._factory_outcome_unknown is False
        assert co._owner.thread_id is None
        assert co.cancel() == {"phase": "idle", "cleanup_verified": True}
        co.shutdown()
    finally:
        co._owner.close()


def test_environment_report_does_not_start_runtime_owner(tmp_path):
    co = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), thread_initializer=lambda: None, thread_finalizer=lambda: None)
    try:
        result = co.environment()
        assert result["contract_version"] == "native_environment_metadata_v1"
        assert result["runtime_verified"] is False
        assert co._owner.thread_id is None
        assert co._runtime is None
    finally:
        co.shutdown()


def test_positive_metadata_does_not_hide_actual_factory_failure_or_release_unknown_owner(tmp_path, monkeypatch):
    from tests.test_native_vision_configuration import _config
    _config(tmp_path / "configs/vision.json")
    import app.desktop_review.single_step_coordinator as module
    from app.runtime_environment import inspect_environment
    present = inspect_environment(profile="windows_runtime", find_spec=lambda name: object(),
                                  version=lambda name: "1", python_version=(3, 11, 9), platform="win32")
    monkeypatch.setattr(module, "inspect_environment", lambda **kwargs: present)
    calls = []

    def factory(**kwargs):
        calls.append(kwargs["selection"])
        raise RuntimeError("private-factory-failure")

    factory.window_manager = _Windows()
    monkeypatch.setattr(module, "_production_runtime_factory", factory)
    co = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), thread_initializer=lambda: None, thread_finalizer=lambda: None)
    selection = dict(asset_id="asset-1", asset_content_sha256="a" * 64, target_window_handle=41, target_process_id=7)
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.prepare(**selection)
        assert error.value.code == "runtime_prepare_failed"
        assert error.value.result_unknown is True
        assert "private-factory-failure" not in str(error.value)
        assert co._factory_outcome_unknown is True
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.prepare(**selection)
        assert error.value.code == "runtime_cleanup_pending"
        for operation in (co.cancel, co.shutdown):
            with pytest.raises(NativeSingleStepCoordinatorError):
                operation()
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.environment()
        assert error.value.code == "invalid_phase"
        assert len(calls) == 1
        assert co._factory_outcome_unknown is True
    finally:
        co._owner.close()


def test_falsy_injected_factory_is_not_replaced_by_unchecked_production_factory(tmp_path, monkeypatch):
    import app.desktop_review.single_step_coordinator as module
    windows, runtime = _Windows(), _Runtime()
    calls = []

    class Factory:
        window_manager = windows

        def __bool__(self):
            return False

        def __call__(self, **kwargs):
            calls.append(kwargs["selection"])
            return runtime

    def forbidden(**kwargs):
        pytest.fail("an explicit injected factory must never select the production backend")

    forbidden.window_manager = windows
    monkeypatch.setattr(module, "_production_runtime_factory", forbidden)
    monkeypatch.setattr(module, "inspect_environment", lambda **kwargs: pytest.fail("production metadata must not govern an injected backend"))
    co = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), runtime_factory=Factory(),
                                   thread_initializer=lambda: None, thread_finalizer=lambda: None)
    try:
        result = co.prepare(asset_id="asset-1", asset_content_sha256="a" * 64, target_window_handle=41, target_process_id=7)
        assert result["session_id"] == "session-1"
        assert len(calls) == 1
        assert co.cancel() == {"phase": "idle", "cleanup_verified": True}
        co.shutdown()
    finally:
        co._owner.close()
