from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _post_json(base_url: str, endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{endpoint}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{endpoint} returned HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{endpoint} request failed: {exc}") from exc


def _result_payload(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        return data["result"]
    if isinstance(data, dict):
        return data
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def _sha256(path_value: Any) -> str | None:
    if not isinstance(path_value, str):
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _step_ms(result: dict[str, Any], name: str) -> float | None:
    timings = result.get("timings")
    if not isinstance(timings, dict):
        return None
    steps = timings.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if isinstance(step, dict) and step.get("name") == name:
            value = step.get("elapsed_ms")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _summary(response: dict[str, Any]) -> dict[str, Any]:
    result = _result_payload(response)
    plan = result.get("recognition_plan") if isinstance(result.get("recognition_plan"), dict) else {}
    plan_path = plan.get("execution_path") if isinstance(plan.get("execution_path"), dict) else {}
    execution_path = result.get("execution_path") if isinstance(result.get("execution_path"), dict) else {}
    decision = result.get("pre_click_decision") if isinstance(result.get("pre_click_decision"), dict) else {}
    local_validation = (
        result.get("local_target_validation")
        if isinstance(result.get("local_target_validation"), dict)
        else {}
    )
    live_capture = result.get("live_capture") if isinstance(result.get("live_capture"), dict) else {}
    freshness_decision = (
        result.get("candidate_freshness_decision")
        if isinstance(result.get("candidate_freshness_decision"), dict)
        else plan.get("candidate_freshness_decision")
        if isinstance(plan.get("candidate_freshness_decision"), dict)
        else {}
    )
    candidate_freshness = (
        freshness_decision.get("candidate_freshness")
        if isinstance(freshness_decision.get("candidate_freshness"), dict)
        else {}
    )
    image_path = live_capture.get("image_path") or result.get("image_path")
    selected_candidate = None
    selected_id = decision.get("selected_candidate_id")
    for candidate_decision in decision.get("candidate_decisions") or []:
        if isinstance(candidate_decision, dict) and candidate_decision.get("candidate_id") == selected_id:
            selected_candidate = candidate_decision
            break
    resolved = (
        selected_candidate.get("resolved_click_point")
        if isinstance(selected_candidate, dict)
        and isinstance(selected_candidate.get("resolved_click_point"), dict)
        else {}
    )
    timings = result.get("timings") if isinstance(result.get("timings"), dict) else {}
    return {
        "success": response.get("success"),
        "status": (result.get("agent_step_result") or {}).get("status")
        if isinstance(result.get("agent_step_result"), dict)
        else None,
        "image_path": image_path,
        "screenshot_sha256": _sha256(image_path),
        "selected_candidate_id": selected_id,
        "selected_bbox": resolved.get("bbox"),
        "selected_click_point": result.get("selected_click_point"),
        "pre_click_allowed": decision.get("allowed"),
        "local_target_validation_allowed": local_validation.get("allowed"),
        "local_target_validation_reason": local_validation.get("reason"),
        "vision_model_used": execution_path.get("vision_model_used"),
        "coordinate_source": plan_path.get("coordinate_source") or execution_path.get("coordinate_source"),
        "selection_source": plan_path.get("selection_source") or execution_path.get("selection_source"),
        "fast_grounding_requested": plan_path.get("operational_memory_fast_grounding_requested"),
        "fast_grounding_used": plan_path.get("operational_memory_fast_grounding_used"),
        "fast_grounding_reason": plan_path.get("operational_memory_fast_grounding_reason"),
        "current_uia_unique_match_count": plan_path.get("current_uia_unique_match_count"),
        "candidate_freshness_allowed": freshness_decision.get("allowed"),
        "candidate_freshness_candidate_id": freshness_decision.get("candidate_id"),
        "candidate_freshness_capture_id": candidate_freshness.get("capture_id"),
        "candidate_freshness_source": candidate_freshness.get("source"),
        "candidate_freshness": candidate_freshness.get("freshness"),
        "total_ms": timings.get("total_ms"),
        "surface_validation_ms": _step_ms(result, "validate_operational_memory_surface"),
        "recognition_plan_ms": _step_ms(result, "recognition_plan"),
        "action_trace_path": result.get("trace_path"),
        "recognition_plan_trace_path": result.get("recognition_plan_trace_path") or plan.get("trace_path"),
        "overlay_path": (
            (result.get("recognition_plan_overlay") or {}).get("output_path")
            or (result.get("recognition_plan_overlay") or {}).get("overlay_path")
            or (result.get("recognition_plan_overlay") or {}).get("image_path")
        )
        if isinstance(result.get("recognition_plan_overlay"), dict)
        else None,
        "action_executed": execution_path.get("action_executed"),
        "dry_run": execution_path.get("dry_run"),
    }


def evaluate_ab_expectation(
    *,
    baseline: dict[str, Any],
    fast: dict[str, Any],
    expected_fast_path: str,
) -> dict[str, Any]:
    if expected_fast_path not in {"used", "fallback"}:
        raise ValueError(f"Unsupported fast-path expectation: {expected_fast_path}")

    checks = {
        "baseline_gate_allowed": baseline.get("pre_click_allowed") is True,
        "fast_gate_allowed": fast.get("pre_click_allowed") is True,
        "baseline_dry_run": baseline.get("dry_run") is True,
        "fast_dry_run": fast.get("dry_run") is True,
        "baseline_no_action": baseline.get("action_executed") is False,
        "fast_no_action": fast.get("action_executed") is False,
        "current_candidate_freshness_allowed": fast.get("candidate_freshness_allowed") is True,
        "current_capture_freshness": fast.get("candidate_freshness_source")
        in {"current_uia_unique_match_v1", "current_uia_vista_grounded_v1"},
    }
    if expected_fast_path == "used":
        checks.update(
            {
                "fast_path_used": fast.get("fast_grounding_used") is True,
                "single_current_uia_match": fast.get("current_uia_unique_match_count") == 1,
                "vista_not_used": fast.get("vision_model_used") is False,
                "unique_match_freshness": fast.get("candidate_freshness_source")
                == "current_uia_unique_match_v1",
            }
        )
    else:
        match_count = fast.get("current_uia_unique_match_count")
        checks.update(
            {
                "fast_path_not_used": fast.get("fast_grounding_used") is False,
                "ambiguity_reported": fast.get("fast_grounding_reason")
                == "current_uia_match_not_unique",
                "multiple_current_uia_matches": isinstance(match_count, int) and match_count >= 2,
                "vista_fallback_used": fast.get("vision_model_used") is True,
                "vista_current_candidate_freshness": fast.get("candidate_freshness_source")
                == "current_uia_vista_grounded_v1",
            }
        )
    return {
        "expectation": expected_fast_path,
        "passed": all(checks.values()),
        "checks": checks,
    }


def _run_variant(
    *,
    base_url: str,
    payload: dict[str, Any],
    fast: bool,
    timeout: float,
) -> dict[str, Any]:
    request = json.loads(json.dumps(payload, ensure_ascii=False))
    if fast:
        metadata = request.setdefault("metadata", {})
        metadata["operational_memory_fast_grounding"] = {
            "enabled": True,
            "mode": "current_uia_unique_match_v1",
        }
    started = time.perf_counter()
    response = _post_json(base_url, "/action/execute_recognition_plan", request, timeout)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "request": request,
        "http_elapsed_ms": elapsed_ms,
        "response": response,
        "summary": _summary(response),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Real-screenshot dry-run A/B for operational-memory grounding.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--window-handle", type=int, required=True)
    parser.add_argument("--case-id", required=True)
    goal_group = parser.add_mutually_exclusive_group(required=True)
    goal_group.add_argument("--goal")
    goal_group.add_argument(
        "--goal-unicode-escaped",
        help="ASCII-only JSON-style Unicode escapes for a goal containing non-ASCII text.",
    )
    parser.add_argument("--interface-memory-id", required=True)
    parser.add_argument("--interface-memory-action-id", required=True)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--expected-fast-path",
        choices=("used", "fallback"),
        default="used",
        help="Expected result for the enabled current-UIA fast-grounding variant.",
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    bind_response = _post_json(
        args.base_url,
        "/session/bind_window",
        {"handle": args.window_handle},
        args.timeout,
    )
    if not bind_response.get("success"):
        raise RuntimeError(f"Window binding failed: {bind_response}")

    goal = args.goal
    if goal is None:
        goal = json.loads(f'"{args.goal_unicode_escaped}"')

    payload = {
        "goal": goal,
        "interface_memory_id": args.interface_memory_id,
        "interface_memory_action_id": args.interface_memory_action_id,
        "task": "click_target",
        "app_name": args.app_name,
        "provider_mode": "local_grounding",
        "agent_mode": "execute",
        "write_policy": {"path_graph": False, "element_memory": True, "trace": True},
        "metadata": {"runtime_validation": "operational_memory_fast_grounding_real_ab_v1"},
        "top_k": 5,
        "capture_live": True,
        "enable_post_click_verification": True,
        "max_execution_attempts": 2,
        "dry_run": True,
    }
    baseline = _run_variant(
        base_url=args.base_url,
        payload=payload,
        fast=False,
        timeout=args.timeout,
    )
    fast = _run_variant(
        base_url=args.base_url,
        payload=payload,
        fast=True,
        timeout=args.timeout,
    )
    evaluation = evaluate_ab_expectation(
        baseline=baseline["summary"],
        fast=fast["summary"],
        expected_fast_path=args.expected_fast_path,
    )
    report = {
        "contract_version": "operational_memory_fast_grounding_real_ab_v1",
        "case_id": args.case_id,
        "real_screenshot_test": True,
        "dry_run_only": True,
        "real_clicks": 0,
        "interface_memory_id": args.interface_memory_id,
        "interface_memory_action_id": args.interface_memory_action_id,
        "bound_window": bind_response.get("data"),
        "expected_fast_path": args.expected_fast_path,
        "evaluation": evaluation,
        "baseline": baseline,
        "fast_path": fast,
    }
    report_path = args.out / f"{args.case_id}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "contract_version": report["contract_version"],
        "case_id": args.case_id,
        "report_path": str(report_path.resolve()),
        "real_screenshot_test": True,
        "dry_run_only": True,
        "expected_fast_path": args.expected_fast_path,
        "evaluation": evaluation,
        "baseline": baseline["summary"],
        "fast_path": fast["summary"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0 if evaluation["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
