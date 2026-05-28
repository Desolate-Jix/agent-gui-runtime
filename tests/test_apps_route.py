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
