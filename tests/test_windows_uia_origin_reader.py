from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.windows_uia_origin_reader import WindowsUIAOriginReader


def _bound(handle: int = 4242, process_id: int | None = 9001) -> SimpleNamespace:
    return SimpleNamespace(handle=handle, process_id=process_id)


class _WindowManager:
    def __init__(self, *snapshots: SimpleNamespace | None) -> None:
        self._snapshots = list(snapshots)
        self.calls = 0

    def get_bound_window(self) -> SimpleNamespace | None:
        self.calls += 1
        if not self._snapshots:
            return None
        return self._snapshots.pop(0)


class _EditControl:
    def __init__(self, value: str = "", *, fallback: str = "", value_error: Exception | None = None) -> None:
        self._value = value
        self._fallback = fallback
        self._value_error = value_error

    def get_value(self) -> str:
        if self._value_error is not None:
            raise self._value_error
        return self._value

    def window_text(self) -> str:
        return self._fallback


class _Root:
    def __init__(self, controls: list[_EditControl]) -> None:
        self.controls = controls
        self.descendant_calls: list[dict[str, object]] = []

    def descendants(self, **kwargs: object) -> list[_EditControl]:
        self.descendant_calls.append(dict(kwargs))
        return list(self.controls)


class _Desktop:
    def __init__(self, root: _Root) -> None:
        self.root = root
        self.window_calls: list[dict[str, object]] = []

    def window(self, **kwargs: object) -> _Root:
        self.window_calls.append(dict(kwargs))
        return self.root


class _DesktopFactory:
    def __init__(self, desktop: _Desktop) -> None:
        self.desktop = desktop
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> _Desktop:
        self.calls.append(dict(kwargs))
        return self.desktop


def _reader(
    *controls: _EditControl,
    before: SimpleNamespace | None = None,
    after: SimpleNamespace | None = None,
) -> tuple[WindowsUIAOriginReader, _WindowManager, _DesktopFactory, _Desktop, _Root]:
    root = _Root(list(controls))
    desktop = _Desktop(root)
    factory = _DesktopFactory(desktop)
    manager = _WindowManager(before or _bound(), after or _bound())
    return (
        WindowsUIAOriginReader(window_manager=manager, desktop_factory=factory),
        manager,
        factory,
        desktop,
        root,
    )


def test_reads_normalized_origin_from_exact_bound_window_descendant() -> None:
    reader, manager, factory, desktop, root = _reader(
        _EditControl("https://Example.COM/jobs/123?source=secret#apply")
    )

    result = reader.read_origin(target_window_handle=4242)

    assert result == {
        "contract_version": "windows_uia_origin_observation_v1",
        "provider": "windows_uia",
        "status": "observed",
        "target_window_handle": 4242,
        "bound_process_id": 9001,
        "origin": "https://example.com",
        "source": "uia_edit_value",
        "edit_control_count": 1,
    }
    assert manager.calls == 2
    assert factory.calls == [{"backend": "uia"}]
    assert desktop.window_calls == [{"handle": 4242}]
    assert root.descendant_calls == [{"control_type": "Edit"}]
    assert "jobs" not in str(result)
    assert "secret" not in str(result)


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("http://EXAMPLE.com:80/path", "http://example.com"),
        ("https://EXAMPLE.com:443/path", "https://example.com"),
        ("https://EXAMPLE.com:8443/path", "https://example.com:8443"),
    ],
)
def test_normalizes_default_ports_and_host_case(url: str, origin: str) -> None:
    reader, *_ = _reader(_EditControl(url))

    result = reader.read_origin(target_window_handle=4242)

    assert result["status"] == "observed"
    assert result["origin"] == origin


