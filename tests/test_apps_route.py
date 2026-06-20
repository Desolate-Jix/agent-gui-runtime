from __future__ import annotations

from types import SimpleNamespace

from app.api import apps as apps_api
from app.models.request import OpenAppRequest


def test_list_apps_returns_catalog_and_running_windows(monkeypatch) -> None:
    monkeypatch.setattr(apps_api, "_load_app_catalog", lambda: {"contract_version": "app_catalog_v1", "apps": [{"app_id": "edge"}]})
    monkeypatch.setattr(apps_api.window_manager, "list_visible_windows", lambda: [{"title": "Edge", "process_name": "msedge.exe"}])
    monkeypatch.setattr(apps_api.window_manager, "get_bound_window", lambda: None)

    response = apps_api.list_apps()

    assert response.success is True
    assert response.data["contract_version"] == "app_discovery_v1"
    assert response.data["catalog"]["apps"][0]["app_id"] == "edge"
    assert response.data["running_windows"][0]["process_name"] == "msedge.exe"


def test_open_app_launches_catalog_entry_and_binds(monkeypatch) -> None:
    monkeypatch.setattr(
        apps_api,
        "_load_app_catalog",
        lambda: {
            "contract_version": "app_catalog_v1",
            "apps": [
                {
                    "app_id": "demo",
                    "launch_command": ["demo.exe"],
                    "process_name": "demo.exe",
                    "title_hint": "Demo",
                }
            ],
        },
    )
    monkeypatch.setattr(apps_api.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(apps_api.subprocess, "Popen", lambda command: SimpleNamespace(pid=1234, command=command))
    monkeypatch.setattr(apps_api.window_manager, "list_visible_windows", lambda: [{"title": "Demo"}])
    bound = SimpleNamespace(
        handle=1,
        title="Demo",
        process_id=1234,
        process_name="demo.exe",
        rect=SimpleNamespace(left=0, top=0, right=100, bottom=100),
        is_active=True,
    )
    monkeypatch.setattr(apps_api.window_manager, "bind_window", lambda process_name, title: bound)
    monkeypatch.setattr(apps_api, "write_trace", lambda **_kwargs: "trace.json")

    response = apps_api.open_app(OpenAppRequest(app_id="demo"))

    assert response.success is True
    assert response.data["command"] == ["demo.exe"]
    assert response.data["bound_window"]["process_name"] == "demo.exe"
    assert response.data["timings"]["contract_version"] == "runtime_timing_v1"
    assert [step["name"] for step in response.data["timings"]["steps"]] == [
        "load_app_catalog",
        "resolve_app",
        "resolve_launch_command",
        "list_visible_windows_before_open",
        "launch_process",
        "wait_after_open",
        "list_visible_windows",
        "bind_window",
    ]


def test_open_app_resolves_executable_candidate_and_appends_url(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "browser.exe"
    exe.write_text("demo", encoding="utf-8")
    monkeypatch.setattr(
        apps_api,
        "_load_app_catalog",
        lambda: {
            "contract_version": "app_catalog_v1",
            "apps": [
                {
                    "app_id": "browser",
                    "launch_command": ["missing-browser.exe"],
                    "executable_candidates": [str(exe)],
                    "process_name": "browser.exe",
                    "title_hint": "Browser",
                }
            ],
        },
    )
    monkeypatch.setattr(apps_api.time, "sleep", lambda _seconds: None)
    launched: dict[str, object] = {}

    def fake_popen(command):
        launched["command"] = command
        return SimpleNamespace(pid=1234, command=command)

    monkeypatch.setattr(apps_api.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(apps_api.window_manager, "list_visible_windows", lambda: [])
    monkeypatch.setattr(apps_api.window_manager, "bind_window", lambda process_name, title: None)
    monkeypatch.setattr(apps_api, "write_trace", lambda **_kwargs: "trace.json")

    response = apps_api.open_app(OpenAppRequest(app_id="browser", url="https://www.google.com"))

    assert response.success is True
    assert launched["command"] == [str(exe), "https://www.google.com"]
    assert response.data["command"] == [str(exe), "https://www.google.com"]
    assert response.data["timings"]["steps"][0]["name"] == "load_app_catalog"


def test_open_app_uses_requested_browser_url_wait(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "browser.exe"
    exe.write_text("demo", encoding="utf-8")
    monkeypatch.setattr(
        apps_api,
        "_load_app_catalog",
        lambda: {
            "contract_version": "app_catalog_v1",
            "apps": [
                {
                    "app_id": "edge",
                    "launch_command": [str(exe)],
                    "process_name": "msedge.exe",
                    "title_hint": "Microsoft Edge",
                    "capabilities": ["browser_ui"],
                }
            ],
        },
    )
    sleeps: list[float] = []
    monkeypatch.setattr(apps_api.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(apps_api.subprocess, "Popen", lambda command: SimpleNamespace(pid=1234, command=command))
    monkeypatch.setattr(apps_api.window_manager, "list_visible_windows", lambda: [])
    monkeypatch.setattr(apps_api.window_manager, "bind_window", lambda process_name, title: None)
    monkeypatch.setattr(apps_api, "write_trace", lambda **_kwargs: "trace.json")

    response = apps_api.open_app(OpenAppRequest(app_id="edge", url="https://www.google.com", wait_seconds=1.5))

    assert response.success is True
    assert sleeps == [1.5]
    wait_step = next(step for step in response.data["timings"]["steps"] if step["name"] == "wait_after_open")
    assert wait_step["name"] == "wait_after_open"
    assert wait_step["wait_seconds"] == 1.5
    assert wait_step["requested_wait_seconds"] == 1.5


def test_open_app_retries_catalog_title_bind_by_process(monkeypatch) -> None:
    monkeypatch.setattr(
        apps_api,
        "_load_app_catalog",
        lambda: {
            "contract_version": "app_catalog_v1",
            "apps": [
                {
                    "app_id": "edge",
                    "launch_command": ["edge.exe"],
                    "process_name": "msedge.exe",
                    "title_hint": "Microsoft Edge",
                    "capabilities": ["browser_ui"],
                }
            ],
        },
    )
    monkeypatch.setattr(apps_api.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(apps_api.subprocess, "Popen", lambda command: SimpleNamespace(pid=1234, command=command))
    monkeypatch.setattr(apps_api.window_manager, "list_visible_windows", lambda: [{"title": "Microsoft Edge"}])
    bound = SimpleNamespace(
        handle=1,
        title="Google News - Microsoft Edge",
        process_id=1234,
        process_name="msedge.exe",
        rect=SimpleNamespace(left=0, top=0, right=100, bottom=100),
        is_active=True,
    )
    calls: list[tuple[str | None, str | None]] = []

    def fake_bind(process_name, title):
        calls.append((process_name, title))
        if title:
            raise ValueError("No matching visible top-level window found")
        return bound

    monkeypatch.setattr(apps_api.window_manager, "bind_window", fake_bind)
    monkeypatch.setattr(apps_api, "write_trace", lambda **_kwargs: "trace.json")

    response = apps_api.open_app(OpenAppRequest(app_id="edge", url="https://news.google.com"))

    assert response.success is True
    assert response.data["bound_window"]["window_title"] == "Google News - Microsoft Edge"
    assert calls == [("msedge.exe", "Microsoft Edge"), ("msedge.exe", None)]


def test_open_app_prefers_new_window_handle_over_existing_title_match(monkeypatch) -> None:
    monkeypatch.setattr(
        apps_api,
        "_load_app_catalog",
        lambda: {
            "contract_version": "app_catalog_v1",
            "apps": [
                {
                    "app_id": "edge",
                    "launch_command": ["edge.exe"],
                    "process_name": "msedge.exe",
                    "title_hint": "Microsoft Edge",
                    "capabilities": ["browser_ui"],
                }
            ],
        },
    )
    monkeypatch.setattr(apps_api.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(apps_api.subprocess, "Popen", lambda command: SimpleNamespace(pid=4321, command=command))
    snapshots = [
        [
            {
                "handle": 10,
                "title": "Review and submit | SEEK - Microsoft Edge",
                "process_id": 111,
                "process_name": "msedge.exe",
            }
        ],
        [
            {
                "handle": 10,
                "title": "Review and submit | SEEK - Microsoft Edge",
                "process_id": 111,
                "process_name": "msedge.exe",
            },
            {
                "handle": 20,
                "title": "New tab - Microsoft Edge",
                "process_id": 111,
                "process_name": "msedge.exe",
            },
        ],
    ]

    def fake_list_visible_windows():
        return snapshots.pop(0)

    bound = SimpleNamespace(
        handle=20,
        title="New tab - Microsoft Edge",
        process_id=111,
        process_name="msedge.exe",
        rect=SimpleNamespace(left=0, top=0, right=100, bottom=100),
        is_active=True,
    )
    bind_calls: list[tuple[str | None, str | None]] = []
    handle_calls: list[int] = []
    monkeypatch.setattr(apps_api.window_manager, "list_visible_windows", fake_list_visible_windows)
    monkeypatch.setattr(apps_api.window_manager, "bind_window_by_handle", lambda handle: handle_calls.append(handle) or bound)
    monkeypatch.setattr(apps_api.window_manager, "bind_window", lambda process_name, title: bind_calls.append((process_name, title)) or bound)
    monkeypatch.setattr(apps_api, "write_trace", lambda **_kwargs: "trace.json")

    response = apps_api.open_app(OpenAppRequest(app_id="edge", url="https://nz.seek.com/", title="SEEK"))

    assert response.success is True
    assert response.data["bound_window"]["handle"] == 20
    assert handle_calls == [20]
    assert bind_calls == []
    assert response.data["windows_before_open"][0]["handle"] == 10
