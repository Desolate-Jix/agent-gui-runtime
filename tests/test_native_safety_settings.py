"""本地安全策略开关不能成为远程权限或更改已批准的步骤。"""
from types import SimpleNamespace
import pytest
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError, _production_runtime_factory


def _coordinator(tmp_path):
    return NativeSingleStepCoordinator(tmp_path,
        SimpleNamespace(list_reviewed_assets=lambda: []),
        SimpleNamespace(status=lambda: {'phase': 'ready'}),
        runtime_factory=lambda **kw: None, thread_initializer=lambda: None,
        thread_finalizer=lambda: None)


def test_default_on_toggle_is_local_and_does_not_dispatch(tmp_path):
    coordinator = _coordinator(tmp_path)
    assert coordinator.safety_settings() == {'automatic_safety_interception': True,
        'scope': 'automatic_risk_policy', 'session_only': True}
    assert coordinator.set_automatic_safety_interception(False)['automatic_safety_interception'] is False
    assert coordinator._runtime is None and coordinator._confirmation_id is None
    assert coordinator.set_automatic_safety_interception(True)['automatic_safety_interception'] is True
    assert _coordinator(tmp_path).safety_settings()['automatic_safety_interception'] is True


@pytest.mark.parametrize('field,value', [('_busy', True), ('_shutdown', True),
    ('_phase', 'pending_review'), ('_phase', 'approved'), ('_runtime', object()),
    ('_confirmation_id', 'pending'), ('_factory_outcome_unknown', True),
    ('_model_service', object()), ('_model_release_pending', True),
    ('_window_preparations', {'pending': {}})])
def test_mode_is_frozen_while_an_action_or_cleanup_is_owned(tmp_path, field, value):
    coordinator = _coordinator(tmp_path)
    setattr(coordinator, field, value)
    with pytest.raises(NativeSingleStepCoordinatorError, match='safety_mode_change_unavailable'):
        coordinator.set_automatic_safety_interception(False)
    assert coordinator.safety_settings()['automatic_safety_interception'] is True


@pytest.mark.parametrize('value', [0, 1, None, 'false', {}, []])
def test_mode_accepts_only_explicit_local_boolean(tmp_path, value):
    with pytest.raises(TypeError):
        _coordinator(tmp_path).set_automatic_safety_interception(value)


def test_old_published_path_cannot_silently_ignore_disabled_interception(tmp_path):
    with pytest.raises(NativeSingleStepCoordinatorError, match='safety_observation_mode_unsupported'):
        _production_runtime_factory(project_root=tmp_path, selection=object(),
            window_manager=None, automatic_safety_interception=False)


def test_unsupported_mode_is_rejected_before_model_or_window_loading(tmp_path, monkeypatch):
    coordinator = _coordinator(tmp_path)
    coordinator.set_automatic_safety_interception(False)
    def unexpected():
        pytest.fail('unsupported mode must fail before runtime setup')
    monkeypatch.setattr(coordinator, '_check_runtime_environment', unexpected)
    with pytest.raises(NativeSingleStepCoordinatorError) as caught:
        coordinator._create_runtime_on_owner(object())
    assert caught.value.code == 'safety_observation_mode_unsupported'


@pytest.mark.parametrize('enabled', [True, False])
def test_production_factory_forwards_local_mode_to_fresh_controller(tmp_path, monkeypatch, enabled):
    from app.agent import fresh_learning_factory
    from app.desktop_review.fresh_runtime_callsite import FreshRuntimeSelection
    from tests.test_fresh_runtime_callsite import _callsite, _close

    host, owner, runtime, backend, claims, callsite, scope, intent = _callsite(tmp_path)
    monkeypatch.setattr(fresh_learning_factory, 'create_fresh_learning_observation_owner', lambda **kw: owner)
    try:
        built = _production_runtime_factory(project_root=callsite._selection.source.project_root,
            selection=FreshRuntimeSelection(callsite._selection.source), window_manager=SimpleNamespace(),
            fresh_source_owner=host.fresh_learning, learning_binding=callsite._learning_binding,
            automatic_safety_interception=enabled)
        assert built._controller._automatic_safety_interception is enabled
        assert built.cancel_local_preparation()['cleanup_verified'] is True
        assert backend.commands == []
    finally:
        _close(host, runtime)
