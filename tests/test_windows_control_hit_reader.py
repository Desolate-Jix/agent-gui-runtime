"""原生按钮命中只产生可核验事实，不能执行动作或冒充 OCR。"""
from types import SimpleNamespace
import json

import pytest

from app.agent.windows_control_hit_reader import NativeControlHitError, WindowsControlHitReader
from tests.test_windows_text_field_reader import _Native, _Wrapper


class _InvokeOnly:
    def Invoke(self):
        pytest.fail("read-only hit must never Invoke")


def _button(kind="Button", name="Search", **kwargs):
    wrapper = _Wrapper(control_type=kind, **kwargs)
    wrapper.element_info.name = name
    wrapper.iface_invoke = _InvokeOnly()
    wrapper.parent = lambda: pytest.fail("control hit must not promote a parent")
    wrapper.click = lambda: pytest.fail("control hit must not click")
    wrapper.set_focus = lambda: pytest.fail("control hit must not focus")
    return wrapper


def _setup(sequence=None):
    sequence = sequence if sequence is not None else [_button(), _button()]
    bound = SimpleNamespace(handle=7, process_id=8,
        rect=SimpleNamespace(left=100, top=200, right=500, bottom=500))
    state = {"hits": [], "native_reads": 0, "native_change": None}
    def from_point(x, y):
        item = sequence[min(len(state["hits"]), len(sequence) - 1)]
        state["hits"].append((x, y))
        if isinstance(item, Exception): raise item
        return item
    def native(handle):
        state["native_reads"] += 1
        fact = _Native().read_identity(handle)
        if state["native_change"]: state["native_change"](fact, state["native_reads"])
        return fact
    reader = WindowsControlHitReader(SimpleNamespace(get_bound_window=lambda: bound),
        native_identity_reader=SimpleNamespace(read_identity=native),
        desktop_factory=lambda **_: SimpleNamespace(from_point=from_point), clock_ns=lambda: 999)
    return reader, state, bound


def _observe(reader, **changes):
    args = dict(window_handle=7, process_id=8, process_create_time=2.0,
        window_rect=(100, 200, 400, 300), capture_id="capture", control_id="search",
        point=(10, 10), expected_runtime_id=(1, 2), expected_control_type="Button",
        expected_bbox=(0, 0, 200, 40))
    args.update(changes)
    return reader.observe_control_hit(**args)


@pytest.mark.parametrize("kind", ["Button", "Hyperlink"])
@pytest.mark.parametrize("name", ["Search", "搜索", "", "Delete", "Pay now"])
def test_two_direct_hits_return_actual_identity_not_authority(kind, name):
    reader, state, _ = _setup([_button(kind, name), _button(kind, name)])
    proof = _observe(reader, expected_control_type=kind)
    assert proof == {"contract_version": "native_control_hit_v1", "provider": "windows_uia.from_point",
        "capture_id": "capture", "control_id": "search", "target": {"window_handle": 7,
            "process_id": 8, "process_create_time": 2.0, "window_rect": [100, 200, 400, 300]},
        "accessible_name": name, "runtime_id": [1, 2], "control_type": kind,
        "bbox": {"x": 0, "y": 0, "w": 200, "h": 40}, "point": {"x": 10, "y": 10},
        "observed_at_ns": 999, "sample_count": 2, "pattern": "Invoke",
        "artifact_is_authorization": False, "action_executed": False}
    assert state["hits"] == [(110, 210), (110, 210)]
    assert state["native_reads"] >= 3
    assert "ocr" not in json.dumps(proof).lower()


@pytest.mark.parametrize("kind", ["Text", "Image", "Group", "Pane", "Edit", "ComboBox", "CheckBox"])
def test_non_button_raw_hit_is_never_promoted(kind):
    reader, state, _ = _setup([_button(kind)])
    with pytest.raises(NativeControlHitError): _observe(reader)
    assert len(state["hits"]) == 1


@pytest.mark.parametrize("change", ["runtime", "runtime_bool", "bbox", "window", "process",
    "disabled", "hidden", "unknown_enabled", "unknown_visible", "missing_name", "non_string_name",
    "missing_pattern", "false_pattern", "missing_element", "native_process_conflict", "native_process_missing"])
