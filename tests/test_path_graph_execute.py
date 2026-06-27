from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.execute as execute_api
from app.execute.available_actions import build_available_actions
from app.execute.path_graph_step import build_execute_step_plan
from app.learn.path_graph_artifacts import build_seek_runtime_path_graph_export
from app.learn.path_graph_resolver import resolve_runtime_path_graph
from app.main import app
from app.models.response import APIResponse
from app.seek.learn_artifacts import build_seek_learn_artifacts


def _event(index: int) -> dict:
    return {
        "index": index,
        "job_id": f"job-{index}",
        "card": {
            "title": f"Software Engineer {index}",
            "company": "Example Co",
            "location": "Auckland",
            "card_bbox": {"x": 24, "y": 400 + index * 12, "w": 410, "h": 220},
            "click_point": {"x": 220, "y": 510 + index * 12},
        },
        "detail_read": {
            "title": f"Software Engineer {index}",
            "company": "Example Co",
            "complete": True,
        },
    }


def _runtime_graph() -> dict:
    report = {
        "contract_version": "seek_mvp_run_report_v1",
        "jobs_seen": 5,
        "jobs_opened": 5,
        "jobs_fully_read": 5,
        "submit_clicks": 0,
        "final_submissions": 0,
        "accuracy_summary": {
            "status": "pass",
            "post_click_layout_drift_count": 0,
            "wrong_scope_scroll_count": 0,
        },
        "traversal_steps": [_event(index) for index in range(5)],
    }
    artifact = build_seek_learn_artifacts(report)
    return build_seek_runtime_path_graph_export(artifact)["runtime_path_graph"]


def _generic_runtime_graph() -> dict:
    return {
        "contract_version": "runtime_path_graph_v1",
        "graph_id": "generic_search_runtime_path_graph_v1",
        "app_id": "generic_web",
        "page_type": "search_results_with_detail",
        "coordinate_policy": {"coordinate_space": "window_screenshot"},
        "states": [{"state_id": "search_results"}],
        "transitions": [
            {"from_state_id": "search_results", "to_state_id": "detail_open", "action_template_id": "open_result"},
            {"from_state_id": "search_results", "to_state_id": "results_scrolled", "action_template_id": "scroll_results"},
            {"from_state_id": "search_results", "to_state_id": "search_results", "action_template_id": "input_search_query"},
        ],
        "action_templates": [
            {
                "action_template_id": "open_result",
                "action_type": "click",
                "goal_template": "Open the selected search result",
                "learned_skill_ref": "skill.open_card_from_list",
            },
            {
                "action_template_id": "scroll_results",
                "action_type": "scroll",
                "scroll_target": {"target_container_id": "generic:results_list", "target_pane": "results_list"},
                "learned_skill_ref": "skill.scroll_container_until_new_content",
            },
            {
                "action_template_id": "input_search_query",
                "action_type": "input",
                "input_target": {"role": "searchbox", "click_point": {"x": 180, "y": 96}},
                "input_policy": {"requires_agent_text": True, "clear_existing": True, "submit_allowed": False},
                "learned_skill_ref": "skill.input_text_into_field",
            },
        ],
    }


def test_resolver_matches_seek_graph_and_rejects_final_submit_inventory() -> None:
    graph = _runtime_graph()

    matched = resolve_runtime_path_graph(
        graph,
        requested_state_id="seek_search_results_with_selected_job",
        screen_inventory={"available_actions": [{"label": "Apply"}]},
        safety={"forbid_final_submit": True, "allow_apply_entry": False, "allow_safe_fill": False},
    )
    rejected = resolve_runtime_path_graph(
        graph,
        requested_state_id="seek_search_results_with_selected_job",
        screen_inventory={"available_actions": [{"label": "Submit application"}]},
        safety={"forbid_final_submit": True, "allow_apply_entry": False, "allow_safe_fill": False},
    )

    assert matched["contract_version"] == "path_graph_resolution_v1"
    assert matched["matched"] is True
    assert matched["artifact_is_authorization"] is False
    assert "seek:results_list_container_found" in matched["matched_evidence"]
    assert rejected["matched"] is False
    assert "final_submit_visible" in rejected["reject_reasons"]


