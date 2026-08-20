from __future__ import annotations

import re
from typing import Any


BOUND_WINDOW_MATCH_CONTRACT = "bound_window_match_decision_v1"


def validate_bound_window_for_app(
    *,
    expected_app_name: Any,
    bound_window: dict[str, Any],
) -> dict[str, Any]:
    expected = _normalize_window_token(expected_app_name)
    process = _normalize_window_token(bound_window.get("process_name"))
    title = _normalize_window_token(bound_window.get("title"))
    if not expected:
        return {
            "contract_version": BOUND_WINDOW_MATCH_CONTRACT,
            "valid": True,
            "reason": "no_app_name_requested",
            "bound_window": bound_window,
        }

    alias = _WINDOW_ALIASES.get(expected)
    if alias is not None:
        allowed_processes = alias["processes"]
        title_tokens = alias["title_tokens"]
        valid = process in allowed_processes or any(token in title for token in title_tokens)
        return {
            "contract_version": BOUND_WINDOW_MATCH_CONTRACT,
            "valid": valid,
            "reason": "matched_app_alias" if valid else "process_name_mismatch",
            "expected_app_name": expected_app_name,
            "allowed_processes": sorted(allowed_processes),
            "actual_process_name": bound_window.get("process_name"),
            "actual_title": bound_window.get("title"),
            "bound_window": bound_window,
        }

    valid = bool(expected and (expected in process or expected in title))
    if not valid:
        return {
            "contract_version": BOUND_WINDOW_MATCH_CONTRACT,
            "valid": True,
            "reason": "unmapped_app_name_not_enforced",
            "expected_app_name": expected_app_name,
            "actual_process_name": bound_window.get("process_name"),
            "actual_title": bound_window.get("title"),
            "bound_window": bound_window,
        }
    return {
        "contract_version": BOUND_WINDOW_MATCH_CONTRACT,
        "valid": True,
        "reason": "matched_process_or_title",
        "expected_app_name": expected_app_name,
        "actual_process_name": bound_window.get("process_name"),
        "actual_title": bound_window.get("title"),
        "bound_window": bound_window,
    }


def _normalize_window_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


_WINDOW_ALIASES: dict[str, dict[str, set[str]]] = {
    "edge": {"processes": {"msedgeexe"}, "title_tokens": set()},
    "msedge": {"processes": {"msedgeexe"}, "title_tokens": set()},
    "browser": {"processes": {"msedgeexe", "chromeexe", "firefoxexe"}, "title_tokens": set()},
    "chrome": {"processes": {"chromeexe"}, "title_tokens": set()},
    "notepad": {"processes": {"notepadexe"}, "title_tokens": {"notepad"}},
    "qq": {"processes": {"qqexe"}, "title_tokens": {"qq"}},
    "mousetester": {"processes": {"msedgeexe", "chromeexe"}, "title_tokens": {"mousetester"}},
    "mousetesterweb": {"processes": {"msedgeexe", "chromeexe"}, "title_tokens": {"mousetester"}},
}
