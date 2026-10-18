from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agent import desktop_backend as backend_module


def prepared(**changes):
    from app.agent.scroll_parameters import ReviewedScrollParameters, ScrollDispatchParameters

    values = {"target_container_id": "pane", "axis": "vertical", "direction": "down", "wheel_clicks": 2, "unit": "wheel_detent"}
    values.update(changes)
    return ScrollDispatchParameters(
        parameters=ReviewedScrollParameters(**values), target_bbox=(20.0, 30.0, 100.0, 100.0), viewport_size=(800, 600),
    )


def command_and_authority(scroll):
    command = backend_module.DesktopDispatchCommand(
        semantic_action="scroll_region", capture_id="capture-current", candidate_id="candidate-current",
        click_point=(70.0, 80.0), target_window_handle=4242, scroll=scroll,
    )
    authority = backend_module._mint_execution_authority(
        session_id="session-1", observation_id="observation-1", intent_id="intent-1", workflow_revision_hash="b" * 64,
        semantic_action=command.semantic_action, selection_sha256="a" * 64,
        capture_id=command.capture_id, candidate_id=command.candidate_id, click_point=command.click_point,
        target_window_handle=command.target_window_handle, gate_decision_ref="gate:current", scroll=scroll,
    )
    return command, authority


class InputBoundary:
    def __init__(self, result="success"):
        self.calls = []
        self.result = result

    def click_point(self, *args, **kwargs):
        raise AssertionError("scroll must not click")

    def scroll_window(self, **kwargs):
        from app.core.runtime_input_authority import runtime_backend_input_is_active
        self.calls.append((kwargs, runtime_backend_input_is_active()))
        if self.result == "lost":
            raise OSError("result lost after wheel")
        if self.result != "success":
            return self.result
        return {"scrolled": True, "direction": kwargs["direction"], "wheel_clicks": kwargs["wheel_clicks"],
                "wheel_delta": -240, "window_handle": 4242}


def backend(boundary, *, width=800, handle=4242):
    bound = SimpleNamespace(handle=handle, rect=SimpleNamespace(left=0, top=0, right=width, bottom=600))
    return backend_module.ExistingWindowsBackendAdapter(
        input_controller=boundary, window_manager=SimpleNamespace(get_bound_window=lambda: bound),
    )


def test_typed_scroll_calls_existing_backend_once_under_authority_and_is_not_a_click():
    command, authority = command_and_authority(prepared())
    boundary = InputBoundary()
    adapter = backend(boundary)
    receipt = adapter.dispatch(command, authority=authority)
    assert receipt.status == "dispatched"
    assert boundary.calls == [({"direction": "down", "wheel_clicks": 2, "x": 70, "y": 80}, True)]
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)
    assert len(boundary.calls) == 1


@pytest.mark.parametrize("field,value", [("direction", "up"), ("wheel_clicks", 3), ("target_container_id", "other-pane")])
def test_reviewed_parameter_drift_is_rejected_before_backend(field, value):
    command, authority = command_and_authority(prepared())
    forged = replace(command, scroll=prepared(**{field: value}))
    boundary = InputBoundary()
    with pytest.raises(PermissionError, match="does not match"):
        backend(boundary).dispatch(forged, authority=authority)
    assert boundary.calls == []


def test_authority_snapshot_cannot_be_rebound_to_accept_changed_scroll():
    command, authority = command_and_authority(prepared())
    forged = replace(command, scroll=prepared(direction="up", wheel_clicks=3))
    boundary = InputBoundary()
    with pytest.raises(AttributeError):
        authority.scroll = forged.scroll
    with pytest.raises(AttributeError):
        del authority.scroll
    with pytest.raises(PermissionError, match="does not match"):
        backend(boundary).dispatch(forged, authority=authority)
    assert boundary.calls == []


@pytest.mark.parametrize("field,value", [("semantic_action", "open_detail"), ("capture_id", "forged"), ("candidate_id", "forged"), ("click_point", (90.0, 90.0)), ("target_window_handle", 9999), ("selection_sha256", "f" * 64), ("gate_decision_ref", "forged"), ("_lock", None)])
def test_authority_binding_fields_cannot_be_reassigned(field, value):
    _, authority = command_and_authority(prepared())
    with pytest.raises(AttributeError):
        setattr(authority, field, value)


