"""可配置判断与复核采用离线 HTTP 传输，验证凭据隔离和旧请求兼容。"""
from hashlib import sha256
import json

import httpx
import pytest

from app.judgment import DecisionProfile, OpenAIDecisionsProvider
from app.judgment.openai_decisions import DecisionNotConnected
from test_decision_choice import choice_reply
from test_luna_choice_review_provider import payload, response_body
from test_openai_decisions import payload as predicate_payload, reply as predicate_reply


SETTINGS = {
    'endpoint': 'https://decision.example.test/custom/decisions',
    'model': 'custom-decision-v1',
    'api_key_env': 'CONFIG_DECISION_KEY',
    'ordinary_review_endpoint': 'https://review.example.test/custom/responses',
    'ordinary_review_model': 'custom-vision-v2',
    'ordinary_review_api_key_env': 'CONFIG_REVIEW_KEY',
}


def test_omitted_provider_settings_preserve_profile_and_wire(monkeypatch):
    profile = DecisionProfile(contract_version='decision_profile.v2', decision_format='choice',
        ordinary_review='on_reject', api_key_env='CONFIG_TEST_KEY')
    assert profile.model_dump(mode='json') == {
        'api_key_env': 'CONFIG_TEST_KEY', 'auto_conditions': [], 'contract_version': 'decision_profile.v2',
        'decision_format': 'choice', 'fail_threshold': 0.1, 'mode': 'auto', 'ordinary_review': 'on_reject',
        'pass_threshold': 0.9, 'proactive_review': True, 'request_cap': 20,
        'review_policy': 'adaptive', 'timeout_seconds': 8.0,
    }
    monkeypatch.setenv('CONFIG_TEST_KEY', 'synthetic-default-key')
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response_body() if request.url.path.endswith('responses') else choice_reply())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env='CONFIG_TEST_KEY', client=client)
        provider.judge(payload())
        provider.review(payload())
    assert [str(r.url) for r in calls] == ['https://api.openai.com/v1/decisions', 'https://api.openai.com/v1/responses']
    assert [sha256(r.content).hexdigest() for r in calls] == [
        '59d9c31e86943257dddc401248d80da94fabb13c46aef1afdcee399dfe62796d',
        'a3fd34a863cf408f19e1e5f2bac0ea4e2dbbd3f8d2872b9f218b4f0d1f644eb8',
    ]
    assert all(r.headers['authorization'] == 'Bearer synthetic-default-key' for r in calls)


def test_custom_routes_send_each_model_and_only_its_own_key(monkeypatch):
    profile = DecisionProfile(**SETTINGS)
    assert all(profile.model_dump()[key] == value for key, value in SETTINGS.items())
    monkeypatch.setenv('CONFIG_DECISION_KEY', 'synthetic-decision-secret')
    monkeypatch.setenv('CONFIG_REVIEW_KEY', 'synthetic-review-secret')
    calls = []
    def handle(request):
        calls.append(request)
        review = request.url.host == 'review.example.test'
        body = response_body() if review else choice_reply()
        body['model'] = SETTINGS['ordinary_review_model' if review else 'model']
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(**SETTINGS, client=client)
        first = provider.judge(payload())
        second = provider.review(payload())
    assert first['choice_result']['choice'] == second['review_result']['choice'] == 'condition_met'
    assert [(str(r.url), json.loads(r.content)['model'], r.headers['authorization']) for r in calls] == [
        (SETTINGS['endpoint'], SETTINGS['model'], 'Bearer synthetic-decision-secret'),
        (SETTINGS['ordinary_review_endpoint'], SETTINGS['ordinary_review_model'], 'Bearer synthetic-review-secret'),
    ]
    assert 'synthetic-' not in json.dumps([first, second])


