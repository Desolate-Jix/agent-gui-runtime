"""长输入框保留点击处原始细节；所有供应商响应均来自离线传输。"""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from app.judgment import OpenAIDecisionsProvider
from app.judgment.candidate_annotation import candidate_annotation_metadata, render_candidate_annotation
from tests.test_decision_candidate_view import png_bytes, metadata
from tests.test_luna_choice_review_provider import candidate_payload, compact_field_payload, decision_body, response_body


def field_source(size=(2560, 1400), bbox=None, point=None):
    bbox = bbox or {'x': 75, 'y': 43, 'w': 2261, 'h': 34}
    point = point or {'x': 326, 'y': 59}
    data = png_bytes(size)
    return data, metadata(data, size, bbox, point)


def field_payload():
    value = candidate_payload()
    data, bound = field_source()
    frame = value['frames'][0]
    frame.update(data_url='data:image/png;base64,' + base64.b64encode(data).decode('ascii'),
        capture_id=bound['capture_id'], candidate_annotation={'metadata': bound,
            'data_url': 'data:image/png;base64,' + base64.b64encode(render_candidate_annotation(data, bound)).decode('ascii')})
    value['action']['candidate'] = {'candidate_id': bound['candidate_id'], 'capture_id': bound['capture_id'],
        'bbox': deepcopy(bound['bbox']), 'click_point': deepcopy(bound['click_point'])}
    value['action']['target_check'] = {'schema': 'target_check.v1', 'kind': 'input_field',
        'target': 'The intended long text field', 'appearance': 'A long horizontal text field', 'container': 'Top toolbar'}
    return value


def wires(value):
    records = []

    def handle(request):
        records.append(request.content)
        return httpx.Response(200, json=decision_body() if request.url.path.endswith('decisions') else response_body())

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('FIELD_VIEW_OFFLINE_KEY', 'synthetic-offline-key')
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            provider = OpenAIDecisionsProvider(api_key_env='FIELD_VIEW_OFFLINE_KEY', client=client)
            provider.judge(value)
            provider.review(value)
    return records


def render_field(data, bound):
    from app.judgment.candidate_view import render_input_field_candidate_view
    return render_input_field_candidate_view(data, bound)


def test_long_field_detail_keeps_original_pixel_height_and_truthful_crop_mapping():
    data, bound = field_source()
    original = deepcopy(bound)
    rendered, mapping = render_field(data, bound)
    overview, detail = mapping['views']
    assert overview['source_crop_ltrb'] == [0, 0, 2560, 1400]
    assert overview['size'] == [640, 350]
    assert detail['source_crop_ltrb'] == [134, 0, 518, 160]
    assert detail['scale_xy'] == [2, 2]
    assert detail['size'] == [768, 320]
    assert mapping['composite_size'] == [768, 718]
    assert bound['bbox']['h'] * detail['scale_xy'][1] >= bound['bbox']['h']
    assert detail['point_in_view_exact'] == [384.5, 118.5]
    assert mapping['source_point'] == bound['click_point'] == {'x': 326, 'y': 59}
    assert mapping['source_bbox'] == bound['bbox'] == original['bbox']
    assert mapping['schema'] == 'decision_candidate_view.v2'
    assert mapping['recipe'] == 'overview_input_field_point384x160_zoom2.v1'
    assert mapping['detail_includes_complete_bbox'] is False
    assert mapping['overview_includes_complete_frame'] is True
    assert detail['crop_edges_are_ui_boundaries'] is False
    assert detail['source_frame_edges'] == {'left': False, 'top': True, 'right': False, 'bottom': False}
    with Image.open(BytesIO(data)) as source, Image.open(BytesIO(rendered)) as output:
        expected = source.convert('RGB').crop(detail['source_crop_ltrb']).resize(detail['size'], Image.Resampling.LANCZOS)
        ox, oy = detail['image_origin_in_composite']
        px, py = detail['marker_center_in_view']
        actual = output.crop((ox + px - 6, oy + py - 6, ox + px + 7, oy + py + 7))
        assert actual.tobytes() == expected.crop((px - 6, py - 6, px + 7, py + 7)).tobytes()
    assert bound == original
    assert render_field(data, bound) == (rendered, mapping)


