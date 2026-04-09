from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ActionTarget:
    action_id: str
    state_id: str
    action_name: str
    target_kind: str
    panel_locator_profile: dict[str, Any]
    zone_resolver_profile: dict[str, Any]
    point_strategy_profile: dict[str, Any]
    validator_profile_id: str
    successful_points: list[dict[str, Any]] = field(default_factory=list)
    forbidden_points: list[dict[str, Any]] = field(default_factory=list)
    local_patch_template_path: Optional[str] = None
    notes: Optional[str] = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionTarget":
        return cls(**payload)