@pytest.mark.parametrize('review', [False, True])
def test_response_model_must_match_selected_layer(monkeypatch, review):
    monkeypatch.setenv('CONFIG_DECISION_KEY', 'decision-test-secret')
    monkeypatch.setenv('CONFIG_REVIEW_KEY', 'review-test-secret')
    body = response_body() if review else choice_reply()
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(**SETTINGS, client=client)
        with pytest.raises(ValueError, match='ordinary_review_model_invalid' if review else 'decision_protocol_error'):
            (provider.review if review else provider.judge)(payload())
    assert len(calls) == 1


def test_review_can_use_its_own_key_without_primary_key(monkeypatch):
    monkeypatch.delenv('CONFIG_DECISION_KEY', raising=False)
    monkeypatch.setenv('CONFIG_REVIEW_KEY', 'review-only-key')
    body = response_body()
    body['model'] = SETTINGS['ordinary_review_model']
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        provider = OpenAIDecisionsProvider(**SETTINGS, client=client)
        assert provider.ready is False and provider.review_ready is True
        assert provider.review(payload())['review_result']['choice'] == 'condition_met'
        with pytest.raises(DecisionNotConnected):
            provider.judge(payload())


def test_explicit_missing_review_key_does_not_borrow_primary_key(monkeypatch):
    monkeypatch.setenv('CONFIG_DECISION_KEY', 'primary-only-key')
    monkeypatch.delenv('CONFIG_REVIEW_KEY', raising=False)
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request))) as client:
        provider = OpenAIDecisionsProvider(**SETTINGS, client=client)
        assert provider.ready is True and provider.review_ready is False
        with pytest.raises(DecisionNotConnected, match='ordinary_review_key_missing'):
            provider.review(payload())
    assert calls == []


def test_custom_primary_model_also_supports_predicate_protocol(monkeypatch):
    monkeypatch.setenv('CONFIG_DECISION_KEY', 'synthetic-primary')
    body = predicate_reply()
    body['model'] = SETTINGS['model']
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        result = OpenAIDecisionsProvider(**SETTINGS, client=client).judge(predicate_payload())
    assert result['predicates']['condition_met']['probability'] == body['answers'][0]['probability']


@pytest.mark.parametrize('field', ['endpoint', 'ordinary_review_endpoint'])
@pytest.mark.parametrize('endpoint', [
    'http://remote.example.test/v1', 'https://user:secret@example.test/v1',
    'https://example.test/v1?key=secret', 'https://example.test/v1#secret',
    'https://example.test:0/v1', 'https://example.test/v1\n', 'file:///secret', '',
])
def test_endpoint_validation_precedes_any_transport(field, endpoint):
    with pytest.raises(ValueError):
        DecisionProfile(**{field: endpoint})
    with pytest.raises(ValueError):
        OpenAIDecisionsProvider(**{field: endpoint})


@pytest.mark.parametrize('endpoint', ['http://127.0.0.1:8042/decisions', 'http://localhost:8042/responses', 'http://[::1]:8042/api'])
def test_explicit_local_compatible_service_is_configurable(endpoint):
    assert DecisionProfile(endpoint=endpoint, ordinary_review_endpoint=endpoint).endpoint == endpoint


@pytest.mark.parametrize('field', ['model', 'ordinary_review_model'])
@pytest.mark.parametrize('model', ['', ' model', 'model\n', 'x' * 129, None])
def test_invalid_models_are_rejected(field, model):
    with pytest.raises(ValueError):
        DecisionProfile(**{field: model})
    with pytest.raises(ValueError):
        OpenAIDecisionsProvider(**{field: model})


