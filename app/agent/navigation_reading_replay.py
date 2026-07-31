from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.agent.continuous_task_session import (
    create_continuous_task_session,
    observe_interface,
    record_action_result,
    record_agent_decision,
    record_gate_rejection,
    record_read_result,
)
from app.agent.navigation_reading import (
    build_navigation_reading_context,
    validate_navigation_reading_decision,
)
from app.learn.agent_evidence import build_agent_evidence_context


MANIFEST_CONTRACT = "navigation_reading_replay_manifest_v1"
REPORT_CONTRACT = "navigation_reading_replay_report_v1"
METRIC_NAMES = (
    "reviewed_asset_validity",
    "agent_context_build",
    "agent_decision_validation",
    "gate_safety",
    "operation_dispatch",
    "effect_verification",
    "destination_observation",
    "finite_read_completion",
    "wrong_scope_safe_stop",
)


def run_navigation_reading_replay(
    *,
    manifest_path: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    """复跑审核资产的导航、读取和滚动证据，不执行真实 GUI 动作。"""

    manifest_file = Path(manifest_path).resolve()
    manifest = _read_json(manifest_file)
    if manifest.get("contract_version") != MANIFEST_CONTRACT:
        raise ValueError(f"{MANIFEST_CONTRACT} manifest is required")

    assets, asset_errors = _load_assets(
        manifest.get("interface_assets"),
        base_dir=manifest_file.parent,
    )
    transitions = [
        item
        for item in manifest.get("transitions") or []
        if isinstance(item, dict)
    ]
    cases = [item for item in manifest.get("cases") or [] if isinstance(item, dict)]
    invalid_cases: list[dict[str, Any]] = []
    runnable_cases: list[dict[str, Any]] = []

    for case in cases:
        case_id = _required_text(case.get("case_id"), "case_id")
        referenced = _case_interface_ids(case)
        failures = [
            (interface_id, asset_errors[interface_id])
            for interface_id in referenced
            if interface_id in asset_errors
        ]
        missing = [
            interface_id
            for interface_id in referenced
            if interface_id not in assets and interface_id not in asset_errors
        ]
        if failures or missing:
            if failures:
                interface_id, failure = failures[0]
                invalid_cases.append(
                    {
                        "case_id": case_id,
                        "failure_category": failure["failure_category"],
                        "interface_id": interface_id,
                        "asset_path": failure["asset_path"],
                        "expected_sha256": failure.get("expected_sha256"),
                        "actual_sha256": failure.get("actual_sha256"),
                    }
                )
            else:
                invalid_cases.append(
                    {
                        "case_id": case_id,
                        "failure_category": "missing_reviewed_asset",
                        "interface_id": missing[0],
                        "asset_path": None,
                    }
                )
            continue
        runnable_cases.append(case)

    metrics = {name: _counter() for name in METRIC_NAMES}
    used_asset_ids = {
        interface_id
        for case in runnable_cases
        for interface_id in _case_interface_ids(case)
    }
    for interface_id in sorted(used_asset_ids):
        _record(metrics["reviewed_asset_validity"], passed=interface_id in assets)

    case_reports = [
        _run_case(
            case,
            assets=assets,
            transitions=transitions,
            metrics=metrics,
        )
        for case in runnable_cases
    ]
    passed = sum(item["case_outcome"] in {"passed", "safe_stop"} for item in case_reports)
    safe_stop = sum(item["case_outcome"] == "safe_stop" for item in case_reports)

    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    report_path = out_path / "navigation_reading_replay_report.json"
    report = {
        "contract_version": REPORT_CONTRACT,
        "suite_id": str(manifest.get("suite_id") or manifest_file.stem),
        "decision_source": str(
            manifest.get("decision_source") or "recorded_agent_output"
        ),
        "model_decision_quality": "not_evaluated",
        "interpretation": (
            "Recorded semantic Agent decisions and recorded Operation/Gate evidence "
            "only; this is not live GUI or model decision reliability."
        ),
        "summary": {
            "attempted": len(case_reports),
            "passed": passed,
            "failed": len(case_reports) - passed,
            "invalid": len(invalid_cases),
            "safe_stop": safe_stop,
        },
        "metrics": {
            name: _finalize_metric(value)
            for name, value in metrics.items()
        },
        "invalid_cases": invalid_cases,
        "cases": case_reports,
        "safety": {
            "live_gui_actions": 0,
            "historical_coordinates_used": False,
            "final_submit_forbidden": True,
            "artifact_is_authorization": False,
        },
        "report_path": str(report_path),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _run_case(
    case: dict[str, Any],
    *,
    assets: dict[str, dict[str, Any]],
    transitions: list[dict[str, Any]],
    metrics: dict[str, dict[str, int]],
) -> dict[str, Any]:
    case_id = _required_text(case.get("case_id"), "case_id")
    goal = _required_text(case.get("goal"), "goal")
    initial = _validated_observation(case.get("initial_observation"))
    session = create_continuous_task_session(
        session_id=f"replay:{case_id}",
        workflow_id=str(case.get("workflow_id") or "navigation-reading"),
    )
    visited_interfaces: list[str] = []
    session = _observe(
        session,
        initial,
        assets=assets,
        visited_interfaces=visited_interfaces,
    )
    step_reports: list[dict[str, Any]] = []
    case_failure: str | None = None

    for raw_step in case.get("steps") or []:
        if not isinstance(raw_step, dict):
            continue
        try:
            session, step_report = _run_step(
                raw_step,
                goal=goal,
                session=session,
                assets=assets,
                transitions=transitions,
                metrics=metrics,
                visited_interfaces=visited_interfaces,
            )
            step_reports.append(step_report)
        except (KeyError, TypeError, ValueError) as exc:
            case_failure = f"{type(exc).__name__}: {exc}"
            step_reports.append(
                {
                    "step_id": str(raw_step.get("step_id") or "unknown"),
                    "case_outcome": "failed",
                    "failure_category": "replay_contract_failure",
                    "error": case_failure,
                }
            )
            break
        if session.get("status") == "safe_stop":
            break

    expected_outcome = str(case.get("expected_outcome") or "goal_satisfied")
    expected_stop = str(case.get("expected_stop_reason") or "")
    actual_stop = str(session.get("stop_reason") or "")
    has_failed_step = any(
        item.get("case_outcome") == "failed" for item in step_reports
    )
    if case_failure:
        outcome = "failed"
    elif expected_outcome == "safe_stop":
        outcome = (
            "safe_stop"
            if session.get("status") == "safe_stop"
            and (not expected_stop or actual_stop == expected_stop)
            else "failed"
        )
    else:
        outcome = (
            "passed"
            if not has_failed_step
            and session.get("status") not in {"safe_stop", "needs_human_review"}
            else "failed"
        )

    return {
        "case_id": case_id,
        "goal": goal,
        "expected_outcome": expected_outcome,
        "case_outcome": outcome,
        "stop_reason": actual_stop or None,
        "visited_interfaces": visited_interfaces,
        "final_read_state": deepcopy(session.get("current_read_state")),
        "steps": step_reports,
        "trace_events": deepcopy(session.get("events") or []),
        "failure": case_failure,
    }


def _run_step(
    step: dict[str, Any],
    *,
    goal: str,
    session: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    transitions: list[dict[str, Any]],
    metrics: dict[str, dict[str, int]],
    visited_interfaces: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    interface_id = _required_text(session.get("current_interface_id"), "interface_id")
    asset = assets[interface_id]
    observation = _observation_from_session(session)
    outgoing = [
        item
        for item in transitions
        if str(item.get("source_interface_id") or "") == interface_id
    ]

    try:
        agent_evidence = build_agent_evidence_context(
            _asset_with_transition_targets(asset, outgoing),
        )
        context = build_navigation_reading_context(
            goal=goal,
            interface_evidence=agent_evidence,
            observation=observation,
            read_progress=step.get("read_progress"),
        )
    except (TypeError, ValueError):
        _record(metrics["agent_context_build"], passed=False)
        raise
    _record(metrics["agent_context_build"], passed=True)

    try:
        decision_plan = validate_navigation_reading_decision(
            context,
            step.get("decision"),
        )
    except (TypeError, ValueError):
        _record(metrics["agent_decision_validation"], passed=False)
        raise
    _record(metrics["agent_decision_validation"], passed=True)
    session = record_agent_decision(session, decision_plan=decision_plan)
    result = step.get("read_result") or step.get("operation_result")
    if not isinstance(result, dict):
        raise ValueError("step result evidence is required")

    gate = result.get("gate_result")
    if not isinstance(gate, dict) or not isinstance(gate.get("allowed"), bool):
        _record(metrics["gate_safety"], passed=False)
        raise ValueError("boolean gate_result.allowed is required")
    allowed = gate["allowed"]
    dispatched = bool(
        result.get("action_dispatched")
        if "action_dispatched" in result
        else result.get("action_executed")
    )
    gate_passed = allowed or not dispatched
    _record(metrics["gate_safety"], passed=gate_passed)

    step_report = {
        "step_id": str(step.get("step_id") or "unknown"),
        "interface_id": interface_id,
        "choice_id": decision_plan["choice_id"],
        "decision_type": decision_plan["decision_type"],
        "semantic_action": decision_plan["semantic_action"],
        "gate_allowed": allowed,
        "gate_reason": str(gate.get("reason") or ""),
        "fresh_capture_id": decision_plan["freshness"]["capture_id"],
        "historical_coordinates_used": False,
        "action_executed": dispatched,
    }

    if not allowed:
        if dispatched:
            step_report["case_outcome"] = "failed"
            step_report["gate_safety"] = "failed_executed_after_rejection"
            raise ValueError("operation executed after Gate rejection")
        session = record_gate_rejection(
            session,
            reason=str(gate.get("reason") or "gate_rejected"),
            evidence=observation,
        )
        step_report["case_outcome"] = "safe_intercept"
        step_report["gate_safety"] = "passed_rejected"
        return session, step_report

    _record(metrics["operation_dispatch"], passed=dispatched)
    if "read_result" in step:
        effect_verified = bool(result.get("effect_verified"))
        _record(metrics["effect_verification"], passed=effect_verified)
        session = record_read_result(
            session,
            action_type=str(result.get("action_type") or ""),
            action_dispatched=dispatched,
            effect_verified=effect_verified,
            read_report=result.get("report"),
            evidence=result.get("evidence"),
        )
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        if (
            decision_plan["decision_type"] == "read_region"
            and _selected_read_strategy(context, decision_plan) == "finite_detail"
        ):
            completed = (
                report.get("reached_bottom") is True
                or report.get("stop_reason") == "reached_bottom"
            )
            _record(metrics["finite_read_completion"], passed=completed)
        if session.get("stop_reason") == "wrong_scope_detected":
            _record(metrics["wrong_scope_safe_stop"], passed=True)
            step_report["case_outcome"] = "safe_intercept"
        else:
            step_report["case_outcome"] = "passed" if effect_verified else "failed"
    else:
        effect_verified = bool(result.get("post_action_verified"))
        _record(metrics["effect_verification"], passed=effect_verified)
        session = record_action_result(
            session,
            action_type=str(result.get("action_type") or ""),
            action_executed=dispatched,
            post_action_verified=effect_verified,
            evidence=result.get("evidence"),
            transition_audit={
                "decision_choice_id": decision_plan["choice_id"],
                "expected_target_interface_id": _expected_target(
                    decision_plan,
                    outgoing,
                ),
            },
        )
        step_report["case_outcome"] = (
            "passed" if dispatched and effect_verified else "failed"
        )

    if isinstance(step.get("post_observation"), dict):
        post_observation = _validated_observation(step["post_observation"])
        expected_target = _expected_target(decision_plan, outgoing)
        destination_ok = (
            not expected_target
            or post_observation["interface_id"] == expected_target
        )
        _record(metrics["destination_observation"], passed=destination_ok)
        if not destination_ok:
            raise ValueError("post observation does not match transition target")
        session = _observe(
            session,
            post_observation,
            assets=assets,
            visited_interfaces=visited_interfaces,
        )
        step_report["post_observation_interface_id"] = post_observation[
            "interface_id"
        ]
    return session, step_report


def _asset_with_transition_targets(
    asset: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    projected = deepcopy(asset)
    actions = projected.get("action_candidates")
    if not isinstance(actions, list):
        actions = []
        projected["action_candidates"] = actions
    matched: set[int] = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        for index, transition in enumerate(transitions):
            if _same_action(action, transition):
                action["target_interface_id"] = transition.get("target_interface_id")
                action["success_conditions"] = list(
                    transition.get("success_conditions") or []
                )
                matched.add(index)
                break
    for index, transition in enumerate(transitions):
        if index in matched:
            continue
        item = deepcopy(transition)
        item["action_template_id"] = str(
            item.get("action_id") or item.get("transition_id") or ""
        )
        item.pop("transition_id", None)
        actions.append(item)
    return projected


def _same_action(action: dict[str, Any], transition: dict[str, Any]) -> bool:
    action_type = str(
        action.get("semantic_action") or action.get("action_type") or ""
    ).casefold()
    transition_type = str(transition.get("action_type") or "").casefold()
    action_control = str(
        action.get("target_control_id") or action.get("source_control_id") or ""
    )
    transition_control = str(transition.get("source_control_id") or "")
    return bool(
        action_type
        and action_type == transition_type
        and action_control
        and action_control == transition_control
    )


def _observe(
    session: dict[str, Any],
    observation: dict[str, str],
    *,
    assets: dict[str, dict[str, Any]],
    visited_interfaces: list[str],
) -> dict[str, Any]:
    interface_id = observation["interface_id"]
    asset = assets[interface_id]
    if not visited_interfaces or visited_interfaces[-1] != interface_id:
        visited_interfaces.append(interface_id)
    return observe_interface(
        session,
        interface_id=interface_id,
        surface_type=str(asset.get("surface_type") or "unknown_surface"),
        memory_object_sha256=_sha256_json(asset),
        evidence=observation,
        learning_required=False,
        knowledge_source="reviewed_interface_asset_replay",
    )


def _selected_read_strategy(
    context: dict[str, Any],
    decision: dict[str, Any],
) -> str:
    selected = next(
        (
            item
            for item in context.get("choices") or []
            if isinstance(item, dict)
            and item.get("choice_id") == decision.get("choice_id")
        ),
        {},
    )
    return str(selected.get("read_strategy") or "")


def _expected_target(
    decision: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> str:
    expected = str(decision.get("expected_target_interface_id") or "")
    if expected:
        return expected
    for transition in transitions:
        if (
            str(transition.get("source_control_id") or "")
            == str(decision.get("source_control_id") or "")
            and str(transition.get("action_type") or "").casefold()
            == str(decision.get("semantic_action") or "").casefold()
        ):
            return str(transition.get("target_interface_id") or "")
    return ""


def _load_assets(
    value: Any,
    *,
    base_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    assets: dict[str, dict[str, Any]] = {}
    errors: dict[str, dict[str, Any]] = {}
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        interface_id = _required_text(item.get("interface_id"), "interface_id")
        raw_path = Path(_required_text(item.get("path"), "asset path"))
        asset_path = raw_path if raw_path.is_absolute() else base_dir / raw_path
        expected = _required_text(item.get("sha256"), "asset sha256").casefold()
        if not asset_path.is_file():
            errors[interface_id] = {
                "failure_category": "missing_reviewed_asset",
                "asset_path": str(asset_path),
                "expected_sha256": expected,
                "actual_sha256": None,
            }
            continue
        content = asset_path.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            errors[interface_id] = {
                "failure_category": "stale_reviewed_asset",
                "asset_path": str(asset_path),
                "expected_sha256": expected,
                "actual_sha256": actual,
            }
            continue
        asset = json.loads(content.decode("utf-8-sig"))
        if (
            not isinstance(asset, dict)
            or asset.get("contract_version") != "single_interface_asset_v1"
            or str(asset.get("interface_id") or "") != interface_id
        ):
            errors[interface_id] = {
                "failure_category": "invalid_reviewed_asset",
                "asset_path": str(asset_path),
                "expected_sha256": expected,
                "actual_sha256": actual,
            }
            continue
        assets[interface_id] = asset
    return assets, errors


def _case_interface_ids(case: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    observations = [case.get("initial_observation")]
    observations.extend(
        step.get("post_observation")
        for step in case.get("steps") or []
        if isinstance(step, dict)
    )
    for observation in observations:
        if isinstance(observation, dict):
            interface_id = str(observation.get("interface_id") or "").strip()
            if interface_id:
                result.add(interface_id)
    return result


def _observation_from_session(session: dict[str, Any]) -> dict[str, Any]:
    evidence = session.get("current_observation_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("current observation evidence is missing")
    return {
        "contract_version": "current_interface_observation_v1",
        "interface_id": session.get("current_interface_id"),
        **deepcopy(evidence),
    }


def _validated_observation(value: Any) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or value.get("contract_version") != "current_interface_observation_v1"
    ):
        raise ValueError("current_interface_observation_v1 is required")
    return {
        "contract_version": "current_interface_observation_v1",
        "interface_id": _required_text(value.get("interface_id"), "interface_id"),
        "capture_id": _required_text(value.get("capture_id"), "capture_id"),
        "screenshot_sha256": _required_text(
            value.get("screenshot_sha256"),
            "screenshot_sha256",
        ),
        "trace_path": _required_text(value.get("trace_path"), "trace_path"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("JSON object is required")
    return value


def _sha256_json(value: dict[str, Any]) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _counter() -> dict[str, int]:
    return {"passed": 0, "attempted": 0}


def _record(counter: dict[str, int], *, passed: bool) -> None:
    counter["attempted"] += 1
    if passed:
        counter["passed"] += 1


def _finalize_metric(counter: dict[str, int]) -> dict[str, Any]:
    attempted = counter["attempted"]
    passed = counter["passed"]
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": round(passed / attempted, 4) if attempted else "not_covered",
    }


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
