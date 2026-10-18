from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

import app.core.verifier as verifier_module
from app.gate.scroll_evidence import measure_scroll_spatial_evidence


@pytest.fixture
def capture_runtime(tmp_path, monkeypatch):
    bound = SimpleNamespace(handle=42, title="fixture", is_active=True, process_id=12,
                            rect=SimpleNamespace(left=10, top=10, right=210, bottom=110))
    fact = {
        "contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 42, "process_id": 12,
        "process_create_time": 123.0, "executable_path": "c:\\fixture\\app.exe",
    }
    state = SimpleNamespace(bound=bound, fact=fact, after_capture=None, calls=[], changes=[])

    def capture(**kwargs):
        state.calls.append(kwargs)
        path = tmp_path / f"capture-{len(state.calls)}.png"
        image = Image.new("RGB", (200, 100), "white")
        for box in state.changes:
            ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
        if state.after_capture:
            state.after_capture()
        return {"image_path": str(path), "image_width": 200, "image_height": 100,
                "window_size": {"width": 200, "height": 100}, "roi": None, "roi_adjusted": False}

    monkeypatch.setattr(verifier_module, "VERIFICATION_DIR", tmp_path)
    monkeypatch.setattr(verifier_module, "build_verification_image_path", lambda **kwargs: tmp_path / "diff.png")
    monkeypatch.setattr(verifier_module, "window_manager", SimpleNamespace(get_bound_window=lambda: state.bound))
    monkeypatch.setattr(verifier_module, "screenshot_service", SimpleNamespace(capture_window=capture))
    state.reader = SimpleNamespace(read_identity=lambda handle: deepcopy(state.fact))
    return state


def test_public_pre_post_captures_supply_real_hashes_freshness_and_identity_without_focus(capture_runtime):
    runtime = verifier_module.Verifier(native_identity_reader=capture_runtime.reader)
    before = runtime.capture_pre_action_state(action_name="scroll_down", capture_scope_evidence=True)
    verified = runtime.verify_action("scroll_down", before_state=before, capture_scope_evidence=True, wait_ms=0)
    after = verified["after"]
    assert before["capture_status"] == after["capture_status"] == "observed"
    assert verified["verified"] is None
    assert before["capture_id"] != after["capture_id"]
    assert before["captured_at_ns"] < after["capture_started_ns"]
    from pathlib import Path
    assert before["image_sha256"] == sha256(Path(before["image_path"]).read_bytes()).hexdigest()
    assert before["native_identity"] == after["native_identity"] == capture_runtime.fact
    assert [call["focus_window"] for call in capture_runtime.calls] == [False, False]
    result = measure_scroll_spatial_evidence(before=before, after=after, target_bbox={"x": 0, "y": 0, "width": 100, "height": 100}, target_container_id="pane")
    assert result["available"] is True
    assert result["status"] == "no_visual_change"


@pytest.mark.parametrize("change,reason", [("process", "capture_identity_changed"), ("geometry", "capture_geometry_changed"), ("binding", "capture_identity_changed")])
def test_identity_or_geometry_drift_during_capture_is_unavailable(capture_runtime, change, reason):
    def drift():
        if change == "process":
            capture_runtime.fact["process_create_time"] = 124.0
        elif change == "geometry":
            capture_runtime.bound.rect.left = 11
        else:
            capture_runtime.bound.handle = 43
    capture_runtime.after_capture = drift
    runtime = verifier_module.Verifier(native_identity_reader=capture_runtime.reader)
    result = runtime.capture_pre_action_state(action_name="scroll_down", capture_scope_evidence=True)
    assert result["capture_status"] == "unavailable"
    assert result["reason"] == reason


def test_identity_unavailable_prevents_capture_and_is_not_fabricated(capture_runtime):
    capture_runtime.fact = {"status": "unavailable", "reason": "access_denied"}
    result = verifier_module.Verifier(native_identity_reader=capture_runtime.reader).capture_pre_action_state(capture_scope_evidence=True)
    assert result["capture_status"] == "unavailable"
    assert result["reason"] == "capture_identity_unavailable"
    assert capture_runtime.calls == []


