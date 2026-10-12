"""显式零输入恢复的证据与许可；不派发输入、不替代原动作门禁。"""
from copy import deepcopy
from hashlib import sha256

from app.core.json_snapshot import read_json_snapshot
from app.core.recognition_dispatch import local_receipt_zero_input_verified
from app.learning_memory.receipt_adapter import resolve_execution_receipt
from app.learning_memory.workflow_trial import _actual_action_executed, _execution_identity, _receipt_state
from .task_plan_review import pending_packet, validate_packet


def zero_input_verified(backend, state, pending):
    path = backend.session / 'responses' / (pending['execution_request_id'] + '.json')
    original = read_json_snapshot(path)
    command = pending['suggested_command']
    if original.get('command') != command:
        return False
    succeeded, terminal, _ = _receipt_state(original, path, pending['execution_request_id'], command)
    effective, resolved = resolve_execution_receipt(original, path, pending['execution_request_id'])
    result = effective.get('result')
    if succeeded or terminal != resolved or _actual_action_executed(result, terminal) is not False:
        return False
    if _execution_identity(effective) != state['target_identity']:
        return False
    if command.get('kind') == 'step' and command.get('operation') == 'execute_recognition_plan':
        return local_receipt_zero_input_verified(result, 'execute_recognition_plan')
    if command.get('kind') == 'input_sequence' and isinstance(result, dict):
        rows = result.get('steps')
        return bool(rows) and all(isinstance(row, dict) and row.get('action_executed') is False
            and row.get('status') == (row.get('receipt') or {}).get('phase')
            and local_receipt_zero_input_verified(row.get('receipt'), row.get('operation', 'execute_recognition_plan'))
            for row in rows)
    return False


def checked_block(backend, state, request):
    pending = state.get('pending')
    if (state.get('recovery_policy', 'legacy') != 'intervention_v1' or state['status'] != 'pending'
            or state.get('cancel_requests') or (backend.session / 'closing.json').exists() or not pending):
        raise ValueError('task_plan_intervention_unavailable_or_cancelled')
    packet = pending_packet(state)
    if packet is None or packet.get('reason') not in {'blocked_before_dispatch', 'repeated_obstruction'}:
        raise ValueError('task_plan_intervention_zero_input_required')
    validate_packet(packet, state, backend.session)
    if (any(request.get(key) != packet.get(key) for key in
            ('run_id', 'wait_id', 'step_id', 'execution_request_id', 'evidence_set_sha256', 'assessment_round'))
            or request.get('review_packet_sha256') != packet['packet_sha256']):
        raise ValueError('task_plan_intervention_wait_binding_mismatch')
    result = next(value for value in state['verification_results'].values()
        if value.get('review_packet') == packet)
    backend._evidence(state, pending, result, request_id='intervention', decision_service=None)
    if not zero_input_verified(backend, state, pending):
        raise ValueError('task_plan_intervention_zero_input_unproven')
    if packet['reason'] == 'repeated_obstruction':
        raise ValueError('task_plan_intervention_repeated_obstruction_limit')
    return packet


def recovery_command(value):
    from app.instant_mcp import InstantCommand
    if (not isinstance(value, dict) or value.get('kind') != 'step'
            or value.get('operation') != 'execute_recognition_plan'):
        raise ValueError('task_plan_recovery_gated_click_required')
    checked = InstantCommand.model_validate(value).command()
    if checked != value:
        raise ValueError('task_plan_recovery_command_normalization_mismatch')
    # 此命令仍经过原识别、动作分类和授权门禁，不接受已有坐标的直接重放。
    if set(value.get('request') or {}) - {'goal', 'click_kind'}:
        raise ValueError('task_plan_recovery_fresh_grounding_required')
    return deepcopy(checked)


def assert_recovery_settled(backend, state, *, allow_no_dispatch=False):
    permit = state.get('intervention_recovery')
    if not permit:
        return
    execution_id = permit['recovery_request_id']
    path = backend.session / 'responses' / (execution_id + '.json')
    if not path.is_file():
        raise ValueError('task_plan_recovery_unsettled')
    original = read_json_snapshot(path)
    succeeded, terminal, _ = _receipt_state(original, path, execution_id, permit['command'])
    effective, resolved = resolve_execution_receipt(original, path, execution_id)
    result = effective.get('result')
    actual = _actual_action_executed(result, terminal)
    known_zero = allow_no_dispatch and actual is False and local_receipt_zero_input_verified(result)
    if (terminal != resolved or not (succeeded and actual is True or known_zero)
            or _execution_identity(effective) != state['target_identity']):
        raise ValueError('task_plan_recovery_unsettled_or_unknown')
    paths = [backend.session / 'commands' / (execution_id + '.json'), path]
    if terminal is not None:
        from pathlib import Path
        paths.append(Path(terminal['path']))
    refs = []
    for item in paths:
        if not item.resolve(strict=True).is_relative_to(backend.session):
            raise ValueError('task_plan_recovery_evidence_outside_session')
        refs.append({'path': item.relative_to(backend.session).as_posix(), 'sha256': sha256(item.read_bytes()).hexdigest()})
    return {'schema': 'task_plan_recovery_settlement.v1', 'recovery_request_id': execution_id,
        'action_executed': actual, 'evidence_refs': refs}


def assert_queue_quiet(runtime, *, ignore=()):
    ignored = set(ignore)
    for path in (runtime.session / 'commands').glob('*.json'):
        if path.stem in ignored:
            continue
        if not (runtime.session / 'responses' / path.name).is_file():
            raise ValueError('task_plan_recovery_queue_not_quiescent')
        if runtime._read_result(path.stem)['status'] not in {'completed', 'failed', 'cancelled'}:
            raise ValueError('task_plan_recovery_queue_not_quiescent')
        command = read_json_snapshot(path)
        if command.get('kind') in {'step', 'input_sequence', 'form_fill', 'grounding_execute'}:
            response_path = runtime.session / 'responses' / path.name
            receipt = read_json_snapshot(response_path)
            succeeded, terminal, _ = _receipt_state(receipt, response_path, path.stem, command)
            effective, resolved = resolve_execution_receipt(receipt, response_path, path.stem)
            if terminal != resolved or not succeeded and _actual_action_executed(effective.get('result'), terminal) is not False:
                raise ValueError('task_plan_recovery_queue_input_unknown')
    for path in (runtime.session / 'agent-commands').glob('*.json'):
        if read_json_snapshot(path).get('status') not in {'completed', 'failed', 'cancelled'}:
            raise ValueError('task_plan_recovery_agent_job_not_quiescent')
