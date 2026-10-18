"""合成导航复核覆盖轻微远端动画；系统输入始终使用替身。"""
from contextlib import contextmanager
from hashlib import sha1
import json

from PIL import Image
import pytest

from tests import test_fresh_agent_stdio as rig_module
from tests.test_fresh_learning_action_preview import _recognize, _CurrentUIA
from tests.test_formal_fresh_learning_observation import _bound, _WindowManager
from tests.test_learned_control_reference import _saved


class _NavigationUIA(_CurrentUIA):
    def snapshot_window(self, bound):
        result = super().snapshot_window(bound)
        result['controls'][0]['runtime_id'] = [42, 4242, 123]
        return result


def _vista(**kwargs):
    result = _recognize(**kwargs)
    point = result['narrow_search_result']['results'][0]['refined_click_point']
    candidate = result['candidate_result']['candidates'][0]
    candidate['element']['evidence'] = {'vista_direct_identity': {
        'source': 'vista_direct_point_grounding', 'point': dict(point),
        'source_candidate_id': 'vista_direct_' + sha1(
            f"{kwargs['goal']}|{point['x']}|{point['y']}".encode('utf-8')).hexdigest()[:10]}}
    result['narrow_search_result']['results'][0]['coordinate_source'] = 'vista_point_v1_corroborated_by_local_ocr'
    return result


@contextmanager
def _ready(tmp_path, monkeypatch, *, learned=True):
    original = rig_module._owner
    def owner(root, **kwargs):
        kwargs['manager'] = _WindowManager(*[_bound(left=0, top=0, width=400, height=300) for _ in range(160)])
        kwargs['uia'] = _NavigationUIA(width=400, height=300)
        kwargs['runner'] = _vista
        value = original(root, **kwargs)
        value._screenshot_service.width = 400
        value._screenshot_service.height = 300
        return value
    monkeypatch.setattr(rig_module, '_owner', owner)
    with rig_module._rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        service, token = host._service, connection['token']
        prepared = service.agent_call(token, 'prepare_fresh_learning_runtime', {
            'segment_id': segment['segment_id'], 'batch_id': staged['batch_id'], 'idempotency_key': 'nav.stability'})
        _, runtime, backend, observation = instances[0]
        selected = _saved(host, runtime._binding.source)[2] if learned else None
        service.agent_call(token, 'request_fresh_learning_action', {
            'segment_id': segment['segment_id'], 'preparation_id': prepared['preparation_id'],
            'intent_id': 'nav.intent', 'action_id': 'nav.action', 'semantic_action': 'open_detail',
            'goal': 'View details', **({'learned_control': selected} if learned else {})})
        view = coordinator.current_fresh_review()
        coordinator.approve(confirmation_id=view['confirmation_id'], preview_content_sha256=view['preview']['preview_sha256'])
        yield coordinator, runtime, backend, observation, view


def _alter(owner, monkeypatch, *, point_delta=1, pixel=(300, 220), final_only=False, point_axis='y'):
    capture, recognize = owner._screenshot_service.capture_window, owner._recognition_runner
    count = 0
    def changed_capture(**kwargs):
        nonlocal count
        count += 1
        result = capture(**kwargs)
        if pixel is not None and (not final_only or count == 2):
            with Image.open(owner._screenshot_service.path) as source:
                image = source.convert('RGB')
            image.putpixel(pixel, (200, 210, 220))
            image.save(owner._screenshot_service.path)
        return result
    def changed_recognition(**kwargs):
        result = recognize(**kwargs)
        local = result['narrow_search_result']['results'][0]
        point = local['refined_click_point']
        point[point_axis] += point_delta
        direct = result['candidate_result']['candidates'][0]['element']['evidence']['vista_direct_identity']
        direct['point'] = dict(point)
        direct['source_candidate_id'] = 'vista_direct_' + sha1(
            f"{kwargs['goal']}|{point['x']}|{point['y']}".encode('utf-8')).hexdigest()[:10]
        return result
    monkeypatch.setattr(owner._screenshot_service, 'capture_window', changed_capture)
    monkeypatch.setattr(owner, '_recognition_runner', changed_recognition)


@pytest.mark.parametrize('point_delta,final_only,point_axis', [(1, False, 'y'), (0, True, 'y'), (14, False, 'x')])
def test_tiny_background_and_bounded_grounding_delta_dispatch_once(tmp_path, monkeypatch, point_delta, final_only, point_axis):
    with _ready(tmp_path, monkeypatch) as (coordinator, runtime, backend, owner, view):
        _alter(owner, monkeypatch, point_delta=point_delta, final_only=final_only, point_axis=point_axis)
        response = coordinator.execute(confirmation_id=view['confirmation_id'])
        assert response['kind'] == 'receipt', response
        assert len(backend.commands) == 1
        assert backend.commands[0].click_point == (60 + (point_delta if point_axis == 'x' else 0),
                                                  30 + (point_delta if point_axis == 'y' else 0))
        claims = runtime._intent_claim_store
        cid = view['confirmation_id']
        proof_path = claims.root / ('navigation-visual-stability-' + cid.split('.')[-1] + '.json')
        record = json.loads(proof_path.read_text(encoding='utf-8'))
        assert record['artifact_is_authorization'] is False
        assert record['visibility']['proof']['recognition_status'] == 'not_requested'
        assert record['visibility']['proof']['changed_pixels'] == 1
        if not final_only:
            assert record['proof']['changed_pixels'] == 1
        else:
            assert record['proof'] is None
        assert runtime.consume_grounded_confirmation(confirmation_id=cid).model_dump(mode='json') == response['payload']
        assert len(backend.commands) == 1


