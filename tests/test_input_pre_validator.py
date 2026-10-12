"""输入前回调走真实 click_point；仅替换操作系统边界，不派发桌面输入。"""
import inspect

import pytest

import app.core.input_controller as input_module
from app.agent.popup_click_guard import PopupClickGuard, PopupTargetSnapshot
from app.core.input_controller import InputController
from tests.test_mouse_click_sequence import _prepared


def prepared(monkeypatch, *, popup=False):
    controller, bound, events = _prepared(monkeypatch)
    monkeypatch.setattr(input_module.window_manager, "get_owned_foreground_popup_handle", lambda bound: None)
    monkeypatch.setattr(controller, "_double_click_time_ms", lambda: 500)
    options = {}
    if popup:
        expected = PopupTargetSnapshot(parent_handle=1, popup_handle=7, process_id=11,
            process_create_time=1.0, executable_path="C:/Example/browser.exe", thread_id=2,
            parent_rect=(0, 0, 800, 600), popup_rect=(0, 0, 800, 600),
            combo_name="Search", item_name="Result", combo_runtime_id=(1,), item_runtime_id=(2,),
            item_bbox=(0, 0, 20, 40), click_point=(10, 20))
        monkeypatch.setattr(input_module.win32gui, "GetForegroundWindow", lambda: 1)
        options["popup_guard"] = PopupClickGuard(expected, lambda: expected)
    return controller, bound, events, options


def test_real_signature_accepts_pre_input_validator():
    inspect.signature(InputController.click_point).bind(None, 10, 20, pre_input_validator=lambda: None)


@pytest.mark.parametrize("popup", [False, True])
@pytest.mark.parametrize("click_count", [1, 2])
def test_validator_runs_after_settle_and_immediately_before_each_mouse_down(monkeypatch, popup, click_count):
    controller, _, events, options = prepared(monkeypatch, popup=popup)

    def validate():
        events.append(("validate",))

    result = controller.click_point(10, 20, click_count=click_count, settle_ms=100, hold_ms=0,
        pre_input_validator=validate, **options)

    assert result["clicked"] is True
    assert [event[0] for event in events].count("validate") == click_count
    for index, event in enumerate(events):
        if event[0] == "down":
            assert events[index - 1] == ("validate",)
    assert events.index(("sleep", .1)) < events.index(("validate",))


@pytest.mark.parametrize("refused", [False, {}, "allowed"])
def test_explicit_validator_refusal_never_sends_mouse_down_or_release(monkeypatch, refused):
    controller, _, events, _ = prepared(monkeypatch)
    with pytest.raises(ValueError, match="pre_input_validator_rejected") as caught:
        controller.click_point(10, 20, pre_input_validator=lambda: refused)
    assert not any(event[0] in {"down", "up"} for event in events)
    assert caught.value.click_sequence["input_attempted"] is False


def test_validator_exception_is_preserved_without_input(monkeypatch):
    controller, _, events, _ = prepared(monkeypatch)
    failure = RuntimeError("capture expired")

    def validate():
        raise failure

    with pytest.raises(RuntimeError, match="capture expired") as caught:
        controller.click_point(10, 20, pre_input_validator=validate)
    assert caught.value is failure
    assert not any(event[0] in {"down", "up"} for event in events)


def test_second_validator_refusal_preserves_first_click_and_blocks_second_down(monkeypatch):
    controller, _, events, _ = prepared(monkeypatch)
    calls = []

    def validate():
        calls.append(len(calls) + 1)
        return len(calls) == 1

    with pytest.raises(ValueError, match="pre_input_validator_rejected") as caught:
        controller.click_point(10, 20, click_count=2, settle_ms=0, hold_ms=0,
            pre_input_validator=validate)
    assert calls == [1, 2]
    assert [event[0] for event in events].count("down") == 1
    assert [event[0] for event in events].count("up") == 1
    assert caught.value.completed_click_count == 1
    assert caught.value.click_sequence["completed_clicks"] == 1


def test_window_drift_during_validator_still_blocks_input(monkeypatch):
    controller, _, events, _ = prepared(monkeypatch)

    def validate():
        monkeypatch.setattr(input_module.window_manager, "get_bound_window", lambda: None)

    with pytest.raises(RuntimeError, match="Bound window changed"):
        controller.click_point(10, 20, pre_input_validator=validate)
    assert not any(event[0] in {"down", "up"} for event in events)


def test_noncallable_validator_is_rejected_before_windows_input(monkeypatch):
    controller = InputController()
    monkeypatch.setattr(controller, "_ensure_windows_input",
        lambda: pytest.fail("invalid validator reached Windows input"))
    with pytest.raises(ValueError, match="pre_input_validator must be callable"):
        controller.click_point(10, 20, pre_input_validator=False)
