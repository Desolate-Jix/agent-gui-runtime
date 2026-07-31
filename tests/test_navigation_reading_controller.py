from __future__ import annotations

import hashlib
from collections.abc import Callable

import pytest

from app.agent.navigation_reading_controller import run_navigation_reading_controller


def _observation(interface_id: str, capture_id: str) -> dict:
    return {
        "contract_version": "current_interface_observation_v1",
        "interface_id": interface_id,
        "surface_type": (
            "content_collection"
            if interface_id == "news_list"
            else "finite_detail"
        ),
        "capture_id": capture_id,
        "screenshot_sha256": hashlib.sha256(capture_id.encode("utf-8")).hexdigest(),
        "trace_path": f"logs/traces/{capture_id}.json",
    }


def _evidence(interface_id: str) -> dict:
    is_list = interface_id == "news_list"
    actions = []
    if is_list:
        actions.append(
            {
                "action_id": "open_selected_article",
                "action_type": "open_detail",
                "source_control_id": "article_card",
                "display_name": "Open selected article",
                "agent_description": "打开选中的新闻卡片。",
                "target_interface_id": "news_detail",
                "risk_level": "low",
            }
        )
    return {
        "contract_version": "agent_evidence_context_v1",
        "asset_sha256": hashlib.sha256(
            f"reviewed:{interface_id}".encode("utf-8")
        ).hexdigest(),
        "interface": {
            "interface_id": interface_id,
            "display_name": interface_id,
            "surface_type": (
                "content_collection"
                if is_list
                else "finite_detail"
            ),
        },
        "deferred_reads": [
            {
                "content_id": f"{interface_id}:content",
                "label": "Current content",
                "content_behavior": (
                    "dynamic_collection"
                    if is_list
                    else "dynamic_value"
                ),
                "read_strategy": (
                    "infinite_collection"
                    if is_list
                    else "finite_detail"
                ),
                "completion_policy": (
                    "budget_or_no_new_content"
                    if is_list
                    else "reached_bottom_required"
                ),
                "max_scrolls": 2 if is_list else 4,
                "max_items": 20 if is_list else 0,
                "agent_description": "按需读取当前内容。",
            }
        ],
        "available_actions": actions,
        "verification_rules": [],
        "blockers": [],
        "readiness": {"status": "agent_usable"},
        "execution_contract": {
            "current_capture_required": True,
            "gate_required": True,
            "artifact_is_authorization": False,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def test_controller_rejects_reviewed_evidence_without_asset_provenance() -> None:
    observe, observe_calls = _observer([_observation("news_list", "list-1")])
    evidence = _evidence("news_list")
    evidence.pop("asset_sha256")

    with pytest.raises(ValueError, match="asset_sha256"):
        run_navigation_reading_controller(
            goal="读取当前列表。",
            workflow_id="news-reading",
            session_id="session-missing-provenance",
            observe_current=observe,
            load_interface_evidence=lambda _interface_id: evidence,
            decide=lambda _context: pytest.fail(
                "unproven reviewed evidence must not reach Agent decision"
            ),
            execute_operation=lambda _plan, _context: pytest.fail(
                "unproven reviewed evidence must not reach Operation"
            ),
            max_steps=1,
        )

    assert observe_calls == ["list-1"]


def _observer(sequence: list[dict]) -> tuple[Callable[[], dict], list[str]]:
    remaining = list(sequence)
    calls: list[str] = []

    def observe() -> dict:
        if not remaining:
            raise AssertionError("unexpected extra observation")
        current = remaining.pop(0)
        calls.append(current["capture_id"])
        return current

    return observe, calls


def _read_result(
    *,
    action_type: str,
    stop_reason: str,
    unique_line_count: int,
    effect_verified: bool = True,
    wrong_scope_detected: bool = False,
) -> dict:
    return {
        "contract_version": "navigation_reading_operation_result_v1",
        "gate_result": {"allowed": True, "reason": "read_only"},
        "action_dispatched": True,
        "effect_verified": effect_verified,
        "read_report": {
            "contract_version": "read_region_batch_v1",
            "stop_reason": stop_reason,
            "completion_status": (
                "complete"
                if stop_reason == "reached_bottom"
                else "incomplete"
            ),
            "reached_bottom": stop_reason == "reached_bottom",
            "wrong_scope_detected": wrong_scope_detected,
            "unique_line_count": unique_line_count,
        },
        "action_type": action_type,
    }


def test_controller_reobserves_after_every_read_scroll_and_transition() -> None:
    observe, observe_calls = _observer(
        [
            _observation("news_list", "list-1"),
            _observation("news_list", "list-2"),
            _observation("news_list", "list-3"),
            _observation("news_detail", "detail-1"),
            _observation("news_detail", "detail-2"),
        ]
    )
    decisions = iter(
        [
            {
                "choice_id": "read:news_list:content",
                "reason": "先读取可见列表。",
                "decision_source": "actual_model_call",
            },
            {
                "choice_id": "scroll:current_read_region",
                "reason": "还需要更多候选。",
                "decision_source": "actual_model_call",
            },
            {
                "choice_id": "transition:open_selected_article",
                "reason": "打开符合目标的新闻。",
                "decision_source": "actual_model_call",
            },
            {
                "choice_id": "read:news_detail:content",
                "reason": "完整读取详情。",
                "decision_source": "actual_model_call",
            },
            {
                "choice_id": "read:stop_budgeted_collection",
                "reason": "信息目标已经满足。",
                "decision_source": "actual_model_call",
            },
        ]
    )
    operation_results = iter(
        [
            _read_result(
                action_type="read",
                stop_reason="captures_exhausted",
                unique_line_count=8,
            ),
            _read_result(
                action_type="scroll",
                stop_reason="captures_exhausted",
                unique_line_count=15,
            ),
            {
                "contract_version": "navigation_reading_operation_result_v1",
                "gate_result": {"allowed": True, "reason": "low_risk"},
                "action_type": "open_detail",
                "action_executed": True,
                "post_action_verified": True,
            },
            _read_result(
                action_type="read",
                stop_reason="reached_bottom",
                unique_line_count=32,
            ),
        ]
    )
    seen_contexts: list[dict] = []

    def decide(context: dict) -> dict:
        seen_contexts.append(context)
        decision = next(decisions)
        if context["interface"]["interface_id"] == "news_detail":
            if context["read_state"].get("status") == "reached_bottom":
                return {
                    "choice_id": "safe_stop:agent_requested_safe_stop",
                    "reason": "信息目标已经满足。",
                    "decision_source": "actual_model_call",
                }
        return decision

    def execute(plan: dict, _context: dict) -> dict:
        result = next(operation_results)
        result["source_freshness"] = dict(plan["freshness"])
        return result

    report = run_navigation_reading_controller(
        goal="浏览列表，打开一篇新闻并完整读取。",
        workflow_id="news-reading",
        session_id="session-1",
        observe_current=observe,
        load_interface_evidence=lambda interface_id: _evidence(interface_id),
        decide=decide,
        execute_operation=execute,
        max_steps=8,
    )

    assert observe_calls == ["list-1", "list-2", "list-3", "detail-1", "detail-2"]
    assert report["visited_interfaces"] == ["news_list", "news_detail"]
    assert report["actual_model_call_count"] == 5
    assert report["final_status"] == "safe_stop"
    assert report["stop_reason"] == "safe_stop:agent_requested_safe_stop"
    assert [step["semantic_action"] for step in report["steps"]] == [
        "read",
        "scroll",
        "open_detail",
        "read",
        "safe_stop",
    ]
    assert all("bbox" not in str(context) for context in seen_contexts)
    assert all("click_point" not in str(context) for context in seen_contexts)


def test_controller_gate_rejection_never_reports_operation_execution() -> None:
    observe, observe_calls = _observer([_observation("news_list", "list-1")])

    report = run_navigation_reading_controller(
        goal="打开一篇新闻。",
        workflow_id="news-reading",
        session_id="session-gate",
        observe_current=observe,
        load_interface_evidence=lambda interface_id: _evidence(interface_id),
        decide=lambda _context: {
            "choice_id": "transition:open_selected_article",
            "reason": "打开目标新闻。",
            "decision_source": "deterministic_fixture",
        },
        execute_operation=lambda plan, _context: {
            "contract_version": "navigation_reading_operation_result_v1",
            "gate_result": {"allowed": False, "reason": "target_ambiguous"},
            "action_type": "open_detail",
            "action_executed": False,
            "post_action_verified": False,
            "source_freshness": dict(plan["freshness"]),
        },
        max_steps=2,
    )

    assert observe_calls == ["list-1"]
    assert report["final_status"] == "safe_stop"
    assert report["stop_reason"] == "gate_rejected"
    assert report["steps"][0]["case_outcome"] == "safe_intercept"
    assert report["steps"][0]["action_executed"] is False


def test_controller_records_model_decision_audit_without_treating_it_as_authority() -> None:
    observe, _observe_calls = _observer([_observation("news_list", "list-1")])

    report = run_navigation_reading_controller(
        goal="停止当前任务。",
        workflow_id="news-reading",
        session_id="session-audit",
        observe_current=observe,
        load_interface_evidence=lambda interface_id: _evidence(interface_id),
        decide=lambda _context: {
            "choice_id": "safe_stop:agent_requested_safe_stop",
            "reason": "没有足够证据继续。",
            "decision_source": "actual_model_call",
            "decision_audit": {
                "model_name": "test-model",
                "prompt_sha256": "a" * 64,
                "raw_model_output": '{"choice_id":"safe_stop"}',
            },
        },
        execute_operation=lambda _plan, _context: pytest.fail(
            "safe stop must not dispatch an Operation"
        ),
        max_steps=1,
    )

    assert report["actual_model_call_count"] == 1
    assert report["steps"][0]["decision_audit"]["model_name"] == "test-model"
    assert report["safety"]["artifact_is_authorization"] is False


def test_controller_scroll_dispatch_without_effect_requires_human_review() -> None:
    observe, observe_calls = _observer([_observation("news_list", "list-1")])

    def execute(plan: dict, _context: dict) -> dict:
        result = _read_result(
            action_type="scroll",
            stop_reason="no_new_content",
            unique_line_count=8,
            effect_verified=False,
        )
        result["source_freshness"] = dict(plan["freshness"])
        return result

    report = run_navigation_reading_controller(
        goal="继续读取列表。",
        workflow_id="news-reading",
        session_id="session-scroll",
        observe_current=observe,
        load_interface_evidence=lambda interface_id: _evidence(interface_id),
        decide=lambda _context: {
            "choice_id": "scroll:current_read_region",
            "reason": "继续读取。",
            "decision_source": "deterministic_fixture",
        },
        execute_operation=execute,
        initial_read_progress={
            "strategy": "infinite_collection",
            "status": "reading",
            "scrolls_used": 0,
            "max_scrolls": 2,
        },
        max_steps=2,
    )

    assert observe_calls == ["list-1"]
    assert report["final_status"] == "needs_human_review"
    assert report["steps"][0]["dispatch_success"] is True
    assert report["steps"][0]["effect_verified"] is False


def test_controller_preserves_reviewed_finite_read_scroll_budget() -> None:
    observe, observe_calls = _observer(
        [
            _observation("news_detail", "detail-1"),
            _observation("news_detail", "detail-2"),
        ]
    )
    contexts: list[dict] = []

    def decide(context: dict) -> dict:
        contexts.append(context)
        if len(contexts) == 1:
            return {
                "choice_id": "read:news_detail:content",
                "reason": "先读取当前可见内容。",
                "decision_source": "deterministic_fixture",
            }
        assert any(
            choice.get("choice_id") == "scroll:current_read_region"
            for choice in context["choices"]
        )
        assert context["read_state"]["max_scrolls"] == 4
        assert context["read_state"]["content_id"] == "news_detail:content"
        return {
            "choice_id": "safe_stop:agent_requested_safe_stop",
            "reason": "测试已确认滚动选择可用。",
            "decision_source": "deterministic_fixture",
        }

    def execute(plan: dict, _context: dict) -> dict:
        result = _read_result(
            action_type="read",
            stop_reason="captures_exhausted",
            unique_line_count=10,
        )
        result["source_freshness"] = dict(plan["freshness"])
        return result

    report = run_navigation_reading_controller(
        goal="完整读取当前详情。",
        workflow_id="detail-reading",
        session_id="session-finite-scroll-budget",
        observe_current=observe,
        load_interface_evidence=lambda interface_id: _evidence(interface_id),
        decide=decide,
        execute_operation=execute,
        max_steps=3,
    )

    assert observe_calls == ["detail-1", "detail-2"]
    assert report["final_status"] == "safe_stop"


def test_controller_rejects_operation_result_bound_to_stale_capture() -> None:
    observe, observe_calls = _observer([_observation("news_list", "list-1")])

    report = run_navigation_reading_controller(
        goal="读取当前列表。",
        workflow_id="news-reading",
        session_id="session-stale",
        observe_current=observe,
        load_interface_evidence=lambda interface_id: _evidence(interface_id),
        decide=lambda _context: {
            "choice_id": "read:news_list:content",
            "reason": "读取列表。",
            "decision_source": "deterministic_fixture",
        },
        execute_operation=lambda _plan, _context: {
            **_read_result(
                action_type="read",
                stop_reason="captures_exhausted",
                unique_line_count=8,
            ),
            "source_freshness": {
                "capture_id": "stale-capture",
                "screenshot_sha256": "0" * 64,
                "trace_path": "logs/traces/stale.json",
            },
        },
        max_steps=2,
    )

    assert observe_calls == ["list-1"]
    assert report["final_status"] == "safe_stop"
    assert report["stop_reason"] == "stale_operation_source"
    assert report["steps"][0]["action_executed"] is False


def test_controller_continues_navigation_after_agent_stops_infinite_reading() -> None:
    observe, observe_calls = _observer(
        [
            _observation("news_list", "list-1"),
            _observation("news_detail", "detail-1"),
        ]
    )
    decisions = iter(
        [
            {
                "choice_id": "read:stop_budgeted_collection",
                "reason": "列表读取预算已经满足，现在继续目标流程。",
                "decision_source": "actual_model_call",
            },
            {
                "choice_id": "transition:open_selected_article",
                "reason": "打开已选择的文章继续读取。",
                "decision_source": "actual_model_call",
            },
            {
                "choice_id": "safe_stop:agent_requested_safe_stop",
                "reason": "已到达目标详情，本测试安全停止。",
                "decision_source": "actual_model_call",
            },
        ]
    )
    operation_plans: list[dict] = []

    def execute(plan: dict, _context: dict) -> dict:
        operation_plans.append(plan)
        return {
            "contract_version": "navigation_reading_operation_result_v1",
            "gate_result": {"allowed": True, "reason": "low_risk"},
            "action_type": "open_detail",
            "action_executed": True,
            "post_action_verified": True,
            "source_freshness": dict(plan["freshness"]),
        }

    report = run_navigation_reading_controller(
        goal="按预算读取新闻列表，然后打开选中的文章。",
        workflow_id="news-reading",
        session_id="session-stop-read-then-transition",
        observe_current=observe,
        load_interface_evidence=lambda interface_id: _evidence(interface_id),
        decide=lambda _context: next(decisions),
        execute_operation=execute,
        initial_read_progress={
            "strategy": "infinite_collection",
            "status": "reading",
            "content_id": "news_list:content",
            "scrolls_used": 2,
            "max_scrolls": 2,
            "items_read": 12,
            "max_items": 20,
        },
        max_steps=5,
    )

    assert observe_calls == ["list-1", "detail-1"]
    assert [step["semantic_action"] for step in report["steps"]] == [
        "stop_reading",
        "open_detail",
        "safe_stop",
    ]
    assert [plan["semantic_action"] for plan in operation_plans] == ["open_detail"]
    assert report["visited_interfaces"] == ["news_list", "news_detail"]
    assert report["final_status"] == "safe_stop"


def test_controller_exposes_completed_branch_history_after_returning_to_hub() -> None:
    observe, observe_calls = _observer(
        [
            _observation("news_list", "list-1"),
            _observation("news_detail", "detail-1"),
            _observation("news_list", "list-2"),
        ]
    )
    contexts: list[dict] = []
    decisions = iter(
        [
            "transition:open_selected_article",
            "transition:return_to_list",
            "safe_stop:agent_requested_safe_stop",
        ]
    )

    def evidence(interface_id: str) -> dict:
        value = _evidence(interface_id)
        if interface_id == "news_detail":
            value["available_actions"] = [
                {
                    "action_id": "return_to_list",
                    "action_type": "navigate_back",
                    "source_control_id": "back_button",
                    "display_name": "Return to list",
                    "agent_description": "返回新闻列表。",
                    "target_interface_id": "news_list",
                    "risk_level": "low",
                }
            ]
        return value

    def decide(context: dict) -> dict:
        contexts.append(context)
        return {
            "choice_id": next(decisions),
            "reason": "根据已完成路径选择下一步。",
            "decision_source": "actual_model_call",
        }

    def execute(plan: dict, _context: dict) -> dict:
        return {
            "contract_version": "navigation_reading_operation_result_v1",
            "gate_result": {"allowed": True, "reason": "low_risk"},
            "action_type": plan["semantic_action"],
            "action_executed": True,
            "post_action_verified": True,
            "source_freshness": dict(plan["freshness"]),
        }

    report = run_navigation_reading_controller(
        goal="打开详情后返回列表，并根据任务历史选择其他分支。",
        workflow_id="branching-reading",
        session_id="session-branch-history",
        observe_current=observe,
        load_interface_evidence=evidence,
        decide=decide,
        execute_operation=execute,
        max_steps=4,
    )

    assert observe_calls == ["list-1", "detail-1", "list-2"]
    assert contexts[2]["task_progress"]["visited_interfaces"] == [
        "news_list",
        "news_detail",
        "news_list",
    ]
    assert contexts[2]["task_progress"]["completed_choice_ids"] == [
        "transition:open_selected_article",
        "transition:return_to_list",
    ]
    assert report["final_status"] == "safe_stop"
