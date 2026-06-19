from __future__ import annotations

from typing import Any


def add_audit_check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    message: str,
    *,
    actual: Any = None,
    expected: Any = None,
    severity: str = "fail",
) -> None:
    status = "pass" if passed else severity
    checks.append(
        {
            "id": check_id,
            "status": status,
            "message": message,
            "actual": actual,
            "expected": expected,
        }
    )


def audit_counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "checks": len(checks),
        "passed": sum(1 for check in checks if check.get("status") == "pass"),
        "warnings": sum(1 for check in checks if check.get("status") == "warn"),
        "failed": sum(1 for check in checks if check.get("status") == "fail"),
    }


def audit_decision(checks: list[dict[str, Any]]) -> str:
    return "needs_review" if any(check.get("status") == "fail" for check in checks) else "pass"


def int_value(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []


def recursive_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        if key in value:
            found.append(value[key])
        for child in value.values():
            found.extend(recursive_values(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(recursive_values(child, key))
    return found
