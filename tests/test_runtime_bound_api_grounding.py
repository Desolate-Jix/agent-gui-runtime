"""外部模型只返回目标内容；本次HTTP调用绑定运行时身份，不修补旧协议错ID。"""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import httpx
import pytest
from pydantic import ValidationError

from app.vision.external_grounding_api import ApiGroundingError, ChatCompletionsGrounder
from tests.test_external_grounding_api import capture, profile, reply, result
from tests.test_agent_command_action_review import scene, start, done


def _unbound_result():
    value = result()
    del value['request_id']
    del value['capture_id']
    return value


def test_legacy_binding_omission_and_explicit_default_preserve_profile():
    assert profile().model_dump() == profile(response_binding='model_echo').model_dump()
    assert profile(response_binding='runtime').model_dump()['response_binding'] == 'runtime'


@pytest.mark.parametrize('binding', [None, True, 1, 'repair_wrong_ids'])
def test_response_binding_rejects_undefined_modes(binding):
    with pytest.raises(ValidationError):
        profile(response_binding=binding)


def test_runtime_binding_omits_model_ids_and_preserves_local_provenance(capture, monkeypatch):
    monkeypatch.setenv('TEST_VISION_KEY', 'synthetic-key')
    bodies = []

    def handle(request):
        body = json.loads(request.content)
        bodies.append(body)
        context = json.loads(body['messages'][1]['content'][0]['text'])
        assert 'request_id' not in context and 'capture_id' not in context
        schema = context['required_output_schema']
        assert not {'request_id', 'capture_id'} & schema['properties'].keys()
        assert not {'request_id', 'capture_id'} & set(schema['required'])
        assert context['image_size'] == capture['image_size'] and context['goal'] == 'Search'
        assert 'long-runtime-request-abc123' not in request.content.decode('utf-8')
        return httpx.Response(200, json=reply(_unbound_result()))

    with ChatCompletionsGrounder(profile(response_binding='runtime'), capture_trace=True,
                                 transport=httpx.MockTransport(handle)) as grounder:
        value = grounder.ground(request_id='long-runtime-request-abc123', capture=capture, goal='Search')
    assert len(bodies) == 1 and value['action_executed'] is False
    assert value['result']['request_id'] == 'long-runtime-request-abc123'
    assert value['result']['capture_id'] == capture['capture_id']
    assert value['trace']['parsed_model_json'] == _unbound_result()
    assert 'request_id' not in value['trace']['prompt']
    assert value['trace']['binding']['request_id'] == 'long-runtime-request-abc123'
    assert value['trace']['binding']['capture_id'] == capture['capture_id']
    assert value['trace']['binding']['sha256'] == capture['sha256']


@pytest.mark.parametrize('invalid', ['request_id', 'capture_id', 'request_null', 'capture_null', 'size', 'point', 'extra'])
def test_runtime_binding_rejects_foreign_fields_and_invalid_geometry(capture, monkeypatch, invalid):
    monkeypatch.setenv('TEST_VISION_KEY', 'synthetic-key')
    model = _unbound_result()
    if invalid in {'request_id', 'capture_id'}:
        model[invalid] = 'request-1' if invalid == 'request_id' else 'capture-1'
    elif invalid in {'request_null', 'capture_null'}:
        model['request_id' if invalid == 'request_null' else 'capture_id'] = None
    elif invalid == 'size':
        model['image_size']['width'] = 200
    elif invalid == 'point':
        model['candidates'][0]['click_point']['x'] = 99
    else:
        model['unknown_metadata'] = 'untrusted'
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(model))

    with ChatCompletionsGrounder(profile(response_binding='runtime'), transport=httpx.MockTransport(handle)) as grounder:
        with pytest.raises(ApiGroundingError, match='api_grounding_invalid') as failed:
            grounder.ground(request_id='request-1', capture=capture, goal='Search')
    assert len(calls) == 1 and failed.value.attempt['usage']['total_tokens'] == 50
    assert failed.value.trace['binding']['capture_id'] == 'capture-1'
    if invalid in {'request_id', 'capture_id', 'request_null', 'capture_null'}:
        assert 'runtime-owned' in failed.value.trace['parse_error']


def test_legacy_wrong_id_still_fails_without_rebinding(capture, monkeypatch):
    monkeypatch.setenv('TEST_VISION_KEY', 'synthetic-key')
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=reply()))) as grounder:
        with pytest.raises(ApiGroundingError, match='api_grounding_invalid') as failed:
            grounder.ground(request_id='different-runtime-request', capture=capture, goal='Search')
    assert failed.value.trace['parse_error'] == 'grounding request_id does not match runtime request'


