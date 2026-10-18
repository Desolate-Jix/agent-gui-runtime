from copy import deepcopy
import importlib.util

import pytest


GOAL = 'Right click inside the text area of the document'


def fixture():
    control = {'control_id': 'edit', 'control_type': 'Edit', 'name': 'probe',
        'enabled': True, 'visible': True, 'patterns': ['Value', 'Scroll'],
        'bbox': {'x': 0, 'y': 0, 'w': 1471, 'h': 920},
        'native_client_geometry': {'status': 'ok', 'source': 'win32_edit_client_rect',
            'coordinate_space': 'capture_image_pixels', 'native_window_handle': 11,
            'bbox': {'x': 2, 'y': 2, 'w': 1448, 'h': 897}}}
    uia = {'provider': 'windows_uia', 'status': 'ok', 'scan_complete': True,
           'truncated': False, 'scan_scope': 'bound_window', 'controls': [control]}
    return {'status': 'ready', 'raw_uia_snapshot': uia,
        'screen_reading': {'image_path': 'frame.png', 'image_size': {'width': 1471, 'height': 942},
                           'source_layers': {'windows_uia': uia}}}


def locate(fast=None, **kwargs):
    assert importlib.util.find_spec('app.operation.recognition.native_edit_target') is not None
    from app.operation.recognition.native_edit_target import native_edit_primary_point
    return native_edit_primary_point(fast or fixture(), goal=kwargs.get('goal', GOAL),
        image_path='frame.png', image_size={'width': 1471, 'height': 942},
        control_target=kwargs.get('control_target'), target_text=kwargs.get('target_text'))


def test_generic_right_click_uses_current_client_center_not_model_scrollbar_point():
    fast = fixture()
    before = deepcopy(fast)
    result = locate(fast)
    assert result['point'] == {'x': 726, 'y': 450}
    assert result['control_id'] == 'edit'
    assert result['coordinate_source'] == 'current_native_edit_client_center'
    assert result['client_bbox'] == {'x': 2, 'y': 2, 'w': 1448, 'h': 897}
    assert fast == before


@pytest.mark.parametrize('mutation', ['two_edits', 'incomplete', 'truncated', 'wrong_frame',
    'wrong_size', 'missing_geometry', 'unavailable', 'wrong_source', 'screen_coordinates',
    'outside_edit', 'outside_frame', 'zero_width', 'disabled', 'hidden', 'duplicate_id',
    'point_over_button', 'raw_layer_mismatch', 'menu_scope'])
def test_primary_requires_current_unique_native_client_geometry(mutation):
    fast = fixture()
    uia = fast['raw_uia_snapshot']
    edit = uia['controls'][0]
    geo = edit['native_client_geometry']
    if mutation == 'two_edits': uia['controls'].append({**deepcopy(edit), 'control_id': 'other'})
    elif mutation == 'incomplete': uia['scan_complete'] = False
    elif mutation == 'truncated': uia['truncated'] = True
    elif mutation == 'wrong_frame': fast['screen_reading']['image_path'] = 'stale.png'
    elif mutation == 'wrong_size': fast['screen_reading']['image_size']['width'] = 100
    elif mutation == 'missing_geometry': edit.pop('native_client_geometry')
    elif mutation == 'unavailable': geo['status'] = 'unavailable'
    elif mutation == 'wrong_source': geo['source'] = 'model'
    elif mutation == 'screen_coordinates': geo['coordinate_space'] = 'screen_pixels'
    elif mutation == 'outside_edit': geo['bbox']['x'] = 40
    elif mutation == 'outside_frame': geo['bbox']['h'] = 1000
    elif mutation == 'zero_width': geo['bbox']['w'] = 0
    elif mutation == 'disabled': edit['enabled'] = False
    elif mutation == 'hidden': edit['visible'] = False
    elif mutation == 'duplicate_id': uia['controls'].append({**edit, 'control_type': 'Button'})
    elif mutation == 'point_over_button': uia['controls'].append({'control_id': 'button',
        'control_type': 'Button', 'visible': True, 'enabled': True,
        'bbox': {'x': 700, 'y': 440, 'w': 100, 'h': 40}})
    elif mutation == 'raw_layer_mismatch': fast['screen_reading']['source_layers']['windows_uia'] = {}
    elif mutation == 'menu_scope': uia['scan_scope'] = 'menu_subtree'
    assert locate(fast) is None


@pytest.mark.parametrize('kwargs', [{'goal': 'Click the text area'},
    {'goal': 'Right click the Quick search input box'},
    {'goal': 'Right click the word probe inside the text area'},
    {'target_text': 'probe'}, {'control_target': {'label': 'probe'}}])
def test_specific_or_non_context_actions_are_not_replaced_by_generic_center(kwargs):
    assert locate(**kwargs) is None


def test_full_plan_uses_native_primary_without_invoking_visual_guess(tmp_path, monkeypatch):
    from PIL import Image
    from app.api import vision
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    path = tmp_path / 'frame.png'
    Image.new('RGB', (1471, 942)).save(path)
    def unexpected(**kwargs):
        pytest.fail('unique native Edit client area must not be guessed by a visual model')
    monkeypatch.setattr(vision, '_call_vista_point_prompt', unexpected)
    monkeypatch.setattr(vision, '_call_vista_point_grounding', unexpected)
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(path), task='locate_element',
        goal=GOAL, provider_mode='local_grounding', agent_mode='execute',
        write_policy={'path_graph': False, 'element_memory': False, 'trace': False}, metadata={})
    with pinned_uia_snapshot(fixture()['raw_uia_snapshot']), pinned_runtime_output_root(tmp_path):
        result = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={'vision': {'mode': 'local_grounding'}}, local_config={'model_name': 'unused'},
            image_path=path, input_image_size=vision.ImageSize(width=1471, height=942), goal=GOAL,
            observe_reuse={}, path_graph_recall={'status': 'not_requested', 'candidates': []}).data['result']
    local = result['narrow_search_result']['results'][0]
    assert local['coordinate_source'] == 'current_native_edit_client_center'
    assert local['refined_click_point'] == {'x': 726, 'y': 450}
    assert local['matched_text'] is None
    assert result['execution_path']['vision_model_used'] is False
    assert result['execution_path']['action_executed'] is False
    assert result['model_io']['attempt_count'] == 0
