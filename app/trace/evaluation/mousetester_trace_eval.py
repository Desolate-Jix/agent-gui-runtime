from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MouseTesterEvalCase:
    case_id: str
    trace_path: str
    expected_goal: str | None = None
    expected_label_contains: str | None = None
    expected_pre_click_allowed: bool | None = None
    expected_action_executed: bool | None = None
    expected_success: bool | None = None
    expected_semantic_verified: bool | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MouseTesterEvalCase":
        return cls(
            case_id=str(payload["case_id"]),
            trace_path=str(payload["trace_path"]),
            expected_goal=payload.get("expected_goal"),
            expected_label_contains=payload.get("expected_label_contains"),
            expected_pre_click_allowed=payload.get("expected_pre_click_allowed"),
            expected_action_executed=payload.get("expected_action_executed"),
            expected_success=payload.get("expected_success"),
            expected_semantic_verified=payload.get("expected_semantic_verified"),
        )


def load_cases(path: str | Path) -> list[MouseTesterEvalCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    return [MouseTesterEvalCase.from_dict(item) for item in raw_cases]


def evaluate_cases(cases: list[MouseTesterEvalCase], *, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    results = [evaluate_case(case, root=root_path) for case in cases]
    present = [item for item in results if not item.get("missing")]
    return {
        "contract_version": "mousetester_trace_eval_v1",
        "summary": _summarize(results),
        "results": results,
        "root": str(root_path.resolve()),
    }


def evaluate_case(case: MouseTesterEvalCase, *, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    trace_path = Path(case.trace_path)
    if not trace_path.is_absolute():
        trace_path = root_path / trace_path
    base = {
        "case_id": case.case_id,
        "trace_path": str(trace_path),
        "expectations": {
            "expected_goal": case.expected_goal,
            "expected_label_contains": case.expected_label_contains,
            "expected_pre_click_allowed": case.expected_pre_click_allowed,
            "expected_action_executed": case.expected_action_executed,
            "expected_success": case.expected_success,
            "expected_semantic_verified": case.expected_semantic_verified,
        },
    }
    if not trace_path.exists():
        return {**base, "missing": True, "passed": False, "checks": {"trace_exists": False}}

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    extracted = _extract_trace_facts(payload)
    checks = _evaluate_expectations(case, payload, extracted)
    return {
        **base,
        "missing": False,
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "facts": extracted,
    }


def _extract_trace_facts(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") or {}
    action_result = "recognition_plan" in result
    plan = result.get("recognition_plan") if action_result else result
    plan = plan or {}
    recommended = plan.get("recommended_target") or {}
    pre_click = plan.get("pre_click_decision") or {}
    semantic = result.get("semantic_post_click_verification") or {}
    semantic_replayed = False
    if action_result and semantic.get("verified") is None:
        replayed = _try_replay_semantic_verification(payload, result, plan)
        if replayed is not None:
            semantic = replayed
            semantic_replayed = True
    execution_path = result.get("execution_path") or plan.get("execution_path") or {}
    attempts = result.get("attempts") or []
    return {
        "trace_success": bool(payload.get("success")),
        "trace_kind": "action_execution" if action_result else "recognition_plan",
        "goal": plan.get("goal"),
        "recommended_label": recommended.get("label"),
        "recommended_score": recommended.get("score"),
        "pre_click_allowed": pre_click.get("allowed"),
        "pre_click_reasons": pre_click.get("reasons") or [],
        "action_executed": execution_path.get("action_executed"),
        "semantic_verified": semantic.get("verified"),
        "semantic_applicable": semantic.get("applicable"),
        "semantic_replayed": semantic_replayed,
        "attempt_count": len(attempts),
        "retry_count": execution_path.get("retry_count", max(0, len(attempts) - 1)),
        "selected_click_point": result.get("selected_click_point") or pre_click.get("selected_click_point"),
        "recognition_plan_trace_path": result.get("recognition_plan_trace_path") or plan.get("trace_path"),
    }


def _try_replay_semantic_verification(
    payload: dict[str, Any],
    result: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any] | None:
    generic = result.get("post_click_verification") or {}
    before_path = Path(str(((generic.get("before") or {}).get("image_path") or "")))
    after_path = Path(str(((generic.get("after") or {}).get("image_path") or "")))
    if not before_path.exists() or not after_path.exists():
        return None
    try:
        from app.api.models.request import ExecuteRecognitionPlanRequest
        from app.operation.mousetester import verify_mouse_tester_post_click_semantics

        request_payload = payload.get("request") or {}
        request = ExecuteRecognitionPlanRequest(
            goal=str(request_payload.get("goal") or plan.get("goal") or ""),
            app_name=request_payload.get("app_name") or "mousetesterweb",
            state_hint=request_payload.get("state_hint"),
        )
        replayed = verify_mouse_tester_post_click_semantics(
            request=request,
            plan=plan,
            generic_verification=generic,
        )
        replayed["replayed_from_trace"] = True
        return replayed
    except Exception as exc:
        return {
            "applicable": True,
            "verified": False,
            "replayed_from_trace": True,
            "replay_error": str(exc),
        }


def _evaluate_expectations(
    case: MouseTesterEvalCase,
    payload: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {
        "trace_exists": _check(True, True),
    }
    if case.expected_success is not None:
        checks["trace_success"] = _check(bool(payload.get("success")), case.expected_success)
    if case.expected_goal is not None:
        checks["goal"] = _check(_normalize_text(facts.get("goal")), _normalize_text(case.expected_goal))
    if case.expected_label_contains is not None:
        label = _normalize_text(facts.get("recommended_label"))
        expected = _normalize_text(case.expected_label_contains)
        checks["top1_label_contains"] = {
            "passed": bool(expected and expected in label),
            "actual": facts.get("recommended_label"),
            "expected": case.expected_label_contains,
        }
    if case.expected_pre_click_allowed is not None:
        checks["pre_click_allowed"] = _check(facts.get("pre_click_allowed"), case.expected_pre_click_allowed)
    if case.expected_action_executed is not None:
        checks["action_executed"] = _check(facts.get("action_executed"), case.expected_action_executed)
    if case.expected_semantic_verified is not None:
        checks["semantic_verified"] = _check(facts.get("semantic_verified"), case.expected_semantic_verified)
    return checks


def _check(actual: Any, expected: Any) -> dict[str, Any]:
    return {"passed": actual == expected, "actual": actual, "expected": expected}


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    present = [item for item in results if not item.get("missing")]
    return {
        "case_count": len(results),
        "present_case_count": len(present),
        "missing_case_count": len(results) - len(present),
        "passed_case_count": len([item for item in present if item.get("passed")]),
        "pass_rate": _rate(len([item for item in present if item.get("passed")]), len(present)),
        "top1_label_pass_rate": _check_rate(present, "top1_label_contains"),
        "pre_click_pass_rate": _check_rate(present, "pre_click_allowed"),
        "action_execution_pass_rate": _check_rate(present, "action_executed"),
        "semantic_verification_pass_rate": _check_rate(present, "semantic_verified"),
    }


def _check_rate(results: list[dict[str, Any]], check_name: str) -> float | None:
    applicable = [item for item in results if check_name in (item.get("checks") or {})]
    if not applicable:
        return None
    passed = len([item for item in applicable if item["checks"][check_name]["passed"]])
    return _rate(passed, len(applicable))


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _normalize_text(value: Any) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())
