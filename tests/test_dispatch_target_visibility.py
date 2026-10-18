from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agent.desktop_backend import (
    DesktopDispatchCommand,
    DeterministicFakeBackend,
    ExistingWindowsBackendAdapter,
    _mint_execution_authority,
)
from app.agent.live_controller import ExistingWindowManagerVisibilityChecker


BBOX = (10.0, 20.0, 80.0, 40.0)


def _command(*, bbox=BBOX):
    return DesktopDispatchCommand(
        semantic_action="open_detail", capture_id="capture-current",
        candidate_id="candidate-current", click_point=(30.0, 40.0),
        target_window_handle=4242, target_bbox=bbox,
    )


def _authority(command):
    return _mint_execution_authority(
        session_id="session", observation_id="observation", intent_id="intent",
        workflow_revision_hash="a" * 64, selection_sha256="b" * 64,
        semantic_action=command.semantic_action, capture_id=command.capture_id,
        candidate_id=command.candidate_id, click_point=command.click_point,
        target_window_handle=command.target_window_handle, gate_decision_ref="gate",
        target_bbox=command.target_bbox,
    )


def test_dispatch_authority_rejects_replaced_or_removed_bbox():
    command = _command()
    authority = _authority(command)
    backend = DeterministicFakeBackend()
    for bbox in ((20.0, 30.0, 80.0, 40.0), None):
        with pytest.raises(PermissionError, match="does not match"):
            backend.dispatch(replace(command, target_bbox=bbox), authority=authority)
    assert backend.dispatch_count == 0
    assert backend.dispatch(command, authority=authority).status == "dispatched"
    assert backend.dispatch_count == 1


@pytest.mark.parametrize("bbox", [
    [10, 20, 80, 40], (10, 20, 0, 40), (10, 20, float("nan"), 40),
    (True, 20, 80, 40), (-1, 20, 80, 40), (50, 20, 80, 40),
])
def test_dispatch_command_rejects_invalid_target_bbox(bbox):
    with pytest.raises(ValueError, match="target bbox"):
        _command(bbox=bbox)


@pytest.mark.parametrize("bbox", [BBOX, None])
def test_windows_adapter_passes_bound_bbox_without_changing_legacy_kwargs(bbox):
    calls = []

    def click(x, y, **kwargs):
        calls.append((x, y, kwargs))
        return {"clicked": True, "window_handle": 4242,
                "window_point": {"x": x, "y": y}}

    command = _command(bbox=bbox)
    backend = ExistingWindowsBackendAdapter(
        input_controller=SimpleNamespace(click_point=click),
        window_manager=SimpleNamespace(get_bound_window=lambda: SimpleNamespace(handle=4242)),
    )
    assert backend.dispatch(command, authority=_authority(command)).status == "dispatched"
    assert calls == [(30, 40, {"target_bbox": BBOX} if bbox is not None else {})]


def _check(manager):
    return ExistingWindowManagerVisibilityChecker(window_manager=manager).check(
        session_id="session", capture_lineage={}, target_window_handle=4242,
        click_point=(30.0, 40.0), target_bbox=BBOX,
    )


@pytest.mark.parametrize("occluder, allowed", [
    ((150, 150, 10, 10), True), ((10, 20, 5, 5), False),
])
def test_visibility_checker_uses_full_target_bbox_even_when_point_is_clear(occluder, allowed):
    calls = []
    bound = SimpleNamespace(handle=4242)

    def region(*, bound, bbox):
        calls.append((bound.handle, bbox))
        x, y, w, h = bbox
        ox, oy, ow, oh = occluder
        clear = not (max(x, ox) < min(x + w, ox + ow)
                     and max(y, oy) < min(y + h, oy + oh))
        return {"allowed": clear, "reason": "target_region_visible" if clear else "target_region_occluded"}

    manager = SimpleNamespace(
        get_bound_window=lambda: bound,
        validate_bound_point_visibility=lambda **kwargs: {"allowed": True, "reason": "point_clear"},
        validate_bound_region_visibility=region,
    )
    facts = _check(manager)
    assert facts["point_visibility"]["allowed"] is allowed
    assert facts["region_visibility"]["allowed"] is allowed
    assert calls == [(4242, BBOX)]
    if not allowed:
        assert facts["point_visibility"]["reason"] == "target_region_occluded"


@pytest.mark.parametrize("capability", [None, lambda **kwargs: None, lambda **kwargs: {"allowed": 1}])
def test_visibility_checker_missing_or_malformed_region_fact_fails_closed(capability):
    manager = SimpleNamespace(
        get_bound_window=lambda: SimpleNamespace(handle=4242),
        validate_bound_point_visibility=lambda **kwargs: {"allowed": True},
    )
    if capability is not None:
        manager.validate_bound_region_visibility = capability
    facts = _check(manager)
    assert facts["point_visibility"]["allowed"] is False
    assert facts["point_visibility"]["reason"] == "target_region_visibility_unavailable"


def test_visibility_checker_region_failure_does_not_override_point_rejection():
    manager = SimpleNamespace(
        get_bound_window=lambda: SimpleNamespace(handle=4242),
        validate_bound_point_visibility=lambda **kwargs: {"allowed": False, "reason": "point_occluded"},
        validate_bound_region_visibility=lambda **kwargs: {"allowed": True, "reason": "target_region_visible"},
    )
    assert _check(manager)["point_visibility"]["allowed"] is False
