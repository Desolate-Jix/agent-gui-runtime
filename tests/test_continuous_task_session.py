import pytest

from app.agent.continuous_task_session import (
    confirm_apply_entry,
    create_continuous_task_session,
    observe_interface,
    refresh_current_observation,
    record_agent_decision,
    record_action_result,
    record_read_result,
    record_gate_rejection,
    request_apply_entry_confirmation,
    resume_after_learning,
)


def _evidence(capture_id: str) -> dict[str, str]:
    return {
        "capture_id": capture_id,
        "screenshot_sha256": f"sha256:{capture_id}",
        "trace_path": f"logs/{capture_id}.json",
    }


def test_known_interfaces_form_one_verified_no_submit_session() -> None:
    session = create_continuous_task_session(
        session_id="seek-demo-1",
        workflow_id="seek-quick-apply-demo",
    )
    session = observe_interface(
        session,
        interface_id="seek_home_recommendations",
        surface_type="seek_results",
        memory_object_sha256="memory-results",
        evidence=_evidence("capture-results"),
    )
    session = record_action_result(
        session,
        action_type="open_detail",
        action_executed=True,
        post_action_verified=True,
        evidence=_evidence("capture-detail-transition"),
    )
    session = observe_interface(
        session,
        interface_id="seek_job_detail",
        surface_type="seek_job_detail",
        memory_object_sha256="memory-detail",
        evidence=_evidence("capture-detail"),
    )
    session = request_apply_entry_confirmation(
        session,
        job_id="job-123",
        job_title="Graduate Software Engineer",
    )
    session = confirm_apply_entry(session, approved=True)
    session = record_action_result(
        session,
        action_type="open_apply_flow",
        action_executed=True,
        post_action_verified=True,
        evidence=_evidence("capture-quick-apply-transition"),
    )
    session = observe_interface(
        session,
        interface_id="seek_quick_apply_questions",
        surface_type="seek_quick_apply",
        memory_object_sha256="memory-questions",
        evidence=_evidence("capture-questions"),
    )
    session = record_action_result(
        session,
        action_type="continue_next_step",
        action_executed=True,
        post_action_verified=True,
        evidence=_evidence("capture-final-review-transition"),
    )
    session = observe_interface(
        session,
        interface_id="seek_quick_apply_review",
        surface_type="final_submit_visible",
        memory_object_sha256="memory-review",
        evidence=_evidence("capture-final-review"),
    )

    assert session["status"] == "safe_stop"
    assert session["stop_reason"] == "final_submit_visible"
    assert session["safety"]["final_submit_forbidden"] is True
    assert session["safety"]["final_submit_executed"] is False
    assert [event["event_type"] for event in session["events"]] == [
        "interface_observed",
        "action_verified",
        "interface_observed",
        "apply_entry_confirmation_requested",
        "apply_entry_confirmation_recorded",
        "action_verified",
        "interface_observed",
        "action_verified",
        "interface_observed",
        "safe_stop",
    ]


def test_unknown_interface_pauses_for_learning_and_resumes_after_reviewed_memory_publish() -> None:
    session = create_continuous_task_session(
        session_id="seek-demo-2",
        workflow_id="seek-quick-apply-demo",
    )
    session = observe_interface(
        session,
        interface_id="seek_quick_apply_new_question",
        surface_type="seek_quick_apply",
        memory_object_sha256=None,
        evidence=_evidence("capture-unknown"),
    )

    assert session["status"] == "paused_for_learning"
    assert session["pending_learning"]["interface_id"] == "seek_quick_apply_new_question"

    session = resume_after_learning(
        session,
        interface_id="seek_quick_apply_new_question",
        memory_object_sha256="reviewed-memory-new-question",
    )

    assert session["status"] == "ready_for_agent_decision"
    assert session["current_memory_object_sha256"] == "reviewed-memory-new-question"
    assert session["pending_learning"] is None


def test_runtime_profile_surface_can_continue_without_reviewed_memory() -> None:
    session = create_continuous_task_session(
        session_id="seek-demo-runtime-profile",
        workflow_id="seek-quick-apply-demo",
    )
    session = observe_interface(
        session,
        interface_id="seek_job_detail_runtime_profile",
        surface_type="seek_job_detail",
        memory_object_sha256=None,
        evidence=_evidence("capture-detail"),
        learning_required=False,
        knowledge_source="seek_runtime_profile",
    )

    assert session["status"] == "ready_for_agent_decision"
    assert session["pending_learning"] is None
    observed = session["events"][-1]["details"]
    assert observed["learning_required"] is False
    assert observed["knowledge_source"] == "seek_runtime_profile"