def test_execute_step_plan_builds_scroll_and_click_contexts() -> None:
    graph = _runtime_graph()

    scroll_plan = build_execute_step_plan(
        graph,
        {"action_template_id": "read_detail", "action_id": "read_detail"},
        state_id="seek_search_results_with_selected_job",
        dry_run=True,
    )
    click_plan = build_execute_step_plan(
        graph,
        {"action_template_id": "open_job_card", "action_id": "open_job_card", "target_entity_id": "job-1"},
        state_id="seek_search_results_empty_detail",
        dry_run=True,
    )

    assert scroll_plan["contract_version"] == "execute_step_response_v1"
    assert scroll_plan["low_level_action_type"] == "scroll"
    assert scroll_plan["action_taxonomy"]["kind"] == "read"
    assert scroll_plan["low_level_request"]["target_container_id"] == "seek:job_detail"
    assert scroll_plan["path_graph_action_context"]["contract_version"] == "path_graph_action_context_v1"
    assert scroll_plan["path_graph_action_context"]["artifact_is_authorization"] is False
    assert scroll_plan["path_graph_runtime_state_v1"]["contract_version"] == "path_graph_runtime_state_v1"
    assert scroll_plan["path_graph_runtime_state_v1"]["before_state_id"] == "seek_search_results_with_selected_job"
    assert scroll_plan["path_graph_runtime_state_v1"]["action_template_id"] == "read_detail"
    assert click_plan["low_level_action_type"] == "click"
    assert click_plan["action_taxonomy"]["kind"] == "open_detail"
    assert click_plan["low_level_request"]["metadata"]["path_graph_action_context"]["requires_gate"] is True
    assert click_plan["low_level_request"]["metadata"]["artifact_is_authorization"] is False


def test_execute_available_actions_and_step_api() -> None:
    client = TestClient(app)
    graph = _runtime_graph()

    available_response = client.post(
        "/execute/available_actions",
        json={
            "runtime_path_graph": graph,
            "current_state_id": "seek_search_results_with_selected_job",
            "screen_inventory": {"available_actions": [{"label": "Apply"}, {"label": "Save"}]},
            "safety": {"forbid_final_submit": True, "allow_apply_entry": False, "allow_safe_fill": False},
        },
    )
    available_payload = available_response.json()

    assert available_response.status_code == 200
    assert available_payload["success"] is True
    data = available_payload["data"]
    assert data["contract_version"] == "available_actions_response_v1"
    assert data["path_graph_resolution"]["matched"] is True
    action_ids = {item["action_template_id"] for item in data["available_actions"]["actions"]}
    assert {"read_detail", "load_more_results"} <= action_ids
    assert "apply_entry" not in action_ids
    assert data["available_actions"]["artifact_is_authorization"] is False
    assert data["trace_path"]

    selected_action = next(item for item in data["available_actions"]["actions"] if item["action_template_id"] == "read_detail")
    assert selected_action["transition_id"] == "seek:transition:read_detail"
    assert selected_action["from_state_id"] == "seek_search_results_with_selected_job"
    assert selected_action["to_state_id"] == "seek_detail_scrolled"
    assert selected_action["action_taxonomy"]["kind"] == "read"
    assert selected_action["safety"]["final_submit"] is False
    step_response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "available_actions_trace_path": data["trace_path"],
            "path_graph_resolution": data["path_graph_resolution"],
            "selected_action": selected_action,
            "dry_run": True,
        },
    )
    step_payload = step_response.json()

    assert step_response.status_code == 200
    assert step_payload["success"] is True
    step_data = step_payload["data"]
    assert step_data["contract_version"] == "execute_step_response_v1"
    assert step_data["path_graph_assisted"] is True
    assert step_data["low_level_action_type"] == "scroll"
    assert step_data["low_level_request"]["target_container_id"] == "seek:job_detail"
    assert step_data["path_graph_action_context"]["artifact_is_authorization"] is False
    assert step_data["path_graph_runtime_state_v1"]["before_state_id"] == "seek_search_results_with_selected_job"
    assert step_data["path_graph_runtime_state_v1"]["action_template_id"] == "read_detail"
    assert step_data["path_graph_runtime_state_v1"]["low_level_action_type"] == "scroll"
    assert step_data["execute_step_trace_path"]


