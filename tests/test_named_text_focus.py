"""明确标签必须在点击前与真实命中控件绑定，不能靠写入后的值证明。"""
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_text_field_reader as text_reader
from app.agent import windows_form_control_reader as form_reader
from app.core import local_text_focus
from tests.test_windows_form_control_reader import Node, Walker, rect, IDENTITY


@pytest.fixture
def desktop(monkeypatch):
    def build(*nodes):
        root = Node('root', 'Window', (0, 1), children=nodes)
        monkeypatch.setattr(form_reader, '_finite_children', lambda node: node.nodes)
        monkeypatch.setattr(form_reader, '_same_element', lambda a, b: a is b)
        monkeypatch.setattr(form_reader, '_uia_factory', lambda: (
            NS(window=lambda **kw: NS(wrapper_object=lambda: root)), Walker(), lambda raw: raw))
        return root
    return build


@pytest.mark.parametrize('requested,names,hit,reason', [
    ('missing', ['First', 'Second'], 0, 'text_field_label_not_found'),
    ('Second', ['First', 'Second'], 0, 'text_field_label_mismatch'),
    ('First', ['First', 'First'], 0, 'text_field_label_ambiguous'),
])
def test_named_hit_rejects_missing_wrong_or_duplicate_label(desktop, requested, names, hit, reason):
    nodes = [Node(name, 'Edit', (1, i)) for i, name in enumerate(names)]
    desktop(*nodes)
    with pytest.raises(text_reader.TextFieldReadError, match=reason):
        text_reader._verify_named_focus_hit(nodes[hit], 10, 20, (100, 200, 600, 500), requested)


@pytest.mark.parametrize('alias', ['direct', 'labeled_by', 'visible_label_geometry'])
def test_named_hit_preserves_verified_live_labels(desktop, alias):
    field = Node('Name' if alias == 'direct' else '', 'Edit', (1, 1))
    label = Node('Name：', 'Text', (1, 2))
    label.element_info.rectangle = rect(120, 205, 100, 20)
    if alias == 'labeled_by':
        field.CurrentLabeledBy = label
    desktop(field, label)
    text_reader._verify_named_focus_hit(field, 10, 20, (100, 200, 600, 500), ' NAME: ')


def test_direct_name_and_distinct_verified_alias_are_ambiguous(desktop):
    named = Node('Name', 'Edit', (1, 1))
    alias = Node('', 'Edit', (1, 2))
    label = Node('Name', 'Text', (1, 3))
    alias.CurrentLabeledBy = label
    desktop(named, alias, label)
    with pytest.raises(text_reader.TextFieldReadError, match='text_field_label_ambiguous'):
        text_reader._verify_named_focus_hit(named, 10, 20, (100, 200, 600, 500), 'Name')


def test_named_identity_failure_cannot_publish_binding_or_click(monkeypatch):
    calls = []
    def probe(manager, handle, pid, point, *, expected_label=None):
        assert expected_label == 'Missing'
        raise text_reader.TextFieldReadError('text_field_label_not_found')
    monkeypatch.setattr(local_text_focus, 'probe_local_focus_target', probe)
    monkeypatch.setattr(local_text_focus, 'require_local_operator_input', lambda manager: True)
    target = local_text_focus.LocalTextFocusTarget(10, 20, expected_label='Missing')
    with local_text_focus.local_text_focus_scope(target):
        with pytest.raises(text_reader.TextFieldReadError, match='text_field_label_not_found'):
            local_text_focus.check_local_text_focus({'x': 40, 'y': 45}, object())
            calls.append('click')
    assert calls == [] and target.binding is None


def test_form_declared_label_reaches_preclick_target(monkeypatch):
    from tests.test_form_fill import Coordinator, text_reader as setup_text_reader, run, TEXT
    setup_text_reader(monkeypatch, '', 'Ada')
    coordinator = Coordinator()
    result = run(coordinator, {**TEXT, 'label': 'Name'})
    assert result['status'] == 'completed'
    assert coordinator.calls[0]['focus_target'].expected_label == 'Name'


def test_real_probe_enforces_label_before_returning_binding(monkeypatch):
    from tests.test_windows_text_field_reader import field
    wrapper = field(kind='Group', text='')
    wrapper.element_info.process_id = 20
    wrapper.element_info.rectangle = rect(20, 30, 100, 40)
    wrapper.is_visible = lambda: True
    wrapper.is_enabled = lambda: True
    wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
    wrapper.iface_text.DocumentRange.GetAttributeValue = lambda _: False
    del wrapper.iface_value
    manager = NS(get_bound_window=lambda: NS(handle=10, process_id=20, rect=rect(0, 0)))
    monkeypatch.setattr(text_reader, 'WindowsNativeIdentityReader', lambda **kw: NS(read_identity=lambda _: IDENTITY))
    monkeypatch.setattr(text_reader, '_no_pattern_exception', lambda: AttributeError)
    monkeypatch.setattr(text_reader, '_desktop_factory', lambda **kw: NS(from_point=lambda *args: wrapper))
    monkeypatch.setattr(text_reader.WindowsTextFieldReader, '_verify_binding', lambda *args: None)
    calls = []
    def reject(hit, handle, pid, window, label):
        calls.append((hit, label))
        raise text_reader.TextFieldReadError('text_field_label_not_found')
    monkeypatch.setattr(text_reader, '_verify_named_focus_hit', reject)
    with pytest.raises(text_reader.TextFieldReadError, match='text_field_label_not_found'):
        text_reader.probe_local_focus_target(manager, 10, 20, (40, 45), expected_label='Missing')
    assert calls == [(wrapper, 'Missing')]
