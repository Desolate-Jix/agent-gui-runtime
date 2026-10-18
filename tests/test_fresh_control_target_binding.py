"""学习版本到当前控件定位的约束；所有窗口、截图、识别和输入均为隔离替身。"""

from copy import deepcopy

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.learned_control_reference import (
    recognition_target_from_learned_control, resolve_learned_control,
)
from app.agent.live_controller import LiveControllerDecision
from tests.test_fresh_learning_action_preview import _recognize, _setup
from tests.test_learned_control_reference import _close, _saved


def _binding(host, source):
    _, _, selection = _saved(host, source)
    return resolve_learned_control(host.fresh_learning, source.reference(), selection)


def test_target_derived_from_pinned_text_role_hash_not_meaning_or_coordinates(tmp_path):
    host, _, runtime, backend, _, source, session, _ = _setup(tmp_path)
    try:
        binding = _binding(host, source)
        target = recognition_target_from_learned_control(binding, semantic_action='open_detail')
        assert target == {
            'contract_version': 'recognition_control_target_v1', 'label': 'View details',
            'role': 'button', 'source_binding_sha256': binding['binding_sha256'],
        }
        mutated = deepcopy(binding)
        mutated['region']['recognition_text'] = 'Pay now'
        with pytest.raises(ValueError, match='digest'):
            recognition_target_from_learned_control(mutated, semantic_action='open_detail')
        assert recognition_target_from_learned_control(binding, semantic_action='fill_field') is None
        assert recognition_target_from_learned_control(binding, semantic_action='scroll_region') is None
        assert recognition_target_from_learned_control(None, semantic_action='open_detail') is None
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def test_prepare_and_consume_rederive_same_target_from_persisted_claim(tmp_path):
    from tests.test_fresh_agent_stdio import _rig
    seen = []
    def runner(**kwargs):
        seen.append(deepcopy(kwargs.get('control_target')))
        return _recognize(**kwargs)
    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        service, token = host._service, connection['token']
        prepared = service.agent_call(token, 'prepare_fresh_learning_runtime', {
            'segment_id': segment['segment_id'], 'batch_id': staged['batch_id'], 'idempotency_key': 'target.rederive'})
        _, runtime, backend, owner = instances[0]
        owner._recognition_runner = runner
        _, _, selected = _saved(host, runtime._binding.source)
        service.agent_call(token, 'request_fresh_learning_action', {
            'segment_id': segment['segment_id'], 'preparation_id': prepared['preparation_id'],
            'intent_id': 'intent.target', 'action_id': 'action.view', 'semantic_action': 'open_detail',
            'goal': 'View details', 'learned_control': selected})
        view = coordinator.current_fresh_review()
        cid = view['confirmation_id']
        claims = runtime._intent_claim_store
        from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
        from app.agent.runtime_receipt_store import RuntimeReceiptStore
        reopened = RuntimeIntentClaimStore(project_root=claims.project_root,
            receipt_store=RuntimeReceiptStore(project_root=claims.project_root))
        reloaded = reopened.get_for_grounded_confirmation(confirmation_id=cid)
        persisted = reloaded.grounded_confirmation.preview.to_dict()['intent']
        restored = FreshLearningIntent.from_dict(persisted)
        expected = recognition_target_from_learned_control(restored.learned_control,
            semantic_action=restored.semantic_action)
        assert seen == [expected]
        coordinator.approve(confirmation_id=cid, preview_content_sha256=view['preview']['preview_sha256'])
        result = coordinator.execute(confirmation_id=cid)
        assert result['kind'] == 'receipt', result
        assert seen == [expected, expected]
        assert len(backend.commands) == 1
        coordinator.cancel()


@pytest.mark.parametrize('mutation', ['drop', 'label', 'role', 'source', 'extra'])
def test_runner_cannot_substitute_or_omit_bound_target(tmp_path, mutation):
    def runner(**kwargs):
        result = _recognize(**kwargs)
        target = result['candidate_result']['summary'].get('control_target')
        if target is not None:
            if mutation == 'drop':
                result['candidate_result']['summary'].pop('control_target')
            elif mutation == 'extra':
                target['bbox'] = [1, 2, 3, 4]
            else:
                key = {'label': 'label', 'role': 'role', 'source': 'source_binding_sha256'}[mutation]
                target[key] = {'label': 'Different', 'role': 'link', 'source': 'f' * 64}[mutation]
        return result
    host, _, runtime, backend, _, source, session, intent = _setup(tmp_path, runner=runner)
    try:
        binding = _binding(host, source)
        rejected = runtime._prepare_fresh_grounded_review({**intent.to_dict(), 'learned_control': binding},
            target_process_id=9001)
        assert isinstance(rejected, LiveControllerDecision) and rejected.status == 'REJECTED'
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def test_semantic_action_goal_stays_descriptive_while_target_is_pure_label(tmp_path):
    def runner(**kwargs):
        # 替身只根据独立标签产出控件证据，不以动作长句生成控件名称。
        result = _recognize(**kwargs)
        if kwargs.get('control_target'):
            label = kwargs['control_target']['label']
            candidate = result['candidate_result']['candidates'][0]
            candidate.update(label=label, text=label)
            candidate['element'].update(label=label, text=label)
            result['narrow_search_result']['results'][0]['matched_text'] = label
        return result
    host, _, runtime, backend, _, source, session, intent = _setup(tmp_path, runner=runner)
    try:
        goal = 'Click View details to inspect the result for OpenStreetMap'
        payload = {**intent.to_dict(), 'goal': goal, 'learned_control': _binding(host, source)}
        prepared = runtime._prepare_fresh_grounded_review(payload, target_process_id=9001)
        assert not isinstance(prepared, LiveControllerDecision), prepared
        evidence = prepared.preview.to_dict()['observation_evidence']['recognition']
        assert evidence['goal'] == evidence['result']['goal'] == goal
        assert evidence['result']['candidate_result']['summary']['control_target']['label'] == 'View details'
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def test_persisted_preview_rejects_rehashed_foreign_target(tmp_path):
    from app.agent.fresh_learning_action_preview import _decision_and_risk
    host, _, runtime, backend, _, source, session, intent = _setup(tmp_path)
    try:
        intent = FreshLearningIntent.from_dict({**intent.to_dict(), 'learned_control': _binding(host, source)})
        prepared = runtime._prepare_fresh_grounded_review(intent.to_dict(), target_process_id=9001)
        data = prepared.preview.to_dict()
        target = data['observation_evidence']['recognition']['result']['candidate_result']['summary']['control_target']
        target['source_binding_sha256'] = 'f' * 64
        with pytest.raises(ValueError, match='control target'):
            _decision_and_risk(data['observation_evidence'], data['uia_snapshot'], intent)
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def _rehash_preview(data):
    from app.agent.fresh_learning_action_contracts import payload_sha256, canonical_json_bytes
    evidence = data['observation_evidence']
    data['capture_source']['content_sha256'] = payload_sha256({
        'evidence_json': canonical_json_bytes(evidence).decode('utf-8'),
        'screenshot_sha256': evidence['capture']['screenshot_sha256']})
    data['preview_sha256'] = payload_sha256({k: v for k, v in data.items() if k != 'preview_sha256'})
    return data