def test_parallel_http_calls_bind_their_own_request_and_capture(capture, monkeypatch):
    monkeypatch.setenv('TEST_VISION_KEY', 'synthetic-key')
    together = Barrier(2)

    def handle(request):
        context = json.loads(json.loads(request.content)['messages'][1]['content'][0]['text'])
        together.wait(timeout=2)
        model = _unbound_result()
        model['candidates'][0]['label'] = context['goal']
        return httpx.Response(200, json=reply(model))

    def call(grounder, name):
        local_capture = {**capture, 'capture_id': 'capture-' + name}
        return grounder.ground(request_id='request-' + name, capture=local_capture, goal=name)

    with ChatCompletionsGrounder(profile(response_binding='runtime', max_concurrency=2),
                                 transport=httpx.MockTransport(handle)) as grounder:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(call, grounder, name) for name in ('left', 'right')]
            outputs = [future.result(timeout=4) for future in futures]
    for name, output in zip(('left', 'right'), outputs):
        assert output['result']['request_id'] == 'request-' + name
        assert output['result']['capture_id'] == 'capture-' + name
        assert output['result']['candidates'][0]['label'] == name


def test_runtime_binding_uses_capture_snapshot_before_http_wait(capture, monkeypatch):
    monkeypatch.setenv('TEST_VISION_KEY', 'synthetic-key')
    original_sha = capture['sha256']

    def handle(request):
        capture['capture_id'] = 'changed-after-dispatch'
        capture['sha256'] = '0' * 64
        capture['image_size']['width'] = 900
        return httpx.Response(200, json=reply(_unbound_result()))

    with ChatCompletionsGrounder(profile(response_binding='runtime'), capture_trace=True,
                                 transport=httpx.MockTransport(handle)) as grounder:
        output = grounder.ground(request_id='request-1', capture=capture, goal='Search')
    assert output['result']['capture_id'] == 'capture-1'
    assert output['result']['image_size']['width'] == 100
    assert output['trace']['binding']['sha256'] == original_sha


@pytest.mark.parametrize('capture_trace', [False, True])
def test_deep_model_json_does_not_mask_original_failure_or_known_usage(scene, monkeypatch, capture_trace):
    monkeypatch.setenv('TEST_VISION_KEY', 'synthetic-key')
    jobs, coordinator, store, _, decision, _ = scene
    content = '{"nested":' + '[' * 1500 + '0' + ']' * 1500 + '}'
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(choices=[{'finish_reason': 'stop', 'message': {'content': content}}]))

    with ChatCompletionsGrounder(profile(response_binding='runtime'), capture_trace=capture_trace,
                                 transport=httpx.MockTransport(handle)) as grounder:
        jobs.api_grounder = grounder
        start(scene)
        terminal = done(jobs)
    assert terminal['error']['code'] == 'api_grounding_invalid'
    assert terminal['action_executed'] is False and terminal['dispatch_attempts'] == []
    assert coordinator.calls == decision.calls == [] and len(calls) == 1
    call = terminal['recognition_calls'][0]
    assert call['attempt']['usage']['total_tokens'] == 50
    assert call['failure_trace']['parsed_model_json'] is None
    assert 'recursion' in call['failure_trace']['parse_error']
    persisted = json.loads((store.session_root / 'agent-commands/job-1.json').read_text(encoding='utf-8'))
    assert persisted['recognition_calls'] == terminal['recognition_calls']


@pytest.mark.parametrize('cancelled', [False, True])
def test_runtime_bound_grounding_uses_existing_job_and_cancel_gates(scene, monkeypatch, cancelled):
    monkeypatch.setenv('TEST_VISION_KEY', 'synthetic-key')
    jobs, coordinator, _, _, _, _ = scene

    def handle(request):
        if cancelled:
            jobs.cancel('job-1')
        return httpx.Response(200, json=reply(_unbound_result()))

    with ChatCompletionsGrounder(profile(response_binding='runtime'), transport=httpx.MockTransport(handle)) as grounder:
        jobs.api_grounder = grounder
        start(scene)
        terminal = done(jobs)
    assert terminal['status'] == ('cancelled' if cancelled else 'completed')
    call = terminal['recognition_calls'][0]
    assert call['request_id'] == terminal['api_request']['request_id']
    assert call['attempt']['usage']['total_tokens'] == 50
    assert len(coordinator.calls) == (0 if cancelled else 1)
    if cancelled:
        assert terminal['action_executed'] is False and terminal['dispatch_attempts'] == []