def test_external_ats_stops_without_continuing_or_filling() -> None:
    session = create_continuous_task_session(
        session_id="seek-demo-3",
        workflow_id="seek-quick-apply-demo",
    )
    session = observe_interface(
        session,
        interface_id="external_workday_login",
        surface_type="external_ats",
        memory_object_sha256=None,
        evidence=_evidence("capture-external"),
    )

    assert session["status"] == "safe_stop"
    assert session["stop_reason"] == "external_ats_not_supported"
    assert session["forbidden_next_actions"] == [
        "continue_next_step",
        "fill_field",
        "final_submit",
    ]


def test_final_submit_action_is_never_recorded_as_executed() -> None:
    session = create_continuous_task_session(
        session_id="seek-demo-4",
        workflow_id="seek-quick-apply-demo",
    )

    with pytest.raises(ValueError, match="final submit action is forbidden"):
        record_action_result(
            session,
            action_type="final_submit",
            action_executed=True,
            post_action_verified=True,
            evidence=_evidence("capture-submit"),
        )


def test_verified_action_event_retains_agent_gate_and_post_action_audit() -> None:
    session = create_continuous_task_session(
        session_id="seek-demo-audit",
        workflow_id="seek-quick-apply-demo",
    )
    session = observe_interface(
        session,
        interface_id="seek_job_detail_runtime_profile",
        surface_type="seek_job_detail",
        memory_object_sha256=None,
        evidence=_evidence("capture-detail"),
        learning_required=False,
        knowledge_source="seek_runtime_profile",
    )
    session = record_action_result(
        session,
        action_type="open_apply_flow",
        action_executed=True,
        post_action_verified=True,
        evidence=_evidence("capture-quick-apply"),
        transition_audit={
            "agent_decision": "strong_apply",
            "gate_result": "allowed",
            "post_action_verification": "application_flow_started",
        },
    )

    assert session["events"][-1]["details"]["transition_audit"] == {
        "agent_decision": "strong_apply",
        "gate_result": "allowed",
        "post_action_verification": "application_flow_started",
    }


