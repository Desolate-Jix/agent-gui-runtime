"""首次 Chromium 内容树延迟的只读就绪采样；不运行浏览器或模型。"""
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_form_control_reader as reader
from test_windows_form_control_reader import IDENTITY, Node, Walker, rect


def root(*children, chromium=True):
    value = Node("root", "Window", (0, 1), children=children)
    value.CurrentFrameworkId = "Win32"
    value.CurrentClassName = "Chrome_WidgetWin_1" if chromium else "NativeFixture"
    return value


def document(*children):
    return Node("document", "Document", (0, 2), children=children)


@pytest.fixture
def scenario(monkeypatch):
    def build(roots, *, executable="C:\\msedge.exe", drift=None):
        clock = NS(now=0.0, waits=[], reads=0, owner_calls=0)

        def wait(seconds):
            clock.waits.append(seconds)
            clock.now += seconds

        def uia():
            index = min(clock.reads, len(roots) - 1)
            clock.reads += 1
            return NS(window=lambda **kw: NS(wrapper_object=lambda: roots[index])), Walker(), lambda n: n

        def bound():
            return NS(handle=10, process_id=20,
                      rect=rect(101 if drift == "geometry" and clock.now > 0 else 100))

        def identity(_):
            return {**IDENTITY, "executable_path": executable,
                    "process_create_time": 124.0 if drift == "process" and clock.now > 0 else 123.0}

        def call(fn):
            clock.owner_calls += 1
            return fn()

        monkeypatch.setattr(reader, "_readiness_clock", lambda: clock.now, raising=False)
        monkeypatch.setattr(reader, "_readiness_wait", wait, raising=False)
        monkeypatch.setattr(reader, "_uia_factory", uia)
        monkeypatch.setattr(reader, "_finite_children", lambda node: node.nodes)
        monkeypatch.setattr(reader, "WindowsNativeIdentityReader", lambda **kw: NS(read_identity=identity))
        monkeypatch.setattr(reader, "_same_element", lambda left, right: left is right)
        coordinator = NS(_owner=NS(call=call), _windows=lambda: NS(get_bound_window=bound))
        return coordinator, clock
    return build


def read(coordinator):
    return reader.read_form_control(coordinator, {"handle": 10, "process_id": 20}, "Show Source", "checkbox")


def test_empty_chromium_content_becomes_ready_without_replaying_input(scenario):
    checkbox = Node("Show Source")
    checkbox.iface_toggle = NS(CurrentToggleState=0)
    co, clock = scenario([root(), root(document(checkbox))])
    result = read(co)
    ready = result["diagnostics"]["readiness"]
    assert result["checked"] is False
    assert clock.owner_calls == 1 and clock.reads == 2
    assert clock.waits == [.1]
    assert ready["termination"] == "ready"
    assert ready["elapsed_ms"] == 100.0
    assert [s["document_count"] for s in ready["samples"]] == [0, 1]
    assert [s["match_count"] for s in ready["samples"]] == [0, 1]


def test_empty_chromium_content_budget_exhaustion_is_explicit(scenario):
    co, clock = scenario([root()])
    with pytest.raises(reader.FormControlReadError, match="form_control_not_ready") as error:
        read(co)
    assert .0 < clock.now <= 1.500001
    assert all(0 < seconds <= .100001 for seconds in clock.waits)
    assert 1 < clock.reads <= 16
    assert error.value.diagnostics["readiness"]["termination"] == "budget_exhausted"
    assert len(error.value.diagnostics["readiness"]["samples"]) == clock.reads


@pytest.mark.parametrize("roots, executable", [
    ([root(document())], "C:\\msedge.exe"),
    ([root()], "C:\\fixture.exe"),
    ([root(chromium=False)], "C:\\msedge.exe"),
])
def test_stable_document_missing_or_non_chromium_never_waits(scenario, roots, executable):
    co, clock = scenario(roots, executable=executable)
    with pytest.raises(reader.FormControlReadError, match="form_control_not_found"):
        read(co)
    assert clock.reads == 1 and clock.waits == []


def test_content_appears_but_target_is_missing_stops_immediately(scenario):
    co, clock = scenario([root(), root(document())])
    with pytest.raises(reader.FormControlReadError, match="form_control_not_found") as error:
        read(co)
    assert clock.reads == 2 and clock.waits == [.1]
    assert error.value.diagnostics["readiness"]["termination"] == "target_missing"


