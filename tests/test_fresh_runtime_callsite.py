"""正式首次学习适配器复用实际控制器与归档。"""

import base64
import importlib.util

import pytest

from app.agent_link.learning_runtime_binding import LearningRuntimeBinding
from tests.test_fresh_learning_action_preview import _setup
from tests.test_fresh_dispatch_graph import _Visible, _close


def _callsite(tmp_path):
    assert importlib.util.find_spec("app.desktop_review.fresh_runtime_callsite"), "fresh callsite is missing"
    from app.desktop_review.fresh_runtime_callsite import FreshLearningRuntimeCallsite

    host, owner, runtime, backend, claims, source, old, intent = _setup(tmp_path)
    runtime.cancel_session_preparation(preparation_id="fresh.preview")
    runtime.set_action_learning_recorder(host.learning_segments.recorder)
    runtime._window_visibility_checker = _Visible()
    scope = {key: source.reference()[key] for key in ("connection_id", "task_id", "segment_id")}
    binding = LearningRuntimeBinding(host.learning_segments, **scope)
    callsite = FreshLearningRuntimeCallsite(controller=runtime, learning_binding=binding)
    return host, owner, runtime, backend, claims, callsite, scope, intent


def test_fresh_callsite_starts_actual_child_and_cancels_same_preparation(tmp_path):
    host, owner, runtime, backend, claims, callsite, scope, intent = _callsite(tmp_path)
    try:
        observation = callsite.start_session()
        assert host.learning_segments.get(**scope)["children"][0]["runtime_session_id"] == observation.session_id
        count = len(owner._screenshot_service.calls)
        state = callsite.get_fresh_runtime_state()
        assert state["observation"] == observation.to_dict()
        assert base64.b64decode(state["screenshot"]["png_base64"]) == owner._screenshot_service.path.read_bytes()
        assert len(owner._screenshot_service.calls) == count and backend.commands == []
        proof = callsite.cancel_local_preparation()
        assert proof["cleanup_verified"] is True
        assert proof["selection"]["source_kind"] == "fresh_learning"
        assert callsite.cancel_local_preparation() == proof
        assert runtime._sessions == {}
        assert host.learning_segments.get(**scope)["children"][0]["phase"] == "cancelled"
    finally:
        _close(host, runtime)


def test_fresh_callsite_terminal_read_returns_actual_after_not_initial_capture(tmp_path):
    host, owner, runtime, backend, claims, callsite, scope, intent = _callsite(tmp_path)
    try:
        observation = callsite.start_session()
        request = {**intent.to_dict(), "session_id": observation.session_id,
                   "observation_id": observation.observation_id}
        claim = callsite.request_grounded_confirmation(request)
        confirmation_id = claim.grounded_confirmation.confirmation_id
        with pytest.raises(ValueError):
            callsite.cancel_local_preparation()
        callsite.decide_grounded_confirmation(confirmation_id=confirmation_id, decision="approved")
        receipt = callsite.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert receipt.outcome == "ACTION_RECORDED"
        count = len(owner._screenshot_service.calls)
        state = callsite.get_fresh_runtime_state()
        assert state["receipt"] == receipt.model_dump(mode="json")
        assert state["observation"]["observation_id"] == receipt.next_observation_id
        assert state["observation"]["capture"]["capture_id"] != observation.to_dict()["capture"]["capture_id"]
        assert state["observation_role"] == "after_action"
        assert len(backend.commands) == 1 and len(owner._screenshot_service.calls) == count
        assert callsite.get_fresh_runtime_state() == state
    finally:
        _close(host, runtime)


def test_failed_child_attach_can_clean_exact_retained_session(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, callsite, scope, intent = _callsite(tmp_path)
    attach = host.learning_segments.attach_runtime
    def fail_after_attach(**kwargs):
        attach(**kwargs)
        raise OSError("isolated attach response loss")
    monkeypatch.setattr(host.learning_segments, "attach_runtime", fail_after_attach)
    try:
        with pytest.raises(OSError, match="response loss"):
            callsite.start_session()
        session_id = next(iter(runtime._sessions))
        assert callsite.cancel_local_preparation()["cleanup_verified"] is True
        child = host.learning_segments.get(**scope)["children"][0]
        assert child["runtime_session_id"] == session_id and child["phase"] == "cancelled"
        assert runtime._sessions == {} and backend.commands == []
    finally:
        _close(host, runtime)


def test_after_capture_unavailable_never_returns_before_as_current(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, callsite, scope, intent = _callsite(tmp_path)
    observe = owner.observe
    def fail_after(**kwargs):
        if backend.commands:
            raise OSError("isolated after capture failure")
        return observe(**kwargs)
    monkeypatch.setattr(owner, "observe", fail_after)
    try:
        observation = callsite.start_session()
        claim = callsite.request_grounded_confirmation({**intent.to_dict(), "session_id": observation.session_id,
            "observation_id": observation.observation_id})
        confirmation_id = claim.grounded_confirmation.confirmation_id
        callsite.decide_grounded_confirmation(confirmation_id=confirmation_id, decision="approved")
        receipt = callsite.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert receipt.outcome == "OBSERVATION_FAILED"
        state = callsite.get_fresh_runtime_state()
        assert "observation" not in state and "screenshot" not in state
        assert state["observation_role"] == "unavailable_after_action"
        assert len(backend.commands) == 1
    finally:
        _close(host, runtime)


def test_production_builder_reuses_backend_and_frozen_observation_configuration(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.agent import fresh_learning_factory
    from app.agent.desktop_backend import ExistingWindowsBackendAdapter
    from app.desktop_review.fresh_runtime_callsite import FreshRuntimeSelection, build_fresh_runtime_callsite

    host, owner, runtime, backend, claims, callsite, scope, intent = _callsite(tmp_path)
    calls = []
    snapshot = object()
    def observation_factory(**kwargs):
        calls.append(kwargs)
        return owner
    monkeypatch.setattr(fresh_learning_factory, "create_fresh_learning_observation_owner", observation_factory)
    windows = SimpleNamespace()
    try:
        built = build_fresh_runtime_callsite(project_root=callsite._selection.source.project_root,
            selection=FreshRuntimeSelection(callsite._selection.source), window_manager=windows,
            fresh_source_owner=host.fresh_learning, learning_binding=callsite._learning_binding,
            vision_configuration=snapshot)
        assert calls[0]["vision_configuration"] is snapshot
        assert isinstance(built._controller._backend, ExistingWindowsBackendAdapter)
        assert built._controller._backend._window_manager is windows
        assert built._controller._action_learning_recorder is host.learning_segments.recorder
        assert built._controller._asset_loader is None
        assert built.cancel_local_preparation()["cleanup_verified"] is True
    finally:
        _close(host, runtime)
