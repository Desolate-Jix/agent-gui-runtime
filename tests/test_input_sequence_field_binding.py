"""聚焦回执的当前 UIA 身份必须传至字段读取，不以屏幕点替代原字段。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace as NS

import pytest

from app.desktop_review import input_sequence as module


def focus(tmp_path):
    image = tmp_path / "recognition.png"
    image.write_bytes(b"synthetic-recognition-frame")
    size = {"width": 2560, "height": 1400}
    box = {"x": 116, "y": 103, "w": 246, "h": 24}
    action = {"source": "windows_uia.controls", "source_id": "field"}
    candidate = {"candidate_id": "selected", "role": "combobox", "element": {
        "bbox": box, "evidence": {"screen_inventory_action": action}}}
    raw = {"status": "ok", "scan_complete": True, "truncated": False,
        "window": {"handle": 11, "process_id": 22, "bbox": {"x": 0, "y": 0, "w": 2560, "h": 1400}},
        "controls": [{"control_id": "field", "runtime_id": [42, 9], "control_type": "ComboBox",
            "visible": True, "enabled": True, "patterns": ["Value", "Text"], "bbox": box}]}
    plan = {"image_path": str(image), "recommended_target": candidate,
        "candidate_result": {"recommended_candidate_id": "selected", "candidates": [deepcopy(candidate)]},
        "narrow_search_result": {"recommended_candidate_id": "selected", "results": [
            {"candidate_id": "selected", "refined_click_point": {"x": 189, "y": 115}}]},
        "parse_result": {"screen_reading": {"image_path": str(image), "image_size": size},
            "execute_fast_inventory": {"raw_uia_snapshot": raw}}}
    located = {"recognition_plan": plan, "selected_click_point": {"x": 189, "y": 115},
        "selected_click_point_coordinate_space": "capture_image_pixels",
        "live_capture": {"image_path": str(image), "window_size": size}}
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 11, "process_id": 22,
        "process_create_time": 123.0, "executable_path": "c:\\fixture.exe"}
    receipt = {"target_identity": identity, "capture": {"image_path": "different-before.png"},
        "target_window_geometry": {"coordinate_space": "screen_pixels", "rect_format": "ltrb",
            "rect": [-30, 40, 2530, 1440]}}
    return located, receipt, {"handle": 11, "process_id": 22}


def test_original_uia_identity_is_bound_to_recognition_capture_not_step_before(tmp_path):
    located, receipt, target = focus(tmp_path)
    binding = module._focus_field_binding(located, receipt, target)
    assert binding["runtime_id"] == [42, 9]
    assert binding["control_type"] == "ComboBox"
    assert binding["bbox"] == {"x": 116, "y": 103, "w": 246, "h": 24}
    assert binding["source_capture_sha256"] == sha256(b"synthetic-recognition-frame").hexdigest()
    assert binding["window_rect"] == [-30, 40, 2560, 1400]


@pytest.mark.parametrize("fault", ["missing_raw", "wrong_runtime", "duplicate", "wrong_point", "another_field",
    "stale_capture", "wrong_window", "wrong_process", "wrong_sha", "wrong_bbox", "incomplete"])
def test_declared_uia_failure_never_falls_back_to_unbound_point(tmp_path, fault):
    located, receipt, target = focus(tmp_path)
    plan = located["recognition_plan"]
    raw = plan["parse_result"]["execute_fast_inventory"]["raw_uia_snapshot"]
    if fault == "missing_raw": raw["controls"] = []
    elif fault == "wrong_runtime": raw["controls"][0]["runtime_id"] = [True]
    elif fault == "duplicate": raw["controls"].append(deepcopy(raw["controls"][0]))
    elif fault == "wrong_point": located["selected_click_point"] = {"x": 189, "y": 140}
    elif fault == "another_field": plan["candidate_result"]["recommended_candidate_id"] = "another"
    elif fault == "stale_capture": located["live_capture"]["image_path"] = str(tmp_path / "other.png")
    elif fault == "wrong_window": raw["window"]["handle"] = 12
    elif fault == "wrong_process": raw["window"]["process_id"] = 23
    elif fault == "wrong_sha": located["live_capture"]["sha256"] = "a"*64
    elif fault == "wrong_bbox": raw["controls"][0]["bbox"] = {"x": 200, "y": 103, "w": 100, "h": 24}
    elif fault == "incomplete": raw["scan_complete"] = False
    with pytest.raises(module.InputSequenceInterrupted):
        module._focus_field_binding(located, receipt, target)


def test_pixel_only_keeps_unbound_contract(tmp_path):
    located, receipt, target = focus(tmp_path)
    located["recognition_plan"]["recommended_target"]["element"]["evidence"] = {"vista_direct_point": {}}
    assert module._focus_field_binding(located, receipt, target) is None
    assert module._focus_field_binding({}, receipt, target) is None


@pytest.mark.parametrize("fault", ["missing", "space", "format", "bool", "size", "inverted", "uia_origin"])
def test_declared_uia_requires_unambiguous_native_screen_geometry(tmp_path, fault):
    located, receipt, target = focus(tmp_path)
    geometry = receipt["target_window_geometry"]
    if fault == "missing": del receipt["target_window_geometry"]
    elif fault == "space": geometry["coordinate_space"] = "capture_image_pixels"
    elif fault == "format": geometry["rect_format"] = "xywh"
    elif fault == "bool": geometry["rect"][0] = False
    elif fault == "size": geometry["rect"][2] += 1
    elif fault == "inverted": geometry["rect"][2] = -31
    else: located["recognition_plan"]["parse_result"]["execute_fast_inventory"]["raw_uia_snapshot"]["window"]["bbox"]["x"] = -30
    with pytest.raises(module.InputSequenceInterrupted, match="input_field_binding_invalid"):
        module._focus_field_binding(located, receipt, target)


@pytest.mark.parametrize("use_binding,post_input", [(True, False), (True, True), (False, False)])
@pytest.mark.parametrize("origin", [(-30, 40), (100, 100), (0, 0)])
def test_bound_reader_receives_original_identity_and_bbox(tmp_path, monkeypatch, use_binding, post_input, origin):
    from app.agent import native_identity, windows_text_field_reader
    located, receipt, target = focus(tmp_path)
    left, top = origin
    receipt["target_window_geometry"]["rect"] = [left, top, left + 2560, top + 1400]
    binding = module._focus_field_binding(located, receipt, target)
    captured = []
    manager = NS(bind_window_by_handle=lambda h: NS(rect=NS(left=left, top=top, right=left+2560, bottom=top+1400)))
    monkeypatch.setattr(native_identity, "WindowsNativeIdentityReader", lambda **kw:
        NS(read_identity=lambda h: receipt["target_identity"]))
    monkeypatch.setattr(windows_text_field_reader, "WindowsTextFieldReader", lambda **kw:
        NS(read_field=lambda **args: captured.append(args) or "snapshot"))
    coordinator = NS(_windows=lambda: manager, _owner=NS(call=lambda fn: fn()))
    assert module._read_field(coordinator, target, located["selected_click_point"],
        {"sha256": "b"*64, "window_size": {"width": 2560, "height": 1400}}, "field-id",
        receipt["target_identity"], field_binding=binding if use_binding else None, post_input=post_input) == "snapshot"
    if use_binding:
        assert captured[0]["expected_runtime_id"] == (42, 9)
        assert captured[0]["expected_control_type"] == "ComboBox"
        assert captured[0]["target_bbox"] == (116, 103, 246, 24)
        assert captured[0].get("allow_post_input_geometry_rebind", False) is post_input
    else:
        assert "expected_runtime_id" not in captured[0] and "expected_control_type" not in captured[0]
        assert captured[0]["target_bbox"] == (189, 115, 1, 1)
    assert captured[0]["click_point"] == (189, 115)
    assert captured[0]["window_rect"] == (left, top, 2560, 1400)
    assert located["recognition_plan"]["parse_result"]["execute_fast_inventory"]["raw_uia_snapshot"]["window"]["bbox"] == {
        "x": 0, "y": 0, "w": 2560, "h": 1400}


@pytest.mark.parametrize("post_input", [False, True])
def test_native_window_movement_after_focus_still_rejects(tmp_path, monkeypatch, post_input):
    from app.agent import native_identity, windows_text_field_reader
    located, receipt, target = focus(tmp_path)
    binding = module._focus_field_binding(located, receipt, target)
    reads = []
    manager = NS(bind_window_by_handle=lambda h: NS(rect=NS(left=100, top=100, right=2660, bottom=1500)))
    monkeypatch.setattr(native_identity, "WindowsNativeIdentityReader", lambda **kw:
        NS(read_identity=lambda h: receipt["target_identity"]))
    monkeypatch.setattr(windows_text_field_reader, "WindowsTextFieldReader", lambda **kw:
        NS(read_field=lambda **args: reads.append(args)))
    coordinator = NS(_windows=lambda: manager, _owner=NS(call=lambda fn: fn()))
    with pytest.raises(module.InputSequenceInterrupted, match="input_field_binding_changed"):
        module._read_field(coordinator, target, located["selected_click_point"],
            {"sha256": "b"*64, "window_size": {"width": 2560, "height": 1400}}, "field-id",
            receipt["target_identity"], field_binding=binding, post_input=post_input)
    assert reads == []


def test_sequence_preserves_same_field_binding_across_focus_and_content_reads(tmp_path, monkeypatch):
    from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
    located, receipt, target = focus(tmp_path)
    calls, reads, post_modes, keyboard_targets = [], [], [], []
    def execute(**kwargs):
        calls.append(kwargs["operation"])
        if kwargs["operation"] in {"type_text", "press_key"}:
            keyboard_targets.append(kwargs.get("keyboard_target"))
        data = {**located, "execution_path": {"action_executed": True}}
        if kwargs["operation"] == "press_key": data = {"pressed": True}
        return {**receipt, "phase": "returned", "response": {"success": True, "data": {"result": data}
                if kwargs["operation"] != "press_key" else data},
            "observation": {"capture": {"sha256": "b"*64, "window_size": {"width": 2560, "height": 1400}}}}
    def read(coordinator, target, point, capture, field_id, expected_identity, *, field_binding=None, post_input=False):
        reads.append(field_binding)
        post_modes.append(post_input)
        identity = TextFieldIdentity(field_id, 11, 22, 123.0, (42, 9), (-30,40,2560,1400),
            (116,103,326 if post_input else 246,24))
        return TextFieldSnapshot(identity, capture["sha256"], str(len(reads)), len(reads), "uia_value",
            "" if len(reads) == 1 else "museum", None)
    monkeypatch.setattr(module, "_read_field", read)
    result = module.run_input_sequence(NS(execute_local_step=execute), target,
        {"field_goal": "Click the search input field in the webpage", "text": "museum", "submit_search": True})
    assert result["status"] == "completed"
    assert len(reads) == 2 and reads[0] is not None and reads[0] == reads[1]
    assert reads[0]["runtime_id"] == [42, 9]
    assert post_modes == [False, True]
    assert result["field_binding"]["bbox"] == {"x": 116, "y": 103, "w": 246, "h": 24}
    assert result["input_check"]["geometry_change"] == {"before_bbox": [116,103,246,24],
        "after_bbox": [116,103,326,24], "coordinate_space": "capture_image_pixels", "read_only": True}
    assert calls == ["execute_recognition_plan", "type_text", "press_key"]
    assert all(target is not None for target in keyboard_targets)
    assert keyboard_targets[0].snapshot.value == ""
    assert keyboard_targets[0].snapshot.identity.control_bbox == (116,103,246,24)
    assert keyboard_targets[1].snapshot.value == "museum"
    assert keyboard_targets[1].snapshot.identity.control_bbox == (116,103,326,24)