@pytest.mark.parametrize("drift", ["geometry", "process"])
def test_native_identity_is_rechecked_before_each_new_sample(scenario, drift):
    co, clock = scenario([root(), root(document(Node("Show Source")))], drift=drift)
    with pytest.raises(reader.FormControlReadError, match="form_control_window_changed") as error:
        read(co)
    assert clock.reads == 1 and clock.waits == [.1]
    assert error.value.diagnostics["readiness"]["termination"] == "identity_changed"


def test_root_provider_identity_drift_cannot_be_treated_as_readiness(scenario):
    changed = root(document(Node("Show Source")))
    changed.element_info.runtime_id = [0, 99]
    co, clock = scenario([root(), changed])
    with pytest.raises(reader.FormControlReadError, match="form_control_identity_changed"):
        read(co)
    assert clock.reads == 2 and clock.waits == [.1]


@pytest.mark.parametrize("same_rid", [False, True])
def test_new_content_conflicts_never_get_another_readiness_retry(scenario, same_rid):
    one = Node("Show Source")
    two = Node("Show Source", rid=(1, 2) if same_rid else (1, 3))
    co, clock = scenario([root(), root(document(one, two))])
    expected = "form_control_tree_runtime_id_conflict" if same_rid else "form_control_ambiguous"
    with pytest.raises(reader.FormControlReadError, match=expected) as error:
        read(co)
    assert clock.reads == 2 and clock.waits == [.1]
    assert len(error.value.diagnostics["readiness"]["samples"]) == 2


def test_expected_existing_field_does_not_enter_cold_start_wait(scenario):
    co, clock = scenario([root()])
    with pytest.raises(reader.FormControlReadError, match="form_control_not_found"):
        reader.read_form_control(co, {"handle": 10, "process_id": 20}, "Show Source", "checkbox",
                                 expected_runtime_id=[1, 2])
    assert clock.reads == 1 and clock.waits == []


def test_initial_scan_over_budget_still_gets_content_readiness_observation(scenario, monkeypatch):
    checkbox = Node("Show Source")
    checkbox.iface_toggle = NS(CurrentToggleState=0)
    co, clock = scenario([root(), root(document(checkbox))])
    scan = reader._scan_controls

    def slow_initial(*args):
        if clock.reads == 1:
            clock.now += 1.8
        return scan(*args)

    monkeypatch.setattr(reader, "_scan_controls", slow_initial)
    result = read(co)
    ready = result["diagnostics"]["readiness"]
    assert result["checked"] is False and clock.reads == 2
    assert clock.waits == [.1]
    assert ready["initial_scan_ms"] == 1800.0
    assert ready["elapsed_ms"] == 1900.0
    assert ready["budget_elapsed_ms"] == 100.0


def test_readiness_budget_does_not_claim_to_preempt_synchronous_com(scenario, monkeypatch):
    co, clock = scenario([root()])
    scan = reader._scan_controls

    def slow_scan(*args):
        clock.now += 1.8 if clock.reads == 1 else 2.0
        return scan(*args)

    monkeypatch.setattr(reader, "_scan_controls", slow_scan)
    with pytest.raises(reader.FormControlReadError, match="form_control_not_ready") as error:
        read(co)
    ready = error.value.diagnostics["readiness"]
    assert clock.reads == 2 and clock.waits == [.1]
    assert ready["initial_scan_ms"] == 1800.0
    assert ready["elapsed_ms"] == 3900.0
    assert ready["budget_elapsed_ms"] == 2100.0
    assert ready["termination"] == "budget_exhausted"


def test_readiness_sample_count_stays_bounded_even_with_nonadvancing_clock(scenario, monkeypatch):
    co, clock = scenario([root()])
    monkeypatch.setattr(reader, "_readiness_wait", lambda seconds: clock.waits.append(seconds))
    with pytest.raises(reader.FormControlReadError, match="form_control_not_ready") as error:
        read(co)
    assert clock.reads == 16 and len(clock.waits) == 15
    assert len(error.value.diagnostics["readiness"]["samples"]) == 16
