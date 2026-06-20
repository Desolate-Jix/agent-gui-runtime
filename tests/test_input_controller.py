from __future__ import annotations

from types import SimpleNamespace

import app.core.input_controller as input_module
from app.core.input_controller import InputController, VK_A, VK_CONTROL, VK_V


def test_type_text_verifies_clipboard_before_paste_and_restores_after_settle(monkeypatch) -> None:
    controller = InputController()
    events: list[tuple[str, object]] = []
    clipboard_reads = iter(["previous clipboard", "list comprehension"])

    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: events.append(("ensure", None)))
    monkeypatch.setattr(
        controller,
        "_require_bound_window",
        lambda: SimpleNamespace(handle=7, title="Python Docs"),
    )
    monkeypatch.setattr(
        controller,
        "click_point",
        lambda x, y, **kwargs: events.append(("click", (x, y, kwargs))) or {"clicked": True},
    )
    monkeypatch.setattr(controller, "_get_clipboard_text", lambda: next(clipboard_reads))
    monkeypatch.setattr(controller, "_set_clipboard_text", lambda text: events.append(("set_clipboard", text)))
    monkeypatch.setattr(controller, "_press_chord", lambda keys: events.append(("press_chord", tuple(keys))))
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    result = controller.type_text(
        "list comprehension",
        x=575,
        y=352,
        click_before_typing=True,
        clear_existing=True,
    )

    assert result["typed"] is True
    assert result["clipboard_verified_before_paste"] is True
    assert result["clipboard_verify_attempts"] == 1
    assert result["clipboard_paste_settle_ms"] == 150
    assert events == [
        ("ensure", None),
        ("click", (575, 352, {"move_before_click": True, "settle_ms": 100, "hold_ms": 50})),
        ("press_chord", (VK_CONTROL, VK_A)),
        ("sleep", 0.03),
        ("set_clipboard", "list comprehension"),
        ("press_chord", (VK_CONTROL, VK_V)),
        ("sleep", input_module.CLIPBOARD_PASTE_SETTLE_SECONDS),
        ("set_clipboard", "previous clipboard"),
    ]


def test_type_text_fails_when_clipboard_write_verification_mismatches(monkeypatch) -> None:
    controller = InputController()
    events: list[tuple[str, object]] = []
    monotonic_values = iter([100.0, 100.1, 100.4, 100.6])

    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(
        controller,
        "_require_bound_window",
        lambda: SimpleNamespace(handle=7, title="Python Docs"),
    )
    monkeypatch.setattr(controller, "_focus_window", lambda handle: True)
    monkeypatch.setattr(
        controller,
        "_get_clipboard_text",
        lambda: "previous clipboard" if not events else "stale browser url",
    )
    monkeypatch.setattr(controller, "_set_clipboard_text", lambda text: events.append(("set_clipboard", text)))
    monkeypatch.setattr(input_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(
        controller,
        "_press_chord",
        lambda keys: (_ for _ in ()).throw(AssertionError("paste should not run after clipboard mismatch")),
    )

    try:
        controller.type_text("list comprehension")
    except RuntimeError as exc:
        assert "Clipboard write verification failed before paste" in str(exc)
    else:  # pragma: no cover - defensive assertion path
        raise AssertionError("expected clipboard verification failure")

    assert events == [
        ("set_clipboard", "list comprehension"),
        ("sleep", input_module.CLIPBOARD_VERIFY_RETRY_SECONDS),
        ("sleep", input_module.CLIPBOARD_VERIFY_RETRY_SECONDS),
    ]
