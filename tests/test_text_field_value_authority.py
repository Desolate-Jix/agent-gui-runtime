"""Value 权威与受限旁路证据；仅隔离 UIA/native 边界，不读取桌面。"""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from types import SimpleNamespace as NS

import pytest

from app.agent import text_field_evidence as evidence
from app.agent import windows_text_field_reader as module
from tests.test_windows_text_field_reader import field, read, fake_com_boundary, NoPattern


def digest(value):
    return sha256(value.encode("utf-8")).hexdigest()


def pattern(value="private contents", text="private range", **changes):
    data = dict(authority="uia_value", pattern_consistency="disagrees",
        value_sha256=digest(value), value_length=len(value), text_sha256=digest(text),
        text_length=len(text), selection_basis="disabled_disagreement")
    return evidence.TextFieldPatternEvidence(**{**data, **changes})


def full_read(monkeypatch, wrappers, *, focused=False):
    for wrapper in wrappers:
        wrapper.element_info.process_id = 20
        wrapper.element_info.rectangle = NS(left=20, top=30, right=120, bottom=55)
        wrapper.is_visible = lambda: True
        wrapper.is_enabled = lambda: True
        wrapper.parent = lambda: NS(element_info=NS(process_id=20, handle=10))
        wrapper.element_info.element.CurrentHasKeyboardFocus = True
    hits = iter(wrappers)
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None,
        desktop_factory=lambda **kwargs: NS(from_point=lambda *args: next(hits)))
    monkeypatch.setattr(reader, "_verify_binding", lambda *args: None)
    if focused:
        monkeypatch.setattr(module, "_focused_field", lambda: next(hits))
    return reader.read_field(target_field_id="field", capture_id="fresh",
        target_window_handle=10, target_process_id=20, process_create_time=123.0,
        window_rect=(0, 0, 600, 500), target_bbox=(20, 30, 100, 25), click_point=(50, 40),
        **({"expected_runtime_id": (42, 1), "expected_control_type": wrappers[0].element_info.control_type,
            "require_keyboard_focus": True} if focused else {}))


@pytest.mark.parametrize("kind", ["Edit", "ComboBox"])
@pytest.mark.parametrize("value,text", [("", "Q"), ("fresh contents", "different range"),
    ("\u4e2d\u6587", "\u8303\u56f4")])
def test_value_authority_is_provider_neutral_and_disables_disagreeing_selection(monkeypatch, kind, value, text):
    wrappers = [field(kind=kind, value=value, text=text) for _ in range(2)]
    for wrapper in wrappers:
        wrapper.element_info.element.CurrentFrameworkId = "Win32"
        wrapper.iface_text.DocumentRange.GetEnclosingElement().CurrentFrameworkId = "Win32"
        wrapper.iface_text.GetSelection = lambda: pytest.fail("分歧不能读取或授权选区")
    snapshot = full_read(monkeypatch, wrappers)
    assert snapshot.value == value and snapshot.source == "uia_value" and snapshot.selection is None
    sidecar = snapshot.pattern_evidence.to_reference()
    assert sidecar["pattern_consistency"] == "disagrees"
    assert sidecar["value"] == {"sha256": digest(value), "length": len(value)}
    assert sidecar["text"] == {"sha256": digest(text), "length": len(text)}
    assert sidecar["selection_basis"] == "disabled_disagreement"


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("after", ["R", "", "value", None])
def test_stable_value_cannot_hide_text_or_consistency_drift(monkeypatch, focused, after):
    monkeypatch.setattr(module, "_selection", lambda _: None)
    second = field(value="value", text=after)
    if after is None:
        class ValueOnly(NS):
            @property
            def iface_text(self):
                raise NoPattern()
        second = ValueOnly(element_info=second.element_info, iface_value=second.iface_value)
    with pytest.raises(module.TextFieldReadError, match="text_field_changed_during_read"):
        full_read(monkeypatch, [field(value="value", text="Q"), second], focused=focused)


