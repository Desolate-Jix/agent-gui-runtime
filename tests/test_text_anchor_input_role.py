"""文本字段锚点接受标准输入角色，但普通点击锚点不能借此扩大匹配。"""
from copy import deepcopy

import pytest

from app.agent.live_runtime_composition import _matching_pairs, _parse_recognition
from tests.test_live_runtime_composition_w3b import _adapter, _RecognitionRunner, _recognition
from tests.test_native_current_evidence import _NativeIdentityReader
from tests.test_text_formal_review_flow import _text_review
from test_reviewed_workflow_compiler_v2 import _persist_reviewed_workflow, _run_compile


@pytest.mark.parametrize('kind', ['control', 'region'])
def test_declared_text_field_matches_canonical_input_role(kind):
    anchor = {'anchor_id': 'editor', 'kind': kind, 'label': '文本编辑器', 'text_field_id': 'body'}
    candidates, local = _parse_recognition(_recognition('文本编辑器', role='input'))
    matches = _matching_pairs(candidates, local, anchor)
    assert len(matches) == 1
    assert matches[0][0].role == 'input'


@pytest.mark.parametrize('change', ['no_field', 'blank_field', 'wrong_label', 'unverified', 'unknown_role', 'text_kind'])
def test_input_role_does_not_bypass_declared_field_or_matching_evidence(change):
    anchor = {'anchor_id': 'editor', 'kind': 'control', 'label': '文本编辑器', 'text_field_id': 'body'}
    raw = _recognition('文本编辑器', role='input')
    if change == 'no_field':
        anchor.pop('text_field_id')
    elif change == 'blank_field':
        anchor['text_field_id'] = ' '
    elif change == 'wrong_label':
        raw['candidate_result']['candidates'][0]['label'] = '其他字段'
        raw['candidate_result']['candidates'][0]['text'] = '其他字段'
        raw['candidate_result']['candidates'][0]['element']['label'] = '其他字段'
        raw['candidate_result']['candidates'][0]['element']['text'] = '其他字段'
    elif change == 'unknown_role':
        raw = _recognition('文本编辑器', role='unknown')
    elif change == 'text_kind':
        anchor['kind'] = 'text'
    candidates, local = _parse_recognition(raw)
    if change == 'unverified':
        local.results[0].status = 'unverified'
    assert _matching_pairs(candidates, local, anchor, allow_text_identity_on_interactive_role=True) == []


@pytest.mark.parametrize('score,expected', [(0.95, True), (0.1, False)])
def test_current_capture_includes_input_anchor_only_with_sufficient_evidence(tmp_path, score, expected):
    source, digest = _persist_reviewed_workflow(tmp_path, _text_review())
    compiled = _run_compile(tmp_path, source, digest)
    assert compiled['status'] == 'compiled'
    asset = compiled['asset']
    anchor = next(a for s in asset['states'] for a in s['identity_anchors'] if a.get('text_field_id') == 'job_card')
    frozen_asset = deepcopy(asset)
    raw = _recognition(anchor['label'], role='input', score=score)
    adapter, *_ = _adapter(tmp_path, asset, runner=_RecognitionRunner({anchor['label']: raw}))
    adapter._native_identity_reader = _NativeIdentityReader(executable_path=r'c:\browser\browser.exe')
    current = adapter.capture_current(session_id='input-anchor', asset=asset, target_window_handle=4242)
    evidence = [a for a in current['observed_anchor_evidence'] if a['anchor_id'] == anchor['anchor_id']]
    assert bool(evidence) is expected
    if expected:
        assert current['capture_id'] in evidence[0]['evidence_ref']
    assert asset == frozen_asset
