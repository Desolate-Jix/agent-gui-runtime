import pytest

from app.learning_memory import learning_observation_capture as module


class _Bound:
    handle = 12
    process_id = 34


class _Windows:
    def get_bound_window(self):
        return _Bound()


class _Coordinator:
    def _windows(self):
        return _Windows()


def _capture(_coordinator, handle, pid, *, image_path, recipe):
    assert (handle, pid) == (12, 34)
    assert image_path == "current.png"
    assert recipe == {"scope": {"anchors": [{"kind": "uia"}]}, "strategies": []}
    identity = {"handle": handle, "process_id": pid, "process_create_time": 56.0}
    frame = {"capture_id": "memory-capture-current", "image_path": image_path,
        "sha256": "frame-sha", "image_size": {"width": 200, "height": 120},
        "window_identity": identity, "application": {"executable_name": "fixture.exe"}}
    snapshot = {"provider": "windows_uia", "status": "ok", "scan_complete": True,
        "truncated": False, "controls": [], "capture_id": frame["capture_id"],
        "window_identity": identity}
    uia = {"status": "ok", "capture_id": frame["capture_id"],
        "window_identity": identity, "snapshot": snapshot}
    return frame, {"uia": uia}


def test_observation_scope_projects_current_frame_and_keeps_source(monkeypatch):
    monkeypatch.setattr(module, "capture_memory_observation", _capture)
    candidate = {"candidate_id": "chosen", "source": "agent_visual",
        "bbox": {"x": 10, "y": 20, "width": 30, "height": 12},
        "capture_id": "old-capture"}
    context = {"event_id": "event-1", "command_sha256": "command-sha"}
    with module.learning_capture_scope(_Coordinator(), context):
        observation = module.observe_learning_target(image_path="current.png", candidate=candidate,
            click_point={"x": 24, "y": 26})
    assert observation == {"contract_version": "learning_target_observation.v1",
        "event_id": "event-1", "command_sha256": "command-sha", "observation_stage": "before",
        "frame": _capture(_Coordinator(), 12, 34, image_path="current.png",
            recipe={"scope": {"anchors": [{"kind": "uia"}]}, "strategies": []})[0],
        "uia": _capture(_Coordinator(), 12, 34, image_path="current.png",
            recipe={"scope": {"anchors": [{"kind": "uia"}]}, "strategies": []})[1]["uia"],
        "candidate": {"capture_id": "memory-capture-current",
            "viewport_size": {"width": 200, "height": 120}, "source": "agent_visual",
            "bbox": {"x": 10, "y": 20, "w": 30, "h": 12},
            "click_point": {"x": 24, "y": 26}, "freshness": "current_capture"}}
    assert candidate["capture_id"] == "old-capture"


def test_no_scope_is_a_noop_and_scope_does_not_leak(monkeypatch):
    monkeypatch.setattr(module, "capture_memory_observation", lambda *_a, **_k: pytest.fail("unexpected capture"))
    args = {"image_path": "current.png", "candidate": {}, "click_point": {"x": 1, "y": 2}}
    assert module.observe_learning_target(**args) is None
    with module.learning_capture_scope(_Coordinator(), {"event_id": "event", "command_sha256": "sha"}):
        assert module.observe_learning_target(**args)["event_id"] == "event"
    assert module.observe_learning_target(**args) is None


def test_incomplete_uia_returns_structured_unavailable(monkeypatch):
    def capture(*_args, **_kwargs):
        frame, observations = _capture(*_args, **_kwargs)
        observations["uia"] = {"status": "unavailable", "reason": "uia_incomplete",
            "capture_id": frame["capture_id"], "window_identity": frame["window_identity"]}
        return frame, observations
    monkeypatch.setattr(module, "capture_memory_observation", capture)
    with module.learning_capture_scope(_Coordinator(), {"event_id": "event", "command_sha256": "sha"}):
        value = module.observe_learning_target(image_path="current.png",
            candidate={"source": "ocr", "bbox": {"x": 1, "y": 2, "width": 4, "height": 5}},
            click_point={"x": 2, "y": 3})
    assert value["status"] == "unavailable"
    assert value["reason"] == "uia_incomplete"
    assert value["frame"]["capture_id"] == "memory-capture-current"


def test_unexpected_capture_error_is_not_swallowed(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("programming_failure")
    monkeypatch.setattr(module, "capture_memory_observation", fail)
    with module.learning_capture_scope(_Coordinator(), {"event_id": "event", "command_sha256": "sha"}):
        with pytest.raises(RuntimeError, match="programming_failure"):
            module.observe_learning_target(image_path="current.png",
                candidate={"source": "api_visual",
                    "bbox": {"x": 0, "y": 0, "width": 2, "height": 2}},
                click_point={"x": 1, "y": 1})


@pytest.mark.parametrize("candidate,point,reason", [
    ({"bbox": {"x": 10, "y": 20, "width": 30, "height": 12}}, {"x": 24, "y": 26},
     "candidate_source_unavailable"),
    ({"source": "api_visual", "bbox": {"x": 10, "y": 20, "width": 30, "height": 12}},
     {"x": 5, "y": 5}, "selected_click_point_outside_candidate_bbox"),
])
def test_missing_source_or_point_outside_bbox_is_unavailable(monkeypatch, candidate, point, reason):
    monkeypatch.setattr(module, "capture_memory_observation", _capture)
    with module.learning_capture_scope(_Coordinator(), {"event_id": "event", "command_sha256": "sha"}):
        value = module.observe_learning_target(image_path="current.png", candidate=candidate,
            click_point=point)
    assert value["status"] == "unavailable"
    assert value["reason"] == reason
    assert "candidate" not in value
