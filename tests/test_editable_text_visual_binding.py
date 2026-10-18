"""真实前端与完整填写预览的截图摘要归一；纯等价检查不证明视觉 Gate 或输入授权。"""
from copy import deepcopy

from PIL import Image, ImageChops
import pytest

from app.api import vision
from app.agent.fresh_learning_action_contracts import canonical_json_bytes, payload_sha256
from app.agent.fresh_learning_action_preview import (
    FreshLearningActionPreview, validate_fresh_execution_preview, validate_text_execution_equivalence,
)
from app.operation.recognition.editable_control_corroboration import EVIDENCE_KEY
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch
from tests import test_fresh_text_preview as text_fixture


def _previews(tmp_path, monkeypatch):
    class UIA(text_fixture._TextUIA):
        def snapshot_window(self, bound):
            result = super().snapshot_window(bound)
            result.update(scan_complete=True, truncated=False, scan_budget=1000,
                          scan_visited_count=1, truncation_reason=None)
            result['controls'][0]['name'] = '\ufffc'
            return result

    uia = UIA()
    monkeypatch.setattr(vision.uia_provider, 'snapshot_bound_window',
                        lambda **kwargs: deepcopy(uia.snapshot_window(text_fixture._bound())))
    monkeypatch.setattr(vision.VisionProviderFactory, 'load_config', lambda: {
        'vision': {'mode': 'local', 'timeout_seconds': 10, 'local_grounding': {
            'model_name': 'inclusionAI/VISTA-4B', 'endpoint': 'http://127.0.0.1:1/v1/chat/completions',
            'runtime': 'transformers', 'output_contract': 'vista_point_v1'}}})
    monkeypatch.setattr(vision.VisionProviderFactory, 'create', lambda **kwargs: object())
    monkeypatch.setattr(vision, 'VISTA_DIRECT_IMAGES_DIR', tmp_path / 'model-crops')
    monkeypatch.setattr(vision.LocalVisionProvider, '_call_openai_compatible_endpoint',
        lambda *args, **kwargs: {'choices': [{'message': {'content': '[375, 300]'}}]})
    monkeypatch.setattr(vision.ocr_service, 'scan_image', lambda path: OCRResult(image_path=str(path),
        matches=[OCRTextMatch('Search field', .96, OCRBoundingBox(20, 20, 70, 14))]))
    originals = []
    images = []

    def runner(**kwargs):
        # 模型和 OCR 只提供合成观测；候选、公共投影、风险和完整预览走生产路径。
        response = vision.recognition_plan(vision.VisionRecognitionPlanRequestModel(
            image_path=kwargs['image_path'], goal=kwargs['goal'], task='locate_element',
            provider_mode='local_grounding', agent_mode='execute',
            write_policy={'path_graph': False, 'element_memory': False, 'trace': False},
            metadata={'semantic_action': 'fill_field',
                      'vista_direct_grounding': {'enabled': True, 'refine': False}}))
        assert response.success, response
        result = response.data['result']
        assert result['pre_click_decision']['allowed'] is True, result['pre_click_decision']
        originals.append(deepcopy(result))
        return result

    original_factory = text_fixture._native_owner

    def factory(root):
        owner = original_factory(root)
        owner._uia_provider = uia
        owner._recognition_runner = runner
        capture = owner._screenshot_service.capture_window
        calls = 0

        def changed_capture(**kwargs):
            nonlocal calls
            calls += 1
            result = capture(**kwargs)
            with Image.open(result['image_path']) as opened:
                image = opened.convert('RGB')
            if calls == 3:
                image.putpixel((155, 95), (200, 201, 202))
                image.save(result['image_path'])
            images.append(image.copy())
            return result

        monkeypatch.setattr(owner._screenshot_service, 'capture_window', changed_capture)
        return owner

    monkeypatch.setattr(text_fixture, '_native_owner', factory)
    previews, _ = text_fixture._text_previews(tmp_path, count=2)
    assert len(originals) == 2 and len(images) == 4
    assert ImageChops.difference(images[-2], images[-1]).getbbox() == (155, 95, 156, 96)
    assert images[-2].crop((10, 10, 130, 50)).tobytes() == images[-1].crop((10, 10, 130, 50)).tobytes()
    for preview, original in zip(previews, originals):
        assert type(preview) is FreshLearningActionPreview
        data = preview.to_dict()
        assert FreshLearningActionPreview.from_dict(data).to_dict() == data
        recognition = data['observation_evidence']['recognition']
        assert recognition['result_projection_contract'] == 'fresh_read_only_recognition_projection_v1'
        source_proof = original['candidate_result']['candidates'][0]['element']['evidence'][EVIDENCE_KEY]
        assert _proof(data) == source_proof
        assert source_proof['raw_name'] == '\ufffc' and source_proof['runtime_id'] == [42, 12]
        assert source_proof['point'] == {'x': 60, 'y': 30}
        assert source_proof['matched_text_bbox'] == {'x': 20, 'y': 20, 'w': 70, 'h': 14}
        assert data['risk']['risk_class'] == 'low_risk_text_input'
        assert data['action_executed'] is False and data['artifact_is_authorization'] is False
    return previews


def _proof(data):
    return data['observation_evidence']['recognition']['result']['candidate_result']['candidates'][0]['element']['evidence'][EVIDENCE_KEY]


def test_full_editable_previews_normalize_only_verified_capture_digest(tmp_path, monkeypatch):
    before, after = _previews(tmp_path, monkeypatch)
    original = [item.to_dict() for item in (before, after)]
    proofs = [_proof(data) for data in original]
    assert proofs[0]['screenshot_sha256'] != proofs[1]['screenshot_sha256']
    assert {k: v for k, v in proofs[0].items() if k != 'screenshot_sha256'} == {
        k: v for k, v in proofs[1].items() if k != 'screenshot_sha256'}
    assert validate_text_execution_equivalence(before, after) is None
    assert [item.to_dict() for item in (before, after)] == original
    # 缺少真实类型化视觉证明时，执行比较仍必须拒绝不同原图。
    with pytest.raises(ValueError, match='drifted'):
        validate_fresh_execution_preview(before, after)


def test_full_editable_previews_reject_rehashed_target_fact_tampering(tmp_path, monkeypatch):
    before, after = _previews(tmp_path, monkeypatch)
    for fault in ('point', 'runtime_id', 'ocr'):
        changed = after.to_dict()
        proof = _proof(changed)
        if fault == 'point':
            proof['point']['x'] += 1
        elif fault == 'runtime_id':
            proof['runtime_id'][-1] += 1
        else:
            proof['matched_text'] = 'Search account'
        evidence = changed['observation_evidence']
        changed['capture_source']['content_sha256'] = payload_sha256({
            'evidence_json': canonical_json_bytes(evidence).decode('utf-8'),
            'screenshot_sha256': evidence['capture']['screenshot_sha256']})
        changed['preview_sha256'] = payload_sha256({k: v for k, v in changed.items() if k != 'preview_sha256'})
        with pytest.raises(ValueError, match='editable field OCR binding'):
            validate_text_execution_equivalence(before, changed)
