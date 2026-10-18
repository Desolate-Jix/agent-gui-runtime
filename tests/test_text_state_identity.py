"""输入框定位不能单独充当所属页面或弹窗的身份确认。"""
from copy import deepcopy

from app.agent.reviewed_workflow_replay import resolve_current_state, select_transition_for_review
from tests.test_reviewed_workflow_replay_v2 import _observation
from tests.test_text_formal_review_flow import _text_review
from test_reviewed_workflow_compiler_v2 import _persist_reviewed_workflow, _run_compile


def _compiled(tmp_path):
    source, digest = _persist_reviewed_workflow(tmp_path, _text_review())
    result = _run_compile(tmp_path, source, digest)
    assert result['status'] == 'compiled'
    asset = result['asset']
    transition = next(t for t in asset['transitions'] if t['semantic_action'] == 'fill_field')
    state = next(s for s in asset['states'] if s['state_id'] == transition['source_state_id'])
    field = next(a for a in state['identity_anchors'] if a.get('text_field_id'))
    identity = next(a for a in state['identity_anchors'] if not a.get('text_field_id'))
    return asset, transition, field, identity


def test_same_named_field_without_interface_identity_cannot_resolve_or_select(tmp_path):
    asset, transition, field, _ = _compiled(tmp_path)
    before = deepcopy(asset)
    current = _observation(asset, 'wrong-state-current', 'a' * 64, field['anchor_id'])
    resolution = resolve_current_state(asset, current)
    assert resolution['status'] == 'blocked'
    assert resolution['failure_code'] == 'current_state_unresolved'
    selection = select_transition_for_review(asset, resolution,
        transition_id=transition['transition_id'], current_observation=current)
    assert selection['status'] == 'blocked'
    assert asset == before


def test_field_with_separate_current_interface_identity_remains_resolvable(tmp_path):
    asset, transition, field, identity = _compiled(tmp_path)
    current = _observation(asset, 'correct-state-current', 'a' * 64, field['anchor_id'], identity['anchor_id'])
    resolution = resolve_current_state(asset, current)
    assert resolution['status'] == 'resolved'
    assert resolution['state_id'] == transition['source_state_id']
    selection = select_transition_for_review(asset, resolution,
        transition_id=transition['transition_id'], current_observation=current)
    assert selection['status'] == 'selected'
    assert resolution['artifact_is_authorization'] is False
