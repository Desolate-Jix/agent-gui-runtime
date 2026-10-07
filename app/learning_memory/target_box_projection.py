"""在已验证的原动作帧中投影目标，不保存任意屏幕坐标。"""
from .target_resolution import _matches_control
from .target_recipe_proposal import _TARGET_TYPES
from .uia_rows import _inside, _matches, _row_action_matches


def box_list(box):
    return [box[key] for key in ('x', 'y', 'w', 'h')]


def viewport(frame):
    return {'x': 0, 'y': 0, 'w': frame['image_size']['width'], 'h': frame['image_size']['height']}


def overlaps(a, b):
    return (a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w']
            and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h'])


def row_members(controls, strategy, frame):
    containers = [c for c in controls if _matches(c, strategy['container'])]
    if len(containers) != 1:
        raise ValueError('target_box_container_not_unique')
    container = containers[0]
    if not _inside(container.get('bbox'), viewport(frame)):
        raise ValueError('target_box_container_geometry_invalid')
    rows = [c for c in controls if container['control_id'] in c.get('ancestor_control_ids', [])
            and _matches(c, strategy['row']) and _inside(c.get('bbox'), container['bbox'])]
    return [(row, c) for row in rows for c in controls
            if (c is row if strategy['action'].get('source') == 'row' else row['control_id'] in c.get('ancestor_control_ids', []))
            and (strategy['action'].get('source') != 'row_name' or _row_action_matches(c, strategy['action'], row))
            and container['control_id'] in c.get('ancestor_control_ids', [])
            and _inside(c.get('bbox'), row['bbox'])]


def project_target_boxes(recipe, observation):
    controls = observation['uia']['snapshot']['controls']
    frame = observation['frame']
    boxes, issues = [], []
    for index, strategy in enumerate(recipe['strategies']):
        try:
            if strategy['kind'] == 'uia':
                candidates = [c for c in controls if _matches_control(c, strategy)]
                meaning = 'learning_target'
            elif strategy['kind'] == 'visible_row':
                point = observation['candidate']['click_point']
                candidates = [c for row, c in row_members(controls, strategy, frame)
                    if row['bbox']['x'] <= point['x'] < row['bbox']['x'] + row['bbox']['w']
                    and row['bbox']['y'] <= point['y'] < row['bbox']['y'] + row['bbox']['h']
                    and _matches(c, strategy['action'])]
                meaning = 'learning_example'
            else:
                raise ValueError('target_box_strategy_unsupported')
            if len(candidates) != 1:
                raise ValueError('target_box_control_not_unique')
            control = candidates[0]
            if not _inside(control.get('bbox'), viewport(frame)):
                raise ValueError('target_box_control_geometry_invalid')
            name = control.get('name') or control.get('automation_id') or ''
            boxes.append({'region_id': f'strategy-{index}', 'strategy_index': index,
                'bbox': box_list(control['bbox']), 'name': name, 'kind': strategy['kind'],
                'meaning': meaning, 'recognition_text': control.get('name') or ''})
        except ValueError as error:
            issues.append({'strategy_index': index, 'reason': str(error)})
    return boxes, issues


def select_box_control(controls, frame, action, bbox, *, row_strategy=None):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError('target_box_invalid')
    box = dict(zip(('x', 'y', 'w', 'h'), bbox))
    if not _inside(box, viewport(frame)):
        raise ValueError('target_box_outside_frame')
    types = _TARGET_TYPES.get(action.get('kind'), set())
    if row_strategy is not None:
        if action.get('kind') != 'click' or row_strategy.get('action', {}).get('source') != 'row_name':
            raise ValueError('target_box_strategy_unsupported')
        # 名称子区例外只来自当前行的显式关系，不扩大普通控件点击集。
        controls = [c for row, c in row_members(controls, row_strategy, frame)]
        types = types | {'Edit'}
    eligible = [c for c in controls if c.get('visible') is True and c.get('enabled') is True
        and c.get('control_type') in types and _inside(c.get('bbox'), viewport(frame))]
    touched = [c for c in eligible if overlaps(box, c['bbox'])]
    if len(touched) != 1:
        raise ValueError('target_box_ambiguous' if touched else 'target_box_control_missing')
    if not _inside(box, touched[0]['bbox']):
        raise ValueError('target_box_not_inside_control')
    return touched[0]
