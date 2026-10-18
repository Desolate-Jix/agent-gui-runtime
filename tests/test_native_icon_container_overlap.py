"""容器几何重叠不能取代实际原生命中；具体控件歧义继续拒绝。"""
from copy import deepcopy
import pytest

from app.operation.recognition.native_control_hit_binding import current_icon_control


def _tree():
    target = {'control_id': 'search-button', 'control_type': 'Button', 'name': 'Find',
        'visible': True, 'enabled': True, 'patterns': ['Invoke'], 'runtime_id': [42, 1],
        'bbox': {'x': 100, 'y': 100, 'w': 40, 'h': 40}, 'ancestor_control_ids': []}
    container = {'control_id': 'page-container', 'control_type': 'Group', 'name': None,
        'visible': True, 'enabled': True, 'patterns': ['Invoke'], 'runtime_id': [42, 2],
        'bbox': {'x': 0, 'y': 0, 'w': 500, 'h': 300}, 'ancestor_control_ids': []}
    return {'status': 'ok', 'scan_complete': True, 'truncated': False,
        'controls': [target, container]}


def test_container_does_not_prevent_collecting_actual_native_hit():
    tree = _tree()
    assert current_icon_control(tree, {'x': 120, 'y': 120}) == tree['controls'][0]


@pytest.mark.parametrize('change', ['named', 'button', 'editable', 'same_box', 'partial', 'patterns'])
def test_concrete_or_ambiguous_overlap_still_rejected(change):
    tree = _tree()
    other = tree['controls'][1]
    if change == 'named': other['name'] = 'Confirm'
    elif change == 'button': other['control_type'] = 'Button'
    elif change == 'editable': other['control_type'] = 'Edit'
    elif change == 'same_box': other['bbox'] = deepcopy(tree['controls'][0]['bbox'])
    elif change == 'partial': other['bbox'] = {'x': 110, 'y': 110, 'w': 100, 'h': 100}
    else: other['patterns'] = ['Invoke', 'Value']
    assert current_icon_control(tree, {'x': 120, 'y': 120}) is None