def test_available_actions_include_click_scroll_and_input_skill_kinds() -> None:
    graph = _generic_runtime_graph()

    available = build_available_actions(graph, current_state_id="search_results")

    assert available["contract_version"] == "available_actions_v1"
    actions = {item["action_template_id"]: item for item in available["actions"]}
    assert actions["open_result"]["action_kind"] == "click"
    assert actions["open_result"]["low_level_action_type"] == "click"
    assert actions["scroll_results"]["action_kind"] == "scroll"
    assert actions["scroll_results"]["low_level_action_type"] == "scroll"
    assert actions["scroll_results"]["scroll_container_id"] == "generic:results_list"
    assert actions["input_search_query"]["action_kind"] == "input"
    assert actions["input_search_query"]["low_level_action_type"] == "input"
    assert actions["input_search_query"]["input_policy"]["requires_agent_text"] is True
    assert available["artifact_is_authorization"] is False


def test_open_search_action_without_declared_type_is_click_not_input() -> None:
    graph = _generic_runtime_graph()
    graph["transitions"].append(
        {"from_state_id": "search_results", "to_state_id": "detail_open", "action_template_id": "open_search_result"}
    )
    graph["action_templates"].append(
        {
            "action_template_id": "open_search_result",
            "goal_template": "Open a search result from the list",
            "learned_skill_ref": "skill.open_result_from_search_list",
        }
    )

    available = build_available_actions(graph, current_state_id="search_results")
    actions = {item["action_template_id"]: item for item in available["actions"]}

    assert actions["open_search_result"]["action_kind"] == "click"
    assert actions["open_search_result"]["low_level_action_type"] == "click"


def test_execute_step_plan_builds_input_request_from_generic_skill() -> None:
    graph = _generic_runtime_graph()

    plan = build_execute_step_plan(
        graph,
        {
            "action_template_id": "input_search_query",
            "action_id": "input_search_query",
            "input_text": "software engineer",
        },
        state_id="search_results",
        dry_run=True,
    )
    missing_text_plan = build_execute_step_plan(
        graph,
        {"action_template_id": "input_search_query", "action_id": "input_search_query"},
        state_id="search_results",
        dry_run=True,
    )

    assert plan["contract_version"] == "execute_step_response_v1"
    assert plan["status"] == "planned"
    assert plan["low_level_action_type"] == "input"
    assert plan["low_level_request"]["text"] == "software engineer"
    assert plan["low_level_request"]["x"] == 180
    assert plan["low_level_request"]["y"] == 96
    assert plan["low_level_request"]["click_before_typing"] is True
    assert plan["low_level_request"]["clear_existing"] is True
    assert plan["low_level_request"]["submit"] is False
    assert plan["low_level_request"]["metadata"]["path_graph_action_context"]["skill_ref"] == "skill.input_text_into_field"
    assert missing_text_plan["status"] == "rejected"
    assert missing_text_plan["low_level_action_type"] == "input"
    assert missing_text_plan["reject_reasons"] == ["missing_input_text"]


