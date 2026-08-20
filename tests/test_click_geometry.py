from __future__ import annotations

from dataclasses import dataclass

import pytest

from modules.click.geometry import resolve_window_and_screen_point


@dataclass
class _Rect:
    left: int
    top: int
    right: int
    bottom: int


@dataclass
class _Bound:
    rect: _Rect


def test_resolve_window_and_screen_point_returns_both_coordinate_spaces() -> None:
    bound = _Bound(rect=_Rect(left=100, top=200, right=500, bottom=700))
    result = resolve_window_and_screen_point(bound=bound, x=20, y=30)
    assert result == {"window_x": 20, "window_y": 30, "screen_x": 120, "screen_y": 230}


def test_resolve_window_and_screen_point_rejects_out_of_bounds() -> None:
    bound = _Bound(rect=_Rect(left=0, top=0, right=100, bottom=100))
    with pytest.raises(ValueError):
        resolve_window_and_screen_point(bound=bound, x=100, y=50)
