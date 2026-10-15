"""真实定位提供者的失败诊断必须穿过任务记录；不访问外网或桌面。"""
import json

import httpx
import pytest

from app.vision import external_grounding_api as api
from app.vision.external_grounding_api import ApiGroundingError, ChatCompletionsGrounder
from tests.test_external_grounding_api import capture, profile, reply, result
from tests.test_agent_command_action_review import scene, start, done


@pytest.mark.parametrize('failure', ['model_json', 'wrong_binding', 'description', 'completion'])
def test_default_provider_retains_failure_without_exporting_request_image(capture, monkeypatch, failure):
    monkeypatch.setenv('TEST_VISION_KEY', 'secret-value')
    model = result()
    model['candidates'][0]['label'] = '搜索 secret-value'
    payload = reply(model)
    expected_code = 'api_grounding_invalid'
    changes = {}
    if failure == 'model_json':
        payload['choices'][0]['message']['content'] = '{"label":"搜索 secret-value", invalid}'
    elif failure == 'wrong_binding':
        model['request_id'] = 'stale-request'
        payload = reply(model)
    elif failure == 'description':
        changes['target_description'] = True
    else:
        payload['choices'][0]['finish_reason'] = 'length'
        expected_code = 'api_output_truncated'
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    with ChatCompletionsGrounder(profile(**changes), transport=httpx.MockTransport(handle)) as grounder:
        with pytest.raises(ApiGroundingError, match=expected_code) as failed:
            grounder.ground(request_id='request-1', capture=capture, goal='搜索')
    trace = failed.value.trace
    assert isinstance(trace, dict)
    assert trace['error_code'] == expected_code
    assert trace['prompt']['request_id'] == 'request-1'
    assert trace['prompt']['capture_id'] == capture['capture_id']
    assert trace['prompt']['goal'] == '搜索'
    assert '搜索' in trace['raw_model_text']
    assert 'secret-value' not in json.dumps(trace, ensure_ascii=False)
    assert 'data:image/' not in json.dumps(trace, ensure_ascii=False)
    assert 'Authorization' not in json.dumps(trace)
    assert failed.value.attempt['usage']['total_tokens'] == 50
    assert len(calls) == 1
    if failure == 'model_json':
        assert trace['parsed_model_json'] is None
        assert trace['parse_error'].startswith('grounding JSON invalid')
    else:
        assert trace['parsed_model_json']['candidates'][0]['label'] == '搜索 [REDACTED]'
    if failure == 'description':
        assert trace['stage'] == 'profile_contract'
        assert trace['parse_error'] == 'target_description required for found status'


def test_default_success_response_remains_trace_free(capture, monkeypatch):
    monkeypatch.setenv('TEST_VISION_KEY', 'secret-value')
    bodies = []

    def handle(request):
        bodies.append(request.content)
        return httpx.Response(200, json=reply())

    responses = []
    for enabled in (False, True):
        with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(handle), capture_trace=enabled) as grounder:
            responses.append(grounder.ground(request_id='request-1', capture=capture, goal='搜索'))
    assert 'trace' not in responses[0] and 'trace' in responses[1]
    assert responses[0]['result'] == responses[1]['result']
    assert bodies[0] == bodies[1]


def test_diagnostic_redacts_echoed_image_and_credentials(capture, monkeypatch):
    monkeypatch.setenv('TEST_VISION_KEY', 'secret-value')
    sent_images = []

    def handle(request):
        uri = json.loads(request.content)['messages'][1]['content'][1]['image_url']['url']
        sent_images.append(uri.split(',', 1)[1])
        model = result()
        model['candidates'][0]['label'] = '搜索 secret-value Bearer other-private-token ' + uri + ' ' + sent_images[0]
        return httpx.Response(200, json=reply(model))

    with ChatCompletionsGrounder(profile(target_description=True), transport=httpx.MockTransport(handle)) as grounder:
        with pytest.raises(ApiGroundingError) as failed:
            grounder.ground(request_id='request-1', capture=capture, goal='搜索')
    trace = failed.value.trace
    exported = json.dumps(trace, ensure_ascii=False)
    assert trace['redactions_applied'] is True
    assert 'secret-value' not in exported and 'other-private-token' not in exported
    assert 'data:image/' not in exported and sent_images[0] not in exported
    assert '搜索' in trace['raw_model_text']
    assert trace['parsed_model_json']['candidates'][0]['label'].startswith('搜索 [REDACTED]')


