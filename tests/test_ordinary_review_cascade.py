"""两级审核只覆盖模型结论，保持原证据、预算及认证边界。"""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from app.judgment import DecisionProfile, DecisionService
from app.execution.task_plan_review import assessment_summary
from test_adaptive_decision_policy import context
from test_decision_choice import choice_reply, runtime
from test_decision_service import arguments


def setup(root, monkeypatch, *, first='condition_not_met', second='condition_met', cap=20, mode='auto', failure=None):
    service, calls, client = runtime(root, monkeypatch, body=choice_reply(first),
        profile={'ordinary_review': 'on_reject', 'request_cap': cap, 'mode': mode})
    reviews = []
    primary_payloads = []
    original_judge = service._provider.judge
    def judge(payload):
        primary_payloads.append(deepcopy(payload))
        return original_judge(payload)
    monkeypatch.setattr(service._provider, 'judge', judge)
    def review(payload):
        reviews.append(deepcopy(payload))
        assert payload['frames'] == primary_payloads[0]['frames']
        if failure:
            raise failure
        return {'request_sha256': payload['request_sha256'],
                'review_result': {'type': 'choice', 'name': 'current_step', 'choice': second},
                'usage': {'input_tokens': 20, 'output_tokens': 3, 'total_tokens': 23},
                'http_elapsed_ms': 5, 'server_processing_ms': 3, 'provider_request_id': 'secondary-1'}
    monkeypatch.setattr(service._provider, 'review', review, raising=False)
    return service, calls, reviews, client


def cache_write_usages(primary_details=True, secondary_details=True):
    """Synthetic nonzero counts extend the recorded single-response shape."""
    fixture = Path(__file__).parent / 'fixtures/decisions-choice-cache-write-details-20261023.json'
    primary = json.loads(fixture.read_text(encoding='utf-8'))['usage']
    primary['input_tokens_details'].update(cache_write_tokens=12,
        cache_write_tokens_details={'ttl_30m_tokens': 5, 'ttl_12h_tokens': 7})
    secondary = {'input_tokens': 20, 'output_tokens': 3, 'total_tokens': 23,
        'input_tokens_details': {'cached_tokens': 2, 'cache_write_tokens': 7,
            'cache_write_tokens_details': {'ttl_30m_tokens': 3, 'ttl_12h_tokens': 4}},
        'output_tokens_details': {'reasoning_tokens': 2}}
    for usage, present in ((primary, primary_details), (secondary, secondary_details)):
        if present is None:
            usage.pop('input_tokens_details')
        elif not present:
            usage['input_tokens_details'].pop('cache_write_tokens_details')
    return primary, secondary


def expected_cache_write_usage(primary_details, secondary_details):
    expected = {'input_tokens': 1472, 'output_tokens': 3, 'total_tokens': 1475,
        'output_tokens_details': {'reasoning_tokens': 2}}
    if primary_details is not None and secondary_details is not None:
        expected['input_tokens_details'] = {'cached_tokens': 1279, 'cache_write_tokens': 19}
        if primary_details and secondary_details:
            expected['input_tokens_details']['cache_write_tokens_details'] = {'ttl_30m_tokens': 8, 'ttl_12h_tokens': 11}
    return expected


@pytest.mark.parametrize('primary_details,secondary_details', [(True, True), (True, False), (False, True), (True, None), (None, True)])
def test_combined_cache_write_usage_sums_known_counts_without_inventing_missing_metadata(primary_details, secondary_details):
    from app.judgment.ordinary_review import combined_usage

    primary, secondary = cache_write_usages(primary_details, secondary_details)
    original = deepcopy((primary, secondary))
    assert combined_usage(primary, secondary) == expected_cache_write_usage(primary_details, secondary_details)
    assert (primary, secondary) == original


@pytest.mark.parametrize('side', [0, 1])
@pytest.mark.parametrize('nested', [True, {'ttl_30m_tokens': True, 'ttl_12h_tokens': 0},
    {'ttl_30m_tokens': -1, 'ttl_12h_tokens': 0}, {'ttl_30m_tokens': 0, 'ttl_12h_tokens': 0, 'unknown': 0}])
