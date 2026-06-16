from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


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
        raise RuntimeError(f"{endpoint} returned HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{endpoint} request failed: {exc}") from exc
    return json.loads(raw)


def _result_payload(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        return data["result"]
    return data if isinstance(data, dict) else {}


def _step_summary(response: dict[str, Any]) -> dict[str, Any]:
    result = _result_payload(response)
    step = result.get("agent_step_result") if isinstance(result.get("agent_step_result"), dict) else {}
    guidance = result.get("agent_execution_guidance") if isinstance(result.get("agent_execution_guidance"), dict) else {}
    evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
    post_click = step.get("post_click") if isinstance(step.get("post_click"), dict) else {}
    return {
        "success": response.get("success"),
        "message": response.get("message"),
        "error": response.get("error"),
        "status": step.get("status"),
        "goal": step.get("goal") or result.get("goal"),
        "approved_plan_id": step.get("approved_plan_id") or result.get("approved_plan_id"),
        "selected_click_point": step.get("selected_click_point") or result.get("selected_click_point"),
        "next_agent_action": step.get("next_agent_action") or guidance.get("next_action"),
        "trace_path": result.get("trace_path") or evidence.get("action_trace_path"),
        "recognition_plan_trace_path": evidence.get("recognition_plan_trace_path") or result.get("recognition_plan_trace_path"),
        "coordinate_overlay_path": evidence.get("coordinate_overlay_path"),
        "before_image_path": post_click.get("before_image_path"),
        "after_image_path": post_click.get("after_image_path"),
        "diff_image_path": post_click.get("diff_image_path"),
        "failure_reason": step.get("failure_reason"),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Smoke one Execute Mode atom: framework screenshot, dry-run preview, and optional approved real click."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Runtime API base URL.")
    parser.add_argument("--goal", required=True, help="One-step goal, for example: click Learn more.")
    parser.add_argument("--app-name", default=None, help="Expected bound app name, for example edge/chrome/notepad.")
    parser.add_argument("--state-hint", default=None, help="Optional current screen state hint.")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="After dry-run succeeds, execute the approved single step. This can perform a real click.",
    )
    parser.add_argument(
        "--reviewed-test",
        action="store_true",
        help="Allow reviewed test execution to pass a grounded candidate when only the top-score margin is too small.",
    )
    args = parser.parse_args()

    output: dict[str, Any] = {"contract_version": "execute_single_step_smoke_v1"}

    capture_response = _post_json(args.base_url, "/state/capture_window", {"save_image": True}, args.timeout)
    output["framework_capture"] = {
        "success": capture_response.get("success"),
        "message": capture_response.get("message"),
        "image_path": (capture_response.get("data") or {}).get("image_path") if isinstance(capture_response.get("data"), dict) else None,
        "error": capture_response.get("error"),
    }
    if not capture_response.get("success"):
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2

    dry_body = {
        "agent_mode": "execute",
        "goal": args.goal,
        "app_name": args.app_name,
        "state_hint": args.state_hint,
        "capture_live": True,
        "dry_run": True,
        "enable_post_click_verification": True,
        "write_policy": {"path_graph": False, "element_memory": True, "trace": True},
    }
    if args.reviewed_test:
        dry_body["metadata"] = {
            "reviewed_test_execution": {
                "allow_low_margin_when_grounded": True,
                "review_required_before_execute": True,
            }
        }
    dry_response = _post_json(args.base_url, "/action/execute_recognition_plan", dry_body, args.timeout)
    output["dry_run"] = _step_summary(dry_response)

    if args.execute and dry_response.get("success"):
        dry_result = _result_payload(dry_response)
        guidance = dry_result.get("agent_execution_guidance") if isinstance(dry_result.get("agent_execution_guidance"), dict) else {}
        next_request = guidance.get("next_request") if isinstance(guidance.get("next_request"), dict) else {}
        real_body = next_request.get("body") if isinstance(next_request.get("body"), dict) else None
        if real_body is None:
            approved_plan_id = dry_result.get("approved_plan_id")
            real_body = {
                "agent_mode": "execute",
                "goal": args.goal,
                "app_name": args.app_name,
                "state_hint": args.state_hint,
                "approved_plan_id": approved_plan_id,
                "capture_live": True,
                "dry_run": False,
                "enable_post_click_verification": True,
            }
        real_response = _post_json(args.base_url, "/action/execute_recognition_plan", real_body, args.timeout)
        output["real_click"] = _step_summary(real_response)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not dry_response.get("success"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
