"""仅供测试操作员代审本轮精确自有窗口；不注入 Agent 或正式版权限。"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox

from app.agent.native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
from app.core.window_preparation import _mint_window_preparation_permit
from app.desktop_review.grounded_preview_widget import validate_review_view, review_time


class FixtureScope:
    def __init__(self, manager, launcher_pid, handle, process_id, script, evidence_dir, process_factory):
        self.manager, self.handle, self.pid = manager, handle, process_id
        self.script, self.evidence_dir = Path(script).resolve(), Path(evidence_dir).resolve()
        self.process_factory = process_factory
        self.launcher_pid = launcher_pid
        self.launcher_created = process_factory(launcher_pid).create_time()
        self.command = process_factory(process_id).cmdline()
        self.script_sha = hashlib.sha256(self.script.read_bytes()).hexdigest()
        self.reader = WindowsNativeIdentityReader(window_manager=manager, process_factory=process_factory)
        manager.bind_window_by_handle(handle)
        self.identity = self.reader.read_identity(handle)
        self.verify_process()

    def verify_process(self):
        launcher = self.process_factory(self.launcher_pid)
        process = self.process_factory(self.pid)
        if (launcher.create_time() != self.launcher_created
                or self.pid not in {launcher.pid, *(p.pid for p in launcher.children(recursive=True))}
                or process.cmdline() != self.command):
            raise PermissionError("fixture_process_changed")
        command = self.command
        if (len(command) != 4 or Path(command[1]).resolve() != self.script
                or command[2] != "--evidence-dir" or Path(command[3]).resolve() != self.evidence_dir
                or hashlib.sha256(self.script.read_bytes()).hexdigest() != self.script_sha):
            raise PermissionError("not_this_navigation_fixture")
        self.manager.bind_window_by_handle(self.handle)
        current = self.reader.read_identity(self.handle)
        checked = validate_native_identity_fact(current, target_window_handle=self.handle, expected_process_id=self.pid)
        if checked is None or current != self.identity:
            raise PermissionError("fixture_window_identity_changed")
        return current

    def verify_review(self, view, pinned, grant):
        checked, _ = validate_review_view(view)
        if ({**checked, "phase": "pending_review"} != pinned
                or datetime.now(timezone.utc) >= review_time(checked["expires_at"])):
            raise PermissionError("fixture_preview_changed_or_expired")
        preview = checked["preview"]
        intent, evidence = preview["intent"], preview["observation_evidence"]
        expected_state = self.expected_state(checked)
        identity = self.verify_process()
        if (evidence["target"]["window_handle"] != self.handle
                or evidence["target"]["process_id"] != self.pid
                or evidence["application"]["process_create_time"] != identity["process_create_time"]):
            raise PermissionError("fixture_preview_target_changed")
        state = json.loads((self.evidence_dir / "latest-state.json").read_text(encoding="utf-8"))
        if (state["pid"] != self.pid or state["source_file_sha256"] != self.script_sha
                or state["state"] != expected_state):
            raise PermissionError("fixture_state_changed")
        self.verify_state(checked, state)
        required = {"actor": "authorized_fixture_test_operator", "human_approval": False,
                    "confirmation_id": checked["confirmation_id"], "preview_sha256": preview["preview_sha256"],
                    "png_sha256": hashlib.sha256(checked["png_bytes"]).hexdigest(),
                    "window_handle": self.handle, "process_id": self.pid, **self.grant_details(checked)}
        if grant != required:
            raise PermissionError("fixture_operator_grant_mismatch")

    def expected_state(self, checked):
        intent = checked["preview"]["intent"]
        allowed = {"open_detail": ("查看示例详情", "list"), "back": ("返回列表", "detail")}
        expected = allowed.get(intent["semantic_action"])
        if expected is None or intent["goal"] != expected[0]:
            raise PermissionError("fixture_action_not_allowed")
        return expected[1]

    def verify_state(self, checked, state):
        pass

    def grant_details(self, checked):
        return {}

    def focus(self):
        identity = self.verify_process()
        permit = _mint_window_preparation_permit(self.manager, identity, self.reader)
        return self.manager.prepare_bound_window(permit)


class FixtureTextScope(FixtureScope):
    """只允许无提交入口的单字段夹具与两组预先确定的非敏感测试值。"""

    VALUES = ("预览版固定文本 S71", "预览版变量文本 S71")

    def expected_state(self, checked):
        intent = checked["preview"]["intent"]
        if (self.script != Path(__file__).with_name("native_text_target.py").resolve()
                or intent["semantic_action"] != "fill_field" or intent["goal"] != "搜索词"):
            raise PermissionError("fixture_text_action_not_allowed")
        parameters = checked["text_input_local"]
        reviewed, field = parameters.reviewed, checked["text_field_local"]
        index = {"literal": 0, "variable": 1}.get(reviewed.content.kind)
        if (index is None or reviewed.target_field_id != "fixture.searchQuery"
                or parameters.text != self.VALUES[index]
                or reviewed.content.value != (self.VALUES[0] if index == 0 else "search_term")
                or reviewed.clear_existing is not True or reviewed.sensitive is not False
                or reviewed.submit is not False or reviewed.clipboard_policy != "restore_previous"
                or field.before.value != ("" if index == 0 else self.VALUES[0])
                or field.expected_value != parameters.text):
            raise PermissionError("fixture_text_value_not_allowed")
        controls = [c for c in checked["preview"]["uia_snapshot"]["controls"]
                    if c.get("control_type") == "Edit" and c.get("name") == "搜索词"
                    and (c.get("automation_id") or "").endswith(".searchQuery")]
        if (len(controls) != 1 or tuple(controls[0]["bbox"][k] for k in ("x", "y", "w", "h"))
                != field.before.identity.control_bbox):
            raise PermissionError("fixture_text_field_not_exact")
        return "text"

    def verify_state(self, checked, state):
        if state.get("value") != checked["text_field_local"].before.value:
            raise PermissionError("fixture_text_value_changed")

    def grant_details(self, checked):
        parameters, field = checked["text_input_local"], checked["text_field_local"]
        return {"text": {"field_id": parameters.reviewed.target_field_id,
            "source_kind": parameters.reviewed.content.kind, "source_value": parameters.reviewed.content.value,
            "before": field.before.value, "value": parameters.text}}


class FixtureReviewDriver(QObject):
    def __init__(self, dialog, scope, view, grant_path, log_path):
        super().__init__(dialog)
        self.dialog, self.scope, self.pinned = dialog, scope, deepcopy(view)
        self.grant_path, self.log_path = Path(grant_path), Path(log_path)
        self.stage, self.error, self.grant = "waiting_operator", None, None
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def log(self, stage):
        self.stage = stage
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), "stage": stage,
                 "actor": "authorized_fixture_test_operator", "human_approval": False,
                 "confirmation_id": self.pinned["confirmation_id"], "error": self.error}
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def verify(self):
        self.scope.verify_review(self.dialog.preview_widget.review, self.pinned, self.grant)

    def semantic_action(self):
        """返回首次学习预览中的动作；已审核预览由受限子类改写读取路径。"""
        return self.pinned["preview"]["intent"]["semantic_action"]

    def tick(self):
        dialog = self.dialog
        try:
            if self.stage == "waiting_operator":
                if dialog._jobs or not self.grant_path.exists():
                    return
                self.grant = json.loads(self.grant_path.read_text(encoding="utf-8"))
                self.verify()
                if not dialog.approve_button.isEnabled():
                    raise RuntimeError("fixture_approval_button_unavailable")
                dialog.showMinimized()
                self.scope.focus()
                self.log("approval_button")
                dialog.approve_button.click()
            elif self.stage == "approval_button" and not dialog._jobs:
                self.verify()
                if dialog._phase != "approved" or not dialog.execute_button.isEnabled():
                    raise RuntimeError("fixture_approval_failed")
                self.log("execution_dialog")
                self.timer.stop()
                QTimer.singleShot(50, self.poll_confirmation)
                dialog.execute_button.click()
                if self.error is None:
                    self.timer.start()
            elif self.stage == "execution_dialog":
                box = next((box for box in dialog.findChildren(QMessageBox) if box.isVisible()), None)
                if box is None:
                    return
                self.verify()
                expected = f"将对 HWND {self.scope.handle} / PID {self.scope.pid} 执行："
                if (box.parent() is not dialog or box.windowTitle() != "确认执行这一步"
                        or not box.text().startswith(expected + self.semantic_action() + "。")):
                    raise PermissionError("fixture_execution_dialog_changed")
                self.log("execution_confirmed")
                box.button(QMessageBox.StandardButton.Yes).click()
                QTimer.singleShot(100, self.focus_after_confirmation)
            elif self.stage == "execution_confirmed" and not dialog._jobs:
                self.log("execution_returned")
                self.timer.stop()
                dialog.close()
        except Exception as error:
            self.error = type(error).__name__ + ": " + str(error)
            self.log("failed")
            self.timer.stop()
            for box in dialog.findChildren(QMessageBox):
                if box.isVisible():
                    box.reject()
            dialog._stop_wait()
            dialog.close()

    def poll_confirmation(self):
        if self.stage == "execution_dialog":
            self.tick()
            if self.stage == "execution_dialog":
                QTimer.singleShot(50, self.poll_confirmation)

    def focus_after_confirmation(self):
        try:
            self.scope.focus()
        except Exception as error:
            self.error = type(error).__name__ + ": " + str(error)
            self.log("focus_failed")
            self.timer.stop()
            self.dialog._stop_wait()
            self.dialog.close()
