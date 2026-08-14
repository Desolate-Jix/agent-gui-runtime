from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from seek_debug_export_application_fill_record import build_record_from_debug_run  # noqa: E402
from seek_debug_step_runner import build_parser as build_step_parser  # noqa: E402
from seek_debug_step_runner import run_step  # noqa: E402
from seek_mvp_traversal_runner import _get_json, _post_json  # noqa: E402
from app.agent.continuous_task_session import (  # noqa: E402
    confirm_apply_entry,
    create_continuous_task_session,
    observe_interface,
    record_action_result,
    resume_after_learning,
    request_apply_entry_confirmation,
)
from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore  # noqa: E402
from app.agent.seek_continuous_demo import (  # noqa: E402
    build_step_evidence,
    load_seek_checkpoint,
    load_seek_session,
    quick_apply_interface_id,
    resolve_active_memory_sha256,
    save_seek_checkpoint,
    save_seek_session,
)
from app.core.gpu_resources import build_model_resource_preflight  # noqa: E402
from app.core.model_server import check_model_server, profile_for_stage  # noqa: E402
from app.learn.continuous_workflow_projection import (  # noqa: E402
    persist_continuous_session_workflow_candidate,
)
from app.seek.application_artifacts import build_seek_application_flow_artifact  # noqa: E402
from seek_demo_readiness_report import build_demo_readiness_report, load_step_reports  # noqa: E402


DEFAULT_SEARCH_URL = "https://nz.seek.com/software-engineer-jobs/in-All-Auckland"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
SCROLL_WHEEL_CLICKS_MAX = 20


def _build_reviewed_memory_store() -> ReviewedInterfaceMemoryStore:
    return ReviewedInterfaceMemoryStore(project_root=REPO_ROOT)


