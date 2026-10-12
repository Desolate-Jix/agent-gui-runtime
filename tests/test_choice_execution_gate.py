"""Choice 经真实判断服务认证后才到输入门禁；桌面及网络边界离线替换。"""
import json

import httpx
import pytest

from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from tests.test_agent_grounding_target import scene
from tests.test_execution_decision_check import run_route


@pytest.mark.parametrize('selected', ['condition_met', 'condition_not_met', 'evidence_insufficient'])
def test_real_choice_service_drives_action_gate_without_probability_threshold(scene, monkeypatch, selected):
    monkeypatch.setenv('CHOICE_GATE_KEY', 'offline-only')
    calls = []

    def response(request):
        body = json.loads(request.content)
        calls.append(body)
        assert len(body['questions']) == 1
        assert body['questions'][0]['type'] == 'choice'
        return httpx.Response(200, json={'model': 'gpt-6-luna', 'answers': [{
            'type': 'choice', 'name': 'current_step', 'choice': selected, 'confidence': .01,
            'probabilities': [{'value': label, 'probability': .34 if label == selected else .33}
                for label in ('condition_met', 'condition_not_met', 'evidence_insufficient')]}],
            'usage': {'input_tokens': 1, 'output_tokens': 0, 'total_tokens': 1}})

    profile = DecisionProfile(contract_version='decision_profile.v2', mode='auto', decision_format='choice',
        api_key_env='CHOICE_GATE_KEY', auto_conditions=['Search is safe'])
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        service = DecisionService(scene[3], profile=profile, provider=OpenAIDecisionsProvider(
            api_key_env='CHOICE_GATE_KEY', client=client))
        try:
            _, clicks, _, _, _, _, _ = run_route(scene, monkeypatch, service)
            assert len(clicks) == (1 if selected == 'condition_met' else 0)
            assert len(calls) == 1
        finally:
            service.close()
