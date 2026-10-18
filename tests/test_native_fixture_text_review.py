"""文字代审只限预定夹具和确切字段/值；此处不启动窗口或系统输入。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.text_parameters import ReviewedTextParameters, ReviewedTextSource, resolve_text_parameters
from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot, prepare_text_field_expectation
from tests.native_fixture_review_support import FixtureTextScope


@pytest.mark.parametrize("kind", ["literal", "variable"])
@pytest.mark.parametrize("mutation", [None, "value", "before", "field", "script", "grant", "state", "submit_action"])
def test_text_fixture_requires_exact_local_review(tmp_path, monkeypatch, kind, mutation):
    import tests.native_fixture_review_support as module
    script = Path(module.__file__).with_name("native_text_target.py").resolve()
    process = SimpleNamespace(pid=9001, create_time=lambda: 42., children=lambda **k: [],
        cmdline=lambda: ["C:/Python/python.exe", str(script), "--evidence-dir", str(tmp_path)],
        exe=lambda: "C:/Python/python.exe")
    bound = SimpleNamespace(handle=4242, process_id=9001)
    manager = SimpleNamespace(bind_window_by_handle=lambda h: bound, get_bound_window=lambda: bound)
    scope = FixtureTextScope(manager, 9001, 4242, 9001, script, tmp_path, lambda pid: process)
    value = scope.VALUES[0 if kind == "literal" else 1]
    old = "" if kind == "literal" else scope.VALUES[0]
    parameters = resolve_text_parameters(ReviewedTextParameters("fixture.searchQuery",
        ReviewedTextSource(kind, value if kind == "literal" else "search_term"), True, False), {"search_term": value})
    identity = TextFieldIdentity("fixture.searchQuery", 4242, 9001, 42., (42, 12), (0, 0, 900, 560), (11, 50, 878, 22))
    field = prepare_text_field_expectation(TextFieldSnapshot(identity, "capture", "read", 12, "uia_value", old, None), parameters)
    view = {"phase": "pending_review", "confirmation_id": "test-only", "png_bytes": b"synthetic",
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat(),
        "text_input_local": parameters, "text_field_local": field,
        "preview": {"intent": {"semantic_action": "fill_field", "goal": "搜索词"},
            "preview_sha256": "test-hash", "observation_evidence": {
                "target": {"window_handle": 4242, "process_id": 9001}, "application": {"process_create_time": 42.}},
            "uia_snapshot": {"controls": [{"control_type": "Edit", "name": "搜索词", "automation_id": "QApplication.NativeTextTarget.searchQuery",
                "bbox": {"x": 11, "y": 50, "w": 878, "h": 22}}]}}}
    # 附加范围测试复用完整原生预览测试对协议的验证，不伪造实机证明。
    monkeypatch.setattr(module, "validate_review_view", lambda v: (v, None))
    state = {"pid": 9001, "source_file_sha256": scope.script_sha, "state": "text", "value": old}
    grant = {"actor": "authorized_fixture_test_operator", "human_approval": False, "confirmation_id": "test-only",
        "preview_sha256": "test-hash", "png_sha256": hashlib.sha256(b"synthetic").hexdigest(),
        "window_handle": 4242, "process_id": 9001, **scope.grant_details(view)}
    if mutation in {"value", "before"}:
        changed = resolve_text_parameters(ReviewedTextParameters("fixture.searchQuery",
            ReviewedTextSource(kind, "other" if kind == "literal" else "search_term"), True, False), {"search_term": "other"})
        if mutation == "value":
            view["text_input_local"] = changed
        else:
            view["text_field_local"] = prepare_text_field_expectation(
                TextFieldSnapshot(identity, "capture", "read", 12, "uia_value", "other", None), parameters)
    if mutation == "field": view["preview"]["uia_snapshot"]["controls"][0]["name"] = "other"
    if mutation == "script": scope.script = tmp_path / "foreign.py"
    if mutation == "grant": grant["text"]["value"] = "other"
    if mutation == "state": state["value"] = "other"
    if mutation == "submit_action": view["preview"]["intent"]["semantic_action"] = "final_submit"
    (tmp_path / "latest-state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    if mutation is None:
        scope.verify_review(view, deepcopy(view), grant)
    else:
        with pytest.raises(PermissionError):
            scope.verify_review(view, deepcopy(view), grant)
