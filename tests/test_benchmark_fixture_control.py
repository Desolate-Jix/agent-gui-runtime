"""原生案例状态和结果必须来自本次夹具，不沿用历史成功。"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]


def api():
    name = "scripts.learning_benchmark_fixture"
    assert importlib.util.find_spec(name) is not None, "fixture case driver is missing"
    return __import__(name, fromlist=["RecordDeskCaseDriver"])


def test_original_fixture_process_resets_and_observes_same_window(tmp_path):
    module = api()
    from scripts.learning_benchmark_cases import build_cases
    root = tmp_path / "fixture"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    process = subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "scripts/run_learning_workflow_fixture.py"),
        "--data-root", str(root), "--seed", "case-driver"], cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 12
        while not (root / "ready.json").exists() and time.monotonic() < deadline:
            time.sleep(.05)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        driver = module.RecordDeskCaseDriver(root, timeout=3)
        cases = build_cases(23)
        first = driver.prepare(cases[0])
        changed = driver.prepare(next(case for case in cases if case["variation"] == "unseen"))
        assert first["snapshot"]["records"] != changed["snapshot"]["records"]
        assert first["window_handle"] == changed["window_handle"] == manifest["window_handle"]
        assert changed["snapshot"]["query"] == "" and changed["snapshot"]["selected_id"] is None
        assert changed["snapshot"]["reset_event_index"] > first["snapshot"]["reset_event_index"]
        assert changed["events"][0]["action"] == "case_reset"
        assert len(changed["events"]) == 1
        assert process.poll() is None
    finally:
        if process.poll() is None:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            (root / "control.json").write_text(json.dumps({"action": "close", "nonce": manifest["control_nonce"]}), encoding="utf-8")
            assert process.wait(timeout=8) == 0


def window_case(tmp_path, family):
    module = api()
    from scripts.learning_benchmark_cases import build_cases, scenario_for
    from scripts.run_learning_workflow_fixture import _load_fixture_class
    app = QApplication.instance() or QApplication([])
    case = next(case for case in build_cases(24) if case["task_family"] == family)
    events = []
    window = _load_fixture_class()([], event_sink=lambda event: events.append(dict(event)))
    window.reset_case(**scenario_for(case))
    prepared = {"snapshot": window.state_snapshot(), "events": list(events)}
    return module, case, window, events, prepared, app


@pytest.mark.parametrize("family", ["query_verify", "unique_row_detail", "current_detail_downstream"])
def test_each_family_requires_its_actual_current_result(tmp_path, family):
    module, case, window, events, prepared, app = window_case(tmp_path, family)
    def result():
        return module.evaluate_case(case, prepared, {"snapshot": window.state_snapshot(), "events": list(events)})
    assert result()["completed"] is False
    target = case["inputs"]["record_id"]
    if family == "query_verify":
        window.query_field.setText(case["inputs"]["query"])
        assert result()["completed"] is False
        window.search_button.click()
    else:
        wrong = next(row["id"] for row in window.records_snapshot() if row["id"] != target)
        window._open_detail(wrong)
        assert result()["completed"] is False
        window._open_detail(target)
        if family == "current_detail_downstream":
            assert result()["completed"] is False
            current = next(row["detail"] for row in window.records_snapshot() if row["id"] == target)
            window.controlled_field.setText(current)
            window.verify_button.click()
    verdict = result()
    assert verdict["completed"] is True
    assert verdict["observed_wrong_clicks"] == (0 if family == "query_verify" else 1)
    window.close()


def test_updated_detail_and_reset_invalidate_prior_success(tmp_path):
    module, case, window, events, prepared, app = window_case(tmp_path, "current_detail_downstream")
    from scripts.learning_benchmark_cases import scenario_for
    target = case["inputs"]["record_id"]
    window._open_detail(target)
    detail = next(row["detail"] for row in window.records_snapshot() if row["id"] == target)
    window.controlled_field.setText(detail)
    window.verify_button.click()
    def result():
        return module.evaluate_case(case, prepared, {"snapshot": window.state_snapshot(), "events": list(events)})
    assert result()["completed"] is True
    window.update_detail(target, "new-current-value")
    assert result()["completed"] is False
    window.controlled_field.setText("new-current-value")
    window.verify_button.click()
    assert result()["completed"] is True
    window.reset_case(**scenario_for(case))
    with pytest.raises(ValueError, match="epoch"):
        result()
    window.close()
