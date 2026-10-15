"""原任务决定期望身份；定位模型只提供混淆选项。"""
from copy import deepcopy

import pytest

from app.judgment import target_identity


def build(goal, options):
    return target_identity.grounding_target_identity(goal, options)


def test_original_goal_is_preserved_and_option_order_cannot_choose_expected():
    goal = "Webpage search field"
    options = ["Browser address bar", "Browser tab title"]
    result = build(goal, options)
    assert result == build(goal, list(reversed(options)))
    expected = next(row for row in result['choices'] if row['value'] == result['expected'])
    assert expected['description'] == goal
    assert result['expected'] == 'c'
    other_task = build("Browser address bar", [goal, "Browser tab title"])
    assert other_task['choices'] == result['choices']
    assert other_task['expected'] == 'a'
    assert target_identity.identity_question(result) == target_identity.identity_question(other_task)


def test_goal_duplicate_is_removed_without_replacing_original_unicode_text():
    goal = "\u6d4f\u89c8\u5668\u5730\u5740\u680f"
    options = [goal + " ", "\u7f51\u9875\u641c\u7d22\u6846"]
    original = deepcopy(options)
    result = build(goal, options)
    assert len(result['choices']) == 2
    assert next(x['description'] for x in result['choices'] if x['value'] == result['expected']) == goal
    assert options == original


@pytest.mark.parametrize('goal,options', [
    ('', ['Other control']), (' ', ['Other control']), (True, ['Other control']),
    ('x' * 4001, ['Other control']), ('Target', None), ('Target', []),
    ('Target', ('Alternative',)), ('Target', ['Alternative'] * 2),
    ('Target', [' Alternative ', 'alternative']), ('Target', [' ']),
    ('Target', [False]), ('Target', ['x' * 4001]),
    ('Target', ['Target']), ('Target', [str(i) for i in range(8)]),
])
def test_bad_or_nonindependent_identity_options_are_rejected(goal, options):
    with pytest.raises(ValueError, match='target_identity'):
        build(goal, options)


def test_maximum_options_and_original_goal_do_not_mutate_model_response():
    options = ['Option ' + str(i) for i in range(7)]
    result = build('Target', options)
    assert len(result['choices']) == 8
    result['choices'][0]['description'] = 'changed'
    assert options[0] == 'Option 0'
