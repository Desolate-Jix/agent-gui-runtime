from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.surface_adapters import select_learning_surface_adapter
from app.learn.recognition.trace_input import (
    observe_bundle_from_trace_result,
    stage1_inventory_from_trace_result,
)


def run_surface_adapter_benchmark(
    *,
    manifest_path: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    manifest_file = _resolve(manifest_path)
    output_dir = _resolve(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    contract_version = str(manifest.get("contract_version") or "")
    supported_contracts = {
        "learning_surface_adapter_holdout_manifest_v1",
        "learning_surface_adapter_protocol_manifest_v1",
    }
    if contract_version not in supported_contracts:
        raise ValueError(f"unsupported surface adapter benchmark manifest: {contract_version}")
    protocol_manifest = contract_version == "learning_surface_adapter_protocol_manifest_v1"
    manifest_split = str(manifest.get("split") or ("holdout" if not protocol_manifest else ""))
    used_for_rule_tuning = bool(manifest.get("used_for_rule_tuning"))
    if protocol_manifest and manifest_split not in {"dev", "holdout"}:
        raise ValueError("surface adapter protocol manifest split must be dev or holdout")
    if manifest_split == "holdout" and used_for_rule_tuning:
        raise ValueError("holdout manifest cannot be used for rule tuning")

    valid_cases: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    for case in manifest.get("cases") if isinstance(manifest.get("cases"), list) else []:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "unknown_case")
        trace_path = _resolve(str(case.get("trace_path") or ""))
        screenshot_path = _resolve(str(case.get("screenshot_path") or ""))
        invalid = _fixture_error(case_id, case, trace_path=trace_path, screenshot_path=screenshot_path)
        if invalid:
            invalid_cases.append(invalid)
            continue
        trace = json.loads(trace_path.read_text(encoding="utf-8-sig"))
        result = trace.get("result") if isinstance(trace.get("result"), dict) else trace
        bundle = observe_bundle_from_trace_result(result, trace_path=trace_path)
        inventory = stage1_inventory_from_trace_result(result)
        decision = select_learning_surface_adapter(bundle=bundle, screen_inventory=inventory)
        expected_adapter_id = (
            _optional_text(case.get("expected_adapter_id"))
            if protocol_manifest
            else str(case.get("expected_adapter_id") or "generic")
        )
        actual_adapter_id = str(decision.get("adapter_id") or "generic")
        expected_host_adapter_id = _optional_text(case.get("expected_host_adapter_id"))
        expected_host_adapter_status = _optional_text(case.get("expected_host_adapter_status"))
        expected_content_adapter_id = _optional_text(case.get("expected_content_adapter_id"))
        expected_content_adapter_status = _optional_text(case.get("expected_content_adapter_status"))
        expected_decision_status = _optional_text(case.get("expected_decision_status"))
        checks = {
            "adapter_selection": (
                actual_adapter_id == expected_adapter_id
                if expected_adapter_id is not None
                else None
            ),
            "host_adapter_selection": (
                str(decision.get("host_adapter_id") or "generic") == expected_host_adapter_id
                if expected_host_adapter_id is not None
                else None
            ),
            "host_adapter_status": (
                str(decision.get("host_adapter_status") or "not_applicable")
                == expected_host_adapter_status
                if expected_host_adapter_status is not None
                else None
            ),
            "content_adapter_selection": (
                str(decision.get("content_adapter_id") or "generic") == expected_content_adapter_id
                if expected_content_adapter_id is not None
                else None
            ),
            "content_adapter_status": (
                str(decision.get("content_adapter_status") or "not_applicable")
                == expected_content_adapter_status
                if expected_content_adapter_status is not None
                else None
            ),
            "decision_status": (
                str(decision.get("status") or "") == expected_decision_status
                if expected_decision_status is not None
                else None
            ),
        }
        explicit_check_results = [value for value in checks.values() if value is not None]
        source_type = str(case.get("source_type") or "fixed_recorded_trace")
        valid_cases.append(
            {
                "case_id": case_id,
                "source_type": source_type,
                "used_for_rule_tuning": bool(case.get("used_for_rule_tuning", used_for_rule_tuning)),
                "expected_adapter_id": expected_adapter_id,
                "actual_adapter_id": actual_adapter_id,
                "expected_host_adapter_id": expected_host_adapter_id,
                "actual_host_adapter_id": decision.get("host_adapter_id"),
                "expected_host_adapter_status": expected_host_adapter_status,
                "actual_host_adapter_status": decision.get("host_adapter_status"),
                "expected_content_adapter_id": expected_content_adapter_id,
                "actual_content_adapter_id": decision.get("content_adapter_id"),
                "expected_content_adapter_status": expected_content_adapter_status,
                "actual_content_adapter_status": decision.get("content_adapter_status"),
                "expected_decision_status": expected_decision_status,
                "checks": checks,
                "passed": bool(explicit_check_results) and all(explicit_check_results),
                "decision_status": decision.get("status"),
                "selection_evidence": decision.get("selection_evidence") or [],
                "trace_path": _relative(trace_path),
                "screenshot_path": _relative(screenshot_path),
                "surface_adapter_decision": decision,
            }
        )

    attempted = len(valid_cases)
    passed = sum(1 for case in valid_cases if case["passed"])
    source_breakdown: dict[str, int] = {}
    for case in valid_cases:
        source_type = str(case.get("source_type") or "unknown")
        source_breakdown[source_type] = source_breakdown.get(source_type, 0) + 1
    legacy_denominator = contract_version == "learning_surface_adapter_holdout_manifest_v1"
    report = {
        "contract_version": "learning_surface_adapter_benchmark_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": _relative(manifest_file),
        "manifest_contract_version": contract_version,
        "manifest_split": manifest_split,
        "used_for_rule_tuning": used_for_rule_tuning,
        "holdout_used_for_rule_tuning": used_for_rule_tuning if manifest_split == "holdout" else False,
        "adapter_selection": {
            "passed": passed,
            "attempted": attempted,
            "rate": round(passed / attempted, 4) if attempted else "not_covered",
            "denominator": (
                "checksum-valid fixed holdout adapter decisions"
                if legacy_denominator
                else "checksum-valid cases passing every explicit host/content/status expectation"
            ),
            "interpretation": (
                "fixed holdout decision checks only; not recognition accuracy or general GUI reliability"
                if legacy_denominator
                else "layered routing contract checks only; not recognition accuracy or general GUI reliability"
            ),
        },
        "host_adapter_selection": _layer_metric(
            valid_cases,
            "host_adapter_selection",
            denominator="cases with an explicit expected host adapter",
            interpretation="host-shell routing only; not content recognition or GUI reliability",
        ),
        "content_adapter_selection": _layer_metric(
            valid_cases,
            "content_adapter_selection",
            denominator="cases with an explicit expected content adapter",
            interpretation="content-topology routing only; not bbox, grounding, or live reliability",
        ),
        "content_adapter_status": _layer_metric(
            valid_cases,
            "content_adapter_status",
            denominator="cases with an explicit expected content evidence status",
            interpretation="evidence-correlation status only; not recognition accuracy",
        ),
        "host_adapter_status": _layer_metric(
            valid_cases,
            "host_adapter_status",
            denominator="cases with an explicit expected host evidence status",
            interpretation="host evidence status only; not content recognition or GUI reliability",
        ),
        "decision_status": _layer_metric(
            valid_cases,
            "decision_status",
            denominator="cases with an explicit expected combined decision status",
            interpretation="combined routing status only; not recognition accuracy",
        ),
        "source_breakdown": source_breakdown,
        "model_ability_denominator": {
            "attempted": 0,
            "rate": "not_covered",
            "interpretation": "surface-routing fixtures do not measure model ability",
        },
        "cases": valid_cases,
        "invalid_cases": invalid_cases,
        "failure_cases": [case for case in valid_cases if not case["passed"]],
        "safety": {
            "model_calls": 0,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "interpretation": (
            "Offline adapter-selection holdout. It validates evidence routing only and does not measure recognition "
            "accuracy, bbox quality, point grounding, model ability, or live GUI reliability."
        ),
    }
    report_path = output_dir / "surface_adapter_benchmark_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = _relative(report_path)
    return report


def _fixture_error(
    case_id: str,
    case: dict[str, Any],
    *,
    trace_path: Path,
    screenshot_path: Path,
) -> dict[str, Any] | None:
    if not trace_path.exists() or not screenshot_path.exists():
        return {
            "case_id": case_id,
            "failure_category": "missing_fixture",
            "trace_path": _relative(trace_path),
            "screenshot_path": _relative(screenshot_path),
        }
    expected_trace = str(case.get("trace_sha256") or "").casefold()
    actual_trace = _sha256(trace_path)
    if not expected_trace or expected_trace != actual_trace:
        return {
            "case_id": case_id,
            "failure_category": "stale_trace_fixture",
            "expected_trace_checksum": expected_trace,
            "actual_trace_checksum": actual_trace,
            "trace_path": _relative(trace_path),
        }
    expected_screenshot = str(case.get("screenshot_sha256") or "").casefold()
    actual_screenshot = _sha256(screenshot_path)
    if not expected_screenshot or expected_screenshot != actual_screenshot:
        return {
            "case_id": case_id,
            "failure_category": "stale_screenshot_fixture",
            "expected_screenshot_checksum": expected_screenshot,
            "actual_screenshot_checksum": actual_screenshot,
            "screenshot_path": _relative(screenshot_path),
        }
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _layer_metric(
    cases: list[dict[str, Any]],
    check_name: str,
    *,
    denominator: str,
    interpretation: str,
) -> dict[str, Any]:
    values = [
        case.get("checks", {}).get(check_name)
        for case in cases
        if isinstance(case.get("checks"), dict)
        and case["checks"].get(check_name) is not None
    ]
    attempted = len(values)
    passed = sum(value is True for value in values)
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": round(passed / attempted, 4) if attempted else "not_covered",
        "denominator": denominator,
        "interpretation": interpretation,
    }


def _resolve(path: str | Path) -> Path:
    value = Path(path)
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed Learning Mode surface-adapter holdout.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_surface_adapter_benchmark(manifest_path=args.manifest, out_dir=args.out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"report_path={report['report_path']}")
        print(f"adapter_selection={report['adapter_selection']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
