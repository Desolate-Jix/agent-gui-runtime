"""独立夹具仅在离屏模式启动，并只通过本目录控制文件关闭。"""
import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys
import time

from PySide6.QtWidgets import QApplication

from scripts import run_learning_workflow_fixture as fixture_launcher


def test_reorder_receipt_preserves_accumulated_window_state(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    records = [{"id": f"R-{index}", "name": "Same name", "detail": f"value-{index}"}
               for index in (11, 22, 33)]
    window = fixture_launcher._load_fixture_class()(records)
    window.query_field.setText("R-22")
    window._filter()
    window._open_detail("R-22")
    window.controlled_field.setText("value-22")
    window._verify_field()
    before = window.state_snapshot()
    oracle_path = tmp_path / "records.json"
    fixture_launcher._write(oracle_path, {"schema": "learning_fixture_oracle.v1", "records": records})
    control = {"action": "reorder_rows", "nonce": "nonce", "request_id": "reorder-1",
               "ordered_ids": ["R-33", "R-22", "R-11"]}
    try:
        receipt = fixture_launcher._reorder_receipt(window, oracle_path, control,
                                                   pid=123, window_handle=int(window.winId()))
        assert receipt["status"] == "applied"
        after = window.state_snapshot()
        for key in ("case_id", "reset_event_index", "selected_id", "query", "detail_text",
                    "controlled_value", "verification_text", "layout_variant", "notice_visible"):
            assert after[key] == before[key], key
        assert after["visible_ids"] == control["ordered_ids"]
        assert after["records"] == json.loads(oracle_path.read_text(encoding="utf-8"))["records"]
        invalid = {**control, "request_id": "invalid", "ordered_ids": ["R-22"]}
        assert fixture_launcher._reorder_receipt(window, oracle_path, invalid,
                                                 pid=123, window_handle=int(window.winId()))["status"] == "failed"
        assert window.state_snapshot() == after
        extra = {**control, "request_id": "extra", "unexpected": True}
        assert fixture_launcher._reorder_receipt(window, oracle_path, extra,
                                                 pid=123, window_handle=int(window.winId()))["status"] == "failed"
        def blocked_write(path, value):
            raise OSError("oracle storage unavailable")
        monkeypatch.setattr(fixture_launcher, "_write_atomic", blocked_write)
        failed = fixture_launcher._reorder_receipt(window, oracle_path,
            {**control, "request_id": "storage", "ordered_ids": ["R-11", "R-22", "R-33"]},
            pid=123, window_handle=int(window.winId()))
        assert failed["status"] == "failed" and failed["reason"] == "oracle storage unavailable"
        assert window.state_snapshot() == after
        assert json.loads(oracle_path.read_text(encoding="utf-8"))["records"] == after["records"]
    finally:
        window.close()


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "run_learning_workflow_fixture.py"


def _wait(path, *, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        time.sleep(.05)
    raise AssertionError(f"missing fixture file: {path}")


def _run(tmp_path, seed):
    root = tmp_path / "fresh-fixture"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    process = subprocess.Popen([sys.executable, "-X", "utf8", str(LAUNCHER), "--data-root", str(root),
                                "--seed", seed], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        ready = _wait(root / "ready.json")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        assert ready["status"] == "ready" and ready["pid"] == manifest["pid"]
        assert manifest["pid"] > 0 and manifest["seed"] == seed
        assert manifest["title"] == "Record Desk" and manifest["data_root"] == str(root.resolve())
        assert "oracle" not in manifest and "records" not in manifest
        assert isinstance(manifest["window_handle"], int) and manifest["window_handle"] > 0
        oracle = json.loads((root / "oracle" / "records.json").read_text(encoding="utf-8"))
        assert len(oracle["records"]) == 3
        target = oracle["records"][0]["id"]
        (root / "control.json").write_text(json.dumps({"action": "set_detail", "nonce": manifest["control_nonce"],
                                                      "request_id": "change-1", "record_id": target,
                                                      "detail": "current-after-control"}), encoding="utf-8")
        result = _wait(root / "control_result.json")
        assert result == {"request_id": "change-1", "status": "applied", "record_id": target}
        changed = json.loads((root / "oracle" / "records.json").read_text(encoding="utf-8"))
        assert next(row for row in changed["records"] if row["id"] == target)["detail"] == "current-after-control"
        assert manifest["window_handle"] == json.loads((root / "ready.json").read_text(encoding="utf-8"))["window_handle"]
        oracle = changed
        (root / "control.json").write_text(json.dumps({"action": "close", "nonce": "incorrect"}), encoding="utf-8")
        time.sleep(.15)
        assert process.poll() is None and not (root / "closed.json").exists()
        (root / "control.json").write_text(json.dumps({"action": "close", "nonce": manifest["control_nonce"]}),
                                           encoding="utf-8")
        code = process.wait(timeout=12)
        assert code == 0, process.stderr.read()
        closed = _wait(root / "closed.json")
        assert closed["status"] == "closed" and closed["pid"] == manifest["pid"]
        events = (root / "oracle" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
        assert json.loads(events[-1])["action"] == "fixture_closed"
        assert sum(json.loads(row).get("action") == "set_detail" for row in events) == 1
        return oracle
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_offscreen_launcher_ready_close_and_seed(tmp_path):
    first = _run(tmp_path / "one", "fresh-seed-1")
    second = _run(tmp_path / "two", "fresh-seed-1")
    assert first == second


def test_offscreen_control_request_id_replay_and_errors(tmp_path):
    root = tmp_path / "fresh-fixture"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    process = subprocess.Popen([sys.executable, "-X", "utf8", str(LAUNCHER), "--data-root", str(root),
                                "--seed", "control-replay"], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        _wait(root / "ready.json")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        oracle_path = root / "oracle" / "records.json"
        target = json.loads(oracle_path.read_text(encoding="utf-8"))["records"][0]["id"]

        def request(request_id, record_id, detail, expected_status):
            control = {"action": "set_detail", "nonce": manifest["control_nonce"],
                       "request_id": request_id, "record_id": record_id, "detail": detail}
            (root / "control.json").write_text(json.dumps(control), encoding="utf-8")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                path = root / "control_result.json"
                if path.is_file():
                    result = json.loads(path.read_text(encoding="utf-8"))
                    if result.get("request_id") == request_id and result.get("status") == expected_status:
                        return result
                time.sleep(.02)
            raise AssertionError(f"missing control receipt: {request_id}/{expected_status}")

        first = request("A", target, "v1", "applied")
        request("B", target, "v2", "applied")
        assert request("A", target, "v1", "applied") == first
        assert next(row for row in json.loads(oracle_path.read_text(encoding="utf-8"))["records"]
                    if row["id"] == target)["detail"] == "v2"
        conflict = request("A", target, "unexpected", "conflict")
        assert conflict["reason"] == "request_id_reused_with_different_payload"
        assert request("unknown", "R-000", "bad", "failed")["reason"] == "record_id must identify an existing record"
        assert request("invalid", target, "", "failed")["reason"] == "detail must be a non-empty string"
        assert next(row for row in json.loads(oracle_path.read_text(encoding="utf-8"))["records"]
                    if row["id"] == target)["detail"] == "v2"
        events = [json.loads(row) for row in (root / "oracle" / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
        assert sum(row.get("action") == "set_detail" for row in events) == 2
    finally:
        if process.poll() is None:
            if (root / "manifest.json").is_file():
                manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
                (root / "control.json").write_text(json.dumps({"action": "close", "nonce": manifest["control_nonce"]}),
                                                   encoding="utf-8")
                process.wait(timeout=5)
            else:
                process.terminate()
                process.wait(timeout=5)


def test_oracle_write_error_returns_failed_receipt_without_mutation(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    records = [{"id": "R-101", "name": "Record", "detail": "before"}]
    window = fixture_launcher._load_fixture_class()(records)
    window._open_detail("R-101")
    oracle_path = tmp_path / "records.json"
    fixture_launcher._write(oracle_path, {"schema": "learning_fixture_oracle.v1", "records": records})

    def blocked_write(path, value):
        raise OSError("oracle storage unavailable")

    monkeypatch.setattr(fixture_launcher, "_write_atomic", blocked_write)
    receipt = fixture_launcher._detail_receipt(window, oracle_path,
        {"request_id": "write-failure", "record_id": "R-101", "detail": "after"})
    assert receipt == {"request_id": "write-failure", "status": "failed", "reason": "oracle storage unavailable"}
    assert window.detail_output.text() == "ID: R-101 | Detail: before"
    assert window.records_snapshot()[0]["detail"] == "before"
    assert json.loads(oracle_path.read_text(encoding="utf-8"))["records"][0]["detail"] == "before"
    window.close()


def test_offscreen_case_load_observe_replay_nonce_and_epoch(tmp_path):
    root = tmp_path / "case-fixture"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    process = subprocess.Popen([sys.executable, "-X", "utf8", str(LAUNCHER), "--data-root", str(root),
                                "--seed", "case-control"], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        _wait(root / "ready.json")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        records = [{"id": f"R-{index}", "name": f"Record {index}", "detail": f"current-{index}"}
                   for index in (11, 22, 33)]
        first = {"case_id": "case-one", "records": records,
                 "ordered_ids": ["R-22", "R-11", "R-33"], "layout_variant": "search_below_rows"}
        second = {"case_id": "case-one", "records": records,
                  "ordered_ids": ["R-33", "R-22", "R-11"], "layout_variant": "detail_above_rows"}

        def control(payload, expected_status):
            (root / "control.json").write_text(json.dumps(payload), encoding="utf-8")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                path = root / "control_result.json"
                if path.is_file():
                    result = json.loads(path.read_text(encoding="utf-8"))
                    if result.get("request_id") == payload["request_id"] and result.get("status") == expected_status:
                        return result
                time.sleep(.02)
            raise AssertionError(f"missing {expected_status} receipt: {payload['request_id']}")

        load_a = {"action": "load_case", "nonce": manifest["control_nonce"], "request_id": "load-A",
                  "scenario": first}
        receipt_a = control(load_a, "applied")
        assert receipt_a["control_sha256"] == sha256(json.dumps(load_a, sort_keys=True, separators=(",", ":"),
                                                               ensure_ascii=False).encode("utf-8")).hexdigest()
        assert receipt_a["pid"] == manifest["pid"]
        assert receipt_a["window_handle"] == manifest["window_handle"]
        observe_a = control({"action": "observe_case", "nonce": manifest["control_nonce"],
                             "request_id": "observe-A", "case_id": "case-one"}, "observed")
        assert observe_a["events"][0]["action"] == "case_reset"
        assert observe_a["snapshot"]["visible_ids"] == first["ordered_ids"]
        assert observe_a["snapshot"]["records"] == json.loads((root / "oracle" / "records.json").read_text(encoding="utf-8"))["records"]
        first_reset = observe_a["snapshot"]["reset_event_index"]
        load_b = {**load_a, "request_id": "load-B", "scenario": second}
        control(load_b, "applied")
        assert control(load_a, "applied") == receipt_a
        observe_b = control({"action": "observe_case", "nonce": manifest["control_nonce"],
                             "request_id": "observe-B", "case_id": "case-one"}, "observed")
        assert observe_b["snapshot"]["visible_ids"] == second["ordered_ids"]
        assert observe_b["snapshot"]["reset_event_index"] > first_reset
        assert observe_b["events"][0]["event_index"] == observe_b["snapshot"]["reset_event_index"]
        assert all(event["event_index"] >= observe_b["snapshot"]["reset_event_index"] for event in observe_b["events"])
        changed = control({"action": "set_detail", "nonce": manifest["control_nonce"],
                           "request_id": "detail-after-case", "record_id": "R-22",
                           "detail": "fresh-current-value"}, "applied")
        assert changed == {"request_id": "detail-after-case", "status": "applied", "record_id": "R-22"}
        assert json.loads((root / "oracle" / "records.json").read_text(encoding="utf-8"))["case_id"] == "case-one"
        observe_c = control({"action": "observe_case", "nonce": manifest["control_nonce"],
                             "request_id": "observe-C", "case_id": "case-one"}, "observed")
        assert observe_c["events"][-1]["action"] == "set_detail"
        assert next(row for row in observe_c["snapshot"]["records"] if row["id"] == "R-22")["detail"] == "fresh-current-value"
        reorder = {"action": "reorder_rows", "nonce": manifest["control_nonce"],
                   "request_id": "reorder-A", "ordered_ids": ["R-11", "R-33", "R-22"]}
        reordered = control(reorder, "applied")
        assert reordered["pid"] == manifest["pid"]
        assert reordered["window_handle"] == manifest["window_handle"]
        assert reordered["control_sha256"] == fixture_launcher._control_hash(reorder)
        observed = control({"action": "observe_case", "nonce": manifest["control_nonce"],
                            "request_id": "observe-reordered", "case_id": "case-one"}, "observed")
        assert observed["snapshot"]["visible_ids"] == reorder["ordered_ids"]
        assert observed["snapshot"]["reset_event_index"] == observe_c["snapshot"]["reset_event_index"]
        assert sum(event["action"] == "reorder_rows" for event in observed["events"]) == 1
        assert control(reorder, "applied") == reordered
        assert control({**reorder, "ordered_ids": ["R-22", "R-33", "R-11"]}, "conflict")["reason"] == "request_id_reused_with_different_payload"
        wrong_reorder = {**reorder, "nonce": "incorrect", "request_id": "wrong-reorder"}
        (root / "control.json").write_text(json.dumps(wrong_reorder), encoding="utf-8")
        time.sleep(.2)
        assert json.loads((root / "control_result.json").read_text(encoding="utf-8"))["status"] == "conflict"
        observe_c = observed
        bad_scenario = {**second, "ordered_ids": ["R-33", "R-33", "R-11"]}
        invalid = control({"action": "load_case", "nonce": manifest["control_nonce"],
                           "request_id": "invalid-case", "scenario": bad_scenario}, "failed")
        assert "ordered_ids" in invalid["reason"]
        assert json.loads((root / "oracle" / "records.json").read_text(encoding="utf-8"))["records"] == observe_c["snapshot"]["records"]
        wrong_nonce = {**load_b, "request_id": "bad-nonce", "nonce": "incorrect"}
        (root / "control.json").write_text(json.dumps(wrong_nonce), encoding="utf-8")
        time.sleep(.2)
        assert json.loads((root / "control_result.json").read_text(encoding="utf-8")) == invalid
        conflict = control({**load_a, "scenario": second}, "conflict")
        assert conflict["reason"] == "request_id_reused_with_different_payload"
        oracle_path = root / "oracle" / "records.json"
        oracle_path.write_text('{"schema":"learning_fixture_oracle.v1","case_id":"case-one","records":[]}',
                               encoding="utf-8")
        bad_observe = {"action": "observe_case", "nonce": manifest["control_nonce"],
                       "request_id": "bad-oracle", "case_id": "case-one"}
        failed = control(bad_observe, "failed")
        assert failed["reason"] == "observe_case oracle records mismatch"
        assert failed["control_sha256"] == sha256(json.dumps(bad_observe, sort_keys=True,
                                                               separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        assert failed["pid"] == manifest["pid"]
        assert failed["window_handle"] == manifest["window_handle"]
    finally:
        if process.poll() is None:
            if (root / "manifest.json").is_file():
                manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
                (root / "control.json").write_text(json.dumps({"action": "close", "nonce": manifest["control_nonce"]}),
                                                   encoding="utf-8")
                process.wait(timeout=5)
            else:
                process.terminate()
                process.wait(timeout=5)