def test_combined_cache_write_usage_rejects_bad_structure_in_either_layer(side, nested):
    from app.judgment.ordinary_review import combined_usage

    layers = cache_write_usages()
    layers[side]['input_tokens_details']['cache_write_tokens_details'] = nested
    with pytest.raises(ValueError, match='decision_usage_details_invalid'):
        combined_usage(*layers)


@pytest.mark.parametrize('primary_details,secondary_details', [(True, True), (True, False), (False, True), (True, None), (None, True)])
def test_cascade_cache_write_usage_is_authenticated_and_never_rebilled(tmp_path, monkeypatch, primary_details, secondary_details):
    from test_luna_choice_review_provider import response_body

    primary_usage, secondary_usage = cache_write_usages(primary_details, secondary_details)

    def handle(request):
        ordinary = request.url.path == '/v1/responses'
        body = response_body('condition_met') if ordinary else choice_reply('condition_not_met')
        body['usage'] = secondary_usage if ordinary else primary_usage
        return httpx.Response(200, json=body)

    service, calls, client = runtime(tmp_path, monkeypatch, handler=handle,
        profile={'ordinary_review': 'on_reject'})
    args = arguments(tmp_path, review_context=context())
    try:
        result = service.evaluate(**args)
        assert result['status'] == 'completed' and result['ordinary_review']['status'] == 'completed'
        assert result['primary_usage'] == primary_usage
        assert result['ordinary_review']['usage'] == secondary_usage
        assert result['usage'] == expected_cache_write_usage(primary_details, secondary_details)
        assert result['authorizes_action'] is False and result['automatic_retry_allowed'] is False
        assert service.status()['used'] == 2 and len(calls) == 2
        assert service.validate_result(result, **args)
        assert service.evaluate(**args) == result and len(calls) == 2
        reopened = DecisionService(tmp_path, profile=service.profile)
        try:
            assert reopened.evaluate(**args) == result
            assert reopened.validate_result(result, **args)
            assert reopened.status()['used'] == 2 and len(calls) == 2
        finally:
            reopened.close()
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize('first,second,adopted,verdict', [
    ('condition_not_met', 'condition_met', True, 'success'),
    ('evidence_insufficient', 'condition_met', True, 'success'),
    ('condition_not_met', 'condition_not_met', False, 'failure'),
    ('evidence_insufficient', 'evidence_insufficient', False, 'uncertain')])
def test_later_choice_controls_outcome_with_original_evidence_and_no_replay(tmp_path, monkeypatch, first, second, adopted, verdict):
    service, calls, reviews, client = setup(tmp_path, monkeypatch, first=first, second=second)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result['adopted'] is adopted and result['verdict'] == verdict
    assert result['disposition'] == ('continue' if adopted else 'review_required')
    assert result['choice_result']['choice'] == first
    assert result['ordinary_review']['review_result']['choice'] == second
    assert result['ordinary_review']['request_sha256'] == result['request_sha256']
    assert reviews[0]['frames']
    assert 'choice_result' not in reviews[0]
    assert 0 < reviews[0]['request_timeout_seconds'] <= service.profile.timeout_seconds
    assert result['usage'] == {'input_tokens': 32, 'output_tokens': 3, 'total_tokens': 35}
    assert service.status()['used'] == 2
    assert not result['authorizes_action'] and not result['automatic_retry_allowed']
    assert service.validate_result(result, **args)
    assert service.evaluate(**args) == result and len(calls) == len(reviews) == 1
    reopened = DecisionService(tmp_path, profile=service.profile)
    assert reopened.evaluate(**args) == result and reopened.validate_result(result, **args)
    assert assessment_summary(result)['ordinary_review'] == result['ordinary_review']
    tampered = deepcopy(result)
    tampered['ordinary_review']['review_result']['choice'] = 'condition_met' if second != 'condition_met' else 'condition_not_met'
    assert not service.validate_result(tampered, **args)
    client.close()


