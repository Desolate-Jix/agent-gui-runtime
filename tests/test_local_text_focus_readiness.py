"""固定点只读收敛与深层原生根归属的隔离回归；不操作桌面。"""
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_text_field_reader as module


MIXED = object()
NOT_SUPPORTED = object()


class NoPattern(Exception):
    pass


def _private_read(*args):
    raise AssertionError("field text and input must not be accessed")


def _node(kind="Edit", *, bbox=(20, 30, 100, 40), readonly=False, pid=20, hwnd=0, rid=1):
    x, y, w, h = bbox
    element = NS(CurrentProcessId=pid, CurrentIsPassword=False, CurrentFrameworkId="Chrome",
                 CurrentAriaRole="combobox" if kind == "ComboBox" else "textbox", CurrentName="")
    wrapper = NS(element_info=NS(control_type=kind, process_id=pid, handle=hwnd,
        runtime_id=[42, rid], rectangle=NS(left=x, top=y, right=x+w, bottom=y+h), element=element),
        iface_value=NS(CurrentIsReadOnly=readonly),
        iface_text=NS(DocumentRange=NS(GetAttributeValue=lambda _: readonly, GetText=_private_read)),
        is_visible=lambda: True, is_enabled=lambda: True, click_input=_private_read,
        set_focus=_private_read, type_keys=_private_read, set_edit_text=_private_read, parent=lambda: None)
    return wrapper


def _attach_root(wrapper, *, depth=1, root_handle=10, root_pid=20, foreign_at=None):
    root = _node("Window", bbox=(0, 0, 600, 500), hwnd=root_handle, pid=root_pid, rid=1000)
    parent = root
    for index in reversed(range(1, depth)):
        node = _node("Pane", bbox=(0, 0, 600, 500), pid=21 if index == foreign_at else 20, rid=100+index)
        node.parent = lambda parent=parent: parent
        parent = node
    wrapper.parent = lambda: parent
    return root


@pytest.fixture(autouse=True)
def isolated_uia(monkeypatch):
    monkeypatch.setattr(module, "_no_pattern_exception", lambda: NoPattern)
    monkeypatch.setattr(module, "_native_root_handle", lambda hwnd: {10: 10, 11: 11}.get(hwnd))
    def classify(value):
        if value is MIXED:
            return "mixed"
        if value is NOT_SUPPORTED:
            return "not_supported"
        if type(value) in (bool, int) and value in (0, 1):
            return "readonly" if value else "writable"
        return "unknown"
    monkeypatch.setattr(module, "_readonly_attribute_class", classify)


def _scenario(monkeypatch, wrappers, *, on_wait=None, on_hit=None):
    bound = NS(handle=10, process_id=20, rect=NS(left=0, top=0, right=600, bottom=500))
    fact = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
            "status": "observed", "target_window_handle": 10, "process_id": 20,
            "process_create_time": 123.0, "executable_path": "C:/fixture.exe"}
    calls, waits, now = [], [], [0.0]
    def hit(x, y):
        index = len(calls)
        calls.append((x, y))
        if on_hit:
            on_hit(index, now)
        item = wrappers[min(index, len(wrappers)-1)]
        if isinstance(item, Exception):
            raise item
        return item
    def wait(duration):
        waits.append(duration)
        now[0] += duration
        if on_wait:
            on_wait(bound, fact)
    monkeypatch.setattr(module, "WindowsNativeIdentityReader", lambda **kw: NS(read_identity=lambda _: dict(fact)))
    monkeypatch.setattr(module, "_desktop_factory", lambda **kw: NS(from_point=hit))
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(module.time, "sleep", wait)
    manager = NS(get_bound_window=lambda: bound)
    return manager, calls, waits


def _probe(manager, **kwargs):
    return module.probe_local_focus_target(manager, 10, 20, (40, 45), **kwargs)


@pytest.mark.parametrize("depth", [17, 31])
def test_virtual_field_resolves_nearest_native_root_within_32_nodes(depth):
    field = _node("ComboBox")
    root = _attach_root(field, depth=depth)
    owner = _node("Window", hwnd=11, pid=99, rid=2000)
    root.parent = lambda: owner
    assert module._top_window_handle(field) == 10


@pytest.mark.parametrize("fault", ["depth32", "foreign_pid", "cycle", "invalid_native"])
def test_extended_root_budget_keeps_strict_ancestry(fault):
    field = _node()
    _attach_root(field, depth=32 if fault == "depth32" else 17,
                 foreign_at=16 if fault == "foreign_pid" else None)
    if fault == "cycle":
        parent = field.parent()
        parent.parent = lambda: field
    elif fault == "invalid_native":
        field.element_info.handle = 777
    assert module._top_window_handle(field) is None