def test_execute_step_plan_uses_page_scroll_for_generic_page_container() -> None:
    graph = _generic_runtime_graph()
    graph["transitions"].append(
        {"from_state_id": "search_results", "to_state_id": "detail_scrolled", "action_template_id": "read_page"}
    )
    graph["action_templates"].append(
        {
            "action_template_id": "read_page",
            "action_type": "scroll",
            "scroll_target": {"target_container_id": "generic:page", "target_pane": "page"},
            "learned_skill_ref": "skill.read_detail_page_until_bounded",
        }
    )

    plan = build_execute_step_plan(
        graph,
        {"action_template_id": "read_page", "action_id": "read_page"},
        state_id="search_results",
        dry_run=True,
    )

    assert plan["status"] == "planned"
    assert plan["low_level_action_type"] == "scroll"
    assert plan["low_level_request"]["scroll_scope"] == "page"
    assert plan["low_level_request"]["target_pane"] == "page"
    assert plan["low_level_request"]["target_container_id"] is None


def test_github_issues_graph_available_actions_and_page_scroll_plan() -> None:
    graph = json.loads(Path("artifacts/github/runtime_path_graph_github_issues_v1.json").read_text(encoding="utf-8"))

    available = build_available_actions(graph, current_state_id="github_issue_detail")
    actions = {item["action_template_id"]: item for item in available["actions"]}

    assert "read_issue_detail" in actions
    assert actions["read_issue_detail"]["action_kind"] == "read"
    assert actions["read_issue_detail"]["low_level_action_type"] == "scroll"
    assert actions["read_issue_detail"]["scroll_container_id"] == "github:page"

    plan = build_execute_step_plan(
        graph,
        {"action_template_id": "read_issue_detail", "action_id": "read_issue_detail"},
        state_id="github_issue_detail",
        dry_run=True,
    )

    assert plan["status"] == "planned"
    assert plan["path_graph_action_context"]["skill_ref"] == "skill.read_detail_page_until_bounded"
    assert plan["low_level_action_type"] == "scroll"
    assert plan["low_level_request"]["scroll_scope"] == "page"
    assert plan["low_level_request"]["target_pane"] == "page"
    assert plan["low_level_request"]["target_container_id"] is None


def test_python_docs_search_available_actions_by_state() -> None:
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))

    search_page = build_available_actions(graph, current_state_id="docs:search_page")
    results_page = build_available_actions(graph, current_state_id="docs:search_results")
    article_page = build_available_actions(graph, current_state_id="docs:article_page")

    search_actions = {item["action_template_id"]: item for item in search_page["actions"]}
    result_actions = {item["action_template_id"]: item for item in results_page["actions"]}
    article_actions = {item["action_template_id"]: item for item in article_page["actions"]}
    assert set(search_actions) == {"type_public_search_query", "trigger_search"}
    assert search_actions["type_public_search_query"]["low_level_action_type"] == "input"
    assert search_actions["type_public_search_query"]["input_policy"]["submit_allowed"] is True
    assert search_actions["trigger_search"]["low_level_action_type"] == "click"
    assert set(result_actions) == {"open_search_result"}
    assert result_actions["open_search_result"]["low_level_action_type"] == "click"
    assert set(article_actions) == {"read_article"}
    assert article_actions["read_article"]["low_level_action_type"] == "scroll"
    assert article_actions["read_article"]["scroll_container_id"] == "docs:page"
    assert search_page["artifact_is_authorization"] is False


def test_python_docs_search_execute_step_plans_input_and_page_scroll_dry_run() -> None:
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))
    available = build_available_actions(graph, current_state_id="docs:search_page")
    input_action = next(item for item in available["actions"] if item["action_template_id"] == "type_public_search_query")
    input_action["input_text"] = "list comprehension"

    input_plan = build_execute_step_plan(
        graph,
        input_action,
        state_id="docs:search_page",
        dry_run=True,
    )
    missing_text_plan = build_execute_step_plan(
        graph,
        {"action_template_id": "type_public_search_query", "action_id": "type_public_search_query"},
        state_id="docs:search_page",
        dry_run=True,
    )
    scroll_plan = build_execute_step_plan(
        graph,
        {"action_template_id": "read_article", "action_id": "read_article"},
        state_id="docs:article_page",
        dry_run=True,
    )

    assert input_plan["status"] == "planned"
    assert input_plan["low_level_action_type"] == "input"
    assert input_plan["low_level_request"]["text"] == "list comprehension"
    assert input_plan["low_level_request"]["submit"] is False
    assert input_plan["low_level_request"]["dry_run"] is True
    assert input_plan["path_graph_action_context"]["artifact_is_authorization"] is False
    assert missing_text_plan["status"] == "rejected"
    assert missing_text_plan["reject_reasons"] == ["missing_input_text"]
    assert scroll_plan["status"] == "planned"
    assert scroll_plan["low_level_action_type"] == "scroll"
    assert scroll_plan["low_level_request"]["scroll_scope"] == "page"
    assert scroll_plan["low_level_request"]["target_container_id"] is None
    assert scroll_plan["low_level_request"]["target_pane"] == "page"


