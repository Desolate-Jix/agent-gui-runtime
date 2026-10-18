"""终态拒绝后的取消须同步持久空 child，不以返回类型代替账本事实。"""
from dataclasses import replace

import pytest

from app.agent.fresh_learning_observation import FreshLearningObservationError
from app.agent.fresh_learning_action_contracts import FreshLearningClaimObservation
from app.agent.live_controller import LiveControllerDecision
from tests.test_fresh_runtime_callsite import _callsite
from tests.test_fresh_dispatch_graph import _close


def _pending(callsite,intent):
    observation = callsite.start_session()
    claim = callsite.request_grounded_confirmation({**intent.to_dict(),
        'session_id':observation.session_id,'observation_id':observation.observation_id})
    return observation,claim.grounded_confirmation.confirmation_id


def test_real_stale_then_repeated_cancel_closes_empty_child_and_segment(tmp_path,monkeypatch):
    host,owner,runtime,backend,claims,callsite,scope,intent = _callsite(tmp_path)
    try:
        observation,cid = _pending(callsite,intent)
        callsite.decide_grounded_confirmation(confirmation_id=cid,decision='approved')
        def changed(**_): raise FreshLearningObservationError('synthetic capture identity changed')
        monkeypatch.setattr(owner,'observe_for_action',changed)
        # 模拟控制器已关闭 claim、适配器尚未同步的既有状态。
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert isinstance(result,LiveControllerDecision)
        assert result.reason_code == 'grounded_confirmation_stale'
        assert claims.get_for_grounded_confirmation(confirmation_id=cid).phase == 'grounded_confirmation_closed'
        assert host.learning_segments.get(**scope)['children'][0]['phase'] == 'bound'
        for _ in range(2):
            callsite.cancel_grounded_review(session_id=observation.session_id)
            child = host.learning_segments.get(**scope)['children'][0]
            assert child['phase'] == 'cancelled'
            ledger = host.learning_segments.recorder.get_learning_session(learning_session_id=child['learning_session_id'])
            assert ledger['events'] == {}
        segment = host.learning_segments.get(**scope)
        assert host.learning_segments.finish(**scope,expected_revision=segment['revision'])['status'] == 'closed'
        assert backend.commands == []
    finally:
        _close(host,runtime)


def test_public_cancel_after_stale_capture_allows_segment_finish(tmp_path,monkeypatch):
    from tests.test_native_fresh_coordinator import _coordinator, _request

    host,controller,backend,callsite,scope,intent,binding,coordinator,_ = _coordinator(tmp_path)
    try:
        prepared = coordinator.prepare_fresh(source=callsite._selection.source,learning_binding=binding)
        pending = coordinator.request_fresh_review(intent=_request(prepared,intent),expected_learning_binding=binding)
        coordinator.approve(confirmation_id=pending['confirmation_id'],
            preview_sha256=pending['preview']['preview_sha256'])
        def changed(**_):
            raise FreshLearningObservationError('synthetic capture identity changed')
        monkeypatch.setattr(controller._observation_source,'observe_for_action',changed)
        result = coordinator.execute(confirmation_id=pending['confirmation_id'])
        assert result['payload']['reason_code'] == 'grounded_confirmation_stale'
        assert coordinator.cancel(expected_learning_binding=binding)['cleanup_verified'] is True
        segment = host.learning_segments.get(**scope)
        assert segment['children'][0]['phase'] == 'cancelled'
        assert host.learning_segments.finish(**scope,expected_revision=segment['revision'])['status'] == 'closed'
        assert controller._sessions == {} and backend.commands == []
    finally:
        coordinator.shutdown()
        _close(host,controller)


@pytest.mark.parametrize('mode',['pending_cancel','denied'])
def test_normal_terminal_cancel_still_closes_exact_child(tmp_path,mode):
    host,owner,runtime,backend,claims,callsite,scope,intent = _callsite(tmp_path)
    try:
        observation,cid = _pending(callsite,intent)
        if mode == 'denied':
            callsite.decide_grounded_confirmation(confirmation_id=cid,decision='denied')
        callsite.cancel_grounded_review(session_id=observation.session_id)
        assert host.learning_segments.get(**scope)['children'][0]['phase'] == 'cancelled'
        assert backend.commands == []
    finally:
        _close(host,runtime)


def test_successful_action_is_not_removed_as_empty(tmp_path):
    host,owner,runtime,backend,claims,callsite,scope,intent = _callsite(tmp_path)
    try:
        observation,cid = _pending(callsite,intent)
        callsite.decide_grounded_confirmation(confirmation_id=cid,decision='approved')
        result = callsite.consume_grounded_confirmation(confirmation_id=cid)
        assert result.outcome == 'ACTION_RECORDED'
        callsite._close_empty_child_after_terminal_claim(confirmation_id=cid)
        segment = host.learning_segments.get(**scope)
        child = segment['children'][0]
        assert child['phase'] == 'bound'
        ledger = host.learning_segments.recorder.get_learning_session(learning_session_id=child['learning_session_id'])
        assert len(ledger['events']) == 1
        assert len(backend.commands) == 1
    finally:
        _close(host,runtime)


def test_uncertain_dispatch_preserves_child_and_recovery(tmp_path,monkeypatch):
    host,owner,runtime,backend,claims,callsite,scope,intent = _callsite(tmp_path)
    try:
        observation,cid = _pending(callsite,intent)
        callsite.decide_grounded_confirmation(confirmation_id=cid,decision='approved')
        original = claims.mark_fresh_dispatch_started
        def lost(*args,**kwargs):
            original(*args,**kwargs)
            raise OSError('synthetic dispatch acknowledgement loss')
        monkeypatch.setattr(claims,'mark_fresh_dispatch_started',lost)
        result = callsite.consume_grounded_confirmation(confirmation_id=cid)
        assert result.status == 'RECOVERY_REQUIRED'
        callsite.cancel_grounded_review(session_id=observation.session_id)
        assert host.learning_segments.get(**scope)['children'][0]['phase'] == 'bound'
        assert claims.get_for_grounded_confirmation(confirmation_id=cid).recovery_required
        assert backend.commands == []
    finally:
        _close(host,runtime)


@pytest.mark.parametrize('mutation',['session','observation','recovery','confirmation'])
def test_only_owned_terminal_claim_can_sync_child(tmp_path,monkeypatch,mutation):
    host,owner,runtime,backend,claims,callsite,scope,intent = _callsite(tmp_path)
    try:
        observation,cid = _pending(callsite,intent)
        runtime.cancel_grounded_review(session_id=observation.session_id)
        claim = claims.get_for_grounded_confirmation(confirmation_id=cid)
        if mutation in {'session','observation'}:
            field = 'session_id' if mutation == 'session' else 'observation_id'
            fact = FreshLearningClaimObservation.from_dict({**claim.observation.to_dict(),field:'foreign-owned-id'})
            claim = replace(claim,observation=fact)
        if mutation == 'recovery':
            claim = replace(claim,recovery_required=True)
        monkeypatch.setattr(claims,'find_for_observation',lambda **_:claim)
        callsite._close_empty_child_after_terminal_claim(confirmation_id='foreign' if mutation=='confirmation' else cid)
        assert host.learning_segments.get(**scope)['children'][0]['phase'] == 'bound'
        assert backend.commands == []
    finally:
        _close(host,runtime)