@pytest.mark.parametrize("kind,readonly", [("Document", MIXED), ("Group", NOT_SUPPORTED)])
def test_coarse_mixed_container_resamples_same_point_before_exact_writable_field(monkeypatch, kind, readonly):
    coarse = _node(kind, bbox=(0, 0, 600, 500), readonly=readonly)
    precise = _node("ComboBox", rid=7)
    _attach_root(coarse)
    _attach_root(precise)
    manager, calls, waits = _scenario(monkeypatch, [coarse, precise])
    result = _probe(manager)
    assert result["runtime_id"] == [42, 7] and result["control_type"] == "ComboBox"
    assert result["bbox"] == [20, 30, 100, 40]
    assert calls == [(40, 45), (40, 45)] and waits == [.025]


def test_coarse_raw_pane_mixed_document_can_only_converge_through_new_point_hit(monkeypatch):
    raw = _node("Pane", bbox=(0, 0, 600, 500))
    document = _node("Document", bbox=(0, 0, 600, 500), readonly=MIXED, rid=2)
    _attach_root(document)
    raw.parent = lambda: document
    precise = _node("Edit", rid=7)
    _attach_root(precise, depth=17)
    manager, calls, waits = _scenario(monkeypatch, [raw, precise])
    assert _probe(manager)["runtime_id"] == [42, 7]
    assert calls == [(40, 45)] * 2 and len(waits) == 1


@pytest.mark.parametrize("kind", ["Document", "Group"])
@pytest.mark.parametrize("readonly,bbox", [(True, (0, 0, 600, 500)), (MIXED, (20, 30, 100, 40)),
                                         (NOT_SUPPORTED, (20, 30, 100, 40)), (None, (0, 0, 600, 500))])
def test_readonly_or_small_container_is_not_treated_as_transient(monkeypatch, kind, readonly, bbox):
    wrapper = _node(kind, readonly=readonly, bbox=bbox)
    _attach_root(wrapper)
    precise = _node()
    _attach_root(precise)
    manager, calls, waits = _scenario(monkeypatch, [wrapper, precise])
    with pytest.raises(module.TextFieldReadError) as error:
        _probe(manager)
    assert error.value.reason_code == "text_field_target_not_writable"
    assert len(calls) == 1 and waits == []


@pytest.mark.parametrize("kind", ["Edit", "ComboBox"])
@pytest.mark.parametrize("readonly", [True, None, MIXED, NOT_SUPPORTED])
def test_precise_field_unknown_or_readonly_is_never_retried(monkeypatch, kind, readonly):
    wrapper = _node(kind, readonly=readonly)
    _attach_root(wrapper)
    precise = _node()
    _attach_root(precise)
    manager, calls, waits = _scenario(monkeypatch, [wrapper, precise])
    with pytest.raises(module.TextFieldReadError):
        _probe(manager)
    assert len(calls) == 1 and waits == []


@pytest.mark.parametrize("fault", ["foreign_pid", "wrong_root", "cycle"])
def test_coarse_wrong_ownership_is_not_retried(monkeypatch, fault):
    coarse = _node("Document", bbox=(0, 0, 600, 500), readonly=MIXED, pid=21 if fault == "foreign_pid" else 20)
    _attach_root(coarse, root_handle=11 if fault == "wrong_root" else 10)
    if fault == "cycle":
        coarse.parent = lambda: coarse
    manager, calls, waits = _scenario(monkeypatch, [coarse])
    with pytest.raises(module.TextFieldReadError) as error:
        _probe(manager)
    assert error.value.reason_code == "text_field_window_or_process_changed"
    assert len(calls) == 1 and waits == []


@pytest.mark.parametrize("change,reason", [("birth", "text_field_process_identity_changed"),
                                         ("rect", "text_field_window_binding_changed")])
def test_retry_rechecks_original_birth_and_rectangle_before_next_hit(monkeypatch, change, reason):
    coarse = _node("Document", bbox=(0, 0, 600, 500), readonly=MIXED)
    _attach_root(coarse)
    precise = _node()
    _attach_root(precise)
    def changed(bound, fact):
        if change == "birth":
            fact["process_create_time"] = 456.0
        else:
            bound.rect.left = 1
    manager, calls, waits = _scenario(monkeypatch, [coarse, precise], on_wait=changed)
    with pytest.raises(module.TextFieldReadError) as error:
        _probe(manager)
    assert error.value.reason_code == reason and len(calls) == 1 and len(waits) == 1


