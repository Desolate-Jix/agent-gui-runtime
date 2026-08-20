from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_APPLICATION_ARTIFACT = Path("artifacts/seek/learned_seek_application_flow_plexure_20260620.json")


def read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def check(check_id: str, passed: bool, message: str, evidence: Any = None) -> dict[str, Any]:
    item: dict[str, Any] = {"check_id": check_id, "status": "pass" if passed else "fail", "message": message}
    if evidence is not None:
        item["evidence"] = evidence
    return item


def build_seek_application_flow_replay_report(artifact: dict[str, Any]) -> dict[str, Any]:
    source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
    safety = artifact.get("safety_policy") if isinstance(artifact.get("safety_policy"), dict) else {}
    field_policy = artifact.get("field_fill_policy") if isinstance(artifact.get("field_fill_policy"), dict) else {}
    filled_summary = artifact.get("filled_content_summary") if isinstance(artifact.get("filled_content_summary"), dict) else {}
    states = {str(item.get("state_id") or ""): item for item in artifact.get("states") or [] if isinstance(item, dict)}
    transitions = [item for item in artifact.get("transitions") or [] if isinstance(item, dict)]
    transition_ids = [str(item.get("transition_id") or "") for item in transitions]
    required_transitions = [
        "seek_apply:keep_default_documents",
        "seek_apply:fill_cover_letter",
        "seek_apply:answer_questions",
        "seek_apply:skip_profile_update",
        "seek_apply:block_final_submit",
    ]
    timeline = [_timeline_entry(transition) for transition in transitions]
    checks = [
        check("contract", artifact.get("contract_version") == "seek_application_flow_artifact_v1", "artifact contract is seek_application_flow_artifact_v1", artifact.get("contract_version")),
        check("source_record_exists", bool(source.get("application_fill_record_path")), "source application_fill_record path is present", source.get("application_fill_record_path")),
        check("source_audit_exists", bool(source.get("final_review_audit_path")), "source final_review_audit path is present", source.get("final_review_audit_path")),
        check("source_review_reached", source.get("reached_review_and_submit") is True, "source run reached Review and submit", source.get("reached_review_and_submit")),
        check("required_states", _required_states_present(states), "required application states are present", sorted(states)),
        check("required_transitions", all(item in transition_ids for item in required_transitions), "required application transitions are present", transition_ids),
        check("timeline_shape", len(timeline) == 5 and timeline[-1]["action"] == "stop_before_final_submit", "replay timeline stops at final submit boundary", [item["action"] for item in timeline]),
        check("safe_fill_required", field_policy.get("safe_fill_required_for_future_replay") is True, "future replay requires safe-fill verification", field_policy.get("safe_fill_required_for_future_replay")),
        check("focus_verification_required", field_policy.get("field_focus_required") is True, "field focus verification is required", field_policy.get("field_focus_required")),
        check("post_fill_required", field_policy.get("post_fill_value_verification_required") is True, "post-fill value verification is required", field_policy.get("post_fill_value_verification_required")),
        check("direct_type_text_not_authority", field_policy.get("direct_type_text_is_milestone_evidence_only") is True, "direct type_text is milestone evidence only", field_policy.get("direct_type_text_is_milestone_evidence_only")),
        check("final_submit_forbidden", safety.get("final_submit_forbidden") is True, "final submit remains forbidden", safety.get("final_submit_forbidden")),
        check("artifact_not_authorization", safety.get("artifact_is_authorization") is False, "artifact is not authorization", safety.get("artifact_is_authorization")),
        check("profile_mutation_forbidden", safety.get("seek_profile_mutation_policy") == "forbidden_without_explicit_user_approval", "SEEK profile mutation remains forbidden", safety.get("seek_profile_mutation_policy")),
        check("zero_submit_counters", int(safety.get("submit_clicks") or 0) == 0 and int(safety.get("final_submissions") or 0) == 0, "source counters show no submit", {"submit_clicks": safety.get("submit_clicks"), "final_submissions": safety.get("final_submissions")}),
    ]
    blockers = [item for item in checks if item["status"] != "pass"]
    return {
        "contract_version": "seek_application_flow_replay_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not blockers else "fail",
        "mode": "dry_run_replay_plan",
        "artifact_id": artifact.get("artifact_id"),
        "source": source,
        "summary": {
            "timeline_steps": len(timeline),
            "can_run_live_strict_replay": not blockers,
            "safe_fill_required": field_policy.get("safe_fill_required_for_future_replay") is True,
            "employer_question_count": int(filled_summary.get("employer_question_count") or 0),
            "field_focus_required": field_policy.get("field_focus_required") is True,
            "post_fill_value_verification_required": field_policy.get("post_fill_value_verification_required") is True,
            "artifact_is_authorization": safety.get("artifact_is_authorization"),
            "final_submit_forbidden": safety.get("final_submit_forbidden"),
            "write_actions_clicked": 0,
            "submit_clicks": int(safety.get("submit_clicks") or 0),
            "final_submissions": int(safety.get("final_submissions") or 0),
        },
        "timeline": timeline,
        "checks": checks,
        "blocking_failures": blockers,
    }


def _required_states_present(states: dict[str, Any]) -> bool:
    return {
        "seek_apply:choose_documents",
        "seek_apply:cover_letter",
        "seek_apply:answer_employer_questions",
        "seek_apply:update_seek_profile",
        "seek_apply:review_and_submit",
        "seek_apply:final_submit_blocked",
        "seek_apply:third_party_ats_deferred",
        "seek_apply:blocked_upload_or_login",
    } <= set(states)


def _timeline_entry(transition: dict[str, Any]) -> dict[str, Any]:
    action = str(transition.get("action_template_id") or "")
    low_level = _low_level_action(action)
    return {
        "transition_id": transition.get("transition_id"),
        "from_state": transition.get("from_state"),
        "to_state": transition.get("to_state"),
        "action": action,
        "low_level_action_type": low_level,
        "requires_current_observe": True,
        "requires_screenshot_before": True,
        "requires_screenshot_after": action != "stop_before_final_submit",
        "requires_safe_fill_focus": action in {"fill_cover_letter_and_continue", "answer_employer_questions_and_continue"},
        "requires_post_fill_verification": action in {"fill_cover_letter_and_continue", "answer_employer_questions_and_continue"},
        "allows_profile_mutation": False,
        "allows_final_submit": False,
    }


def _low_level_action(action: str) -> str:
    if action in {"fill_cover_letter_and_continue", "answer_employer_questions_and_continue"}:
        return "type_text_and_gated_continue"
    if action in {"continue_keep_default_resume", "continue_without_persistent_profile_update"}:
        return "gated_click"
    if action == "stop_before_final_submit":
        return "guard"
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a dry-run replay plan report for a learned SEEK application flow artifact.")
    parser.add_argument("--artifact", type=Path, default=DEFAULT_APPLICATION_ARTIFACT)
    parser.add_argument("--out", type=Path, default=Path("logs/smoke/seek_application_flow_replay_20260620.json"))
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)

    report = build_seek_application_flow_replay_report(read_json(args.artifact))
    write_json(args.out, report)
    print(
        json.dumps(
            {
                "success": report["status"] == "pass",
                "status": report["status"],
                "summary": report["summary"],
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    if args.fail_on_error and report["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
