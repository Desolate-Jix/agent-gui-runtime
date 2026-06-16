from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("logs/smoke/execute_smoke_results.jsonl")


class SmokeRunnerError(RuntimeError):
    pass


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_cases(*, case_path: Path | None = None, cases_dir: Path | None = None) -> list[dict[str, Any]]:
    if bool(case_path) == bool(cases_dir):
        raise SmokeRunnerError("Provide exactly one of --case or --cases")
    paths: list[Path]
    if case_path is not None:
        paths = [case_path]
    else:
        assert cases_dir is not None
        paths = sorted([item for item in cases_dir.iterdir() if item.suffix.lower() == ".json"])
    cases: list[dict[str, Any]] = []
    for path in paths:
        payload = _read_json(path)
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict) and isinstance(payload.get("cases"), list):
            items = payload["cases"]
        elif isinstance(payload, dict):
            items = [payload]
        else:
            raise SmokeRunnerError(f"Unsupported case payload in {path}")
        for item in items:
            if not isinstance(item, dict):
                raise SmokeRunnerError(f"Case item in {path} is not an object")
            item = dict(item)
            item.setdefault("_case_path", str(path))
            cases.append(item)
    return cases


def _post_json(base_url: str, endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{endpoint}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SmokeRunnerError(f"{endpoint} returned HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise SmokeRunnerError(f"{endpoint} request failed: {exc}") from exc
    return json.loads(raw)


def _result_payload(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        return data["result"]
    return data if isinstance(data, dict) else {}


def _first_recursive_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _first_recursive_value(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_recursive_value(child, key)
            if found is not None:
                return found
    return None


def _agent_step(result: dict[str, Any]) -> dict[str, Any]:
    step = result.get("agent_step_result")
    return step if isinstance(step, dict) else {}


def _guidance(result: dict[str, Any]) -> dict[str, Any]:
    guidance = result.get("agent_execution_guidance")
    return guidance if isinstance(guidance, dict) else {}


def _post_click_success(result: dict[str, Any], step: dict[str, Any]) -> bool | None:
    post_click = step.get("post_click") if isinstance(step.get("post_click"), dict) else {}
    for source in (post_click, result.get("post_click_verification"), result.get("verification_result")):
        if isinstance(source, dict):
            if isinstance(source.get("success"), bool):
                return source["success"]
            if isinstance(source.get("verified"), bool):
                return source["verified"]
    return None


def _extract_summary(response: dict[str, Any], *, latency_ms: float, dry_run: bool, goal: str) -> dict[str, Any]:
    result = _result_payload(response)
    step = _agent_step(result)
    evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
    pre_click = result.get("pre_click_decision") if isinstance(result.get("pre_click_decision"), dict) else {}
    overlay = evidence.get("coordinate_overlay_path")
    if not overlay and isinstance(result.get("recognition_plan_overlay"), dict):
        overlay = result["recognition_plan_overlay"].get("output_path")
    allowed = response.get("success") is True and (
        step.get("status") in {"dry_run_ready", "verified", "clicked", "success"}
        or pre_click.get("allowed") is True
        or bool(result.get("approved_plan_id"))
    )
    attempt_count = _first_recursive_value(result, "attempt_count")
    if not isinstance(attempt_count, int):
        attempt_count = None
    summary = {
        "dry_run": dry_run,
        "goal": step.get("goal") or result.get("goal") or goal,
        "allowed": bool(allowed),
        "status": step.get("status"),
        "attempt_count": attempt_count,
        "latency_ms": round(float(latency_ms), 3),
        "action_type": "click",
        "trace_path": result.get("trace_path") or evidence.get("action_trace_path"),
        "recognition_plan_trace_path": evidence.get("recognition_plan_trace_path") or result.get("recognition_plan_trace_path"),
        "coordinate_overlay_path": overlay,
        "approved_plan_id": step.get("approved_plan_id") or result.get("approved_plan_id"),
        "selected_click_point": step.get("selected_click_point") or result.get("selected_click_point"),
        "next_agent_action": step.get("next_agent_action") or _guidance(result).get("next_action"),
        "failure_reason": step.get("failure_reason") or result.get("failure_reason"),
        "post_click_verification": {
            "success": _post_click_success(result, step),
        },
        "raw_success": response.get("success"),
        "raw_message": response.get("message"),
        "raw_error": response.get("error"),
    }
    if dry_run:
        summary["dry_run_latency_ms"] = summary["latency_ms"]
    return summary


def _expected(case: dict[str, Any]) -> dict[str, Any]:
    expect = case.get("expect")
    return expect if isinstance(expect, dict) else {}


def _mode(case: dict[str, Any]) -> dict[str, Any]:
    mode = case.get("mode")
    return mode if isinstance(mode, dict) else {}


def _app(case: dict[str, Any]) -> dict[str, Any]:
    app = case.get("app")
    return app if isinstance(app, dict) else {}


def _request_overrides(case: dict[str, Any]) -> dict[str, Any]:
    request = case.get("request")
    return request if isinstance(request, dict) else {}


def _bind_if_requested(base_url: str, case: dict[str, Any], *, timeout: float) -> dict[str, Any] | None:
    app = _app(case)
    process_name = app.get("process_name")
    title = app.get("window_title_contains") or app.get("title")
    if not process_name and not title:
        return None
    return _post_json(
        base_url,
        "/session/bind_window",
        {"process_name": process_name, "title": title},
        timeout,
    )


def _open_if_requested(base_url: str, case: dict[str, Any], *, timeout: float) -> dict[str, Any] | None:
    app = _app(case)
    if not app.get("open_before"):
        return None
    payload: dict[str, Any] = {
        "app_id": app.get("app_id") or app.get("app_name"),
        "command": app.get("command"),
        "url": app.get("url"),
        "process_name": app.get("process_name"),
        "title": app.get("window_title_contains") or app.get("title"),
        "bind_after_open": app.get("bind_after_open", True),
        "wait_seconds": app.get("wait_seconds", 2.0),
    }
    return _post_json(
        base_url,
        "/apps/open",
        {key: value for key, value in payload.items() if value is not None},
        timeout,
    )


def _resize_if_requested(base_url: str, case: dict[str, Any], *, timeout: float) -> dict[str, Any] | None:
    app = _app(case)
    resize = app.get("resize_before")
    if not isinstance(resize, dict):
        return None
    payload = {
        "width": resize.get("width"),
        "height": resize.get("height"),
        "left": resize.get("left"),
        "top": resize.get("top"),
        "focus": resize.get("focus", True),
    }
    return _post_json(
        base_url,
        "/session/resize_bound_window",
        {key: value for key, value in payload.items() if value is not None},
        timeout,
    )


def _execute_body(case: dict[str, Any], *, dry_run: bool, approved_plan_id: str | None = None) -> dict[str, Any]:
    app = _app(case)
    overrides = _request_overrides(case)
    body: dict[str, Any] = {
        "agent_mode": "execute",
        "goal": case["goal"],
        "app_name": app.get("app_name"),
        "state_hint": case.get("state_hint"),
        "observe_trace_path": case.get("observe_trace_path"),
        "capture_live": True,
        "dry_run": dry_run,
        "enable_post_click_verification": True,
        "write_policy": {"path_graph": False, "element_memory": True, "trace": True},
    }
    body.update({key: value for key, value in overrides.items() if value is not None})
    if approved_plan_id:
        body["approved_plan_id"] = approved_plan_id
    return {key: value for key, value in body.items() if value is not None}


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _point_in_expected_rect(point: Any, rect: dict[str, Any]) -> tuple[bool, str | None]:
    if not isinstance(point, dict):
        return False, "selected_click_point_missing"
    x = _number(point.get("x"))
    y = _number(point.get("y"))
    if x is None or y is None:
        return False, "selected_click_point_invalid"

    min_x = _number(rect.get("min_x", rect.get("x_min")))
    max_x = _number(rect.get("max_x", rect.get("x_max")))
    min_y = _number(rect.get("min_y", rect.get("y_min")))
    max_y = _number(rect.get("max_y", rect.get("y_max")))
    missing = [name for name, value in (("min_x", min_x), ("max_x", max_x), ("min_y", min_y), ("max_y", max_y)) if value is None]
    if missing:
        return False, "point_in_rect_missing_" + "_".join(missing)
    if not (min_x <= x <= max_x and min_y <= y <= max_y):
        return False, f"point_outside_rect_x{x:.1f}_y{y:.1f}"
    return True, None


def _evaluate_result(case: dict[str, Any], summary: dict[str, Any], *, executed: bool) -> tuple[bool, list[str]]:
    expect = _expected(case)
    reasons: list[str] = []
    expected_allow = expect.get("allow")
    if isinstance(expected_allow, bool) and bool(summary.get("allowed")) != expected_allow:
        reasons.append(f"allowed_expected_{expected_allow}_got_{summary.get('allowed')}")
    max_attempt_count = expect.get("max_attempt_count")
    attempt_count = summary.get("attempt_count")
    if isinstance(max_attempt_count, int) and isinstance(attempt_count, int) and attempt_count > max_attempt_count:
        reasons.append(f"attempt_count_above_{max_attempt_count}")
    max_latency_ms = expect.get("max_latency_ms")
    decision_latency = summary.get("dry_run_latency_ms", summary.get("latency_ms"))
    if isinstance(max_latency_ms, (int, float)) and float(decision_latency or 0) > float(max_latency_ms):
        reasons.append(f"latency_above_{max_latency_ms}")
    action_type = expect.get("action_type")
    if action_type and summary.get("action_type") != action_type:
        reasons.append(f"action_type_expected_{action_type}_got_{summary.get('action_type')}")
    point_in_rect = expect.get("point_in_rect")
    if isinstance(point_in_rect, dict):
        ok, reason = _point_in_expected_rect(summary.get("selected_click_point"), point_in_rect)
        if not ok and reason:
            reasons.append(reason)
    post_click = expect.get("post_click") if isinstance(expect.get("post_click"), dict) else {}
    if executed and post_click.get("required") is True and summary.get("post_click_verification", {}).get("success") is not True:
        reasons.append("post_click_verification_not_successful")
    if not summary.get("raw_success"):
        reasons.append("api_response_not_successful")
    return not reasons, reasons


def run_case(
    case: dict[str, Any],
    *,
    base_url: str,
    execute: bool,
    timeout: float,
    repeat_index: int = 1,
    repeat_count: int = 1,
) -> dict[str, Any]:
    case_id = str(case.get("id") or Path(str(case.get("_case_path", "case"))).stem)
    if not case.get("goal"):
        raise SmokeRunnerError(f"Case {case_id} missing goal")
    mode = _mode(case)
    if execute and mode.get("destructive") is True:
        raise SmokeRunnerError(f"Case {case_id} is marked destructive; refusing --execute")

    open_response = _open_if_requested(base_url, case, timeout=timeout)
    if open_response is not None and open_response.get("success") is not True:
        return {
            "contract_version": "execute_smoke_result_v1",
            "case_id": case_id,
            "case_path": case.get("_case_path"),
            "repeat_index": repeat_index,
            "repeat_count": repeat_count,
            "dry_run": True,
            "executed": False,
            "open_success": False,
            "bind_success": False,
            "resize_success": None,
            "goal": str(case["goal"]),
            "allowed": False,
            "status": "open_failed",
            "attempt_count": None,
            "latency_ms": 0.0,
            "action_type": "click",
            "trace_path": None,
            "recognition_plan_trace_path": None,
            "coordinate_overlay_path": None,
            "approved_plan_id": None,
            "selected_click_point": None,
            "next_agent_action": "fix_app_open",
            "failure_reason": open_response.get("message") or "App open failed",
            "post_click_verification": {"success": None},
            "raw_success": open_response.get("success"),
            "raw_message": open_response.get("message"),
            "raw_error": open_response.get("error"),
            "pass": False,
            "fail_reasons": ["app_open_failed"],
        }

    bind_response = None if open_response is not None else _bind_if_requested(base_url, case, timeout=timeout)
    if bind_response is not None and bind_response.get("success") is not True:
        return {
            "contract_version": "execute_smoke_result_v1",
            "case_id": case_id,
            "case_path": case.get("_case_path"),
            "repeat_index": repeat_index,
            "repeat_count": repeat_count,
            "dry_run": True,
            "executed": False,
            "open_success": None,
            "bind_success": False,
            "resize_success": None,
            "goal": str(case["goal"]),
            "allowed": False,
            "status": "bind_failed",
            "attempt_count": None,
            "latency_ms": 0.0,
            "action_type": "click",
            "trace_path": None,
            "recognition_plan_trace_path": None,
            "coordinate_overlay_path": None,
            "approved_plan_id": None,
            "selected_click_point": None,
            "next_agent_action": "fix_window_binding",
            "failure_reason": bind_response.get("message") or "Window bind failed",
            "post_click_verification": {"success": None},
            "raw_success": bind_response.get("success"),
            "raw_message": bind_response.get("message"),
            "raw_error": bind_response.get("error"),
            "pass": False,
            "fail_reasons": ["bind_window_failed"],
        }
    resize_response = _resize_if_requested(base_url, case, timeout=timeout)
    if resize_response is not None and resize_response.get("success") is not True:
        return {
            "contract_version": "execute_smoke_result_v1",
            "case_id": case_id,
            "case_path": case.get("_case_path"),
            "repeat_index": repeat_index,
            "repeat_count": repeat_count,
            "dry_run": True,
            "executed": False,
            "open_success": None if open_response is None else bool(open_response.get("success")),
            "bind_success": None if bind_response is None else bool(bind_response.get("success")),
            "resize_success": False,
            "goal": str(case["goal"]),
            "allowed": False,
            "status": "resize_failed",
            "attempt_count": None,
            "latency_ms": 0.0,
            "action_type": "click",
            "trace_path": None,
            "recognition_plan_trace_path": None,
            "coordinate_overlay_path": None,
            "approved_plan_id": None,
            "selected_click_point": None,
            "next_agent_action": "fix_window_resize",
            "failure_reason": resize_response.get("message") or "Window resize failed",
            "post_click_verification": {"success": None},
            "raw_success": resize_response.get("success"),
            "raw_message": resize_response.get("message"),
            "raw_error": resize_response.get("error"),
            "pass": False,
            "fail_reasons": ["resize_window_failed"],
        }
    dry_body = _execute_body(case, dry_run=True)
    dry_started = time.perf_counter()
    dry_response = _post_json(base_url, "/action/execute_recognition_plan", dry_body, timeout)
    dry_latency = (time.perf_counter() - dry_started) * 1000.0
    dry_summary = _extract_summary(dry_response, latency_ms=dry_latency, dry_run=True, goal=str(case["goal"]))

    result_summary = dry_summary
    executed = False
    if execute:
        approved_plan_id = dry_summary.get("approved_plan_id")
        guidance = _guidance(_result_payload(dry_response))
        next_request = guidance.get("next_request") if isinstance(guidance.get("next_request"), dict) else {}
        real_body = next_request.get("body") if isinstance(next_request.get("body"), dict) else None
        if real_body is None:
            real_body = _execute_body(case, dry_run=False, approved_plan_id=str(approved_plan_id) if approved_plan_id else None)
        real_started = time.perf_counter()
        real_response = _post_json(base_url, "/action/execute_recognition_plan", real_body, timeout)
        real_latency = (time.perf_counter() - real_started) * 1000.0
        result_summary = _extract_summary(real_response, latency_ms=real_latency, dry_run=False, goal=str(case["goal"]))
        result_summary["dry_run_latency_ms"] = dry_summary["latency_ms"]
        result_summary["dry_run_trace_path"] = dry_summary.get("trace_path")
        result_summary["dry_run_recognition_plan_trace_path"] = dry_summary.get("recognition_plan_trace_path")
        result_summary["dry_run_coordinate_overlay_path"] = dry_summary.get("coordinate_overlay_path")
        result_summary["execute_latency_ms"] = result_summary["latency_ms"]
        executed = True

    passed, fail_reasons = _evaluate_result(case, result_summary, executed=executed)
    return {
        "contract_version": "execute_smoke_result_v1",
        "case_id": case_id,
        "case_path": case.get("_case_path"),
        "repeat_index": repeat_index,
        "repeat_count": repeat_count,
        "dry_run": not executed,
        "executed": executed,
        "open_success": None if open_response is None else bool(open_response.get("success")),
        "bind_success": None if bind_response is None else bool(bind_response.get("success")),
        "resize_success": None if resize_response is None else bool(resize_response.get("success")),
        **result_summary,
        "pass": passed,
        "fail_reasons": fail_reasons,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run Execute Mode smoke cases. Defaults to dry-run; --execute can click.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case", help="Path to a JSON case file.")
    group.add_argument("--cases", help="Directory containing JSON case files.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="JSONL output path.")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--repeat", type=int, default=1, help="Repeat the selected case set this many times.")
    parser.add_argument("--execute", action="store_true", help="Execute approved real clicks. Default is dry-run only.")
    args = parser.parse_args(argv)

    try:
        cases = load_cases(case_path=Path(args.case) if args.case else None, cases_dir=Path(args.cases) if args.cases else None)
        repeat = max(1, int(args.repeat))
        rows = [
            run_case(
                case,
                base_url=args.base_url,
                execute=bool(args.execute),
                timeout=float(args.timeout),
                repeat_index=index,
                repeat_count=repeat,
            )
            for index in range(1, repeat + 1)
            for case in cases
        ]
        _write_jsonl(Path(args.out), rows)
        for row in rows:
            print(
                json.dumps(
                    {
                        "case_id": row["case_id"],
                        "repeat_index": row.get("repeat_index"),
                        "repeat_count": row.get("repeat_count"),
                        "pass": row["pass"],
                        "dry_run": row["dry_run"],
                        "allowed": row["allowed"],
                        "resize_success": row.get("resize_success"),
                        "latency_ms": row["latency_ms"],
                        "dry_run_latency_ms": row.get("dry_run_latency_ms"),
                        "execute_latency_ms": row.get("execute_latency_ms"),
                        "selected_click_point": row.get("selected_click_point"),
                        "coordinate_overlay_path": row.get("coordinate_overlay_path"),
                        "trace_path": row.get("trace_path"),
                        "fail_reasons": row["fail_reasons"],
                    },
                    ensure_ascii=False,
                )
            )
        return 0 if all(row["pass"] for row in rows) else 1
    except SmokeRunnerError as exc:
        print(json.dumps({"contract_version": "execute_smoke_runner_error_v1", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
