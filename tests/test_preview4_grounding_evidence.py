"""真实反馈对应的通用回归：短中文、独立文字锚点、原始模型点与回执留痕。"""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from PIL import Image
from app.api import vision
from app.vision.schemas import ImageSize
from app.operation.recognition import decision, local_grounding
from app.operation.recognition.schemas import LocalGroundingCandidateResult
from app.operation.recognition.text_match import explicit_target_label


GOAL = "Click the tab labelled 游戏 (Games tab) in the app's left tab bar"


def test_same_short_cjk_match_at_both_stages():
    a, b = '游戏', local_grounding._normalize_text(GOAL)
    assert local_grounding._text_similarity(a, b) == decision._text_similarity(a, b) == .9
    assert decision._text_similarity('游戏', '游戏币') < .9
    assert decision._text_similarity('go', 'google') < .9


def test_explicit_label_is_not_the_instruction():
    assert explicit_target_label(GOAL) == '游戏'
    candidate = vision._recognition_candidate_from_vista_direct(goal=GOAL,
        point={'x': 200, 'y': 29}, image_size=ImageSize(width=1000, height=690), bbox_size=48)
    assert candidate.label == candidate.text == '游戏'


@pytest.mark.parametrize('matched', ['游戏', '其他', None])
def test_direct_point_uses_only_matching_current_ocr_anchor(tmp_path, monkeypatch, matched):
    path = tmp_path / 'capture.png'
    Image.new('RGB', (1000, 690)).save(path)
    original = {'x': 200, 'y': 29}
    candidate = vision._recognition_candidate_from_vista_direct(goal=GOAL,
        point=original, image_size=ImageSize(width=1000, height=690), bbox_size=48)
    local = LocalGroundingCandidateResult(candidate_id=candidate.candidate_id,
        element_id=candidate.element_id, status='grounded' if matched else 'fallback',
        crop_path=None, crop_bbox={'x': 152, 'y': 0, 'width': 96, 'height': 77},
        refined_click_point={'x': 223, 'y': 31}, coordinate_source='local_ocr_text_center',
        confidence=.95, matched_text=matched,
        matched_text_bbox={'x': 53, 'y': 21, 'width': 36, 'height': 20} if matched else None,
        reasons=['matched_local_ocr_text', 'mapped_crop_text_center_to_full_image'] if matched else [])
    monkeypatch.setattr(vision, 'run_local_grounding', lambda req: SimpleNamespace(results=[deepcopy(local)]))
    result = vision._corroborate_vista_direct_point(image_path=path, goal=GOAL,
        candidate=candidate, point=original, app_name='fixture')
    if matched == '游戏':
        assert result.refined_click_point == {'x': 223, 'y': 31}
        assert result.coordinate_source == 'local_ocr_text_center'
        assert candidate.refined_bbox == {'x': 205, 'y': 21, 'w': 36, 'h': 20}
        assert result.status == 'grounded'
        assert candidate.element.evidence['vista_direct_point']['point'] == original
    else:
        assert result.refined_click_point == original
        assert result.status == 'unverified'
        assert 'corroborated' not in result.coordinate_source
        assert 'mapped_crop_text_center_to_full_image' not in result.reasons


def test_synthetic_box_is_not_independent_target_proof():
    candidate = vision._recognition_candidate_from_vista_direct(goal=GOAL,
        point={'x': 200, 'y': 29}, image_size=ImageSize(width=1000, height=690), bbox_size=48)
    _, receipt = decision._resolve_click_point(candidate=candidate, bbox=candidate.element.bbox,
        raw_point={'x': 200, 'y': 29})
    assert receipt['independent_target_bbox_verified'] is False
    assert receipt['adjustment_reason'] == 'synthetic_search_box_not_target_proof'


def test_operator_mode_retains_candidate_audit():
    from test_local_recognition_policy import plan_fixture, select
    plan = plan_fixture()
    result = select(plan)
    audit = result['candidate_decisions'][0]
    assert audit['candidate_id'] == 'current'
    assert audit['click_point'] == result['selected_click_point']
    assert audit['original_grounding_status'] == 'unverified'
    assert result['original_policy'] == plan['pre_click_decision']


@pytest.mark.parametrize('duplicate', [False, True])
def test_actual_crop_ocr_mapping_and_duplicate_negative_control(tmp_path, monkeypatch, duplicate):
    from modules.ocr.contracts import OCRResult, OCRTextMatch, OCRBoundingBox
    from app.core.runtime_artifacts import pinned_runtime_output_root
    path = tmp_path / 'frame.png'
    Image.new('RGB', (1000, 690)).save(path)
    candidate = vision._recognition_candidate_from_vista_direct(goal=GOAL,
        point={'x': 200, 'y': 29}, image_size=ImageSize(width=1000, height=690), bbox_size=48)
    def scan(crop_path):
        with Image.open(crop_path) as image:
            assert image.size == (96, 77)
        matches = [OCRTextMatch('游戏', .95, OCRBoundingBox(53, 21, 36, 20))]
        if duplicate:
            matches.append(OCRTextMatch('游戏', .95, OCRBoundingBox(3, 21, 36, 20)))
        return OCRResult(crop_path, matches)
    monkeypatch.setattr(vision.ocr_service, 'scan_image', scan)
    with pinned_runtime_output_root(tmp_path):
        result = vision._corroborate_vista_direct_point(image_path=path, goal=GOAL,
            candidate=candidate, point={'x': 200, 'y': 29}, app_name='fixture')
    assert result.refined_click_point == ({'x': 200, 'y': 29} if duplicate else {'x': 223, 'y': 31})
    assert result.status == ('unverified' if duplicate else 'grounded')


@pytest.mark.parametrize('changed', [False, True])
def test_agent_judged_verifier_never_promotes_cursor_or_diff_to_success(monkeypatch, changed):
    from app.core import verifier as module
    verifier = module.Verifier()
    monkeypatch.setattr(module.screenshot_service, 'capture_window', lambda **kw: {'image_path': 'after.png'})
    monkeypatch.setattr(module.window_manager, 'get_bound_window', lambda: None)
    monkeypatch.setattr(verifier, '_compare_images', lambda **kw: {'available': True, 'changed': changed})
    result = verifier.verify_action('fixture', wait_ms=0, judged_by_agent=True,
        before_state={'image_path': 'before.png', 'window_handle': 321},
        click_result={'cursor_before': {'x': 0, 'y': 0}, 'cursor_after': {'x': 2, 'y': 2},
                      'foreground_before': 321, 'foreground_after': 321})
    assert result['verified'] is None
    assert result['verification_status'] == 'awaiting_agent_review'
    assert result['verification_basis'] == {'diff_changed': changed, 'cursor_and_focus': True}
