"""普通图片和文字背景不等于滚轮输入控件；真实交互覆盖仍拒绝。"""
from copy import deepcopy

import pytest

from app.agent.fresh_scroll_region import current_scroll_container
from tests.test_current_scroll_grounding import _controls, _public_observe


@pytest.mark.parametrize('kind', ['Image', 'Text'])
def test_passive_background_does_not_block_real_scroll_owner(tmp_path, monkeypatch, kind):
    def alter(uia):
        background = deepcopy(uia['controls'][1])
        background.update(control_id='background', runtime_id=[42, 999],
                          control_type=kind, patterns=[], name='')
        uia['controls'].append(background)
        uia['control_count'] = len(uia['controls'])
    bundle, state = _public_observe(tmp_path, monkeypatch, alter=alter)
    result = bundle.recognition_result()
    assert result['candidate_result']['candidates'][0]['element']['interaction_type'] == 'scroll'
    assert state['hits'] == []


@pytest.mark.parametrize('kind', ['Image', 'Text', 'Button', 'Edit', 'Slider'])
def test_interactive_background_still_blocks_scroll(kind):
    controls = _controls()
    overlay = deepcopy(controls[1])
    overlay.update(control_id='interactive', runtime_id=[42, 999],
                   control_type=kind, patterns=['Invoke'])
    controls.append(overlay)
    with pytest.raises(ValueError, match='non-container input'):
        current_scroll_container(controls, {'x': 50, 'y': 50}, target_container_id='panel')
