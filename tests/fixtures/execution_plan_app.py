"""全新原生执行基准；仅按钮业务动作产生独立效果标记与外部真值。"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets

from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout, QWidget


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
LAYOUT_VARIANTS = frozenset({"default", "reversed"})


def _case(case_id, layout_variant):
    if not isinstance(case_id, str) or not _IDENTIFIER.fullmatch(case_id):
        raise ValueError("case_id must be 1..128 ASCII letters, digits, underscores or dashes")
    if not isinstance(layout_variant, str) or layout_variant not in LAYOUT_VARIANTS:
        raise ValueError("layout_variant must be default or reversed")


def control_digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


def _write(path, value):
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class ActionOracle:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=False)

    def append(self, row):
        value = {"schema": "execution_fixture_action.v1", "at": datetime.now(timezone.utc).isoformat(), **row}
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def events(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]


class ExecutionPlanWindow(QWidget):
    def __init__(self, case_id, *, layout_variant="default", event_sink=None):
        _case(case_id, layout_variant)
        super().__init__()
        self.setWindowTitle("Execution Plan Desk")
        self.setObjectName("executionPlanWindow")
        self.resize(680, 440)
        self._event_sink = event_sink
        self._event_index = self._epoch = self._reset_event_index = 0
        self._markers = {}
        self._closed = False
        self.notice_dialog = None
        layout = QVBoxLayout(self)
        self.page_anchor = QLabel("Execution Plan workspace")
        self.page_anchor.setAccessibleName(self.page_anchor.text())
        layout.addWidget(self.page_anchor)
        self.controls = QWidget()
        self.controls.setAccessibleName("Record load controls")
        self.button_layout = QVBoxLayout(self.controls)
        self.buttons = {}
        for record_id in ("A", "B"):
            button = QPushButton(f"Load record {record_id}")
            button.setObjectName(f"loadRecord{record_id}")
            button.setAccessibleName(button.text())
            button.setMinimumHeight(48)
            button.clicked.connect(lambda checked=False, value=record_id: self._load_record(value))
            self.buttons[record_id] = button
            self.button_layout.addWidget(button)
        layout.addWidget(self.controls)
        self.results = QWidget()
        self.results.setObjectName("loadedResults")
        self.results.setAccessibleName("Loaded record results")
        self.results_layout = QVBoxLayout(self.results)
        layout.addWidget(self.results)
        self.notice_button = QPushButton("Show notice")
        self.notice_button.setObjectName("showNoticeButton")
        self.notice_button.setAccessibleName("Show notice")
        self.notice_button.clicked.connect(self.show_notice)
        layout.addWidget(self.notice_button)
        self.reset_case(case_id=case_id, layout_variant=layout_variant)

    def _emit(self, row):
        self._event_index += 1
        event = {**row, "event_index": self._event_index, "case_id": self._case_id,
                 "epoch": self._epoch, "layout_variant": self._layout_variant}
        if self._event_sink is not None:
            self._event_sink(deepcopy(event))
        return self._event_index

    def _load_record(self, record_id):
        if self.notice_dialog is not None and self.notice_dialog.isVisible():
            return
        marker = self._markers.get(record_id)
        if marker is None:
            marker = QLabel()
            marker.setObjectName(f"loadedRecord{record_id}")
            self.results_layout.addWidget(marker)
            self._markers[record_id] = marker
        marker.setText(f"Record {record_id} loaded {self._case_id}")
        marker.setAccessibleName(marker.text())
        marker.show()
        # 真值读取按钮所属记录和实际标签文字，不读取 runtime 的目标或成功判断。
        self._emit({"action": "load_record", "record_id": record_id, "marker_name": marker.text()})

    def reset_case(self, *, case_id, layout_variant):
        _case(case_id, layout_variant)
        if self.notice_dialog is not None:
            dialog = self.notice_dialog
            with QSignalBlocker(dialog):
                dialog.close()
            dialog.setParent(None)
            dialog.deleteLater()
            self.notice_dialog = None
        for marker in self._markers.values():
            self.results_layout.removeWidget(marker)
            marker.hide()
            marker.setParent(None)
            marker.deleteLater()
        self._markers = {}
        for button in self.buttons.values():
            self.button_layout.removeWidget(button)
            button.setEnabled(True)
        for record_id in (("A", "B") if layout_variant == "default" else ("B", "A")):
            self.button_layout.addWidget(self.buttons[record_id])
        self.notice_button.setEnabled(True)
        self._case_id, self._layout_variant = case_id, layout_variant
        self._epoch += 1
        self._reset_event_index = self._emit({"action": "case_reset", "loaded_records": [], "marker_names": []})

    def show_notice(self):
        if self.notice_dialog is not None and self.notice_dialog.isVisible():
            return
        dialog = QDialog(self)
        self.notice_dialog = dialog
        dialog.setWindowTitle("Notice")
        dialog.setObjectName("noticeDialog")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        text = QLabel("Review this notice before continuing.")
        text.setAccessibleName(text.text())
        layout.addWidget(text)
        button = QPushButton("Close")
        button.setObjectName("closeNoticeButton")
        button.setAccessibleName("Close")
        button.clicked.connect(dialog.accept)
        layout.addWidget(button)
        for record in self.buttons.values():
            record.setEnabled(False)
        self.notice_button.setEnabled(False)
        dialog.finished.connect(lambda result: self._notice_finished(dialog))
        dialog.show()
        self._emit({"action": "notice_opened"})

    def _notice_finished(self, dialog):
        if self.notice_dialog is not dialog:
            return
        self.notice_dialog = None
        for record in self.buttons.values():
            record.setEnabled(True)
        self.notice_button.setEnabled(True)
        self._emit({"action": "notice_closed"})
        dialog.setParent(None)
        dialog.deleteLater()

    def state_snapshot(self):
        return {"case_id": self._case_id, "epoch": self._epoch, "layout_variant": self._layout_variant,
                "event_index": self._event_index, "reset_event_index": self._reset_event_index,
                "loaded_records": list(self._markers), "marker_names": [marker.text() for marker in self._markers.values()],
                "notice_visible": bool(self.notice_dialog and self.notice_dialog.isVisible())}

    def closeEvent(self, event):
        if self.notice_dialog is not None and self.notice_dialog.isVisible():
            self.notice_dialog.close()
        self._closed = True
        super().closeEvent(event)


class FixtureController:
    def __init__(self, window, root, manifest, oracle):
        self.window, self.root, self.manifest, self.oracle = window, Path(root), deepcopy(manifest), oracle
        self._receipts = {}
        self._last_control = None

    def _receipt(self, control, *, status, reason=None):
        snapshot = self.window.state_snapshot()
        return {"request_id": control.get("request_id"), "status": status,
            **({"reason": reason} if reason is not None else {}), "control_sha256": control_digest(control),
            "pid": self.manifest["pid"], "window_handle": self.manifest["window_handle"], "snapshot": snapshot,
            "events": [event for event in self.oracle.events() if event["epoch"] == snapshot["epoch"]]}

    def apply(self, control):
        if not isinstance(control, dict):
            return self._receipt({}, status="rejected", reason="control_object_required")
        request_id = control.get("request_id")
        previous = self._receipts.get(request_id) if isinstance(request_id, str) else None
        if previous is not None:
            return deepcopy(previous[1]) if previous[0] == control else self._receipt(control,
                status="conflict", reason="request_id_reused_with_different_payload")
        try:
            base = {"action", "nonce", "request_id"}
            if control.get("nonce") != self.manifest["control_nonce"]:
                raise ValueError("control_nonce_invalid")
            action = control.get("action")
            legacy_close = control == {"action": "close", "nonce": self.manifest["control_nonce"]}
            if not legacy_close and (not isinstance(request_id, str) or not _IDENTIFIER.fullmatch(request_id)):
                raise ValueError("request_id_invalid")
            if action == "load_case" or action == "reset":
                state = self.window.state_snapshot()
                fields = base | {"case_id", "layout_variant"}
                if set(control) != fields and not (action == "reset" and set(control) == base):
                    raise ValueError("reset_case_requires_exact_fields")
                self.window.reset_case(case_id=control.get("case_id", state["case_id"]),
                    layout_variant=control.get("layout_variant", state["layout_variant"]))
            elif action == "observe":
                state = self.window.state_snapshot()
                if (set(control) != base | {"case_id", "epoch"} or type(control["epoch"]) is not int
                        or control["case_id"] != state["case_id"] or control["epoch"] != state["epoch"]):
                    raise ValueError("observe_current_case_epoch_required")
            elif action == "close":
                if not legacy_close and set(control) != base:
                    raise ValueError("close_requires_exact_fields")
                self.window.close()
            else:
                raise ValueError("control_action_unsupported")
            result = self._receipt(control, status="observed" if action == "observe" else "applied")
        except ValueError as error:
            result = self._receipt(control, status="rejected", reason=str(error))
        if isinstance(request_id, str):
            self._receipts[request_id] = (deepcopy(control), deepcopy(result))
        return result

    def poll(self):
        if self.window._closed:
            return
        try:
            control = json.loads((self.root / "control.json").read_text(encoding="utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite_control")))
        except (OSError, ValueError, UnicodeError):
            return
        if control == self._last_control:
            return
        result = self.apply(control)
        _write(self.root / "control_result.json", result)
        self._last_control = deepcopy(control)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--layout-variant", choices=sorted(LAYOUT_VARIANTS), default="default")
    args = parser.parse_args(argv)
    try:
        _case(args.case_id, args.layout_variant)
        root = args.data_root.resolve()
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("fixture_data_root_must_be_new: " + str(root))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    oracle = ActionOracle(root / "oracle" / "actions.jsonl")
    app = QApplication.instance() or QApplication([])
    window = ExecutionPlanWindow(args.case_id, layout_variant=args.layout_variant, event_sink=oracle.append)
    window.show()
    app.processEvents()
    handle = int(window.winId())
    manifest = {"schema": "execution_fixture_manifest.v1", "pid": os.getpid(), "window_handle": handle,
        "handle": handle, "title": window.windowTitle(), "data_root": str(root), "control_nonce": secrets.token_hex(16)}
    _write(root / "manifest.json", manifest)
    _write(root / "ready.json", {"status": "ready", "pid": os.getpid(), "window_handle": handle,
        "case_id": args.case_id, "epoch": 1, "layout_variant": args.layout_variant})
    controller = FixtureController(window, root, manifest, oracle)
    timer = QTimer(window)
    timer.timeout.connect(controller.poll)
    timer.start(50)
    code = app.exec()
    timer.stop()
    _write(root / "closed.json", {"status": "closed", "normal_close": window._closed,
        "pid": os.getpid(), "window_handle": handle, "exit_code": code, "snapshot": window.state_snapshot()})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