def test_custom_redirect_is_not_followed_or_retried(monkeypatch):
    monkeypatch.setenv('CONFIG_DECISION_KEY', 'synthetic-primary')
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(307, headers={'Location': 'https://elsewhere.example.test/decisions'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(**SETTINGS, client=client)
        with pytest.raises(OSError, match='decision_http_status_307'):
            provider.judge(payload())
    assert len(calls) == 1


@pytest.mark.parametrize('wrong_model', [False, True])
@pytest.mark.parametrize('review', [False, True])
def test_identity_reply_checks_the_selected_model(monkeypatch, review, wrong_model):
    from copy import deepcopy
    from test_luna_choice_review_provider import candidate_payload
    from test_target_identity_provider import SPEC, answer

    monkeypatch.setenv('CONFIG_DECISION_KEY', 'synthetic-primary')
    monkeypatch.setenv('CONFIG_REVIEW_KEY', 'synthetic-secondary')
    data = candidate_payload()
    data['action']['target_identity'] = deepcopy(SPEC)
    body = response_body('a') if review else answer('a')
    body['model'] = 'wrong-model' if wrong_model else SETTINGS['ordinary_review_model' if review else 'model']
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        provider = OpenAIDecisionsProvider(**SETTINGS, client=client)
        if wrong_model:
            with pytest.raises(ValueError, match='ordinary_review_model_invalid' if review else 'decision_protocol_error'):
                (provider.review if review else provider.judge)(data)
        else:
            result = (provider.review if review else provider.judge)(data)
            assert result['identity_result']['answer']['choice'] == 'a'


def test_legacy_field_content_parser_accepts_configured_model(monkeypatch):
    from test_field_content_choice import payload as content_payload, response

    monkeypatch.setenv('CONFIG_DECISION_KEY', 'synthetic-primary')
    body = response()
    body['model'] = SETTINGS['model']
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        result = OpenAIDecisionsProvider(**SETTINGS, client=client).judge(content_payload())
    assert result['field_content_result']['choice'] == 'empty'


def test_public_configuration_and_frozen_session_keep_independent_routes_without_keys(monkeypatch, tmp_path):
    import sys
    from app.core.decision_configuration import create_session_decision_service, PROFILE_SNAPSHOT
    from app.judgment import load_decision_profile
    from scripts import configure_instant_mcp

    profile = tmp_path / 'decision.json'
    profile.write_text(json.dumps({'contract_version': 'decision_profile.v2', 'mode': 'auto',
        'decision_format': 'choice', 'ordinary_review': 'on_reject', **SETTINGS}), encoding='utf-8')
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    monkeypatch.setattr(configure_instant_mcp, '__file__', str(scripts / 'configure_instant_mcp.py'))
    monkeypatch.setattr(sys, 'argv', ['configure', '--recognition-source', 'agent_current',
        '--decision-profile', str(profile), '--python', sys.executable, '--data-dir', str(tmp_path / 'data')])
    monkeypatch.setenv('CONFIG_DECISION_KEY', 'synthetic-primary-secret')
    monkeypatch.setenv('CONFIG_REVIEW_KEY', 'synthetic-secondary-secret')
    configure_instant_mcp.main()
    raw = (tmp_path / 'mcp-config.local.json').read_text(encoding='utf-8')
    args = json.loads(raw)['mcpServers']['agent-review-instant']['args']
    assert args[args.index('--decision-profile') + 1] == str(profile)
    session = tmp_path / 'session'
    service = create_session_decision_service(session, profile_path=profile)
    frozen = load_decision_profile(session / PROFILE_SNAPSHOT)
    assert all(getattr(frozen, key) == value for key, value in SETTINGS.items())
    persisted = raw + (session / PROFILE_SNAPSHOT).read_text(encoding='utf-8')
    assert 'synthetic-primary-secret' not in persisted and 'synthetic-secondary-secret' not in persisted
    service.close()
    profile.write_text(json.dumps({**frozen.model_dump(mode='json'), 'ordinary_review_model': 'changed'}), encoding='utf-8')
    with pytest.raises(ValueError, match='decision_session_profile_mismatch'):
        create_session_decision_service(session, profile_path=profile)


def test_task_plan_summary_identifies_custom_review_without_exposing_connections():
    from app.execution.task_plan_review import assessment_summary

    summary = assessment_summary({'judged_by': 'ordinary_review', 'ordinary_review_model': 'custom-vision-v2',
        'ordinary_review_endpoint': 'https://review.example.test/v1/responses', 'ordinary_review_api_key_env': 'CONFIG_REVIEW_KEY'})
    assert summary == {'judged_by': 'ordinary_review', 'ordinary_review_model': 'custom-vision-v2'}