@pytest.mark.parametrize('point', [
    {'x': 0, 'y': 0}, {'x': 2559, 'y': 0}, {'x': 0, 'y': 1399}, {'x': 2559, 'y': 1399},
])
def test_frame_edge_points_remain_in_the_field_detail(point):
    data, bound = field_source(bbox={'x': 0, 'y': 0, 'w': 2560, 'h': 1400}, point=point)
    _, mapping = render_field(data, bound)
    detail = mapping['views'][1]
    rect = detail['source_crop_ltrb']
    assert rect[0] <= point['x'] < rect[2] and rect[1] <= point['y'] < rect[3]
    assert [rect[2] - rect[0], rect[3] - rect[1]] == [384, 160]
    assert detail['scale_xy'] == [2, 2]
    assert all(0 <= detail['marker_center_in_view'][i] < detail['size'][i] for i in (0, 1))
    assert mapping['source_point'] == point
    assert detail['crop_edges_are_ui_boundaries'] is False


def test_normalized_input_field_route_shares_new_image_and_original_question_between_both_models():
    from app.judgment.target_check import target_check_question
    value = field_payload()
    before = deepcopy(value)
    primary, secondary = [json.loads(x) for x in wires(value)]
    assert primary['questions'] == [target_check_question(value['action']['target_check'])]
    content = primary['input'][0]['content']
    assert secondary['input'][0]['content'][:-1] == content
    mapping = json.loads(content[-1]['text'])['candidate_view']
    assert mapping['recipe'] == 'overview_input_field_point384x160_zoom2.v1'
    assert mapping['detail_includes_complete_bbox'] is False
    image = next(item['image_url'] for item in content if item['type'] == 'input_image')
    expected, _ = render_field(base64.b64decode(value['frames'][0]['data_url'].split(',', 1)[1]),
        value['frames'][0]['candidate_annotation']['metadata'])
    assert base64.b64decode(image.split(',', 1)[1]) == expected
    assert value == before


@pytest.mark.parametrize('point_y', [200, 299])
def test_field_top_and_bottom_edges_are_kept_when_the_vertical_bbox_fits(point_y):
    data, bound = field_source(bbox={'x': 75, 'y': 200, 'w': 2261, 'h': 100},
        point={'x': 1200, 'y': point_y})
    _, mapping = render_field(data, bound)
    detail = mapping['views'][1]
    left, top, right, bottom = detail['source_crop_ltrb']
    assert top <= 200 and bottom >= 300
    assert right - left == 384 and bottom - top == 160
    assert detail['scale_xy'] == [2, 2]
    assert mapping['source_point'] == {'x': 1200, 'y': point_y}


@pytest.mark.parametrize('route', ['legacy', 'graphic'])
def test_wide_graphic_or_goal_text_alone_cannot_enable_input_field_view(route):
    from app.judgment.candidate_view import render_candidate_view
    value = field_payload()
    value['action']['goal'] = 'The intended long input field'
    if route == 'graphic':
        value['action']['target_check']['kind'] = 'graphic'
    else:
        value['action'].pop('target_check')
    body = json.loads(wires(value)[0])
    image = next(item['image_url'] for item in body['input'][0]['content'] if item['type'] == 'input_image')
    frame = value['frames'][0]
    expected, mapping = render_candidate_view(base64.b64decode(frame['data_url'].split(',', 1)[1]),
        frame['candidate_annotation']['metadata'])
    assert base64.b64decode(image.split(',', 1)[1]) == expected
    assert mapping['recipe'] == 'overview_detail_zoom2.v1' and mapping['detail_includes_complete_bbox'] is True


@pytest.mark.parametrize('size,point', [((1, 1), {'x': 0, 'y': 0}), ((119, 61), {'x': 118, 'y': 60})])
def test_small_viewport_keeps_complete_source_and_bounded_zoom(size, point):
    data, bound = field_source(size, {'x': 0, 'y': 0, 'w': size[0], 'h': size[1]}, point)
    _, mapping = render_field(data, bound)
    detail = mapping['views'][1]
    assert detail['source_crop_ltrb'] == [0, 0, *size]
    assert detail['size'] == [size[0] * 2, size[1] * 2]
    assert detail['scale_xy'] == [2, 2]
    assert mapping['detail_includes_complete_bbox'] is True


