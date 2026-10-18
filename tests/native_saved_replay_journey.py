"""新宿主读取本轮确切流程版本，再由真实 Agent 请求两次独立受控动作。"""
import json


def run_saved_replay_journey(*, call_agent, human_step, result, handle, target_pid,
                             task, publication, memory, focus):
    tools = ['agent_link_status', 'get_workflow_memory', 'start_learning_segment',
             'get_learning_segment', 'finish_learning_segment', 'prepare_learning_runtime',
             'request_learning_action', 'get_learning_action_result', 'cancel_learning_runtime']
    common = (
        f'只使用Agent Review MCP核对task_id={task}。不调用shell/web，不审批、不执行输入。'
        f'读取get_workflow_memory(workflow_id={publication["logical_workflow_id"]},version={publication["version_id"]})。'
        f'核对asset_id={memory["asset_id"]}，asset_sha256={memory["asset_sha256"]}。'
        '这是本轮全新mock学习后保存、关闭并重开的确切版本，不允许重学或使用旧坐标。'
        '公开工具错误立即停止，不能用文字宣称成功。'
    )
    prior = None
    for index, (semantic, goal, state) in enumerate([
        ('open_detail', '查看示例详情', 'detail'), ('back', '返回列表', 'list')]):
        focus()
        if index == 0:
            phase = f'start_learning_segment，idempotency_key={task}-start，title=本轮保存重开流程复用。'
        else:
            phase = (f'同一segment_id={result["segment_id"]}，先读取get_learning_action_result，'
                     f'preparation_id={prior}。核对真实回执及图片；确认已结束后cancel_learning_runtime释放旧准备。')
        prompt = common + phase + (
            f'调用prepare_learning_runtime绑定以上确切asset/id/hash与target_window_handle={handle},'
            f'target_process_id={target_pid},idempotency_key={task}-prepare-{index}。'
            f'仅observed时，从实际actions中选择semantic_action={semantic}、表示{goal}的action_id，'
            f'然后request_learning_action，intent_id=s72-replay-intent-{index}，其他身份用真实返回值。'
            '核对pending_review，停下等待获授权的自有fixture测试操作员审核。只请求，不执行下一步。')
        calls = call_agent(f'replay-{index}-preview', prompt, tools)
        memories = [call for call in calls if call['tool'] == 'get_workflow_memory']
        assert memories and memories[0]['result']['structured_content'] == memory
        if index == 0:
            starts = [call for call in calls if call['tool'] == 'start_learning_segment']
            assert len(starts) == 1
            result['segment_id'] = starts[0]['result']['structured_content']['segment_id']
        prepared = [call for call in calls if call['tool'] == 'prepare_learning_runtime']
        assert len(prepared) == 1
        preparation = prepared[0]['result']['structured_content']
        assert preparation['phase'] == 'observed', preparation
        requested = [call for call in calls if call['tool'] == 'request_learning_action']
        assert len(requested) == 1 and requested[0]['result']['structured_content']['phase'] == 'pending_review'
        selected = next(action for action in preparation['actions']
                        if action['action_id'] == requested[0]['arguments']['action_id'])
        assert selected['semantic_action'] == semantic
        prior = preparation['preparation_id']
        human_step(f'replay-{index}', state, prior)
    call_agent('replay-final-read', common +
        f'只读核对segment_id={result["segment_id"]},preparation_id={prior}的get_learning_action_result和事后图；'
        'cancel_learning_runtime释放本次准备，get_learning_segment核对事件，使用确切最新revision结束学习段。'
        '不执行任何新动作，区分回执和可见结果，没有安装版验收。', tools)
    result['saved_reopened_two_transition_target_verified'] = True
    result['full_journey_verified'] = False
