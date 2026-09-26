"""浏览器正文首次可访问性采样与截图同代绑定的离线回归。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core.local_input_policy import _local_operator_input_scope


def api():
    from app.operation.screen_reading import browser_content_readiness
    return browser_content_readiness


def test_preparation_preserves_execution_inventory_scan_budget(monkeypatch, harness):
    from app.operation.screen_reading.uia_provider import HARD_UIA_MAX_CONTROLS
    calls = []
    monkeypatch.setattr(api().uia_provider, "snapshot_window", lambda bound, **kwargs:
        calls.append((bound, kwargs)) or snapshot())
    assert api()._snapshot(harness.bound)["status"] == "ok"
    assert calls == [(harness.bound, {"max_controls": HARD_UIA_MAX_CONTROLS})]


def snapshot(document=True, **changes):
    value = {"status": "ok", "scan_complete": True, "truncated": False,
        "traversal_errors": [], "provider_tree_valid": True, "scan_visited_count": 3,
        "window": {"handle": 321, "process_id": 12, "process_name": "msedge.exe",
            "bbox": {"x": 0, "y": 0, "w": 1000, "h": 690}},
        "controls": [{"control_id": "uia_0_root", "control_type": "Window",
            "class_name": "Chrome_WidgetWin_1", "runtime_id": [42, 321]}]}
    if document:
        value["controls"].append({"control_id": "doc", "control_type": "Document", "runtime_id": [1, 2]})
    value.update(changes)
    return value


@pytest.fixture
def harness(monkeypatch):
    bound = SimpleNamespace(handle=321, process_id=12, process_name="msedge.exe", title="Fixture",
        rect=SimpleNamespace(left=100, top=200, right=1100, bottom=890))
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 321, "process_id": 12,
        "process_create_time": 123.5, "executable_path": "c:\\fixture\\msedge.exe"}
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    reader = SimpleNamespace(read_identity=lambda handle: deepcopy(identity))
    scope = lambda: _local_operator_input_scope(manager=manager, identity_reader=reader, identity=identity,
        window_rect=(100, 200, 1100, 890), enabled=lambda: True)
    return SimpleNamespace(manager=manager, bound=bound, identity=identity, scope=scope)


def source(monkeypatch, values):
    samples = iter(values)
    events = []
    clock = [0.0]
    def read(bound):
        events.append("sample")
        return deepcopy(next(samples))
    def wait(seconds):
        events.append("wait")
        clock[0] += seconds
    monkeypatch.setattr(api(), "_snapshot", read)
    monkeypatch.setattr(api(), "_clock", lambda: clock[0])
    monkeypatch.setattr(api(), "_wait", wait)
    return events


@pytest.mark.parametrize("goal", ["Click the search input field in the webpage", "Click the Address input field",
    'Click the input field labelled "Address"'])
def test_first_empty_content_prepares_before_new_capture_and_uses_final_tree(monkeypatch, harness, goal):
    events = source(monkeypatch, [snapshot(False), snapshot(), snapshot(controls=[
        snapshot()["controls"][0], {"control_id": "final-doc", "control_type": "Document", "runtime_id": [1, 9]}])])
    with harness.scope():
        prepared = api().prepare_browser_content(harness.manager, goal)
        events.append("capture")
        final = prepared.capture_snapshot({"image_path": "fresh.png", "window_size": {"width": 1000, "height": 690}})
    assert events == ["sample", "wait", "sample", "capture", "sample"]
    assert final["controls"][-1]["control_id"] == "final-doc"
    assert prepared.report["samples"][0]["document_count"] == 0
    assert prepared.report["initial_snapshot"]["controls"] == snapshot(False)["controls"]
    assert prepared.report["capture_binding"]["image_path"] == "fresh.png"
    assert prepared.report["page_ready_verified"] is None
    assert prepared.report["automatic_retry_allowed"] is False


def test_existing_document_never_waits(monkeypatch, harness):
    events = source(monkeypatch, [snapshot()])
    with harness.scope():
        prepared = api().prepare_browser_content(harness.manager, "Click the Address input field")
    assert events == ["sample"]
    assert prepared.report["status"] == "observed"


def test_explicit_batch_focus_prepares_browser_without_goal_grammar(monkeypatch, harness):
    from app.core.local_text_focus import LocalTextFocusTarget, local_text_focus_scope
    goal = 'Focus the first text input labelled \u4ee5\u4e0b\u6240\u6709\u5b57\u8bcd'
    events = source(monkeypatch, [snapshot()])
    with harness.scope(), local_text_focus_scope(LocalTextFocusTarget(321, 12)):
        prepared = api().prepare_browser_content(harness.manager, goal)
    assert prepared is not None
    assert events == ['sample']
    with harness.scope():
        assert api().prepare_browser_content(harness.manager, goal) is None


@pytest.mark.parametrize("edge", ["sibling", "self", "root", "cross_parent"])
def test_canonical_complete_alias_graph_remains_usable(monkeypatch, harness, edge):
    from tests.test_uia_alias_normalization import Node, install
    from app.operation.screen_reading import uia_provider as provider
    install(monkeypatch)
    root = Node(1)
    first, wanted = Node(2, root), Node(3, root)
    root.children = [first, wanted]
    if edge == "sibling": root.children = [first, first, wanted]
    elif edge == "self": first.children = [first]
    elif edge == "root": first.children = [root]
    else: wanted.children = [first]
    walk = provider._bounded_uia_walk(root, budget=100)
    assert walk["provider_tree_valid"] is False and walk["graph_scan_complete"] is True
    value = snapshot(**provider._walk_metadata(walk))
    events = source(monkeypatch, [value, value])
    with harness.scope():
        prepared = api().prepare_browser_content(harness.manager, "Click the Address input field")
        final = prepared.capture_snapshot({"image_path": "fresh.png", "window_size": {"width": 1000, "height": 690}})
    assert final["provider_tree_valid"] is False
    assert events == ["sample", "sample"]


@pytest.mark.parametrize("changes", [{"graph_scan_complete": False}, {"graph_scan_complete": None},
    {"alias_count": 0}, {"alias_count": True}, {"cycle_count": -1}, {"cycle_count": 2},
    {"provider_tree_valid": None}, {"traversal_errors": None},
    {"traversal_errors": [{"reason": "tree_runtime_id_conflict"}]}])
def test_unknown_or_conflicting_alias_graph_never_becomes_ready(monkeypatch, harness, changes):
    value = snapshot(provider_tree_valid=False, graph_scan_complete=True, alias_count=1, cycle_count=0)
    value.update(changes)
    events = source(monkeypatch, [value])
    with harness.scope(), pytest.raises(api().BrowserContentReadinessError, match="browser_content_scan_incomplete"):
        api().prepare_browser_content(harness.manager, "Click the Address input field")
    assert events == ["sample"]


def test_other_application_is_not_probed(monkeypatch, harness):
    harness.bound.process_name = "editor.exe"
    events = source(monkeypatch, [])
    with harness.scope():
        assert api().prepare_browser_content(harness.manager, "Click the Address input field") is None
    assert events == []


def test_edge_owned_native_dialog_does_not_require_browser_document(monkeypatch, harness):
    dialog = snapshot(False)
    dialog["controls"][0]["class_name"] = "#32770"
    events = source(monkeypatch, [dialog])
    with harness.scope():
        prepared = api().prepare_browser_content(harness.manager,
            'Click the input field labelled "\u6587\u4ef6\u540d(N):"')
    assert prepared is None
    assert events == ["sample"]


def test_unknown_browser_process_root_still_fails_closed(monkeypatch, harness):
    unknown = snapshot(False)
    unknown["controls"][0]["class_name"] = "OtherWindow"
    events = source(monkeypatch, [unknown])
    with harness.scope(), pytest.raises(api().BrowserContentReadinessError,
            match="browser_content_root_unavailable"):
        api().prepare_browser_content(harness.manager, 'Click the input field labelled "Address"')
    assert events == ["sample"]


def test_no_local_scope_cannot_start_preparation(monkeypatch, harness):
    events = source(monkeypatch, [])
    with pytest.raises(api().BrowserContentReadinessError, match="identity_changed"):
        api().prepare_browser_content(harness.manager, "Click the Address input field")
    assert events == []


@pytest.mark.parametrize("goal", ["Click the browser Back button", "Click the address bar", "Click the menu item Open",
    "Click the word Address inside the input field", "Click the browser search input field",
    "Click the input field", "Click the input field not in the webpage"])
def test_non_page_field_targets_do_not_probe(monkeypatch, harness, goal):
    events = source(monkeypatch, [])
    with harness.scope():
        assert api().prepare_browser_content(harness.manager, goal) is None
    assert events == []


@pytest.mark.parametrize("changes", [{"scan_complete": False}, {"truncated": True},
    {"traversal_errors": [{"reason": "children_enumeration_failed"}]}, {"status": "unavailable"}])
def test_bad_scan_never_waits_or_becomes_ready(monkeypatch, harness, changes):
    events = source(monkeypatch, [snapshot(False, **changes)])
    with harness.scope(), pytest.raises(api().BrowserContentReadinessError) as failure:
        api().prepare_browser_content(harness.manager, "Click the Address input field")
    assert events == ["sample"]
    assert failure.value.report["status"] == "unavailable"


def test_never_ready_is_bounded_and_keeps_first_absence(monkeypatch, harness):
    events = source(monkeypatch, [snapshot(False)] * 20)
    with harness.scope(), pytest.raises(api().BrowserContentReadinessError, match="browser_content_not_observed") as failure:
        api().prepare_browser_content(harness.manager, "Click the search input field in the webpage")
    assert events.count("sample") <= 16
    assert len(failure.value.report["samples"]) == events.count("sample")
    assert failure.value.report["initial_snapshot"]["controls"] == snapshot(False)["controls"]


def test_root_identity_change_is_not_retried(monkeypatch, harness):
    changed = snapshot()
    changed["controls"][0]["runtime_id"] = [42, 999]
    events = source(monkeypatch, [snapshot(False), changed])
    with harness.scope(), pytest.raises(api().BrowserContentReadinessError, match="identity_changed"):
        api().prepare_browser_content(harness.manager, "Click the Address input field")
    assert events == ["sample", "wait", "sample"]


def test_process_change_during_wait_is_rejected(monkeypatch, harness):
    events = source(monkeypatch, [snapshot(False)])
    monkeypatch.setattr(api(), "_wait", lambda seconds: harness.identity.update(process_create_time=999.0))
    with harness.scope(), pytest.raises(api().BrowserContentReadinessError, match="identity_changed"):
        api().prepare_browser_content(harness.manager, "Click the Address input field")
    assert events == ["sample"]


def test_final_capture_tree_loss_does_not_wait_or_use_old_tree(monkeypatch, harness):
    events = source(monkeypatch, [snapshot(), snapshot(False)])
    with harness.scope():
        prepared = api().prepare_browser_content(harness.manager, "Click the Address input field")
        with pytest.raises(api().BrowserContentReadinessError, match="browser_content_not_observed"):
            prepared.capture_snapshot({"image_path": "fresh.png", "window_size": {"width": 1000, "height": 690}})
    assert events == ["sample", "sample"]


@pytest.mark.parametrize("change", ["geometry", "viewport", "roi", "snapshot_window"])
def test_capture_binding_drift_is_rejected_before_recognition(monkeypatch, harness, change):
    final = snapshot()
    if change == "snapshot_window": final["window"]["handle"] = 999
    events = source(monkeypatch, [snapshot(), final])
    with harness.scope():
        prepared = api().prepare_browser_content(harness.manager, "Click the Address input field")
        capture = {"image_path": "fresh.png", "window_size": {"width": 1000, "height": 690}}
        if change == "geometry": harness.bound.rect.left = 101
        elif change == "viewport": capture["window_size"]["width"] = 500
        elif change == "roi": capture["roi"] = {"x": 1, "y": 1, "w": 500, "h": 300}
        with pytest.raises(api().BrowserContentReadinessError):
            prepared.capture_snapshot(capture)
    assert "wait" not in events


@pytest.mark.parametrize("mode", ["ready", "timeout", "bad_scan", "final_loss", "model_error"])
def test_real_action_route_prepares_before_capture_and_pins_only_final_generation(monkeypatch, harness, tmp_path, mode):
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.api.models.response import APIResponse
    from app.operation.screen_reading.uia_provider import _PINNED_UIA_SNAPSHOT, uia_provider
    from tests.test_local_recognition_policy import plan_fixture

    values = [snapshot(False), snapshot(), snapshot()]
    if mode == "timeout": values = [snapshot(False)] * 20
    elif mode == "bad_scan": values = [snapshot(False, scan_complete=False)]
    elif mode == "final_loss": values[-1] = snapshot(False)
    events = source(monkeypatch, values)
    image = str((tmp_path / "fresh.png").resolve())
    monkeypatch.setattr(action, "window_manager", harness.manager)
    def capture(**kwargs):
        events.append("capture")
        return {"image_path": image, "window_size": {"width": 1000, "height": 690}, "roi": None}
    monkeypatch.setattr(action.screenshot_service, "capture_window", capture)
    def recognize(request):
        events.append("model")
        assert request.image_path == image
        assert _PINNED_UIA_SNAPSHOT.get() is not None
        assert uia_provider.snapshot_bound_window()["controls"] == snapshot()["controls"]
        if mode == "model_error":
            raise RuntimeError("model failed")
        return APIResponse(success=True, message="fixture", data={"result": plan_fixture(image)})
    monkeypatch.setattr(action, "_run_recognition_plan_for_execution", recognize)
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda p: None)
    monkeypatch.setattr(action, "write_trace", lambda **kw: str(tmp_path / "trace.json"))
    monkeypatch.setattr(action, "_rewrite_execute_trace_result", lambda **kw: None)
    monkeypatch.setattr(action.input_controller, "click_point", lambda *args, **kwargs:
        events.append("click") or {"clicked": True, "window_point": {"x": 184, "y": 516}})
    request = ExecuteRecognitionPlanRequest(goal="Click the Address input field", agent_mode="execute",
        auto_observe_learning_artifacts=False, enable_post_click_verification=False, max_execution_attempts=1,
        write_policy={"path_graph": False, "element_memory": False, "trace": True})
    with harness.scope():
        if mode == "model_error":
            with pytest.raises(RuntimeError, match="model failed"):
                action.execute_recognition_plan(request)
        else:
            response = action.execute_recognition_plan(request)
    assert _PINNED_UIA_SNAPSHOT.get() is None
    if mode == "ready":
        assert response.success, response
        assert events == ["sample", "wait", "sample", "capture", "sample", "model", "click"]
        report = response.data["result"]["live_capture"]["browser_content_readiness"]
        assert report["samples"][0]["document_count"] == 0
        assert report["capture_binding"]["image_path"] == image
    elif mode == "model_error":
        assert events == ["sample", "wait", "sample", "capture", "sample", "model"]
    else:
        assert not response.success
        assert response.data["action_executed"] is False
        assert response.data["browser_content_readiness"]["status"] == "unavailable"
        assert "model" not in events and "click" not in events
        assert events.count("capture") == (1 if mode == "final_loss" else 0)
