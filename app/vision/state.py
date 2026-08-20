from __future__ import annotations

from dataclasses import dataclass, field
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
