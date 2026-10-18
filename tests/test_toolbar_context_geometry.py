"""工具栏边界和实际变化叶节点分别验证，不创建桌面动作权限。"""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.agent.control_uia_stability import compare_navigation_uia_context
from app.agent.text_uia_stability import compare_fill_uia_context
from tests.test_control_uia_stability import _fixture as navigation_fixture, _bind
from tests.test_text_uia_stability import _fixture as text_fixture


@pytest.mark.parametrize("navigation", [False, True])
@pytest.mark.parametrize("toolbar_bottom,leaf_x,expected", [
    (197, 800, True),
    (211, 800, True),
    (149, 800, True),
    (212, 800, True),
    (213, 800, False),
    (212, 400, False),
])
def test_toolbar_boundary_separation_and_remote_leaf_distance(navigation, toolbar_bottom, leaf_x, expected):
    args = navigation_fixture() if navigation else text_fixture()
    for prefix in ("original", "current"):
        toolbar, leaf = args[prefix + "_uia"]["controls"][1:3]
        toolbar["bbox"].update(h=toolbar_bottom)
        toolbar["screen_bbox"].update(h=toolbar_bottom)
        leaf_y = min(170, toolbar_bottom-20)
        leaf["bbox"].update(x=leaf_x, y=leaf_y, h=20)
        leaf["screen_bbox"].update(x=leaf_x + 100, y=leaf_y + 50, h=20)
    _bind(args)
    before = deepcopy(args)
    compare = compare_navigation_uia_context if navigation else compare_fill_uia_context
    if expected:
        assert compare(**args)["changes"][0]["control_id"] == "badge"
    else:
        with pytest.raises(ValueError, match="protected field context"):
            compare(**args)
    assert args == before


@pytest.mark.parametrize("navigation", [False, True])
def test_full_width_toolbar_with_fifteen_pixel_gap_and_remote_badge(navigation):
    args = navigation_fixture() if navigation else text_fixture()
    key = "control_identity" if navigation else "field_identity"
    args[key] = replace(args[key], window_rect=(100, 50, 2560, 1400), control_bbox=(116, 103, 246, 24))
    boxes = [(0, 0, 2560, 1400), (0, 40, 2560, 40), (2133, 44, 32, 32),
             (76, 80, 392, 184), (116, 103, 246, 24), (116, 135, 160, 20)]
    for prefix in ("original", "current"):
        uia, evidence = args[prefix + "_uia"], args[prefix + "_evidence"]
        uia["window"]["bbox"].update(w=2560, h=1400)
        evidence["target"]["rect"].update(width=2560, height=1400)
        evidence["capture"]["viewport_size"].update(width=2560, height=1400)
        for control, (x, y, w, h) in zip(uia["controls"], boxes):
            control["bbox"] = dict(x=x, y=y, w=w, h=h)
            control["screen_bbox"] = dict(x=x+100, y=y+50, w=w, h=h)
    _bind(args)
    compare = compare_navigation_uia_context if navigation else compare_fill_uia_context
    assert compare(**args)["changes"][0]["control_id"] == "badge"
