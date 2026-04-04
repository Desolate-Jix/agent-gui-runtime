from __future__ import annotations

from typing import Any

from loguru import logger


class InputController:
    """Dispatch input actions to the currently bound window.

    TODO:
    - Add foreground and background input backends.
    - Support click, key press, and scroll primitives.
    """

    def click_point(self, x: int, y: int) -> dict[str, Any]:
        """Click a point relative to the bound window."""
        logger.info("Clicking point: x={}, y={}", x, y)
        return {
            "clicked": True,
            "point": {"x": x, "y": y},
        }


input_controller = InputController()