def test_consumed_authority_cannot_be_reset_for_another_dispatch():
    command, authority = command_and_authority(prepared())
    boundary = InputBoundary()
    adapter = backend(boundary)
    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    with pytest.raises(AttributeError):
        authority._consumed = False
    with pytest.raises(AttributeError):
        del authority._consumed
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)
    assert len(boundary.calls) == 1


@pytest.mark.parametrize("field,value", [("target_bbox", (10.0, 10.0, 150.0, 150.0)), ("viewport_size", (801, 600))])
def test_current_spatial_binding_cannot_change_after_authority(field, value):
    scroll = prepared()
    command, authority = command_and_authority(scroll)
    forged = replace(command, scroll=replace(scroll, **{field: value}))
    boundary = InputBoundary()
    with pytest.raises(PermissionError, match="does not match"):
        backend(boundary).dispatch(forged, authority=authority)
    assert boundary.calls == []


@pytest.mark.parametrize("change", [{"width": 799}, {"handle": 9999}])
def test_changed_bound_window_or_viewport_is_not_dispatched(change):
    command, authority = command_and_authority(prepared())
    boundary = InputBoundary()
    assert backend(boundary, **change).dispatch(command, authority=authority).status == "not_started"
    assert boundary.calls == []


@pytest.mark.parametrize("response", ["lost", None, {"scrolled": False}, {"scrolled": True}, {"scrolled": True, "direction": "up", "wheel_clicks": 2, "wheel_delta": 240, "window_handle": 4242}])
def test_lost_or_mismatched_dispatch_result_is_indeterminate_and_not_repeatable(response):
    command, authority = command_and_authority(prepared())
    boundary, adapter = InputBoundary(response), None
    adapter = backend(boundary)
    assert adapter.dispatch(command, authority=authority).status == "indeterminate"
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)
    assert len(boundary.calls) == 1


@pytest.mark.parametrize("change", [{"wheel_clicks": True}, {"wheel_clicks": 0}, {"wheel_clicks": 21}, {"wheel_clicks": 2.0}, {"direction": "left"}, {"axis": "horizontal"}, {"unit": "pixels"}, {"target_container_id": ""}])
def test_reviewed_scroll_never_normalizes_invalid_or_unbounded_parameters(change):
    with pytest.raises(ValueError):
        prepared(**change)


@pytest.mark.parametrize("point", [(120.0, 50.0), (50.0, 130.0), (float("nan"), 50.0), (-1.0, 30.0)])
def test_dispatch_point_must_be_inside_current_container_after_integer_conversion(point):
    command, _ = command_and_authority(prepared())
    with pytest.raises(ValueError):
        replace(command, click_point=point)


def test_scroll_requires_parameters_and_click_cannot_carry_scroll_parameters():
    command, _ = command_and_authority(prepared())
    with pytest.raises(ValueError):
        replace(command, scroll=None)
    with pytest.raises(ValueError):
        replace(command, semantic_action="open_detail")


def test_payload_contract_rejects_missing_or_injected_fields_instead_of_defaulting():
    from app.agent.scroll_parameters import ReviewedScrollParameters

    expected = {"contract_version": "reviewed_scroll_parameters_v1", "target_container_id": "pane", "axis": "vertical", "direction": "down", "wheel_clicks": 2, "unit": "wheel_detent"}
    parameters = ReviewedScrollParameters.from_payload(expected)
    assert parameters.to_payload() == expected
    for field in expected:
        with pytest.raises(ValueError):
            ReviewedScrollParameters.from_payload({key: value for key, value in expected.items() if key != field})
    with pytest.raises(ValueError):
        ReviewedScrollParameters.from_payload({**expected, "x": 99})


@pytest.mark.parametrize("bbox,viewport", [([20, 30, 100, 100], (800, 600)), ((-1, 30, 100, 100), (800, 600)), ((20, 30, 900, 100), (800, 600)), ((20, 30, 100, 100), [800, 600]), ((20, 30, 100, 100), (True, 600)), ((20, 30, 10 ** 400, 100), (800, 600))])
def test_dispatch_spatial_contract_rejects_mutable_invalid_or_unbounded_geometry(bbox, viewport):
    scroll = prepared()
    with pytest.raises(ValueError):
        replace(scroll, target_bbox=bbox, viewport_size=viewport)
