"""重现真实 Chromium 搜索框的对象范围，不访问桌面。"""
from types import SimpleNamespace as NS

import pytest

from app.agent.windows_text_field_reader import WindowsTextFieldReader, TextFieldReadError


def field(value="", role="searchbox", kind="Edit"):
    identity = (42, 133872, 4, 7, 1, 2)
    element = NS(CurrentFrameworkId="Chrome", CurrentAriaRole=role,
                 CurrentName="Search Wikipedia", CurrentProcessId=38608)
    owner = NS(**vars(element), GetRuntimeId=lambda: identity)
    document = NS(GetText=lambda _: "\ufffc", GetAttributeValue=lambda _: 0,
                  GetEnclosingElement=lambda: owner, GetChildren=lambda: NS(Length=0))
    wrapper = NS(element_info=NS(control_type=kind, element=element, runtime_id=identity),
                 iface_value=NS(CurrentValue=value, CurrentIsReadOnly=0),
                 iface_text=NS(DocumentRange=document))
    return wrapper, owner


@pytest.mark.parametrize("role,kind", [("searchbox", "Edit"), ("textbox", "Edit"), ("combobox", "ComboBox")])
@pytest.mark.parametrize("value", ["", "\u5965\u514b\u5170"])
def test_same_element_object_range_uses_real_value_without_selection(role, kind, value):
    wrapper, _ = field(value, role, kind)
    reader = WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    assert reader._read_text(wrapper, kind) == (value, "uia_value", None)


@pytest.mark.parametrize("mismatch", ["role", "process", "runtime", "framework", "children", "text", "readonly"])
def test_object_range_does_not_hide_unrelated_pattern_conflicts(mismatch):
    wrapper, owner = field()
    document = wrapper.iface_text.DocumentRange
    if mismatch == "role":
        owner.CurrentAriaRole = "button"
    elif mismatch == "process":
        owner.CurrentProcessId += 1
    elif mismatch == "runtime":
        owner.GetRuntimeId = lambda: (999,)
    elif mismatch == "framework":
        owner.CurrentFrameworkId = "Other"
    elif mismatch == "children":
        document.GetChildren = lambda: NS(Length=1)
    elif mismatch == "text":
        document.GetText = lambda _: "different actual content"
    else:
        wrapper.iface_value.CurrentIsReadOnly = 1
    reader = WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    with pytest.raises(TextFieldReadError):
        reader._read_text(wrapper, "Edit")
