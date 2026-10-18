from types import SimpleNamespace

import pytest

from tests.native_target_process_support import owned_window_candidates, wait_for_owned_capture_visibility


def test_venv_child_window_is_selected_but_same_title_foreign_window_is_not():
    own = {"handle": 42, "process_id": 20, "title": "test target"}
    foreign = {"handle": 43, "process_id": 30, "title": "test target"}
    manager = SimpleNamespace(list_visible_windows=lambda: [own, foreign])
    parent = SimpleNamespace(pid=10, children=lambda recursive: [SimpleNamespace(pid=20)])
    assert owned_window_candidates(manager, SimpleNamespace(pid=10), lambda pid: parent) == [own]


def visibility_manager(results, *, process_id=20):
    bound = SimpleNamespace(handle=42, process_id=process_id,
                            rect=SimpleNamespace(left=10, top=20, right=110, bottom=220))
    def check(*, bound, rect):
        assert rect == {"left": 10, "top": 20, "width": 100, "height": 200}
        return next(results)
    return SimpleNamespace(bind_window_by_handle=lambda handle: bound,
                           validate_bound_capture_visibility=check)


def test_fixture_waits_for_uncovered_window_without_input_or_focus():
    manager = visibility_manager(iter([{"allowed": False, "reason": "capture_window_occluded"},
                                       {"allowed": True, "reason": "capture_window_visible"}]))
    pauses, checks = [], []
    result = wait_for_owned_capture_visibility(manager, 42, 20, clock=lambda: 0,
                                               pause=pauses.append, on_check=checks.append)
    assert result["allowed"] is True
    assert len(checks) == 2 and pauses == [0.5]


def test_fixture_visibility_timeout_does_not_proceed():
    manager = visibility_manager(iter([{"allowed": False, "reason": "capture_window_occluded"}]))
    with pytest.raises(TimeoutError, match="fixture_not_ready: capture_window_occluded"):
        wait_for_owned_capture_visibility(manager, 42, 20, timeout=0, clock=lambda: 0)


def test_fixture_identity_drift_does_not_proceed():
    manager = visibility_manager(iter([]), process_id=99)
    with pytest.raises(RuntimeError, match="fixture_identity_changed"):
        wait_for_owned_capture_visibility(manager, 42, 20)