def test_capture_error_is_an_explicit_unavailable_observation(capture_runtime):
    def fail():
        raise OSError("fixture capture failed")
    capture_runtime.after_capture = fail
    result = verifier_module.Verifier(native_identity_reader=capture_runtime.reader).capture_pre_action_state(capture_scope_evidence=True)
    assert result["capture_status"] == "unavailable"
    assert result["reason"] == "capture_failed"
    assert result["error_type"] == "OSError"


def test_scoped_capture_rejects_roi_before_capturing(capture_runtime):
    from app.api.models.request import ROIModel

    result = verifier_module.Verifier(native_identity_reader=capture_runtime.reader).capture_pre_action_state(
        roi=ROIModel(x=0, y=0, width=100, height=100), capture_scope_evidence=True,
    )
    assert result["capture_status"] == "unavailable"
    assert result["reason"] == "full_window_capture_required"
    assert capture_runtime.calls == []


def test_corrupt_capture_is_not_marked_observed(capture_runtime, tmp_path, monkeypatch):
    path = tmp_path / "corrupt.png"
    path.write_bytes(b"not a png")
    monkeypatch.setattr(verifier_module, "screenshot_service", SimpleNamespace(capture_window=lambda **kwargs: {
        "image_path": str(path), "window_size": {"width": 200, "height": 100}, "roi": None,
    }))
    result = verifier_module.Verifier(native_identity_reader=capture_runtime.reader).capture_pre_action_state(capture_scope_evidence=True)
    assert result["capture_status"] == "unavailable"
    assert result["reason"] == "capture_failed"


@pytest.mark.parametrize("changes,status", [([], "no_visual_change"), ([(10, 10, 29, 29)], "target_visual_change"), ([(120, 10, 139, 29)], "non_target_visual_change")])
def test_existing_scroll_route_measures_actual_fixture_images_without_authorizing_retry(capture_runtime, tmp_path, monkeypatch, changes, status):
    from app.api import action as action_api
    from app.api.models.request import ROIModel, ScrollRequest

    bbox = {"x": 0, "y": 0, "width": 100, "height": 100}
    monkeypatch.setattr(action_api, "window_manager", verifier_module.window_manager)
    monkeypatch.setattr(action_api, "verifier", verifier_module.Verifier(native_identity_reader=capture_runtime.reader))
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: str(tmp_path / "fixture-trace.json"))
    monkeypatch.setattr(action_api, "discover_seek_scroll_containers", lambda **kwargs: {})
    monkeypatch.setattr(action_api, "get_scroll_container", lambda *args: {"container_id": "pane", "bbox": bbox})
    dispatches = []

    def dispatch(**kwargs):
        dispatches.append(kwargs)
        capture_runtime.changes = changes
        return {"scrolled": True, "cursor_before": {"x": 0, "y": 0}, "cursor_after": {"x": 50, "y": 50}, "foreground_before": 42, "foreground_after": 42}

    monkeypatch.setattr(action_api, "input_controller", SimpleNamespace(scroll_window=dispatch))
    response = action_api.scroll(ScrollRequest(scroll_scope="container", target_container_id="pane", container_bbox=ROIModel(**bbox), direction="down", wheel_clicks=2))
    assert response.success is True
    result = response.data["result"]
    assert result["scroll_effect_validation"]["status"] == status
    assert result["post_scroll_verification"]["verified"] is None
    assert result["scroll_effect_validation"]["scroll_movement_verified"] is None
    assert result["outcome"]["should_retry_goal"] is False
    assert len(dispatches) == 1
    assert [call["focus_window"] for call in capture_runtime.calls] == [False, False]


def test_scroll_route_does_not_dispatch_when_pre_capture_identity_is_unavailable(capture_runtime, tmp_path, monkeypatch):
    from app.api import action as action_api
    from app.api.models.request import ScrollRequest

    capture_runtime.fact = {"status": "unavailable"}
    monkeypatch.setattr(action_api, "window_manager", verifier_module.window_manager)
    monkeypatch.setattr(action_api, "verifier", verifier_module.Verifier(native_identity_reader=capture_runtime.reader))
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: str(tmp_path / "fixture-trace.json"))
    dispatches = []
    monkeypatch.setattr(action_api, "input_controller", SimpleNamespace(scroll_window=lambda **kwargs: dispatches.append(kwargs)))
    response = action_api.scroll(ScrollRequest(direction="down"))
    assert response.success is False
    assert response.error.code == "pre_scroll_evidence_unavailable"
    assert dispatches == []
