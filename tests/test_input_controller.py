from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.core.input_controller as input_module
from app.core.input_controller import InputController, TargetPointOccludedError, VK_A, VK_CONTROL, VK_V


def test_click_point_rejects_occluded_point_before_mouse_down(monkeypatch) -> None:
    controller = InputController()
    bound = SimpleNamespace(handle=7, title="Browser")
    events: list[str] = []
    evidence = {
        "allowed": False,
        "reason": "target_point_occluded",
        "hit_window": {"handle": 900, "title": "QQ notification"},
    }

    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(
        controller,
        "_resolve_window_and_screen_point",
        lambda **kwargs: {"window_x": 315, "window_y": 246, "screen_x": 307, "screen_y": 238},
    )
    monkeypatch.setattr(input_module.win32gui, "GetForegroundWindow", lambda: 7)
    monkeypatch.setattr(input_module.win32api, "GetCursorPos", lambda: (0, 0))
    monkeypatch.setattr(controller, "_focus_window", lambda handle: True)
    monkeypatch.setattr(controller, "_send_move", lambda x, y: events.append("move"))
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        input_module.window_manager,
        "validate_bound_point_visibility",
        lambda **kwargs: evidence,
    )
    monkeypatch.setattr(controller, "mouse_down", lambda button: events.append("mouse_down"))

    with pytest.raises(TargetPointOccludedError) as exc_info:
        controller.click_point(315, 246)

    assert exc_info.value.evidence == evidence
    assert events == ["move"]


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


def test_paste_image_can_target_current_focus_without_refocusing_bound_window(monkeypatch, tmp_path) -> None:
    controller = InputController()
    image_path = tmp_path / "overlay.png"
    image_path.write_bytes(b"fake image bytes")
    events: list[tuple[str, object]] = []

    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: events.append(("ensure", None)))
    monkeypatch.setattr(
        controller,
        "_require_bound_window",
        lambda: (_ for _ in ()).throw(AssertionError("should not require a bound window")),
    )
    monkeypatch.setattr(
        controller,
        "_focus_window",
        lambda handle: (_ for _ in ()).throw(AssertionError("should not refocus a bound window")),
    )
    monkeypatch.setattr(controller, "_image_path_to_cf_dib", lambda path: events.append(("read_image", path)) or b"dib")
    monkeypatch.setattr(controller, "_set_clipboard_image_dib", lambda data: events.append(("set_image", data)))
    monkeypatch.setattr(controller, "_press_chord", lambda keys: events.append(("press_chord", tuple(keys))))
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    result = controller.paste_image(str(image_path), focus_bound_window=False, settle_ms=25)

    assert result["pasted"] is True
    assert result["focus_bound_window"] is False
    assert result["window_handle"] is None
    assert result["clipboard_format"] == "CF_DIB"
    assert result["clipboard_paste_settle_ms"] == 25
    assert events == [
        ("ensure", None),
        ("read_image", image_path),
        ("set_image", b"dib"),
        ("press_chord", (VK_CONTROL, VK_V)),
        ("sleep", 0.025),
    ]


def test_paste_image_can_restore_previous_text_clipboard(monkeypatch, tmp_path) -> None:
    controller = InputController()
    image_path = tmp_path / "overlay.png"
    image_path.write_bytes(b"fake image bytes")
    events: list[tuple[str, object]] = []

    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: SimpleNamespace(handle=9, title="ChatGPT"))
    monkeypatch.setattr(controller, "_focus_window", lambda handle: events.append(("focus", handle)) or True)
    monkeypatch.setattr(controller, "_get_clipboard_text", lambda: "previous text")
    monkeypatch.setattr(controller, "_image_path_to_cf_dib", lambda path: b"dib")
    monkeypatch.setattr(controller, "_set_clipboard_image_dib", lambda data: events.append(("set_image", data)))
    monkeypatch.setattr(controller, "_set_clipboard_text", lambda text: events.append(("set_text", text)))
    monkeypatch.setattr(controller, "_press_chord", lambda keys: events.append(("press_chord", tuple(keys))))
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    result = controller.paste_image(str(image_path), restore_clipboard_text=True)

    assert result["window_handle"] == 9
    assert result["restore_clipboard_text"] is True
    assert events == [
        ("focus", 9),
        ("set_image", b"dib"),
        ("press_chord", (VK_CONTROL, VK_V)),
        ("sleep", input_module.CLIPBOARD_PASTE_SETTLE_SECONDS),
        ("set_text", "previous text"),
    ]
