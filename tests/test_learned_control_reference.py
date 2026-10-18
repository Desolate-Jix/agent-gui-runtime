"""新原生界面的确切控件引用，不借用其他版本或旧记忆库。"""

from copy import deepcopy
from uuid import uuid4

import pytest

from tests.test_fresh_learning_action_preview import _setup


def _close(host, runtime, session):
    try:
        if session.session_id in runtime._grounded_publications:
            runtime.cancel_grounded_review(session_id=session.session_id)
        else:
            runtime.abandon_session(session_id=session.session_id)
    finally:
        host.close()


def _saved(host, source):
    ref = source.reference()
    first = host.facade.import_interface_content(ref['task_id'], ref['batch_id'], 'observed-screen')
    region = {'region_id': 'region-user-' + str(uuid4()), 'bbox': [10, 10, 120, 40], 'name': '详情按钮', 'kind': 'button',
              'meaning': '打开详情', 'recognition_text': 'View details'}
    saved = host.facade.save_interface_content(first['interface_id'], first['revision'],
        first['content_sha256'], {'regions': [region]}, 'learned-control-save')
    control = {'interface_id': saved['interface_id'], 'version_id': saved['version_id'],
               'region_id': saved['content']['regions'][0]['region_id']}
    return first, saved, control


def test_joint_exact_version_resolution_and_current_source(tmp_path):
    from app.agent.learned_control_reference import resolve_learned_control
    host, _, runtime, backend, _, source, session, _ = _setup(tmp_path)
    try:
        first, saved, control = _saved(host, source)
        resolved = resolve_learned_control(host.fresh_learning, source.reference(), control)
        assert resolved['reference'] == control
        assert resolved['content_sha256'] == saved['content_sha256']
        assert resolved['region'] == saved['content']['regions'][0]
        assert resolved['application_identity'] == source.reference()['application_identity']
        assert backend.commands == []
        with pytest.raises(ValueError, match='learned control'):
            resolve_learned_control(host.fresh_learning, source.reference(),
                {**control, 'version_id': first['version_id']})
        with pytest.raises(ValueError, match='learned control'):
            resolve_learned_control(host.fresh_learning, {**source.reference(), 'task_id': 'foreign'}, control)
        with pytest.raises(ValueError, match='learned control'):
            resolve_learned_control(host.fresh_learning, {**source.reference(),
                'application_identity': {'kind': 'web', 'canonical_origin': 'https://different.example'}}, control)
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def test_saved_reference_is_bound_into_normal_preview_and_old_version_remains_pinned(tmp_path):
    from app.agent.fresh_learning_action_contracts import FreshLearningIntent
    from app.agent.learned_control_reference import resolve_learned_control
    from app.agent.live_controller import LiveControllerDecision
    host, _, runtime, backend, _, source, session, intent = _setup(tmp_path)
    try:
        _, saved, control = _saved(host, source)
        binding = resolve_learned_control(host.fresh_learning, source.reference(), control)
        payload = {**intent.to_dict(), 'learned_control': binding}
        assert FreshLearningIntent.from_dict(payload).to_dict() == payload
        host.facade.save_interface_content(saved['interface_id'], saved['revision'], saved['content_sha256'],
            {'regions': [{**saved['content']['regions'][0], 'recognition_text': 'Different control'}]}, 'v3')
        prepared = runtime._prepare_fresh_grounded_review(payload, target_process_id=9001)
        assert not isinstance(prepared, LiveControllerDecision), prepared
        assert prepared.preview.to_dict()['intent']['learned_control'] == binding
        from app.desktop_review.window import ensure_application
        from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget
        application = ensure_application()
        widget = GroundedPreviewWidget()
        try:
            claim = runtime.request_grounded_confirmation(payload, target_process_id=9001)
            assert not isinstance(claim, LiveControllerDecision), claim
            grounded = claim.grounded_confirmation
            view = {'phase': 'pending_review', 'confirmation_id': grounded.confirmation_id,
                'preview': grounded.preview.to_dict(),
                'requested_at': grounded.requested_at.isoformat().replace('+00:00', 'Z'),
                'expires_at': grounded.expires_at.isoformat().replace('+00:00', 'Z'),
                'owner_is_current': grounded.owner_is_current,
                'png_bytes': runtime.get_local_grounded_image(confirmation_id=grounded.confirmation_id),
                'source_kind': 'fresh_learning'}
            widget.set_review(view)
            assert control['version_id'] in widget.metadata_text.toPlainText()
            assert saved['content']['regions'][0]['name'] in widget.metadata_text.toPlainText()
        finally:
            widget.close()
        assert backend.commands == []
        mutated = deepcopy(payload)
        mutated['learned_control']['region']['recognition_text'] = 'Invented'
        with pytest.raises(ValueError):
            FreshLearningIntent.from_dict(mutated)
        from app.agent.fresh_learning_action_contracts import payload_sha256
        mutated['learned_control']['binding_sha256'] = payload_sha256({
            k: v for k, v in mutated['learned_control'].items() if k != 'binding_sha256'})
        # 即使重新计算公开摘要，也不能伪造原生库中的确切内容。
        assert runtime._prepare_fresh_grounded_review(mutated, target_process_id=9001).reason_code == 'invalid_intent'
    finally:
        _close(host, runtime, session)


