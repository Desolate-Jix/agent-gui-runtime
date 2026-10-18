"""主窗口选择上游结果并保存重开；用合成回执核对本次数据流。"""
from hashlib import sha256
import json
import os
from types import SimpleNamespace

from PIL import Image
from PySide6.QtWidgets import QTableWidgetItem

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workflow_runtime import WorkflowRuntime
from app.learning_memory.workspace import MemoryWorkspace
from tests.test_workflow_guided_journey import _source_and_session
from tests.test_workflow_guided_values import _choose
from tests.test_workflow_steps_ui import qt_app
from tests.test_workflow_trial import response
from tests.test_workflow_user_journey import _run_main


def test_main_selects_prior_output_and_saved_program_only_uses_current_read(monkeypatch, qt_app, tmp_path):
    session = _source_and_session(tmp_path)
    saved = {}

    def edit(window):
        pane = window.steps
        pane.open_learning_button.click()
        pane.add_button.click()
        _choose(pane.action_kind, "read_text")
        pane.step_title.setText("读取当前状态")
        pane.goal.setText("读取当前记录状态")
        read_id = pane._selected_id
        pane.add_output.click()
        pane.outputs.setItem(0, 0, QTableWidgetItem("status"))
        rules = pane.rules_editor
        _choose(rules.read_method, "agent_read")
        rules.target_type.setText("Text")
        rules.target_name.setText("当前状态")
        rules.read_output.setCurrentText("status")
        pane.add_button.click()
        fill_id = pane._selected_id
        _choose(pane.action_kind, "input_sequence")
        pane.step_title.setText("填写本次状态")
        pane.field_goal.setText("状态接收字段")
        _choose(pane.text_source, "output")
        reference = {"source": "output", "step_id": read_id, "name": "status"}
        _choose(pane.text_binding, reference)
        pane.steps.setCurrentRow(1)
        _choose(pane.success, fill_id)
        pane.steps.setCurrentRow(0)
        _choose(pane.success, read_id)
        pane.save_button.click()
        assert not pane.dirty, pane.status.text()
        saved.update(snapshot=pane.snapshot, read_id=read_id, fill_id=fill_id, reference=reference)
        assert not list((session / "commands").glob("*.json"))

    _run_main(monkeypatch, qt_app, tmp_path, edit, session=session)

    def reopen(window):
        pane = window.steps
        assert pane.snapshot == saved["snapshot"]
        pane.steps.setCurrentRow(2)
        assert pane.text_binding.currentData() == saved["reference"]
        assert "读取当前状态" in pane.text_binding.currentText()
        # 合成回执只验证保存定义的数据关系，不执行或证明任何物理动作。
        with MemoryWorkspace(tmp_path / "memory-library") as library:
            trials = TrialService(library, session)
            program = pane.snapshot
            blocked = trials.start(program["workflow_id"], program["program_id"], saved["fill_id"], {}, "missing-start")
            result = trials.prepare(blocked["run_id"], "missing-prepare")
            assert result["status"] == "blocked" and result["input_executed"] is False
            pane.open_run_button.click()
            pane.run_panel._show_run({**trials.status(blocked["run_id"]), "runner_state": "waiting", "wait_reason": "input_required"})
            assert "读取当前状态" in pane.run_panel.wait_label.text()
            assert "status" in pane.run_panel.wait_label.text()
            assert not list((session / "commands").glob("*.json"))
            trials.cancel(blocked["run_id"], "cancel-missing")

        runtime = WorkflowRuntime(session, SimpleNamespace(_memory_library_root=tmp_path / "memory-library"))
        for index, value in enumerate(("本次状态甲", "本次状态乙")):
            with MemoryWorkspace(tmp_path / "memory-library") as library:
                trials = TrialService(library, session)
                run = trials.start(program["workflow_id"], program["program_id"], saved["read_id"], {}, f"read-start-{index}")
            reading = runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, f"run-{index}")
            assert reading["wait_reason"] == "execution_pending"
            ticket = reading["pending"]
            assert ticket["suggested_command"]["kind"] == "read_text"
            image_path = session / f"read-current-{index}.png"
            Image.new("RGB", (100, 80), (index * 70, 120, 240)).save(image_path)
            capture = {"image_path": str(image_path), "sha256": sha256(image_path.read_bytes()).hexdigest(),
                       "capture_id": f"synthetic-current-{index}"}
            command_id = ticket["execution_request_id"]
            assert json.loads((session / "commands" / f"{command_id}.json").read_text(encoding="utf-8")) == ticket["suggested_command"]
            write_json_snapshot(session / "responses" / f"{command_id}.json", {
                "command": ticket["suggested_command"], "status": "returned", "observation": capture,
                "result": {"status": "agent_read_required", "action_executed": False}})
            with MemoryWorkspace(tmp_path / "memory-library") as library:
                trials = TrialService(library, session)
                trials.review(run["run_id"], f"read-review-{index}", command_id, "success", {}, {"status": value})
            filling = runtime.tick(force=True)
            assert filling["wait_reason"] == "execution_pending"
            fill = filling["pending"]
            queued = json.loads((session / "commands" / (fill["execution_request_id"] + ".json")).read_text(encoding="utf-8"))
            assert queued == fill["suggested_command"]
            assert queued["request"]["text"] == value
            assert queued["request"]["field_goal"] == "状态接收字段"
            response(session, fill)
            with MemoryWorkspace(tmp_path / "memory-library") as library:
                trials = TrialService(library, session)
                completed = trials.review(run["run_id"], f"fill-review-{index}", fill["execution_request_id"], "success", {}, {})
                assert completed["status"] == "completed"
                assert completed["outputs"][saved["read_id"] + ".status"] == value
                assert completed["history"][0]["read_observation"]["capture_id"] == capture["capture_id"]
            final = runtime.tick(force=True)
            assert final["runner_state"] == "completed"
            pane.run_panel._show_run(final)
            assert value in pane.run_panel.outputs.toPlainText()
            history = pane.run_panel.history_table
            assert history.rowCount() == 2
            assert [history.item(row, 1).text() for row in range(2)] == ["通过", "通过"]
            assert [history.item(row, 2).text() for row in range(2)] == ["Agent 判断", "Agent 判断"]
            assert history.item(0, 0).text() == "读取当前状态"
            assert history.item(0, 4).text() == "未知"
            if os.environ.get("WORKFLOW_HISTORY_CAPTURE"):
                pane.editor_tabs.setCurrentWidget(pane.run_panel)
                qt_app.processEvents()
                assert window.grab().save(os.environ["WORKFLOW_HISTORY_CAPTURE"])
        with MemoryWorkspace(tmp_path / "memory-library") as library:
            trials = TrialService(library, session)
            fresh = trials.start(program["workflow_id"], program["program_id"], saved["fill_id"], {}, "fresh-missing")
            again = trials.prepare(fresh["run_id"], "fresh-prepare")
            assert again["status"] == "blocked" and fresh["outputs"] == {}
            trials.cancel(fresh["run_id"], "cancel-fresh")
        output = os.environ.get("WORKFLOW_GUIDED_CAPTURE_DIR")
        if output:
            from pathlib import Path
            pane.editor_tabs.setCurrentIndex(0)
            qt_app.processEvents()
            assert window.grab().save(str(Path(output) / "guided-output-main.png"))

    _run_main(monkeypatch, qt_app, tmp_path, reopen, session=session)
