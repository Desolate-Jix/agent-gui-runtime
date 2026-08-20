from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class UIASmokeEvalCase:
    case_id: str
    trace_path: str
    expected_status: str = "ok"
    min_control_count: int = 1
    min_button_count: int = 0
    expected_name_contains: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UIASmokeEvalCase":
        return cls(
            case_id=str(payload["case_id"]),
            trace_path=str(payload["trace_path"]),
            expected_status=str(payload.get("expected_status") or "ok"),
            min_control_count=int(payload.get("min_control_count") or 1),
            min_button_count=int(payload.get("min_button_count") or 0),
            expected_name_contains=[str(item) for item in payload.get("expected_name_contains") or []],
        )


def load_cases(path: str | Path) -> list[UIASmokeEvalCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    return [UIASmokeEvalCase.from_dict(item) for item in raw_cases]


def evaluate_cases(cases: list[UIASmokeEvalCase], *, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    results = [evaluate_case(case, root=root_path) for case in cases]
    present = [item for item in results if not item.get("missing")]
    passed = [item for item in present if item.get("passed")]
    return {
        "contract_version": "uia_smoke_eval_v1",
        "summary": {
            "case_count": len(results),
            "present_case_count": len(present),
            "missing_case_count": len(results) - len(present),
            "passed_case_count": len(passed),
            "pass_rate": _rate(len(passed), len(present)),
        },
        "results": results,
        "root": str(root_path.resolve()),
    }


def evaluate_case(case: UIASmokeEvalCase, *, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    trace_path = Path(case.trace_path)
    if not trace_path.is_absolute():
        trace_path = root_path / trace_path
    base = {
        "case_id": case.case_id,
        "trace_path": str(trace_path),
        "expectations": {
            "expected_status": case.expected_status,
            "min_control_count": case.min_control_count,
            "min_button_count": case.min_button_count,
            "expected_name_contains": case.expected_name_contains,
        },
    }
    if not trace_path.exists():
        return {**base, "missing": True, "passed": False, "checks": {"trace_exists": {"passed": False}}}

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    facts = _extract_facts(payload)
    checks = _evaluate_expectations(case, facts)
    return {
        **base,
        "missing": False,
        "passed": all(item["passed"] for item in checks.values()),
        "checks": checks,
        "facts": facts,
    }


def _extract_facts(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") or {}
    snapshot = result.get("snapshot") or payload.get("snapshot") or {}
    controls = list(snapshot.get("controls") or [])
    button_controls = [item for item in controls if str(item.get("control_type") or "").casefold() == "button"]
    names = [str(item.get("name") or "") for item in controls if str(item.get("name") or "").strip()]
    return {
        "trace_success": bool(payload.get("success")),
        "snapshot_status": snapshot.get("status"),
        "snapshot_reason": snapshot.get("reason"),
        "control_count": int(snapshot.get("control_count") or len(controls)),
        "button_count": len(button_controls),
        "names": names,
        "matched_names": [],
    }


def _evaluate_expectations(case: UIASmokeEvalCase, facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    names = list(facts.get("names") or [])
    name_checks = {}
    matched_names: list[str] = []
    for expected in case.expected_name_contains:
        matched = _first_name_match(names, expected)
        if matched is not None:
            matched_names.append(matched)
        name_checks[f"name_contains:{expected}"] = {
            "passed": matched is not None,
            "actual": matched,
            "expected": expected,
        }
    facts["matched_names"] = matched_names

    return {
        "status": _check(facts.get("snapshot_status"), case.expected_status),
        "control_count": {
            "passed": int(facts.get("control_count") or 0) >= case.min_control_count,
            "actual": facts.get("control_count"),
            "expected_min": case.min_control_count,
        },
        "button_count": {
            "passed": int(facts.get("button_count") or 0) >= case.min_button_count,
            "actual": facts.get("button_count"),
            "expected_min": case.min_button_count,
        },
        **name_checks,
    }


def _first_name_match(names: list[str], expected: str) -> str | None:
    normalized_expected = _normalize_text(expected)
    if not normalized_expected:
        return None
    for name in names:
        if normalized_expected in _normalize_text(name):
            return name
    return None


def _check(actual: Any, expected: Any) -> dict[str, Any]:
    return {"passed": actual == expected, "actual": actual, "expected": expected}


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _normalize_text(value: Any) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())
