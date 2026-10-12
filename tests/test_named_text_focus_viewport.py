"""屏幕外同名副本不参与当前窗口命中的歧义判断，未知或相交几何仍拒绝。"""
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_text_field_reader as text_reader
from tests.test_named_text_focus import desktop
from tests.test_windows_form_control_reader import Node, rect


WINDOW = (684, 0, 1410, 1032)


def fields(desktop, duplicate_box):
    hit = Node('Quick search', 'Edit', (1, 1))
    hit.element_info.rectangle = rect(1740, 100, 152, 21)
    duplicate = Node('Quick search', 'Edit', (1, 2), visible=True)
    duplicate.element_info.rectangle = duplicate_box
    desktop(hit, duplicate)
    return hit


@pytest.mark.parametrize('box', [
    (1740, 1447, 152, 21), (1740, -21, 152, 21),
    (2094, 100, 152, 21), (532, 100, 152, 21),
])
def test_only_proven_nonintersecting_duplicate_is_excluded(desktop, box):
    # 首项取自 Edge05；UIA 的 visible=True 不能替代窗口交集。
    hit = fields(desktop, rect(*box))
    text_reader._verify_named_focus_hit(hit, 10, 20, WINDOW, 'Quick search')


@pytest.mark.parametrize('box', [
    rect(1740, 400, 152, 21), rect(1740, 1020, 152, 21),
    rect(2085, 100, 152, 21), rect(680, 100, 152, 21),
    rect(1740, -10, 152, 21), None,
    NS(left=1740, top=1447, right=1740, bottom=1468),
    NS(left='1740', top=1447, right=1892, bottom=1468),
])
def test_visible_partial_or_unknown_duplicate_remains_ambiguous(desktop, box):
    hit = fields(desktop, box)
    with pytest.raises(text_reader.TextFieldReadError, match='text_field_label_ambiguous'):
        text_reader._verify_named_focus_hit(hit, 10, 20, WINDOW, 'Quick search')


def test_window_offset_on_negative_monitor_is_respected(desktop):
    hit = fields(desktop, rect(-500, 1100, 152, 21))
    hit.element_info.rectangle = rect(-500, 200, 152, 21)
    text_reader._verify_named_focus_hit(hit, 10, 20, (-1600, 100, 1400, 900), 'Quick search')


def test_exclusion_cannot_replace_hit_identity_with_another_control(desktop):
    hit = fields(desktop, rect(1740, 1447, 152, 21))
    hit.element_info.name = 'Different field'
    with pytest.raises(text_reader.TextFieldReadError, match='text_field_label_not_found'):
        text_reader._verify_named_focus_hit(hit, 10, 20, WINDOW, 'Quick search')
