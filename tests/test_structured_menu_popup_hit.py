"""原生菜单浮窗只凭本次完整来源证明进入严格双次命中。"""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from tests.test_task_plan_target import control, current_frame


def menu_snapshot(frame, kind="MenuItem"):
    capture, snapshot = frame
    menu = control("menu", "Settings menu", "Menu", (10, 10, 250, 190), runtime_id=[42, 700])
    item = control("language", "Language", kind, (40, 80, 120, 40), ancestors=("menu",))
    snapshot["controls"] = [menu, item]
    scoped_menu, scoped_item = deepcopy(menu), deepcopy(item)
    scoped_menu["control_id"] = "scope_menu"
    scoped_item["control_id"] = "scope_item"
    scoped_item["ancestor_control_ids"] = ["scope_menu"]
    snapshot["menu_scopes"] = [{"provider": "windows_uia", "status": "ok", "scan_scope": "menu_subtree",
        "scan_complete": True, "truncated": False, "provider_tree_valid": True,
        "window": deepcopy(snapshot["window"]), "owned_popup_handle": 77,
        "source_menu_control_id": "scope_menu", "controls": [scoped_menu, scoped_item]}]
    return {"name": "Language", "control_type": kind,
        "container": {"name": "Settings menu", "control_type": "Menu"}}


def popup_native_scene(frame, monkeypatch, *, kind="MenuItem", defect=None):
    from app.agent.native_identity import WindowsNativeIdentityReader
    from app.core import window_manager as wm
    from tests.test_task_plan_dispatch_target import wrapper
    target = menu_snapshot(frame, kind)
    capture, snapshot = frame
    root = NS(element_info=NS(handle=11, process_id=22), parent=lambda: None)
    popup = NS(element_info=NS(handle=77, process_id=22), parent=lambda: None)
    parent = wrapper(snapshot["controls"][0], parent=popup)
    current = wrapper(snapshot["controls"][1], parent=parent)
    state = {"hit": 77, "owner": 11, "reads": 0, "visibility": [], "created": 123.0, "popup_pid": 22}
    if defect == "owner": state["owner"] = 99
    if defect == "occluded": state["hit"] = 88
    if defect == "popup_gone": state["hit"] = 0
    if defect == "pid": state["popup_pid"] = 99
    gui = NS(WindowFromPoint=lambda point: state["hit"],
        GetAncestor=lambda handle, mode: state["owner"] if mode == 3 else handle,
        IsChild=lambda *args: False, GetWindowText=lambda _: "",
        GetWindowRect=lambda handle: (110, 210, 350, 390) if defect != "popup_bbox" else (500, 500, 600, 600),
        GetClassName=lambda _: "QMenu")
    monkeypatch.setattr(wm, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(wm, "win32gui", gui)
    manager = wm.WindowManager()
    bound = NS(handle=11, process_id=22, title="Fixture", process_name="editor.exe",
        rect=NS(left=100, top=200, right=1000, bottom=800))
    manager.get_bound_window = lambda: bound
    manager._get_process_id = lambda handle: state["popup_pid"] if handle == 77 else 22
    manager._get_process_name = lambda _: "editor.exe"
    original_visibility = manager.validate_bound_point_visibility
    def visibility(**kwargs):
        state["visibility"].append(kwargs["expected_owned_popup_handle"])
        return original_visibility(**kwargs)
    manager.validate_bound_point_visibility = visibility
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 11, "process_id": 22,
        "process_create_time": 123.0, "executable_path": "c:/fixture/editor.exe"}
    # 使用生产 bound-only reader；只隔离底层进程属性，不假造任意 HWND 的身份。
    identity_reader = WindowsNativeIdentityReader(window_manager=manager,
        process_factory=lambda pid: NS(exe=lambda: "c:/fixture/editor.exe", create_time=lambda: state["created"]))
    def from_point(x, y):
        state["reads"] += 1
        if state["reads"] == 2 and defect == "second_popup": popup.element_info.handle = 78
        if state["reads"] == 1 and defect == "disappear_after_hit": state["hit"] = 11
        if state["reads"] == 1 and defect == "root_pid": bound.process_id = 99
        if state["reads"] == 1 and defect == "root_birth": state["created"] = 124.0
        if state["reads"] == 1 and defect == "popup_pid_after_hit": state["popup_pid"] = 99
        if defect == "container": parent.element_info.runtime_id = [42, 999]
        return current
    return target, root, parent, current, manager, identity, identity_reader.read_identity, from_point, state


