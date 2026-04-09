from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Optional


@dataclass
class NormalizedRect:
    coord_space: str
    nx: float
    ny: float
    nw: float
    nh: float


@dataclass
class PageFingerprint:
    image_hash: Optional[str] = None
    thumbnail_hash: Optional[str] = None
    anchor_patch_paths: list[str] = field(default_factory=list)
    stable_regions: list[dict[str, Any]] = field(default_factory=list)
    notes: Optional[str] = None
    version: int = 1


@dataclass
class AppState:
    state_id: str
    app_name: str
    state_name: str
    window_size_bucket: str
    fingerprint: PageFingerprint
    panel_profiles: list[dict[str, Any]] = field(default_factory=list)
    known_action_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return _to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AppState":
        payload = dict(payload)
        payload["fingerprint"] = PageFingerprint(**payload.get("fingerprint", {}))
        return cls(**payload)


def _to_json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _to_json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_to_json_safe(v) for v in value]
    return value
