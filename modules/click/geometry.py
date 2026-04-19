from __future__ import annotations

from typing import Any


def resolve_window_and_screen_point(*, bound: Any, x: int, y: int) -> dict[str, int]:
    """Resolve a point from bound-window coordinates into screen coordinates."""
    window_width = max(1, int(bound.rect.right) - int(bound.rect.left))
    window_height = max(1, int(bound.rect.bottom) - int(bound.rect.top))
    if x < 0 or y < 0 or x >= window_width or y >= window_height:
        raise ValueError(
            f"Click point is outside the bound window: point=({x}, {y}), "
            f"window_size=({window_width}, {window_height})"
        )

    screen_x = int(bound.rect.left + x)
    screen_y = int(bound.rect.top + y)
    return {
        "window_x": int(x),
        "window_y": int(y),
        "screen_x": screen_x,
        "screen_y": screen_y,
    }
