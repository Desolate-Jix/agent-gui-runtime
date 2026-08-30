from __future__ import annotations

from copy import deepcopy

import pytest

from tests.uei_v1_helpers import build_context_from_sidecar, load_fixture


_FORBIDDEN = {
    'action', 'click_point', 'wire_payload', 'image_path',
    'artifact_is_authorization', 'execute_binding_enabled',
}


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*( _walk_keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*( _walk_keys(child) for child in value)) if value else set()
    return set()


def test_ocr_projection_generates_jcs_source_id_without_mutating_fixture(tmp_path):
    from app.learn.recognition.uei.projections import project_ocr_result

    context = build_context_from_sidecar(tmp_path, 'ocr')
    fixture = load_fixture('ocr-result-static.json')
    before = deepcopy(fixture)
    result = project_ocr_result(**context.for_case('ocr'), fixture=fixture)

    assert result['status'] == 'success'
    assert result['items'][0]['source_id_origin'] == 'uei_deterministic_projection'
    assert result['items'][0]['source_item_id'].startswith('sha256:')
    assert fixture == before


def test_uia_projection_preserves_relative_outer_window_geometry_and_redacts_screen_bbox(tmp_path):
    from app.learn.recognition.uei.projections import project_uia_snapshot

    context = build_context_from_sidecar(tmp_path, 'uia')
    result = project_uia_snapshot(**context.for_case('uia'), fixture=load_fixture('uia-snapshot-static.json'))
    item = result['items'][0]

    assert item['source_item_id'] == 'uia_0_synthetic_search'
    assert item['source_coordinate_space'] == 'window_outer_pixel_xyxy'
    assert item['source_bbox'] == [12, 24, 112, 56]
    assert all('screen_bbox' not in durable for durable in result['items'])
    assert result['redaction_summary']['redacted_field_count'] == 1


def test_screen_parser_projection_preserves_ids_without_confidence_or_unsafe_fields(tmp_path):
    from app.learn.recognition.uei.projections import project_screen_parser_result

    context = build_context_from_sidecar(tmp_path, 'screen-parser')
    result = project_screen_parser_result(
        **context.for_case('screen-parser'), fixture=load_fixture('screen-parser-result-static.json')
    )

    assert result['items'][0]['source_item_id'] == 'omniparser_0001_synthetic'
    assert result['items'][0]['source_bbox'] == [12, 24, 112, 56]
    assert all(item['provider_confidence'] is None for item in result['items'])
    assert not (_walk_keys(result) & _FORBIDDEN)
    stored = context.store.get({'id': result['result_id'], 'content_sha256': result['content_sha256']},
                               contract_version='provider_safe_result_v1')
    assert stored == result

@pytest.mark.parametrize('case', ['ocr', 'uia', 'screen-parser'])
def test_static_projection_matches_hashless_approved_golden(tmp_path, case):
    from app.learn.recognition.uei.canonical import seal_immutable
    from tests.uei_v1_helpers import load_expected, project_case

    result = project_case(build_context_from_sidecar(tmp_path, case))
    assert result == seal_immutable(load_expected(case))


def _assert_key_absent_recursively(value: object, key: str) -> None:
    if isinstance(value, dict):
        assert key not in value
        for child in value.values():
            _assert_key_absent_recursively(child, key)
    elif isinstance(value, list):
        for child in value:
            _assert_key_absent_recursively(child, key)


@pytest.mark.parametrize(
    ('mutation', 'expected_stage', 'expected_code'),
    [
        (lambda fixture: fixture.pop('capture_id'), 'projection', 'provider_fixture_schema_invalid'),
        (lambda fixture: fixture.__setitem__('artifact_is_authorization', True), 'projection', 'provider_fixture_schema_invalid'),
        (lambda fixture: fixture['elements'][0].__setitem__('bbox', [12, 24, 641, 56]), 'projection', 'provider_fixture_schema_invalid'),
        (lambda fixture: fixture['elements'][0].__setitem__('unexpected_nested', 'synthetic'), 'projection', 'provider_fixture_schema_invalid'),
        (lambda fixture: fixture.__setitem__('unexpected_top_level', 'synthetic'), 'projection', 'provider_fixture_schema_invalid'),
    ],
    ids=['missing-capture', 'authorization-flag', 'out-of-image-bbox', 'extra-nested', 'extra-top-level'],
)
def test_screen_parser_projection_stores_malformed_current_contract_failure(tmp_path, mutation, expected_stage, expected_code):
    from app.learn.recognition.uei.projections import project_screen_parser_result

    context = build_context_from_sidecar(tmp_path, 'screen-parser')
    fixture = deepcopy(load_fixture('screen-parser-result-static.json'))
    mutation(fixture)

    result = project_screen_parser_result(**context.for_case('screen-parser'), fixture=fixture)
    error = context.store.get(result['error_ref'], contract_version='provider_error_v1')

    assert result['status'] == 'failed' and result['items'] == [] and result['review_only'] is True
    assert (error['stage'], error['code']) == (expected_stage, expected_code)
    assert context.store.write_order[-2:] == ('provider_error_v1', 'provider_safe_result_v1')