@pytest.mark.parametrize("attribute", ["value", "text"])
@pytest.mark.parametrize("readonly", [None, True, object()])
def test_disagreement_requires_both_patterns_explicitly_writable(attribute, readonly):
    wrapper = field(value="value", text="Q")
    if attribute == "value":
        wrapper.iface_value.CurrentIsReadOnly = readonly
    else:
        wrapper.iface_text.DocumentRange.GetAttributeValue = lambda _: readonly
    with pytest.raises(module.TextFieldReadError):
        read(wrapper)


@pytest.mark.parametrize("password", [None, True])
def test_disagreement_requires_explicit_nonpassword(password):
    wrapper = field(value="value", text="Q")
    wrapper.element_info.element.CurrentIsPassword = password
    with pytest.raises(module.TextFieldReadError):
        read(wrapper)


@pytest.mark.parametrize("fault", ["enclosing_identity", "enclosing_process", "unknown_children"])
def test_disagreement_cannot_erase_original_range_identity_or_provider_failure(fault):
    with pytest.raises(module.TextFieldReadError):
        read(field(fault=fault))


@pytest.mark.parametrize("fault", ["value", "text", "owner"])
def test_disagreement_does_not_fallback_after_provider_exception(fault):
    wrapper = field(value="value", text="Q")

    def broken(*args):
        raise RuntimeError("PRIVATE_PROVIDER_MESSAGE")

    if fault == "text":
        wrapper.iface_text.DocumentRange.GetText = broken
    elif fault == "owner":
        wrapper.iface_text.DocumentRange.GetEnclosingElement = broken
    else:
        class Value:
            CurrentIsReadOnly = False
            CurrentValue = property(broken)
        wrapper.iface_value = Value()
    with pytest.raises(module.TextFieldReadError) as caught:
        read(wrapper)
    assert "PRIVATE" not in json.dumps(caught.value.to_reference())


@pytest.mark.parametrize("kind,text", [("Edit", "\ufffc"), ("ComboBox", "Address:")])
def test_matching_noncontent_exception_still_cannot_enable_append(monkeypatch, kind, text):
    wrapper = field(kind=kind, role="textbox" if kind == "Edit" else "combobox", value=text, text=text)
    wrapper.iface_text.GetSelection = lambda: pytest.fail("匹配非内容范围仍不能授权选区")
    snapshot = full_read(monkeypatch, [wrapper, wrapper])
    assert snapshot.selection is None and snapshot.pattern_evidence.pattern_consistency == "matched"
    assert snapshot.pattern_evidence.selection_basis == "non_content_range"


def test_evidence_is_immutable_redacted_and_snapshot_reference_stays_exact_v1():
    item = pattern()
    identity = evidence.TextFieldIdentity("field", 10, 20, 123.0, (42, 1), (0, 0, 600, 500), (20, 30, 100, 25))
    old = evidence.TextFieldSnapshot(identity, "capture", "read", 100, "uia_value", "private contents", None)
    new = replace(old, pattern_evidence=item)
    assert new.to_reference() == old.to_reference()
    assert evidence.validate_text_field_snapshot_reference(new.to_reference()) == old.to_reference()
    assert "private" not in json.dumps(item.to_reference())
    with pytest.raises(FrozenInstanceError):
        item.text_length = 1
    with pytest.raises(ValueError):
        replace(old, pattern_evidence=item.to_reference())
    with pytest.raises(ValueError):
        replace(new, selection=(0, 1))
    with pytest.raises(ValueError):
        replace(new, value="changed")


@pytest.mark.parametrize("changes", [{"authority": "unknown"}, {"value_length": True},
    {"text_length": 32769}, {"text_sha256": "A" * 64}, {"pattern_consistency": "matched"},
    {"selection_basis": "aligned_text"}, {"text_sha256": None}, {"authority": ["uia_value"]}])
def test_pattern_evidence_rejects_unbounded_or_inconsistent_metadata(changes):
    with pytest.raises(ValueError):
        pattern(**changes)
