from __future__ import annotations

from app.api import session as session_api
from app.core.window_manager import BoundWindow, WindowRect
from app.api.models.request import BindWindowRequest, ResizeBoundWindowRequest


def _bound(title: str = "Demo") -> BoundWindow:
    return BoundWindow(
        handle=123,
        title=title,
        process_id=456,
        process_name="msedge.exe",
        rect=WindowRect(left=10, top=20, right=810, bottom=620),
        is_active=True,
    )


def test_resize_bound_window_route_returns_before_and_after(monkeypatch) -> None:
    before = _bound("Before")
    after = BoundWindow(
        handle=123,
        title="After",
        process_id=456,
        process_name="msedge.exe",
        rect=WindowRect(left=20, top=30, right=1120, bottom=930),
        is_active=True,
    )
    calls: list[dict] = []

    monkeypatch.setattr(session_api.window_manager, "get_bound_window", lambda: before)

    def fake_resize_bound_window(**kwargs):
        calls.append(kwargs)
        return after

    monkeypatch.setattr(session_api.window_manager, "resize_bound_window", fake_resize_bound_window)

    response = session_api.resize_bound_window(
        ResizeBoundWindowRequest(width=1100, height=900, left=20, top=30)
    )

    assert response.success is True
    assert calls == [{"width": 1100, "height": 900, "left": 20, "top": 30, "focus": True}]
    assert response.data["contract_version"] == "bound_window_resize_v1"
    assert response.data["before"]["window_title"] == "Before"
    assert response.data["after"]["window_title"] == "After"
    assert response.data["after"]["rect"] == {"left": 20, "top": 30, "right": 1120, "bottom": 930}


def test_bind_window_route_returns_operation_context(monkeypatch) -> None:
    bound = _bound("Bound")
    monkeypatch.setattr(session_api.window_manager, "list_visible_windows", lambda: [{"handle": 123, "title": "Bound"}])
    monkeypatch.setattr(session_api.window_manager, "bind_window", lambda process_name, title: bound)

    response = session_api.bind_window(BindWindowRequest(process_name="msedge.exe", title="Bound"))

    assert response.success is True
    assert response.data["operation_context"]["skill_id"] == "bind_window"
    assert response.data["operation_context"]["window_binding_id"] == "window:123"
    assert response.data["operation_trace_link"]["result_status"] == "success"


def test_resize_bound_window_route_reports_failure(monkeypatch) -> None:
    monkeypatch.setattr(session_api.window_manager, "get_bound_window", lambda: None)

    def fake_resize_bound_window(**kwargs):
        raise ValueError("No bound window available to resize")

    monkeypatch.setattr(session_api.window_manager, "resize_bound_window", fake_resize_bound_window)

    response = session_api.resize_bound_window(ResizeBoundWindowRequest(width=1100, height=900))

    assert response.success is False
    assert response.message == "Failed to resize bound window"
    assert response.error is not None
    assert response.error.code == "window_resize_failed"