@pytest.mark.parametrize('route,expected', [
    ('legacy', ('331fb84960c85edf3cd2ef0e691ec21c81683df007b7eb482fade06567b79802',
        '5243e5d29b67b43a128750eb5ea1482f1dda180b0badf3a75fcd658dc03a7c45')),
    ('graphic', ('ab906c1a83eaad57563296813a4dc859696810159865a18bed58eb538213ba2a',
        'a5a449e2e56aed583fc25f6042c122f2afa2466abd0b396029cc8ccee8b988e9')),
    ('value', ('bd28fbb51e80a486282e3a1d98428d6f9646c76350e43b04582f27554e94678b',
        '53587961a628ea9217a1b9d3b2c2a4d281ff7abbb32d71b11c17063765ddbbbd')),
])
def test_legacy_graphic_and_field_value_exact_wire_remain_frozen(route, expected):
    value = compact_field_payload() if route == 'value' else candidate_payload()
    if route == 'graphic':
        value['action']['target_check'] = {'schema': 'target_check.v1', 'kind': 'graphic',
            'target': 'Plus button', 'appearance': 'A plus-shaped icon', 'container': 'Toolbar'}
    assert tuple(sha256(body).hexdigest() for body in wires(value)) == expected


def old_target_check_digest(binding, profile):
    policy = {'profile': profile.model_dump(mode='json'), 'enabled_predicates': [],
        'review_policy': 'adaptive', 'prompt_version': 'decision_prompt.target_check.v2'}
    return sha256(json.dumps({'binding': binding, 'policy': policy}, ensure_ascii=False,
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


@pytest.mark.parametrize('kind', ['input_field', 'graphic'])
def test_field_view_recipe_changes_authentication_without_changing_graphic_policy(tmp_path, monkeypatch, kind):
    from tests.test_decision_choice import runtime
    from tests.test_candidate_current_scope import candidate_args, CANDIDATE_CONDITION
    service, _, client = runtime(tmp_path, monkeypatch, profile={'auto_conditions': [CANDIDATE_CONDITION]})
    args = candidate_args(tmp_path, 'FIELD_VIEW_AUTH')
    args['action']['target_check'] = {'schema': 'target_check.v1', 'kind': kind,
        'target': 'Target field', 'appearance': 'Neutral hint', 'container': 'Toolbar'}
    try:
        binding, _, digest = service._prepare(args)
        legacy = old_target_check_digest(binding, service.profile)
        assert (digest != legacy) is (kind == 'input_field')
    finally:
        service.close()
        client.close()


def test_old_field_view_ledger_cannot_authenticate_or_redispatch_as_new_recipe(tmp_path, monkeypatch):
    from tests.test_decision_choice import runtime
    from tests.test_candidate_current_scope import candidate_args, CANDIDATE_CONDITION
    service, calls, client = runtime(tmp_path, monkeypatch, profile={'auto_conditions': [CANDIDATE_CONDITION]})
    args = candidate_args(tmp_path, 'OLD_FIELD_VIEW_LEDGER')
    args['action']['target_check'] = {'schema': 'target_check.v1', 'kind': 'input_field',
        'target': 'Target field', 'appearance': 'Neutral hint', 'container': 'Toolbar'}
    original = service._prepare

    def legacy_prepare(kwargs, **options):
        binding, frames, _ = original(kwargs, **options)
        return binding, frames, old_target_check_digest(binding, service.profile)

    try:
        # 仅重建旧认证 policy；离线应答不用于声称旧模型准确率。
        with monkeypatch.context() as patch:
            patch.setattr(service, '_prepare', legacy_prepare)
            old = service.evaluate(**args)
            assert old['adopted'] and service.validate_result(old, **args)
        assert not service.validate_result(old, **args)
        replay = service.evaluate(**args)
        assert replay['status'] == 'conflict' and replay['adopted'] is False
        assert len(calls) == 1
    finally:
        service.close()
        client.close()
