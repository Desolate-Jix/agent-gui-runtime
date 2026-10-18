"""代审仅限精确自有夹具；合成身份负控和原生 Qt 按钮链，不派发真实输入。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from tests.native_fixture_review_support import FixtureScope, FixtureReviewDriver


def _scope(tmp_path):
    script = tmp_path / "native_navigation_target.py"
    script.write_text("# fixture\n", encoding="utf-8")
    state_dir = tmp_path / "target"
    state_dir.mkdir()
    values = {"created": 42., "pid": 9001, "cmd": ["C:/Python/python.exe", str(script), "--evidence-dir", str(state_dir)]}
    process = SimpleNamespace(pid=9001, create_time=lambda: values["created"],
        cmdline=lambda: values["cmd"], exe=lambda: "C:/Python/python.exe", children=lambda **k: [])
    bound = SimpleNamespace(handle=4242, process_id=9001)
    manager = SimpleNamespace(bind_window_by_handle=lambda h: bound, get_bound_window=lambda: bound)
    scope = FixtureScope(manager, 9001, 4242, 9001, script, state_dir, lambda p: process)
    return scope, values, bound


@pytest.mark.parametrize("mutation", ["pid", "created", "cmd", "script"])
def test_owned_target_drift_is_rejected(tmp_path, mutation):
    scope, values, bound = _scope(tmp_path)
    if mutation == "pid":
        bound.process_id = 9002
    elif mutation == "created":
        values["created"] = 43.
    elif mutation == "cmd":
        values["cmd"] = ["C:/Python/python.exe", "foreign.py"]
    else:
        scope.script.write_text("# changed\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        scope.verify_process()


@pytest.mark.parametrize("mutation", [None, "grant", "expired", "state", "danger", "target", "preview"])
def test_exact_grant_and_fixture_semantics(tmp_path, monkeypatch, mutation):
    import tests.native_fixture_review_support as module
    scope, values, bound = _scope(tmp_path)
    now = datetime.now(timezone.utc)
    view = {"phase": "pending_review", "confirmation_id": "test-only", "png_bytes": b"synthetic",
        "expires_at": (now + timedelta(seconds=300)).isoformat(), "preview": {
            "intent": {"semantic_action": "open_detail", "goal": "查看示例详情"},
            "preview_sha256": "test-hash", "observation_evidence": {
                "target": {"window_handle": 4242, "process_id": 9001},
                "application": {"process_create_time": 42.}}}}
    # 这里只测夹具附加约束；真实预览解析由后面的完整协调器测试覆盖。
    monkeypatch.setattr(module, "validate_review_view", lambda v: (v, None))
    state = {"pid": 9001, "source_file_sha256": scope.script_sha, "state": "list"}
    grant = {"actor": "authorized_fixture_test_operator", "human_approval": False,
        "confirmation_id": "test-only", "preview_sha256": "test-hash",
        "png_sha256": hashlib.sha256(b"synthetic").hexdigest(), "window_handle": 4242, "process_id": 9001}
    if mutation == "grant": grant["confirmation_id"] = "other"
    if mutation == "expired": view["expires_at"] = (now - timedelta(seconds=1)).isoformat()
    if mutation == "state": state["state"] = "detail"
    if mutation == "danger": view["preview"]["intent"]["semantic_action"] = "final_submit"
    if mutation == "target": view["preview"]["observation_evidence"]["target"]["window_handle"] = 77
    pinned = deepcopy(view)
    if mutation == "preview": view["preview"]["intent"]["goal"] = "other"
    (scope.evidence_dir / "latest-state.json").write_text(json.dumps(state), encoding="utf-8")
    if mutation is None:
        scope.verify_review(view, pinned, grant)
    else:
        with pytest.raises(PermissionError): scope.verify_review(view, pinned, grant)


def test_driver_uses_real_dialog_two_confirmations_and_keeps_backend_gate(tmp_path):
    from tests.test_native_fresh_coordinator import _coordinator, _request
    from tests.test_fresh_dispatch_graph import _close
    from tests.test_desktop_single_step_dialog import _wait, _idle
    from app.desktop_review.single_step_dialog import SingleStepDialog
    from app.desktop_review.window import ensure_application
    ensure_application()
    host, controller, backend, callsite, scope, intent, binding, coordinator, calls = _coordinator(tmp_path)
    dialog = None
    try:
        prepared = coordinator.prepare_fresh(source=callsite._selection.source, learning_binding=binding)
        view = coordinator.request_fresh_review(intent=_request(prepared, intent), expected_learning_binding=binding)
        dialog = SingleStepDialog(coordinator)
        dialog.show()
        dialog._read_fresh_review()
        _idle(dialog)
        checked = []
        test_scope = SimpleNamespace(handle=4242, pid=9001, focus=lambda: checked.append("focus"),
            verify_review=lambda v, p, g: checked.append(v["phase"]))
        grant = tmp_path / "grant.json"
        grant.write_text("{}", encoding="utf-8")
        log = tmp_path / "operator.jsonl"
        driver = FixtureReviewDriver(dialog, test_scope, view, grant, log)
        _wait(lambda: not dialog.isVisible(), timeout=15)
        _idle(dialog)
        assert driver.error is None
        assert len(backend.commands) == 1
        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert [e["stage"] for e in events] == ["approval_button", "execution_dialog", "execution_confirmed", "execution_returned"]
        assert all(e["human_approval"] is False for e in events)
        assert "approved" in checked and checked.count("focus") == 2
    finally:
        if dialog is not None:
            dialog.close()
            _idle(dialog)
        coordinator.shutdown()
        _close(host, controller)