def _decision(
    *,
    semantic_action: str,
    decision_type: str,
    interface_id: str = "news:list",
) -> dict:
    return {
        "contract_version": "navigation_reading_decision_plan_v1",
        "goal": "Read current technology news",
        "interface_id": interface_id,
        "choice_id": f"choice:{semantic_action}",
        "decision_type": decision_type,
        "semantic_action": semantic_action,
        "reason": "This is the next reviewed semantic step.",
        "source_control_id": "article_card",
        "expected_target_interface_id": "news:detail",
        "freshness": _evidence("capture-news"),
        "requires_operation_resolution": True,
        "requires_gate": True,
        "requires_post_action_verification": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def test_generic_navigation_decision_is_recorded_before_operation() -> None:
    session = create_continuous_task_session(
        session_id="news-navigation",
        workflow_id="news-reading",
    )
    session = observe_interface(
        session,
        interface_id="news:list",
        surface_type="content_collection",
        memory_object_sha256="memory-news-list",
        evidence=_evidence("capture-news"),
    )

    session = record_agent_decision(
        session,
        decision_plan=_decision(
            semantic_action="open_detail",
            decision_type="follow_transition",
        ),
    )

    assert session["status"] == "ready_for_operation"
    assert session["pending_agent_decision"]["semantic_action"] == "open_detail"
    assert session["events"][-1]["event_type"] == "agent_decision_recorded"

    session = record_action_result(
        session,
        action_type="open_detail",
        action_executed=True,
        post_action_verified=True,
        evidence=_evidence("capture-news-detail"),
    )

    assert session["status"] == "ready_for_observation"
    assert session["pending_agent_decision"] is None


def test_gate_rejection_safe_stops_without_operation_dispatch() -> None:
    session = create_continuous_task_session(
        session_id="news-gate-rejection",
        workflow_id="news-reading",
    )
    session = observe_interface(
        session,
        interface_id="news:list",
        surface_type="content_collection",
        memory_object_sha256="memory-news-list",
        evidence=_evidence("capture-news"),
    )
    session = record_agent_decision(
        session,
        decision_plan=_decision(
            semantic_action="open_detail",
            decision_type="follow_transition",
        ),
    )

    session = record_gate_rejection(
        session,
        reason="target_ambiguous",
        evidence=_evidence("capture-news"),
    )

    assert session["status"] == "safe_stop"
    assert session["stop_reason"] == "gate_rejected"
    assert session["pending_agent_decision"] is None
    assert session["events"][-2]["event_type"] == "gate_rejected"
    assert session["events"][-1]["event_type"] == "safe_stop"
    assert session["safety"]["final_submit_executed"] is False


def test_verified_finite_read_records_reached_bottom_and_returns_to_agent() -> None:
    session = create_continuous_task_session(
        session_id="article-read",
        workflow_id="news-reading",
    )
    session = observe_interface(
        session,
        interface_id="news:detail",
        surface_type="finite_detail",
        memory_object_sha256="memory-news-detail",
        evidence=_evidence("capture-news"),
    )
    session = record_agent_decision(
        session,
        decision_plan=_decision(
            semantic_action="read",
            decision_type="read_region",
            interface_id="news:detail",
        ),
    )
    session = record_read_result(
        session,
        action_type="read",
        action_dispatched=True,
        effect_verified=True,
        read_report={
            "contract_version": "read_region_batch_v1",
            "stop_reason": "reached_bottom",
            "completion_status": "complete",
            "reached_bottom": True,
            "unique_line_count": 12,
        },
        evidence=_evidence("capture-article-bottom"),
    )

    assert session["status"] == "ready_for_agent_decision"
    assert session["current_read_state"]["status"] == "reached_bottom"
    assert session["current_read_state"]["completion"] == "complete"
    assert session["pending_agent_decision"] is None


def test_no_new_content_stays_incomplete_and_wrong_scope_safe_stops() -> None:
    session = create_continuous_task_session(
        session_id="article-read-stalled",
        workflow_id="news-reading",
    )
    session = observe_interface(
        session,
        interface_id="news:detail",
        surface_type="finite_detail",
        memory_object_sha256="memory-news-detail",
        evidence=_evidence("capture-news"),
    )
    session = record_read_result(
        session,
        action_type="read",
        action_dispatched=True,
        effect_verified=True,
        read_report={
            "contract_version": "read_region_batch_v1",
            "stop_reason": "no_new_content",
            "completion_status": "incomplete",
            "reached_bottom": False,
            "unique_line_count": 8,
        },
        evidence=_evidence("capture-stalled"),
    )

    assert session["status"] == "ready_for_agent_decision"
    assert session["current_read_state"]["completion"] == "incomplete"

    session = record_read_result(
        session,
        action_type="scroll",
        action_dispatched=True,
        effect_verified=False,
        read_report={
            "contract_version": "read_region_batch_v1",
            "stop_reason": "wrong_scope_detected",
            "completion_status": "blocked",
            "wrong_scope_detected": True,
        },
        evidence=_evidence("capture-wrong-scope"),
    )

    assert session["status"] == "safe_stop"
    assert session["stop_reason"] == "wrong_scope_detected"
    assert "scroll" in session["forbidden_next_actions"]


def test_scroll_dispatch_without_verified_effect_needs_human_review() -> None:
    session = create_continuous_task_session(
        session_id="feed-scroll-no-effect",
        workflow_id="news-reading",
    )
    session = observe_interface(
        session,
        interface_id="news:list",
        surface_type="content_collection",
        memory_object_sha256="memory-news-list",
        evidence=_evidence("capture-news"),
    )
    session = record_read_result(
        session,
        action_type="scroll",
        action_dispatched=True,
        effect_verified=False,
        read_report={
            "contract_version": "read_region_batch_v1",
            "stop_reason": "no_new_content",
            "completion_status": "incomplete",
            "wrong_scope_detected": False,
        },
        evidence=_evidence("capture-no-effect"),
    )

    assert session["status"] == "needs_human_review"
    assert session["events"][-1]["event_type"] == "read_effect_not_verified"


def test_refresh_current_observation_preserves_read_state_and_updates_freshness() -> None:
    session = create_continuous_task_session(
        session_id="feed-scroll-refresh",
        workflow_id="news-reading",
    )
    session = observe_interface(
        session,
        interface_id="news:list",
        surface_type="content_collection",
        memory_object_sha256="memory-news-list",
        evidence=_evidence("capture-news-1"),
    )
    session = record_read_result(
        session,
        action_type="scroll",
        action_dispatched=True,
        effect_verified=True,
        read_report={
            "contract_version": "read_region_batch_v1",
            "stop_reason": "captures_exhausted",
            "completion_status": "incomplete",
            "reached_bottom": False,
            "unique_line_count": 18,
        },
        evidence=_evidence("capture-news-1"),
    )

    refreshed = refresh_current_observation(
        session,
        interface_id="news:list",
        surface_type="content_collection",
        evidence=_evidence("capture-news-2"),
    )

    assert refreshed["status"] == "ready_for_agent_decision"
    assert refreshed["current_read_state"]["unique_line_count"] == 18
    assert refreshed["current_observation_evidence"]["capture_id"] == "capture-news-2"
    assert refreshed["events"][-1]["event_type"] == "observation_refreshed"
