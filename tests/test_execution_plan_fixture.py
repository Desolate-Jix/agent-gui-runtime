"""独立原生性能场景的离屏合同；不启动桌面、runtime 或模型。"""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
import pytest


def module():
    source = Path(__file__).parent / "fixtures" / "execution_plan_app.py"
    spec = importlib.util.spec_from_file_location("execution_plan_fixture", source)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == "offscreen"
    return app


def test_real_buttons_create_independent_markers_and_actual_action_oracle(qapp):
    events = []
    window = module().ExecutionPlanWindow("case-fresh", event_sink=events.append)
    window.show()
    qapp.processEvents()
    assert window.state_snapshot()["marker_names"] == []
    assert not any(label.text().startswith("Record ") for label in window.findChildren(QLabel))
    assert [button.accessibleName() for button in window.buttons.values()] == ["Load record A", "Load record B"]
    window.buttons["A"].click()
    qapp.processEvents()
    assert window.state_snapshot()["marker_names"] == ["Record A loaded case-fresh"]
    marker = window.findChild(QLabel, "loadedRecordA")
    assert marker.accessibleName() == marker.text() and marker.isVisible()
    assert events[-1]["action"] == "load_record" and events[-1]["record_id"] == "A"
    assert events[-1]["marker_name"] == marker.text()
    window.buttons["B"].click()
    assert window.state_snapshot()["loaded_records"] == ["A", "B"]
    assert [event["event_index"] for event in events] == [1, 2, 3]
    assert [event["record_id"] for event in events if event["action"] == "load_record"] == ["A", "B"]
    window.close()


def test_same_window_reset_advances_epoch_erases_markers_and_reverses_layout(qapp):
    events = []
    window = module().ExecutionPlanWindow("case-1", event_sink=events.append)
    window.show()
    qapp.processEvents()
    handle = int(window.winId())
    old_a = window.buttons["A"].pos().y()
    window.buttons["A"].click()
    window.reset_case(case_id="case-1", layout_variant="reversed")
    qapp.processEvents()
    state = window.state_snapshot()
    assert state["epoch"] == 2 and state["reset_event_index"] == 3
    assert state["loaded_records"] == state["marker_names"] == []
    assert window.findChild(QLabel, "loadedRecordA") is None
    assert int(window.winId()) == handle
    assert window.buttons["A"].pos().y() > window.buttons["B"].pos().y()
    assert old_a < window.buttons["A"].pos().y()
    window.buttons["B"].click()
    assert events[-1]["epoch"] == 2 and events[-1]["record_id"] == "B"
    window.reset_case(case_id="case-2", layout_variant="default")
    assert window.state_snapshot()["epoch"] == 3
    assert window.state_snapshot()["case_id"] == "case-2"
    assert window.state_snapshot()["marker_names"] == []
    assert [event["event_index"] for event in events] == list(range(1, 6))
    window.close()


def test_notice_is_native_modal_and_close_recovers_without_business_load(qapp):
    events = []
    window = module().ExecutionPlanWindow("case-notice", event_sink=events.append)
    window.show()
    window.notice_button.click()
    qapp.processEvents()
    assert window.notice_dialog.isVisible() and window.notice_dialog.isModal()
    assert window.state_snapshot()["notice_visible"]
    window.buttons["A"].click()
    assert window.state_snapshot()["loaded_records"] == []
    window.notice_dialog.findChild(QPushButton, "closeNoticeButton").click()
    qapp.processEvents()
    assert not window.state_snapshot()["notice_visible"] and window.buttons["A"].isEnabled()
    window.buttons["A"].click()
    assert [event["action"] for event in events] == ["case_reset", "notice_opened", "notice_closed", "load_record"]
    window.notice_button.click()
    window.reset_case(case_id="case-reset", layout_variant="default")
    assert not window.state_snapshot()["notice_visible"]
    assert window.state_snapshot()["marker_names"] == []
    window.close()


def controller(tmp_path, qapp):
    fixture = module()
    oracle = fixture.ActionOracle(tmp_path / "oracle" / "actions.jsonl")
    window = fixture.ExecutionPlanWindow("case-1", event_sink=oracle.append)
    window.show()
    qapp.processEvents()
    manifest = {"pid": os.getpid(), "window_handle": int(window.winId()), "control_nonce": "safe-nonce"}
    return fixture.FixtureController(window, tmp_path, manifest, oracle), window, fixture


def command(action, request_id="r1", **extra):
    return {"action": action, "nonce": "safe-nonce", "request_id": request_id, **extra}


