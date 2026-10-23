"""面向 Agent 的精简投影；完整回执仍由原会话保存，不改写执行事实。"""
from copy import deepcopy


def _pre_action_packet(packet):
    if not isinstance(packet, dict) or packet.get('schema') != 'pre_action_review_packet.v1':
        return None
    value = {key: deepcopy(packet[key]) for key in ('schema', 'stage', 'reason', 'command_id', 'session_directory', 'owner_id',
        'execution_request_id', 'run_id', 'step_id', 'attempt_id', 'plan_sha256', 'target_identity',
        'window_rect', 'candidate', 'before', 'packet_sha256', 'evidence_set_sha256', 'assessment_round',
        'profile_sha256', 'original_receipt_id', 'original_receipt_sha256', 'original_input_status',
        'action_executed', 'main_wait_deadline_ns', 'authorizes_action', 'automatic_retry_allowed', 'image') if key in packet}
    assessment = packet.get('assessment') or {}
    raw = (assessment.get('judgment') or {}).get('judgment_result') or {}
    ordinary = raw.get('ordinary_review') or {}
    value['original_refusal'] = {'disposition': assessment.get('disposition'),
        'envelope_sha256': assessment.get('envelope_sha256'), 'status': raw.get('status'),
        'adopted': raw.get('adopted'), 'choice_result': deepcopy(raw.get('choice_result')),
        'ordinary_status': ordinary.get('status'), 'ordinary_result': deepcopy(ordinary.get('review_result'))}
    return value


def _compact_steps(steps):
    summaries = []
    for row in steps:
        summary = {key: deepcopy(row.get(key)) for key in
            ("name", "operation", "status", "action_executed", "elapsed_ms")}
        response = (row.get("receipt") or {}).get("response") or {}
        if response.get("error"):
            summary["error"] = deepcopy(response["error"])
        data = response.get("data") or {}
        action = data.get("result", data)
        if action.get("failure_reason"):
            summary["failure_reason"] = deepcopy(action["failure_reason"])
        summaries.append(summary)
    return summaries


def _field_review_packet(packet):
    if not isinstance(packet, dict) or packet.get("schema") != "field_review_packet.v1":
        return None
    # 原包已绑定公开证据；不把 worker 私有状态或未知调试字段扩张到附件。
    value = {key: deepcopy(packet[key]) for key in (
        "schema", "run_id", "step_id", "execution_request_id", "command_id", "owner_id", "plan_id", "plan_sha256",
        "target_identity", "stage", "reason", "request", "assessment", "progress_snapshot",
        "progress_snapshot_ref", "evidence_refs", "packet_sha256", "evidence_set_sha256",
        "assessment_round", "original_input_status", "action_executed", "authorizes_action",
        "automatic_retry_allowed") if key in packet}
    after = packet.get("after")
    if isinstance(after, dict):
        value["after"] = {key: deepcopy(after[key]) for key in (
            "image_path", "sha256", "capture_id", "frame_id", "window_size", "window_identity",
            "target_identity", "observation_stage") if key in after}
    return value