def test_uia_and_screen_parser_projection_inputs_are_immutable_and_screen_bbox_never_persists_recursively(tmp_path):
    from app.learn.recognition.uei.projections import project_screen_parser_result, project_uia_snapshot

    uia_context = build_context_from_sidecar(tmp_path / 'uia', 'uia')
    uia_fixture = load_fixture('uia-snapshot-static.json')
    uia_before = deepcopy(uia_fixture)
    uia_result = project_uia_snapshot(**uia_context.for_case('uia'), fixture=uia_fixture)
    assert uia_fixture == uia_before
    _assert_key_absent_recursively(uia_result, 'screen_bbox')
    stored_uia = uia_context.store.get(
        {'id': uia_result['result_id'], 'content_sha256': uia_result['content_sha256']},
        contract_version='provider_safe_result_v1',
    )
    _assert_key_absent_recursively(stored_uia, 'screen_bbox')

    parser_context = build_context_from_sidecar(tmp_path / 'screen-parser', 'screen-parser')
    parser_fixture = load_fixture('screen-parser-result-static.json')
    parser_before = deepcopy(parser_fixture)
    parser_result = project_screen_parser_result(**parser_context.for_case('screen-parser'), fixture=parser_fixture)
    assert parser_fixture == parser_before
    assert not (_walk_keys(parser_result) & _FORBIDDEN)


def test_uia_projection_accepts_truthful_nullable_root_automation_id(tmp_path):
    from app.learn.recognition.uei.projections import project_uia_snapshot

    context = build_context_from_sidecar(tmp_path, 'uia')
    fixture = deepcopy(load_fixture('uia-snapshot-static.json'))
    fixture['controls'][0]['automation_id'] = None

    result = project_uia_snapshot(**context.for_case('uia'), fixture=fixture)

    assert result['status'] == 'success'
    assert result['review_only'] is True
    assert result['items'][0]['opaque_attributes']['automation_id'] is None


def test_uia_projection_accepts_truthful_nullable_descendant_metadata(tmp_path):
    from app.learn.recognition.uei.projections import project_uia_snapshot

    context = build_context_from_sidecar(tmp_path, 'uia')
    fixture = deepcopy(load_fixture('uia-snapshot-static.json'))
    descendant = deepcopy(fixture['controls'][0])
    descendant.update({
        'control_id': 'uia_1_unknown_descendant',
        'name': None,
        'control_type': None,
        'automation_id': None,
        'class_name': None,
        'bbox': {'x': 120, 'y': 24, 'w': 80, 'h': 32},
        'screen_bbox': {'x': 220, 'y': 224, 'w': 80, 'h': 32},
        'enabled': None,
        'visible': None,
        'patterns': [],
    })
    fixture['controls'].append(descendant)
    fixture['control_count'] = 2

    result = project_uia_snapshot(**context.for_case('uia'), fixture=fixture)

    assert result['status'] == 'success'
    assert result['review_only'] is True
    assert result['items'][1]['safe_text'] is None
    assert result['items'][1]['safe_role'] is None
    assert result['items'][1]['safe_states'] == []
    assert result['items'][1]['opaque_attributes'] == {
        'automation_id': None,
        'class_name': None,
        'patterns': [],
    }


@pytest.mark.parametrize(
    ('field', 'invalid_value'),
    [
        ('name', 7),
        ('name', ''),
        ('control_type', 7),
        ('control_type', ''),
        ('class_name', 7),
        ('class_name', ''),
        ('enabled', 'true'),
        ('visible', 'true'),
    ],
    ids=[
        'name-non-string',
        'name-empty',
        'control-type-non-string',
        'control-type-empty',
        'class-name-non-string',
        'class-name-empty',
        'enabled-non-bool',
        'visible-non-bool',
    ],
)
def test_uia_projection_rejects_invalid_non_null_optional_metadata(tmp_path, field, invalid_value):
    from app.learn.recognition.uei.projections import project_uia_snapshot

    context = build_context_from_sidecar(tmp_path, 'uia')
    fixture = deepcopy(load_fixture('uia-snapshot-static.json'))
    fixture['controls'][0][field] = invalid_value

    result = project_uia_snapshot(**context.for_case('uia'), fixture=fixture)
    error = context.store.get(result['error_ref'], contract_version='provider_error_v1')

    assert (result['status'], error['stage'], error['code']) == (
        'failed',
        'projection',
        'provider_fixture_schema_invalid',
    )


