"""首次学习不需要旧资产；目录启动仍经同一确认与系统边界。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from tests.test_window_preparation_authority import scene


@pytest.fixture
def catalog_host(tmp_path, monkeypatch, scene, request):
    manager, state, identity, _reader = scene
    exe = tmp_path / getattr(request, "param", "fresh.exe")
    exe.write_bytes(b"synthetic; must never execute")
    identity["executable_path"] = str(exe).replace("/", "\\").casefold()
    catalog = {"contract_version": "app_catalog_v1", "apps": [{
        "app_id": "fixture", "name": "Fresh browser", "launch_command": [str(exe)],
        "capabilities": ["open_url", "browser_ui"], "process_name": "fresh.exe",
    }]}
    monkeypatch.setattr("app.api.apps._load_app_catalog", lambda: deepcopy(catalog))
    launched = []
    monkeypatch.setattr("app.core.application_launch.launch_process", lambda cmd: launched.append(list(cmd)) or SimpleNamespace(pid=987))
    monkeypatch.setattr("psutil.Process", lambda pid: SimpleNamespace(
        exe=lambda: identity["executable_path"], create_time=lambda: identity["process_create_time"]))
    monkeypatch.setattr(manager, "list_visible_windows", lambda: [
        dict(handle=321, process_id=12, title="Fresh fixture", process_name="fresh.exe")
    ] if launched else [])
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "reviews", "reviewer-test-token-20260913")
    host.start()
    co = NativeSingleStepCoordinator(tmp_path / "reviews", host.facade, host,
        thread_initializer=lambda: None, thread_finalizer=lambda: None)
    co._window_manager = manager
    try:
        yield co, catalog, launched, state, exe
    finally:
        co.shutdown()


def test_empty_workspace_discovers_previews_confirms_exact_url_once(catalog_host):
    co, _catalog, launched, state, exe = catalog_host
    discovery = co.discover_applications()
    assert discovery["contract_version"] == "native_application_discovery_v1"
    assert discovery["apps"][0]["launchable"] is True
    assert discovery["running_windows"] == [] and launched == []
    preview = co.preview_application_launch(app_id="fixture", url="https://example.org/search?q=place")
    assert preview["source"] == "app_catalog" and "asset_id" not in preview
    assert preview["command"] == [str(exe).casefold(), "https://example.org/search?q=place"]
    assert launched == [] and co._runtime is None
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "launched_window_ready"
    assert result["window"]["handle"] == 321 and result["window"]["process_id"] == 12
    assert launched == [preview["command"]] and state.mutations == []
    assert co._runtime is None and co._prepared_window_identities == {}
    with pytest.raises(NativeSingleStepCoordinatorError):
        co.confirm_window_preparation(preview["preparation_id"])
    assert len(launched) == 1


@pytest.mark.parametrize("change", ["arguments", "duplicate", "file", "expiry"])
def test_catalog_or_binary_drift_and_expiry_reject_without_launch(catalog_host, change):
    co, catalog, launched, _state, exe = catalog_host
    preview = co.preview_application_launch(app_id="fixture")
    if change == "arguments": catalog["apps"][0]["launch_command"].append("--new-argument")
    elif change == "duplicate": catalog["apps"].append(deepcopy(catalog["apps"][0]))
    elif change == "file": exe.write_bytes(b"changed executable")
    else: co._window_preparations[preview["preparation_id"]]["expires_at"] = 0
    with pytest.raises(NativeSingleStepCoordinatorError):
        co.confirm_window_preparation(preview["preparation_id"])
    assert launched == []


@pytest.mark.parametrize("url", ["file:///C:/secret", "javascript:alert(1)", "--flag", "https://u:p@example.org", "https://example.org/\n--flag", "https://", "https://example.org:bad/"])
def test_untrusted_url_never_becomes_command_options(catalog_host, url):
    co, _catalog, launched, _state, _exe = catalog_host
    with pytest.raises(NativeSingleStepCoordinatorError):
        co.preview_application_launch(app_id="fixture", url=url)
    assert launched == []


def test_non_url_app_and_unknown_catalog_id_reject(catalog_host):
    co, catalog, launched, _state, _exe = catalog_host
    catalog["apps"][0]["capabilities"] = ["text_editing"]
    for app_id in ("fixture", "unknown"):
        with pytest.raises(NativeSingleStepCoordinatorError):
            co.preview_application_launch(app_id=app_id, url="https://example.org")
    assert launched == []


def test_unknown_launch_is_not_mistaken_for_ready_or_retried(catalog_host, monkeypatch):
    co, _catalog, launched, _state, _exe = catalog_host
    monkeypatch.setattr(co._windows(), "list_visible_windows", lambda: [])
    co._WINDOW_PREPARATION_TTL_SECONDS = 0.02
    preview = co.preview_application_launch(app_id="fixture")
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["result_unknown"] is True and result["window"] is None
    co.discover_applications()
    with pytest.raises(NativeSingleStepCoordinatorError) as error:
        co.preview_application_launch(app_id="fixture")
    assert error.value.code == "window_launch_requires_inventory" and len(launched) == 1


@pytest.mark.parametrize("catalog_host", ["msedge.exe", "chrome.exe"], indirect=True)
def test_browser_url_launch_freezes_new_window_option(catalog_host):
    co, _catalog, launched, _state, exe = catalog_host
    preview = co.preview_application_launch(app_id="fixture", url="https://example.org/")
    assert preview["command"] == [str(exe).casefold(), "--new-window", "https://example.org/"]
    assert launched == []
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "launched_window_ready"
    assert launched == [preview["command"]]


@pytest.mark.parametrize("catalog_host", ["msedge.exe"], indirect=True)
def test_browser_option_is_scoped_and_not_duplicated(catalog_host):
    co, catalog, _launched, _state, exe = catalog_host
    assert co.preview_application_launch(app_id="fixture")["command"] == [str(exe).casefold()]
    catalog["apps"][0]["capabilities"].remove("browser_ui")
    assert "--new-window" not in co.preview_application_launch(
        app_id="fixture", url="https://example.org/")["command"]
    catalog["apps"][0]["capabilities"].append("browser_ui")
    catalog["apps"][0]["launch_command"].append("--new-window")
    assert co.preview_application_launch(app_id="fixture", url="https://example.org/")["command"].count("--new-window") == 1
