"""同字段聚焦后一像素边缘变化的现场回归；只用隔离 UIA 与原生身份边界。"""
from hashlib import sha256
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_text_field_reader as module
from app.core import local_keyboard_target as keyboard


# 原现场 root02 的失败身份与几何；字段内容使用全新合成值。
RID = (42, 3082802, 4, 8, 8, 4)
HWND, PID, BIRTH = 13175872, 62660, 1791459681.5274239
ORIGINAL = (971, 96, 516, 24)
FOCUSED = (971, 96, 515, 24)
POINT = (1045, 98)


class NoPattern(Exception):
    pass


def field(box=FOCUSED, *, value="", kind="ComboBox", rid=RID, pid=PID, focus=True, root=HWND):
    x, y, w, h = box
    element = NS(CurrentFrameworkId="Chrome", CurrentAriaRole="combobox" if kind == "ComboBox" else "textbox",
        CurrentName="Synthetic field", CurrentProcessId=pid, CurrentIsPassword=False,
        CurrentHasKeyboardFocus=focus)
    enclosing = NS(**vars(element), GetRuntimeId=lambda: rid)
    text_range = NS(GetAttributeValue=lambda _: False, GetText=lambda _: "\ufffc",
        GetEnclosingElement=lambda: enclosing, GetChildren=lambda: NS(Length=0))
    root_wrapper = NS(element_info=NS(handle=root, process_id=pid))
    return NS(element_info=NS(handle=0, runtime_id=list(rid), process_id=pid, control_type=kind,
        rectangle=NS(left=x, top=y, right=x+w, bottom=y+h), element=element),
        iface_value=NS(CurrentIsReadOnly=False, CurrentValue=value), iface_text=NS(DocumentRange=text_range),
        is_visible=lambda: True, is_enabled=lambda: True, parent=lambda: root_wrapper)


def scene(monkeypatch, wrappers):
    wrappers = list(wrappers)
    focused, hits = [], []
    def next_field():
        index = len(focused)
        focused.append(index)
        return wrappers[min(index, len(wrappers)-1)]
    def hit(x, y):
        hits.append((x, y))
        return wrappers[0]
    bound = NS(handle=HWND, process_id=PID, rect=NS(left=0, top=0, right=2560, bottom=1400))
    fact = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": HWND, "process_id": PID,
        "process_create_time": BIRTH, "executable_path": "C:/fixture.exe"}
    manager = NS(get_bound_window=lambda: bound)
    monkeypatch.setattr(module, "_focused_field", next_field)
    monkeypatch.setattr(module, "_no_pattern_exception", lambda: NoPattern)
    monkeypatch.setattr(module, "_native_root_handle", lambda handle: handle if handle in (HWND, HWND+1) else None)
    monkeypatch.setattr(module, "_native_window_process_id", lambda handle: PID if handle == HWND else PID+1)
    monkeypatch.setattr(module, "_desktop_factory", lambda **kw: NS(from_point=hit))
    identity_reader = NS(read_identity=lambda _: dict(fact))
    reader = module.WindowsTextFieldReader(window_manager=manager, native_identity_reader=identity_reader,
        clock_ns=lambda: 10, read_id_factory=lambda: "synthetic-read")
    kwargs = dict(target_field_id="field", capture_id="synthetic-current-capture", target_window_handle=HWND,
        target_process_id=PID, process_create_time=BIRTH, window_rect=(0, 0, 2560, 1400), target_bbox=ORIGINAL,
        click_point=POINT, expected_runtime_id=RID, expected_control_type="ComboBox", require_keyboard_focus=True)
    return reader, kwargs, focused, hits, manager, fact, bound


def test_real_receipt_same_focused_field_one_pixel_right_edge_shrink(monkeypatch):
    reader, kwargs, focused, hits, *_ = scene(monkeypatch, [field(), field()])
    snapshot = reader.read_field(**kwargs)
    assert snapshot.identity.runtime_id == RID and snapshot.identity.control_bbox == FOCUSED
    assert snapshot.identity.window_handle == HWND and snapshot.identity.process_id == PID
    assert snapshot.value == "" and snapshot.source == "uia_value"
    assert focused == [0, 1] and hits == []


def from_edges(left=971, top=96, right=1487, bottom=120):
    return left, top, right-left, bottom-top


@pytest.mark.parametrize("box", [from_edges(**{edge: base+delta})
    for edge, base in (("left", 971), ("top", 96), ("right", 1487), ("bottom", 120)) for delta in (-1, 1)]
    + [from_edges(970, 95, 1488, 121), from_edges(972, 97, 1486, 119)])
@pytest.mark.parametrize("kind", ["Edit", "ComboBox"])
def test_each_physical_edge_at_most_one_pixel_can_be_read_when_bound_and_focused(monkeypatch, box, kind):
    reader, kwargs, *_ = scene(monkeypatch, [field(box, kind=kind), field(box, kind=kind)])
    kwargs["expected_control_type"] = kind
    snapshot = reader.read_field(**kwargs)
    assert snapshot.identity.control_bbox == box


@pytest.mark.parametrize("box", [from_edges(**{edge: base+delta})
    for edge, base in (("left", 971), ("top", 96), ("right", 1487), ("bottom", 120)) for delta in (-2, 2)]
    + [(972, 96, 517, 24)])
def test_more_than_one_pixel_on_any_edge_still_rejects(monkeypatch, box):
    reader, kwargs, focused, *_ = scene(monkeypatch, [field(box)])
    with pytest.raises(module.TextFieldReadError, match="text_field_expected_identity_changed") as failure:
        reader.read_field(**kwargs)
    assert failure.value.diagnostic["focused_field_identity"]["failure_branch"] == "geometry"
    assert focused == [0]


