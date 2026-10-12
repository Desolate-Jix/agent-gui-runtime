"""弹窗是否可忽略由已配置的判断服务决定；原点击门禁仍执行。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import get_ident

from app.execution.decision_check import (
    DecisionCheckRejected, _before_evidence, _candidate, _evaluate, _identity,
    adaptive_decision_enabled, decision_frame, service_enabled,
)


POPUP_CONTINUE_CONDITION = (
    'The current task can continue by performing the specified original action '
    'without interacting with or dismissing the visible popup. The popup does not '
    'require a choice, consent, authentication, or any other intervention before that action.'
)
_SCOPE = ContextVar('popup_decision_scope', default=None)
_ISSUER = object()


def _bound_snapshot(bound):
    return (bound.handle, bound.process_id,
        (bound.rect.left, bound.rect.top, bound.rect.right, bound.rect.bottom))


class PopupContinuationGuard:
    def __init__(self, issuer, *, scope, bound, point, bbox, popup_handle, click_count, verify):
        if issuer is not _ISSUER or not callable(verify):
            raise ValueError('popup_continuation_requires_verified_decision')
        self._scope, self._bound = scope, _bound_snapshot(bound)
        self._point, self._bbox = tuple(point), tuple(bbox)
        self._popup, self._count, self._verify = popup_handle, click_count, verify
        self._owner, self._claimed = get_ident(), False

    def validate_command(self, *, bound, point, bbox, popup_handle, click_count):
        if (self._claimed or not self._scope['active'] or self._owner != get_ident()
                or _bound_snapshot(bound) != self._bound or tuple(point) != self._point
                or bbox is None or tuple(bbox) != self._bbox
                or popup_handle != self._popup or click_count != self._count):
            raise ValueError('popup_continuation_command_mismatch')
        self._claimed = True

    def verify_current(self):
        if not self._claimed or not self._scope['active'] or self._owner != get_ident():
            raise ValueError('popup_continuation_scope_unavailable')
        if self._verify() is not None:
            raise ValueError('popup_continuation_verification_invalid')


@contextmanager
def popup_decision_scope(service, *, execution_request_id, step_id, evidence_root):
    if _SCOPE.get() is not None:
        raise ValueError('popup_decision_scope_overlap')
    scope = dict(service=service, execution_request_id=execution_request_id or step_id,
        step_id=step_id, evidence_root=evidence_root, active=True, owner=get_ident(),
        result=None, assessed=False)
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        scope['active'] = False
        _SCOPE.reset(token)


def _reject(scope, reason, result=None):
    result = {**(result or {}), 'reason': reason, 'status': (result or {}).get('status', 'not_applied'),
        'verdict': (result or {}).get('verdict', 'uncertain'), 'disposition': 'review_required',
        'adopted': False, 'authorizes_action': False, 'automatic_retry_allowed': False,
        'phase': 'before_action'}
    scope['result'] = deepcopy(result)
    raise DecisionCheckRejected(reason, result)


def prepare_popup_continuation(*, manager, capture, identity, candidate, point, bbox,
        goal, click_kind, click_count, image_path, expected_owned_popup_handle=None,
        revalidate_target=None, combined_review=None):
    if combined_review is not None:
        return _combined_popup_guard(combined_review, manager=manager, identity=identity,
            point=point, bbox=bbox, click_count=click_count,
            expected_owned_popup_handle=expected_owned_popup_handle)
    scope = _SCOPE.get()
    if scope is None:
        return None, None
    if not scope['active'] or scope['owner'] != get_ident():
        raise ValueError('popup_decision_scope_unavailable')
    detect = getattr(manager, 'get_owned_foreground_popup_handle', None)
    if not callable(detect):
        return None, None
    bound = manager.get_bound_window()
    popup = detect(bound)
    if popup is None or expected_owned_popup_handle is not None:
        return None, None
    # 明确点在弹窗内的原任务目标沿用原门禁；此分支只判断忽略弹窗的父窗动作。
    hit = manager.validate_bound_point_visibility(bound=bound, x=point['x'], y=point['y'])
    if (hit.get('hit_window') or {}).get('root_handle') == popup:
        return None, None
    service = scope['service']
    if (not service_enabled(service) or not adaptive_decision_enabled(service)
            or getattr(service, 'adoption_mode', None) != 'auto'
            or not service.auto_condition_allowed(POPUP_CONTINUE_CONDITION)
            or service.readiness().get('ready') is not True):
        _reject(scope, 'popup_decision_unavailable')
    if scope['assessed']:
        _reject(scope, 'popup_decision_already_assessed')
    scope['assessed'] = True
    original_bound = _bound_snapshot(bound)
    try:
        original_identity = _identity(identity())
        source_digest = sha256(Path(image_path).read_bytes()).hexdigest()
        before = capture()
        if before.get('roi') is not None or bbox is None:
            raise ValueError('popup_requires_full_window_and_target_box')
        frame, selected = _before_evidence(scope, before, original_identity, candidate, point)
        if frame['sha256'] != source_digest or detect(manager.get_bound_window()) != popup:
            raise ValueError('popup_candidate_changed')
        # 将原生弹窗事实与截图一同绑定；模型不能从画面文字更改任务目标。
        popup_fact = manager.read_owned_foreground_popup(bound)
        if (not isinstance(popup_fact, dict) or popup_fact.get('handle') != popup
                or popup_fact.get('parent_handle') != bound.handle
                or popup_fact.get('process_id') != bound.process_id
                or type(popup_fact.get('parent_enabled')) is not bool):
            raise ValueError('popup_snapshot_unavailable')
        pr, br = popup_fact.get('rect'), original_bound[2]
        if (not isinstance(pr, (tuple, list)) or len(pr) != 4
                or any(type(value) is not int for value in pr)
                or not (br[0] <= pr[0] < pr[2] <= br[2] and br[1] <= pr[1] < pr[3] <= br[3])):
            raise ValueError('popup_outside_original_frame')
    except (ValueError, OSError, TypeError, AttributeError, RuntimeError) as error:
        _reject(scope, 'popup_decision_stale', {'status': 'invalidated', 'error_type': type(error).__name__})
    execution_id = scope['execution_request_id']
    action = {'operation': 'execute_recognition_plan', 'goal': goal, 'click_kind': click_kind,
        'target_window_identity': original_identity, 'candidate': selected, 'popup': popup_fact}
    result = _evaluate(service, request_id='popup-before-' + str(execution_id),
        execution_request_id=execution_id, condition=POPUP_CONTINUE_CONDITION,
        frames=[frame], phase='before_action', step_id=scope['step_id'], action=action,
        review_context={'goal': goal, 'step_goal': POPUP_CONTINUE_CONDITION, 'remaining_plan': [],
            'allowed_states': ['A popup may remain visible when the original target is accessible and no popup interaction is needed.'],
            'source_id': execution_id})
    if (result.get('adopted') is not True or result.get('disposition') != 'continue'
            or result.get('verdict') != 'success'):
        _reject(scope, 'popup_decision_review_required', result)

    def verify_identity():
        if (_bound_snapshot(manager.get_bound_window()) != original_bound
                or _identity(identity()) != original_identity):
            raise ValueError('popup_continuation_identity_changed')
        current_popup = manager.read_owned_foreground_popup(manager.get_bound_window())
        if current_popup is not None and current_popup != popup_fact:
            raise ValueError('popup_continuation_popup_changed')

    try:
        fresh = decision_frame(capture(), identity(), role='before')
        verify_identity()
        if (fresh['sha256'] != frame['sha256'] or fresh['window_identity'] != original_identity
                or _candidate(candidate, point) != selected
                or manager.read_owned_foreground_popup(manager.get_bound_window()) != popup_fact):
            raise ValueError('popup_changed_while_deciding')
        if revalidate_target is not None:
            revalidate_target()
    except Exception as error:
        _reject(scope, 'popup_decision_stale', {**result, 'status': 'invalidated',
            'error_type': type(error).__name__})
    result.update(freshness_revalidated=True, gate_applied=True, popup_handle=popup,
        reason='popup_can_be_ignored', automatic_retry_allowed=False)
    scope['result'] = deepcopy(result)
    guard = PopupContinuationGuard(_ISSUER, scope=scope, bound=bound,
        point=(point['x'], point['y']), bbox=bbox, popup_handle=popup,
        click_count=click_count, verify=verify_identity)
    return guard, result


def _combined_popup_guard(combined, *, manager, identity, point, bbox, click_count,
                          expected_owned_popup_handle):
    from .action_review import current_action_review
    if combined.get("scope") is not current_action_review():
        raise ValueError("combined_popup_review_scope_invalid")
    combined["validate"]()
    detect = getattr(manager, "get_owned_foreground_popup_handle", None)
    if not callable(detect) or expected_owned_popup_handle is not None:
        return None, None
    bound = manager.get_bound_window()
    popup = detect(bound)
    if popup is None:
        return None, None
    hit = manager.validate_bound_point_visibility(bound=bound, x=point["x"], y=point["y"])
    if (hit.get("hit_window") or {}).get("root_handle") == popup:
        return None, None
    fact = manager.read_owned_foreground_popup(bound)
    rect = (fact or {}).get("rect")
    original_bound, original_identity = _bound_snapshot(bound), _identity(identity())
    if (bbox is None or not isinstance(fact, dict) or fact.get("handle") != popup
            or fact.get("parent_handle") != bound.handle or fact.get("process_id") != bound.process_id
            or not isinstance(rect, (list, tuple)) or len(rect) != 4
            or any(type(v) is not int for v in rect)
            or not (bound.rect.left <= rect[0] < rect[2] <= bound.rect.right
                and bound.rect.top <= rect[1] < rect[3] <= bound.rect.bottom)):
        _reject(combined["scope"], "combined_popup_not_in_reviewed_frame")
    def verify():
        combined["validate"]()
        if (_bound_snapshot(manager.get_bound_window()) != original_bound
                or _identity(identity()) != original_identity
                or manager.read_owned_foreground_popup(manager.get_bound_window()) != fact):
            raise ValueError("combined_popup_changed_after_review")
    return PopupContinuationGuard(_ISSUER, scope=combined["scope"], bound=bound,
        point=(point["x"], point["y"]), bbox=bbox, popup_handle=popup,
        click_count=click_count, verify=verify), {"source": "combined_candidate_review",
            "additional_requests": 0, "authorizes_action": False}
