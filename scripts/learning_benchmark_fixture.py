"""验收侧准备 Record Desk 场景并读取真值；不派发桌面输入。"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from app.learning_memory.benchmark_manifest import digest
from scripts.learning_benchmark_cases import scenario_for


class RecordDeskCaseDriver:
    def __init__(self, root: Path, *, timeout: float = 10):
        if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("fixture_control_timeout_invalid")
        self.root = Path(root).resolve()
        self.timeout = timeout
        self.manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        if (self.manifest.get("schema") != "learning_fixture_manifest.v1"
                or self.manifest.get("data_root") != str(self.root)
                or type(self.manifest.get("pid")) is not int
                or type(self.manifest.get("window_handle")) is not int
                or not isinstance(self.manifest.get("control_nonce"), str)):
            raise ValueError("fixture_control_manifest_invalid")

    def _request(self, action, **fields):
        current = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        if current != self.manifest or (self.root / "closed.json").exists():
            raise ValueError("fixture_control_identity_changed_or_closed")
        command = {"action": action, "nonce": self.manifest["control_nonce"],
                   "request_id": "benchmark-" + uuid4().hex, **fields}
        temporary = self.root / (command["request_id"] + ".pending")
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(command, stream, ensure_ascii=False, allow_nan=False)
        temporary.replace(self.root / "control.json")
        deadline = monotonic() + self.timeout
        while True:
            path = self.root / "control_result.json"
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                receipt = None
            if isinstance(receipt, dict) and receipt.get("request_id") == command["request_id"]:
                if (receipt.get("control_sha256") != digest(command)
                        or receipt.get("pid") != self.manifest["pid"]
                        or receipt.get("window_handle") != self.manifest["window_handle"]):
                    raise ValueError("fixture_control_receipt_identity_mismatch")
                if receipt.get("status") not in {"applied", "observed"}:
                    raise ValueError("fixture_control_failed:" + str(receipt.get("reason", receipt.get("status"))))
                return receipt
            if monotonic() >= deadline:
                raise TimeoutError("fixture_control_timeout_no_replay:" + command["request_id"])
            sleep(min(.05, max(0, deadline - monotonic())))

    def prepare(self, case):
        scenario = scenario_for(case)
        self._request("load_case", scenario=scenario)
        observed = self.observe(case["case_id"])
        _validate_prepared(case, observed)
        return observed

    def observe(self, case_id):
        return self._request("observe_case", case_id=case_id)


def _validate_prepared(case, prepared):
    scenario = scenario_for(case)
    snapshot = prepared["snapshot"]
    by_id = {row["id"]: row for row in scenario["records"]}
    records = [by_id[record_id] for record_id in scenario["ordered_ids"]]
    if (snapshot["case_id"] != case["case_id"] or snapshot["records"] != records
            or snapshot["visible_ids"] != scenario["ordered_ids"]
            or snapshot["layout_variant"] != scenario["layout_variant"]
            or snapshot["query"] != "" or snapshot["selected_id"] is not None
            or snapshot["controlled_value"] != "" or snapshot["detail_text"] != "No record selected"
            or snapshot["verification_text"] != "Not verified" or snapshot["notice_visible"]):
        raise ValueError("fixture_prepared_state_not_frozen_scenario")
    events = _epoch_events(case, snapshot, prepared)
    if len(events) != 1 or events[0]["action"] != "case_reset":
        raise ValueError("fixture_prepared_state_has_prior_actions")
    return scenario


def _epoch_events(case, initial, observed):
    current = observed["snapshot"]
    epoch = initial["reset_event_index"]
    if (current["case_id"] != case["case_id"] or initial["case_id"] != case["case_id"]
            or current["reset_event_index"] != epoch or type(epoch) is not int or epoch < 1):
        raise ValueError("fixture_case_epoch_changed")
    events = observed["events"]
    if not isinstance(events, list):
        raise ValueError("fixture_case_events_invalid")
    events = [event for event in events if event.get("event_index", -1) >= epoch]
    if (not events or events[0].get("action") != "case_reset"
            or any(event.get("case_id") != case["case_id"] for event in events)
            or [event.get("event_index") for event in events] != list(range(epoch, current["event_index"] + 1))):
        raise ValueError("fixture_case_event_sequence_invalid")
    return events


def evaluate_case(case, prepared, observed):
    """按本轮真实控件值和事件判定；旧详情及旧 epoch 不能充当成功。"""
    _validate_prepared(case, prepared)
    initial = prepared["snapshot"]
    events = _epoch_events(case, initial, observed)
    state = observed["snapshot"]
    target = case["inputs"]["record_id"]
    records = state["records"]
    if (not isinstance(records, list) or len({record["id"] for record in records}) != len(records)
            or {row["id"] for row in records} != {row["id"] for row in initial["records"]}
            or state["layout_variant"] != initial["layout_variant"]):
        raise ValueError("fixture_case_identity_or_layout_changed")
    current = next(record for record in records if record["id"] == target)
    actions = events[1:]
    wrong = sum(event["action"] == "open_detail" and event.get("record_id") != target for event in actions)
    family = case["task_family"]
    detail_matches = (state["selected_id"] == target
        and state["detail_text"] == f"ID: {target} | Detail: {current['detail']}"
        and any(event["action"] == "open_detail" and event.get("record_id") == target for event in actions))
    if family == "query_verify":
        filters = [event for event in actions if event["action"] == "filter"]
        completed = (state["query"] == case["inputs"]["query"] and state["visible_ids"] == [target]
            and bool(filters) and filters[-1].get("query") == state["query"]
            and filters[-1].get("visible_ids") == [target])
    elif family == "unique_row_detail":
        completed = detail_matches
    else:
        verifications = [event for event in actions if event["action"] == "verify_field"]
        verification = verifications[-1] if verifications else {}
        completed = (detail_matches and state["controlled_value"] == current["detail"]
            and state["verification_text"] == "Matches current detail"
            and verification.get("record_id") == target and verification.get("matched") is True
            and verification.get("actual_value") == current["detail"]
            and verification.get("expected_detail") == current["detail"])
    return {"schema": "record_desk_case_verdict.v1", "case_id": case["case_id"],
        "completed": bool(completed) and not state["notice_visible"],
        "observed_wrong_clicks": wrong, "wrong_click_coverage": "fixture_open_detail_events_only",
        "reset_event_index": initial["reset_event_index"], "event_index": state["event_index"],
        "current_detail": current["detail"], "evidence_sha256": digest(observed)}