def test_complete_current_scope_projects_popup_without_decoding_runtime_id(current_frame):
    from app.execution.task_plan_target import resolve_current_uia_target
    target = menu_snapshot(current_frame)
    value = resolve_current_uia_target(target, capture=current_frame[0], snapshot=current_frame[1])
    assert value["expected_owned_popup_handle"] == 77
    assert value["runtime_id"] == current_frame[1]["controls"][1]["runtime_id"]
    assert value["window_identity"]["handle"] == 11


@pytest.mark.parametrize("defect", ["incomplete", "truncated", "window", "duplicate_scope", "target_name",
    "target_type", "target_bbox", "menu_rid", "menu_type", "ancestor", "source", "bool_handle", "root_handle",
    "wrong_scope", "provider_failed", "graph_invalid", "errors", "bad_controls", "late_duplicate_rid",
    "menu_outside", "menu_not_containing", "menu_disabled"])
def test_inconsistent_matching_menu_scope_is_rejected(current_frame, defect):
    from app.execution.task_plan_target import resolve_current_uia_target
    target = menu_snapshot(current_frame)
    snapshot = current_frame[1]
    scope = snapshot["menu_scopes"][0]
    item, menu = scope["controls"][1], scope["controls"][0]
    if defect == "incomplete": scope["scan_complete"] = False
    elif defect == "truncated": scope["truncated"] = True
    elif defect == "window": scope["window"]["handle"] = 12
    elif defect == "duplicate_scope": snapshot["menu_scopes"].append(deepcopy(scope))
    elif defect == "target_name": item["name"] = "Other"
    elif defect == "target_type": item["control_type"] = "Button"
    elif defect == "target_bbox": item["bbox"]["x"] += 1
    elif defect == "menu_rid": menu["runtime_id"] = [42, 999]
    elif defect == "menu_type": menu["control_type"] = "Pane"
    elif defect == "ancestor": item["ancestor_control_ids"] = []
    elif defect == "source": scope["source_menu_control_id"] = "missing"
    elif defect == "bool_handle": scope["owned_popup_handle"] = True
    elif defect == "root_handle": scope["owned_popup_handle"] = 11
    elif defect == "wrong_scope": scope["scan_scope"] = "browser_chrome"
    elif defect == "provider_failed": scope["status"] = "unavailable"
    elif defect == "graph_invalid": scope["provider_tree_valid"] = False
    elif defect == "errors": scope["traversal_errors"] = ["provider_failure"]
    elif defect == "bad_controls": scope["controls"] = None
    elif defect == "late_duplicate_rid":
        duplicate = deepcopy(item)
        duplicate["control_id"] = "late"
        scope["controls"].append(duplicate)
    elif defect in {"menu_outside", "menu_not_containing"}:
        for value in (menu, snapshot["controls"][0]):
            value["bbox"]["x"] = -1 if defect == "menu_outside" else 300
            value["screen_bbox"]["x"] = value["bbox"]["x"] + 100
        target.pop("container")
    elif defect == "menu_disabled":
        menu["enabled"] = snapshot["controls"][0]["enabled"] = False
        target.pop("container")
    with pytest.raises(ValueError, match="task_plan_target_menu_scope_invalid"):
        resolve_current_uia_target(target, capture=current_frame[0], snapshot=snapshot)


@pytest.mark.parametrize("kind", ["Button", "Edit", "ComboBox", "TabItem", "Hyperlink"])
def test_other_types_never_receive_popup_projection(current_frame, kind):
    from app.execution.task_plan_target import resolve_current_uia_target
    target = menu_snapshot(current_frame, kind)
    value = resolve_current_uia_target(target, capture=current_frame[0], snapshot=current_frame[1])
    assert "expected_owned_popup_handle" not in value


