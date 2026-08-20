from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


APPLICATION_IDENTITY_CONTRACT = "application_identity_v1"
_BROWSER_EXECUTABLES = {
    "brave.exe",
    "chrome.exe",
    "firefox.exe",
    "iexplore.exe",
    "msedge.exe",
    "opera.exe",
}


def normalize_application_identity(value: dict[str, Any] | None) -> dict[str, Any]:
    """把窗口线索规范为稳定的软件或网站身份。"""

    source = value if isinstance(value, dict) else {}
    name = _text(source.get("display_name") or source.get("name"))
    process = _normalize_executable(
        source.get("executable_identity")
        or source.get("process")
        or source.get("executable")
    )
    product_name = _text(
        source.get("product")
        or source.get("product_name")
        or source.get("app_name")
        or name
    )
    url_value = _text(
        source.get("url")
        or source.get("origin")
        or source.get("canonical_origin")
        or source.get("domain")
        or source.get("canonical_domain")
    )
    explicit_kind = _text(source.get("kind")).lower()
    is_browser = (
        explicit_kind == "web"
        or process in _BROWSER_EXECUTABLES
        or bool(_canonical_web_location(url_value)[0])
    )

    if is_browser:
        domain, origin = _canonical_web_location(url_value)
        identity_key = f"web:{domain}" if domain else None
        return {
            "contract_version": APPLICATION_IDENTITY_CONTRACT,
            "identity_schema_version": 1,
            "kind": "web",
            "identity_key": identity_key,
            "identity_status": "resolved" if identity_key else "needs_domain_review",
            "name": name or domain or "Browser site",
            "display_name": name or domain or "Browser site",
            "canonical_domain": domain,
            "canonical_origin": origin,
            "executable_identity": process or None,
            "product_identity": None,
            "source_evidence": {
                "url_or_domain_provided": bool(url_value),
                "browser_process_detected": process in _BROWSER_EXECUTABLES,
            },
            "artifact_is_authorization": False,
        }

    product_identity = _slug(product_name)
    executable_identity = process or None
    identity_parts = [part for part in (executable_identity, product_identity) if part]
    identity_key = f"native:{':'.join(identity_parts)}" if identity_parts else None
    return {
        "contract_version": APPLICATION_IDENTITY_CONTRACT,
        "identity_schema_version": 1,
        "kind": "native",
        "identity_key": identity_key,
        "identity_status": "resolved" if identity_key else "needs_application_review",
        "name": name or product_name or "Windows application",
        "display_name": name or product_name or "Windows application",
        "canonical_domain": None,
        "canonical_origin": None,
        "executable_identity": executable_identity,
        "product_identity": product_identity or None,
        "source_evidence": {
            "executable_provided": bool(process),
            "product_provided": bool(product_name),
        },
        "artifact_is_authorization": False,
    }


def _canonical_web_location(raw_value: str) -> tuple[str | None, str | None]:
    text = _text(raw_value)
    if not text:
        return None, None
    candidate = text if "://" in text else f"https://{text}"
    parsed = urlparse(candidate)
    hostname = _text(parsed.hostname).lower().rstrip(".")
    if not hostname:
        return None, None
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return None, None
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = parsed.port
    host_with_port = (
        f"{hostname}:{port}"
        if port and not (parsed.scheme == "https" and port == 443) and not (parsed.scheme == "http" and port == 80)
        else hostname
    )
    scheme = parsed.scheme.lower() if parsed.scheme.lower() in {"http", "https"} else "https"
    return host_with_port, f"{scheme}://{host_with_port}"


def _normalize_executable(value: Any) -> str:
    text = _text(value).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return text


def _slug(value: Any) -> str:
    text = _text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def _text(value: Any) -> str:
    return str(value or "").strip()
