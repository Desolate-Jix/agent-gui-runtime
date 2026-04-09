from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from app.core.state_memory import state_memory
from app.schemas.state import AppState
from app.vision.page_fingerprint import build_page_fingerprint


@dataclass
class StateRecognitionResult:
    matched: bool
    state_id: Optional[str]
    confidence: float
    reason: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "state_id": self.state_id,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class StateRecognizer:
    def recognize(self, image_path: str, window_size_bucket: str) -> StateRecognitionResult:
        candidates = [state for state in state_memory.list_states() if state.window_size_bucket == window_size_bucket]
        if not candidates:
            return StateRecognitionResult(False, None, 0.0, {"bucket_match": False})

        fingerprint = build_page_fingerprint(image_path)
        best_state: Optional[AppState] = None
        best_score = -1.0
        best_reason: dict[str, Any] = {}

        for state in candidates:
            score = 0.0
            reason: dict[str, Any] = {"bucket_match": True, "thumbnail_match": False, "anchor_patch_hits": 0}
            if state.fingerprint.thumbnail_hash and state.fingerprint.thumbnail_hash == fingerprint.thumbnail_hash:
                score += 0.7
                reason["thumbnail_match"] = True
            patch_hits = self._count_patch_hits(image_path, state)
            if patch_hits > 0:
                score += min(0.3, patch_hits * 0.15)
            reason["anchor_patch_hits"] = patch_hits
            if score > best_score:
                best_score = score
                best_state = state
                best_reason = reason

        if best_state is None or best_score < 0.7:
            return StateRecognitionResult(False, None, max(best_score, 0.0), best_reason or {"bucket_match": True})
        return StateRecognitionResult(True, best_state.state_id, best_score, best_reason)

    def _count_patch_hits(self, image_path: str, state: AppState) -> int:
        if not state.fingerprint.anchor_patch_paths or not state.fingerprint.stable_regions:
            return 0
        image = Image.open(image_path)
        hits = 0
        for patch_path, region in zip(state.fingerprint.anchor_patch_paths, state.fingerprint.stable_regions):
            patch_file = Path(patch_path)
            if not patch_file.exists():
                continue
            nx = float(region.get("nx", 0.0))
            ny = float(region.get("ny", 0.0))
            nw = float(region.get("nw", 0.0))
            nh = float(region.get("nh", 0.0))
            x = max(0, int(image.width * nx))
            y = max(0, int(image.height * ny))
            w = max(1, int(image.width * nw))
            h = max(1, int(image.height * nh))
            crop = image.crop((x, y, min(image.width, x + w), min(image.height, y + h)))
            patch = Image.open(patch_file)
            if crop.size == patch.size and crop.tobytes() == patch.tobytes():
                hits += 1
        return hits


state_recognizer = StateRecognizer()
