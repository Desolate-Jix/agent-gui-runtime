from types import SimpleNamespace

import pytest

import app.core.input_controller as input_module
from app.core.input_controller import InputController, VK_A, VK_CONTROL, VK_V


class ClipboardSession:
    def __init__(self, events):
        self.events = events
        self.status = "not_started"

    def __enter__(self):
        self.events.append("clipboard-prepared")
        self.status = "pending_restore"
        return self

    def verify_current_text(self):
        self.events.append("clipboard-verified")
        return 1

    def __exit__(self, *exception):
        self.status = "restored"
        self.events.append("clipboard-restored")


def prepared(monkeypatch):
    controller = InputController()
    events = []
    bound = SimpleNamespace(handle=7, process_id=9, title="isolated", rect=SimpleNamespace(left=0, top=0, right=320, bottom=200))
    session = ClipboardSession(events)
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_focus_window", lambda hwnd: True)
    monkeypatch.setattr(input_module.win32gui, "GetForegroundWindow", lambda: 7)
    monkeypatch.setattr(input_module.window_manager, "validate_bound_point_visibility", lambda **kwargs: {"allowed": True})
    monkeypatch.setattr(input_module.window_manager, "validate_bound_region_visibility", lambda **kwargs: {"allowed": True})
    monkeypatch.setattr(controller, "_clipboard_text_transaction", lambda *args, **kwargs: session, raising=False)
    monkeypatch.setattr(controller, "_get_clipboard_text", lambda: "next")
    monkeypatch.setattr(controller, "_set_clipboard_text", lambda text: None)
    monkeypatch.setattr(controller, "click_point", lambda *args, **kwargs: events.append("click") or {"clicked": True})
    monkeypatch.setattr(controller, "_press_chord", lambda keys: events.append(tuple(keys)))
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: None)
    return controller, bound, events, session


def test_text_primary_path_uses_one_paste_with_restore_after_paste(monkeypatch):
    controller, _, events, _ = prepared(monkeypatch)
    result = controller.type_text("next", x=70, y=80, click_before_typing=True, clear_existing=True)
    assert result["typed"] is True
    assert result["clipboard_restore_status"] == "restored"
    assert events.count("click") == 1
    assert events.count((VK_CONTROL, VK_V)) == 1
    assert events.index("clipboard-prepared") < events.index("click")
    assert events.index((VK_CONTROL, VK_A)) < events.index((VK_CONTROL, VK_V)) < events.index("clipboard-restored")


def test_text_never_types_when_focus_request_did_not_focus_target(monkeypatch):
    controller, _, events, _ = prepared(monkeypatch)
    monkeypatch.setattr(controller, "_focus_window", lambda hwnd: False)
    monkeypatch.setattr(input_module.win32gui, "GetForegroundWindow", lambda: 999)
    with pytest.raises(RuntimeError, match="foreground"):
        controller.type_text("next")
    assert not any(isinstance(event, tuple) for event in events)
    assert events[-1] == "clipboard-restored"


def test_text_rechecks_target_after_select_all_before_paste(monkeypatch):
    controller, bound, events, _ = prepared(monkeypatch)

    def chord(keys):
        events.append(tuple(keys))
        if keys == [VK_CONTROL, VK_A]:
            bound.rect.right += 10

    monkeypatch.setattr(controller, "_press_chord", chord)
    with pytest.raises(RuntimeError, match="changed"):
        controller.type_text("next", x=70, y=80, click_before_typing=True, clear_existing=True)
    assert (VK_CONTROL, VK_V) not in events
    assert events[-1] == "clipboard-restored"


def test_partial_chord_failure_releases_attempted_keys(monkeypatch):
    controller = InputController()
    events = []

    def key(value, *, key_up):
        events.append((value, key_up))
        if value == VK_V and not key_up:
            raise RuntimeError("send failed")

    monkeypatch.setattr(controller, "_send_key", key)
    with pytest.raises(RuntimeError, match="send failed"):
        controller._press_chord([VK_CONTROL, VK_V])
    assert events == [(VK_CONTROL, False), (VK_V, False), (VK_V, True), (VK_CONTROL, True)]


def test_clipboard_preparation_cannot_redirect_the_following_click(monkeypatch):
    controller, bound, events, _ = prepared(monkeypatch)

    class ReboundClipboard(ClipboardSession):
        def __enter__(self):
            result = super().__enter__()
            bound.handle = 888
            return result

    monkeypatch.setattr(controller, "_clipboard_text_transaction", lambda *args, **kwargs: ReboundClipboard(events))
    with pytest.raises(RuntimeError, match="changed"):
        controller.type_text("next", x=70, y=80, click_before_typing=True)
    assert "click" not in events
    assert events[-1] == "clipboard-restored"


@pytest.mark.parametrize('value,selection,allowed', [('', None, True), ('abc', None, False),
                                                  ('abc', (1, 2), False), ('abc', (0, 3), True)])
def test_verified_empty_value_needs_no_fabricated_selection_but_nonempty_requires_all(monkeypatch, value, selection, allowed):
    from dataclasses import replace
    from app.agent.text_input_guard import TextInputGuard
    from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot, prepare_text_field_expectation
    from app.agent.text_parameters import ReviewedTextParameters, ReviewedTextSource, resolve_text_parameters
    controller, _, events, _ = prepared(monkeypatch)
    identity = TextFieldIdentity('field', 7, 9, 10.5, (42, 1), (0, 0, 320, 200), (20, 30, 180, 40))
    before = TextFieldSnapshot(identity, 'capture', 'before', 100, 'uia_value', value, selection)
    params = resolve_text_parameters(ReviewedTextParameters('field', ReviewedTextSource('literal', 'next'), True, False), {})
    counter = []
    def current():
        counter.append(1)
        return replace(before, read_id=f'read-{len(counter)}', observed_at_ns=100+len(counter))
    guard = TextInputGuard(prepare_text_field_expectation(before, params), current)
    kwargs = dict(x=70, y=40, click_before_typing=True, clear_existing=True, field_guard=guard)
    if allowed:
        assert controller.type_text('next', **kwargs)['typed']
        assert events.count((VK_CONTROL, VK_V)) == 1
    else:
        with pytest.raises(ValueError, match='precondition'):
            controller.type_text('next', **kwargs)
        assert (VK_CONTROL, VK_V) not in events
    assert events[-1] == 'clipboard-restored'
    assert len(counter) == 2
