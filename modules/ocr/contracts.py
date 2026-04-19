from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OCRBoundingBox:
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class OCRTextMatch:
    text: str
    score: float
    bbox: OCRBoundingBox

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "score": float(self.score),
            "bbox": self.bbox.to_dict(),
        }


@dataclass
class OCRResult:
    image_path: str | None
    matches: list[OCRTextMatch] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_path": self.image_path,
            "matches": [match.to_dict() for match in self.matches],
            "metadata": self.metadata,
        }
