"""全新合成证据验证策略观察模式，不运行模型或真实输入。"""
from copy import deepcopy

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, payload_sha256
from app.agent.fresh_learning_action_preview import FreshLearningActionPreview, _decision_and_risk
from tests.test_navigation_visual_stability import _fixture, _rehash, _current, _png


def _manual(data):
    from app.agent.automatic_safety_policy import action_selection, automatic_safety_report
    from app.agent.fresh_learning_action_preview import _parse_projected_recognition
    intent = FreshLearningIntent.from_dict(data['intent'])
    decision, risk = _decision_and_risk(data['observation_evidence'], data['uia_snapshot'], intent,
        require_control_target=intent.learned_control is not None, automatic_safety_interception=False)
    candidates, local = _parse_projected_recognition(data['observation_evidence']['recognition']['result'])
    data.update(contract_version='fresh_learning_action_preview_v3', automatic_safety_interception=False,
        pre_click_decision=decision, risk=risk,
        action_selection=action_selection(decision, candidates, local, automatic_safety_interception=False),
        automatic_safety_report=automatic_safety_report(decision, risk))
    return FreshLearningActionPreview.from_dict(_rehash(data))


def _low_score():
    original, png = _fixture()
    data = original.to_dict()
    from app.operation.recognition.schemas import ScoreBreakdown
    candidate = data['observation_evidence']['recognition']['result']['candidate_result']['candidates'][0]
    breakdown = ScoreBreakdown(text_similarity=1)
    candidate['score_breakdown'] = breakdown.to_dict()
    candidate['score'] = breakdown.total()
    return data, png


def test_rejected_score_becomes_retained_warning_not_forged_allowed():
    data, _ = _low_score()
    with pytest.raises(ValueError, match='pre-click gate rejected'):
        _decision_and_risk(data['observation_evidence'], data['uia_snapshot'], FreshLearningIntent.from_dict(data['intent']))
    preview = _manual(data).to_dict()
    assert preview['pre_click_decision']['allowed'] is False
    assert preview['pre_click_decision']['selected_candidate_id'] is None
    assert preview['automatic_safety_report']['would_block'] is True
    assert 'candidate_score_too_low' in preview['automatic_safety_report']['reasons']
    assert preview['action_selection']['selected_click_point'] == {'x': 130, 'y': 75}
    assert preview['artifact_is_authorization'] is False


def test_manual_selection_still_rejects_missing_grounding_and_invalid_geometry():
    for fault in ('point', 'status', 'candidate_id'):
        data, _ = _low_score()
        local = data['observation_evidence']['recognition']['result']['narrow_search_result']['results'][0]
        if fault == 'point':
            local['refined_click_point'] = {'x': 0, 'y': 0}
        elif fault == 'status':
            local['status'] = 'not_found'
        else:
            local['candidate_id'] = 'unrelated'
        with pytest.raises(ValueError):
            _manual(data)


def test_manual_preview_mode_and_selection_are_hash_bound():
    data, _ = _low_score()
    value = _manual(data).to_dict()
    for key, replacement in [('automatic_safety_interception', True), ('action_selection', {})]:
        changed = deepcopy(value)
        changed[key] = replacement
        with pytest.raises(ValueError):
            FreshLearningActionPreview.from_dict(changed)


def test_manual_mode_is_exact_boolean_and_legacy_is_strict():
    from app.agent.automatic_safety_policy import preview_automatic_safety_interception
    original, _ = _fixture()
    assert preview_automatic_safety_interception(original.to_dict()) is True
    for value in (None, 0, 1, '', 'false', []):
        data = original.to_dict()
        data.update(contract_version='fresh_learning_action_preview_v3', automatic_safety_interception=value)
        with pytest.raises((TypeError, ValueError)):
            preview_automatic_safety_interception(data)


