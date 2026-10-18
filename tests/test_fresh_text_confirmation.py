"""首次填写走实际控制器和持久确认；不调用系统输入。"""

from contextlib import contextmanager
from dataclasses import replace
import json

import pytest

from app.agent.live_controller import LiveControllerDecision
from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from tests.test_fresh_text_preview import _native_owner, _parameters, _intent_payload
from tests.text_field_fixture_support import SyntheticTextFieldReader
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_runtime_session import _runtime


@contextmanager
def _text_runtime(root, kind='literal', *, clear=True):
    owner = _native_owner(root / 'capture')
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    host, connection, segment, _packet, _args, staged = _stage(root, packet)
    owner.project_root = host.fresh_learning.archive.project_root
    owner._text_field_reader = SyntheticTextFieldReader()
    runtime, backend, claims, source = _runtime(host, connection, segment, staged, observation_owner=owner)
    session = runtime.start_session_preparation(preparation_id='fresh.text.confirmation')
    params = _parameters(kind, clear=clear)
    try:
        intent = FreshLearningIntent.from_dict({**_intent_payload(params), 'session_id': session.session_id,
            'observation_id': session.current_observation.observation_id, 'source_sha256': source.reference()['source_sha256']})
        yield host, owner, runtime, backend, claims, session, intent, params
    finally:
        if session.session_id in runtime._grounded_publications:
            runtime.cancel_grounded_review(session_id=session.session_id)
        elif session.session_id in runtime._sessions:
            runtime.abandon_session(session_id=session.session_id)
        host.close()


@pytest.mark.parametrize('kind', ['literal', 'variable'])
def test_text_confirmation_retains_private_values_but_persists_only_references(tmp_path, kind):
    with _text_runtime(tmp_path, kind) as (_, owner, runtime, backend, claims, session, intent, params):
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001, text_input=params)
        assert not isinstance(claim, LiveControllerDecision), claim
        assert claim.phase == 'grounded_confirmation_pending'
        confirmation_id = claim.grounded_confirmation.confirmation_id
        assert runtime.get_local_grounded_text_input(confirmation_id=confirmation_id) == params
        expected = runtime.get_local_grounded_text_field_expectation(confirmation_id=confirmation_id)
        assert expected.expected_value == params.text
        assert expected.before.value == owner._text_field_reader.value
        assert params.text not in json.dumps(claim.grounded_confirmation.preview.to_dict(), ensure_ascii=False)
        again = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert again == claim
        assert len(owner._text_field_reader.calls) == 1
        assert backend.attempt_count == 0
        assert list(claims.dispatch_started_root.glob('*.json')) == []
        denied = runtime.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision='denied')
        assert denied.phase == 'grounded_confirmation_denied'
        assert session.session_id not in runtime._sessions


@pytest.mark.parametrize('case', ['missing', 'other_declaration', 'raw_dict'])
def test_invalid_fresh_text_never_captures_or_claims(tmp_path, case):
    with _text_runtime(tmp_path) as (_, owner, runtime, backend, claims, session, intent, params):
        supplied = None if case == 'missing' else _parameters('variable') if case == 'other_declaration' else {'text': params.text}
        before = len(owner._screenshot_service.calls)
        result = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001, text_input=supplied)
        assert isinstance(result, LiveControllerDecision) and result.status == 'REJECTED'
        assert len(owner._screenshot_service.calls) == before
        assert claims.find_for_observation(session_id=session.session_id, observation_id=intent.observation_id) is None
        assert backend.attempt_count == 0


def test_pending_variable_cannot_silently_change_resolved_text(tmp_path):
    with _text_runtime(tmp_path, 'variable') as (_, owner, runtime, backend, claims, session, intent, params):
        first = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001, text_input=params)
        assert not isinstance(first, LiveControllerDecision), first
        conflict = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001,
            text_input=replace(params, text='different value'))
        assert conflict.reason_code == 'grounded_confirmation_request_conflict'
        assert len(owner._text_field_reader.calls) == 1
        assert runtime.get_local_grounded_text_input(confirmation_id=first.grounded_confirmation.confirmation_id) == params
        assert backend.attempt_count == 0


def test_missing_field_provider_does_not_create_pending_text_confirmation(tmp_path):
    with _text_runtime(tmp_path) as (_, owner, runtime, backend, claims, session, intent, params):
        def unavailable(**kwargs):
            raise ValueError('private provider details')
        owner._text_field_reader.read_field = unavailable
        result = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001, text_input=params)
        assert isinstance(result, LiveControllerDecision) and result.status == 'REJECTED'
        assert claims.find_for_observation(session_id=session.session_id, observation_id=intent.observation_id) is None
        assert backend.attempt_count == 0


def test_fresh_insert_preview_uses_current_selection_and_keeps_existing_text(tmp_path):
    with _text_runtime(tmp_path, 'variable', clear=False) as (_, owner, runtime, backend, claims, session, intent, params):
        owner._text_field_reader.value = 'abcXYZdef'
        owner._text_field_reader.selection = (3, 6)
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001, text_input=params)
        assert not isinstance(claim, LiveControllerDecision), claim
        expected = runtime.get_local_grounded_text_field_expectation(confirmation_id=claim.grounded_confirmation.confirmation_id)
        assert expected.expected_value == 'abc' + params.text + 'def'
        assert backend.attempt_count == 0


def test_local_approval_cannot_dispatch_text_without_learning_recording(tmp_path):
    with _text_runtime(tmp_path) as (_, owner, runtime, backend, claims, session, intent, params):
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001, text_input=params)
        assert not isinstance(claim, LiveControllerDecision), claim
        confirmation_id = claim.grounded_confirmation.confirmation_id
        approved = runtime.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision='approved')
        assert approved.phase == 'grounded_confirmation_approved'
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert result.reason_code == 'fresh_learning_recording_required'
        assert backend.attempt_count == 0
        assert list(claims.dispatch_started_root.glob('*.json')) == []
