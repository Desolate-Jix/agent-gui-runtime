"""已审核导航夹具代审适配的离屏正反例；不派发系统输入。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from tests.native_reviewed_fixture_support import (
    ReviewedFixtureReviewDriver, ReviewedNavigationFixtureScope,
)


ASSET_SHA = "a" * 64


def _scope(tmp_path, *, semantic="open_detail", transition="transition.open", goal="查看示例详情"):
    from tests import native_navigation_target
    script = __import__("pathlib").Path(native_navigation_target.__file__).resolve()
    evidence = tmp_path / "target"
    evidence.mkdir()
    values = {"created": 42.0, "cmd": ["python.exe", str(script), "--evidence-dir", str(evidence)]}
    process = SimpleNamespace(pid=9001, create_time=lambda: values["created"],
        cmdline=lambda: values["cmd"], exe=lambda: "C:/Python/python.exe", children=lambda **_kwargs: [])
    bound = SimpleNamespace(handle=4242, process_id=9001)
    manager = SimpleNamespace(bind_window_by_handle=lambda _handle: bound, get_bound_window=lambda: bound)
    scope = ReviewedNavigationFixtureScope(manager, 9001, 4242, 9001, script, evidence,
        lambda _pid: process, asset_id="fixture-nav", asset_content_sha256=ASSET_SHA,
        transition_id=transition, goal=goal)
    return scope


def _view(*, semantic="open_detail", transition="transition.open"):
    now = datetime.now(timezone.utc)
    descriptions = {"open_detail": "open_detail · ACTION_RECORDED", "back": "back · ACTION_RECORDED"}
    action = {"action_id": transition, "semantic_action": semantic,
              "description": descriptions[semantic]}
    return {"phase": "pending_review", "source_kind": "reviewed_learning",
        "confirmation_id": "grounded-confirmation." + "b" * 64,
        "expires_at": (now + timedelta(minutes=5)).isoformat(), "png_bytes": b"reviewed-png",
        "preview": {"content_sha256": "c" * 64, "target_window_handle": 4242,
            "target_process_id": 9001,
            "workflow": {"asset_id": "fixture-nav", "asset_content_sha256": ASSET_SHA},
            "current_observation": {"available_actions": [action]},
            "grounding_preview": {"asset_id": "fixture-nav", "asset_content_sha256": ASSET_SHA,
                "transition_id": transition, "semantic_action": semantic}}}


def _grant(view):
    return {"actor": "authorized_fixture_test_operator", "human_approval": False,
        "confirmation_id": view["confirmation_id"], "preview_sha256": view["preview"]["content_sha256"],
        "png_sha256": hashlib.sha256(view["png_bytes"]).hexdigest(),
        "window_handle": 4242, "process_id": 9001, "asset_id": "fixture-nav",
        "asset_content_sha256": ASSET_SHA, "transition_id": "transition.open", "goal": "查看示例详情"}


@pytest.mark.parametrize("mutation", [None, "asset", "transition", "goal", "action", "state", "grant"])
def test_reviewed_scope_accepts_only_exact_navigation_binding(tmp_path, monkeypatch, mutation):
    import tests.native_reviewed_fixture_support as module
    scope, view = _scope(tmp_path), _view()
    checked = deepcopy(view)
    checked.pop("source_kind")
    pinned, grant = deepcopy(checked), _grant(view)
    state = {"pid": 9001, "source_file_sha256": scope.script_sha, "state": "list"}
    if mutation == "asset": checked["preview"]["workflow"]["asset_id"] = "other"
    elif mutation == "transition": checked["preview"]["grounding_preview"]["transition_id"] = "other"
    elif mutation == "goal": checked["preview"]["current_observation"]["available_actions"][0]["goal"] = "other"
    elif mutation == "action": checked["preview"]["grounding_preview"]["semantic_action"] = "final_submit"
    elif mutation == "state": state["state"] = "detail"
    elif mutation == "grant": grant["human_approval"] = True
    monkeypatch.setattr(module, "validate_review_view", lambda _value: (checked, None))
    (scope.evidence_dir / "latest-state.json").write_text(json.dumps(state), encoding="utf-8")
    if mutation is None:
        scope.verify_review(checked, pinned, grant)
    else:
        with pytest.raises(PermissionError):
            scope.verify_review(checked, pinned, grant)


@pytest.mark.parametrize(("semantic", "transition", "goal", "state"), [
    ("open_detail", "transition.open", "查看示例详情", "list"),
    ("back", "transition.back", "返回列表", "detail"),
])
def test_real_recorded_titles_map_one_to_one_to_chinese_goals(
    tmp_path, monkeypatch, semantic, transition, goal, state,
):
    import tests.native_reviewed_fixture_support as module
    scope = _scope(tmp_path, semantic=semantic, transition=transition, goal=goal)
    view = _view(semantic=semantic, transition=transition)
    checked = deepcopy(view); checked.pop("source_kind")
    grant = _grant(view)
    grant.update(transition_id=transition, goal=goal)
    pinned = deepcopy(checked)
    monkeypatch.setattr(module, "validate_review_view", lambda _value: (checked, None))
    (scope.evidence_dir / "latest-state.json").write_text(json.dumps({
        "pid": 9001, "source_file_sha256": scope.script_sha, "state": state}), encoding="utf-8")
    scope.verify_review(checked, pinned, grant)


def test_recorded_title_cannot_be_cross_mapped(tmp_path, monkeypatch):
    import tests.native_reviewed_fixture_support as module
    scope, view = _scope(tmp_path), _view()
    checked = deepcopy(view); checked.pop("source_kind")
    checked["preview"]["current_observation"]["available_actions"][0]["description"] = "back · ACTION_RECORDED"
    monkeypatch.setattr(module, "validate_review_view", lambda _value: (checked, None))
    (scope.evidence_dir / "latest-state.json").write_text(json.dumps({
        "pid": 9001, "source_file_sha256": scope.script_sha, "state": "list"}), encoding="utf-8")
    with pytest.raises(PermissionError, match="reviewed_fixture"):
        scope.verify_review(checked, deepcopy(checked), _grant(view))


def test_reviewed_driver_reads_grounding_semantic_and_strips_source_kind(tmp_path):
    view = _view()
    driver = SimpleNamespace(pinned=deepcopy(view))
    driver.semantic_action = lambda: ReviewedFixtureReviewDriver.semantic_action(driver)
    assert driver.semantic_action() == "open_detail"
    assert view["source_kind"] == "reviewed_learning"


def test_reviewed_driver_uses_existing_dialog_approval_and_confirmation(tmp_path):
    from app.desktop_review.single_step_dialog import SingleStepDialog
    from app.desktop_review.window import ensure_application
    from tests.test_desktop_single_step_dialog import _review, _wait, _idle

    class Coordinator:
        def __init__(self):
            self.view = _review()
            self.view["source_kind"] = "reviewed_learning"
            self.calls = []
        def current_agent_review(self):
            return deepcopy(self.view)
        def approve(self, **identity):
            self.calls.append(("approve", identity))
            result = deepcopy(self.view); result.pop("source_kind"); result["phase"] = "approved"
            return result
        def execute(self, **identity):
            self.calls.append(("execute", identity))
            return {"kind": "decision", "payload": {"status": "REJECTED",
                "reason_code": "synthetic_no_dispatch"}}
        def cancel(self):
            return {"phase": "idle", "cleanup_verified": True}

    ensure_application()
    coordinator, dialog = Coordinator(), None
    try:
        dialog = SingleStepDialog(coordinator)
        dialog.show(); dialog._read_fresh_review(); _idle(dialog)
        grant = tmp_path / "grant.json"; grant.write_text("{}", encoding="utf-8")
        log = tmp_path / "operator.jsonl"
        checked = []
        scope = SimpleNamespace(handle=5000, pid=9001, focus=lambda: checked.append("focus"),
            verify_review=lambda *_args: checked.append("verified"))
        driver = ReviewedFixtureReviewDriver(dialog, scope, coordinator.view, grant, log)
        _wait(lambda: not dialog.isVisible(), timeout=15); _idle(dialog)
        assert driver.error is None
        assert [call[0] for call in coordinator.calls] == ["approve", "execute"]
        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert [event["stage"] for event in events] == [
            "approval_button", "execution_dialog", "execution_confirmed", "execution_returned"]
        assert all(event["human_approval"] is False for event in events)
        assert checked.count("focus") == 2
    finally:
        if dialog is not None:
            dialog._has_owner = False; dialog.close(); _idle(dialog)


def test_scope_rejects_any_other_script(tmp_path):
    foreign = tmp_path / "native_navigation_target.py"
    foreign.write_text("# foreign\n", encoding="utf-8")
    evidence = tmp_path / "target"; evidence.mkdir()
    process = SimpleNamespace(pid=1, create_time=lambda: 1.0,
        cmdline=lambda: ["python", str(foreign), "--evidence-dir", str(evidence)], children=lambda **_k: [])
    bound = SimpleNamespace(handle=2, process_id=1)
    manager = SimpleNamespace(bind_window_by_handle=lambda _h: bound, get_bound_window=lambda: bound)
    with pytest.raises(PermissionError, match="not_this_navigation_fixture"):
        ReviewedNavigationFixtureScope(manager, 1, 2, 1, foreign, evidence, lambda _pid: process,
            asset_id="fixture-nav", asset_content_sha256=ASSET_SHA,
            transition_id="transition.open", goal="查看示例详情")
