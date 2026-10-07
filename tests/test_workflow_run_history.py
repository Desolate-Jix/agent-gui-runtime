"""普通运行页逐步呈现原账本结果，不用派发成功冒充核验通过。"""
from copy import deepcopy

from tests.test_workflow_run_panel import panel, connect, wait, PROGRAM
from tests.test_workflow_trial import services
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_verification_wait_metrics import waiting_scene, review_and_continue


def snapshot():
    return {"run_id": "run-current", "workflow_id": "workflow-1", "program_id": "program-1",
        "runner_state": "waiting", "status": "pending", "current_step_id": "verify",
        "wait_reason": "verification_required", "pending": {"step_id": "verify", "execution_request_id": "exec-verify"},
        "history": [
            {"step_id": "read", "execution_request_id": "exec-read", "verdict": "success", "judged_by": "rule"},
            {"step_id": "fill", "execution_request_id": "exec-fill", "verdict": "uncertain", "judged_by": "agent",
             "input_route_succeeded": True}],
        "metrics": {"total_model_calls": None, "total_usage": None,
            "by_step": {"read": {"event_count": 1, "elapsed_ns": 250000000, "model_calls": {"total": 0}}}}}


def test_normal_refresh_shows_original_step_verdicts_sources_and_partial_metrics(tmp_path):
    app, widget, clients = panel(tmp_path)
    widget.set_context({**PROGRAM, "definition": {"steps": [
        {"step_id": "read", "title": "读取当前详情"}, {"step_id": "fill", "title": "填写详情"},
        {"step_id": "verify", "title": "核对结果"}]}}, "read")
    client = connect(app, widget, clients)
    original = snapshot()
    client.report = deepcopy(original)
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    table = widget.history_table
    assert table.rowCount() == 3
    assert [table.item(0, col).text() for col in range(5)] == ["读取当前详情", "通过", "规则核验", "0.250 秒", "0 次；总量未知"]
    assert table.item(1, 1).text() == "不确定"
    assert table.item(1, 2).text() == "Agent 判断"
    assert table.item(1, 3).text() == "未知"
    assert table.item(1, 4).text() == "未知"
    assert table.item(2, 1).text() == "等待核验"
    assert table.item(2, 2).text() == "尚未结算"
    assert widget._run == original
    assert not client.calls
    widget.close_client()


def test_new_run_clears_old_history_and_unavailable_metrics_do_not_show_stale_numbers(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    client.report = snapshot()
    client.report["metrics"]["status"] = "unavailable"
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert widget.history_table.item(0, 3).text() == "未知"
    assert widget.history_table.item(0, 4).text() == "未知"
    client.report = {"run_id": "new-run", "status": "ready", "history": [], "outputs": {}}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert widget.history_table.rowCount() == 0
    widget.close_client()


def test_run_history_does_not_borrow_titles_from_newer_program(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.set_context({**PROGRAM, "program_id": "new-version", "definition": {"steps": [
        {"step_id": "read", "title": "新版本的不同动作"}]}}, "read")
    client.report = snapshot()
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert widget.history_table.item(0, 0).text() == "第 1 步"
    assert "read" in widget.history_table.item(0, 0).toolTip()
    assert "新版本" not in widget.history_table.item(0, 0).text()
    widget.close_client()


def test_real_run_wait_metrics_are_grouped_by_original_step(runtime_scene, monkeypatch):
    runtime, trials, run, session, co, clock, ticket, waiting = waiting_scene(runtime_scene, monkeypatch)
    clock[0] = 500
    done = review_and_continue(runtime, trials, run, ticket, waiting)
    measured = done["metrics"]["by_step"]
    assert set(measured) == {"search"}
    assert measured["search"]["elapsed_ns"] == 400
    assert measured["search"]["phase_elapsed_ns"]["wait"] == 400
    assert measured["search"]["model_calls"]["total"] == 0
    assert measured["search"]["usage"] is None
    assert done["metrics"]["total_model_calls"] is None
