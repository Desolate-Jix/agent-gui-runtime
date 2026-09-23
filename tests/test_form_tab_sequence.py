"""连续文本组合的真实编排回归；仅替换桌面读写边界。"""
from types import SimpleNamespace

import pytest

from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
from app.desktop_review import input_sequence as seq
from app.desktop_review.form_fill import FormFillRequest, run_form_fill
from test_input_sequence import Coordinator, snapshots


TARGET = {"handle": 1, "process_id": 2}
FIELDS = [{"kind": "text", "field_goal": name, "label": name, "text": value}
          for name, value in [("First name", "Ada"), ("Last name", "Lovelace"), ("Email", "test@example.invalid")]]


def setup(monkeypatch, *, wrong_label=False):
    co = Coordinator()
    co._owner = SimpleNamespace(call=lambda fn: fn())
    co._windows = lambda: object()
    snapshots(monkeypatch, ["", "Ada"])
    from app.agent import windows_text_field_reader as reader
    def probe(manager, handle, pid, label, previous):
        if wrong_label and previous is not None:
            raise reader.TextFieldReadError("text_group_focus_label_mismatch")
        rid = {"First name": 1, "Last name": 2, "Email": 3}[label]
        return {"runtime_id": [rid], "control_type": "Edit", "bbox": [1, 1, 300, 40],
                "window_handle": 1, "process_id": 2, "process_create_time": 100.0,
                "window_rect": [0, 0, 800, 600]}
    monkeypatch.setattr(reader, "probe_tab_focus_target", probe, raising=False)
    values = iter(["", "Lovelace", "", "test@example.invalid"])
    def read(coordinator, target, capture, field_id, binding, expected_identity):
        ident = TextFieldIdentity(field_id, 1, 2, 100.0, tuple(binding["runtime_id"]),
                                  (0, 0, 800, 600), (1, 1, 300, 40))
        return TextFieldSnapshot(ident, capture["sha256"], "r", 1, "uia_value", next(values), None)
    monkeypatch.setattr(seq, "_read_local_focus", read)
    return co


def test_three_fields_use_one_recognition_and_two_tabs(monkeypatch):
    co = setup(monkeypatch)
    result = run_form_fill(co, TARGET, {"text_navigation": "tab_sequence", "fields": FIELDS})
    assert result["status"] == "completed", result
    assert result["completed_fields"] == [0, 1, 2]
    assert [c["operation"] for c in co.calls] == ["execute_recognition_plan", "type_text",
        "press_key", "type_text", "press_key", "type_text"]
    assert [c["request"]["key"] for c in co.calls if c["operation"] == "press_key"] == ["Tab", "Tab"]
    assert all(c.get("keyboard_target") is not None for c in co.calls[1:])
    assert all(f["check"]["status"] == "matched" for f in result["fields"])


def test_unexpected_tab_label_stops_before_typing_or_later_fields(monkeypatch):
    co = setup(monkeypatch, wrong_label=True)
    result = run_form_fill(co, TARGET, {"text_navigation": "tab_sequence", "fields": FIELDS})
    assert result["status"] == "interrupted" and result["completed_fields"] == [0]
    assert result["interrupted_at"] == 1
    assert result["error"]["code"] == "text_group_focus_label_mismatch"
    assert [c["operation"] for c in co.calls] == ["execute_recognition_plan", "type_text", "press_key"]
    assert result["automatic_retry_allowed"] is False


@pytest.mark.parametrize("fields", [[{k:v for k,v in FIELDS[0].items() if k != "label"}],
    [FIELDS[0], {"kind": "dropdown", "label": "Country", "option": "NZ"}],
    [FIELDS[0], {**FIELDS[1], "label": "First name"}]])
def test_tab_batch_rejects_missing_duplicate_labels_and_nontext(fields):
    with pytest.raises(ValueError):
        FormFillRequest.model_validate({"text_navigation": "tab_sequence", "fields": fields})


@pytest.mark.parametrize("fault,reason", [(None, None), ("label", "text_group_focus_label_mismatch"),
    ("button", "text_group_focus_not_edit"), ("unchanged", "text_group_focus_did_not_advance"),
    ("process", "text_group_window_changed"), ("readonly", "text_field_target_not_writable")])
def test_real_focus_probe_requires_named_writable_new_field(monkeypatch, fault, reason):
    from app.agent import windows_text_field_reader as reader
    from test_windows_text_field_reader import field, NoPattern
    wrapper = field()
    wrapper.element_info.element.CurrentName = " Email " if fault != "label" else "Search"
    wrapper.element_info.element.CurrentHasKeyboardFocus = True
    wrapper.element_info.process_id = 20
    wrapper.element_info.rectangle = SimpleNamespace(left=20, top=30, right=120, bottom=55)
    wrapper.is_visible = lambda: True
    wrapper.is_enabled = lambda: True
    wrapper.top_level_parent = lambda: SimpleNamespace(element_info=SimpleNamespace(handle=10))
    if fault == "button": wrapper.element_info.control_type = "Button"
    if fault == "readonly": wrapper.iface_value.CurrentIsReadOnly = True
    manager = SimpleNamespace(get_bound_window=lambda: SimpleNamespace(handle=10, process_id=20,
        rect=SimpleNamespace(left=0, top=0, right=600, bottom=500)))
    fact = {"contract_version": "windows_native_identity_observation_v1",
        "provider": "windows_native_identity", "status": "observed", "target_window_handle": 10,
        "process_id": 20, "process_create_time": 123.0, "executable_path": "C:\\fixture.exe"}
    monkeypatch.setattr(reader, "WindowsNativeIdentityReader", lambda **kw: SimpleNamespace(read_identity=lambda _: fact))
    monkeypatch.setattr(reader, "_focused_field", lambda: wrapper)
    monkeypatch.setattr(reader, "_no_pattern_exception", lambda: NoPattern)
    previous = TextFieldIdentity("previous", 10, 20, 999.0 if fault == "process" else 123.0,
        (42, 1) if fault == "unchanged" else (42, 0), (0, 0, 600, 500), (20, 30, 100, 25))
    if reason:
        with pytest.raises(reader.TextFieldReadError, match=reason):
            reader.probe_tab_focus_target(manager, 10, 20, "Email", previous)
    else:
        result = reader.probe_tab_focus_target(manager, 10, 20, "Email", previous)
        assert result["runtime_id"] == [42, 1] and result["bbox"] == [20, 30, 100, 25]


def test_internal_tab_binding_cannot_dispatch_enter():
    from app.core.local_keyboard_target import LocalKeyboardTarget
    ident = TextFieldIdentity("field", 1, 2, 100.0, (1,), (0, 0, 800, 600), (1, 1, 300, 40))
    snapshot = TextFieldSnapshot(ident, "capture", "read", 1, "uia_value", "Ada", None)
    bound = LocalKeyboardTarget(snapshot, "Edit", (10, 20), "press_key", key="Tab")
    bound.validate_command("press_key", {"key": "Tab", "x": 10, "y": 20})
    with pytest.raises(ValueError):
        bound.validate_command("press_key", {"key": "Enter", "x": 10, "y": 20})
