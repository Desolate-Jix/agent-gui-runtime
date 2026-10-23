"""Narrow Main adoption of an original, authenticated pre-input refusal."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns

from .decision_check import _candidate, _identity


def review_main_pre_action(*, target, scope, capture, identity, candidate, point,
                          goal, click_kind, manager, validate_binding):
    from .action_review_dispatch import _reject
    approval = target._main_pre_action
    source = approval.source
    approval.validate()
    original = source.envelope
    selected = _candidate(candidate, point)
    expected = original['candidate']
    def same_candidate(value):
        return all(value[key] == expected[key] for key in ('candidate_id', 'bbox', 'click_point', 'source'))
    if (scope['service'] is not source.service or scope['context'] != source.context
            or goal != original['action']['goal'] or click_kind != original['action']['click_kind']
            or not same_candidate(selected) or _identity(identity) != original['frame']['window_identity']
            or target.input_claimed):
        _reject(scope, 'main_pre_action_binding_invalid')
    target._validate_main_fresh()
    fresh = deepcopy(target._main_fresh)
    if (Path(capture['image_path']).resolve() != Path(fresh['image_path'])
            or sha256(Path(capture['image_path']).read_bytes()).hexdigest() != fresh['sha256']):
        _reject(scope, 'main_pre_action_fresh_capture_mismatch')
    scope['assessment'], scope['envelope'] = deepcopy(source.assessment), deepcopy(original)
    scope['main_pre_action_review'] = approval.to_reference()
    def validate():
        from .action_review import current_action_review
        approval.validate()
        target._validate_main_fresh()
        bound = manager.get_bound_window()
        if (current_action_review() is not scope or bound is None
                or (bound.handle, bound.process_id) != (source.identity['target_window_handle'], source.identity['process_id'])
                or [bound.rect.left, bound.rect.top, bound.rect.right, bound.rect.bottom] != source.rect
                or scope['assessment'] != source.assessment or scope['envelope'] != original
                or perf_counter_ns() >= scope['deadline_ns']
                or scope['cancelled'] and scope['cancelled']()):
            _reject(scope, 'main_pre_action_no_longer_valid')
        popup_reader = getattr(manager, 'read_owned_foreground_popup', None)
        popup = deepcopy(popup_reader(bound)) if callable(popup_reader) else None
        if popup != original['action']['native_popup_fact']:
            _reject(scope, 'main_pre_action_popup_changed')
        latest_identity, latest_candidate = validate_binding()
        if (_identity(latest_identity) != original['frame']['window_identity']
                or not same_candidate(_candidate(latest_candidate, point))):
            _reject(scope, 'main_pre_action_target_changed')
        target._validate_main_fresh()
    validate()
    box = selected['bbox']
    visibility = {'target_bbox': {'x': point['x'], 'y': point['y'], 'width': 1, 'height': 1},
        'candidate_bbox': {'x': box['x'], 'y': box['y'], 'width': box['w'], 'height': box['h']},
        'scope': 'reviewed_click_point', 'reason': 'authenticated_main_pre_action_adoption'}
    return {'assessment': deepcopy(source.assessment), 'validate': validate, 'scope': scope,
        'frame': deepcopy(original['frame']), 'candidate': selected, 'click_visibility': visibility,
        'main_pre_action_approval': approval}