def test_manual_pixel_observation_retains_real_hashes_and_cold_mode():
    from app.agent.navigation_visual_stability import NavigationVisualStabilityScope, verify_navigation_visual_stability_reference
    data, png = _low_score()
    approved = _manual(data)
    scope = NavigationVisualStabilityScope(approved, png)
    changed = _png([(x, y) for x in range(240, 340) for y in range(150, 230)])
    current = _current(approved, changed, passive=True)
    proof = scope.validate(current, changed)
    assert proof.to_reference()['changed_pixels'] == 8000
    assert 'manual' in proof.to_reference()['policy']
    verify_navigation_visual_stability_reference(proof.to_reference(), approved.to_dict()['observation_evidence'],
        current, scope.expectation_reference, png, changed)
    wrong_mode = scope.expectation_reference
    wrong_mode['automatic_safety_interception'] = True
    with pytest.raises(ValueError):
        verify_navigation_visual_stability_reference(proof.to_reference(), approved.to_dict()['observation_evidence'],
            current, wrong_mode, png, changed)
    target_changed = _png([(80, 60)])
    target_proof = scope.validate(_current(approved, target_changed), target_changed).to_reference()
    assert target_proof['changed_pixels'] == 1
    assert target_proof['protected_before_sha256'] != target_proof['protected_after_sha256']


def test_manual_safe_point_drift_requires_same_mode_and_unchanged_target():
    from app.agent.fresh_learning_action_preview import validate_fresh_execution_preview
    from app.agent.navigation_visual_stability import NavigationVisualStabilityScope
    from tests.test_navigation_execution_equivalence import _previews
    # 严格导航现按目标大小有界容差，17 px 超出当前 16 px 上限。
    original, current, before_png, after_png = _previews((17, 0))
    manual_before, manual_after = _manual(original.to_dict()), _manual(current.to_dict())
    proof = NavigationVisualStabilityScope(manual_before, before_png).validate(manual_after.to_dict()['observation_evidence'], after_png)
    validate_fresh_execution_preview(manual_before, manual_after, navigation_visual_proof=proof)
    strict_proof = NavigationVisualStabilityScope(original, before_png).validate(current.to_dict()['observation_evidence'], after_png)
    with pytest.raises(ValueError, match='target-adaptive axis bound'):
        validate_fresh_execution_preview(original, current, navigation_visual_proof=strict_proof)
    with pytest.raises(ValueError):
        validate_fresh_execution_preview(original, manual_after, navigation_visual_proof=proof)


def test_risk_advice_is_preserved_not_declared_passed():
    from tests.test_fresh_action_risk import _control
    data, _ = _low_score()
    uia = data['uia_snapshot']
    uia['controls'].append(_control('delete-control', 'Delete item', {'x': 80, 'y': 60, 'w': 100, 'h': 30}))
    uia['control_count'] = len(uia['controls'])
    data['observation_evidence']['uia'].update(control_count=uia['control_count'], snapshot_sha256=payload_sha256(uia))
    preview = _manual(data).to_dict()
    assert preview['risk']['hard_blocked'] is True
    assert 'destructive_delete_target' in preview['risk']['reasons']
    assert preview['automatic_safety_report']['would_block'] is True


