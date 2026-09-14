from __future__ import annotations

import re
from dataclasses import dataclass


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class RuntimeSessionSelection:
    asset_id: str
    asset_content_sha256: str
    target_window_handle: int
    target_process_id: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.asset_id, str)
            or not self.asset_id
            or self.asset_id != self.asset_id.strip()
            or len(self.asset_id) > 256
        ):
            raise ValueError("runtime session asset_id is invalid")
        if (
            not isinstance(self.asset_content_sha256, str)
            or _SHA256_PATTERN.fullmatch(self.asset_content_sha256) is None
        ):
            raise ValueError("runtime session asset hash is invalid")
        for label, value in (
            ("target_window_handle", self.target_window_handle),
            ("target_process_id", self.target_process_id),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"runtime session {label} is invalid")
