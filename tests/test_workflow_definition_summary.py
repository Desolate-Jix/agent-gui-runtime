"""定义摘要只描述载入版本，不把编辑或运行结果当成持久审核。"""
from copy import deepcopy

from test_workflow_steps_ui import generated, qt_app, _pane, _wait


def test_pending_definition_counts_memory_and_explicit_verification_separately():
    from app.learning_memory.workflow_definition_summary import summarize_definition
    snapshot = {"program_id": None, "definition": {"steps": [
        {"review_status": "pending", "action": {"kind": "click", "target_memory": {"recipe_id": "one"}},
         "verification": {"kind": "target_present"}},
        {"review_status": "pending", "action": {"kind": "input_sequence"},
         "verification": {"kind": "agent_judgment"}},
        {"review_status": "pending", "action": {"kind": "read_text"}},
    ]}}
    before = deepcopy(snapshot)
    summary = summarize_definition(snapshot)
    assert summary == {"saved": False, "total_steps": 3, "reviewed_steps": 0, "pending_steps": 3,
                       "target_memory_steps": 1, "target_applicable_steps": 2,
                       "verification_rule_steps": 1, "agent_judgment_steps": 1, "image_check_steps": 0}
    assert snapshot == before


def test_review_save_reopen_and_semantic_edit_preserve_summary_boundary(qt_app, generated):
    pane = _pane(qt_app, generated)
    assert hasattr(pane, "definition_summary")
    assert "草稿定义" in pane.definition_summary.text()
    pane.save_button.click()
    assert "已保存定义" in pane.definition_summary.text()
    assert "待审核 1" in pane.definition_summary.text()
    pane.review.setCurrentIndex(pane.review.findData("reviewed"))
    assert "有未保存修改，以下为已保存版本" in pane.definition_summary.text()
    assert "已审核 0" in pane.definition_summary.text()
    pane.save_button.click()
    assert "已审核 1" in pane.definition_summary.text()
    assert "已记录用量，请在运行页查看" in pane.definition_summary.text()
    assert "定位规则" in pane.definition_summary.text()
    assert "结果规则" in pane.definition_summary.text()
    assert "仅由 Agent 判断" in pane.definition_summary.text()
    assert "完整模型调用节省" in pane.definition_summary.toolTip()
    assert "部分调用" in pane.definition_summary.toolTip()
    pane.close()
    reopened = _pane(qt_app, generated)
    assert "已审核 1" in reopened.definition_summary.text()
    reopened.field_goal.setText("新的字段目标")
    assert "已审核 1" in reopened.definition_summary.text()
    reopened.save_button.click()
    assert not reopened.dirty
    assert "已审核 0" in reopened.definition_summary.text()
    assert "待审核 1" in reopened.definition_summary.text()
    reopened.close()


def test_empty_switch_and_failed_read_do_not_retain_old_summary(qt_app, generated, monkeypatch):
    pane = _pane(qt_app, generated)
    assert hasattr(pane, "definition_summary")
    pane.save_button.click()
    pane._install_projects([])
    assert "尚无任务定义" in pane.definition_summary.text()
    pane._install(pane.facade.load_workflow_program(generated[2]))
    assert "共 1 步" in pane.definition_summary.text()
    def fail(_workflow_id):
        raise ValueError("summary_read_failure")
    monkeypatch.setattr(pane.facade, "load_workflow_program", fail)
    pane.open_project("another-project")
    assert "正在读取任务定义" in pane.definition_summary.text()
    assert "共 1 步" not in pane.definition_summary.text()
    _wait(qt_app, lambda: not pane.is_busy)
    assert "任务定义读取失败" in pane.definition_summary.text()
    assert "共 1 步" not in pane.definition_summary.text()
    pane.close()
