from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from app.core.replay_case_store import replay_case_store
from app.core.transition_memory import transition_memory
from app.schemas.action_target import ActionTarget
from app.schemas.replay_case import ReplayCase
from app.schemas.state import AppState
from app.schemas.transition import TransitionRecord
from app.schemas.validator_profile import ValidatorProfile


RunActionCallable = Callable[[], dict[str, Any]]
CaptureCallable = Callable[[str], Optional[str]]
BucketCallable = Callable[[], str]


def run_known_action(
    *,
    app_name: str,
    state_before: Optional[AppState],
    action_target: Optional[ActionTarget],
    validator_profile: Optional[ValidatorProfile],
    execute_action: RunActionCallable,
    capture_state_image: CaptureCallable,
    get_window_bucket: BucketCallable,
) -> dict[str, Any]:
    before_image_path = capture_state_image("before-state")
    result = execute_action()
    after_image_path = capture_state_image("after-state")

    recognition_before = {
        "matched": state_before is not None,
        "state_id": state_before.state_id if state_before else None,
        "confidence": 1.0 if state_before else 0.0,
        "reason": {"source": "state_hint" if state_before else "missing"},
        "image_path": before_image_path,
        "window_bucket": get_window_bucket(),
    }
    recognition_after = {
        "matched": bool(result.get("success")),
        "state_id": state_before.state_id if state_before else None,
        "confidence": 0.85 if result.get("success") else 0.25,
        "reason": {"source": "action_result"},
        "image_path": after_image_path,
        "window_bucket": get_window_bucket(),
    }

    success_type = "miss"
    confidence = 0.2
    if result.get("success") and result.get("strict_success"):
        success_type = "strict"
        confidence = 0.95
    elif result.get("success") and result.get("weak_success"):
        success_type = "weak"
        confidence = 0.7

    replay_case = ReplayCase(
        case_id=f"replay-{uuid4().hex}",
        app_name=app_name,
        state_before_id=state_before.state_id if state_before else None,
        action_id=action_target.action_id if action_target else "unknown_action",
        click_point=result.get("selected_point") or result.get("successful_point") or {},
        artifacts_before={"image_path": before_image_path, "state_recognition": recognition_before},
        artifacts_after={"image_path": after_image_path, "state_recognition": recognition_after},
        validator_result={
            "validator_profile_id": validator_profile.validator_profile_id if validator_profile else None,
            "strict_success": result.get("strict_success"),
            "weak_success": result.get("weak_success"),
            "target_counter_before": result.get("target_counter_before"),
            "target_counter_after": result.get("target_counter_after"),
            "counter_changed": result.get("counter_changed"),
            "strict_score": result.get("strict_score"),
            "roi_diff_score": result.get("roi_diff_score"),
        },
        state_after_id=recognition_after.get("state_id"),
        memory_updates={"memory_path": result.get("memory_path"), "case_path": result.get("case_path")},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    replay_case_path = replay_case_store.save(replay_case)

    transition = TransitionRecord(
        transition_id=f"transition-{uuid4().hex}",
        from_state_id=state_before.state_id if state_before else "unknown",
        action_id=action_target.action_id if action_target else "unknown_action",
        to_state_id=recognition_after.get("state_id"),
        success_type=success_type,
        confidence=confidence,
        evidence={
            "state_recognition_before": recognition_before,
            "state_recognition_after": recognition_after,
            "validator_result": replay_case.validator_result,
        },
        case_path=replay_case_path,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    transition_path = transition_memory.save(transition)

    result["state_recognition_before"] = recognition_before
    result["state_recognition_after"] = recognition_after
    result["state_before_id"] = state_before.state_id if state_before else None
    result["action_target_id"] = action_target.action_id if action_target else None
    result["validator_profile_id"] = validator_profile.validator_profile_id if validator_profile else None
    result["replay_case_path"] = replay_case_path
    result["transition_path"] = transition_path
    result["fallback_available"] = True
    return result
