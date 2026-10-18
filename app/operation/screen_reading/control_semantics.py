"""公共 UIA 控件事实采集；不是动作分类器或执行授权。"""
from __future__ import annotations
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


def collect_control_semantics(wrapper: Any, bound: Any, *, max_ancestry: int = 12) -> dict[str, Any]:
    if type(max_ancestry) is not int or not 1 <= max_ancestry <= 12:
        raise ValueError("max_ancestry must be an integer between 1 and 12")
    errors: list[str] = []
    expected = _identity(bound, errors, "bound")
    if expected is None:
        raise ValueError("bound HWND and PID must be positive integers")
    control = _node_facts(wrapper, errors)
    ancestry: list[dict[str, Any]] = []
    current = wrapper
    seen = {id(wrapper)}
    complete = _identity(current, errors, "control") == expected
    for _ in range(max_ancestry):
        if complete:
            break
        parent = _read(current, "parent", errors, "parent", call=True)
        if parent is None:
            break
        if id(parent) in seen:
            errors.append("ancestry_cycle")
            break
        seen.add(id(parent))
        ancestry.append(_node_facts(parent, errors))
        complete = _identity(parent, errors, "ancestor") == expected
        if complete:
            break
        current = parent
    else:
        errors.append("ancestry_limit_exceeded")
    if not complete:
        errors.append("bound_ancestor_not_reached")
    return {
        "contract_version": "facts_v1", "control": control, "ancestry": ancestry,
        "navigation": _navigation(wrapper, control, complete, errors),
        # complete 只证明父链到达指定窗口，不证明控件事实齐全或点击安全。
        "complete": complete, "errors": list(dict.fromkeys(errors)),
    }


def _node_facts(wrapper: Any, errors: list[str]) -> dict[str, Any]:
    info = _read(wrapper, "element_info", errors, "element_info")
    element = _read(info, "element", errors, "uia_element")
    aria = _text(_read(element, "CurrentAriaProperties", errors, "aria_properties"))
    window = _read(wrapper, "iface_window", errors, "window_pattern")
    legacy = _read(wrapper, "iface_legacy_iaccessible", errors, "legacy_pattern")
    return {
        # pywinauto 已把数字 CurrentControlType 转换为公共控件类型名称。
        "control_type": _text(_read(info, "control_type", errors, "control_type")),
        "aria_role": _text(_read(element, "CurrentAriaRole", errors, "aria_role")),
        "haspopup": _popup(aria, errors),
        "modal": _boolean(_read(window, "CurrentIsModal", errors, "modal")),
        "is_password": _boolean(_read(element, "CurrentIsPassword", errors, "is_password")),
        "help_text": _text(_read(element, "CurrentHelpText", errors, "help_text")),
        "default_action": _text(_read(legacy, "CurrentDefaultAction", errors, "default_action")),
    }


def _navigation(wrapper: Any, control: dict[str, Any], bound_verified: bool,
                errors: list[str]) -> dict[str, Any]:
    result = {"destination": None, "available": False,
              "source": "uia_legacy_value", "observation_only": True}
    # 不读取 Edit、密码或父链未核验的目标；未知密码状态也不读取。
    if (not bound_verified or control["control_type"] != "Hyperlink"
            or control["is_password"] is not False):
        return result
    legacy = _read(wrapper, "iface_legacy_iaccessible", errors, "legacy_pattern")
    raw = _read(legacy, "CurrentValue", errors, "navigation_value")
    destination = _safe_url(raw)
    if raw and destination is None:
        errors.append("navigation_destination_unresolved")
    return {**result, "destination": destination, "available": destination is not None}


def _identity(value: Any, errors: list[str], scope: str) -> tuple[int, int] | None:
    handle = _read(value, "handle", errors, scope + "_handle", call=True)
    pid = _read(value, "process_id", errors, scope + "_pid", call=True)
    if type(handle) is int and handle > 0 and type(pid) is int and pid > 0:
        return handle, pid
    return None


def _read(value: Any, key: str, errors: list[str], code: str, *, call: bool = False) -> Any:
    try:
        result = value.get(key) if isinstance(value, Mapping) else getattr(value, key, None)
        if call and callable(result):
            result = result()
    except Exception:
        # COM 异常可能包含路径、控件正文或 URL，不写入公共事实。
        errors.append(code + "_error")
        return None
    if result is None:
        errors.append(code + "_unknown")
    return result


def _popup(value: str | None, errors: list[str]) -> bool | str | None:
    if value is None:
        return None
    found = [item.partition("=")[2].strip().casefold() for item in value.split(";")
             if item.partition("=")[0].strip().casefold() == "haspopup"]
    if not found:
        return None
    if len(found) != 1 or found[0] not in {"true", "false", "menu", "listbox", "tree", "grid", "dialog"}:
        errors.append("haspopup_unresolved")
        return None
    return {"true": True, "false": False}.get(found[0], found[0])


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        return None
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname
        if parsed.scheme.lower() not in {"http", "https"} or not host or any(c.isspace() for c in host):
            return None
        port = parsed.port
        if ":" in host:
            host = f"[{host}]"
        netloc = host if port is None else f"{host}:{port}"
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, "", ""))
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _boolean(value: Any) -> bool | None:
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    return None
