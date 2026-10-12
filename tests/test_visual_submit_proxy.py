"""提交能力穿过真实命令代理，不重复定位；这里只替换物理动作出口。"""
from copy import deepcopy
from threading import Condition
from types import SimpleNamespace as NS

import pytest
from app.vision.agent_command_jobs import _CoordinatorProxy, AgentCommandError
from tests.test_visual_submit_target import submission, scene, FIELD


@pytest.mark.parametrize('fault', [None, 'cancel', 'wrong_target', 'wrong_goal', 'wrong_review', 'dispatch_error'])
def test_submit_proxy_keeps_original_capability_and_dispatch_boundary(submission, fault):
    v = submission
    events = []
    result = {'phase':'returned','response':{'success':True},'local_input_scope_closed':True}
    def execute(**kwargs):
        events.append(('dispatch', kwargs))
        if fault == 'dispatch_error': raise RuntimeError('offline dispatch exception')
        return result
    manager = NS(coordinator=NS(_decision_service=v.s.service, execute_local_step=execute),
        _condition=Condition(),
        _remaining_action_review=lambda job: 1,
        _update=lambda *a,**kw: None,
        _begin_dispatch=lambda job,op: events.append(('begin',op)) or 1,
        _record_receipt=lambda job,r,op,index: events.append(('receipt',r,op,index)),
        _record_unknown=lambda job,op,index: events.append(('unknown',op,index)))
    context = deepcopy(v.target._context)
    if fault == 'wrong_review': context['attempt_id'] = 'different'
    job = NS(manager=manager, cancelled=fault=='cancel', action_review=context,
        action_review_deadline_ns=v.s.context['deadline_ns'],learning_context=None)
    kwargs={'target_window_handle':10,'target_process_id':20,'operation':'execute_recognition_plan',
        'request':{'goal':FIELD['field_goal'] if fault!='wrong_goal' else 'another field'},
        'grounding_target':object() if fault=='wrong_target' else v.target}
    if fault:
        expected = RuntimeError if fault=='dispatch_error' else AgentCommandError
        match = 'dispatch exception' if fault=='dispatch_error' else ('cancelled' if fault=='cancel' else 'prepared_visual_submit_target_invalid')
        with pytest.raises(expected,match=match): _CoordinatorProxy(job).execute_local_step(**kwargs)
        if fault=='dispatch_error':
            assert [e[0] for e in events] == ['begin','dispatch','unknown']
        else: assert events == []
    else:
        assert _CoordinatorProxy(job).execute_local_step(**kwargs) is result
        assert [e[0] for e in events] == ['begin','dispatch','receipt']
        actual=events[1][1]
        assert actual['grounding_target'] is v.target
        assert actual['action_review'] == v.target._context
        assert actual['action_review_deadline_ns'] == job.action_review_deadline_ns
        assert actual['input_cancelled']() is False
        job.cancelled=True
        assert actual['input_cancelled']() is True
        assert len(v.s.requests)==1
