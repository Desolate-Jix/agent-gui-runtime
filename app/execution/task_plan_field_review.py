"""原输入命令的主 Agent 审核等待；审核只记录，显式继续才唤醒原工作线程。"""
from copy import deepcopy

from .task_plan_cancellation import assert_no_queued_plan_cancel


def current_field_review(runtime, snapshot):
    pending = snapshot.get('pending')
    getter = getattr(runtime.agent_jobs, 'get_field_review', None)
    if (not pending or not callable(getter) or snapshot.get('status') != 'pending'
            or snapshot.get('wait_reason') != 'verification_required'):
        return None
    value = getter(pending['execution_request_id'])
    if value is None or value.get('continued') is True:
        return None
    packet = value.get('packet') or {}
    expected = {'run_id': snapshot['run_id'], 'step_id': pending['step_id'],
        'execution_request_id': pending['execution_request_id'], 'plan_sha256': snapshot['plan_sha256']}
    if (packet.get('schema') != 'field_review_packet.v1'
            or any(packet.get(key) != item for key, item in expected.items())):
        raise ValueError('task_plan_field_review_binding_mismatch')
    return value


def project_field_review(runtime, snapshot):
    value = current_field_review(runtime, snapshot)
    if value is None:
        return None
    packet, review = value['packet'], value.get('review')
    result = deepcopy(snapshot)
    result.update(review_packet=deepcopy(packet), review_required=True,
        review_scope='input_value', allowed_controls=['cancel'])
    controls = {'schema': 'task_plan_caller_controls.v1', 'authorizes_action': False}
    if review is None:
        controls['review'] = {'caller_supplied_fields': ['verdict', 'reason'], 'request': {
            'action': 'review', 'run_id': packet['run_id'], 'step_id': packet['step_id'],
            'execution_request_id': packet['execution_request_id'],
            'evidence_sha256': packet['after']['sha256'], 'review_packet_sha256': packet['packet_sha256'],
            'evidence_set_sha256': packet['evidence_set_sha256'], 'assessment_round': packet['assessment_round']}}
        result['allowed_controls'].append('review')
    elif review['verdict'] == 'success':
        controls['continue'] = {'request': {'action': 'continue', 'run_id': packet['run_id'],
            'wait_id': snapshot['wait']['wait_id']}}
        result['allowed_controls'].append('continue')
        result['field_review'] = deepcopy(review)
    else:
        result['field_review_pending_settlement'] = True
    if 'review' in controls or 'continue' in controls:
        result['caller_controls'] = controls
    return result


def _check_control(runtime, snapshot):
    runtime.backend.validate_resume(snapshot['run_id'], None)
    assert_no_queued_plan_cancel(runtime.session, snapshot['run_id'])
    if runtime._target_identity() != snapshot['target_identity']:
        raise ValueError('task_plan_field_review_target_changed')


def control_field_review(runtime, snapshot, request, request_id):
    value = current_field_review(runtime, snapshot)
    if value is None:
        return None
    _check_control(runtime, snapshot)
    execution_id = value['packet']['execution_request_id']
    if request['action'] == 'review':
        runtime.agent_jobs.review_field(execution_id, request_id, request)
        result = runtime._review_snapshot(runtime.runner.status(snapshot['run_id']))
        if request['verdict'] == 'failure':
            # 拒绝只唤醒原命令退出，后续轮询负责结算原输入事实。
            runtime._enabled_run = snapshot['run_id']
        return result
    if not value.get('review') or value['review']['verdict'] != 'success':
        raise ValueError('task_plan_field_review_required_before_continue')
    # 先验证并保存原 wait 的继续请求，再唤醒；失败后相同请求可重试而不重放输入。
    runtime.runner.resume(snapshot['run_id'], request_id, request['wait_id'])
    _check_control(runtime, snapshot)
    runtime.agent_jobs.continue_field(execution_id, request_id)
    return runtime._remember_active(runtime.runner.advance(snapshot['run_id']))
