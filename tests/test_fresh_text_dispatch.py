"""首次填写复用生产后端适配器；仅系统输入供应方为合成边界。"""

from contextlib import contextmanager
from dataclasses import replace

import pytest

from app.agent.desktop_backend import ExistingWindowsBackendAdapter
from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.live_controller import LiveControllerDecision
from app.core.runtime_input_authority import runtime_backend_input_is_active
from tests.test_fresh_dispatch_graph import _Visible
from tests.test_fresh_text_confirmation import _text_runtime


class _Input:
    def __init__(self, reader):
        self.reader = reader
        self.calls = []
        self.fault = None

    def type_text(self, **kwargs):
        assert runtime_backend_input_is_active()
        self.calls.append(kwargs)
        guard = kwargs['field_guard']
        guard.validate_command(text=kwargs['text'], clear_existing=kwargs['clear_existing'],
            window_handle=4242, click_point=(kwargs['x'], kwargs['y']))
        if self.fault == 'late_value_drift':
            self.reader.value = 'changed after approval'
        guard.verify_before_selection()
        if kwargs['clear_existing']:
            self.reader.selection = (0, len(self.reader.value))
        guard.verify_before_paste()
        self.reader.value = 'wrong output' if self.fault == 'wrong_value' else guard.expectation.expected_value
        self.reader.selection = (len(self.reader.value), len(self.reader.value))
        if self.fault == 'lost_response':
            raise OSError('isolated input response loss')
        return {'typed': True, 'window_handle': 4242, 'text_length': len(kwargs['text']),
            'click_before_typing': kwargs['click_before_typing'], 'clear_existing': kwargs['clear_existing'],
            'submit': False, 'restore_clipboard': True, 'clipboard_restore_status': 'restored',
            'clipboard_verified_before_paste': True}


@contextmanager
def _ready_text(root, kind='literal', *, clear=True):
    with _text_runtime(root, kind, clear=clear) as (host, owner, runtime, _backend, claims, old, intent, params):
        runtime.cancel_session_preparation(preparation_id='fresh.text.confirmation')
        runtime.set_action_learning_recorder(host.fresh_learning.segments.recorder)
        runtime._window_visibility_checker = _Visible()
        native_input = _Input(owner._text_field_reader)
        runtime._backend = ExistingWindowsBackendAdapter(input_controller=native_input,
            window_manager=owner._window_manager, post_dispatch_settle_seconds=0)
        session = runtime.start_session()
        scope = {key: runtime._binding.source.reference()[key] for key in ('connection_id', 'task_id', 'segment_id')}
        host.fresh_learning.segments.attach_runtime(**scope, runtime_session_id=session.session_id)
        fresh_intent = FreshLearningIntent.from_dict({**intent.to_dict(), 'session_id': session.session_id,
            'observation_id': session.current_observation.observation_id})
        try:
            claim = runtime.request_grounded_confirmation(fresh_intent.to_dict(), target_process_id=9001, text_input=params)
            assert not isinstance(claim, LiveControllerDecision), claim
            confirmation_id = claim.grounded_confirmation.confirmation_id
            approved = runtime.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision='approved')
            assert approved.phase == 'grounded_confirmation_approved'
            yield host, owner, runtime, native_input, claims, session, scope, confirmation_id, params
        finally:
            if session.session_id in runtime._grounded_publications:
                runtime.cancel_grounded_review(session_id=session.session_id)
            elif session.session_id in runtime._sessions:
                runtime.abandon_session(session_id=session.session_id)


@pytest.mark.parametrize('kind,clear', [('literal', True), ('variable', True), ('variable', False)])
def test_fresh_fill_records_verified_value_once_and_projects_learning_graph(tmp_path, kind, clear):
    with _ready_text(tmp_path, kind, clear=clear) as (host, owner, runtime, native_input, claims, session, scope, cid, params):
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.outcome == 'ACTION_RECORDED' and result.effect_status == 'verified'
        assert len(native_input.calls) == 1
        assert native_input.calls[0]['submit'] is False
        assert native_input.calls[0]['restore_clipboard'] is True
        proof = result.evidence.text_field_verification
        assert proof['status'] == 'verified'
        assert proof['expected']['before']['capture_id'] != proof['actual']['capture_id']
        record = claims.load_terminal_receipt_record(session_id=session.session_id,
            observation_id=result.observation_id)
        assert proof['actual']['capture_id'] == record.next_observation.to_dict()['capture']['capture_id']
        assert runtime.consume_grounded_confirmation(confirmation_id=cid) == result
        assert len(native_input.calls) == 1
        segment = host.fresh_learning.segments.get(**scope)
        child = segment['children'][0]
        learned = host.fresh_learning.segments.recorder.get_learning_session(learning_session_id=child['learning_session_id'])
        event = next(iter(learned['events'].values()))
        assert learned['recording_gaps'] == []
        assert event['before']['text_parameters_ref'] == result.evidence.text_parameters_ref
        assert event['terminal']['effect_status'] == 'verified'
        synced = host.fresh_learning.sync_actions(**scope)
        graph = host.fresh_learning.facade.load_graph_revision(synced['logical_workflow_id'])
        assert len(graph['graph']['edges']) == 1
        assert session.session_id not in runtime._sessions