def test_incomplete_or_changed_target_rejects_immediately(change):
    wrapper = _button()
    if change == "runtime": wrapper.element_info.runtime_id = (9, 2)
    elif change == "runtime_bool": wrapper.element_info.runtime_id = (True, 2)
    elif change == "bbox": wrapper.element_info.rectangle = SimpleNamespace(left=100, top=200, right=301, bottom=240)
    elif change == "window": wrapper.element_info.handle = 9
    elif change == "process": wrapper.element_info.process_id = 9
    elif change == "disabled": wrapper._enabled = False
    elif change == "hidden": wrapper._visible = False
    elif change == "unknown_enabled": wrapper._enabled = None
    elif change == "unknown_visible": wrapper._visible = None
    elif change == "missing_name": del wrapper.element_info.name
    elif change == "non_string_name": wrapper.element_info.name = 7
    elif change == "missing_pattern": del wrapper.iface_invoke
    elif change == "false_pattern": wrapper.iface_invoke = None
    elif change == "missing_element": wrapper.element_info.element = None
    elif change == "native_process_conflict": wrapper.element_info.element.CurrentProcessId = 9
    elif change == "native_process_missing": del wrapper.element_info.element.CurrentProcessId
    reader, state, _ = _setup([wrapper])
    with pytest.raises(NativeControlHitError): _observe(reader)
    assert len(state["hits"]) == 1


@pytest.mark.parametrize("change", ["name", "runtime", "bbox", "type"])
def test_second_sample_drift_does_not_retry(change):
    first, second = _button(), _button()
    if change == "name": second.element_info.name = "Different"
    elif change == "runtime": second.element_info.runtime_id = (1, 3)
    elif change == "bbox": second.element_info.rectangle = SimpleNamespace(left=101, top=200, right=301, bottom=240)
    else: second.element_info.control_type = "Hyperlink"
    reader, state, _ = _setup([first, second, first])
    with pytest.raises(NativeControlHitError): _observe(reader)
    assert len(state["hits"]) == 2


@pytest.mark.parametrize("key,value", [("window_handle", True), ("process_id", 0),
    ("process_create_time", float("nan")), ("capture_id", ""), ("control_id", ""),
    ("expected_control_type", "Edit"), ("expected_runtime_id", (True, 2)),
    ("point", (200, 10)), ("expected_bbox", (0, 0, 500, 40)), ("point", [10, 10])])
def test_invalid_request_is_rejected_before_native_access(key, value):
    reader, state, _ = _setup()
    with pytest.raises(NativeControlHitError): _observe(reader, **{key: value})
    assert state["hits"] == [] and state["native_reads"] == 0


@pytest.mark.parametrize("when", [1, 2, 3])
def test_process_creation_drift_at_each_identity_boundary_rejects(when):
    reader, state, _ = _setup()
    def drift(fact, count):
        if count == when: fact["process_create_time"] = 3.0
    state["native_change"] = drift
    with pytest.raises(NativeControlHitError): _observe(reader)


def test_native_error_is_structured_and_does_not_leak_provider_text():
    reader, _, _ = _setup([RuntimeError("PRIVATE_PROVIDER_MESSAGE")])
    with pytest.raises(NativeControlHitError) as caught: _observe(reader)
    assert "PRIVATE_PROVIDER_MESSAGE" not in str(caught.value)
    assert caught.value.to_reference() == {"reason_code": caught.value.reason_code}


def test_clock_must_be_positive_integer():
    reader, _, _ = _setup()
    reader._clock_ns = lambda: False
    with pytest.raises(NativeControlHitError): _observe(reader)


@pytest.mark.parametrize("what", ["window", "process", "rect"])
def test_bound_window_drift_after_first_hit_stops_before_second(what):
    reader, state, bound = _setup()
    def change(_fact, count):
        if count == 1:
            if what == "window": bound.handle = 9
            elif what == "process": bound.process_id = 9
            else: bound.rect.right += 1
    state["native_change"] = change
    with pytest.raises(NativeControlHitError): _observe(reader)
    assert len(state["hits"]) <= 1


def test_default_native_identity_dependency_uses_the_same_window_manager(monkeypatch):
    from app.agent import windows_control_hit_reader as module

    original, state, _ = _setup()
    manager = original._window_manager
    created = []
    def factory(*, window_manager):
        created.append(window_manager)
        return original._native_identity_reader
    monkeypatch.setattr(module, "WindowsNativeIdentityReader", factory)
    reader = WindowsControlHitReader(manager, desktop_factory=original._desktop_factory,
        clock_ns=lambda: 999)
    assert _observe(reader)["sample_count"] == 2
    assert created == [manager] and len(state["hits"]) == 2


def test_invoke_attribute_failure_is_not_invoked_or_exposed():
    class UnavailableInvoke(type(_button())):
        @property
        def iface_invoke(self):
            raise RuntimeError("PRIVATE_INVOKE_PROVIDER_MESSAGE")
    wrapper = UnavailableInvoke(control_type="Button")
    wrapper.element_info.name = "Search"
    reader, state, _ = _setup([wrapper])
    with pytest.raises(NativeControlHitError) as caught: _observe(reader)
    assert "PRIVATE_INVOKE_PROVIDER_MESSAGE" not in str(caught.value)
    assert len(state["hits"]) == 1
