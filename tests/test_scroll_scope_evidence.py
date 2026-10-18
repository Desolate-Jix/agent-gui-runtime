from types import SimpleNamespace

import pytest

from app.gate.scroll import apply_scroll_scope_invariant, build_scroll_effect_validation, build_scroll_precondition_decision, build_scroll_scope_invariant


@pytest.mark.parametrize("target_changed,non_target", [
    (None, None), (True, None), (True, [{"container_id": "outside", "changed": None}]),
])
def test_missing_scope_observations_cannot_be_ok(target_changed, non_target) -> None:
    result = build_scroll_scope_invariant(
        target_container_id="pane", target_changed=target_changed, non_target_changes=non_target,
    )
    assert result["status"] == "unknown"
    assert result["wrong_scope_detected"] is None


@pytest.mark.parametrize("point,allowed", [({"x": 99, "y": 99}, True), ({"x": 100, "y": 50}, False), ({"x": 50, "y": 100}, False)])
def test_container_right_and_bottom_edges_are_exclusive(point, allowed):
    result = build_scroll_precondition_decision(
        request=SimpleNamespace(scroll_scope="container", direction="down"),
        window_rect={"width": 200, "height": 200}, point=point,
        container_rect={"x": 0, "y": 0, "width": 100, "height": 100}, target_container={"container_id": "pane"},
    )
    assert (result["decision"] == "ALLOW") is allowed


@pytest.mark.parametrize("point,allowed", [({"x": 199, "y": 199}, True), ({"x": 200, "y": 50}, False)])
def test_window_last_pixel_is_valid_but_width_coordinate_is_not(point, allowed):
    result = build_scroll_precondition_decision(
        request=SimpleNamespace(scroll_scope="window"), window_rect={"width": 200, "height": 200},
        point=point, container_rect=None, target_container=None,
    )
    assert (result["decision"] == "ALLOW") is allowed


@pytest.mark.parametrize("target_changed,status", [(True, "ok"), (False, "no_target_progress")])
def test_complete_scope_observations_have_explicit_result(target_changed, status) -> None:
    result = build_scroll_scope_invariant(
        target_container_id="pane", target_changed=target_changed,
        non_target_changes=[{"container_id": "outside", "changed": False}],
    )
    assert result["status"] == status
    assert result["wrong_scope_detected"] is False


def test_applying_unknown_scope_preserves_unknown_instead_of_false() -> None:
    result = apply_scroll_scope_invariant(
        {"scroll_effect_validation": {"status": "unknown", "wrong_scope_detected": None}},
        build_scroll_scope_invariant(target_container_id="pane", target_changed=None),
    )
    assert result["wrong_scope_detected"] is None
    assert result["scroll_effect_validation"]["wrong_scope_detected"] is None


def test_non_target_change_is_not_hidden_by_missing_target_observation() -> None:
    result = build_scroll_scope_invariant(
        target_container_id="pane", target_changed=None,
        non_target_changes=[{"container_id": "outside", "changed": True}],
    )
    assert result["status"] == "wrong_scope_detected"
    assert result["wrong_scope_detected"] is True


@pytest.mark.parametrize("global_result", [{"verified": True}, {"diff": {"changed": True}}, {"cursor_moved": True, "foreground_consistent": True}])
def test_global_change_or_cursor_cannot_establish_scroll_scope(global_result) -> None:
    result = build_scroll_effect_validation(
        request=SimpleNamespace(scroll_scope="container", target_container_id="pane", target_pane="detail"),
        post_scroll_verification=global_result,
        target_container={"container_id": "pane", "pane_role": "detail"},
    )
    assert result["status"] == "unknown"
    assert result["target_container_content_changed"] is None
    assert result["wrong_scope_detected"] is None