def test_field_value_changed_after_preview_is_rejected_before_input(tmp_path):
    with _ready_text(tmp_path) as (host, owner, runtime, native_input, claims, session, scope, cid, params):
        owner._text_field_reader.value = 'new human value'
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert isinstance(result, LiveControllerDecision) and result.reason_code == 'grounded_confirmation_stale'
        assert native_input.calls == []
        assert claims.get_for_grounded_confirmation(confirmation_id=cid).phase == 'grounded_confirmation_closed'


@pytest.mark.parametrize('persistent', [False, True])
def test_text_last_capture_requires_exact_pixels_after_bounded_wait(tmp_path, monkeypatch, persistent):
    from PIL import Image

    with _ready_text(tmp_path) as (host, owner, runtime, native_input, claims, session, scope, cid, params):
        observe = owner.observe_for_action
        capture = owner._screenshot_service.capture_window
        started = False
        probes = []
        def capture_pixels(**kwargs):
            result = capture(**kwargs)
            if started and not native_input.calls:
                probes.append(1)
                if persistent or len(probes) == 1:
                    with Image.open(owner._screenshot_service.path) as original:
                        changed = Image.new('RGB', original.size, 'black')
                    changed.save(owner._screenshot_service.path)
            return result
        def recognized(**kwargs):
            nonlocal started
            bundle = observe(**kwargs)
            started = True
            return bundle
        monkeypatch.setattr(owner._screenshot_service, 'capture_window', capture_pixels)
        monkeypatch.setattr(owner, 'observe_for_action', recognized)
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        if persistent:
            assert isinstance(result, LiveControllerDecision)
            assert result.reason_code == 'grounded_confirmation_stale'
            assert native_input.calls == [] and len(probes) == 7
        else:
            assert result.outcome == 'ACTION_RECORDED' and result.effect_status == 'verified'
            assert len(native_input.calls) == 1 and len(probes) == 2


@pytest.mark.parametrize('fault,effect,outcome', [
    ('wrong_value', 'not_verified', 'ACTION_RECORDED'),
    ('late_value_drift', 'not_verified', 'EXECUTION_UNKNOWN'),
    ('lost_response', 'not_verified', 'EXECUTION_UNKNOWN'),
])
def test_input_result_is_not_assumed_verified_or_retried(tmp_path, fault, effect, outcome):
    with _ready_text(tmp_path) as (host, owner, runtime, native_input, claims, session, scope, cid, params):
        native_input.fault = fault
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.effect_status == effect and result.outcome == outcome
        assert runtime.consume_grounded_confirmation(confirmation_id=cid) == result
        assert len(native_input.calls) == 1


@pytest.mark.parametrize('fault', ['capture_missing', 'field_missing', 'different_field'])
def test_post_input_capture_and_field_failures_stay_unverified_without_retry(tmp_path, monkeypatch, fault):
    with _ready_text(tmp_path) as (host, owner, runtime, native_input, claims, session, scope, cid, params):
        if fault == 'capture_missing':
            original = owner.observe
            def observe(**kwargs):
                if native_input.calls:
                    raise OSError('post-capture failure')
                return original(**kwargs)
            monkeypatch.setattr(owner, 'observe', observe)
        elif fault == 'field_missing':
            def read_after(**kwargs):
                raise ValueError('post-field failure')
            monkeypatch.setattr(owner, 'read_text_field_after', read_after)
        else:
            original = owner.read_text_field_after
            def read_after(**kwargs):
                actual = original(**kwargs)
                return replace(actual, identity=replace(actual.identity, runtime_id=(42, 99)))
            monkeypatch.setattr(owner, 'read_text_field_after', read_after)
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.effect_status == 'not_verified'
        assert result.outcome == ('OBSERVATION_FAILED' if fault == 'capture_missing' else 'ACTION_RECORDED')
        assert runtime.consume_grounded_confirmation(confirmation_id=cid) == result
        assert len(native_input.calls) == 1


def test_terminal_response_loss_reloads_same_text_proof_without_second_input(tmp_path, monkeypatch):
    with _ready_text(tmp_path) as (host, owner, runtime, native_input, claims, session, scope, cid, params):
        persist = claims.persist_fresh_terminal
        def lost(*args, **kwargs):
            persist(*args, **kwargs)
            raise OSError('lost terminal response')
        monkeypatch.setattr(claims, 'persist_fresh_terminal', lost)
        first = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert isinstance(first, LiveControllerDecision) and first.reason_code == 'fresh_receipt_persistence_failed'
        second = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert second.effect_status == 'verified'
        assert len(native_input.calls) == 1


def test_receipt_cannot_replace_authoritative_text_expectation_or_after_capture(tmp_path):
    from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
    from copy import deepcopy

    with _ready_text(tmp_path) as (host, owner, runtime, native_input, claims, session, scope, cid, params):
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        record = claims.load_terminal_receipt_record(session_id=session.session_id, observation_id=result.observation_id)
        for case in ('expected', 'after'):
            payload = deepcopy(result.model_dump(mode='json'))
            proof = payload['evidence']['text_field_verification']
            if case == 'expected':
                proof['expected']['before']['read_id'] = 'other.read'
            else:
                proof['actual']['capture_id'] = 'another.capture'
            altered = RuntimeFreshResultReceipt.from_dict(payload)
            with pytest.raises(RuntimeIntentClaimStoreError):
                claims.persist_fresh_terminal(altered, record.backend_receipt, next_observation=record.next_observation)
        assert len(native_input.calls) == 1
