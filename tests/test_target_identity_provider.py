"""身份分类走真实适配器与认证服务；HTTP 使用离线响应。"""
from copy import deepcopy
import json

import httpx
import pytest

from app.judgment import OpenAIDecisionsProvider, DecisionService
from test_luna_choice_review_provider import candidate_payload, response_body
from test_candidate_current_scope import candidate_args, CANDIDATE_CONDITION
from test_decision_choice import runtime


SPEC = {'schema': 'target_identity.v1', 'choices': [
    {'value': 'a', 'description': 'Browser address bar'},
    {'value': 'b', 'description': 'Webpage search input'}], 'expected': 'a'}


def answer(choice):
    return {'model': 'gpt-6-luna', 'answers': [{'type': 'choice', 'name': 'observed_target',
        'choice': choice, 'confidence': .91, 'probabilities': [
            {'value': v, 'probability': .91 if v == choice else .03} for v in ('a', 'b', 'other', 'unknown')]}],
        'usage': {'input_tokens': 100, 'output_tokens': 0, 'total_tokens': 100}}


@pytest.mark.parametrize('choice,expected', [('a', 'condition_met'), ('b', 'condition_not_met'),
    ('other', 'condition_not_met'), ('unknown', 'evidence_insufficient')])
def test_provider_identifies_without_receiving_expected_identity(monkeypatch, choice, expected):
    monkeypatch.setenv('IDENTITY_TEST_KEY', 'offline-secret')
    calls = []
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=answer(choice) if request.url.path.endswith('decisions') else response_body(choice))
    payload = candidate_payload()
    payload['action'].update(target_identity=deepcopy(SPEC), goal='SECRET_TARGET_GOAL', native_popup_fact={'private': 'DO_NOT_UPLOAD'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env='IDENTITY_TEST_KEY', client=client)
        first = provider.judge(payload)
        second = provider.review(payload)
    assert first['choice_result']['choice'] == second['review_result']['choice'] == expected
    assert first['identity_result']['answer']['choice'] == second['identity_result']['answer']['choice'] == choice
    question = calls[0]['questions'][0]
    assert question['name'] == 'observed_target'
    assert [x['value'] for x in question['choices']] == ['a', 'b', 'other', 'unknown']
    assert calls[1]['input'][0]['content'][:-1] == calls[0]['input'][0]['content']
    assert json.loads(calls[1]['input'][0]['content'][-1]['text'].split('\nReturn exactly')[0]) == question
    for body in calls:
        text = json.dumps(body)
        assert all(x not in text for x in ('expected', 'SECRET_TARGET_GOAL', 'DO_NOT_UPLOAD', 'condition_met', 'permitted_action'))


@pytest.mark.parametrize('first,second,adopted', [('a', None, True), ('b', 'a', True),
    ('b', 'b', False), ('unknown', 'unknown', False)])
def test_authenticated_service_routes_identity_and_retains_both_raw_answers(tmp_path, monkeypatch, first, second, adopted):
    service, _, old_client = runtime(tmp_path, monkeypatch, profile={
        'ordinary_review': 'on_reject', 'auto_conditions': [CANDIDATE_CONDITION]})
    calls = []
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=answer(first) if request.url.path.endswith('decisions') else response_body(second))
    client = httpx.Client(transport=httpx.MockTransport(handle))
    service._provider._client = client
    args = candidate_args(tmp_path, 'IDENTITY')
    args['action']['target_identity'] = deepcopy(SPEC)
    result = service.evaluate(**args)
    assert result['adopted'] is adopted, result
    assert result['identity_result']['answer']['choice'] == first
    assert len(calls) == (1 if second is None else 2)
    if second:
        assert result['ordinary_review']['identity_result']['answer']['choice'] == second
        assert result['usage']['input_tokens'] == 116
    assert service.validate_result(result, **args)
    assert service.evaluate(**args) == result
    reopened = DecisionService(tmp_path, profile=service.profile)
    assert reopened.evaluate(**args) == result
    corrupted = deepcopy(result)
    corrupted['identity_result']['expected'] = 'b'
    assert not service.validate_result(corrupted, **args)
    changed = deepcopy(args)
    changed['action']['target_identity']['expected'] = 'b'
    assert not service.validate_result(result, **changed)
    client.close()
    old_client.close()
