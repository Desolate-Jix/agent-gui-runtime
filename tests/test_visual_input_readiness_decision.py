"""真实请求边界验证点击可输入审核，不再把可见焦点加入普通执行。"""
from copy import deepcopy
import json

import pytest

from test_decision_choice import runtime, choice_reply
from test_executed_click_integration import arguments
from test_field_content_choice import response

READY = "The marked click is inside the intended visible text input and the field is usable for typing now."
REPLACE = "The intended text input is empty or its complete existing text is selected for replacement."


def ready_request(root):
    args = arguments(root)
    args['condition'] = READY
    args['action']['field_content_check'] = {'schema':'visual_field_content.v1', 'clear_existing':True}
    return args


@pytest.mark.parametrize('choice,adopted', [('condition_met', True), ('condition_not_met',False), ('evidence_insufficient',False)])
def test_marked_input_readiness_has_no_focus_or_future_task_question(tmp_path, monkeypatch, choice, adopted):
    args = ready_request(tmp_path)
    original = deepcopy(args)
    service, calls, client = runtime(tmp_path, monkeypatch, body=response(choice), profile={'auto_conditions':[READY]})
    try:
        result = service.evaluate(**args)
        assert result['status'] == 'completed' and result['adopted'] is adopted
        assert result['choice_result']['choice'] == choice
        assert service.validate_result(result, **args)
        assert service.evaluate(**args) == result and len(calls) == 1
        body = json.loads(calls[0].content)
        assert [q['name'] for q in body['questions']] == ['current_step','field_content']
        question = json.dumps(body['questions']).lower()
        assert 'marked' in question and 'input' in question and 'can text be entered' in question
        assert 'existing text is not ready for replacement' not in question
        for removed in ('focus','caret','playback','continuity','future','selected input text'):
            assert removed not in question
        parts = body['input'][0]['content']
        assert len([p for p in parts if p['type']=='input_image']) == 1
        text = ' '.join(p['text'] for p in parts if p['type']=='input_text')
        assert 'proof of present focus' not in text
        assert 'remaining_plan' not in text and 'expected_text' not in text
        assert args == original
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize('damage', ['missing_click','wrong_stage','two_frames'])
def test_new_input_readiness_never_sends_an_unbound_or_old_focus_payload(tmp_path, monkeypatch, damage):
    args = ready_request(tmp_path)
    if damage == 'missing_click': args['action'].pop('executed_click')
    elif damage == 'wrong_stage':
        args['action'].pop('field_content_check')
        args['action']['focus_stage'] = 'after_selection'
    else:
        args['frames'].insert(0,{**deepcopy(args['frames'][0]),'capture_id':'previous','role':'before'})
    service, calls, client = runtime(tmp_path, monkeypatch, body=response(), profile={'auto_conditions':[READY]})
    try:
        result = service.evaluate(**args)
        assert result['adopted'] is False
        assert calls == []
    finally:
        service.close()
        client.close()


def test_replacement_question_checks_text_selection_without_focus(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    args['condition'] = REPLACE
    args['action']['focus_stage'] = 'after_selection'
    args['frames'].insert(0,{**deepcopy(args['frames'][0]),'capture_id':'previous','role':'before'})
    service, calls, client = runtime(tmp_path, monkeypatch, profile={'auto_conditions':[REPLACE]})
    try:
        result = service.evaluate(**args)
        assert result['adopted'] is True
        body = json.loads(calls[0].content)
        question = json.dumps(body['questions']).lower()
        assert 'selected' in question and 'replacement' in question
        assert 'focus' not in question and 'caret' not in question and 'playback' not in question
    finally:
        service.close()
        client.close()