@pytest.mark.parametrize("fault", ["runtime", "type", "process", "window", "birth", "window_rect", "focus", "point"])
def test_one_pixel_geometry_never_relaxes_other_field_checks(monkeypatch, fault):
    wrapper = field()
    if fault == "runtime": wrapper.element_info.runtime_id = [42, 99]
    elif fault == "type": wrapper.element_info.control_type = "Edit"
    elif fault == "process": wrapper.element_info.process_id = PID+1
    elif fault == "window": wrapper.parent = lambda: NS(element_info=NS(handle=HWND+1, process_id=PID))
    elif fault == "focus": wrapper.element_info.element.CurrentHasKeyboardFocus = False
    reader, kwargs, focused, hits, manager, fact, bound = scene(monkeypatch, [wrapper])
    if fault == "birth": fact["process_create_time"] += 1
    elif fault == "window_rect": bound.rect.left += 1
    elif fault == "point": kwargs["click_point"] = (1486, 98)
    with pytest.raises(module.TextFieldReadError):
        reader.read_field(**kwargs)
    assert hits == [] and len(focused) <= 1


@pytest.mark.parametrize("fault", ["geometry", "runtime", "value", "focus"])
def test_current_two_reads_still_require_exact_stability(monkeypatch, fault):
    second = field()
    if fault == "geometry": second = field(ORIGINAL)
    elif fault == "runtime": second.element_info.runtime_id = [42, 99]
    elif fault == "value": second.iface_value.CurrentValue = "changed"
    else: second.element_info.element.CurrentHasKeyboardFocus = False
    reader, kwargs, focused, hits, *_ = scene(monkeypatch, [field(), second])
    with pytest.raises(module.TextFieldReadError):
        reader.read_field(**kwargs)
    assert focused == [0, 1] and hits == []


def test_bound_point_hit_without_focus_requirement_stays_exact(monkeypatch):
    reader, kwargs, focused, hits, *_ = scene(monkeypatch, [field()])
    kwargs["require_keyboard_focus"] = False
    with pytest.raises(module.TextFieldReadError, match="text_field_expected_identity_changed"):
        reader.read_field(**kwargs)
    assert focused == [] and hits == [POINT]


def test_preclick_direct_hit_proof_stays_exact(monkeypatch):
    reader, kwargs, focused, hits, *_ = scene(monkeypatch, [field()])
    kwargs.pop("require_keyboard_focus")
    with pytest.raises(module.TextFieldReadError, match="text_field_expected_identity_changed"):
        reader.observe_field_hit(**kwargs)
    assert focused == [] and hits == [POINT]


def test_unbound_field_read_and_description_do_not_accept_shrunken_target_box(monkeypatch):
    reader, kwargs, focused, hits, *_ = scene(monkeypatch, [field()])
    kwargs.pop("expected_runtime_id")
    kwargs.pop("expected_control_type")
    with pytest.raises(module.TextFieldReadError, match="text_field_geometry_changed"):
        reader.read_field(**kwargs)
    assert focused == [] and hits == [POINT]


@pytest.mark.parametrize("fault", ["geometry", "runtime", "type"])
def test_description_revalidates_scope_after_resolved_focused_object_changes(monkeypatch, fault):
    reader, kwargs, focused, hits, *_ = scene(monkeypatch, [field()])
    resolve = reader._bound_focused_field
    def changed(*args, **kw):
        wrapper = resolve(*args, **kw)
        if fault == "geometry":
            wrapper.element_info.rectangle.right = 1490
        elif fault == "runtime":
            wrapper.element_info.runtime_id = [42, 99]
        else:
            wrapper.element_info.control_type = "Edit"
        return wrapper
    monkeypatch.setattr(reader, "_bound_focused_field", changed)
    monkeypatch.setattr(reader, "_read_text", lambda *args: pytest.fail("描述校验失败不得读值"))
    reason = "text_field_geometry_changed" if fault == "geometry" else "text_field_expected_identity_changed"
    with pytest.raises(module.TextFieldReadError, match=reason) as failure:
        reader.read_field(**kwargs)
    assert failure.value.diagnostic["phase"] == "describe_target"
    assert focused == [0] and hits == []


@pytest.mark.parametrize("change_again", [False, True])
def test_keyboard_plan_uses_observed_box_and_keeps_exact_identity_before_input(monkeypatch, change_again):
    later = ORIGINAL if change_again else FOCUSED
    reader, kwargs, focused, hits, manager, fact, _ = scene(monkeypatch,
        [field(), field(), field(later), field(later)])
    before = reader.read_field(**kwargs)
    monkeypatch.setattr(keyboard, "WindowsNativeIdentityReader", lambda **kw: NS(read_identity=lambda _: dict(fact)))
    monkeypatch.setattr(keyboard, "require_local_operator_input", lambda manager: True)
    target = keyboard.LocalKeyboardTarget(before, "ComboBox", POINT, "type_text",
        text_sha256=sha256(b"synthetic-query").hexdigest(), clear_existing=True)
    request = {"text": "synthetic-query", "x": POINT[0], "y": POINT[1], "clear_existing": True,
        "click_before_typing": False}
    with keyboard.local_keyboard_target_scope(target):
        assert keyboard.claim_keyboard_target("type_text", request) is target
        if change_again:
            with pytest.raises(ValueError, match="internal keyboard field changed"):
                target.verify(manager)
        else:
            target.verify(manager)
    assert target.snapshot.identity.control_bbox == FOCUSED and target.point == POINT
    assert focused == [0, 1, 2, 3] and hits == []