def compact_receipt(receipt, *, full_receipt_path=None):
    result = receipt.get("result") or {}
    api = result.get("response") or {}
    data = api.get("data") or {}
    action = data.get("result", data)
    keys = ("request_id", "status", "operation_succeeded", "operation_success_scope",
        "input_route_succeeded", "task_effect_verified", "automatic_retry_allowed",
        "observation_status", "started_at", "finished_at", "command_wall_ms", "error", "error_type",
        "diagnostics", "desktop_context", "agent_review", "decision_judgment", "decision_validation", "next", "accepted", "action_executed",
        "wait_expired", "command_cancelled", "partial_execution", "next_action", "learning_recording", "learning_recording_error", "learning_binding", "learning_control")
    value = {key: deepcopy(receipt[key]) for key in keys if key in receipt}
    pre_action = _pre_action_packet(result.get('review_packet') or result.get('pending_pre_action_review')
        or (result.get('pre_action_review') or {}).get('packet'))
    if pre_action is not None:
        # Place actionable controls/evidence before verbose status history.
        value = {'pre_action_review': pre_action,
            'caller_controls': deepcopy(result.get('caller_controls')), **value}
    value["receipt_detail"] = "compact"
    value["full_receipt"] = {"tool": "instant_result", "arguments": {
        "request_id": receipt.get("request_id"), "detail": "full", "images": "none"},
        "path": str(full_receipt_path) if full_receipt_path is not None else None}
    if result.get('contract_version') == 'agent_command.v1':
        value['agent_command'] = {key: deepcopy(result[key]) for key in (
            'contract_version', 'command_id', 'status', 'pending_grounding',
            'action_executed', 'cancel_requested', 'error', 'automatic_retry_allowed',
            'api_request', 'recognition_calls', 'pre_action_resolution') if key in result}
        field_review = _field_review_packet(result.get("pending_field_review"))
        if field_review is not None:
            value["agent_command"]["pending_field_review"] = field_review
        if pre_action is not None:
            value['agent_command']['pending_pre_action_review'] = pre_action
            review = result.get('pre_action_review') or {}
            value['agent_command']['main_review'] = {key: deepcopy(review[key]) for key in (
                'review', 'review_request_id', 'continued', 'continue_request_id') if key in review}
        for key in ('progress', 'result'):
            if isinstance(result.get(key), dict):
                projected = compact_receipt({'request_id': receipt.get('request_id'), 'result': result[key]})
                value['agent_command'][key] = {name: projected[name] for name in (
                    'form', 'sequence', 'action', 'error', 'message', 'observation', 'image', 'decision_judgment') if name in projected}
    elif result.get("contract_version") == "form_fill_v1":
        value["form"] = {key: deepcopy(result[key]) for key in (
            "status", "phase", "completed_fields", "interrupted_at", "action_executed",
            "error", "total_ms", "next_action", "requested_fields", "remaining_fields", "text_navigation") if key in result}
        value["form"]["fields"] = [{key: deepcopy(row[key]) for key in (
            "index", "kind", "status", "check", "error", "action_executed", "option_match", "available_options", "timings") if key in row}
            for row in result.get("fields", [])]
        for row, summary in zip(result.get("fields", []), value["form"]["fields"]):
            if row.get("status") == "interrupted" and row.get("steps"):
                summary["steps"] = _compact_steps(row["steps"])
    elif result.get("contract_version") == "input_sequence_v1":
        value["sequence"] = {key: deepcopy(result.get(key)) for key in (
            "sequence_id", "status", "completed_steps", "interrupted_at", "input_check",
            "action_executed", "error", "total_ms", "next_action", "selected_click_point",
            "selected_click_point_coordinate_space", "check_timings", "main_handoff") if key in result}
        value["sequence"]["steps"] = _compact_steps(result.get("steps", []))
        value["observation"] = {key: deepcopy(result.get("observation", {}).get(key)) for key in
            ("status", "error_code", "next_action", "recovery") if key in result.get("observation", {})}
    elif result.get("contract_version") == "local_direct_step_v1":
        value["action"] = {key: deepcopy(action[key]) for key in (
            "selected_click_point", "selected_click_point_coordinate_space", "coordinate_source",
            "click_kind", "dispatch_status", "pressed") if key in action}
        value["action"].update(operation=result.get("operation"), phase=result.get("phase"),
            action_executed=(action.get("execution_path") or {}).get("action_executed", action.get("pressed")))
        proof = result.get("row_selection_proof")
        if isinstance(proof, dict):
            value["action"]["selection"] = {key: deepcopy(proof[key]) for key in (
                "contract_version", "status", "action_required", "state_satisfied", "sha256") if key in proof}
            value["action"]["selection"]["proof_verified"] = False
        if api.get("error"):
            value["error"] = deepcopy(api["error"])
        if api.get("message"):
            value["message"] = api["message"]
    else:
        # 发现结果、正文和窗口身份是下一步决策必需信息，不作无差别截断。
        if pre_action is not None:
            value['result'] = {key: deepcopy(result[key]) for key in ('run_id', 'status', 'runner_state',
                'wait_reason', 'wait', 'pending', 'allowed_controls', 'review_required', 'review_scope') if key in result}
        elif result:
            value["result"] = deepcopy(result)
    assessment = result.get("action_assessment", action.get("action_assessment"))
    if isinstance(assessment, dict):
        value["action_assessment"] = {key: deepcopy(assessment[key]) for key in
            ("schema", "scope", "disposition", "reason", "envelope_sha256", "freshness", "authorizes_action")
            if key in assessment}
    observation = result.get("observation") or {}
    if observation.get("condition") is not None:
        value.setdefault("observation", {}).update({key: deepcopy(observation[key]) for key in
            ("status", "readiness", "condition") if key in observation})
        # 每轮只读样本留完整日志；精简回执仍保留条件、时长、超时和末帧摘要。
        samples = value["observation"]["condition"].pop("samples", [])
        value["observation"]["condition"]["sample_count"] = len(samples)
    capture = receipt.get("observation") or observation.get("capture")
    if capture:
        value["image"] = {key: deepcopy(capture.get(key)) for key in
            ("image_path", "sha256", "window_size", "frame_id", "observation_stage") if key in capture}
    return value
