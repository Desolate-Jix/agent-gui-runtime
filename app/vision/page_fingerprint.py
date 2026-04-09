from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from PIL import Image

from app.schemas.state import PageFingerprint

PATCHES_DIR = Path("logs/app-states/patches")
PATCHES_DIR.mkdir(parents=True, exist_ok=True)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _thumbnail_hash(image: Image.Image, size: tuple[int, int] = (32, 32)) -> str:
    thumb = image.convert("L").resize(size)
    return _sha256_bytes(thumb.tobytes())


def build_page_fingerprint(
    image_path: str,
    *,
    stable_regions: Optional[list[dict]] = None,
    patch_prefix: str = "state",
) -> PageFingerprint:
    image = Image.open(image_path)
    image_hash = _sha256_bytes(image.tobytes())
    thumbnail_hash = _thumbnail_hash(image)
    patch_paths: list[str] = []
    for index, region in enumerate(stable_regions or []):
        nx = float(region.get("nx", 0.0))
        ny = float(region.get("ny", 0.0))
        nw = float(region.get("nw", 0.0))
        nh = float(region.get("nh", 0.0))
        x = max(0, int(image.width * nx))
        y = max(0, int(image.height * ny))
        w = max(1, int(image.width * nw))
        h = max(1, int(image.height * nh))
        crop = image.crop((x, y, min(image.width, x + w), min(image.height, y + h)))
        patch_path = PATCHES_DIR / f"{patch_prefix}-patch-{index}.png"
        crop.save(patch_path)
        patch_paths.append(str(patch_path))
    return PageFingerprint(
        image_hash=image_hash,
        thumbnail_hash=thumbnail_hash,
        anchor_patch_paths=patch_paths,
        stable_regions=stable_regions or [],
    )
