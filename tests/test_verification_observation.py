from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.learning_memory import verification_observation as module


IDENTITY = {"handle": 91, "process_id": 42, "process_create_time": 17.5}
SELECTOR = {"control_type": "Text", "automation_id": "detailText"}


def captured(capture_id, *, name="Current detail", controls=True):
    frame = {"capture_id": capture_id, "sha256": "a" * 64, "image_path": "current.png",
             "image_size": {"width": 800, "height": 600}, "window_identity": deepcopy(IDENTITY),
             "window_rect": [0, 0, 800, 600], "application": {"executable_name": "fixture.exe"}}
    control = {"control_id": "uia-7", "name": name, "control_type": "Text", "automation_id": "detailText",
               "bbox": {"x": 20, "y": 30, "w": 200, "h": 30}, "runtime_id": [42, 7], "visible": True, "enabled": True,
               "ancestor_control_ids": ["root"]}
    snapshot = {"provider": "windows_uia", "status": "ok", "scan_scope": "bound_window",
                "scan_complete": True, "truncated": False, "provider_tree_valid": True,
                "window": {"handle": 91, "process_id": 42}, "controls": [control] if controls else []}
    return frame, {"uia": {"status": "ok", "capture_id": capture_id, "window_identity": deepcopy(IDENTITY), "snapshot": snapshot}}


def fake_captures(monkeypatch, before=None, after=None):
    rows = iter([before or captured("before"), after or captured("after")])
    calls = []
    def capture(coordinator, handle, pid, *, recipe):
        calls.append((handle, pid, recipe))
        return next(rows)
    monkeypatch.setattr(module, "capture_memory_observation", capture)
    return calls


def coordinator():
    return SimpleNamespace(_windows=lambda: object())


def test_visible_text_is_unique_current_name_with_bracketed_capture(monkeypatch):
    calls = fake_captures(monkeypatch)
    result = module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                          selector=SELECTOR, method="visible_text")
    assert result["status"] == "ok"
    assert result["values"] == {"text": "Current detail"}
    assert result["capture_sha256"] == "a" * 64
    assert result["evidence"]["selected_control"]["control_id"] == "uia-7"
    assert len(calls) == 2
    assert all(call[2]["scope"]["anchors"][0]["kind"] == "uia" for call in calls)


def test_presence_absence_only_on_complete_bound_tree(monkeypatch):
    fake_captures(monkeypatch, captured("before", controls=False), captured("after", controls=False))
    result = module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                          selector=SELECTOR, method="presence")
    assert result["status"] == "ok"
    assert result["values"] == {"target_present": False}
    first = captured("before", controls=False)
    second = captured("after", controls=False)
    second[1]["uia"]["snapshot"]["scan_complete"] = False
    fake_captures(monkeypatch, first, second)
    assert module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                        selector=SELECTOR, method="presence")["status"] == "unavailable"


def test_duplicate_name_or_geometry_drift_unavailable(monkeypatch):
    first = captured("before")
    first[1]["uia"]["snapshot"]["controls"].append({**first[1]["uia"]["snapshot"]["controls"][0], "control_id": "uia-8"})
    fake_captures(monkeypatch, first, captured("after"))
    assert module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                        selector=SELECTOR, method="visible_text")["reason"] == "control_ambiguous"
    second = captured("after")
    second[1]["uia"]["snapshot"]["controls"][0]["bbox"]["x"] = 40
    fake_captures(monkeypatch, captured("before"), second)
    assert module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                        selector=SELECTOR, method="visible_text")["reason"] == "target_changed_between_reads"


def test_uia_value_reads_exact_bound_target_geometry(monkeypatch):
    first = captured("before")
    second = captured("after")
    for pair in (first, second):
        control = pair[1]["uia"]["snapshot"]["controls"][0]
        control["control_type"] = "Edit"
        control["automation_id"] = "field"
    fake_captures(monkeypatch, first, second)
    calls = []
    class Reader:
        def __init__(self, **kwargs):
            pass
        def read_field(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(capture_id="before", source="uia_value", value="fresh",
                                   identity=SimpleNamespace(target_field_id="uia-7", runtime_id=(42, 7),
                                                            control_bbox=(20, 30, 200, 30), window_rect=(0, 0, 800, 600),
                                                            window_handle=91, process_id=42, process_create_time=17.5))
    monkeypatch.setattr(module, "WindowsTextFieldReader", Reader)
    result = module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                          selector={"control_type": "Edit", "automation_id": "field"}, method="uia_value")
    assert result["status"] == "ok"
    assert result["values"] == {"field_value": "fresh"}
    assert calls[0]["expected_runtime_id"] == (42, 7)
    assert calls[0]["window_rect"] == (0, 0, 800, 600)
    assert calls[0]["target_bbox"] == (20, 30, 200, 30)
    assert calls[0]["click_point"] == (120, 45)
    assert calls[0]["require_keyboard_focus"] is False