def test_live_manual_single_step_retains_warning_receipt_and_cold_proof(tmp_path, monkeypatch):
    from app.agent.live_controller import LiveController
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from tests.test_fresh_navigation_stability import _ready, _alter
    from tests import test_fresh_navigation_stability as rig
    from app.operation.recognition.schemas import ScoreBreakdown
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError
    original_recognize = rig._vista
    def low_recognize(**kwargs):
        value = original_recognize(**kwargs)
        candidate = value['candidate_result']['candidates'][0]
        breakdown = ScoreBreakdown(text_similarity=1)
        candidate.update(score=breakdown.total(), score_breakdown=breakdown.to_dict())
        return value
    monkeypatch.setattr(rig, '_vista', low_recognize)
    original_init = LiveController.__init__
    def initialize(self, **kwargs):
        kwargs['automatic_safety_interception'] = False
        original_init(self, **kwargs)
    monkeypatch.setattr(LiveController, '__init__', initialize)
    with _ready(tmp_path, monkeypatch) as (coordinator, runtime, backend, owner, view):
        assert view['preview']['automatic_safety_interception'] is False
        assert view['preview']['pre_click_decision']['allowed'] is False
        assert view['preview']['automatic_safety_report']['would_block'] is True
        runtime._automatic_safety_interception = True
        _alter(owner, monkeypatch, point_delta=5)
        response = coordinator.execute(confirmation_id=view['confirmation_id'])
        assert response['kind'] == 'receipt', response
        assert response['payload']['gate_status'] == 'manual_confirmed'
        assert response['payload']['contract_version'] == 'runtime_fresh_result_receipt_v2'
        assert len(backend.commands) == 1
        claims = runtime._intent_claim_store
        cold = RuntimeIntentClaimStore(project_root=claims.project_root, receipt_store=claims._receipt_store, create_layout=False)
        assert cold.get_for_grounded_confirmation(confirmation_id=view['confirmation_id']).phase == 'terminal'
        from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt, RuntimeFreshReceiptError
        forged = deepcopy(response['payload'])
        forged['gate_status'] = 'allowed'
        with pytest.raises(RuntimeFreshReceiptError):
            RuntimeFreshResultReceipt.from_dict(forged)
        import json
        from app.agent.fresh_learning_action_contracts import canonical_json_bytes
        from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
        proof_path = claims.root / ('navigation-visual-stability-' + view['confirmation_id'].split('.')[-1] + '.json')
        original_bytes = proof_path.read_bytes()
        try:
            changed = json.loads(original_bytes)
            changed['visibility']['proof']['policy'] = 'open_detail_protected_pixels_v1'
            proof_path.write_bytes(canonical_json_bytes(changed))
            with pytest.raises(RuntimeIntentClaimStoreError):
                cold.get_for_grounded_confirmation(confirmation_id=view['confirmation_id'])
        finally:
            proof_path.write_bytes(original_bytes)
        with pytest.raises(NativeSingleStepCoordinatorError, match='current phase'):
            coordinator.execute(confirmation_id=view['confirmation_id'])
        assert len(backend.commands) == 1


def test_strict_mode_does_not_add_original_bbox_overlap_requirement():
    original, _ = _fixture()
    data = original.to_dict()
    candidate = data['observation_evidence']['recognition']['result']['candidate_result']['candidates'][0]
    candidate['element']['bbox'] = {'x': 200, 'y': 100, 'w': 80, 'h': 30}
    decision, risk = _decision_and_risk(data['observation_evidence'], data['uia_snapshot'],
        FreshLearningIntent.from_dict(data['intent']))
    assert decision['allowed'] is True
    assert risk['hard_blocked'] is False


def test_manual_text_fill_background_changes_and_cold_policy(tmp_path, monkeypatch):
    from PIL import Image
    from app.agent.live_controller import LiveController, LiveControllerDecision
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from tests.test_fresh_text_dispatch import _ready_text
    from tests import test_fresh_text_preview as text_rig
    from app.operation.recognition.schemas import ScoreBreakdown
    original_init, original_recognize = LiveController.__init__, text_rig._text_recognize
    def initialize(self, **kwargs):
        kwargs['automatic_safety_interception'] = False
        original_init(self, **kwargs)
    def low_recognize(**kwargs):
        value = original_recognize(**kwargs)
        candidate = value['candidate_result']['candidates'][0]
        breakdown = ScoreBreakdown(text_similarity=1)
        candidate.update(score=breakdown.total(), score_breakdown=breakdown.to_dict())
        return value
    monkeypatch.setattr(LiveController, '__init__', initialize)
    monkeypatch.setattr(text_rig, '_text_recognize', low_recognize)
    with _ready_text(tmp_path) as (_host, owner, runtime, native_input, claims, _session, _scope, cid, _params):
        capture = owner._screenshot_service.capture_window
        def altered(**kwargs):
            result = capture(**kwargs)
            with Image.open(owner._screenshot_service.path) as source:
                image = source.convert('RGB')
            for x in range(140, 159):
                for y in range(70, 99):
                    image.putpixel((x, y), (0, 0, 0))
            image.save(owner._screenshot_service.path)
            return result
        monkeypatch.setattr(owner._screenshot_service, 'capture_window', altered)
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.gate_status == 'manual_confirmed'
        assert result.effect_status == 'verified'
        assert len(native_input.calls) == 1
        cold = RuntimeIntentClaimStore(project_root=claims.project_root, receipt_store=claims._receipt_store, create_layout=False)
        assert cold.get_for_grounded_confirmation(confirmation_id=cid).phase == 'terminal'


