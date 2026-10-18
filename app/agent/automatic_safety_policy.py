"""本地单步策略观察选项；不授予输入权限，也不改写原始安全判定。"""
from copy import deepcopy
from collections.abc import Mapping


MODE_PREVIEW_VERSION = 'fresh_learning_action_preview_v3'
FRESH_PREVIEW_VERSIONS = frozenset({
    'fresh_learning_action_preview_v1', 'fresh_learning_action_preview_v2', MODE_PREVIEW_VERSION,
})


def validate_automatic_safety_interception(value):
    if type(value) is not bool:
        raise ValueError('automatic_safety_interception must be an exact boolean')
    return value


def preview_automatic_safety_interception(preview):
    data = preview.to_dict() if hasattr(preview, 'to_dict') else preview
    if not isinstance(data, Mapping):
        raise ValueError('safety policy requires a preview mapping')
    if data.get('contract_version') == MODE_PREVIEW_VERSION:
        return validate_automatic_safety_interception(data.get('automatic_safety_interception'))
    if data.get('contract_version') not in FRESH_PREVIEW_VERSIONS:
        raise ValueError('safety policy requires a supported fresh preview')
    if 'automatic_safety_interception' in data:
        raise ValueError('legacy preview cannot override automatic safety interception')
    return True


def preview_action_selection(preview):
    data = preview.to_dict() if hasattr(preview, 'to_dict') else preview
    if not isinstance(data, Mapping):
        raise ValueError('action selection requires a preview mapping')
    source = data.get('action_selection') if data.get('contract_version') == MODE_PREVIEW_VERSION else data.get('pre_click_decision')
    if not isinstance(source, Mapping):
        raise ValueError('fresh preview has no action selection')
    keys = ('selected_candidate_id', 'selected_element_id', 'selected_click_point')
    if any(key not in source for key in keys):
        raise ValueError('fresh preview action selection is incomplete')
    return {key: deepcopy(source[key]) for key in keys}


def _unique_manual_grounded_candidate(candidates, local):
    """没有策略选中项时只接受唯一完整几何对，不按顺序或分数兜底。"""
    from app.operation.recognition.schemas import (
        CandidateRankResult, LocalGroundingResult, RecognitionCandidate, LocalGroundingCandidateResult,
    )
    from app.operation.page_structure.schemas import PageElement
    from app.vision.schemas import BBox

    if (not isinstance(candidates, CandidateRankResult) or not isinstance(local, LocalGroundingResult)
            or not isinstance(candidates.candidates, list) or not isinstance(local.results, list)
            or not candidates.candidates or len(candidates.candidates) != len(local.results)
            or any(not isinstance(item, RecognitionCandidate) for item in candidates.candidates)
            or any(not isinstance(item, LocalGroundingCandidateResult) for item in local.results)):
        raise ValueError('manual preview requires complete current candidate grounding')
    candidate_ids = [item.candidate_id for item in candidates.candidates]
    element_ids = [item.element_id for item in candidates.candidates]
    local_ids = [item.candidate_id for item in local.results]
    all_ids = candidate_ids + element_ids + local_ids + [item.element_id for item in local.results]
    if (any(not isinstance(value, str) or not value for value in all_ids)
            or len(set(candidate_ids)) != len(candidate_ids) or len(set(element_ids)) != len(element_ids)
            or len(set(local_ids)) != len(local_ids) or set(candidate_ids) != set(local_ids)):
        raise ValueError('manual preview candidate grounding identities are ambiguous')
    by_id = {item.candidate_id: item for item in local.results}
    grounded_ids = []
    for candidate in candidates.candidates:
        result = by_id[candidate.candidate_id]
        if (result.element_id != candidate.element_id or not isinstance(candidate.element, PageElement)
                or candidate.element.element_id != candidate.element_id
                or not isinstance(result.status, str) or not result.status):
            raise ValueError('manual preview requires bound current grounding')
        if result.status != 'grounded':
            continue
        point = result.refined_click_point
        if (not isinstance(point, dict) or set(point) != {'x', 'y'}
                or any(type(value) is not int for value in point.values())
                or not isinstance(candidate.element.bbox, BBox)):
            raise ValueError('manual preview requires bound current grounding')
        original = candidate.element.bbox.to_dict()
        refined = original if candidate.refined_bbox is None else candidate.refined_bbox
        for box in (original, refined):
            if (not isinstance(box, dict) or set(box) != {'x', 'y', 'w', 'h'}
                    or any(type(value) is not int for value in box.values())
                    or min(box['x'], box['y']) < 0 or min(box['w'], box['h']) <= 0
                    or not (box['x'] <= point['x'] < box['x'] + box['w']
                            and box['y'] <= point['y'] < box['y'] + box['h'])):
                raise ValueError('manual preview point is outside bound target geometry')
        grounded_ids.append(candidate.candidate_id)
    if len(grounded_ids) != 1:
        raise ValueError('manual preview requires one unambiguous current grounded candidate')
    return grounded_ids[0]


def action_selection(decision, candidates, local, *, automatic_safety_interception=True):
    strict = validate_automatic_safety_interception(automatic_safety_interception)
    if strict and decision.get('allowed') is not True:
        raise ValueError('fresh preview pre-click gate rejected')
    if strict:
        # 默认模式沿用既有 Gate 的选择，不为开关额外收紧或放宽几何规则。
        return {key: deepcopy(decision[key]) for key in (
            'selected_candidate_id', 'selected_element_id', 'selected_click_point')}
    candidate_id = decision.get('selected_candidate_id')
    if candidate_id is None:
        candidate_id = _unique_manual_grounded_candidate(candidates, local)
    chosen = [item for item in candidates.candidates if item.candidate_id == candidate_id]
    grounded = [item for item in local.results if item.candidate_id == candidate_id]
    if len(chosen) != 1 or len(grounded) != 1:
        raise ValueError('fresh preview candidate is ambiguous')
    candidate, result = chosen[0], grounded[0]
    point = result.refined_click_point
    if (result.element_id != candidate.element_id or result.status != 'grounded'
            or not isinstance(point, dict) or set(point) != {'x', 'y'}
            or any(type(point[key]) is not int for key in point)):
        raise ValueError('manual preview requires bound current grounding')
    for box in (candidate.element.bbox.to_dict(), candidate.refined_bbox or candidate.element.bbox.to_dict()):
        if (any(type(box.get(key)) is not int for key in ('x', 'y', 'w', 'h'))
                or min(box['x'], box['y']) < 0 or min(box['w'], box['h']) <= 0
                or not (box['x'] <= point['x'] < box['x'] + box['w']
                        and box['y'] <= point['y'] < box['y'] + box['h'])):
            raise ValueError('manual preview point is outside bound target geometry')
    if decision.get('allowed') is True and decision.get('selected_click_point') != point:
        raise ValueError('fresh preview point differs from local grounding')
    return {'selected_candidate_id': candidate.candidate_id, 'selected_element_id': candidate.element_id,
            'selected_click_point': dict(point)}


def automatic_safety_report(decision, risk):
    reasons = []
    if decision.get('allowed') is not True:
        reasons.extend(decision.get('reasons') or [])
        for item in decision.get('candidate_decisions') or []:
            if item.get('allowed') is not True:
                reasons.extend(item.get('reasons') or [])
    if risk.get('hard_blocked') is not False:
        reasons.extend(risk.get('reasons') or [])
    return {'contract_version': 'automatic_safety_observation_v1',
            'would_block': decision.get('allowed') is not True or risk.get('hard_blocked') is not False,
            'reasons': list(dict.fromkeys(reasons)), 'artifact_is_authorization': False}
