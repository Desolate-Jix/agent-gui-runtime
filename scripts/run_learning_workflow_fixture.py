"""在新数据根目录启动基准原生夹具；不调用桌面输入。"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import secrets
import sys
from datetime import datetime, timezone

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "learning_workflow_app.py"


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _write_atomic(path: Path, value: dict) -> None:
    pending = path.with_name(path.name + ".pending")
    _write(pending, value)
    pending.replace(path)


def _load_fixture_class():
    spec = importlib.util.spec_from_file_location("learning_workflow_fixture", FIXTURE)
    if spec is None or spec.loader is None:
        raise RuntimeError("fixture source unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LearningWorkflowWindow


def _records(seed: str) -> list[dict]:
    rng = random.Random(seed)
    identifiers = rng.sample(range(100, 999), 3)
    return [{"id": f"R-{identifier}", "name": f"Record {index}",
             "detail": f"detail-{rng.getrandbits(48):012x}"}
            for index, identifier in enumerate(identifiers, 1)]


def _apply_detail_change(window, oracle_path: Path, record_id, detail) -> None:
    records = window.records_snapshot()
    if not isinstance(detail, str) or not detail:
        raise ValueError("detail must be a non-empty string")
    target = next((row for row in records if row["id"] == record_id), None)
    if target is None:
        raise ValueError("record_id must identify an existing record")
    target["detail"] = detail
    prior = json.loads(oracle_path.read_text(encoding="utf-8"))
    oracle = {"schema": "learning_fixture_oracle.v1", "records": records}
    if "case_id" in prior:
        oracle["case_id"] = prior["case_id"]
    _write_atomic(oracle_path, oracle)
    window.update_detail(record_id, detail)


def _detail_receipt(window, oracle_path: Path, control: dict) -> dict:
    request_id = control["request_id"]
    try:
        _apply_detail_change(window, oracle_path, control["record_id"], control["detail"])
    except (ValueError, OSError) as error:
        return {"request_id": request_id, "status": "failed", "reason": str(error)}
    return {"request_id": request_id, "status": "applied", "record_id": control["record_id"]}


def _control_hash(control: dict) -> str:
    encoded = json.dumps(control, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(encoded).hexdigest()


def _reject_nonfinite(value: str):
    raise ValueError(f"non-finite JSON value: {value}")


def _case_failure(control: dict, reason: str, *, pid: int, window_handle: int) -> dict:
    return {"request_id": control["request_id"], "status": "failed", "reason": reason,
            "control_sha256": _control_hash(control), "pid": pid, "window_handle": window_handle}


def _validated_scenario(value) -> tuple[str, list[dict], list[str], str]:
    if not isinstance(value, dict) or set(value) != {"case_id", "records", "ordered_ids", "layout_variant"}:
        raise ValueError("scenario requires exact case_id, records, ordered_ids and layout_variant")
    case_id, records, ordered_ids, variant = (value[key] for key in
        ("case_id", "records", "ordered_ids", "layout_variant"))
    if (not isinstance(case_id, str) or not case_id.strip() or not case_id.isascii()
            or len(case_id) > 128):
        raise ValueError("scenario case_id must be nonempty ASCII")
    if not isinstance(records, list) or len(records) != 3:
        raise ValueError("scenario records must contain exactly three records")
    for row in records:
        if (not isinstance(row, dict) or set(row) != {"id", "name", "detail"}
                or any(not isinstance(row[key], str) or not row[key] for key in row)):
            raise ValueError("scenario records require nonempty id, name and detail")
    ids = [row["id"] for row in records]
    if len(set(ids)) != len(ids):
        raise ValueError("scenario record IDs must be unique")
    if (not isinstance(ordered_ids, list) or len(ordered_ids) != len(ids)
            or any(not isinstance(item, str) for item in ordered_ids)
            or len(set(ordered_ids)) != len(ordered_ids) or set(ordered_ids) != set(ids)):
        raise ValueError("scenario ordered_ids must contain each record exactly once")
    if variant not in {"default", "search_below_rows", "detail_above_rows"}:
        raise ValueError("scenario layout_variant unsupported")
    return case_id, records, ordered_ids, variant


def _load_case_receipt(window, oracle_path: Path, control: dict, *, pid: int, window_handle: int) -> dict:
    request_id = control["request_id"]
    try:
        if set(control) != {"action", "nonce", "request_id", "scenario"}:
            raise ValueError("load_case requires exact control fields")
        case_id, records, ordered_ids, variant = _validated_scenario(control["scenario"])
        by_id = {row["id"]: row for row in records}
        ordered_records = [dict(by_id[record_id]) for record_id in ordered_ids]
        _write_atomic(oracle_path, {"schema": "learning_fixture_oracle.v1",
                                    "case_id": case_id, "records": ordered_records})
        window.reset_case(case_id=case_id, records=records, ordered_ids=ordered_ids,
                          layout_variant=variant)
    except (ValueError, OSError, TypeError, UnicodeError) as error:
        return _case_failure(control, str(error), pid=pid, window_handle=window_handle)
    return {"request_id": request_id, "status": "applied", "case_id": case_id,
            "control_sha256": _control_hash(control), "pid": pid, "window_handle": window_handle}


def _reorder_receipt(window, oracle_path: Path, control: dict, *, pid: int, window_handle: int) -> dict:
    try:
        if set(control) != {"action", "nonce", "request_id", "ordered_ids"}:
            raise ValueError("reorder_rows requires exact control fields")
        records = window.records_snapshot()
        ids = {row["id"] for row in records}
        ordered_ids = control["ordered_ids"]
        if (not isinstance(ordered_ids, list) or any(not isinstance(item, str) for item in ordered_ids)
                or len(ordered_ids) != len(records) or len(set(ordered_ids)) != len(ordered_ids)
                or set(ordered_ids) != ids):
            raise ValueError("ordered_ids must contain each record exactly once")
        prior = json.loads(oracle_path.read_text(encoding="utf-8"))
        by_id = {row["id"]: row for row in records}
        oracle = {"schema": "learning_fixture_oracle.v1", "records": [by_id[item] for item in ordered_ids]}
        if "case_id" in prior:
            oracle["case_id"] = prior["case_id"]
        # 先保存核验数据，再仅重排行；不清空累计任务状态。
        _write_atomic(oracle_path, oracle)
        window.reorder_rows(ordered_ids)
    except (ValueError, OSError, TypeError, UnicodeError) as error:
        return _case_failure(control, str(error), pid=pid, window_handle=window_handle)
    return {"request_id": control["request_id"], "status": "applied", "ordered_ids": list(ordered_ids),
            "control_sha256": _control_hash(control), "pid": pid, "window_handle": window_handle}


def _observe_case_receipt(window, oracle_path: Path, actions_path: Path, control: dict,
                          *, pid: int, window_handle: int) -> dict:
    request_id = control["request_id"]
    try:
        if set(control) != {"action", "nonce", "request_id", "case_id"}:
            raise ValueError("observe_case requires exact control fields")
        case_id = control["case_id"]
        if not isinstance(case_id, str) or not case_id.strip() or not case_id.isascii():
            raise ValueError("observe_case case_id invalid")
        snapshot = window.state_snapshot()
        if snapshot["case_id"] != case_id:
            raise ValueError("observe_case active case mismatch")
        oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
        if (not isinstance(oracle, dict) or oracle.get("schema") != "learning_fixture_oracle.v1"
                or oracle.get("case_id") != case_id or oracle.get("records") != snapshot["records"]):
            raise ValueError("observe_case oracle records mismatch")
        events = []
        for line in actions_path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if not isinstance(event, dict) or type(event.get("event_index")) is not int:
                raise ValueError("observe_case action event invalid")
            if (event.get("case_id") == case_id and snapshot["reset_event_index"] <= event["event_index"]
                    <= snapshot["event_index"]):
                events.append(event)
        expected = list(range(snapshot["reset_event_index"], snapshot["event_index"] + 1))
        if (not events or events[0].get("action") != "case_reset"
                or [event["event_index"] for event in events] != expected):
            raise ValueError("observe_case current epoch actions missing or out of order")
    except (ValueError, OSError, TypeError, KeyError, UnicodeError) as error:
        return _case_failure(control, str(error), pid=pid, window_handle=window_handle)
    return {"request_id": request_id, "status": "observed", "case_id": case_id,
            "snapshot": snapshot, "events": events, "control_sha256": _control_hash(control),
            "pid": pid, "window_handle": window_handle}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--seed")
    args = parser.parse_args(argv)
    if args.seed is not None and (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.seed)):
        parser.error("seed must be 1..80 ASCII letters, digits, dashes or underscores")
    seed = args.seed or secrets.token_hex(16)
    data_root = args.data_root.resolve()
    data_root.mkdir(parents=True, exist_ok=False)
    oracle = data_root / "oracle"
    oracle.mkdir()
    records = _records(seed)
    _write(oracle / "records.json", {"schema": "learning_fixture_oracle.v1", "records": records})

    def log_event(row):
        event = {"schema": "learning_fixture_action.v1", "at": datetime.now(timezone.utc).isoformat(), **row}
        with (oracle / "actions.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()

    application = QApplication.instance() or QApplication([])
    window = _load_fixture_class()(records, event_sink=log_event)
    nonce = secrets.token_hex(16)
    window.show()
    application.processEvents()
    manifest = {"schema": "learning_fixture_manifest.v1", "pid": os.getpid(),
                "window_handle": int(window.winId()), "title": window.windowTitle(),
                "data_root": str(data_root), "seed": seed, "control_nonce": nonce}
    _write(data_root / "manifest.json", manifest)
    _write(data_root / "ready.json", {"status": "ready", "pid": os.getpid(),
                                      "window_handle": manifest["window_handle"]})
    timer = QTimer()
    control_receipts = {}
    last_control_payload = None

    def check_control():
        nonlocal last_control_payload
        path = data_root / "control.json"
        if not path.is_file():
            return
        try:
            control = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)
        except (OSError, ValueError):
            return
        if control == {"action": "close", "nonce": nonce}:
            timer.stop()
            if window.notice_dialog is not None:
                window.notice_dialog.close()
            window.close()
        elif (isinstance(control, dict) and control.get("action") in {"set_detail", "load_case", "observe_case", "reorder_rows"}
              and control.get("nonce") == nonce
              and isinstance(control.get("request_id"), str)
              and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", control["request_id"])
              and control != last_control_payload):
            request_id = control["request_id"]
            previous = control_receipts.get(request_id)
            if previous is not None:
                result = deepcopy(previous[1]) if previous[0] == control else {
                    "request_id": request_id, "status": "conflict",
                    "reason": "request_id_reused_with_different_payload"}
            else:
                if control["action"] == "set_detail":
                    result = (_detail_receipt(window, oracle / "records.json", control)
                              if set(control) == {"action", "nonce", "request_id", "record_id", "detail"}
                              else {"request_id": request_id, "status": "failed",
                                    "reason": "set_detail requires exact control fields"})
                elif control["action"] == "load_case":
                    result = _load_case_receipt(window, oracle / "records.json", control,
                                                pid=manifest["pid"], window_handle=manifest["window_handle"])
                elif control["action"] == "reorder_rows":
                    result = _reorder_receipt(window, oracle / "records.json", control,
                                              pid=manifest["pid"], window_handle=manifest["window_handle"])
                else:
                    result = _observe_case_receipt(window, oracle / "records.json", oracle / "actions.jsonl",
                                                   control, pid=manifest["pid"],
                                                   window_handle=manifest["window_handle"])
                control_receipts[request_id] = (deepcopy(control), deepcopy(result))
            _write_atomic(data_root / "control_result.json", result)
            last_control_payload = deepcopy(control)

    timer.timeout.connect(check_control)
    timer.start(50)
    code = application.exec()
    _write(data_root / "closed.json", {"status": "closed", "pid": os.getpid(), "exit_code": code})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
