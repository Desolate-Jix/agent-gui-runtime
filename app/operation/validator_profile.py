from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ValidatorProfile:
    validator_profile_id: str
    name: Optional[str] = None
    target_name: Optional[str] = None
    target_roi: Optional[dict[str, Any]] = None
    ocr_roi: Optional[dict[str, Any]] = None
    roi_diff_threshold: Optional[float] = None
    strict_rule: Optional[dict[str, Any]] = None
    weak_rule: Optional[dict[str, Any]] = None
    bad_click_signals: list[dict[str, Any]] = field(default_factory=list)
    notes: Optional[str] = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.target_name is None and self.name is not None:
            self.target_name = self.name
        if self.name is None and self.target_name is not None:
            self.name = self.target_name

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ValidatorProfile":
        return cls(**payload)
