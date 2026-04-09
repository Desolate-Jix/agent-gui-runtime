from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ValidatorProfile:
    validator_profile_id: str
    target_name: str
    target_roi: Optional[dict[str, Any]] = None
    ocr_roi: Optional[dict[str, Any]] = None
    roi_diff_threshold: Optional[float] = None
    strict_rule: Optional[dict[str, Any]] = None
    weak_rule: Optional[dict[str, Any]] = None
    bad_click_signals: list[dict[str, Any]] = field(default_factory=list)
    notes: Optional[str] = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ValidatorProfile":
        return cls(**payload)