@pytest.mark.parametrize('case', ['duplicate', 'no_text', 'old_position_only'])
def test_current_grounding_requires_unique_text_not_saved_coordinates(tmp_path, case):
    from app.agent.learned_control_reference import resolve_learned_control, validate_current_learned_control
    from app.agent.fresh_learning_action_contracts import payload_sha256
    from app.agent.fresh_learning_action_preview import _parse_projected_recognition
    host, _, runtime, backend, _, source, session, intent = _setup(tmp_path)
    try:
        _, _, selected = _saved(host, source)
        binding = resolve_learned_control(host.fresh_learning, source.reference(), selected)
        preview = runtime._prepare_fresh_grounded_review(intent.to_dict(), target_process_id=9001).preview.to_dict()
        evidence, uia = preview['observation_evidence'], preview['uia_snapshot']
        candidates, locals_ = _parse_projected_recognition(evidence['recognition']['result'])
        candidate, local = candidates.candidates[0], locals_.results[0]
        if case == 'duplicate':
            duplicate = deepcopy(uia['controls'][0])
            duplicate['control_id'] = 'another-detail'
            uia['controls'].append(duplicate)
        elif case == 'no_text':
            binding['region']['recognition_text'] = ''
            binding['binding_sha256'] = payload_sha256({k: v for k, v in binding.items() if k != 'binding_sha256'})
        else:
            uia['controls'][0]['name'] = 'Unrelated control'
        with pytest.raises(ValueError, match='learned control'):
            validate_current_learned_control(binding, candidate, local, uia, evidence['application'])
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def test_current_target_cannot_drift_from_learned_control(tmp_path):
    from app.agent.learned_control_reference import resolve_learned_control
    from app.agent.live_controller import LiveControllerDecision
    host, _, runtime, backend, _, source, session, intent = _setup(tmp_path)
    try:
        _, saved, control = _saved(host, source)
        updated = host.facade.save_interface_content(saved['interface_id'], saved['revision'],
            saved['content_sha256'], {'regions': [{**saved['content']['regions'][0],
            'recognition_text': 'A different button'}]}, 'changed-label')
        control['version_id'] = updated['version_id']
        binding = resolve_learned_control(host.fresh_learning, source.reference(), control)
        result = runtime._prepare_fresh_grounded_review({**intent.to_dict(), 'learned_control': binding},
                                                       target_process_id=9001)
        assert isinstance(result, LiveControllerDecision)
        assert result.status == 'REJECTED'
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def test_pinned_memory_failure_after_final_capture_stops_dispatch(tmp_path, monkeypatch):
    import json
    from tests.test_fresh_agent_stdio import _rig
    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        service, token = host._service, connection['token']
        prepared = service.agent_call(token, 'prepare_fresh_learning_runtime', {
            'segment_id': segment['segment_id'], 'batch_id': staged['batch_id'], 'idempotency_key': 'last-check'})
        _, _, selected = _saved(host, instances[0][1]._binding.source)
        service.agent_call(token, 'request_fresh_learning_action', {
            'segment_id': segment['segment_id'], 'preparation_id': prepared['preparation_id'],
            'intent_id': 'intent.last-check', 'action_id': 'action.view', 'semantic_action': 'open_detail',
            'goal': 'View details', 'learned_control': selected})
        view = coordinator.current_fresh_review()
        coordinator.approve(confirmation_id=view['confirmation_id'], preview_content_sha256=view['preview']['preview_sha256'])
        reader = host.facade.get_interface_memory
        runtime = instances[0][1]
        pin_capture = runtime._pin_fresh_learning_capture
        def fail_after_capture(*args, **kwargs):
            result = pin_capture(*args, **kwargs)
            def unavailable(*args, **keys):
                raise ValueError('simulated pinned memory failure')
            monkeypatch.setattr(host.facade, 'get_interface_memory', unavailable)
            return result
        monkeypatch.setattr(runtime, '_pin_fresh_learning_capture', fail_after_capture)
        try:
            result = coordinator.execute(confirmation_id=view['confirmation_id'])
            assert 'stale' in json.dumps(result)
            assert instances[0][2].commands == []
        finally:
            monkeypatch.setattr(host.facade, 'get_interface_memory', reader)
            monkeypatch.setattr(runtime, '_pin_fresh_learning_capture', pin_capture)
