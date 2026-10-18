"""中文明确标签必须进入与英文相同的当前控件定位路径。"""
import pytest
from app.operation.recognition.text_match import explicit_target_label, explicit_target_role

@pytest.mark.parametrize('goal,label,role', [
 ('点击名为“还原”的按钮','还原','button'),
 ('点击“保存”按钮','保存','button'),
 ('选择名称为“候选 1”的列表项','候选 1','list item'),
 ('点击“独立界面库”标签页','独立界面库','tab'),
 ('定位叫做“搜索”的输入框','搜索','input'),
 ('点击名为“包含（备注）”的链接','包含（备注）','link'),
])
def test_chinese_explicit_label_and_role(goal,label,role):
    assert explicit_target_label(goal)==label
    assert explicit_target_role(goal)==role

@pytest.mark.parametrize('goal', [
 '不要点击名为“关闭”的按钮',
 '截图上有“还原”的按钮',
 '点击“还原”或“最小化”按钮',
 '点击“还原”的按钮或者“最小化”的按钮',
 '点击名为“还原的按钮',
])
def test_chinese_ambiguous_or_non_action_label_is_not_identity(goal):
    assert explicit_target_label(goal) is None
