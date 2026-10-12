"""等待后只读复核字段，不能重新消费或更新原绑定。"""
from copy import deepcopy
from hashlib import sha256

import pytest

from app.agent.windows_text_field_reader import TextFieldReadError
from app.core import local_text_focus as focus


POINT = {"x": 40, "y": 45}
BINDING = {"runtime_id": [42, 7], "control_type": "Edit", "bbox": [20, 30, 100, 40],
    "window_handle": 10, "process_id": 20, "process_create_time": 123.0,
    "window_rect": [0, 0, 600, 500]}


@pytest.fixture
def bound(monkeypatch):
    manager = object()
    target = focus.LocalTextFocusTarget(10, 20, expected_label="Search")
    monkeypatch.setattr(focus, "require_local_operator_input", lambda _: True)
    monkeypatch.setattr(focus, "probe_local_focus_target", lambda *args, **kwargs: deepcopy(BINDING))
    with focus.local_text_focus_scope(target):
        focus.check_local_text_focus(dict(POINT), manager)
        yield manager, target


def test_no_scope_does_not_probe(monkeypatch):
    monkeypatch.setattr(focus, "probe_local_focus_target", lambda *a, **kw: pytest.fail("unexpected probe"))
    assert focus.revalidate_local_text_focus(POINT, object()) is None


def test_revalidation_preserves_claim_and_original_binding(bound):
    manager, target = bound
    original = target.binding
    result = focus.revalidate_local_text_focus(POINT, manager)
    assert result == {"status": "revalidated", "control_type": "Edit", "runtime_id": [42, 7],
                      "declared_label_verified": True}
    assert target.binding is original and original == BINDING
    assert focus.has_local_text_focus() is False
    result["runtime_id"].append(99)
    assert target.binding == BINDING
    assert focus.revalidate_local_text_focus(POINT, manager)["runtime_id"] == [42, 7]
    with pytest.raises(ValueError, match="scope unavailable"):
        focus.check_local_text_focus(POINT, manager)


@pytest.mark.parametrize("field,value", [("runtime_id", [42, 8]), ("control_type", "ComboBox"),
    ("bbox", [21, 30, 100, 40]), ("window_handle", 11), ("process_id", 21),
    ("process_create_time", 124.0), ("window_rect", [1, 0, 600, 500])])
def test_any_original_binding_drift_is_rejected(bound, monkeypatch, field, value):
    manager, target = bound
    original = target.binding
    changed = deepcopy(BINDING)
    changed[field] = value
    monkeypatch.setattr(focus, "probe_local_focus_target", lambda *a, **kw: changed)
    with pytest.raises(TextFieldReadError, match="text_field_expected_identity_changed"):
        focus.revalidate_local_text_focus(POINT, manager)
    assert target.binding is original and original == BINDING


@pytest.mark.parametrize("fault", ["inactive", "wrong_owner", "unclaimed", "missing_binding"])
def test_unavailable_scope_cannot_revalidate(bound, monkeypatch, fault):
    manager, target = bound
    scope = focus._SCOPE.get()
    if fault == "inactive":
        scope["active"] = False
    elif fault == "wrong_owner":
        scope["owner"] += 1
    elif fault == "unclaimed":
        scope["claimed"] = False
    else:
        target.binding = None
    monkeypatch.setattr(focus, "probe_local_focus_target", lambda *a, **kw: pytest.fail("unexpected probe"))
    with pytest.raises(ValueError, match="scope unavailable"):
        focus.revalidate_local_text_focus(POINT, manager)


@pytest.mark.parametrize("point", [(40, 45), {"x": 40}, {"x": True, "y": 45},
                                     {"x": 40.0, "y": 45}, {"x": 40, "y": 45, "z": 0}])
def test_invalid_point_is_rejected_before_probe(bound, monkeypatch, point):
    manager, _ = bound
    monkeypatch.setattr(focus, "probe_local_focus_target", lambda *a, **kw: pytest.fail("unexpected probe"))
    with pytest.raises(ValueError, match="point invalid"):
        focus.revalidate_local_text_focus(point, manager)


def test_probe_failure_keeps_original_claim_and_binding(bound, monkeypatch):
    manager, target = bound
    def reject(*args, **kwargs):
        raise TextFieldReadError("text_field_target_not_writable")
    monkeypatch.setattr(focus, "probe_local_focus_target", reject)
    with pytest.raises(TextFieldReadError, match="text_field_target_not_writable"):
        focus.revalidate_local_text_focus(POINT, manager)
    assert target.binding == BINDING and focus.has_local_text_focus() is False


def composite(target, tmp_path):
    path = tmp_path / "source.png"
    path.write_bytes(b"original source")
    target.composite_binding = {"point": dict(POINT), "capture_id": str(path),
        "screenshot_sha256": sha256(path.read_bytes()).hexdigest(),
        "binding": deepcopy(BINDING), "parent": {"runtime_id": [42, 1]}}
    return path


def test_composite_revalidation_keeps_original_ancestor_and_label(bound, monkeypatch, tmp_path):
    manager, target = bound
    composite(target, tmp_path)
    def probe(actual_manager, handle, pid, point, *, expected_label, expected_ancestor):
        assert (actual_manager, handle, pid, point) == (manager, 10, 20, (40, 45))
        assert expected_label == "Search" and expected_ancestor == {"runtime_id": [42, 1]}
        return deepcopy(BINDING)
    monkeypatch.setattr(focus, "probe_local_focus_target", probe)
    assert focus.revalidate_local_text_focus(POINT, manager)["status"] == "revalidated"
    assert target.binding == BINDING


@pytest.mark.parametrize("fault", ["image_before", "point", "binding"])
def test_composite_original_evidence_drift_is_rejected(bound, monkeypatch, tmp_path, fault):
    manager, target = bound
    path = composite(target, tmp_path)
    if fault == "image_before":
        path.write_bytes(b"changed source")
    elif fault == "point":
        target.composite_binding["point"]["x"] += 1
    else:
        target.composite_binding["binding"]["runtime_id"] = [42, 8]
    with pytest.raises((ValueError, TextFieldReadError)):
        focus.revalidate_local_text_focus(POINT, manager)
    assert target.binding == BINDING


def test_composite_source_is_rehashed_after_probe(bound, monkeypatch, tmp_path):
    manager, target = bound
    path = composite(target, tmp_path)
    def probe(*args, **kwargs):
        path.write_bytes(b"changed during probe")
        return deepcopy(BINDING)
    monkeypatch.setattr(focus, "probe_local_focus_target", probe)
    with pytest.raises(ValueError, match="composite_field_source_capture_changed"):
        focus.revalidate_local_text_focus(POINT, manager)
    assert target.binding == BINDING and focus.has_local_text_focus() is False