def test_user_target_cannot_supply_owned_popup_handle():
    from app.execution.task_plan_target import validate_task_plan_control_target
    with pytest.raises(ValueError):
        validate_task_plan_control_target({"name": "Language", "control_type": "MenuItem", "expected_owned_popup_handle": 77})


def test_real_gated_owned_menu_click_keeps_root_coordinates(current_frame, monkeypatch):
    from tests.test_task_plan_dispatch_target import run_scene
    response, clicks, reads = run_scene(current_frame, monkeypatch, owned_popup=True, kind="MenuItem")
    assert response.success, response
    assert clicks == [(100, 100)] and reads == [(200, 300), (200, 300)]
    proof = response.data["result"]["task_plan_dispatch_target_check"]
    assert proof["expected_owned_popup_handle"] == 77
    assert proof["target"]["window_handle"] == 11
    assert proof["target"]["window_rect"] == [100, 200, 900, 600]


@pytest.mark.parametrize("defect", ["owner", "pid", "root_pid", "root_birth", "occluded", "popup_gone",
    "popup_bbox", "second_popup", "disappear_after_hit", "popup_pid_after_hit", "container", "missing_scope"])
def test_real_gated_popup_change_rejects_with_zero_click(current_frame, monkeypatch, defect):
    from tests.test_task_plan_dispatch_target import run_scene
    response, clicks, reads = run_scene(current_frame, monkeypatch, defect, owned_popup=True, kind="MenuItem")
    assert not response.success, response
    expected = {"root_pid": ("window_binding_changed", 1), "root_birth": ("process_identity_changed", 1),
        "second_popup": ("window_or_process_changed", 2), "container": ("container_changed", 1),
        "missing_scope": ("window_or_process_changed", 1)}
    reason, count = expected.get(defect, ("popup_visibility_changed",
        1 if defect in {"disappear_after_hit", "popup_pid_after_hit"} else 0))
    assert "native_control_hit_" + reason in response.error.details
    assert clicks == [] and len(reads) == count


def test_real_identity_reader_keeps_bound_only_contract(current_frame, monkeypatch):
    from app.agent.native_identity import WindowsNativeIdentityReader
    _, _, _, _, _, _, read_identity, _, _ = popup_native_scene(current_frame, monkeypatch)
    assert isinstance(read_identity.__self__, WindowsNativeIdentityReader)
    assert read_identity(11)["status"] == "observed"
    popup = read_identity(77)
    assert popup["status"] == "unavailable" and popup["reason"] == "binding_read_failed"


@pytest.mark.parametrize("kind", ["Button", "Edit"])
def test_non_menu_popup_does_not_relax_root_hit(current_frame, monkeypatch, kind):
    from tests.test_task_plan_dispatch_target import run_scene
    response, clicks, reads = run_scene(current_frame, monkeypatch, owned_popup=True, kind=kind)
    assert not response.success and clicks == []


@pytest.mark.parametrize("kind,popup", [("Button", 77), ("Edit", 77), ("MenuItem", True), ("MenuItem", 11)])
def test_dispatch_rejects_non_menu_or_invalid_popup_binding(current_frame, monkeypatch, kind, popup):
    from app.execution.task_plan_target import resolve_current_uia_target, validate_task_plan_dispatch_target
    target = menu_snapshot(current_frame, kind)
    capture = current_frame[0]
    capture["window_identity"]["process_create_time"] = 123.0
    value = resolve_current_uia_target(target, capture=capture, snapshot=current_frame[1])
    value["expected_owned_popup_handle"] = popup
    with pytest.raises(ValueError, match="task_plan_target_dispatch_binding_invalid"):
        validate_task_plan_dispatch_target(target, resolution=value, capture=capture, point=value["click_point"],
            window_manager=None, identity={"target_window_handle": 11, "process_id": 22, "process_create_time": 123.0})
