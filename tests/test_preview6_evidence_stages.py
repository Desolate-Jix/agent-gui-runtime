"""即时帧与等待后帧分开标识；模式、阶段、部分文字匹配如实记录。"""
import hashlib
from types import SimpleNamespace
from PIL import Image
import pytest
from app.api import vision
from app.core import verifier as verifier_module
from app.operation.recognition.schemas import LocalGroundingCandidateResult
from app.vision.schemas import ImageSize
from tests.test_local_recognition_policy import plan_fixture, select


@pytest.mark.parametrize('allowed,expected', [(True, False), (False, True), (None, False)])
def test_policy_mode_does_not_imply_bypass(allowed, expected):
    plan = plan_fixture()
    plan['pre_click_decision']['allowed'] = allowed
    result = select(plan)
    assert result['bypass_applied'] is expected
    assert result['original_policy_allowed'] is allowed
    assert result['allowed'] is True
    assert ('automatic_rejection_bypassed' in result['reasons']) is expected
    assert result['candidate_decisions'][0]['bypass_applied'] is expected


def test_immediate_diff_carries_its_own_exact_frame_pair(tmp_path, monkeypatch):
    paths = {}
    for phase, color in [('before', 'blue'), ('after', 'green'), ('settled', 'red')]:
        paths[phase] = tmp_path / (phase + '.png')
        Image.new('RGB', (30, 20), color).save(paths[phase])
    monkeypatch.setattr(verifier_module.screenshot_service, 'capture_window',
        lambda **kw: {'image_path': str(paths['after'])})
    monkeypatch.setattr(verifier_module.window_manager, 'get_bound_window', lambda: None)
    verifier = verifier_module.Verifier()
    monkeypatch.setattr(verifier, '_compare_images', lambda **kw: {'changed': True})
    result = verifier.verify_action('fixture', wait_ms=0, judged_by_agent=True,
        before_state={'image_path': str(paths['before'])})
    assert result['verified'] is None
    assert result['diff']['frame_pair'] == 'immediate'
    assert result['diff']['evidence_role'] == 'diagnostic_not_agent_review'
    for phase in ['before', 'after']:
        frame = result[phase]
        assert frame['frame_id'] == phase + '_immediate'
        assert frame['sha256'] == hashlib.sha256(paths[phase].read_bytes()).hexdigest()
        assert result['diff']['source_frames'][phase]['sha256'] == frame['sha256']
    assert result['after']['sha256'] != hashlib.sha256(paths['settled'].read_bytes()).hexdigest()


def test_partial_text_support_does_not_claim_exact_target_identity(tmp_path, monkeypatch):
    image = tmp_path / 'current.png'
    Image.new('RGB', (1000, 690)).save(image)
    goal = 'Click the tab labelled 主机游戏 in the tab row'
    point = {'x': 619, 'y': 100}
    candidate = vision._recognition_candidate_from_vista_direct(goal=goal, point=point,
        image_size=ImageSize(width=1000, height=690), bbox_size=48)
    local = LocalGroundingCandidateResult(candidate_id=candidate.candidate_id,
        element_id=candidate.element_id, status='grounded', crop_path=None,
        crop_bbox={'x': 571, 'y': 52, 'width': 96, 'height': 96},
        refined_click_point={'x': 641, 'y': 103}, coordinate_source='local_ocr_text_center',
        confidence=.9, matched_text='主机游',
        matched_text_bbox={'x': 46, 'y': 43, 'width': 49, 'height': 17},
        reasons=['matched_local_ocr_text'])
    monkeypatch.setattr(vision, 'run_local_grounding', lambda req: SimpleNamespace(results=[local]))
    result = vision._corroborate_vista_direct_point(image_path=image, goal=goal,
        candidate=candidate, point=point, app_name='fixture')
    assert result.coordinate_source == 'vista_point_v1_with_partial_local_ocr'
    assert result.refined_click_point == point
    evidence = candidate.element.evidence['local_ocr_target_match']
    assert evidence['match_kind'] == 'partial'
    assert evidence['full_target_identity_verified'] is False


def test_recognition_metadata_identifies_planning_not_dispatch():
    assert vision._vision_execution_path(requested_mode='local')['phase'] == 'planning'
