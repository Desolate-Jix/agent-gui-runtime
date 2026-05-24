from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class RuntimeHttpClient:
    """Small stdlib HTTP client for the local FastAPI runtime."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def get(self, path: str, *, timeout: float = 20.0) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Runtime API unreachable: {exc.reason}") from exc

    def post(self, path: str, payload: dict[str, Any], *, timeout: float = 240.0) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Runtime API unreachable: {exc.reason}") from exc
