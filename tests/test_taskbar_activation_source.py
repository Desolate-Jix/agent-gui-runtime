from app.desktop_review.taskbar_activation_source import build_taskbar_activation_evidence


def test_builder_handles_negative_desktop_and_negative_runtime_id():
    data = build_taskbar_activation_evidence(
        captured_at_monotonic=1.0, capture_id="cap", image_path="x.png", image_sha256="a"*64,
        desktop_rect={"left": -100, "top": -20, "width": 300, "height": 200},
        taskbar={"handle": 1, "class_name": "Shell_TrayWnd", "pid": 2, "exe": r"C:\Windows\explorer.exe", "create_time": 1.0, "screen_rect": {"left": -100, "top": 140, "width": 300, "height": 40}},
        destination={"handle": 9, "pid": 3, "exe": r"C:\demo.exe", "create_time": 2.0, "title": "Demo"},
        source_foreground={"handle": 8, "pid": 4, "exe": r"C:\source.exe", "create_time": 3.0},
        selected_button={"control_id": "b", "runtime_id": [42, -2147483647], "name": "Demo", "automation_id": "d", "bbox": {"x": 10, "y": 0, "w": 30, "h": 40}, "screen_bbox": {"x": -90, "y": 140, "w": 30, "h": 40}, "enabled": True, "visible": True, "patterns": ["Invoke"], "ancestor_control_ids": ["toolbar", "taskbar"], "toolbar_control_id": "toolbar", "toolbar_runtime_id": [42, 1], "toolbar_handle": 2, "toolbar_class_name": "MSTaskListWClass", "point_visibility": {"kind": "taskbar_button", "hit_handle": 1, "hit_root_handle": 1, "owner_handle": 1}},
    )
    assert data["window_point"] == [25, 20]
    assert data["screen_point"] == [-75, 160]


def test_builder_rejects_missing_ancestor_or_non_taskbar():
    kwargs = dict(captured_at_monotonic=1.0, capture_id="cap", image_path="x.png", image_sha256="a"*64, desktop_rect={"left": 0, "top": 0, "width": 100, "height": 100}, taskbar={"handle": 1, "class_name": "Fake", "pid": 2, "exe": r"C:\x.exe", "create_time": 1.0, "screen_rect": {"left": 0, "top": 60, "width": 100, "height": 40}}, destination={"handle": 9, "pid": 3, "exe": r"C:\demo.exe", "create_time": 2.0, "title": "Demo"}, source_foreground={"handle": 8, "pid": 4, "exe": r"C:\source.exe", "create_time": 3.0}, selected_button={"control_id": "b", "runtime_id": [1], "name": "Demo", "automation_id": "d", "bbox": {"x": 10, "y": 0, "w": 30, "h": 40}, "screen_bbox": {"x": 10, "y": 60, "w": 30, "h": 40}, "enabled": True, "visible": True, "patterns": ["Invoke"], "ancestor_control_ids": [], "toolbar_control_id": "toolbar", "toolbar_runtime_id": [2]})
    import pytest
    with pytest.raises(ValueError):
        build_taskbar_activation_evidence(**kwargs)