@pytest.mark.parametrize('failure,stage,code', [
    ('http', 'transport', 'api_access_denied'),
    ('response_json', 'response_json', 'api_response_invalid'),
    ('envelope', 'completion_envelope', 'api_response_invalid'),
    ('source', 'source_contract', 'api_source_mismatch'),
])
def test_failure_stages_do_not_invent_model_text_or_usage(capture, monkeypatch, failure, stage, code):
    monkeypatch.setenv('TEST_VISION_KEY', 'secret-value')
    calls = []

    def handle(request):
        calls.append(request)
        if failure == 'http':
            return httpx.Response(403, text='private server error secret-value')
        if failure == 'response_json':
            return httpx.Response(200, content=b'{bad response')
        if failure == 'envelope':
            return httpx.Response(200, json=reply(choices=[42]))
        model = result()
        model['candidates'][0]['evidence_source'] = 'agent_visual'
        return httpx.Response(200, json=reply(model))

    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(handle)) as grounder:
        with pytest.raises(ApiGroundingError, match=code) as failed:
            grounder.ground(request_id='request-1', capture=capture, goal='搜索')
    trace = failed.value.trace
    assert trace['stage'] == stage and trace['error_code'] == code
    assert len(calls) == 1
    if failure in {'http', 'response_json'}:
        assert failed.value.attempt['usage'] is None
    else:
        assert failed.value.attempt['usage']['total_tokens'] == 50
    if failure != 'source':
        assert trace['raw_model_text'] is None and trace['parsed_model_json'] is None
    assert 'secret-value' not in json.dumps(trace)
    assert 'private server error' not in json.dumps(trace)
    if failure in {'response_json', 'envelope'}:
        assert trace['parse_error']


def test_deadline_after_usage_keeps_known_cost_and_missing_model_text(capture, monkeypatch):
    monkeypatch.setenv('TEST_VISION_KEY', 'secret-value')
    now = [0.0]
    monkeypatch.setattr(api.time, 'monotonic', lambda: now[0])
    original_loads = api.json.loads

    def parse(value, *args, **kwargs):
        parsed = original_loads(value, *args, **kwargs)
        if isinstance(value, (bytes, bytearray)) and isinstance(parsed, dict) and 'choices' in parsed:
            now[0] = 6.0
        return parsed

    monkeypatch.setattr(api.json, 'loads', parse)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply())

    with ChatCompletionsGrounder(profile(timeout_seconds=5), transport=httpx.MockTransport(handle)) as grounder:
        with pytest.raises(ApiGroundingError, match='api_timeout') as failed:
            grounder.ground(request_id='request-1', capture=capture, goal='搜索')
    assert failed.value.attempt['usage']['total_tokens'] == 50
    assert failed.value.trace['stage'] == 'response_deadline'
    assert failed.value.trace['raw_model_text'] is None
    assert len(calls) == 1


