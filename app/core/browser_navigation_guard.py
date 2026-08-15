"""Fail-closed, HWND-scoped browser navigation verification."""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse
import time


def _origin(url: Any) -> str:
    parsed = urlparse(str(url or ""))
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def verify_navigation_policy(
    policy: dict[str, Any],
    hwnd: int,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    probe: Callable[[int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify an explicit navigation policy; never infer success from pixels alone."""
    required = policy.get("required") is True
    if not required:
        return {"verified": True, "status": "not_required", "policy_applied": False}
    if before is None or after is None:
        if probe is None:
            return {"verified": False, "reason": "navigation_probe_unavailable"}
        before = probe(int(hwnd))
        after = probe(int(hwnd))
    if not isinstance(before, dict) or not isinstance(after, dict) or before.get("status") != "ok" or after.get("status") != "ok":
        return {"verified": False, "reason": "navigation_probe_unavailable", "before": before, "after": after}
    expected = _origin(policy.get("expected_origin"))
    actual = _origin(after.get("url"))
    before_origin = _origin(before.get("url"))
    if policy.get("require_same_origin_as_before") is True and actual != before_origin:
        return {
            "verified": False,
            "reason": "unexpected_origin",
            "expected_origin": before_origin,
            "actual_origin": actual,
            "before": before,
            "after": after,
        }
    if expected and actual != expected:
        return {"verified": False, "reason": "unexpected_origin", "expected_origin": expected, "actual_origin": actual, "before": before, "after": after}
    if policy.get("forbid_new_tab") is True:
        old = set(before.get("tab_ids") or [])
        new = set(after.get("tab_ids") or [])
        before_identity_source = str(before.get("tab_identity_source") or "")
        after_identity_source = str(after.get("tab_identity_source") or "")
        stable_identity_changed = bool(
            old
            and new != old
            and before_identity_source == "uia_runtime_id"
            and after_identity_source == "uia_runtime_id"
        )
        if (before.get("tab_count") is None or after.get("tab_count") is None
                or int(after.get("tab_count")) != int(before.get("tab_count"))
                or stable_identity_changed):
            return {"verified": False, "reason": "unexpected_new_tab", "before": before, "after": after}
    return {"verified": True, "reason": "navigation_verified", "before": before, "after": after}


def probe_after_settle(
    policy: dict[str, Any],
    hwnd: int,
    probe: Callable[[int], dict[str, Any]],
    *,
    before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Poll the bound HWND during the explicit settle window; fail on any bad sample."""
    timeout = max(0, min(int(policy.get("settle_timeout_ms", 0) or 0), 30_000)) / 1000
    deadline = time.monotonic() + timeout
    samples: list[dict[str, Any]] = []
    while True:
        sample = probe(int(hwnd))
        samples.append(sample)
        if sample.get("status") != "ok":
            return {"verified": False, "reason": "navigation_probe_unavailable", "samples": samples}
        if policy.get("require_same_origin_as_before") is True:
            if not isinstance(before, dict) or before.get("status") != "ok":
                return {"verified": False, "reason": "navigation_probe_unavailable", "samples": samples}
            if _origin(sample.get("url")) != _origin(before.get("url")):
                return {"verified": False, "reason": "unexpected_origin", "samples": samples, "after": sample}
        if policy.get("expected_origin") and _origin(sample.get("url")) != _origin(policy.get("expected_origin")):
            return {"verified": False, "reason": "unexpected_origin", "samples": samples, "after": sample}
        if policy.get("forbid_new_tab") is True and isinstance(before, dict):
            old = set(before.get("tab_ids") or [])
            new = set(sample.get("tab_ids") or [])
            stable_identity_changed = bool(
                old
                and new != old
                and before.get("tab_identity_source") == "uia_runtime_id"
                and sample.get("tab_identity_source") == "uia_runtime_id"
            )
            if (
                before.get("tab_count") is None
                or sample.get("tab_count") is None
                or int(sample.get("tab_count")) != int(before.get("tab_count"))
                or stable_identity_changed
            ):
                return {"verified": False, "reason": "unexpected_new_tab", "samples": samples, "after": sample}
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    return {"verified": True, "samples": samples, "after": samples[-1]}


def probe_bound_browser(hwnd: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "unavailable",
        "url": None,
        "tab_count": None,
        "tab_ids": [],
        "tab_identity_source": "unavailable",
    }
    try:
        from pywinauto import Desktop  # type: ignore
        windows = Desktop(backend="uia").windows(handle=int(hwnd))
        if not windows:
            result["reason"] = "bound_hwnd_not_found"
            return result
        window = windows[0]
        tabs = window.descendants(control_type="TabItem")
        result["tab_count"] = len(tabs)
        ids = []
        all_runtime_ids = bool(tabs)
        for tab in tabs:
            info = getattr(tab, "element_info", None)
            try:
                runtime_id = getattr(info, "runtime_id", None) if info is not None else None
                identity = runtime_id() if callable(runtime_id) else runtime_id
            except Exception:
                identity = None
            if identity:
                ids.append(str(tuple(identity)) if isinstance(identity, (list, tuple)) else str(identity))
            else:
                all_runtime_ids = False
                ids.append(str(getattr(info, "name", None) or tab.window_text()))
        result["tab_ids"] = ids
        result["tab_identity_source"] = "uia_runtime_id" if all_runtime_ids else "title_fallback"
        for edit in window.descendants(control_type="Edit"):
            value = edit.get_value() if hasattr(edit, "get_value") else edit.window_text()
            if str(value or "").strip().startswith(("http://", "https://")):
                result.update(status="ok", url=str(value).strip())
                return result
    except Exception as exc:
        result["reason"] = "windows_uia_url_read_failed"
        result["error"] = str(exc)
    return result