def test_uia_value_identity_failure_is_unavailable_without_input(monkeypatch):
    first = captured("before")
    second = captured("after")
    for pair in (first, second):
        pair[1]["uia"]["snapshot"]["controls"][0]["control_type"] = "Edit"
    fake_captures(monkeypatch, first, second)
    from app.agent.windows_text_field_reader import TextFieldReadError
    class Reader:
        def __init__(self, **kwargs):
            pass
        def read_field(self, **kwargs):
            raise TextFieldReadError("text_field_expected_identity_changed")
    monkeypatch.setattr(module, "WindowsTextFieldReader", Reader)
    result = module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                          selector={"control_type": "Edit"}, method="uia_value")
    assert result["status"] == "unavailable"
    assert result["reason"] == "text_field_expected_identity_changed"


def test_capture_hash_change_or_control_outside_current_image_is_unavailable(monkeypatch):
    after = captured("after")
    after[0]["sha256"] = "b" * 64
    fake_captures(monkeypatch, captured("before"), after)
    result = module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                          selector=SELECTOR, method="visible_text")
    assert result["reason"] == "frame_changed_between_reads"
    first = captured("before")
    first[1]["uia"]["snapshot"]["controls"][0]["bbox"]["x"] = 790
    fake_captures(monkeypatch, first, captured("after"))
    result = module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                          selector=SELECTOR, method="visible_text")
    assert result["reason"] == "control_bbox_invalid"


def image_captures(tmp_path, *, change=(5, 100), controls=True):
    from hashlib import sha256
    from PIL import Image
    pairs = [captured("before", controls=controls), captured("after", controls=controls)]
    for index, pair in enumerate(pairs):
        image = Image.new("RGB", (800, 600), "white")
        if index:
            image.putpixel(change, (0, 0, 0))
        path = tmp_path / (pair[0]["capture_id"] + ".png")
        image.save(path)
        pair[0]["image_path"] = str(path)
        pair[0]["sha256"] = sha256(path.read_bytes()).hexdigest()
    return pairs


def test_unrelated_blink_preserves_current_unique_target_read(monkeypatch, tmp_path):
    before, after = image_captures(tmp_path)
    fake_captures(monkeypatch, before, after)
    result = module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                          selector=SELECTOR, method="visible_text")
    assert result["status"] == "ok"
    assert result["values"] == {"text": "Current detail"}
    assert result["capture_sha256"] == after[0]["sha256"]
    evidence = result["evidence"]
    assert evidence["changed_frame_fields"] == ["sha256"]
    assert evidence["before_frame"] == before[0]
    assert evidence["after_frame"] == after[0]
    assert evidence["visual_stability"]["scope"] == "selected_control"
    assert evidence["visual_stability"]["matched"] is True
    assert evidence["visual_stability"]["bbox"] == {"x": 20, "y": 30, "w": 200, "h": 30}
    assert evidence["visual_stability"]["before_sha256"] == evidence["visual_stability"]["after_sha256"]


@pytest.mark.parametrize("variant", ["target_pixels", "window", "geometry", "application", "control", "duplicate", "incomplete", "tampered", "absent"])
def test_scope_check_does_not_accept_changed_or_unproven_targets(monkeypatch, tmp_path, variant):
    before, after = image_captures(tmp_path, change=(21, 31) if variant == "target_pixels" else (5, 100),
                                   controls=variant != "absent")
    if variant == "window":
        after[0]["window_identity"]["process_create_time"] += 1
    elif variant == "geometry":
        after[0]["window_rect"] = [1, 0, 801, 600]
    elif variant == "application":
        after[0]["application"]["executable_name"] = "other.exe"
    elif variant == "control":
        after[1]["uia"]["snapshot"]["controls"][0]["runtime_id"] = [42, 8]
    elif variant == "duplicate":
        snapshot = after[1]["uia"]["snapshot"]
        snapshot["controls"].append({**snapshot["controls"][0], "control_id": "uia-8"})
    elif variant == "incomplete":
        after[1]["uia"]["snapshot"]["scan_complete"] = False
    elif variant == "tampered":
        from pathlib import Path
        Path(before[0]["image_path"]).write_bytes(b"changed after capture")
    fake_captures(monkeypatch, before, after)
    result = module.read_step_observation(coordinator(), target={"handle": 91, "process_id": 42},
                                          selector=SELECTOR, method="presence" if variant == "absent" else "visible_text")
    assert result["status"] == "unavailable"
    assert result["values"] == {}