def test_uses_window_text_only_when_get_value_is_unavailable() -> None:
    reader, *_ = _reader(
        _EditControl(
            value_error=RuntimeError("Value pattern unavailable"),
            fallback="https://Fallback.Example/current/page",
        )
    )

    result = reader.read_origin(target_window_handle=4242)

    assert result["status"] == "observed"
    assert result["origin"] == "https://fallback.example"
    assert result["source"] == "uia_edit_window_text"


def test_ignores_non_http_malformed_and_credential_urls() -> None:
    reader, *_ = _reader(
        _EditControl("ftp://example.com/file"),
        _EditControl("not a URL"),
        _EditControl("https://user:password@example.com/private"),
        _EditControl("https://exa mple.com/private"),
        _EditControl("https://[invalid"),
        _EditControl("https://example.com:0/private"),
    )

    result = reader.read_origin(target_window_handle=4242)

    assert result["status"] == "unavailable"
    assert result["reason"] == "no_http_origin"
    assert result["origin"] is None
    assert "password" not in str(result)


@pytest.mark.parametrize(
    "after",
    [_bound(handle=4343, process_id=9001), _bound(handle=4242, process_id=9002)],
)
def test_binding_or_process_drift_after_uia_read_fails_closed(after: SimpleNamespace) -> None:
    reader, *_ = _reader(
        _EditControl("https://example.com/private/path"),
        before=_bound(handle=4242, process_id=9001),
        after=after,
    )

    result = reader.read_origin(target_window_handle=4242)

    assert result["status"] == "unavailable"
    assert result["reason"] == "bound_window_drift"
    assert result["origin"] is None
    assert "private" not in str(result)


@pytest.mark.parametrize(
    ("snapshots", "reason"),
    [
        ((None,), "no_bound_window"),
        ((_bound(handle=4343),), "bound_window_mismatch"),
        ((_bound(process_id=None),), "bound_process_unavailable"),
    ],
)
def test_invalid_initial_binding_fails_closed(
    snapshots: tuple[SimpleNamespace | None, ...],
    reason: str,
) -> None:
    manager = _WindowManager(*snapshots)
    reader = WindowsUIAOriginReader(
        window_manager=manager,
        desktop_factory=lambda **_: pytest.fail("UIA must not run without an exact binding"),
    )

    result = reader.read_origin(target_window_handle=4242)

    assert result["status"] == "unavailable"
    assert result["reason"] == reason
    assert result["origin"] is None


def test_missing_uia_dependency_fails_closed_without_leaking_exception_text() -> None:
    manager = _WindowManager(_bound())

    def missing_dependency(**_: object) -> object:
        raise ModuleNotFoundError("missing pywinauto while reading https://example.com/private-token")

    reader = WindowsUIAOriginReader(
        window_manager=manager,
        desktop_factory=missing_dependency,
    )

    result = reader.read_origin(target_window_handle=4242)

    assert result["status"] == "unavailable"
    assert result["reason"] == "uia_dependency_unavailable"
    assert result["origin"] is None
    assert result["error_type"] == "ModuleNotFoundError"
    assert "private-token" not in str(result)


def test_uia_read_failure_is_structured_and_does_not_leak_exception_text() -> None:
    class FailingRoot:
        def descendants(self, **_: object) -> list[object]:
            raise RuntimeError("failed while reading https://example.com/private-token")

    desktop = _Desktop(FailingRoot())
    manager = _WindowManager(_bound(), _bound())
    reader = WindowsUIAOriginReader(
        window_manager=manager,
        desktop_factory=_DesktopFactory(desktop),
    )

    result = reader.read_origin(target_window_handle=4242)

    assert result["status"] == "unavailable"
    assert result["reason"] == "uia_read_failed"
    assert result["error_type"] == "RuntimeError"
    assert result["origin"] is None
    assert "private-token" not in str(result)


def test_no_edit_control_url_fails_closed() -> None:
    reader, *_ = _reader()

    result = reader.read_origin(target_window_handle=4242)

    assert result["status"] == "unavailable"
    assert result["reason"] == "no_http_origin"
    assert result["origin"] is None
