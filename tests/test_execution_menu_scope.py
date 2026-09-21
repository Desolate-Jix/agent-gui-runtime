"""菜单子树完整性不能与被截断的网页树混为一谈。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.api import vision
from app.operation.screen_reading import uia_provider as module
from tests.test_uia_provider_pinned_snapshot import _TreeWrapper


@pytest.mark.parametrize("unrelated_popup", [False, True])
def test_truncated_window_collects_bounded_menu_subtree(monkeypatch, unrelated_popup):
    root = _TreeWrapper((1,), "Window", "browser", (0, 0, 600, 500))
    menu = _TreeWrapper((2,), "Menu", "", (100, 100, 300, 300), root)
    item = _TreeWrapper((3,), "MenuItem", "Select all", (100, 120, 300, 150), menu)
    tail = _TreeWrapper((4,), "MenuItem", "Inspect", (100, 160, 300, 190), menu)
    root.iter_descendants = lambda: iter([menu, item, tail])
    menu.iter_descendants = lambda: iter([item, tail])
    mapping = {id(root): [menu], id(menu): [item, tail]}
    monkeypatch.setattr(module, "_finite_uia_children", lambda node: mapping.get(id(node), []))
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", SimpleNamespace(
        Desktop=lambda **kwargs: SimpleNamespace(window=lambda **kw: root)))
    bound = SimpleNamespace(handle=42, title="browser", process_id=7, process_name="browser.exe",
                            rect=SimpleNamespace(left=0, top=0, right=600, bottom=500))
    provider = module.WindowsUIAProvider()
    if unrelated_popup:
        monkeypatch.setattr(provider, "_owned_popup_handles", lambda bound: [99])
        monkeypatch.setattr(provider, "_popup_menu_scopes", lambda *a, **kw: [])
    result = provider.snapshot_window(bound, max_controls=3)
    assert result["scan_complete"] is False
    scope = result["menu_scopes"][0]
    assert scope["scan_scope"] == "menu_subtree"
    assert scope["scan_complete"] is True
    assert scope["window"]["handle"] == 42
    assert [c["name"] for c in scope["controls"]] == [None, "Select all", "Inspect"]
    assert scope["controls"][-1]["ancestor_control_ids"] == [scope["controls"][0]["control_id"]]


def _window():
    menu = {"provider": "windows_uia", "status": "ok", "scan_scope": "menu_subtree",
            "scan_complete": True, "truncated": False, "scan_budget": 128, "scan_visited_count": 2,
            "window": {"handle": 42}, "controls": [
                {"control_id": "menu", "control_type": "Menu", "name": None,
                 "enabled": True, "visible": True, "bbox": {"x": 100, "y": 100, "w": 200, "h": 200}},
                {"control_id": "select", "control_type": "MenuItem", "name": "Select all",
                 "enabled": True, "visible": True, "patterns": ["Invoke"],
                 "bbox": {"x": 100, "y": 120, "w": 200, "h": 30}}]}
    return {"provider": "windows_uia", "status": "ok", "scan_complete": False,
            "truncated": True, "window": {"handle": 42}, "controls": [], "menu_scopes": [menu]}


@pytest.mark.parametrize("menu_is_root", [False, True])
def test_owned_popup_menu_is_found_beyond_main_tree_budget(monkeypatch, menu_is_root):
    root = _TreeWrapper((1,), "Window", "browser", (0, 0, 600, 500))
    page = _TreeWrapper((2,), "Document", "page", (0, 0, 600, 500), root)
    popup = _TreeWrapper((3,), "Pane", "popup", (100, 100, 300, 300))
    menu = _TreeWrapper((4,), "Menu", "", (100, 100, 300, 300), popup)
    item = _TreeWrapper((5,), "MenuItem", "Select all", (100, 120, 300, 150), menu)
    root.iter_descendants = lambda: iter([page] * 10)
    popup.iter_descendants = lambda: iter([menu, item])
    menu.iter_descendants = lambda: iter([item])
    mapping = {id(root): [page] * 10, id(popup): [menu], id(menu): [item]}
    monkeypatch.setattr(module, "_finite_uia_children", lambda node: mapping.get(id(node), []))
    desktop = SimpleNamespace(window=lambda handle: (menu if menu_is_root else popup) if handle == 99 else root)
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", SimpleNamespace(Desktop=lambda **kw: desktop))
    provider = module.WindowsUIAProvider()
    monkeypatch.setattr(provider, "_owned_popup_handles", lambda bound: [99])
    bound = SimpleNamespace(handle=42, title="browser", process_id=7, process_name="browser.exe",
        rect=SimpleNamespace(left=0, top=0, right=600, bottom=500))
    result = provider.snapshot_window(bound, max_controls=3)
    assert result["scan_complete"] is False
    assert all(c["control_type"] != "Menu" for c in result["controls"])
    scope = result["menu_scopes"][0]
    assert scope["scan_complete"] is True and scope["owned_popup_handle"] == 99
    assert scope["controls"][-1]["name"] == "Select all"


def test_missing_optional_win32_probe_does_not_erase_uia(monkeypatch):
    root = _TreeWrapper((1,), "Window", "browser", (0, 0, 600, 500))
    root.iter_descendants = lambda: iter([])
    monkeypatch.setattr(module, "_finite_uia_children", lambda node: [])
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", SimpleNamespace(
        Desktop=lambda **kwargs: SimpleNamespace(window=lambda **kw: root)))
    monkeypatch.setitem(__import__("sys").modules, "win32gui", None)
    bound = SimpleNamespace(handle=42, title="browser", process_id=7, process_name="browser.exe",
        rect=SimpleNamespace(left=0, top=0, right=600, bottom=500))
    result = module.WindowsUIAProvider().snapshot_window(bound)
    assert result["status"] == "ok" and result["control_count"] == 1
    assert result["owned_popup_probe"]["status"] == "unavailable"


@pytest.mark.parametrize("change", [None, "two_menus", "incomplete_menu", "wrong_window", "disabled", "ordinary_goal"])
def test_fast_inventory_scopes_only_explicit_menu_action(tmp_path, monkeypatch, change):
    snapshot = _window()
    goal = "Click the context menu item labelled Select all"
    if change == "two_menus":
        snapshot["menu_scopes"].append(deepcopy(snapshot["menu_scopes"][0]))
    elif change == "incomplete_menu":
        snapshot["menu_scopes"][0]["scan_complete"] = False
    elif change == "wrong_window":
        snapshot["menu_scopes"][0]["window"]["handle"] = 99
    elif change == "disabled":
        snapshot["menu_scopes"][0]["controls"][0]["enabled"] = False
    elif change == "ordinary_goal":
        goal = "Click the search input box"
    monkeypatch.setattr(vision.uia_provider, "snapshot_bound_window", lambda **kw: snapshot)
    result = vision._execute_fast_inventory_from_uia(image_path=tmp_path / "frame.png",
        image_size=vision.ImageSize(width=600, height=500), app_name=None, goal=goal, metadata=None)
    assert result["status"] == ("ready" if change is None else "incomplete")
    if change is None:
        layer = result["screen_reading"]["source_layers"]["windows_uia"]
        assert layer["scan_scope"] == "menu_subtree"
        assert layer["parent_scan_complete"] is False
        assert len(layer["controls"]) == 1
    assert snapshot["scan_complete"] is False


@pytest.mark.parametrize("goal,label", [
    ("Click the context menu item labelled Select all", "Select all"),
    ("Left click the 全选 item in the right-click context menu of the Google search input box", "全选"),
    ("Click the Select all item in the context menu", "Select all"),
    ("Select the Copy option from the menu", "Copy"),
])
def test_full_plan_passes_menu_crop_to_model(tmp_path, monkeypatch, goal, label):
    from PIL import Image
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from modules.ocr.contracts import OCRResult
    path = tmp_path / "frame.png"
    Image.new("RGB", (2560, 1400)).save(path)
    snapshot = _window()
    snapshot["menu_scopes"][0]["controls"][1]["name"] = label
    monkeypatch.setattr(vision.uia_provider, "snapshot_bound_window", lambda **kw: snapshot)
    calls = []
    def locate(**kw):
        calls.append(kw)
        assert kw["image_preprocess"]["roi_policy"] == "current_menu_subtree_primary"
        assert kw["image_size"].width < 640
        assert kw["image_preprocess"]["menu_bbox"] == snapshot["menu_scopes"][0]["controls"][0]["bbox"]
        return {"point": {"x": 150, "y": 135}, "provider": "test-boundary"}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", locate)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(path), task="locate_element",
        goal=goal, provider_mode="local_grounding", agent_mode="execute",
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata={"vista_direct_grounding": {"refine": False}})
    with pinned_runtime_output_root(tmp_path):
        result = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "test-boundary"},
            image_path=path, input_image_size=vision.ImageSize(width=2560, height=1400), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []}).data["result"]
    assert len(calls) == 1
    assert result["candidate_result"]["summary"]["has_recommendation"] is True


@pytest.mark.parametrize("goal", [
    "Right click the input box to open the context menu",
    "Click the search button next to the menu",
    "Do not click the menu item labelled Copy",
    "Click the word menu inside the input box",
    "Click the input box, then select the Copy item in the menu",
])
def test_menu_context_does_not_replace_actual_action_scope(tmp_path, monkeypatch, goal):
    monkeypatch.setattr(vision.uia_provider, "snapshot_bound_window", lambda **kw: _window())
    result = vision._execute_fast_inventory_from_uia(image_path=tmp_path / "frame.png",
        image_size=vision.ImageSize(width=600, height=500), app_name=None, goal=goal, metadata=None)
    assert result["status"] == "incomplete"
    assert result["screen_reading"]["source_layers"]["windows_uia"]["scan_scope"] == "bound_window"