def test_uia_projection_still_rejects_non_string_non_null_automation_id(tmp_path):
    from app.learn.recognition.uei.projections import project_uia_snapshot

    context = build_context_from_sidecar(tmp_path, 'uia')
    fixture = deepcopy(load_fixture('uia-snapshot-static.json'))
    fixture['controls'][0]['automation_id'] = ['not', 'valid']

    result = project_uia_snapshot(**context.for_case('uia'), fixture=fixture)
    error = context.store.get(result['error_ref'], contract_version='provider_error_v1')

    assert (result['status'], error['stage'], error['code']) == (
        'failed',
        'projection',
        'provider_fixture_schema_invalid',
    )


@pytest.mark.parametrize(
    ('case', 'mutate'),
    [
        ('ocr', lambda fixture: fixture.__setitem__('extra', 'safe')),
        ('ocr', lambda fixture: fixture['matches'][0].__setitem__('extra', 'safe')),
        ('ocr', lambda fixture: fixture['matches'][0].__setitem__('score', float('nan'))),
        ('uia', lambda fixture: fixture.__setitem__('control_count', 2)),
        ('uia', lambda fixture: fixture['window'].__setitem__('extra', 'safe')),
        ('uia', lambda fixture: fixture['controls'][0].__setitem__('extra', 'safe')),
    ],
    ids=[
        'ocr-top-extra',
        'ocr-match-extra',
        'ocr-nonfinite-score',
        'uia-count',
        'uia-window-extra',
        'uia-control-extra',
    ],
)
def test_ocr_and_uia_static_source_contract_failures_persist(tmp_path, case, mutate):
    from app.learn.recognition.uei.projections import project_ocr_result, project_uia_snapshot

    context = build_context_from_sidecar(tmp_path, case)
    fixture = deepcopy(load_fixture('ocr-result-static.json' if case == 'ocr' else 'uia-snapshot-static.json'))
    mutate(fixture)
    projection = project_ocr_result if case == 'ocr' else project_uia_snapshot

    result = projection(**context.for_case(case), fixture=fixture)
    error = context.store.get(result['error_ref'], contract_version='provider_error_v1')
    assert (result['status'], error['stage'], error['code']) == ('failed', 'projection', 'provider_fixture_schema_invalid')


def test_ocr_validates_malformed_match_after_legacy_batch_size(tmp_path):
    from app.learn.recognition.uei.canonical import seal_immutable
    from app.learn.recognition.uei.projections import project_ocr_result

    context = build_context_from_sidecar(tmp_path, 'ocr')
    registration = context.store.get(
        context.registration_ref,
        contract_version='trusted_provider_registration_v1',
    )
    registration.pop('content_sha256')
    registration['safe_payload_limits']['max_array_items'] = 10_000
    registration['safe_payload_limits']['max_json_bytes'] = 1_048_576
    registration_ref = context.store.put(seal_immutable(registration))

    fixture = deepcopy(load_fixture('ocr-result-static.json'))
    fixture['matches'] = [deepcopy(fixture['matches'][0]) for _ in range(256)] + [{}]
    arguments = context.for_case('ocr')
    arguments['registration_ref'] = registration_ref

    result = project_ocr_result(**arguments, fixture=fixture)
    error = context.store.get(result['error_ref'], contract_version='provider_error_v1')

    assert (result['status'], error['stage'], error['code']) == (
        'failed',
        'projection',
        'provider_fixture_schema_invalid',
    )
    assert context.store.write_order[-2:] == ('provider_error_v1', 'provider_safe_result_v1')


def test_uei_import_isolated_from_runtime_provider_modules_in_a_clean_subprocess():
    import subprocess
    import sys

    script = '''
import importlib
import sys
importlib.import_module("app.learn.recognition.uei")
blocked = (
    "app.vision",
    "app.vision.local_provider",
    "app.vision.api_provider",
    "app.core.ocr_service",
    "modules.ocr",
)
loaded = set(sys.modules)
assert not [name for name in blocked if name in loaded], sorted(name for name in blocked if name in loaded)
'''
    completed = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_existing_recognition_public_symbols_resolve_lazily():
    import importlib

    recognition = importlib.import_module('app.learn.recognition')
    assert recognition.__all__
    for name in recognition.__all__:
        assert getattr(recognition, name) is not None


def test_existing_learning_public_symbols_resolve_lazily():
    import importlib

    learning = importlib.import_module('app.learn')
    assert learning.__all__
    for name in learning.__all__:
        assert getattr(learning, name) is not None
