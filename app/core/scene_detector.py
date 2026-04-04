from __future__ import annotations

from typing import Any

from loguru import logger


class SceneDetector:
    """Resolve high-level scene names from the current bound window state.

    TODO:
    - Load scene definitions from configs/scenes.
    - Implement scene matching using templates and OCR signals.
    """

    def detect_scene(self) -> dict[str, Any]:
        """Return the currently detected scene summary."""
        logger.info("Detecting current scene")
        return {
            "scene_name": None,
            "confidence": 0.0,
        }

    def wait_for_scene(self, scene_name: str, timeout: float) -> dict[str, Any]:
        """Wait until the requested scene is detected or timeout occurs."""
        logger.info("Waiting for scene: scene_name={}, timeout={}", scene_name, timeout)
        return {
            "scene_name": scene_name,
            "matched": False,
            "elapsed_seconds": timeout,
        }


scene_detector = SceneDetector()
