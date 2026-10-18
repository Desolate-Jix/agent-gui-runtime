import pytest

from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from app.runtime_environment import inspect_environment
from tests.test_agent_runtime_grounded_preview import live
from tests.test_agent_runtime_grounded_recovery import _checkpoint, _release_test_processes
from tests.test_native_single_step_coordinator import _Facade, _Host


def test_missing_metadata_during_history_recovery_preserves_checkpoint_without_factory_or_window(live, tmp_path, monkeypatch):
    import app.desktop_review.single_step_coordinator as module
    confirmation_id = _checkpoint(live, monkeypatch)
    blocked = inspect_environment(profile="windows_runtime", find_spec=lambda name: None, version=lambda name: "1")
    monkeypatch.setattr(module, "inspect_environment", lambda **kwargs: blocked)

    def forbidden(**kwargs):
        pytest.fail("metadata failure must block recovery before constructing a new runtime")

    monkeypatch.setattr(module, "_production_runtime_factory", forbidden)
    co = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), thread_initializer=lambda: None, thread_finalizer=lambda: None)
    monkeypatch.setattr(co, "_windows", lambda: pytest.fail("metadata failure must not bind or enumerate windows"))
    try:
        before = co.history()["items"]
        assert before[0]["phase"] == "verification_pending"
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.recover_history(confirmation_id=confirmation_id)
        assert error.value.code == "runtime_dependencies_missing"
        assert error.value.result_unknown is False
        assert co._runtime is None and co._factory_outcome_unknown is False
        assert co._history_confirmation_id is None
        assert co.history()["items"] == before
        assert co.cancel() == {"phase": "idle", "cleanup_verified": True}
    finally:
        co.shutdown()