def _clamp_scroll_wheel_clicks(value: int) -> int:
    """滚动请求必须遵守 /action/scroll 的 API 上限。"""

    return max(1, min(SCROLL_WHEEL_CLICKS_MAX, int(value)))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_step(run_dir: Path, step: str, extra: list[str] | None = None) -> dict[str, Any]:
    parser = build_step_parser()
    args = parser.parse_args(["--run-dir", str(run_dir), "--step", step, *(extra or [])])
    started = time.perf_counter()
    payload = run_step(args)
    payload["_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return payload


def _step_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_index": payload.get("step_index"),
        "step_name": payload.get("step_name"),
        "status": payload.get("status"),
        "latency_ms": payload.get("_latency_ms"),
        "report_path": payload.get("report_path"),
        "trace_paths": [str(path) for path in payload.get("trace_paths") or []],
        "next_allowed_steps": payload.get("next_allowed_steps"),
        "final_submissions": payload.get("final_submissions"),
        "submit_clicks": payload.get("submit_clicks"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return payload


def _card_prefilter_decision(card: dict[str, Any] | None, *, learned_fast_mode: bool = True) -> dict[str, Any]:
    # 卡片标题不能替代完整岗位详情；是否适合必须交给 Agent 判断。
    return {"decision": "keep", "reason": "agent_requires_full_detail"}


def _final_review_ready(flow_state: dict[str, Any] | None) -> bool:
    payload = flow_state if isinstance(flow_state, dict) else {}
    current_step = str(payload.get("current_step") or "").casefold()
    state_type = str(payload.get("state_type") or "").casefold()
    return (
        current_step == "review_and_submit"
        or state_type == "final_submit_visible"
        or payload.get("final_submit_visible") is True
        or payload.get("submit_application_visible") is True
    )


def _card_needs_scroll_into_safer_position(card: dict[str, Any] | None, *, window_height: int) -> bool:
    payload = card if isinstance(card, dict) else {}
    bbox = payload.get("card_bbox") if isinstance(payload.get("card_bbox"), dict) else {}
    try:
        y = int(bbox.get("y") or 0)
        h = int(bbox.get("h") or 0)
    except (TypeError, ValueError):
        return False
    if y <= 0 or h <= 0:
        return False
    return y + min(h, 80) > int(window_height * 0.86)


def _scroll_results_list(base_url: str, *, timeout: float, wheel_clicks: int) -> dict[str, Any]:
    wheel_clicks = _clamp_scroll_wheel_clicks(wheel_clicks)
    return _post_json(
        base_url,
        "/action/scroll",
        {
            "contract_version": "scroll_request_v2",
            "scroll_scope": "container",
            "target_pane": "results_list",
            "target_container_id": "seek:results_list",
            "direction": "down",
            "wheel_clicks": wheel_clicks,
            "reason": "seek_speed_demo_try_more_visible_job_cards",
            "missing_evidence": ["no_eligible_apply_entry_in_current_visible_cards"],
            "expected_effect": {
                "target_container_content_should_change": True,
                "same_semantic_page_should_remain": True,
            },
            "dry_run": False,
            "enable_verification": True,
        },
        timeout,
    )


def _scroll_results_page(base_url: str, *, timeout: float, wheel_clicks: int) -> dict[str, Any]:
    wheel_clicks = _clamp_scroll_wheel_clicks(wheel_clicks)
    return _post_json(
        base_url,
        "/action/scroll",
        {
            "contract_version": "scroll_request_v2",
            "scroll_scope": "page",
            "target_pane": "page",
            "target_container_id": "seek:page",
            "direction": "down",
            "wheel_clicks": wheel_clicks,
            "reason": "seek_speed_demo_results_list_container_did_not_change",
            "missing_evidence": ["results_list_card_fingerprint_repeated_after_container_scroll"],
            "expected_effect": {
                "target_container_content_should_change": True,
                "same_semantic_page_should_remain": True,
            },
            "dry_run": False,
            "enable_verification": True,
        },
        timeout,
    )


def _cards_fingerprint(cards: list[Any]) -> tuple[str, ...]:
    out: list[str] = []
    for item in cards:
        if not isinstance(item, dict):
            continue
        out.append("|".join([str(item.get("title") or ""), str(item.get("company") or ""), str(item.get("location") or "")]))
    return tuple(out)


def _apply_decision_allowed(decision: Any, *, allow_maybe_apply: bool) -> bool:
    allowed_apply_decisions = {"strong_apply", "suitable", "apply", "safe_to_apply"}
    if allow_maybe_apply:
        allowed_apply_decisions.add("maybe_apply")
    return str(decision or "") in allowed_apply_decisions


def _apply_entry_state(execute_apply: dict[str, Any]) -> dict[str, Any]:
    apply_entry = execute_apply.get("apply_entry") if isinstance(execute_apply.get("apply_entry"), dict) else {}
    wait_state = (
        ((execute_apply.get("post_apply_wait") or {}).get("application_flow_state") or {})
        if isinstance(execute_apply.get("post_apply_wait"), dict)
        else {}
    )
    merged = dict(wait_state)
    merged.update(apply_entry)
    return merged


def _transition_audit(payload: dict[str, Any], *, agent_decision: Any = None) -> dict[str, Any]:
    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    execute_response = (
        action.get("execute_response") if isinstance(action.get("execute_response"), dict) else {}
    )
    apply_entry = payload.get("apply_entry") if isinstance(payload.get("apply_entry"), dict) else {}
    ui_diff = payload.get("ui_diff_verification") if isinstance(payload.get("ui_diff_verification"), dict) else {}
    gate_allowed = execute_response.get("pre_click_allowed")
    gate_source = "recognition_plan_pre_click"
    if gate_allowed is None and apply_entry:
        gate_allowed = bool(apply_entry.get("executed") and apply_entry.get("application_flow_started"))
        gate_source = "seek_apply_entry_verification"
    if gate_allowed is None:
        gate_allowed = payload.get("status") not in {"failed", "blocked_need_user_or_gpt_decision"}
        gate_source = "runner_transition_status"
    verification = str(ui_diff.get("verification_status") or "").strip()
    if not verification and apply_entry.get("application_flow_started") is True:
        verification = "application_flow_started"
    if not verification and isinstance(payload.get("application_flow_state"), dict):
        verification = "application_flow_state_observed"
    return {
        "agent_decision": str(agent_decision or "").strip() or None,
        "gate_result": "allowed" if gate_allowed else "blocked",
        "gate_source": gate_source,
        "post_action_verification": verification or "step_status_only",
        "runner_status": payload.get("status"),
    }


def _station_internal_application_started(execute_apply: dict[str, Any]) -> bool:
    state = _apply_entry_state(execute_apply)
    if state.get("application_flow_started") is not True:
        return False
    state_type = str(state.get("state_type") or "").casefold()
    stop_reason = str(state.get("stop_reason") or "").casefold()
    risk_flags = {str(item).casefold() for item in state.get("risk_flags") or []}
    if state_type == "third_party_ats" or "third_party_ats" in risk_flags:
        return False
    if "third_party_ats" in stop_reason or "external" in stop_reason:
        return False
    return True


def _external_apply_flow_started(execute_apply: dict[str, Any]) -> bool:
    state = _apply_entry_state(execute_apply)
    state_type = str(state.get("state_type") or "").casefold()
    risk_flags = {str(item).casefold() for item in state.get("risk_flags") or []}
    stop_reason = str(state.get("stop_reason") or "").casefold()
    return (
        state_type == "third_party_ats"
        or "third_party_ats" in risk_flags
        or "third_party_ats" in stop_reason
        or "external" in stop_reason
    )


def _external_ats_login_required(execute_apply: dict[str, Any]) -> bool:
    state = _apply_entry_state(execute_apply)
    state_type = str(state.get("state_type") or "").casefold()
    risk_flags = {str(item).casefold() for item in state.get("risk_flags") or []}
    stop_reason = str(state.get("stop_reason") or "").casefold()
    has_external = (
        state_type in {"third_party_ats", "external_ats"}
        or "third_party_ats" in risk_flags
        or "external_ats" in risk_flags
        or "third_party_ats" in stop_reason
        or "external_ats" in stop_reason
        or "external" in stop_reason
    )
    has_login = state_type == "login_required" or "login_required" in risk_flags or "login" in stop_reason
    return has_external and has_login


def _write_speed_demo_result(
    run_dir: Path,
    *,
    started: float,
    args: argparse.Namespace,
    steps: list[dict[str, Any]],
    job_attempts: list[dict[str, Any]],
    result_scrolls: list[dict[str, Any]],
    status: str,
    stop_reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total_ms = round((time.perf_counter() - started) * 1000, 3)
    result = {
        "contract_version": "seek_speed_demo_run_v1",
        "status": status,
        "stop_reason": stop_reason,
        "run_dir": str(run_dir),
        "total_ms": total_ms,
        "time_budget_ms": args.time_budget_ms,
        "within_budget": total_ms <= args.time_budget_ms,
        "learned_fast_mode": not getattr(args, "disable_learned_fast_mode", False),
        "local_keyword_prefilter_enabled": False,
        "full_detail_agent_decision_required": True,
        "steps": steps,
        "job_attempts": job_attempts,
        "result_scrolls": result_scrolls,
        "final_submissions": 0,
        "submit_clicks": 0,
    }
    if extra:
        result.update(extra)
    result["multi_interface_workflow"] = _persist_multi_interface_workflow(
        run_dir=run_dir,
        args=args,
    )
    _write_json(run_dir / "speed_demo_report.json", result)
    return result


def _persist_multi_interface_workflow(
    *,
    run_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    session_path = run_dir / "continuous_task_session.json"
    if not session_path.is_file():
        return {
            "contract_version": "continuous_workflow_projection_result_v1",
            "status": "not_covered",
            "reason": "continuous_session_not_available",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    try:
        return persist_continuous_session_workflow_candidate(
            session=load_seek_session(run_dir),
            application_identity={
                "name": "Microsoft Edge",
                "process": "msedge.exe",
                "url": str(getattr(args, "url", "") or ""),
            },
            goal=(
                "Review job results, open a matching job detail, enter the application "
                "flow, and stop before final submit"
            ),
            memory_store=_build_reviewed_memory_store(),
            project_root=REPO_ROOT,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "contract_version": "continuous_workflow_projection_result_v1",
            "status": "failed",
            "reason": "continuous_workflow_projection_failed",
            "error": str(exc),
            "session_path": str(session_path.resolve()),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }


def _compact_inventory_item(item: dict[str, Any], *, item_id_keys: tuple[str, ...]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in item_id_keys:
        if item.get(key) not in {None, ""}:
            compact["id"] = item.get(key)
            break
    for key in (
        "label",
        "question_text",
        "text",
        "field_type",
        "answer_type",
        "risk_class",
        "required",
        "disabled",
        "policy",
        "category",
        "reason",
        "requires_user_review",
        "answer_source",
        "bbox",
        "field_bbox",
        "question_bbox",
    ):
        value = item.get(key)
        if value is not None and value != "" and value != [] and value != {}:
            compact[key] = value
    return compact


def _compact_answer_policies(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    source = plan if isinstance(plan, dict) else {}
    if source.get("contract_version") == "answer_policy_projection_v1":
        return [dict(item) for item in source.get("policies") or [] if isinstance(item, dict)]
    items = source.get("answers") if isinstance(source.get("answers"), list) else source.get("planned_answers")
    policies: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item_source = item.get("source") if isinstance(item.get("source"), dict) else {}
        raw_value = item.get("planned_answer")
        if raw_value is None:
            raw_value = item.get("value")
        serialized = "" if raw_value is None else json.dumps(raw_value, ensure_ascii=False, sort_keys=True)
        policies.append(
            {
                "field_id": item.get("field_id") or item_source.get("id"),
                "question_id": item.get("question_id"),
                "label": item.get("label") or item.get("question_text"),
                "policy": item.get("policy") or item.get("category") or item.get("status"),
                "reason": item.get("reason"),
                "answer_source": item.get("answer_source"),
                "requires_user_review": item.get("requires_user_review"),
                "value_length": len(serialized),
                "value_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                if serialized
                else None,
                "value_redacted": bool(serialized),
            }
        )
    return policies


def _build_read_only_inventory_checkpoint(payload: dict[str, Any]) -> dict[str, Any]:
    inventory = payload.get("form_field_inventory") if isinstance(payload.get("form_field_inventory"), dict) else {}
    employer_inventory = (
        payload.get("employer_question_inventory")
        if isinstance(payload.get("employer_question_inventory"), dict)
        else {}
    )
    fields = [
        _compact_inventory_item(item, item_id_keys=("field_id", "id"))
        for item in inventory.get("fields") or []
        if isinstance(item, dict)
    ]
    question_sources = [
        *(inventory.get("questions") or []),
        *(employer_inventory.get("questions") or []),
    ]
    questions: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for item in question_sources:
        if not isinstance(item, dict):
            continue
        compact = _compact_inventory_item(item, item_id_keys=("question_id", "field_id", "id"))
        fingerprint = json.dumps(compact, ensure_ascii=False, sort_keys=True)
        if fingerprint not in seen_questions:
            seen_questions.add(fingerprint)
            questions.append(compact)
    final_actions = [
        _compact_inventory_item(item, item_id_keys=("action_id", "id"))
        for item in inventory.get("danger_actions") or []
        if isinstance(item, dict)
    ]
    application_policies = _compact_answer_policies(payload.get("application_answer_plan"))
    employer_question_policies = _compact_answer_policies(payload.get("employer_question_answer_plan"))
    answer_policies = [*application_policies, *employer_question_policies]
    ordinary_fields = [
        item
        for item in fields
        if item.get("risk_class") == "ordinary_field" and item.get("field_type") != "file_upload"
    ]
    unsupported_uploads = [
        item
        for item in fields
        if item.get("field_type") == "file_upload" or item.get("risk_class") == "unsupported_file_upload"
    ]
    review_required_questions = [
        item for item in answer_policies if item.get("question_id") and item.get("policy") == "needs_user_review"
    ]
    sensitive_questions = [
        item for item in answer_policies if item.get("question_id") and item.get("policy") == "blocked_sensitive"
    ]
    unsupported_count = sum(
        1
        for item in fields
        if item.get("field_type") == "file_upload" or item.get("risk_class") == "unsupported_file_upload"
    )
    sensitive_count = sum(
        1
        for item in [*fields, *questions]
        if item.get("risk_class") in {"blocked_sensitive", "sensitive", "needs_user_review"}
        or item.get("policy") in {"blocked_sensitive", "needs_user_review"}
    )
    live_fill_attempted = bool(
        payload.get("live_fill_attempted")
        or inventory.get("fill_attempted")
        or int((payload.get("safe_form_fill_attempt") or {}).get("fields_filled") or 0)
        or int((payload.get("employer_question_fill_attempt") or {}).get("answered_count") or 0)
    )
    submit_clicks = int(payload.get("submit_clicks") or 0) + int(
        (payload.get("continue_after_fill") or {}).get("submit_clicks") or 0
    ) + int(bool(inventory.get("submit_attempted")))
    final_submissions = int(payload.get("final_submissions") or 0) + int(
        (payload.get("continue_after_fill") or {}).get("final_submissions") or 0
    ) + int(
        (payload.get("safe_form_fill_attempt") or {}).get("final_submissions") or 0
    ) + int(
        (payload.get("employer_question_fill_attempt") or {}).get("final_submissions") or 0
    )
    contract_valid = inventory.get("contract_version") == "form_question_inventory_v1"
    read_only_confirmed = payload.get("read_only_inventory") is True
    status = (
        "pass"
        if contract_valid and read_only_confirmed and not live_fill_attempted and submit_clicks == 0 and final_submissions == 0
        else "needs_work"
    )
    return {
        "contract_version": "seek_read_only_inventory_checkpoint_v1",
        "status": status,
        "interpretation": "live read-only inventory evidence; not live safe-fill evidence",
        "summary": {
            "field_count": len(fields),
            "question_count": len(questions),
            "unsupported_count": unsupported_count,
            "sensitive_or_review_count": sensitive_count,
            "final_action_count": len(final_actions),
        },
        "fields": fields,
        "questions": questions,
        "final_actions": final_actions,
        "answer_policies": {
            "application": application_policies,
            "employer_questions": employer_question_policies,
        },
        "human_review": {
            "ordinary_fields": ordinary_fields,
            "review_required_questions": review_required_questions,
            "sensitive_questions": sensitive_questions,
            "unsupported_uploads": unsupported_uploads,
            "final_actions": final_actions,
            "interpretation": "human-review buckets only; no field value is authorized or filled",
        },
        "safety": {
            "read_only_inventory": read_only_confirmed,
            "live_fill_attempted": live_fill_attempted,
            "submit_clicks": submit_clicks,
            "final_submissions": final_submissions,
            "artifact_is_authorization": False,
        },
        "evidence": {
            "trace_paths": [str(path) for path in payload.get("trace_paths") or []],
            "screenshot_paths": [
                str(path)
                for path in (payload.get("before_image"), payload.get("after_image"))
                if path
            ],
            "source_report_path": payload.get("report_path"),
        },
        "pii_redacted": True,
    }


def _build_live_safe_fill_preflight(
    checkpoint: dict[str, Any],
    *,
    field_id: str,
    current_flow_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从只读 inventory 投影一个待人工批准的单字段填写候选。"""

    normalized_field_id = str(field_id or "").strip()
    fields = [
        dict(item)
        for item in checkpoint.get("fields") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip() == normalized_field_id
    ]
    policies = [
        dict(item)
        for group in (checkpoint.get("answer_policies") or {}).values()
        if isinstance(group, list)
        for item in group
        if isinstance(item, dict)
        and str(item.get("field_id") or "").strip() == normalized_field_id
    ]
    field = fields[0] if len(fields) == 1 else {}
    policy = policies[0] if len(policies) == 1 else {}
    eligible = (
        checkpoint.get("status") == "pass"
        and len(fields) == 1
        and len(policies) == 1
        and field.get("risk_class") == "ordinary_field"
        and field.get("field_type") != "file_upload"
        and policy.get("policy") == "auto_fill"
        and policy.get("value_redacted") is True
        and bool(policy.get("value_hash"))
        and int(policy.get("value_length") or 0) > 0
    )
    failure_reasons: list[str] = []
    if checkpoint.get("status") != "pass":
        failure_reasons.append("read_only_inventory_not_passed")
    if len(fields) != 1:
        failure_reasons.append("field_identity_not_unique")
    if len(policies) != 1:
        failure_reasons.append("answer_policy_not_unique")
    if field and field.get("risk_class") != "ordinary_field":
        failure_reasons.append("field_not_ordinary")
    if field and field.get("field_type") == "file_upload":
        failure_reasons.append("file_upload_not_supported")
    if policy and policy.get("policy") != "auto_fill":
        failure_reasons.append("answer_policy_requires_review")
    if policy and (
        policy.get("value_redacted") is not True
        or not policy.get("value_hash")
        or int(policy.get("value_length") or 0) <= 0
    ):
        failure_reasons.append("redacted_value_evidence_incomplete")

    field_projection = {
        key: field[key]
        for key in ("id", "label", "field_type", "risk_class", "required")
        if key in field
    }
    value_evidence = {
        key: policy.get(key)
        for key in (
            "answer_source",
            "value_length",
            "value_hash",
            "value_redacted",
        )
    }
    flow_state = dict(current_flow_state or {})
    return {
        "contract_version": "seek_live_safe_fill_preflight_v1",
        "status": "ready_for_human_review" if eligible else "invalid",
        "approval_state": "awaiting_explicit_approval" if eligible else "not_approvable",
        "interpretation": (
            "single-field review evidence only; not authorization and not live safe-fill evidence"
        ),
        "field": field_projection,
        "value_evidence": value_evidence,
        "target": {
            "state_type": flow_state.get("state_type"),
            "current_step": flow_state.get("current_step"),
        },
        "expected_verification": {
            "mode": "post_observe_hash_and_length",
            "expected_value_hash": policy.get("value_hash"),
            "expected_value_length": policy.get("value_length"),
            "raw_value_must_not_be_recorded": True,
        },
        "safety": {
            "max_fields": 1,
            "cover_letter_fill_allowed": False,
            "continue_allowed": False,
            "final_submit_allowed": False,
            "artifact_is_authorization": False,
        },
        "evidence": dict(checkpoint.get("evidence") or {}),
        "failure_reasons": failure_reasons,
        "pii_redacted": True,
    }


def _validate_approved_live_safe_fill_preflight(
    *,
    path: Path | None,
    expected_sha256: str | None,
    approved_field_id: str,
) -> dict[str, Any]:
    """校验人工批准是否绑定到同一份脱敏预检资产。"""

    if path is None or not str(expected_sha256 or "").strip():
        return {"status": "invalid", "reason": "preflight_path_or_checksum_missing"}
    if not path.is_file():
        return {"status": "invalid", "reason": "preflight_file_missing", "path": str(path)}
    actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha256.casefold() != str(expected_sha256).strip().casefold():
        return {
            "status": "invalid",
            "reason": "checksum_mismatch",
            "path": str(path),
            "expected_sha256": str(expected_sha256),
            "actual_sha256": actual_sha256,
        }
    try:
        preflight = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "invalid",
            "reason": "preflight_json_invalid",
            "path": str(path),
            "details": str(exc),
        }
    field = preflight.get("field") if isinstance(preflight.get("field"), dict) else {}
    safety = preflight.get("safety") if isinstance(preflight.get("safety"), dict) else {}
    checks = {
        "contract_version": preflight.get("contract_version") == "seek_live_safe_fill_preflight_v1",
        "review_status": preflight.get("status") == "ready_for_human_review",
        "approval_state": preflight.get("approval_state") == "awaiting_explicit_approval",
        "field_identity": str(field.get("id") or "").strip() == approved_field_id,
        "ordinary_field": field.get("risk_class") == "ordinary_field"
        and field.get("field_type") != "file_upload",
        "single_field_only": safety.get("max_fields") == 1,
        "cover_letter_blocked": safety.get("cover_letter_fill_allowed") is False,
        "continue_blocked": safety.get("continue_allowed") is False,
        "final_submit_blocked": safety.get("final_submit_allowed") is False,
        "not_authorization_by_itself": safety.get("artifact_is_authorization") is False,
        "pii_redacted": preflight.get("pii_redacted") is True,
    }
    if not all(checks.values()):
        return {
            "status": "invalid",
            "reason": "preflight_contract_rejected",
            "path": str(path),
            "sha256": actual_sha256,
            "checks": checks,
        }
    return {
        "status": "pass",
        "reason": "approved_preflight_bound",
        "path": str(path),
        "sha256": actual_sha256,
        "field_id": approved_field_id,
        "checks": checks,
    }


def _collect_cp14_runtime_preflight(args: argparse.Namespace) -> dict[str, Any]:
    """复用公共资源与模型检查，生成 CP14 只读运行前证据。"""

    try:
        runtime_health = _get_json(
            str(args.base_url),
            "/health",
            min(float(args.timeout), 5.0),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        runtime_health = {
            "success": False,
            "error_code": "runtime_health_preflight_failed",
            "details": str(exc),
        }
    try:
        profile = profile_for_stage("locate")
    except (OSError, RuntimeError, ValueError) as exc:
        error = {
            "status": "unavailable",
            "error_code": "locate_profile_preflight_failed",
            "details": str(exc),
        }
        return {
            "contract_version": "seek_cp14_runtime_preflight_v1",
            "runtime_health": runtime_health,
            "model_resource_preflight": error,
            "model_status": error,
        }
    try:
        resource_preflight = build_model_resource_preflight(profile)
    except (OSError, RuntimeError, ValueError) as exc:
        resource_preflight = {
            "status": "unavailable",
            "model_launch_allowed": False,
            "error_code": "gpu_resource_preflight_failed",
            "details": str(exc),
        }
    try:
        model_status = check_model_server(profile, timeout=2.0)
    except (OSError, RuntimeError, ValueError) as exc:
        model_status = {
            "status": "unavailable",
            "error_code": "locate_model_status_preflight_failed",
            "details": str(exc),
        }
    return {
        "contract_version": "seek_cp14_runtime_preflight_v1",
        "runtime_health": runtime_health,
        "model_resource_preflight": resource_preflight,
        "model_status": model_status,
    }


def _build_cp14_apply_preflight(
    *,
    args: argparse.Namespace,
    steps: list[dict[str, Any]],
    capture_payload: dict[str, Any],
    match_payload: dict[str, Any],
    runtime_preflight_payload: dict[str, Any],
) -> dict[str, Any]:
    """在 CP14 真实 Apply 入口前汇总可复盘、只读的 fail-closed 检查。"""

    capture_value = str(capture_payload.get("after_image") or "")
    capture_path = Path(capture_value) if capture_value else None
    fresh_capture_exists = bool(
        capture_path and capture_path.is_file() and capture_path.stat().st_size > 0
    )
    report_paths: list[Path] = []
    for step in steps:
        if step.get("report_path"):
            report_paths.append(Path(str(step["report_path"])))
        report_paths.extend(Path(str(path)) for path in step.get("trace_paths") or [] if path)
    trace_report_exists = any(path.is_file() and path.stat().st_size > 0 for path in report_paths)
    step_status = {
        str(step.get("step_name") or ""): str(step.get("status") or "")
        for step in steps
    }
    match_decision = str((match_payload.get("match_decision") or {}).get("decision") or "")
    runtime_health = runtime_preflight_payload.get("runtime_health") or {}
    resource_preflight = runtime_preflight_payload.get("model_resource_preflight") or {}
    model_status = runtime_preflight_payload.get("model_status") or {}
    checks = [
        {
            "name": "continuous_session_enabled",
            "passed": bool(getattr(args, "continuous_session", False)),
        },
        {
            "name": "read_only_inventory_enabled",
            "passed": bool(getattr(args, "read_only_inventory", False)),
        },
        {
            "name": "explicit_apply_entry_approval",
            "passed": bool(getattr(args, "approve_quick_apply_entry", False)),
        },
        {
            "name": "target_binding_verified",
            "passed": step_status.get("bind_and_resize_verify") == "ok",
        },
        {
            "name": "fresh_capture_exists",
            "passed": fresh_capture_exists,
            "evidence_path": str(capture_path) if capture_path else None,
        },
        {
            "name": "trace_report_exists",
            "passed": trace_report_exists,
            "evidence_paths": [str(path) for path in report_paths],
        },
        {
            "name": "agent_match_decision_ready",
            "passed": match_payload.get("status") == "ok"
            and match_decision in {"strong_apply", "maybe_apply"},
            "decision": match_decision or None,
        },
        {
            "name": "runtime_health_ready",
            "passed": runtime_health.get("success") is True,
        },
        {
            "name": "gpu_resource_capacity_ready",
            "passed": resource_preflight.get("status") == "ready"
            and resource_preflight.get("model_launch_allowed") is True
            and (resource_preflight.get("gpu") or {}).get("available") is True,
            "resource_mode": resource_preflight.get("resource_mode"),
            "recommended_batch_size": resource_preflight.get("recommended_batch_size"),
            "reason_codes": resource_preflight.get("reason_codes") or [],
        },
        {
            "name": "locate_model_service_ready",
            "passed": model_status.get("status") == "running",
            "model_status": model_status.get("status"),
            "model_id": model_status.get("model_id"),
        },
    ]
    passed = all(check["passed"] for check in checks)
    return {
        "contract_version": "seek_cp14_apply_preflight_v1",
        "status": "pass" if passed else "failed",
        "checks": checks,
        "runtime_preflight": runtime_preflight_payload,
        "safety": {
            "live_fill_allowed": False,
            "final_submit_allowed": False,
            "next_allowed_step": "execute_apply_entry" if passed else "safe_stop",
        },
    }


def _recover_seek_results_after_external_apply(
    *,
    run,
    args: argparse.Namespace,
) -> dict[str, Any]:
    open_payload = run("open", ["--url", args.url])
    if open_payload.get("status") != "ok":
        return {
            "status": "failed",
            "reason": "open_seek_after_external_apply_failed",
            "open_status": open_payload.get("status"),
        }
    cards_payload = run("extract_cards").get("cards_payload") or {}
    visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
    return {
        "status": "ok",
        "reason": "reopened_seek_results_after_external_apply",
        "visible_jobs": len(visible_cards),
        "cards_payload": cards_payload,
        "visible_cards": visible_cards,
    }


def _finish_application_flow(
    *,
    run_dir: Path,
    started: float,
    args: argparse.Namespace,
    run,
    budget_exhausted,
    steps: list[dict[str, Any]],
    job_attempts: list[dict[str, Any]],
    result_scrolls: list[dict[str, Any]],
    initial_flow_state: dict[str, Any] | None = None,
    continuous_session: dict[str, Any] | None = None,
    memory_store=None,
    cp14_preflight_report_path: str | None = None,
) -> dict[str, Any]:
    read_only_inventory = bool(getattr(args, "read_only_inventory", False))
    prepare_live_safe_fill = bool(getattr(args, "prepare_live_safe_fill", False))
    last_flow_state = dict(initial_flow_state or {})
    application_stop_status: str | None = None
    application_stop_reason: str | None = None
    continuous_session_path: Path | None = None
    continuous_checkpoint_path: Path | None = None

    if (
        not read_only_inventory
        and not prepare_live_safe_fill
        and not bool(getattr(args, "approve_live_safe_fill", False))
    ):
        return _write_speed_demo_result(
            run_dir,
            started=started,
            args=args,
            steps=steps,
            job_attempts=job_attempts,
            result_scrolls=result_scrolls,
            status="needs_work",
            stop_reason="live_safe_fill_approval_required",
            extra={
                "application_started": True,
                "live_fill_attempted": False,
                "submit_clicks": 0,
                "final_submissions": 0,
                "last_flow_state": last_flow_state,
            },
        )
    approved_live_field_id = str(getattr(args, "approved_live_field_id", None) or "").strip() or None
    prepare_live_safe_fill_field_id = (
        str(getattr(args, "prepare_live_safe_fill_field_id", None) or "").strip() or None
    )
    if prepare_live_safe_fill and prepare_live_safe_fill_field_id is None:
        return _write_speed_demo_result(
            run_dir,
            started=started,
            args=args,
            steps=steps,
            job_attempts=job_attempts,
            result_scrolls=result_scrolls,
            status="needs_work",
            stop_reason="prepare_live_safe_fill_field_id_required",
            extra={
                "application_started": True,
                "live_fill_attempted": False,
                "submit_clicks": 0,
                "final_submissions": 0,
                "last_flow_state": last_flow_state,
            },
        )
    if not read_only_inventory and not prepare_live_safe_fill and approved_live_field_id is None:
        return _write_speed_demo_result(
            run_dir,
            started=started,
            args=args,
            steps=steps,
            job_attempts=job_attempts,
            result_scrolls=result_scrolls,
            status="needs_work",
            stop_reason="approved_live_field_id_required",
            extra={
                "application_started": True,
                "live_fill_attempted": False,
                "submit_clicks": 0,
                "final_submissions": 0,
                "last_flow_state": last_flow_state,
            },
        )
    approved_live_fill_preflight_validation: dict[str, Any] | None = None
    if not read_only_inventory and not prepare_live_safe_fill:
        approved_preflight_value = str(
            getattr(args, "approved_live_fill_preflight", None) or ""
        ).strip()
        approved_live_fill_preflight_validation = _validate_approved_live_safe_fill_preflight(
            path=Path(approved_preflight_value) if approved_preflight_value else None,
            expected_sha256=str(
                getattr(args, "approved_live_fill_preflight_sha256", None) or ""
            ).strip()
            or None,
            approved_field_id=approved_live_field_id or "",
        )
        if approved_live_fill_preflight_validation.get("status") != "pass":
            missing = approved_live_fill_preflight_validation.get("reason") == (
                "preflight_path_or_checksum_missing"
            )
            return _write_speed_demo_result(
                run_dir,
                started=started,
                args=args,
                steps=steps,
                job_attempts=job_attempts,
                result_scrolls=result_scrolls,
                status="needs_work",
                stop_reason=(
                    "approved_live_fill_preflight_required"
                    if missing
                    else "approved_live_fill_preflight_invalid"
                ),
                extra={
                    "application_started": True,
                    "live_fill_attempted": False,
                    "submit_clicks": 0,
                    "final_submissions": 0,
                    "last_flow_state": last_flow_state,
                    "approved_live_fill_preflight_validation": (
                        approved_live_fill_preflight_validation
                    ),
                },
            )

    for _ in range(args.max_application_steps):
        if budget_exhausted(reserve_ms=12000):
            return _write_speed_demo_result(
                run_dir,
                started=started,
                args=args,
                steps=steps,
                job_attempts=job_attempts,
                result_scrolls=result_scrolls,
                status="needs_work",
                stop_reason="time_budget_exhausted_before_application_step",
                extra={
                    "application_started": True,
                    "last_flow_state": last_flow_state,
                    **(
                        {"continuous_session_path": str(continuous_session_path)}
                        if continuous_session_path
                        else {}
                    ),
                },
            )
        application_step_args = ["--read-only-inventory"] if read_only_inventory or prepare_live_safe_fill else [
            "--fill-safe-fields",
            "--max-safe-fields-to-fill",
            "1",
            "--approved-live-field-id",
            approved_live_field_id,
        ]
        payload = run("continue_application_flow", application_step_args)
        if isinstance(payload.get("application_flow_state"), dict):
            last_flow_state = payload["application_flow_state"]
        elif isinstance(payload.get("post_apply_wait"), dict) and isinstance(
            payload["post_apply_wait"].get("application_flow_state"), dict
        ):
            last_flow_state = payload["post_apply_wait"]["application_flow_state"]

        if read_only_inventory or prepare_live_safe_fill:
            checkpoint = _build_read_only_inventory_checkpoint(payload)
            checkpoint_path = run_dir / "read_only_inventory_report.json"
            _write_json(checkpoint_path, checkpoint)
            if prepare_live_safe_fill:
                preflight = _build_live_safe_fill_preflight(
                    checkpoint,
                    field_id=prepare_live_safe_fill_field_id or "",
                    current_flow_state=last_flow_state,
                )
                preflight_path = run_dir / "live_safe_fill_preflight.json"
                _write_json(preflight_path, preflight)
                preflight_ready = preflight.get("status") == "ready_for_human_review"
                return _write_speed_demo_result(
                    run_dir,
                    started=started,
                    args=args,
                    steps=steps,
                    job_attempts=job_attempts,
                    result_scrolls=result_scrolls,
                    status="needs_work",
                    stop_reason=(
                        "live_safe_fill_preflight_ready"
                        if preflight_ready
                        else "live_safe_fill_preflight_contract_failed"
                    ),
                    extra={
                        "application_started": True,
                        "read_only_inventory_report_path": str(checkpoint_path),
                        "live_safe_fill_preflight_path": str(preflight_path),
                        "live_safe_fill_preflight_status": preflight.get("status"),
                        "live_fill_attempted": False,
                        "submit_clicks": checkpoint.get("safety", {}).get("submit_clicks"),
                        "final_submissions": checkpoint.get("safety", {}).get("final_submissions"),
                        "last_flow_state": last_flow_state,
                    },
                )
            return _write_speed_demo_result(
                run_dir,
                started=started,
                args=args,
                steps=steps,
                job_attempts=job_attempts,
                result_scrolls=result_scrolls,
                status="pass" if checkpoint.get("status") == "pass" else "needs_work",
                stop_reason=(
                    "read_only_inventory_complete"
                    if checkpoint.get("status") == "pass"
                    else "read_only_inventory_contract_failed"
                ),
                extra={
                    "application_started": True,
                    "read_only_inventory_report_path": str(checkpoint_path),
                    "read_only_inventory_status": checkpoint.get("status"),
                    "live_fill_attempted": checkpoint.get("safety", {}).get("live_fill_attempted"),
                    "submit_clicks": checkpoint.get("safety", {}).get("submit_clicks"),
                    "final_submissions": checkpoint.get("safety", {}).get("final_submissions"),
                    "last_flow_state": last_flow_state,
                    **(
                        {"cp14_preflight_report_path": cp14_preflight_report_path}
                        if cp14_preflight_report_path
                        else {}
                    ),
                },
            )

        if continuous_session is not None and memory_store is not None:
            evidence = build_step_evidence(payload, run_dir=run_dir)
            if payload.get("status") != "blocked_need_user_or_gpt_decision":
                continuous_session = record_action_result(
                    continuous_session,
                    action_type="continue_next_step",
                    action_executed=True,
                    post_action_verified=True,
                    evidence=evidence,
                    transition_audit=_transition_audit(payload),
                )
            final_submit_visible = _final_review_ready(last_flow_state)
            interface_id = quick_apply_interface_id(last_flow_state)
            memory_sha256 = None if final_submit_visible else resolve_active_memory_sha256(memory_store, interface_id)
            continuous_session = observe_interface(
                continuous_session,
                interface_id=interface_id,
                surface_type="final_submit_visible" if final_submit_visible else "seek_quick_apply",
                memory_object_sha256=memory_sha256,
                evidence=evidence,
                learning_required=not final_submit_visible,
                knowledge_source="reviewed_interface_memory",
            )
            continuous_session_path = save_seek_session(run_dir, continuous_session)
            continuous_checkpoint_path = save_seek_checkpoint(
                run_dir,
                {
                    "phase": "final_submit_safe_stop" if final_submit_visible else "quick_apply",
                    "application_started": True,
                    "last_flow_state": last_flow_state,
                },
            )
            if continuous_session.get("status") == "paused_for_learning":
                return _write_speed_demo_result(
                    run_dir,
                    started=started,
                    args=args,
                    steps=steps,
                    job_attempts=job_attempts,
                    result_scrolls=result_scrolls,
                    status="paused_for_learning",
                    stop_reason="reviewed_quick_apply_memory_required",
                    extra={
                        "continuous_session_path": str(continuous_session_path),
                        "continuous_checkpoint_path": str(continuous_checkpoint_path),
                        "pending_learning": continuous_session.get("pending_learning"),
                        "application_flow_state": last_flow_state,
                    },
                )
            if continuous_session.get("status") == "safe_stop":
                application_stop_status = "safe_stop"
                application_stop_reason = str(continuous_session.get("stop_reason") or "")
                break

        if payload.get("status") == "blocked_need_user_or_gpt_decision":
            application_stop_status = str(payload.get("status") or "")
            application_stop_reason = str(last_flow_state.get("stop_reason") or payload.get("stop_reason") or "")
            break
        if "continue_application_flow" not in (payload.get("next_allowed_steps") or []):
            break

    record_path = run_dir / "application_fill_record.json"
    record = build_record_from_debug_run(run_dir)
    _write_json(record_path, record)
    final_review: dict[str, Any] = {
        "status": "not_attempted",
        "reason": "not_at_review_and_submit",
        "application_flow_state": last_flow_state,
    }
    extraction_path = run_dir / "final_review_extraction.json"
    extraction: dict[str, Any] = {
        "contract_version": "seek_final_review_extraction_v1",
        "status": "not_attempted",
        "reason": "not_at_review_and_submit",
        "current_step": last_flow_state.get("current_step"),
        "state_type": last_flow_state.get("state_type"),
    }
    if _final_review_ready(last_flow_state):
        final_review = run("extract_final_review", ["--application-fill-record", str(record_path)])
        extraction_path = Path(str(final_review.get("final_review_extraction_path") or extraction_path))
        extraction = _read_json(extraction_path) if extraction_path.exists() else {}
    else:
        _write_json(extraction_path, extraction)
    artifact = build_seek_application_flow_artifact(
        record,
        final_review_extraction=extraction,
        record_path=record_path,
        final_review_extraction_path=extraction_path,
    )
    artifact_path = run_dir / "seek_application_flow_artifact.json"
    _write_json(artifact_path, artifact)
    readiness = build_demo_readiness_report(
        run_dir=run_dir,
        step_reports=load_step_reports(run_dir),
        application_fill_record=record,
        final_review_audit=extraction,
        long_read_benchmark=None,
        time_budget_ms=args.time_budget_ms,
    )
    readiness_path = run_dir / "demo_readiness_report.json"
    _write_json(readiness_path, readiness)
    total_ms = round((time.perf_counter() - started) * 1000, 3)
    safe_stop = bool(continuous_session and continuous_session.get("status") == "safe_stop")
    result = {
        "contract_version": "seek_speed_demo_run_v1",
        "status": (
            "safe_stop"
            if safe_stop
            else "pass"
            if readiness.get("status") == "pass" and extraction.get("status") == "pass"
            else "needs_work"
        ),
        "stop_reason": continuous_session.get("stop_reason") if safe_stop and continuous_session else None,
        "run_dir": str(run_dir),
        "total_ms": total_ms,
        "time_budget_ms": args.time_budget_ms,
        "within_budget": total_ms <= args.time_budget_ms,
        "steps": steps,
        "job_attempts": job_attempts,
        "result_scrolls": result_scrolls,
        "application_fill_record_path": str(record_path),
        "final_review_extraction_path": str(extraction_path),
        "artifact_path": str(artifact_path),
        "readiness_report_path": str(readiness_path),
        "readiness_status": readiness.get("status"),
        "final_review_status": extraction.get("status"),
        "application_stop_status": application_stop_status,
        "application_stop_reason": application_stop_reason,
        "final_submissions": extraction.get("final_submissions", record.get("final_submissions", 0)),
        "submit_clicks": extraction.get("submit_clicks", record.get("submit_clicks", 0)),
    }
    if continuous_session_path:
        result["continuous_session_path"] = str(continuous_session_path)
    if continuous_checkpoint_path:
        result["continuous_checkpoint_path"] = str(continuous_checkpoint_path)
    if cp14_preflight_report_path:
        result["cp14_preflight_report_path"] = cp14_preflight_report_path
    if approved_live_fill_preflight_validation:
        result["approved_live_fill_preflight_validation"] = (
            approved_live_fill_preflight_validation
        )
    result["multi_interface_workflow"] = _persist_multi_interface_workflow(
        run_dir=run_dir,
        args=args,
    )
    _write_json(run_dir / "speed_demo_report.json", result)
    return result


def run_speed_demo(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    steps: list[dict[str, Any]] = []
    job_attempts: list[dict[str, Any]] = []
    result_scrolls: list[dict[str, Any]] = []
    continuous_enabled = bool(getattr(args, "continuous_session", False))
    resume_continuous = continuous_enabled and bool(getattr(args, "resume_continuous_session", False))
    continuous_session: dict[str, Any] | None = None
    continuous_session_path: Path | None = None
    continuous_checkpoint_path: Path | None = None
    resume_checkpoint: dict[str, Any] | None = None
    memory_store = _build_reviewed_memory_store() if continuous_enabled else None
    if resume_continuous:
        continuous_session = load_seek_session(run_dir)
        resume_checkpoint = load_seek_checkpoint(run_dir)
        stored_attempt = resume_checkpoint.get("job_attempt")
        if isinstance(stored_attempt, dict):
            job_attempts.append(stored_attempt)
        if continuous_session.get("status") == "paused_for_learning":
            pending = (
                continuous_session.get("pending_learning")
                if isinstance(continuous_session.get("pending_learning"), dict)
                else {}
            )
            pending_interface_id = str(pending.get("interface_id") or "")
            memory_sha256 = (
                resolve_active_memory_sha256(memory_store, pending_interface_id)
                if memory_store is not None and pending_interface_id
                else None
            )
            if memory_sha256:
                continuous_session = resume_after_learning(
                    continuous_session,
                    interface_id=pending_interface_id,
                    memory_object_sha256=memory_sha256,
                )
        continuous_session_path = save_seek_session(run_dir, continuous_session)
        continuous_checkpoint_path = run_dir / "seek_continuous_checkpoint.json"
    elif continuous_enabled:
        continuous_session = create_continuous_task_session(
            session_id=run_dir.name,
            workflow_id="seek-quick-apply-demo",
        )
        continuous_session_path = save_seek_session(run_dir, continuous_session)
    deadline = started + (float(args.time_budget_ms) / 1000.0) if args.time_budget_ms else None

    def budget_exhausted(*, reserve_ms: float = 0.0) -> bool:
        return bool(deadline is not None and time.perf_counter() + (reserve_ms / 1000.0) >= deadline)

    def budget_stop(reason: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return _write_speed_demo_result(
            run_dir,
            started=started,
            args=args,
            steps=steps,
            job_attempts=job_attempts,
            result_scrolls=result_scrolls,
            status="needs_work",
            stop_reason=reason,
            extra=extra,
        )

    def run(step: str, extra: list[str] | None = None) -> dict[str, Any]:
        step_args = [
            "--base-url",
            str(args.base_url),
            "--timeout",
            str(args.timeout),
            *(extra or []),
        ]
        payload = _run_step(run_dir, step, step_args)
        steps.append(_step_summary(payload))
        if (
            step == "execute_apply_entry"
            and payload.get("status") == "blocked_need_user_or_gpt_decision"
            and (payload.get("apply_entry") or {}).get("application_flow_started") is True
        ):
            return payload
        if step == "execute_apply_entry" and payload.get("status") == "blocked_need_user_or_gpt_decision":
            return payload
        if step == "execute_card" and payload.get("status") == "failed":
            return payload
        if payload.get("status") in {"blocked_need_user_or_gpt_decision", "failed"} and step not in {
            "continue_application_flow",
            "extract_final_review",
        }:
            raise RuntimeError(f"{step} stopped with status {payload.get('status')}")
        return payload

    def run_cp14_apply_preflight(match_payload: dict[str, Any]) -> dict[str, Any] | None:
        if not bool(getattr(args, "cp14_live_uat", False)):
            return None
        runtime_preflight_payload = _collect_cp14_runtime_preflight(args)
        capture_payload = run("capture")
        preflight = _build_cp14_apply_preflight(
            args=args,
            steps=steps,
            capture_payload=capture_payload,
            match_payload=match_payload,
            runtime_preflight_payload=runtime_preflight_payload,
        )
        preflight_path = run_dir / "cp14_apply_preflight.json"
        _write_json(preflight_path, preflight)
        preflight["report_path"] = str(preflight_path)
        return preflight

    if resume_continuous and continuous_session is not None and resume_checkpoint is not None:
        if continuous_session.get("status") == "paused_for_learning":
            return _write_speed_demo_result(
                run_dir,
                started=started,
                args=args,
                steps=steps,
                job_attempts=job_attempts,
                result_scrolls=result_scrolls,
                status="paused_for_learning",
                stop_reason="reviewed_quick_apply_memory_required",
                extra={
                    "continuous_session_path": str(continuous_session_path),
                    "continuous_checkpoint_path": str(continuous_checkpoint_path),
                    "pending_learning": continuous_session.get("pending_learning"),
                },
            )
        if resume_checkpoint.get("phase") == "awaiting_apply_confirmation":
            if not bool(getattr(args, "approve_quick_apply_entry", False)):
                return _write_speed_demo_result(
                    run_dir,
                    started=started,
                    args=args,
                    steps=steps,
                    job_attempts=job_attempts,
                    result_scrolls=result_scrolls,
                    status="awaiting_confirmation",
                    stop_reason="quick_apply_entry_confirmation_required",
                    extra={
                        "continuous_session_path": str(continuous_session_path),
                        "continuous_checkpoint_path": str(continuous_checkpoint_path),
                        "pending_apply_confirmation": continuous_session.get("pending_apply_confirmation"),
                    },
                )
            continuous_session = confirm_apply_entry(continuous_session, approved=True)
            continuous_session_path = save_seek_session(run_dir, continuous_session)
            resumed_attempt = resume_checkpoint.get("job_attempt") or {}
            preflight = run_cp14_apply_preflight(
                {
                    "status": "ok",
                    "match_decision": {"decision": resumed_attempt.get("match_decision")},
                }
            )
            if preflight is not None and preflight.get("status") != "pass":
                return _write_speed_demo_result(
                    run_dir,
                    started=started,
                    args=args,
                    steps=steps,
                    job_attempts=job_attempts,
                    result_scrolls=result_scrolls,
                    status="needs_work",
                    stop_reason="cp14_apply_preflight_failed",
                    extra={"cp14_preflight_report_path": preflight.get("report_path")},
                )
            apply_args = ["--allow-maybe-apply"] if args.allow_maybe_apply else []
            execute_apply = run(
                "execute_apply_entry",
                [
                    "--post-apply-capture-wait-seconds",
                    str(args.post_apply_capture_wait_seconds),
                    *apply_args,
                ],
            )
            apply_state = _apply_entry_state(execute_apply)
            apply_evidence = build_step_evidence(execute_apply, run_dir=run_dir)
            if _external_apply_flow_started(execute_apply):
                continuous_session = observe_interface(
                    continuous_session,
                    interface_id=quick_apply_interface_id(apply_state),
                    surface_type="external_ats",
                    memory_object_sha256=None,
                    evidence=apply_evidence,
                    learning_required=False,
                    knowledge_source="seek_runtime_profile",
                )
                continuous_session_path = save_seek_session(run_dir, continuous_session)
                return _write_speed_demo_result(
                    run_dir,
                    started=started,
                    args=args,
                    steps=steps,
                    job_attempts=job_attempts,
                    result_scrolls=result_scrolls,
                    status="safe_stop",
                    stop_reason="external_ats_not_supported",
                    extra={
                        "continuous_session_path": str(continuous_session_path),
                        "continuous_checkpoint_path": str(continuous_checkpoint_path),
                        "external_apply_state": apply_state,
                    },
                )
            if not _station_internal_application_started(execute_apply):
                return _write_speed_demo_result(
                    run_dir,
                    started=started,
                    args=args,
                    steps=steps,
                    job_attempts=job_attempts,
                    result_scrolls=result_scrolls,
                    status="needs_work",
                    stop_reason=str(apply_state.get("stop_reason") or "quick_apply_entry_not_verified"),
                    extra={
                        "continuous_session_path": str(continuous_session_path),
                        "continuous_checkpoint_path": str(continuous_checkpoint_path),
                        "application_flow_state": apply_state,
                    },
                )
            continuous_session = record_action_result(
                continuous_session,
                action_type="open_apply_flow",
                action_executed=True,
                post_action_verified=True,
                evidence=apply_evidence,
                transition_audit=_transition_audit(
                    execute_apply,
                    agent_decision=(resume_checkpoint.get("job_attempt") or {}).get("match_decision"),
                ),
            )
            quick_apply_id = quick_apply_interface_id(apply_state)
            quick_apply_memory_sha256 = resolve_active_memory_sha256(memory_store, quick_apply_id)
            continuous_session = observe_interface(
                continuous_session,
                interface_id=quick_apply_id,
                surface_type="seek_quick_apply",
                memory_object_sha256=quick_apply_memory_sha256,
                evidence=apply_evidence,
                learning_required=True,
                knowledge_source="reviewed_interface_memory",
            )
            continuous_session_path = save_seek_session(run_dir, continuous_session)
            continuous_checkpoint_path = save_seek_checkpoint(
                run_dir,
                {
                    "phase": "quick_apply",
                    "application_started": True,
                    "job_attempt": resume_checkpoint.get("job_attempt"),
                    "last_flow_state": apply_state,
                },
            )
            if continuous_session.get("status") == "paused_for_learning":
                return _write_speed_demo_result(
                    run_dir,
                    started=started,
                    args=args,
                    steps=steps,
                    job_attempts=job_attempts,
                    result_scrolls=result_scrolls,
                    status="paused_for_learning",
                    stop_reason="reviewed_quick_apply_memory_required",
                    extra={
                        "continuous_session_path": str(continuous_session_path),
                        "continuous_checkpoint_path": str(continuous_checkpoint_path),
                        "pending_learning": continuous_session.get("pending_learning"),
                        "application_flow_state": apply_state,
                    },
                )
            return _finish_application_flow(
                run_dir=run_dir,
                started=started,
                args=args,
                run=run,
                budget_exhausted=budget_exhausted,
                steps=steps,
                job_attempts=job_attempts,
                result_scrolls=result_scrolls,
                initial_flow_state=apply_state,
                continuous_session=continuous_session,
                memory_store=memory_store,
                cp14_preflight_report_path=(preflight or {}).get("report_path"),
            )
        if resume_checkpoint.get("phase") == "quick_apply":
            return _finish_application_flow(
                run_dir=run_dir,
                started=started,
                args=args,
                run=run,
                budget_exhausted=budget_exhausted,
                steps=steps,
                job_attempts=job_attempts,
                result_scrolls=result_scrolls,
                initial_flow_state=resume_checkpoint.get("last_flow_state"),
                continuous_session=continuous_session,
                memory_store=memory_store,
            )
        raise RuntimeError(f"unsupported continuous SEEK resume phase: {resume_checkpoint.get('phase')}")

    if args.close_old_windows:
        run("close_old_seek_windows", ["--allow-close-windows"])
    run("open", ["--url", args.url])
    run(
        "bind_and_resize_verify",
        ["--window-width", str(args.window_width), "--window-height", str(args.window_height)],
    )
    run("capture")
    extract_cards = run("extract_cards")
    cards_payload = extract_cards.get("cards_payload") or {}
    visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
    if continuous_enabled and continuous_session is not None and memory_store is not None:
        results_interface_id = "seek_results_reviewed_current"
        results_memory_sha256 = resolve_active_memory_sha256(memory_store, results_interface_id)
        continuous_session = observe_interface(
            continuous_session,
            interface_id=results_interface_id,
            surface_type="seek_results",
            memory_object_sha256=results_memory_sha256,
            evidence=build_step_evidence(extract_cards, run_dir=run_dir),
            learning_required=False,
            knowledge_source="reviewed_interface_memory" if results_memory_sha256 else "seek_runtime_profile",
        )
        continuous_session_path = save_seek_session(run_dir, continuous_session)
    application_started = False
    attempted_jobs = 0
    scroll_round = 0
    while attempted_jobs < args.max_jobs and not application_started:
        if budget_exhausted(reserve_ms=25000):
            return budget_stop("time_budget_exhausted_before_next_job")
        visible_exhausted = False
        for visible_index in range(args.visible_jobs_per_page):
            if budget_exhausted(reserve_ms=25000):
                return budget_stop("time_budget_exhausted_before_next_job")
            if attempted_jobs >= args.max_jobs:
                break
            job_index = args.job_index + visible_index
            if job_index >= len(visible_cards):
                job_attempts.append(
                    {
                        "job_index": job_index,
                        "scroll_round": scroll_round,
                        "status": "visible_cards_exhausted",
                        "reason": f"job_index {job_index} out of range for {len(visible_cards)} visible jobs",
                    }
                )
                visible_exhausted = True
                break
            attempted_jobs += 1
            card = visible_cards[job_index] if isinstance(visible_cards[job_index], dict) else {}
            prefilter = _card_prefilter_decision(
                card,
                learned_fast_mode=not getattr(args, "disable_learned_fast_mode", False),
            )
            if prefilter["decision"] == "skip":
                job_attempts.append(
                    {
                        "job_index": job_index,
                        "scroll_round": scroll_round,
                        "status": "skipped_card_prefilter",
                        "reason": prefilter["reason"],
                        "job_title": card.get("title"),
                        "company": card.get("company"),
                    }
                )
                continue
            if _card_needs_scroll_into_safer_position(card, window_height=args.window_height):
                job_attempts.append(
                    {
                        "job_index": job_index,
                        "scroll_round": scroll_round,
                        "status": "deferred_low_visible_card",
                        "reason": "card_too_close_to_bottom_for_stable_click",
                        "job_title": card.get("title"),
                        "company": card.get("company"),
                    }
                )
                visible_exhausted = True
                break
            execute_card = run("execute_card", ["--job-index", str(job_index), "--fast-open-detail"])
            if execute_card.get("status") != "ok":
                job_attempts.append(
                    {
                        "job_index": job_index,
                        "scroll_round": scroll_round,
                        "status": "skipped_card_open_failed",
                        "reason": (execute_card.get("action") or {}).get("failure_reason") or execute_card.get("status"),
                        "job_title": card.get("title"),
                        "company": card.get("company"),
                    }
                )
                cards_payload = run("extract_cards").get("cards_payload") or {}
                visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
                continue
            if continuous_enabled and continuous_session is not None:
                detail_evidence = build_step_evidence(execute_card, run_dir=run_dir)
                continuous_session = record_action_result(
                    continuous_session,
                    action_type="open_detail",
                    action_executed=True,
                    post_action_verified=True,
                    evidence=detail_evidence,
                    transition_audit=_transition_audit(execute_card),
                )
                continuous_session = observe_interface(
                    continuous_session,
                    interface_id="seek_job_detail_runtime_profile",
                    surface_type="seek_job_detail",
                    memory_object_sha256=None,
                    evidence=detail_evidence,
                    learning_required=False,
                    knowledge_source="seek_runtime_profile",
                )
                continuous_session_path = save_seek_session(run_dir, continuous_session)
            detail_read = run(
                "read_detail_batch",
                [
                    "--batch-max-captures",
                    str(args.batch_max_captures),
                    "--batch-stop-after-no-new-content",
                    str(args.batch_stop_after_no_new_content),
                    "--wheel-clicks",
                    str(args.wheel_clicks),
                ],
            )
            if detail_read.get("read_complete") is False:
                job_attempts.append(
                    {
                        "job_index": job_index,
                        "scroll_round": scroll_round,
                        "status": "skipped_detail_incomplete",
                        "reason": detail_read.get("read_state") or detail_read.get("stop_reason") or "unknown",
                        "job_title": card.get("title"),
                        "company": card.get("company"),
                    }
                )
                continue
            match_args: list[str] = []
            agent_suitability_review = str(getattr(args, "agent_suitability_review", "") or "").strip()
            if agent_suitability_review:
                match_args.extend(["--agent-suitability-review", agent_suitability_review])
            match = run("match", match_args)
            decision = (match.get("match_decision") or {}).get("decision")
            attempt: dict[str, Any] = {
                "job_index": job_index,
                "scroll_round": scroll_round,
                "match_decision": decision,
                "job_title": (match.get("detail") or {}).get("title"),
                "company": (match.get("detail") or {}).get("company"),
            }
            if not _apply_decision_allowed(decision, allow_maybe_apply=bool(args.allow_maybe_apply)):
                attempt["status"] = "skipped_match_not_eligible"
                if decision == "maybe_apply":
                    attempt["reason"] = "maybe_apply_requires_explicit_allow_maybe_apply"
                job_attempts.append(attempt)
                continue
            if continuous_enabled and continuous_session is not None:
                continuous_session = request_apply_entry_confirmation(
                    continuous_session,
                    job_id=str(card.get("job_id") or card.get("id") or f"visible-{job_index}"),
                    job_title=str(attempt.get("job_title") or card.get("title") or f"Job {job_index}"),
                )
                continuous_session_path = save_seek_session(run_dir, continuous_session)
                continuous_checkpoint_path = save_seek_checkpoint(
                    run_dir,
                    {
                        "phase": "awaiting_apply_confirmation",
                        "application_started": False,
                        "job_index": job_index,
                        "job_attempt": attempt,
                        "last_flow_state": {},
                    },
                )
                if not bool(getattr(args, "approve_quick_apply_entry", False)):
                    return _write_speed_demo_result(
                        run_dir,
                        started=started,
                        args=args,
                        steps=steps,
                        job_attempts=job_attempts,
                        result_scrolls=result_scrolls,
                        status="awaiting_confirmation",
                        stop_reason="quick_apply_entry_confirmation_required",
                        extra={
                            "continuous_session_path": str(continuous_session_path),
                            "continuous_checkpoint_path": str(continuous_checkpoint_path),
                            "pending_apply_confirmation": continuous_session.get("pending_apply_confirmation"),
                        },
                    )
                continuous_session = confirm_apply_entry(continuous_session, approved=True)
                continuous_session_path = save_seek_session(run_dir, continuous_session)
            preflight = run_cp14_apply_preflight(match)
            if preflight is not None and preflight.get("status") != "pass":
                return _write_speed_demo_result(
                    run_dir,
                    started=started,
                    args=args,
                    steps=steps,
                    job_attempts=job_attempts,
                    result_scrolls=result_scrolls,
                    status="needs_work",
                    stop_reason="cp14_apply_preflight_failed",
                    extra={"cp14_preflight_report_path": preflight.get("report_path")},
                )
            apply_args = ["--allow-maybe-apply"] if args.allow_maybe_apply else []
            execute_apply = run(
                "execute_apply_entry",
                [
                    "--post-apply-capture-wait-seconds",
                    str(args.post_apply_capture_wait_seconds),
                    *apply_args,
                ],
            )
            if execute_apply.get("status") == "skipped":
                attempt["status"] = "skipped_apply_entry_execute"
                attempt["apply_entry_stop_reason"] = (execute_apply.get("apply_entry") or {}).get("stop_reason")
                job_attempts.append(attempt)
                continue
            apply_state = _apply_entry_state(execute_apply)
            if not _station_internal_application_started(execute_apply):
                attempt["status"] = "skipped_apply_entry_execute"
                attempt["apply_entry_stop_reason"] = apply_state.get("stop_reason")
                attempt["apply_entry_state_type"] = apply_state.get("state_type")
                job_attempts.append(attempt)
                if _external_apply_flow_started(execute_apply):
                    if _external_ats_login_required(execute_apply):
                        return _write_speed_demo_result(
                            run_dir,
                            started=started,
                            args=args,
                            steps=steps,
                            job_attempts=job_attempts,
                            result_scrolls=result_scrolls,
                            status="safe_stop",
                            stop_reason="external_ats_login_required_safe_stop",
                            extra={
                                "safe_stop": {
                                    "contract_version": "seek_safe_stop_v1",
                                    "reason": "external_ats_login_required",
                                    "surface": "external_ats",
                                    "state_type": apply_state.get("state_type"),
                                    "stop_reason": apply_state.get("stop_reason"),
                                    "forbidden_next_steps": [
                                        "seek_results_extraction",
                                        "result_scroll",
                                        "next_card_lookup",
                                        "safe_fill",
                                        "final_submit",
                                    ],
                                },
                                "state_machine_failure": {
                                    "contract_version": "state_machine_failure_v1",
                                    "category": "surface_drift_prevented",
                                    "reason": "external ATS login blocker must terminate SEEK card loop",
                                },
                                "external_apply_state": apply_state,
                            },
                        )
                    if attempted_jobs >= args.max_jobs:
                        return _write_speed_demo_result(
                            run_dir,
                            started=started,
                            args=args,
                            steps=steps,
                            job_attempts=job_attempts,
                            result_scrolls=result_scrolls,
                            status="needs_work",
                            stop_reason="external_apply_flow_opened_no_remaining_job_budget",
                            extra={
                                "external_apply_state": apply_state,
                                "safety_note": "external ATS opened after the final allowed job attempt",
                            },
                        )
                    recovery = _recover_seek_results_after_external_apply(run=run, args=args)
                    attempt["external_apply_recovery"] = {
                        key: recovery.get(key)
                        for key in ("status", "reason", "visible_jobs", "open_status")
                        if key in recovery
                    }
                    if recovery.get("status") != "ok":
                        return _write_speed_demo_result(
                            run_dir,
                            started=started,
                            args=args,
                            steps=steps,
                            job_attempts=job_attempts,
                            result_scrolls=result_scrolls,
                            status="needs_work",
                            stop_reason="external_apply_flow_opened_cannot_recover_seek_results",
                            extra={
                                "external_apply_state": apply_state,
                                "external_apply_recovery": recovery,
                                "safety_note": "external ATS opened and SEEK result scope could not be re-established",
                            },
                        )
                    cards_payload = recovery.get("cards_payload") if isinstance(recovery.get("cards_payload"), dict) else {}
                    visible_cards = recovery.get("visible_cards") if isinstance(recovery.get("visible_cards"), list) else []
                    continue
                if attempted_jobs >= args.max_jobs:
                    continue
                cards_payload = run("extract_cards").get("cards_payload") or {}
                visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
                continue
            attempt["status"] = "application_started"
            job_attempts.append(attempt)
            if continuous_enabled and continuous_session is not None and memory_store is not None:
                apply_evidence = build_step_evidence(execute_apply, run_dir=run_dir)
                continuous_session = record_action_result(
                    continuous_session,
                    action_type="open_apply_flow",
                    action_executed=True,
                    post_action_verified=True,
                    evidence=apply_evidence,
                    transition_audit=_transition_audit(execute_apply, agent_decision=decision),
                )
                quick_apply_id = quick_apply_interface_id(apply_state)
                quick_apply_memory_sha256 = resolve_active_memory_sha256(memory_store, quick_apply_id)
                continuous_session = observe_interface(
                    continuous_session,
                    interface_id=quick_apply_id,
                    surface_type="seek_quick_apply",
                    memory_object_sha256=quick_apply_memory_sha256,
                    evidence=apply_evidence,
                    learning_required=True,
                    knowledge_source="reviewed_interface_memory",
                )
                continuous_session_path = save_seek_session(run_dir, continuous_session)
                continuous_checkpoint_path = save_seek_checkpoint(
                    run_dir,
                    {
                        "phase": "quick_apply",
                        "application_started": True,
                        "job_index": job_index,
                        "job_attempt": attempt,
                        "last_flow_state": apply_state,
                    },
                )
                if continuous_session.get("status") == "paused_for_learning":
                    return _write_speed_demo_result(
                        run_dir,
                        started=started,
                        args=args,
                        steps=steps,
                        job_attempts=job_attempts,
                        result_scrolls=result_scrolls,
                        status="paused_for_learning",
                        stop_reason="reviewed_quick_apply_memory_required",
                        extra={
                            "continuous_session_path": str(continuous_session_path),
                            "continuous_checkpoint_path": str(continuous_checkpoint_path),
                            "pending_learning": continuous_session.get("pending_learning"),
                            "application_flow_state": apply_state,
                        },
                    )
            application_started = True
            break
        if application_started or attempted_jobs >= args.max_jobs:
            break
        if budget_exhausted(reserve_ms=15000):
            return budget_stop("time_budget_exhausted_before_results_scroll")
        scroll_round += 1
        previous_fingerprint = _cards_fingerprint(visible_cards)
        for scroll_attempt in range(3):
            requested_wheel_clicks = args.results_scroll_wheel_clicks * (scroll_attempt + 1)
            wheel_clicks = _clamp_scroll_wheel_clicks(requested_wheel_clicks)
            if scroll_attempt < 2:
                scroll_response = _scroll_results_list(args.base_url, timeout=args.timeout, wheel_clicks=wheel_clicks)
                scroll_scope = "results_list"
            else:
                scroll_response = _scroll_results_page(args.base_url, timeout=args.timeout, wheel_clicks=wheel_clicks)
                scroll_scope = "page"
            cards_payload = run("extract_cards").get("cards_payload") or {}
            visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
            current_fingerprint = _cards_fingerprint(visible_cards)
            changed = bool(current_fingerprint and current_fingerprint != previous_fingerprint)
            result_scrolls.append(
                {
                    "scroll_round": scroll_round,
                    "attempt": scroll_attempt,
                    "scope": scroll_scope,
                    "wheel_clicks": wheel_clicks,
                    "requested_wheel_clicks": requested_wheel_clicks,
                    "wheel_clicks_clamped": wheel_clicks != requested_wheel_clicks,
                    "success": scroll_response.get("success") is True,
                    "scroll_dispatch_success": scroll_response.get("success") is True,
                    "scroll_effect_success": changed,
                    "message": scroll_response.get("message"),
                    "card_fingerprint_changed": changed,
                }
            )
            if changed:
                break
        if not visible_exhausted and scroll_round >= args.max_result_scrolls:
            break
        if scroll_round >= args.max_result_scrolls:
            break
    if not application_started:
        return _write_speed_demo_result(
            run_dir,
            started=started,
            args=args,
            steps=steps,
            job_attempts=job_attempts,
            result_scrolls=result_scrolls,
            status="needs_work",
            stop_reason="no_eligible_station_internal_apply_entry",
        )
    return _finish_application_flow(
        run_dir=run_dir,
        started=started,
        args=args,
        run=run,
        budget_exhausted=budget_exhausted,
        steps=steps,
        job_attempts=job_attempts,
        result_scrolls=result_scrolls,
        initial_flow_state=apply_state,
        continuous_session=continuous_session,
        memory_store=memory_store,
        cp14_preflight_report_path=(preflight or {}).get("report_path"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a timed SEEK demo path using the existing debug step runner.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--url", default=DEFAULT_SEARCH_URL)
    parser.add_argument("--job-index", type=int, default=0)
    parser.add_argument("--max-jobs", type=int, default=5)
    parser.add_argument("--allow-maybe-apply", action="store_true")
    parser.add_argument(
        "--agent-suitability-review",
        default=None,
        help="Optional full-JD Agent review JSON passed to the match step.",
    )
    parser.add_argument("--visible-jobs-per-page", type=int, default=4)
    parser.add_argument("--max-result-scrolls", type=int, default=3)
    parser.add_argument("--results-scroll-wheel-clicks", type=int, default=9)
    parser.add_argument("--window-width", type=int, default=2560)
    parser.add_argument("--window-height", type=int, default=1400)
    parser.add_argument("--wheel-clicks", type=int, default=9)
    parser.add_argument("--batch-max-captures", type=int, default=3)
    parser.add_argument("--batch-stop-after-no-new-content", type=int, default=2)
    parser.add_argument("--post-apply-capture-wait-seconds", type=float, default=1.0)
    parser.add_argument("--max-application-steps", type=int, default=6)
    parser.add_argument("--max-safe-fields-to-fill", type=int, default=5)
    parser.add_argument(
        "--read-only-inventory",
        action="store_true",
        help="After entering Quick Apply, read one form inventory and answer policy, then stop without filling or continuing.",
    )
    parser.add_argument(
        "--cp14-live-uat",
        action="store_true",
        help="Require a fail-closed runtime preflight immediately before the approved Quick Apply entry click.",
    )
    parser.add_argument(
        "--approve-live-safe-fill",
        action="store_true",
        help="Explicitly approve the live safe-fill branch. Omit this flag to fail closed before any form fill attempt.",
    )
    parser.add_argument(
        "--approved-live-field-id",
        default=None,
        help="Stable ordinary-field ID explicitly approved for the single CP15A live fill.",
    )
    parser.add_argument(
        "--prepare-live-safe-fill",
        action="store_true",
        help="Build one redacted single-field approval preflight from a live read-only inventory, then stop.",
    )
    parser.add_argument(
        "--prepare-live-safe-fill-field-id",
        default=None,
        help="Candidate ordinary-field ID to project into the approval preflight; this is not authorization.",
    )
    parser.add_argument(
        "--approved-live-fill-preflight",
        type=Path,
        default=None,
        help="Reviewed seek_live_safe_fill_preflight_v1 file bound to the explicit field approval.",
    )
    parser.add_argument(
        "--approved-live-fill-preflight-sha256",
        default=None,
        help="SHA-256 of the exact reviewed preflight file; mismatch fails closed before live fill.",
    )
    parser.add_argument("--time-budget-ms", type=float, default=300000.0)
    parser.add_argument("--close-old-windows", action="store_true")
    parser.add_argument(
        "--continuous-session",
        action="store_true",
        help="Persist SEEK interface transitions and pause before using an unreviewed Quick Apply surface.",
    )
    parser.add_argument(
        "--resume-continuous-session",
        action="store_true",
        help="Resume the same run directory after the pending interface memory has been reviewed and published.",
    )
    parser.add_argument(
        "--approve-quick-apply-entry",
        action="store_true",
        help="Record explicit approval to enter a matching SEEK-hosted Quick Apply flow.",
    )
    parser.add_argument(
        "--disable-learned-fast-mode",
        action="store_true",
        help="Compatibility flag. Local keyword pruning is disabled; Agent always reads full job detail.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        result = run_speed_demo(args)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"success": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