def test_v2_missing_target_cannot_pass_cold_parse_even_with_recomputed_digests(tmp_path):
    from app.agent.fresh_learning_action_preview import FreshLearningActionPreview
    host, _, runtime, backend, _, source, session, intent = _setup(tmp_path)
    try:
        intent = FreshLearningIntent.from_dict({**intent.to_dict(), 'learned_control': _binding(host, source)})
        data = runtime._prepare_fresh_grounded_review(intent.to_dict(), target_process_id=9001).preview.to_dict()
        assert data['contract_version'] == 'fresh_learning_action_preview_v2'
        data['observation_evidence']['recognition']['result']['candidate_result']['summary'].pop('control_target')
        with pytest.raises(ValueError, match='control target'):
            FreshLearningActionPreview.from_dict(_rehash_preview(data))
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def test_legacy_preview_stays_readable_but_cannot_approve_new_target_contract(tmp_path):
    from app.agent.fresh_learning_action_preview import FreshLearningActionPreview, validate_fresh_execution_preview
    host, _, runtime, backend, _, source, session, intent = _setup(tmp_path)
    try:
        intent = FreshLearningIntent.from_dict({**intent.to_dict(), 'learned_control': _binding(host, source)})
        legacy = runtime._prepare_fresh_grounded_review(intent.to_dict(), target_process_id=9001).preview.to_dict()
        legacy['contract_version'] = 'fresh_learning_action_preview_v1'
        legacy['observation_evidence']['recognition']['result']['candidate_result']['summary'].pop('control_target')
        legacy = _rehash_preview(legacy)
        assert FreshLearningActionPreview.from_dict(legacy).to_dict() == legacy
        current = runtime._prepare_fresh_grounded_review(intent.to_dict(), target_process_id=9001).preview
        with pytest.raises(ValueError, match='drifted'):
            validate_fresh_execution_preview(legacy, current)
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def test_unsupported_kind_rejects_instead_of_silently_dropping_selector(tmp_path):
    from app.agent.fresh_learning_action_contracts import payload_sha256
    host, _, runtime, backend, _, source, session, _ = _setup(tmp_path)
    try:
        binding = _binding(host, source)
        for kind in ('unknown', 'text', 'image', 'container', 'other'):
            value = deepcopy(binding)
            value['region']['kind'] = kind
            value['binding_sha256'] = payload_sha256({k: v for k, v in value.items() if k != 'binding_sha256'})
            with pytest.raises(ValueError, match='kind is not supported'):
                recognition_target_from_learned_control(value, semantic_action='open_detail')
        value['region']['kind'] = 'menu'
        value['binding_sha256'] = payload_sha256({k: v for k, v in value.items() if k != 'binding_sha256'})
        assert recognition_target_from_learned_control(value, semantic_action='open_detail')['role'] == 'menu_item'
        assert backend.commands == []
    finally:
        _close(host, runtime, session)


def test_production_readonly_adapter_keeps_goal_and_passes_only_target_metadata(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.agent.live_runtime_composition import _run_existing_read_only_recognition
    from app.api import vision
    from app.vision.configuration import load_formal_vision_configuration
    from tests.test_native_vision_configuration import _config
    from tests.test_control_target_vista_path import TARGET, GOAL
    config = load_formal_vision_configuration(_config(tmp_path / 'vision.json', 'offline-model'))
    seen = []
    def api(request):
        seen.append(request)
        return SimpleNamespace(model_dump=lambda **kwargs: {'success': True,
            'data': {'result': {'image_path': request.image_path}}})
    monkeypatch.setattr(vision, 'recognition_plan', api)
    path = str(tmp_path / 'synthetic.png')
    _run_existing_read_only_recognition(image_path=path, goal=GOAL, provider_mode=config.mode,
        uia_snapshot={}, vision_configuration=config, control_target=TARGET)
    assert len(seen) == 1 and seen[0].goal == GOAL
    assert seen[0].metadata == {'control_target': TARGET}
    assert seen[0].write_policy.model_dump() == {'path_graph': False, 'element_memory': False, 'trace': False}
