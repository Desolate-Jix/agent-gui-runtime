"""泛型编辑区右键使用当前原生客户区，不猜滚动条附近的模型点。"""
from collections.abc import Mapping
from pathlib import Path
import re

from .control_target import generic_field_target, uia_action_identity_matches, uia_control_is_action_identity


def _box(value):
    return (isinstance(value, Mapping) and all(type(value.get(k)) is int for k in ('x', 'y', 'w', 'h'))
            and value['w'] > 0 and value['h'] > 0)


def _contains(outer, inner):
    return (_box(outer) and _box(inner) and outer['x'] <= inner['x'] and outer['y'] <= inner['y']
            and inner['x'] + inner['w'] <= outer['x'] + outer['w']
            and inner['y'] + inner['h'] <= outer['y'] + outer['h'])


def native_edit_primary_point(fast_inventory, *, goal, image_path, image_size,
                              control_target=None, target_text=None):
    if (not re.match(r'\s*right[ -]?click\b', goal, re.I)
            or not generic_field_target(goal, control_target=control_target, target_text=target_text)
            or fast_inventory.get('status') != 'ready'):
        return None
    reading = fast_inventory.get('screen_reading') or {}
    uia = fast_inventory.get('raw_uia_snapshot') or {}
    layer = (reading.get('source_layers') or {}).get('windows_uia') or {}
    if (not reading.get('image_path') or Path(reading['image_path']) != Path(image_path)
            or reading.get('image_size') != image_size
            or layer.get('status') != 'ok' or layer.get('scan_complete') is not True
            or layer.get('truncated') is not False
            or uia.get('status') != 'ok' or uia.get('scan_complete') is not True
            or uia.get('truncated') is not False or uia.get('scan_scope', 'bound_window') != 'bound_window'):
        return None
    controls = uia.get('controls') or []
    if not all(isinstance(c, dict) for c in controls):
        return None
    matches = [c for c in controls if uia_action_identity_matches(c, goal=goal)]
    if len(matches) != 1:
        return None
    control = matches[0]
    if sum(c == control for c in layer.get('controls', [])) != 1:
        return None
    control_id = control.get('control_id')
    geometry = control.get('native_client_geometry') or {}
    client = geometry.get('bbox')
    viewport = {'x': 0, 'y': 0, 'w': image_size.get('width'), 'h': image_size.get('height')}
    if (not control_id or sum(c.get('control_id') == control_id for c in controls) != 1
            or control.get('visible') is not True or control.get('enabled') is not True
            or geometry.get('status') != 'ok' or geometry.get('source') != 'win32_edit_client_rect'
            or geometry.get('coordinate_space') != 'capture_image_pixels'
            or type(geometry.get('native_window_handle')) is not int or geometry['native_window_handle'] <= 0
            or not _contains(control.get('bbox'), client) or not _contains(viewport, client)):
        return None
    point = {'x': client['x'] + client['w'] // 2, 'y': client['y'] + client['h'] // 2}
    footprint = {**point, 'w': 1, 'h': 1}
    # 已观察到的独立动作控件遮住中心时不冒充文本内容。
    if any(c is not control and c.get('visible') is not False and uia_control_is_action_identity(c)
           and _contains(c.get('bbox'), footprint) for c in controls):
        return None
    return {'control_id': control_id, 'point': point, 'client_bbox': dict(client),
            'coordinate_source': 'current_native_edit_client_center',
            'source': 'win32_edit_client_rect', 'native_window_handle': geometry['native_window_handle']}
