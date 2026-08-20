from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class TransitionRecord:
    transition_id: str
    from_state_id: str
    action_id: str
    to_state_id: Optional[str]
    success_type: str
    confidence: float
    evidence: dict[str, Any]
    side_effects: list[str] = field(default_factory=list)
    case_path: Optional[str] = None
    timestamp: Optional[str] = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TransitionRecord":
        return cls(**payload)
