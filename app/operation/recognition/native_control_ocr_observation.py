"""保存原始 OCR 分歧；几何证据不能替换文字观测或自动风险判定。"""
from copy import deepcopy
from hashlib import sha256
import math
import re

KEY = 'native_control_ocr_observation'
DISAGREEMENT = 'native_control_ocr_semantic_disagreement'


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _classify(matches, crop, target):
    if not isinstance(matches, list) or len(matches) > 512:
        return None
    inside = []
    for index, item in enumerate(matches):
        if (not isinstance(item, dict) or set(item) != {'text', 'score', 'bbox'}
                or not isinstance(item['text'], str) or not _number(item['score'])
                or not 0 <= item['score'] <= 1):
            return None
        box = item['bbox']
        if not isinstance(box, dict) or set(box) != {'x', 'y', 'width', 'height'}:
            return None
        if not all(_number(value) for value in box.values()):
            return None
        x, y, w, h = [box[key] for key in ('x', 'y', 'width', 'height')]
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > crop['w'] or y + h > crop['h']:
            return None
        x, y = x + crop['x'], y + crop['y']
        if x < target['x'] + target['w'] and x + w > target['x'] and y < target['y'] + target['h'] and y + h > target['y']:
            inside.append(index)
    return {'classification': 'target_text_present' if inside else ('outside_target' if matches else 'empty'),
            'target_match_indices': inside}


def record_native_ocr(*, image_path, image_size, crop, candidate, ocr_result):
    fact = {'contract_version': 'native_control_ocr_observation_v1',
        'source_screenshot_sha256': sha256(image_path.read_bytes()).hexdigest(),
        'candidate_id': candidate.candidate_id, 'element_id': candidate.element_id,
        'crop_bbox': {'x': crop['x'], 'y': crop['y'], 'w': crop['width'], 'h': crop['height']},
        'target_bbox': candidate.element.bbox.to_dict(), 'viewport_size': list(image_size),
        'ocr_engine': ocr_result.metadata.get('engine'),
        'matches': deepcopy(ocr_result.to_dict()['matches'])}
    classification = _classify(fact['matches'], fact['crop_bbox'], fact['target_bbox'])
    if classification is None:
        return None
    fact.update(classification)
    return fact


def validated_native_ocr(candidate, local, screenshot_sha256):
    fact = candidate.element.evidence.get(KEY)
    if (not isinstance(fact, dict) or set(fact) != {'contract_version', 'source_screenshot_sha256',
            'candidate_id', 'element_id', 'crop_bbox', 'target_bbox', 'viewport_size', 'ocr_engine',
            'matches', 'classification', 'target_match_indices'}
            or fact['contract_version'] != 'native_control_ocr_observation_v1'
            or not isinstance(screenshot_sha256, str) or not re.fullmatch('[0-9a-f]{64}', screenshot_sha256)
            or fact['source_screenshot_sha256'] != screenshot_sha256
            or fact['candidate_id'] != candidate.candidate_id or fact['element_id'] != candidate.element_id
            or fact['target_bbox'] != candidate.element.bbox.to_dict()
            or fact['crop_bbox'] != local.crop_bbox
            or fact['ocr_engine'] is not None and not isinstance(fact['ocr_engine'], str)):
        return None
    viewport, crop, target = fact['viewport_size'], fact['crop_bbox'], fact['target_bbox']
    if type(viewport) is not list or len(viewport) != 2 or any(type(v) is not int or v <= 0 for v in viewport):
        return None
    for box in (crop, target):
        if (not isinstance(box, dict) or set(box) != {'x', 'y', 'w', 'h'}
                or any(type(v) is not int for v in box.values())
                or min(box['x'], box['y']) < 0 or min(box['w'], box['h']) <= 0
                or box['x'] + box['w'] > viewport[0] or box['y'] + box['h'] > viewport[1]):
            return None
    if (crop['x'] > target['x'] or crop['y'] > target['y']
            or crop['x'] + crop['w'] < target['x'] + target['w']
            or crop['y'] + crop['h'] < target['y'] + target['h']):
        return None
    classification = _classify(fact['matches'], crop, target)
    if classification is None or any(fact[key] != value for key, value in classification.items()):
        return None
    return deepcopy(fact)
