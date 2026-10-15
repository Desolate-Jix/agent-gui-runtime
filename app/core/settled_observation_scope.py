"""正式本地步骤承接泛用诊断；能力只在同次 owner 调用内有效。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
import json
from threading import get_ident

from app.core.local_input_policy import current_local_operator_identity, _window_rect


_ACTIVE = ContextVar('settled_observation_owner', default=None)
_ISSUER = object()


def _digest(request):
    return sha256(json.dumps(request, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


class _DiagnosticPermit:
    def __init__(self, scope, *, _issuer):
        if _issuer is not _ISSUER:
            raise PermissionError('settled observation permit issuer unavailable')
        self.scope, self.used = scope, False
        self.issuer = _issuer


def _matches(scope, manager):
    if (scope is None or not scope['active'] or scope['thread'] != get_ident()
            or scope['manager'] is not manager):
        return False
    try:
        if current_local_operator_identity(manager) != scope['identity']:
            return False
        bound = manager.get_bound_window()
        return (bound is not None and bound.handle == scope['identity']['target_window_handle']
            and bound.process_id == scope['identity']['process_id']
            and _window_rect(bound) == scope['window_rect'])
    except PermissionError:
        return False


def before_capture_sharing_eligible(request, *, shared_observation):
    if shared_observation is not True:
        return False
    from app.core.agent_grounding_target import AgentGroundingTarget, current_agent_grounding
    from app.core.visual_submit_target import VisualSubmitTarget
    if type(current_agent_grounding()) not in {AgentGroundingTarget, VisualSubmitTarget}:
        return False
    from app.api.action import _execute_plan_request_defaults
    from app.api.models.request import ExecuteRecognitionPlanRequest
    _, effective_metadata = _execute_plan_request_defaults(ExecuteRecognitionPlanRequest.model_validate(request))
    metadata = request.get('metadata') or {}
    # 与正式路由使用同一解析结果，不能把调用方 metadata 当作内部路由事实。
    return (effective_metadata.get('execution_grounding') == 'direct_visual'
        and request.get('capture_live') is True and request.get('agent_mode') == 'execute'
        and request.get('dry_run') is False and request.get('click_kind') == 'single'
        and not metadata.get('verification_policy')
        and not any(request.get(key) is not None for key in ('capture_roi', 'target_memory', 'selection_intent',
            'image_path', 'observe_trace_path', 'approved_plan_id', 'learned_instruction_id',
            'interface_memory_id', 'interface_memory_action_id', 'learning_mode'))
        and request.get('auto_observe_learning_artifacts') is False
        and request.get('allow_saved_image_execution') is False
        and not any((request.get('write_policy') or {}).get(key) for key in ('path_graph', 'element_memory')))


@contextmanager
def _settled_observation_scope(*, owner, manager, identity, window_rect, step_id, request, caller, verifier,
                               before_capture=None):
    if _ACTIVE.get() is not None:
        raise PermissionError('settled observation scopes cannot overlap')
    if owner is None or not isinstance(step_id, str) or not step_id or not callable(caller):
        raise ValueError('settled observation owner binding invalid')
    if before_capture is not None and not callable(before_capture):
        raise ValueError('before_capture callback invalid')
    scope = {'owner': owner, 'manager': manager, 'identity': deepcopy(identity),
        'window_rect': tuple(window_rect), 'step_id': step_id, 'request_sha256': _digest(request),
        'caller': caller, 'verifier': verifier, 'thread': get_ident(), 'active': True, 'claimed': False,
        'before_capture': before_capture, 'before_published': False}
    if not _matches(scope, manager):
        if before_capture is not None:
            raise PermissionError('before_capture scope binding invalid')
        yield
        return
    token = _ACTIVE.set(scope)
    try:
        yield
    finally:
        # 已复制的 Context 同时失效，不留下跨步骤的诊断承接许可。
        scope['active'] = False
        _ACTIVE.reset(token)


def publish_before_capture(*, manager, request, caller, verifier, capture):
    scope = _ACTIVE.get()
    if scope is None or scope.get('before_capture') is None:
        return False
    if not scope['active']:
        return False
    if (not _matches(scope, manager) or scope['before_published'] or scope['caller'] is not caller
            or scope['verifier'] is not verifier or scope['request_sha256'] != _digest(request)):
        raise PermissionError('before_capture publication binding invalid')
    # 发布失败也不重试或接受替代图；回调先完成原字节持久化才返回。
    scope['before_published'] = True
    scope['before_capture'](deepcopy(capture))
    if not _matches(scope, manager):
        raise PermissionError('before_capture window changed during publication')
    return True


def claim_settled_observation(*, manager, request, caller, verifier):
    scope = _ACTIVE.get()
    if (not _matches(scope, manager) or scope['claimed'] or scope['caller'] is not caller
            or scope['verifier'] is not verifier or scope['request_sha256'] != _digest(request)):
        return None
    scope['claimed'] = True
    return _DiagnosticPermit(scope, _issuer=_ISSUER)


def consume_settled_observation(permit, *, verifier, action_name, before_state, click_result):
    if type(permit) is not _DiagnosticPermit or permit.issuer is not _ISSUER:
        raise PermissionError('settled observation permit invalid')
    scope = permit.scope
    if (permit.used or _ACTIVE.get() is not scope or not _matches(scope, scope['manager'])
            or scope['verifier'] is not verifier or action_name != 'execute_recognition_plan'
            or (before_state or {}).get('window_handle') != scope['identity']['target_window_handle']
            or (click_result or {}).get('clicked') is not True):
        raise PermissionError('settled observation permit binding changed')
    permit.used = True
    return {'schema': 'settled_observation_ref.v1', 'step_id': scope['step_id'],
        'field': 'observation.capture', 'window_identity': {
            'handle': scope['identity']['target_window_handle'],
            'process_id': scope['identity']['process_id'],
            'process_create_time': scope['identity']['process_create_time']}}
