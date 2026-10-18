"""当前实机运行器的本地预览投影回归；不执行运行器顶层副作用。"""
import ast
import json
from pathlib import Path

import pytest

from app.agent.text_parameters import ReviewedTextParameters, ReviewedTextSource, resolve_text_parameters
from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot, prepare_text_field_expectation


def export_function(name='public_demo_fill_preview'):
    path = Path(__file__).resolve().parents[1] / '.superpowers/sdd/2026-09-13-formal-release/learn_map_home.py'
    parsed = ast.parse(path.read_text(encoding='utf-8'))
    node = next(x for x in parsed.body if isinstance(x, ast.FunctionDef) and x.name == name)
    namespace = {'json': json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


def view(text='OpenStreetMap', before=''):
    resolved = resolve_text_parameters(ReviewedTextParameters('field', ReviewedTextSource('literal', text), True, False), {})
    identity = TextFieldIdentity('field', 1, 2, 3.0, (42, 12), (0, 0, 500, 300), (10, 10, 200, 30))
    snapshot = TextFieldSnapshot(identity, 'capture', 'read', 1, 'uia_value', before, None)
    expected = prepare_text_field_expectation(snapshot, resolved)
    return {'phase': 'pending_review', 'png_bytes': b'not-an-image', 'text_input_local': resolved,
        'text_field_local': expected, 'preview': {'text_field_expectation_ref': expected.to_reference()}}


def test_real_typed_local_preview_is_json_without_changing_authoritative_objects():
    original = view()
    exported = export_function()(original)
    assert json.loads(json.dumps(exported)) == exported
    assert exported['local_public_text']['text'] == 'OpenStreetMap'
    assert exported['local_public_text']['before'] == ''
    assert exported['local_public_text']['artifact_is_authorization'] is False
    assert original['text_input_local'].text == 'OpenStreetMap'
    assert 'text_input_local' not in exported and 'png_bytes' not in exported


@pytest.mark.parametrize('text,before', [('unapproved-value', ''), ('OpenStreetMap', 'private-old-value')])
def test_unapproved_text_or_nonempty_field_is_not_exported(text, before):
    with pytest.raises(ValueError):
        export_function()(view(text, before))


def test_mismatched_reference_and_unknown_types_fail_explicitly():
    original = view()
    original['preview']['text_field_expectation_ref'] = {}
    with pytest.raises(ValueError):
        export_function()(original)
    original = view()
    original['unknown'] = object()
    with pytest.raises(TypeError):
        export_function()(original)


def test_navigation_export_preserves_exact_preview_without_borrowing_text_evidence():
    export = export_function('public_demo_navigation_preview')
    original = {'png_bytes': b'png', 'preview': {'intent': {'semantic_action': 'open_detail'}}}
    assert export(original) == {'preview': original['preview']}
    original['text_input_local'] = object()
    with pytest.raises(ValueError):
        export(original)
    original.pop('text_input_local')
    original['preview']['intent']['semantic_action'] = 'fill_field'
    with pytest.raises(ValueError):
        export(original)
