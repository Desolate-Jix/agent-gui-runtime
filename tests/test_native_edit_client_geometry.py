from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.core.window_manager import BoundWindow, WindowRect
from app.operation.screen_reading import uia_provider as module


class Backend:
    def __init__(self):
        self.root = 10
        self.pid = 42
        self.runtime_id = (42, 11)
        self.class_name = "Edit"
        self.client = (0, 0, 1448, 897)
        self.origin = (102, 203)
        self.in_physical_context = False
        self.error = None

    @contextmanager
    def physical_pixels(self):
        self.in_physical_context = True
        try:
            yield
        finally:
            self.in_physical_context = False

    def identity(self, handle):
        assert self.in_physical_context
        return self.root, self.pid, self.class_name, self.runtime_id

    def client_rect(self, handle):
        assert self.in_physical_context
        if self.error:
            raise self.error
        return self.client

    def to_screen(self, handle, point):
        assert self.in_physical_context
        return self.origin[0] + point[0], self.origin[1] + point[1]


@pytest.fixture
def case(monkeypatch):
    backend = Backend()
    monkeypatch.setattr(module, "_native_edit_geometry_backend", lambda: backend, raising=False)
    bound = BoundWindow(10, "test", 42, "notepad.exe", WindowRect(100, 200, 1571, 1142), True)
    info = SimpleNamespace(handle=11, runtime_id=(42, 11))
    bbox = module.UIABBox(100, 200, 1471, 920)
    return backend, bound, info, bbox


def collect(case, **changes):
    backend, bound, info, bbox = case
    return module._native_edit_client_geometry(info, bound=bound, screen_bbox=bbox,
                                               control_type=changes.get("control_type", "Edit"))


def test_client_rect_excludes_native_scrollbars_and_maps_pixels(case):
    result = collect(case)
    assert result["status"] == "ok"
    assert result["bbox"] == {"x": 2, "y": 3, "w": 1448, "h": 897}
    assert result["screen_bbox"] == {"x": 102, "y": 203, "w": 1448, "h": 897}
    assert result["coordinate_space"] == "capture_image_pixels"
    assert result["source"] == "win32_edit_client_rect"
    assert result["native_window_handle"] == 11
    assert not case[0].in_physical_context


def test_negative_monitor_origin_is_not_scaled_again(case):
    case[1].rect = WindowRect(-1800, -100, -329, 842)
    case[0].origin = (-1798, -97)
    case = (*case[:3], module.UIABBox(-1800, -100, 1471, 920))
    assert collect(case)["bbox"] == {"x": 2, "y": 3, "w": 1448, "h": 897}


@pytest.mark.parametrize("field,value,reason", [
    ("root", 99, "native_window_root_mismatch"),
    ("pid", 99, "native_window_process_mismatch"),
    ("runtime_id", (42, 99), "native_element_identity_mismatch"),
    ("class_name", "Chrome_RenderWidgetHostHWND", "not_native_edit_class"),
    ("client", (0, 0, 0, 897), "invalid_client_geometry"),
    ("origin", (99, 203), "client_geometry_outside_control"),
])
def test_invalid_optional_geometry_does_not_invent_bbox(case, field, value, reason):
    setattr(case[0], field, value)
    result = collect(case)
    assert result["status"] == "unavailable"
    assert result["reason"] == reason
    assert "bbox" not in result


def test_native_handle_zero_never_uses_wrapper_ancestor(case):
    case[2].handle = 0
    assert collect(case)["reason"] == "native_window_handle_unavailable"


def test_non_edit_is_not_applicable(case):
    assert collect(case, control_type="Button")["status"] == "not_applicable"


def test_winerror_reported_without_discarding_uia(case):
    error = OSError("access denied")
    error.winerror = 5
    case[0].error = error
    result = collect(case)
    assert result["reason"] == "native_client_geometry_failed"
    assert result["winerror"] == 5
    assert "bbox" not in result
    assert not case[0].in_physical_context


def test_virtual_element_cannot_borrow_ancestor_identity(case):
    case[2].runtime_id = None
    assert collect(case)["reason"] == "native_element_identity_unavailable"


def test_uia_control_serializes_optional_geometry(case):
    result = collect(case)
    control = module.UIAControl("id", None, "Edit", None, "Edit", case[3], case[3],
                                True, True, ("Value",), native_client_geometry=result)
    assert control.to_dict()["native_client_geometry"] == result


def test_wrapper_collection_keeps_original_uia_bbox_and_adds_client(case):
    backend, bound, info, bbox = case
    info.control_type = "Edit"
    info.name = ""
    wrapper = SimpleNamespace(element_info=info,
        rectangle=lambda: SimpleNamespace(left=100, top=200, right=1571, bottom=1120),
        is_enabled=lambda: True, is_visible=lambda: True, iface_value=True)
    result = module.WindowsUIAProvider()._control_from_wrapper(wrapper, bound=bound, index=0).to_dict()
    assert result["bbox"] == {"x": 0, "y": 0, "w": 1471, "h": 920}
    assert result["native_client_geometry"]["bbox"] == {"x": 2, "y": 3, "w": 1448, "h": 897}


@pytest.mark.parametrize("native_class", ["RichEdit20W", "RICHEDIT50W", "RichEditD2DPT"])
def test_native_richedit_supported_with_same_identity(case, native_class):
    case[0].class_name = native_class
    assert collect(case)["status"] == "ok"


def test_identity_change_during_collection_rejects_geometry(case):
    backend = case[0]
    original = backend.to_screen
    def move(handle, point):
        backend.pid = 99
        return original(handle, point)
    backend.to_screen = move
    assert collect(case)["reason"] == "native_element_identity_changed"


def test_client_partially_outside_capture_is_not_clipped_into_fake_region(case):
    case[1].rect = WindowRect(200, 200, 1571, 1142)
    result = collect(case)
    assert result["reason"] == "client_geometry_outside_capture"
    assert "bbox" not in result