@pytest.mark.parametrize('semantic', ['open_detail', 'back', 'close_modal'])
def test_unlearned_click_modes_record_pixel_and_score_changes_without_policy_bypass(semantic):
    from app.agent.navigation_visual_stability import NavigationVisualStabilityScope
    from app.agent.fresh_learning_action_preview import validate_fresh_execution_preview
    data, before_png = _low_score()
    data['intent'].pop('learned_control')
    data['intent']['semantic_action'] = semantic
    data['observation_evidence']['recognition']['result']['candidate_result']['summary'].pop('control_target')
    before = _manual(data)
    after_png = _png([(80, 60), (130, 75), (270, 200)])
    current_data = before.to_dict()
    current_data['observation_evidence'] = _current(before, after_png)
    current_data['capture_source']['source_id'] = 'e' * 64
    candidate = current_data['observation_evidence']['recognition']['result']['candidate_result']['candidates'][0]
    from app.operation.recognition.schemas import ScoreBreakdown
    breakdown = ScoreBreakdown(text_similarity=1, role_score=1, confidence_score=1)
    candidate.update(score=breakdown.total(), score_breakdown=breakdown.to_dict())
    after = _manual(current_data)
    assert before.to_dict()['pre_click_decision']['allowed'] is False
    assert after.to_dict()['pre_click_decision']['allowed'] is True
    proof = NavigationVisualStabilityScope(before, before_png).validate(after.to_dict()['observation_evidence'], after_png)
    assert proof.to_reference()['changed_pixels'] == 3
    validate_fresh_execution_preview(before, after, navigation_visual_proof=proof)


def test_manual_scroll_uses_same_single_dispatch_with_pixel_observation(tmp_path, monkeypatch):
    from PIL import Image
    from app.agent.live_controller import LiveController, LiveControllerDecision
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from tests.test_fresh_scroll_dispatch import _scroll_runtime
    original_init = LiveController.__init__
    def initialize(self, **kwargs):
        kwargs['automatic_safety_interception'] = False
        original_init(self, **kwargs)
    monkeypatch.setattr(LiveController, '__init__', initialize)
    with _scroll_runtime(tmp_path) as (_host, owner, runtime, claims, native_input, _session, _scope, intent):
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert not isinstance(claim, LiveControllerDecision), claim
        cid = claim.grounded_confirmation.confirmation_id
        runtime.record_grounded_confirmation_decision(confirmation_id=cid, decision='approved')
        capture = owner._screenshot_service.capture_window
        def altered(**kwargs):
            result = capture(**kwargs)
            with Image.open(owner._screenshot_service.path) as source:
                image = source.convert('RGB')
            image.putpixel((60, 30), (0, 0, 0))
            image.save(owner._screenshot_service.path)
            return result
        monkeypatch.setattr(owner._screenshot_service, 'capture_window', altered)
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.gate_status == 'manual_confirmed'
        assert result.action.semantic_action == 'scroll_region'
        assert len(native_input.calls) == 1
        cold = RuntimeIntentClaimStore(project_root=claims.project_root, receipt_store=claims._receipt_store, create_layout=False)
        assert cold.get_for_grounded_confirmation(confirmation_id=cid).phase == 'terminal'