def test_control_replay_conflict_and_observe_are_independent_of_runtime(tmp_path, qapp):
    driver, window, fixture = controller(tmp_path, qapp)
    reset = command("load_case", case_id="same-case", layout_variant="reversed")
    result = driver.apply(reset)
    assert result["status"] == "applied" and result["snapshot"]["epoch"] == 2
    assert result["control_sha256"] == fixture.control_digest(reset)
    assert driver.apply(deepcopy(reset)) == result
    assert window.state_snapshot()["epoch"] == 2
    assert driver.apply({**reset, "layout_variant": "default"})["status"] == "conflict"
    window.buttons["B"].click()
    observation = driver.apply(command("observe", "r2", case_id="same-case", epoch=2))
    assert observation["status"] == "observed"
    assert [event["action"] for event in observation["events"]] == ["case_reset", "load_record"]
    assert observation["events"][-1]["record_id"] == "B"
    assert driver.apply(command("observe", "r3", case_id="same-case", epoch=1))["status"] == "rejected"
    result = driver.apply(command("reset", "r4"))
    assert result["snapshot"]["epoch"] == 3 and result["snapshot"]["marker_names"] == []
    assert [event["event_index"] for event in driver.oracle.events()] == [1, 2, 3, 4]
    window.close()


@pytest.mark.parametrize("bad", [
    {"action": "click", "record_id": "A"}, {"action": "load_record", "record_id": "B"},
    {"action": "load_case", "case_id": "case-2", "layout_variant": "default", "x": 10},
    {"action": "load_case", "case_id": "case-2", "layout_variant": "unknown"},
    {"action": "reset", "case_id": "case-2"}, {"action": "reset", "nonce": "wrong"},
    {"action": "observe", "case_id": "other", "epoch": 1},
])
def test_control_rejects_business_actions_bad_nonce_and_invalid_state_atomically(tmp_path, qapp, bad):
    driver, window, fixture = controller(tmp_path, qapp)
    before = window.state_snapshot()
    events = driver.oracle.events()
    assert driver.apply({**command("reset"), **bad})["status"] == "rejected"
    assert window.state_snapshot() == before and driver.oracle.events() == events
    window.close()


def test_poll_uses_utf8_atomic_receipt_and_no_repeated_reset(tmp_path, qapp):
    driver, window, fixture = controller(tmp_path, qapp)
    payload = command("load_case", case_id="case-2", layout_variant="default")
    (tmp_path / "control.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    driver.poll()
    result = json.loads((tmp_path / "control_result.json").read_text(encoding="utf-8"))
    assert result["control_sha256"] == fixture.control_digest(payload)
    assert result["snapshot"]["epoch"] == 2
    driver.poll()
    assert window.state_snapshot()["epoch"] == 2
    window.close()


def wait_json(path, process):
    deadline = monotonic() + 6
    while monotonic() < deadline:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        assert process.poll() is None, process.communicate()[1]
        sleep(.03)
    raise AssertionError("offscreen fixture acknowledgement timed out")


def test_cli_offscreen_handshake_nonce_observe_and_normal_close(tmp_path):
    script = Path(__file__).parent / "fixtures" / "execution_plan_app.py"
    root = tmp_path / "fresh-run"
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    process = subprocess.Popen([sys.executable, str(script), "--data-root", str(root), "--case-id", "cli-fresh"],
        env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        ready = wait_json(root / "ready.json", process)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        assert ready["epoch"] == 1 and manifest["window_handle"] == manifest["handle"]
        assert manifest["schema"] == "execution_fixture_manifest.v1"
        import psutil
        # Windows 虚拟环境可保留启动器进程；manifest 必须指向其实际 Qt 子进程。
        allowed_pids = {process.pid, *[child.pid for child in psutil.Process(process.pid).children(recursive=True)]}
        assert manifest["pid"] in allowed_pids
        payload = {"action": "observe", "nonce": manifest["control_nonce"], "request_id": "cli-observe",
            "case_id": "cli-fresh", "epoch": 1}
        (root / "control.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        observed = wait_json(root / "control_result.json", process)
        assert observed["status"] == "observed" and observed["snapshot"]["marker_names"] == []
        (root / "control.json").write_text(json.dumps({"action": "close", "nonce": manifest["control_nonce"]}), encoding="utf-8")
        closed = wait_json(root / "closed.json", process)
        assert closed["status"] == "closed" and closed["normal_close"] is True
        assert process.wait(timeout=3) == 0
        events = [json.loads(line) for line in (root / "oracle" / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
        assert all(event["action"] != "load_record" for event in events)
    finally:
        if (root / "manifest.json").is_file() and not (root / "closed.json").is_file():
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            (root / "control.json").write_text(json.dumps({"action": "close", "nonce": manifest["control_nonce"]}), encoding="utf-8")
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)


def test_cli_rejects_existing_data_root_without_overwrite(tmp_path):
    script = Path(__file__).parent / "fixtures" / "execution_plan_app.py"
    protected = tmp_path / "protected.txt"
    protected.write_text("keep", encoding="utf-8")
    result = subprocess.run([sys.executable, str(script), "--data-root", str(tmp_path), "--case-id", "existing"],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, capture_output=True, text=True, encoding="utf-8", timeout=5)
    assert result.returncode != 0 and protected.read_text(encoding="utf-8") == "keep"
    assert "fixture_data_root_must_be_new" in result.stderr
    assert str(tmp_path.resolve()) in result.stderr
    assert not (tmp_path / "manifest.json").exists()