@pytest.mark.parametrize('encoded', ['credential', 'surrogate'])
def test_encoded_model_strings_cannot_leak_or_prevent_job_usage_persistence(scene, monkeypatch, encoded):
    monkeypatch.setenv('TEST_VISION_KEY', 'secret-value')
    jobs, coordinator, store, _, decision, _ = scene
    text = ('{"label":"\\u641c\\u7d22 \\u0073ecret-value data:image\\/png;base64,QUJD",'
            '"\\u0073ecret-value":{"nested":["\\u0073ecret-value"]}}')
    if encoded == 'surrogate':
        text = '{"label":"\\ud800"}'
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(choices=[{'finish_reason': 'stop', 'message': {'content': text}}]))

    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(handle)) as grounder:
        jobs.api_grounder = grounder
        start(scene)
        terminal = done(jobs)
    assert terminal['status'] == 'failed' and terminal['error']['code'] == 'api_grounding_invalid'
    assert terminal['action_executed'] is False and terminal['dispatch_attempts'] == []
    assert coordinator.calls == decision.calls == [] and len(calls) == 1
    call = terminal['recognition_calls'][0]
    assert call['attempt']['usage']['total_tokens'] == 50
    trace = call['failure_trace']
    serialized = json.dumps(trace, ensure_ascii=False)
    serialized.encode('utf-8')
    assert 'secret-value' not in serialized and 'data:image/' not in serialized
    reparsed = json.loads(trace['raw_model_text'])
    assert 'secret-value' not in json.dumps(reparsed, ensure_ascii=False)
    assert 'data:image/' not in json.dumps(reparsed, ensure_ascii=False)
    assert trace['raw_model_text_normalized'] is True
    if encoded == 'credential':
        assert trace['parsed_model_json']['label'].startswith('搜索 [REDACTED]')
        assert trace['redactions_applied'] is True
    else:
        assert trace['parsed_model_json']['label'] == '\\ud800'
        assert trace['unicode_escapes_applied'] is True
    persisted = json.loads((store.session_root / 'agent-commands/job-1.json').read_text(encoding='utf-8'))
    assert persisted['recognition_calls'] == terminal['recognition_calls']


@pytest.mark.parametrize('cancelled', [False, True])
@pytest.mark.parametrize('capture_trace', [False, True])
def test_real_job_persists_original_failure_and_usage_before_cancellation(scene, monkeypatch, cancelled, capture_trace):
    monkeypatch.setenv('TEST_VISION_KEY', 'secret-value')
    jobs, coordinator, store, _, decision, _ = scene
    calls = []

    def handle(request):
        calls.append(request)
        context = json.loads(json.loads(request.content)['messages'][1]['content'][0]['text'])
        model = result()
        model.update(request_id=context['request_id'], capture_id=context['capture_id'])
        model['candidates'][0]['label'] = '搜索 secret-value'
        if cancelled:
            jobs.cancel('job-1')
        return httpx.Response(200, json=reply(model))

    with ChatCompletionsGrounder(profile(target_description=True), transport=httpx.MockTransport(handle),
                                 capture_trace=capture_trace) as grounder:
        jobs.api_grounder = grounder
        start(scene)
        terminal = done(jobs)
    assert terminal['status'] == ('cancelled' if cancelled else 'failed')
    assert terminal['action_executed'] is False and terminal['dispatch_attempts'] == []
    assert coordinator.calls == decision.calls == [] and len(calls) == 1
    assert len(terminal['recognition_calls']) == 1
    call = terminal['recognition_calls'][0]
    assert call['request_id'] == terminal['api_request']['request_id']
    assert call['attempt']['usage']['total_tokens'] == 50
    trace = call['failure_trace']
    assert trace['error_code'] == 'api_grounding_invalid'
    assert trace['stage'] == 'profile_contract'
    assert trace['parse_error'] == 'target_description required for found status'
    assert trace['prompt']['request_id'] == call['request_id']
    assert trace['prompt']['capture_id'] == call['capture_id']
    assert 'system_prompt' not in trace and 'required_output_schema' not in trace['prompt']
    assert trace['parsed_model_json']['candidates'][0]['label'] == '搜索 [REDACTED]'
    persisted = json.loads((store.session_root / 'agent-commands/job-1.json').read_text(encoding='utf-8'))
    assert persisted['recognition_calls'] == terminal['recognition_calls']
    assert 'secret-value' not in json.dumps(persisted, ensure_ascii=False)
    assert 'data:image/' not in json.dumps(persisted, ensure_ascii=False)
    if not cancelled:
        assert terminal['error']['code'] == 'api_grounding_invalid'