def test_table_directory_graph_available_actions_and_step_plans() -> None:
    graph = json.loads(Path("artifacts/table_directory/runtime_path_graph_table_directory_v1.json").read_text(encoding="utf-8"))

    list_page = build_available_actions(graph, current_state_id="table:list_page")
    filtered_page = build_available_actions(graph, current_state_id="table:list_filtered")
    detail_page = build_available_actions(graph, current_state_id="table:record_detail")

    list_actions = {item["action_template_id"]: item for item in list_page["actions"]}
    filtered_actions = {item["action_template_id"]: item for item in filtered_page["actions"]}
    detail_actions = {item["action_template_id"]: item for item in detail_page["actions"]}
    assert {"switch_filter_tab", "open_record_from_table", "load_more_records"} <= set(list_actions)
    assert "blocked_write_action" not in list_actions
    assert filtered_actions["sort_records"]["low_level_action_type"] == "click"
    assert list_actions["switch_filter_tab"]["low_level_action_type"] == "click"
    assert list_actions["open_record_from_table"]["low_level_action_type"] == "click"
    assert detail_actions["read_record_detail"]["action_kind"] == "read"
    assert detail_actions["read_record_detail"]["low_level_action_type"] == "scroll"

    open_plan = build_execute_step_plan(
        graph,
        {"action_template_id": "open_record_from_table", "action_id": "open_record_from_table"},
        state_id="table:list_page",
        dry_run=True,
    )
    read_plan = build_execute_step_plan(
        graph,
        {"action_template_id": "read_record_detail", "action_id": "read_record_detail"},
        state_id="table:record_detail",
        dry_run=True,
    )
    load_more_plan = build_execute_step_plan(
        graph,
        {"action_template_id": "load_more_records", "action_id": "load_more_records"},
        state_id="table:list_page",
        dry_run=True,
    )

    assert open_plan["status"] == "planned"
    assert open_plan["low_level_action_type"] == "click"
    assert open_plan["path_graph_action_context"]["skill_ref"] == "skill:open_record_from_table"
    assert open_plan["path_graph_action_context"]["artifact_is_authorization"] is False
    assert read_plan["low_level_action_type"] == "scroll"
    assert read_plan["low_level_request"]["scroll_scope"] == "page"
    assert read_plan["low_level_request"]["target_pane"] == "page"
    assert read_plan["low_level_request"]["target_container_id"] is None
    assert load_more_plan["low_level_action_type"] == "scroll"
    assert load_more_plan["low_level_request"]["scroll_scope"] == "container"
    assert load_more_plan["low_level_request"]["target_container_id"] == "table:records_list"


