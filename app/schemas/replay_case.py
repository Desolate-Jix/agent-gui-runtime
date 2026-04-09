from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class ReplayCase:
    case_id: str
    app_name: str
    state_before_id: Optional[str]
    action_id: str
    click_point: dict[str, Any]
    artifacts_before: dict[str, Any]
    artifacts_after: dict[str, Any]
    validator_result: dict[str, Any]
    state_after_id: Optional[str]
    memory_updates: dict[str, Any]
    timestamp: str
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReplayCase":
        return cls(**payload)