@pytest.mark.parametrize('point_delta,pixel,final_only,point_axis', [
    (17, None, False, 'x'), (1, (60, 30), False, 'y'), (1, (60, 30), True, 'y'),
    (1, (140, 55), False, 'y'),
])
def test_changed_target_or_unproven_point_still_rejects(tmp_path, monkeypatch, point_delta, pixel, final_only, point_axis):
    with _ready(tmp_path, monkeypatch) as (coordinator, runtime, backend, owner, view):
        _alter(owner, monkeypatch, point_delta=point_delta, pixel=pixel, final_only=final_only, point_axis=point_axis)
        response = coordinator.execute(confirmation_id=view['confirmation_id'])
        assert response['kind'] == 'decision', response
        assert response['payload']['reason_code'] == 'grounded_confirmation_stale'
        assert backend.commands == []


@pytest.mark.parametrize('final_only', [False, True])
@pytest.mark.parametrize('fault', ['missing', 'proof', 'visibility', 'consume_content_sha256', 'final_png'])
def test_reopened_navigation_record_requires_intact_proof(tmp_path, monkeypatch, fault, final_only):
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
    with _ready(tmp_path, monkeypatch) as (coordinator, runtime, backend, owner, view):
        _alter(owner, monkeypatch, point_delta=0 if final_only else 1, final_only=final_only)
        response = coordinator.execute(confirmation_id=view['confirmation_id'])
        assert response['kind'] == 'receipt', response
        claims, cid = runtime._intent_claim_store, view['confirmation_id']
        reopened = RuntimeIntentClaimStore(project_root=claims.project_root, receipt_store=claims._receipt_store, create_layout=False)
        assert reopened.get_for_grounded_confirmation(confirmation_id=cid).phase == 'terminal'
        path = claims.root / ('navigation-visual-stability-' + cid.split('.')[-1] + '.json')
        original = path.read_bytes()
        original_png, png_path = None, None
        try:
            if fault == 'missing':
                path.unlink()
            elif fault == 'final_png':
                record = json.loads(original)
                digest = record['visibility']['capture_source']['screenshot_sha256']
                from app.agent.fresh_learning_archive import FreshLearningObservationArchive
                png_path = FreshLearningObservationArchive(claims.project_root).root / 'png' / (digest + '.png')
                original_png = png_path.read_bytes()
                png_path.write_bytes(b'corrupt-local-test-only')
            else:
                value = json.loads(original)
                if fault == 'proof':
                    value['proof'] = {'changed_pixels': 999}
                elif fault == 'visibility':
                    value['visibility']['proof']['changed_pixels'] += 1
                else:
                    value[fault] = '0' * 64
                from app.agent.fresh_learning_action_contracts import canonical_json_bytes
                path.write_bytes(canonical_json_bytes(value))
            with pytest.raises(RuntimeIntentClaimStoreError):
                reopened.get_for_grounded_confirmation(confirmation_id=cid)
            assert len(backend.commands) == 1
        finally:
            path.write_bytes(original)
            if original_png is not None:
                png_path.write_bytes(original_png)


def test_consume_rejects_final_capture_reusing_recognition_id(tmp_path, monkeypatch):
    from app.agent.fresh_learning_action_contracts import canonical_json_bytes, FreshLearningIntent
    from app.agent.fresh_learning_action_preview import FreshLearningActionPreview, build_fresh_learning_action_preview
    from app.agent.fresh_learning_observation import FreshLearningObservationPacket
    from app.agent.navigation_visual_stability import NavigationVisualStabilityScope
    from app.agent.learned_control_reference import recognition_target_from_learned_control
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
    with _ready(tmp_path, monkeypatch) as (coordinator, runtime, backend, owner, view):
        claims = runtime._intent_claim_store
        archive = runtime._fresh_source_owner.archive
        reference = runtime._binding.source.reference()
        scope = {key: reference[key] for key in ('connection_id', 'task_id', 'segment_id')}
        approved = FreshLearningActionPreview.from_dict(view['preview'])
        original = archive.read(view['preview']['capture_source'], **scope)
        intent = FreshLearningIntent.from_dict(view['preview']['intent'])
        claim = claims.get_for_grounded_confirmation(confirmation_id=view['confirmation_id'])
        bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal,
            control_target=recognition_target_from_learned_control(intent.learned_control, semantic_action='open_detail'))
        fresh = build_fresh_learning_action_preview(bundle=bundle, capture_source=archive.record(bundle.packet, **scope),
            observation=claim.observation.to_dict(), intent=intent, source_reference=reference)
        packet = owner.observe(target_window_handle=4242, target_process_id=9001, goal=None)
        evidence = packet.evidence()
        evidence['capture']['capture_id'] = bundle.packet.evidence()['capture']['capture_id']
        replacement = FreshLearningObservationPacket(packet.png_bytes, canonical_json_bytes(evidence))
        visibility = {'capture_source': archive.record(replacement, **scope),
            'proof': NavigationVisualStabilityScope(approved, original.png_bytes).validate(evidence, packet.png_bytes)}
        with pytest.raises(RuntimeIntentClaimStoreError, match='final visibility must follow'):
            claims.begin_fresh_confirmation_consume(session_id=intent.session_id, observation_id=intent.observation_id,
                fresh_preview=fresh, navigation_visibility=visibility)
        assert backend.commands == []
        coordinator.cancel()
