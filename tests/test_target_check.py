"""二选一路由只核验原目标图形或输入框内包含关系。"""
from copy import deepcopy
import json

import httpx
import pytest

from app.judgment import OpenAIDecisionsProvider
from test_luna_choice_review_provider import candidate_payload, decision_body, response_body


def contract():
    from app.judgment import target_check
    return target_check


DESCRIPTION = {'kind': 'graphic', 'appearance': 'A plus-shaped icon', 'container': 'Right of the active tab'}


def test_original_goal_and_input_action_choose_question_without_distractor_classes():
    module = contract()
    graphic = module.grounding_target_check('Plus button', DESCRIPTION)
    field = module.grounding_target_check('Browser address bar', DESCRIPTION, input_field=True)
    assert graphic == {'schema':'target_check.v1','kind':'graphic','target':'Plus button',
        'appearance':'A plus-shaped icon','container':'Right of the active tab'}
    assert field['kind'] == 'input_field' and field['target'] == 'Browser address bar'
    g, f = module.target_check_question(graphic), module.target_check_question(field)
    assert 'inside' not in g['instructions']
    assert 'inside' in f['instructions']
    assert 'Plus button' in g['instructions'] and 'Browser address bar' in f['instructions']
    assert [x['value'] for x in g['choices']] == [x['value'] for x in f['choices']] == [
        'condition_met','condition_not_met','evidence_insufficient']
    changed = deepcopy(DESCRIPTION)
    changed['appearance'] = 'A close cross, not a plus'
    wrong_hint = module.grounding_target_check('Plus button', changed)
    assert module.target_check_question(wrong_hint) == g
    changed['kind'] = 'input_field'
    wrong_kind = module.grounding_target_check('Plus button', changed, input_field=False)
    assert wrong_kind['kind'] == 'graphic'
    assert module.target_check_question(wrong_kind) == g


@pytest.mark.parametrize('damage', ['kind','target','appearance','container','extra'])
def test_invalid_check_is_rejected(damage):
    module = contract()
    value = module.grounding_target_check('Plus button', DESCRIPTION)
    value[damage] = 'unknown' if damage == 'kind' else ''
    with pytest.raises(ValueError, match='target_check'):
        module.normalize_target_check(value)


@pytest.mark.parametrize('kind', ['graphic','input_field'])
def test_both_models_receive_one_same_question_and_marked_image_only(monkeypatch, kind):
    monkeypatch.setenv('TARGET_CHECK_OFFLINE_KEY','offline-no-network')
    calls=[]
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json=decision_body() if request.url.path.endswith('decisions') else response_body())
    value = candidate_payload()
    value['action']['target_check'] = {'schema':'target_check.v1','kind':kind,'target':'Plus button' if kind=='graphic' else 'Browser address bar',
        'appearance':'UNVERIFIED_HINT','container':'LOCAL_CONTAINER'}
    value['action']['goal'] = 'UNRELATED_GLOBAL_TASK'
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider=OpenAIDecisionsProvider(api_key_env='TARGET_CHECK_OFFLINE_KEY',client=client)
        first=provider.judge(value)
        second=provider.review(value)
    question=calls[0]['questions'][0]
    review_text=calls[1]['input'][0]['content'][-1]['text']
    assert len(calls[0]['questions'])==1
    assert question['name']=='current_step'
    assert question == contract().target_check_question(value['action']['target_check'])
    assert json.dumps(question,ensure_ascii=False,sort_keys=True) in review_text
    assert calls[1]['input'][0]['content'][:-1] == calls[0]['input'][0]['content']
    assert len([p for p in calls[0]['input'][0]['content'] if p['type']=='input_image'])==1
    wire=json.dumps(calls)
    assert 'UNVERIFIED_HINT' in wire and 'UNRELATED_GLOBAL_TASK' not in wire
    assert 'identity_options' not in wire and 'observed_target' not in wire
    assert first['choice_result']['choice']=='condition_not_met'
    assert second['review_result']['choice']=='condition_met'


@pytest.mark.parametrize('bad', [None, [], {}, True, 1])
def test_nonstring_kind_is_a_clear_contract_error(bad):
    module=contract()
    value=module.grounding_target_check('Plus button',DESCRIPTION)
    value['kind']=bad
    with pytest.raises(ValueError,match='target_check'):
        module.normalize_target_check(value)


@pytest.mark.parametrize('first,second,adopted', [
    ('condition_met',None,True), ('condition_not_met','condition_met',True),
    ('condition_not_met','condition_not_met',False), ('evidence_insufficient','evidence_insufficient',False)])
def test_service_authenticates_target_and_secondary_result_without_replaying(tmp_path,monkeypatch,first,second,adopted):
    from app.judgment import DecisionService
    from test_decision_choice import runtime
    from test_candidate_current_scope import candidate_args,CANDIDATE_CONDITION
    service,_,old_client=runtime(tmp_path,monkeypatch,profile={'ordinary_review':'on_reject','auto_conditions':[CANDIDATE_CONDITION]})
    calls=[]
    def handle(request):
        calls.append(json.loads(request.content))
        if request.url.path.endswith('decisions'):
            reply=decision_body()
            reply['answers'][0]['choice']=first
        else:
            reply=response_body(second)
        return httpx.Response(200,json=reply)
    args=candidate_args(tmp_path,'TARGET_CHECK')
    args['action']['target_check']=contract().grounding_target_check('Browser address bar',DESCRIPTION,input_field=True)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        service._provider._client=client
        result=service.evaluate(**args)
        assert result['status']=='completed' and result['adopted'] is adopted
        assert service.validate_result(result,**args)
        assert len(calls)==(1 if second is None else 2)
        assert service.evaluate(**args)==result
        reopened=DecisionService(tmp_path,profile=service.profile)
        assert reopened.evaluate(**args)==result
        reopened.close()
        changed=deepcopy(args)
        changed['action']['target_check']['target']='Webpage search field'
        assert not service.validate_result(result,**changed)
        changed=deepcopy(args)
        changed['action']['target_check']['kind']='graphic'
        assert not service.validate_result(result,**changed)
        assert len(calls)==(1 if second is None else 2)
    old_client.close()