def test_primary_pass_bypasses_review_known_false_acceptance_gap(tmp_path, monkeypatch):
    service, calls, reviews, client = setup(tmp_path, monkeypatch, first='condition_met')
    result = service.evaluate(**arguments(tmp_path, review_context=context()))
    assert result['adopted'] and not reviews and len(calls) == 1
    assert 'ordinary_review' not in result and service.status()['used'] == 1
    client.close()


def test_review_cap_prevents_second_request_and_remains_authenticated(tmp_path, monkeypatch):
    service, calls, reviews, client = setup(tmp_path, monkeypatch, cap=1)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result['status'] == 'limited' and result['disposition'] == 'review_required'
    assert not result['adopted'] and not reviews and len(calls) == 1
    assert service.status()['used'] == 1 and service.validate_result(result, **args)
    assert service.evaluate(**args) == result
    client.close()


@pytest.mark.parametrize('failure,status', [(TimeoutError('private'), 'timeout'),
    (ValueError('private-secret'), 'error'), (OSError('private-secret'), 'error')])
def test_review_failures_preserve_primary_but_never_adopt_or_replay(tmp_path, monkeypatch, failure, status):
    service, calls, reviews, client = setup(tmp_path, monkeypatch, failure=failure)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result['status'] == status and not result['adopted'] and result['disposition'] == 'review_required'
    assert result['choice_result']['choice'] == 'condition_not_met'
    assert 'private' not in json.dumps(result)
    assert service.status()['used'] == 2 and service.validate_result(result, **args)
    assert service.evaluate(**args) == result and len(calls) == len(reviews) == 1
    client.close()


@pytest.mark.parametrize('fault', ['digest', 'choice', 'probabilities', 'multiple_fields'])
def test_review_protocol_cannot_fabricate_pass(tmp_path, monkeypatch, fault):
    service, calls, reviews, client = setup(tmp_path, monkeypatch)
    original = service._provider.review
    def corrupt(payload):
        value = original(payload)
        if fault == 'digest': value['request_sha256'] = '0' * 64
        elif fault == 'choice': value['review_result']['choice'] = 'yes'
        elif fault == 'probabilities': value['review_result']['probabilities'] = []
        else: value['unexpected'] = True
        return value
    monkeypatch.setattr(service._provider, 'review', corrupt)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result['status'] == 'error' and not result['adopted']
    assert service.validate_result(result, **args) and len(reviews) == 1
    client.close()


def test_shadow_is_advice_only_and_does_not_add_secondary_spend(tmp_path, monkeypatch):
    service, calls, reviews, client = setup(tmp_path, monkeypatch, mode='shadow')
    result = service.evaluate(**arguments(tmp_path, review_context=context()))
    assert not result['adopted'] and not reviews and len(calls) == 1
    client.close()


def test_profile_rejects_secondary_route_on_legacy_predicate_and_preserves_omission():
    legacy = DecisionProfile(contract_version='decision_profile.v2')
    assert 'ordinary_review' not in legacy.model_dump()
    for config in ({}, {'contract_version': 'decision_profile.v2'}):
        with pytest.raises(ValueError):
            DecisionProfile(**config, ordinary_review='on_reject')


def test_primary_protocol_failure_is_not_hidden_by_secondary(tmp_path, monkeypatch):
    service, calls, reviews, client = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(service._provider, 'judge', lambda payload: {'invalid': True})
    result = service.evaluate(**arguments(tmp_path, review_context=context()))
    assert result['status'] == 'error' and not reviews and not result['adopted']
    client.close()


