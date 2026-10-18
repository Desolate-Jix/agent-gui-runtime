"""整理草稿摘要与保存并发基线分别保留。"""
from copy import deepcopy
from test_workflow_steps_ui import generated, qt_app, _pane


def test_open_draft_summary_save_and_discard_keep_distinct_baselines(qt_app, generated, monkeypatch):
    pane = _pane(qt_app, generated)
    baseline = deepcopy(pane.snapshot)
    template = deepcopy(baseline['definition']['steps'][0])
    second = deepcopy(template)
    second['step_id'] = 'second-step'
    baseline['definition']['steps'].append(second)
    definition = deepcopy(baseline['definition'])
    for step in definition['steps']:
        step['verification'] = {'kind': 'agent_judgment'}
    third = deepcopy(template)
    third.update(step_id='read-step', action={'kind': 'read_text', 'goal': '读取新内容'},
                 read_spec={'method': 'agent_read', 'target': {}, 'output_name': 'read_value'})
    third.pop('verification', None)
    definition['steps'].append(third)
    def open_draft():
        pane._learning_result = {'status': 'draft_ready', 'program': deepcopy(baseline),
            'synthesis': {'draft': {'workflow_id': baseline['workflow_id'], 'definition': deepcopy(definition)}}}
        pane.open_learning_draft()
    open_draft()
    assert pane.steps.count() == 3
    assert '共 3 步' in pane.definition_summary.text()
    assert 'Agent 判断 2 步' in pane.definition_summary.text()
    assert pane.definition['steps'][2]['read_spec'] == third['read_spec']
    assert pane.snapshot == baseline
    pane.discard()
    assert pane.definition == baseline['definition']
    assert '共 2 步' in pane.definition_summary.text()
    open_draft()
    pane.steps.setCurrentRow(2)
    captured = []
    def save(workflow_id, content_sha256, edited, request_id, **kwargs):
        captured.append((workflow_id, content_sha256, deepcopy(edited)))
        return {**deepcopy(baseline), 'program_id': 'saved-version', 'definition': deepcopy(edited)}
    monkeypatch.setattr(pane.facade, 'save_workflow_program', save)
    pane.save()
    assert captured[0][0:2] == (baseline['workflow_id'], baseline['content_sha256'])
    assert len(captured[0][2]['steps']) == 3
    assert captured[0][2]['steps'][2]['read_spec'] == third['read_spec']
    assert not pane.dirty
    pane.review.setCurrentIndex(pane.review.findData('reviewed'))
    assert pane.dirty
    assert '以下为已保存版本' in pane.definition_summary.text()
    assert '已审核 0' in pane.definition_summary.text()
    pane.discard()
    pane.close()