def test_execute_step_dispatches_scroll_with_path_graph_context(monkeypatch) -> None:
    client = TestClient(app)
    graph = _runtime_graph()
    selected_action = {"action_template_id": "read_detail", "action_id": "read_detail"}

    def fake_scroll(request):
        assert request.metadata["path_graph_action_context"]["action_template_id"] == "read_detail"
        assert request.metadata["path_graph_action_context"]["artifact_is_authorization"] is False
        return APIResponse(
            success=True,
            message="Scroll dry-run validated",
            data={"action": "scroll", "result": {"trace_path": "logs/traces/actions/scroll.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_scroll", fake_scroll)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "path_graph_resolution": {"state_id": "seek_search_results_with_selected_job"},
            "selected_action": selected_action,
            "dry_run": True,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "dispatched"
    assert data["dispatch_low_level_executed"] is True
    assert data["low_level_trace_path"] == "logs/traces/actions/scroll.json"
    assert data["low_level_response"]["success"] is True


def test_execute_step_dispatches_click_through_recognition_gate(monkeypatch) -> None:
    client = TestClient(app)
    graph = _runtime_graph()
    selected_action = {
        "action_template_id": "open_job_card",
        "action_id": "open_job_card",
        "target_entity_id": "seek:job_card",
    }

    def fake_recognition_plan(request):
        metadata = request.metadata
        assert request.agent_mode == "execute"
        assert request.dry_run is True
        assert metadata["path_graph_action_context"]["action_template_id"] == "open_job_card"
        assert metadata["path_graph_action_context"]["requires_gate"] is True
        assert metadata["forbid_final_submit"] is True
        assert metadata["artifact_is_authorization"] is False
        return APIResponse(
            success=True,
            message="Recognition dry-run validated",
            data={"result": {"trace_path": "logs/traces/actions/recognition.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_recognition_plan", fake_recognition_plan)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "path_graph_resolution": {"state_id": "seek_search_results_empty_detail"},
            "selected_action": selected_action,
            "dry_run": True,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "dispatched"
    assert data["dispatch_low_level_executed"] is True
    assert data["low_level_trace_path"] == "logs/traces/actions/recognition.json"


def test_execute_step_dispatches_input_through_type_text(monkeypatch) -> None:
    client = TestClient(app)
    graph = _generic_runtime_graph()
    selected_action = {
        "action_template_id": "input_search_query",
        "action_id": "input_search_query",
        "input_text": "software engineer",
    }

    def fake_type_text(request):
        assert request.text == "software engineer"
        assert request.submit is False
        assert request.metadata["path_graph_action_context"]["action_template_id"] == "input_search_query"
        assert request.metadata["path_graph_action_context"]["artifact_is_authorization"] is False
        return APIResponse(
            success=True,
            message="Text input dry-run validated",
            data={"action": "type_text", "result": {"trace_path": "logs/traces/actions/type_text.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_type_text", fake_type_text)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "path_graph_resolution": {"state_id": "search_results"},
            "selected_action": selected_action,
            "dry_run": True,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "dispatched"
    assert data["dispatch_low_level_executed"] is True
    assert data["low_level_trace_path"] == "logs/traces/actions/type_text.json"
    assert data["low_level_response"]["success"] is True


def test_execute_step_blocks_live_input_without_explicit_public_input_permission() -> None:
    client = TestClient(app)
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))
    selected_action = {
        "action_template_id": "type_public_search_query",
        "action_id": "type_public_search_query",
        "input_text": "list comprehension",
    }

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "path_graph_resolution": {"state_id": "docs:search_page"},
            "selected_action": selected_action,
            "safety": {"forbid_final_submit": True, "allow_live_input": False},
            "dry_run": False,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "blocked_by_input_gate"
    assert data["dispatch_low_level_executed"] is False
    assert data["dispatch_low_level_blocked_reason"] == "live_input_not_enabled"
    assert data["live_input_gate"]["input_category"] == "public_search_query"


def test_execute_step_allows_live_public_search_input_when_explicitly_enabled(monkeypatch) -> None:
    client = TestClient(app)
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))
    selected_action = {
        "action_template_id": "type_public_search_query",
        "action_id": "type_public_search_query",
        "input_text": "list comprehension",
    }

    def fake_type_text(request):
        assert request.text == "list comprehension"
        assert request.submit is False
        assert request.dry_run is False
        assert request.metadata["input_category"] == "public_search_query"
        assert request.metadata["safety"]["allow_live_input"] is True
        return APIResponse(
            success=True,
            message="Public search input dispatched",
            data={"action": "type_text", "result": {"trace_path": "logs/traces/actions/python_docs_type_text.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_type_text", fake_type_text)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "path_graph_resolution": {"state_id": "docs:search_page"},
            "selected_action": selected_action,
            "safety": {
                "forbid_final_submit": True,
                "allow_live_input": True,
                "allowed_input_categories": ["public_search_query"],
            },
            "dry_run": False,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "dispatched"
    assert data["dispatch_low_level_executed"] is True
    assert data["low_level_trace_path"] == "logs/traces/actions/python_docs_type_text.json"


def test_execute_step_resolves_requested_input_action_from_path_graph(monkeypatch) -> None:
    client = TestClient(app)
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))

    def fake_type_text(request):
        assert request.text == "list comprehension"
        assert request.x == 575
        assert request.y == 352
        assert request.click_before_typing is True
        assert request.clear_existing is True
        assert request.submit is False
        assert request.metadata["path_graph_action_context"]["action_template_id"] == "type_public_search_query"
        assert request.metadata["input_category"] == "public_search_query"
        return APIResponse(
            success=True,
            message="Public search input dispatched",
            data={"action": "type_text", "result": {"trace_path": "logs/traces/actions/python_docs_type_text.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_type_text", fake_type_text)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "current_state_id": "docs:search_page",
            "requested_action_id": "type_public_search_query",
            "input_text": "list comprehension",
            "target_point": {"x": 575, "y": 352},
            "clear_existing": True,
            "safety": {
                "forbid_final_submit": True,
                "allow_live_input": True,
                "allowed_input_categories": ["public_search_query"],
            },
            "dry_run": False,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "dispatched"
    assert data["action_template_id"] == "type_public_search_query"
    assert data["low_level_action_type"] == "input"
    assert data["dispatch_low_level_executed"] is True


def test_execute_step_uses_path_graph_input_target_point_without_override(monkeypatch) -> None:
    client = TestClient(app)
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))

    def fake_type_text(request):
        assert request.text == "list comprehension"
        assert request.x == 404
        assert request.y == 283
        assert request.click_before_typing is True
        assert request.clear_existing is True
        return APIResponse(
            success=True,
            message="Public search input dispatched",
            data={"action": "type_text", "result": {"trace_path": "logs/traces/actions/python_docs_type_text.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_type_text", fake_type_text)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "current_state_id": "docs:search_page",
            "requested_action_id": "type_public_search_query",
            "input_text": "list comprehension",
            "clear_existing": True,
            "safety": {
                "forbid_final_submit": True,
                "allow_live_input": True,
                "allowed_input_categories": ["public_search_query"],
            },
            "dry_run": False,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["status"] == "dispatched"


def test_execute_step_resolves_requested_scroll_action_from_path_graph(monkeypatch) -> None:
    client = TestClient(app)
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))

    def fake_scroll(request):
        assert request.scroll_scope == "page"
        assert request.target_container_id is None
        assert request.target_pane == "page"
        assert request.metadata["path_graph_action_context"]["action_template_id"] == "read_article"
        return APIResponse(
            success=True,
            message="Page scroll dispatched",
            data={"action": "scroll", "result": {"trace_path": "logs/traces/actions/python_docs_scroll.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_scroll", fake_scroll)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "current_state_id": "docs:article_page",
            "requested_action_id": "read_article",
            "dry_run": False,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "dispatched"
    assert data["action_template_id"] == "read_article"
    assert data["low_level_action_type"] == "scroll"
    assert data["dispatch_low_level_executed"] is True


def test_execute_step_passes_approved_plan_id_for_click_reuse(monkeypatch) -> None:
    client = TestClient(app)
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))

    def fake_recognition_plan(request):
        assert request.approved_plan_id == "approved-search-button-plan"
        assert request.dry_run is False
        assert request.metadata["path_graph_action_context"]["action_template_id"] == "trigger_search"
        return APIResponse(
            success=True,
            message="Approved plan reused",
            data={"result": {"trace_path": "logs/traces/actions/python_docs_approved_click.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_recognition_plan", fake_recognition_plan)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "current_state_id": "docs:search_page",
            "requested_action_id": "trigger_search",
            "approved_plan_id": "approved-search-button-plan",
            "dry_run": False,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "dispatched"
    assert data["low_level_trace_path"] == "logs/traces/actions/python_docs_approved_click.json"


def test_execute_step_passes_path_graph_seeded_candidate_for_click(monkeypatch) -> None:
    client = TestClient(app)
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))

    def fake_recognition_plan(request):
        seeded = request.metadata["seeded_candidate"]
        assert request.dry_run is True
        assert request.metadata["path_graph_action_context"]["action_template_id"] == "trigger_search"
        assert seeded["contract_version"] == "seeded_candidate_v1"
        assert seeded["candidate_id"] == "docs_search_button_seed"
        assert seeded["role"] == "button"
        assert seeded["bbox"] == {"x": 497, "y": 272, "w": 57, "h": 22}
        assert seeded["click_point"] == {"x": 525, "y": 283}
        return APIResponse(
            success=True,
            message="Seeded search button planned",
            data={"result": {"trace_path": "logs/traces/actions/python_docs_seeded_click.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_recognition_plan", fake_recognition_plan)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "current_state_id": "docs:search_page",
            "requested_action_id": "trigger_search",
            "dry_run": True,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "dispatched"
    assert data["action_template_id"] == "trigger_search"
    assert data["low_level_action_type"] == "click"
    assert data["dispatch_low_level_executed"] is True
    assert data["low_level_trace_path"] == "logs/traces/actions/python_docs_seeded_click.json"


def test_execute_step_passes_path_graph_seeded_candidate_for_search_result(monkeypatch) -> None:
    client = TestClient(app)
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))

    def fake_recognition_plan(request):
        seeded = request.metadata["seeded_candidate"]
        assert request.metadata["path_graph_action_context"]["action_template_id"] == "open_search_result"
        assert seeded["candidate_id"] == "docs_first_search_result_seed"
        assert seeded["role"] == "link"
        assert seeded["bbox"] == {"x": 356, "y": 602, "w": 78, "h": 24}
        assert seeded["click_point"] == {"x": 392, "y": 614}
        return APIResponse(
            success=True,
            message="Seeded search result planned",
            data={"result": {"trace_path": "logs/traces/actions/python_docs_seeded_result_click.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_recognition_plan", fake_recognition_plan)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "current_state_id": "docs:search_results",
            "requested_action_id": "open_search_result",
            "dry_run": True,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["status"] == "dispatched"
    assert payload["data"]["low_level_trace_path"] == "logs/traces/actions/python_docs_seeded_result_click.json"


def test_execute_step_allows_explicit_public_search_submit(monkeypatch) -> None:
    client = TestClient(app)
    graph = json.loads(Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json").read_text(encoding="utf-8"))

    def fake_type_text(request):
        assert request.text == "list comprehension"
        assert request.submit is True
        assert request.metadata["input_policy"]["submit_allowed"] is True
        assert request.metadata["input_category"] == "public_search_query"
        return APIResponse(
            success=True,
            message="Public search input submitted",
            data={"action": "type_text", "result": {"trace_path": "logs/traces/actions/python_docs_submit.json"}},
            error=None,
        )

    monkeypatch.setattr(execute_api, "dispatch_type_text", fake_type_text)

    response = client.post(
        "/execute/step",
        json={
            "runtime_path_graph": graph,
            "current_state_id": "docs:search_page",
            "requested_action_id": "type_public_search_query",
            "input_text": "list comprehension",
            "target_point": {"x": 575, "y": 352},
            "clear_existing": True,
            "submit": True,
            "safety": {
                "forbid_final_submit": True,
                "allow_live_input": True,
                "allowed_input_categories": ["public_search_query"],
            },
            "dry_run": False,
            "dispatch_low_level": True,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "dispatched"
    assert data["low_level_trace_path"] == "logs/traces/actions/python_docs_submit.json"