@pytest.mark.parametrize('second', ['condition_met', 'condition_not_met', 'evidence_insufficient'])
def test_real_provider_endpoints_share_images_and_current_question(tmp_path, monkeypatch, second):
    from test_luna_choice_review_provider import response_body
    def handle(request):
        return httpx.Response(200, json=response_body(second) if request.url.path == '/v1/responses'
            else choice_reply('condition_not_met'))
    service, calls, client = runtime(tmp_path, monkeypatch, handler=handle,
        profile={'ordinary_review': 'on_reject'})
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result['adopted'] is (second == 'condition_met')
    assert len(calls) == 2 and calls[1].url.path == '/v1/responses'
    first, last = (json.loads(call.content) for call in calls)
    assert last['input'][0]['content'][:-1] == first['input'][0]['content']
    question_text = last['input'][0]['content'][-1]['text']
    prefix = 'Question and allowed choices (JSON): '
    assert question_text.startswith(prefix)
    question, end = json.JSONDecoder().raw_decode(question_text[len(prefix):])
    assert question == first['questions'][0]
    assert question_text[len(prefix) + end:].startswith('\nOutput exactly one allowed choice value')
    assert last['reasoning'] == {'effort': 'none'}
    assert service.validate_result(result, **args)
    assert service.evaluate(**args) == result and len(calls) == 2
    client.close()


def test_secondary_interruption_is_durable_and_never_reissued(tmp_path, monkeypatch):
    service, calls, reviews, client = setup(tmp_path, monkeypatch, failure=KeyboardInterrupt())
    args = arguments(tmp_path, review_context=context())
    with pytest.raises(KeyboardInterrupt):
        service.evaluate(**args)
    reopened = DecisionService(tmp_path, profile=service.profile)
    result = reopened.evaluate(**args)
    assert result['status'] == 'unknown' and not result['adopted']
    assert reopened.status()['used'] == reopened.status()['unknown_dispatches'] == 2
    assert len(calls) == len(reviews) == 1
    client.close()


def test_secondary_refusal_is_authenticated_main_handoff(tmp_path, monkeypatch):
    service, calls, reviews, client = setup(tmp_path, monkeypatch)
    original = service._provider.review
    def refuse(payload):
        answer = original(payload)
        answer['review_result'].update(type='refusal', choice=None)
        return answer
    monkeypatch.setattr(service._provider, 'review', refuse)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result['status'] == 'refused' and not result['adopted']
    assert service.validate_result(result, **args)
    client.close()


def test_close_during_secondary_never_adopts_and_reopens_without_replay(tmp_path, monkeypatch):
    service, calls, reviews, client = setup(tmp_path, monkeypatch)
    original = service._provider.review
    def close_during_review(payload):
        answer = original(payload)
        service.close()
        return answer
    monkeypatch.setattr(service._provider, 'review', close_during_review)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result['status'] == 'error' and not result['adopted']
    reopened = DecisionService(tmp_path, profile=service.profile)
    assert reopened.evaluate(**args) == result
    assert reopened.validate_result(result, **args)
    assert len(calls) == len(reviews) == 1
    client.close()


@pytest.mark.parametrize('late_stage', ['primary', 'secondary'])
def test_shared_deadline_covers_primary_pass_and_secondary_pass(tmp_path, monkeypatch, late_stage):
    import app.judgment.service as service_module
    clock = [0]
    monkeypatch.setattr(service_module, 'perf_counter_ns', lambda: clock[0])
    service, calls, reviews, client = setup(tmp_path, monkeypatch,
        first='condition_met' if late_stage == 'primary' else 'condition_not_met')
    method = 'judge' if late_stage == 'primary' else 'review'
    original = getattr(service._provider, method)
    def late(payload):
        assert 0 < payload['request_timeout_seconds'] <= 8
        answer = original(payload)
        clock[0] = 9_000_000_000
        return answer
    monkeypatch.setattr(service._provider, method, late)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result['status'] == 'timeout' and not result['adopted']
    assert service.validate_result(result, **args)
    assert service.evaluate(**args) == result
    client.close()


def test_maintained_profiles_enable_cascade_without_changing_legacy():
    from pathlib import Path
    from app.judgment.profile import load_decision_profile
    root = Path(__file__).resolve().parents[1] / 'configs'
    for suffix in ('example', 'adaptive.example', 'visual-execution.example'):
        assert load_decision_profile(root / f'decision-profile.{suffix}.json').ordinary_review == 'on_reject'
    assert load_decision_profile(root / 'decision-profile.legacy.example.json').ordinary_review == 'off'