def test_persistent_mixed_container_exhausts_bounded_reads_and_retains_original_failure(monkeypatch):
    coarse = _node("Document", bbox=(0, 0, 600, 500), readonly=MIXED)
    _attach_root(coarse)
    manager, calls, waits = _scenario(monkeypatch, [coarse])
    with pytest.raises(module.TextFieldReadError) as error:
        _probe(manager)
    assert error.value.reason_code == "text_field_target_not_writable"
    diagnostic = error.value.to_reference()["diagnostic"]
    assert diagnostic["attribute_class"] == "mixed" and diagnostic["attempt"] == 11
    assert len(calls) == 11 and len(waits) == 10 and sum(waits) <= .25


def test_coarse_io_overrun_retains_failure_without_another_hit(monkeypatch):
    coarse = _node("Document", bbox=(0, 0, 600, 500), readonly=MIXED)
    _attach_root(coarse)
    manager, calls, waits = _scenario(monkeypatch, [coarse], on_hit=lambda _, now: now.__setitem__(0, .3))
    with pytest.raises(module.TextFieldReadError) as error:
        _probe(manager)
    assert error.value.reason_code == "text_field_target_not_writable"
    assert error.value.to_reference()["diagnostic"]["attempt"] == 1
    assert len(calls) == 1 and waits == []


def test_new_provider_failure_during_retry_is_surfaced_without_more_reads(monkeypatch):
    coarse = _node("Document", bbox=(0, 0, 600, 500), readonly=MIXED)
    _attach_root(coarse)
    manager, calls, waits = _scenario(monkeypatch, [coarse, RuntimeError("private provider text")])
    with pytest.raises(module.TextFieldReadError) as error:
        _probe(manager)
    assert error.value.reason_code == "text_field_target_unavailable"
    assert "private" not in str(error.value.to_reference())
    assert len(calls) == 2 and len(waits) == 1


def test_new_precise_hit_label_failure_never_retries_or_uses_coarse_ancestor(monkeypatch):
    coarse = _node("Document", bbox=(0, 0, 600, 500), readonly=MIXED)
    precise = _node("Edit", rid=7)
    _attach_root(coarse)
    _attach_root(precise)
    manager, calls, waits = _scenario(monkeypatch, [coarse, precise])
    labels = []
    def reject(wrapper, *args):
        labels.append(wrapper)
        raise module.TextFieldReadError("text_field_label_not_found")
    monkeypatch.setattr(module, "_verify_named_focus_hit", reject)
    with pytest.raises(module.TextFieldReadError) as error:
        _probe(manager, expected_label="Expected")
    assert error.value.reason_code == "text_field_label_not_found" and labels == [precise]
    assert len(calls) == 2 and len(waits) == 1


def test_initial_precise_writable_hit_keeps_immediate_original_contract(monkeypatch):
    precise = _node("Edit", rid=7)
    _attach_root(precise)
    manager, calls, waits = _scenario(monkeypatch, [precise])
    result = _probe(manager)
    assert result["runtime_id"] == [42, 7] and result["process_create_time"] == 123.0
    assert calls == [(40, 45)] and waits == []


def test_wait_scheduler_overrun_does_not_start_another_point_read(monkeypatch):
    coarse = _node("Document", bbox=(0, 0, 600, 500), readonly=MIXED)
    precise = _node()
    _attach_root(coarse)
    _attach_root(precise)
    manager, calls, waits = _scenario(monkeypatch, [coarse, precise])
    original_clock = module.time.monotonic
    monkeypatch.setattr(module.time, "monotonic", lambda: original_clock() + (.3 if waits else 0))
    with pytest.raises(module.TextFieldReadError) as error:
        _probe(manager)
    assert error.value.reason_code == "text_field_target_not_writable"
    assert error.value.to_reference()["diagnostic"]["attribute_class"] == "mixed"
    assert error.value.to_reference()["diagnostic"]["attempt"] == 1
    assert len(calls) == 1 and len(waits) == 1


@pytest.mark.parametrize("kind", ["Document", "Group"])
def test_readiness_cannot_promote_a_coarse_writable_ancestor_to_new_field(monkeypatch, kind):
    coarse = _node("Document", bbox=(0, 0, 600, 500), readonly=MIXED)
    ancestor = _node(kind, bbox=(0, 0, 600, 500), readonly=False, rid=99)
    _attach_root(coarse)
    _attach_root(ancestor)
    manager, calls, waits = _scenario(monkeypatch, [coarse, ancestor])
    with pytest.raises(module.TextFieldReadError) as error:
        _probe(manager)
    assert error.value.reason_code == "text_field_target_not_writable"
    assert error.value.to_reference()["diagnostic"]["attribute_class"] == "mixed"
    assert error.value.to_reference()["diagnostic"]["attempt"] == 2
    assert len(calls) == 2 and len(waits) == 1
