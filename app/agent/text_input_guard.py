"""本地文本字段读取与粘贴间的不可变门卫。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .text_field_evidence import (
    TextFieldExpectation,
    TextFieldSnapshot,
    validate_text_field_precondition,
)


@dataclass(frozen=True, slots=True)
class TextInputGuard:
    """将已审核的字段快照绑定到单次键盘输入的关键时点。"""

    expectation: TextFieldExpectation = field(repr=False)
    read_current: Callable[[], TextFieldSnapshot] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.expectation) is not TextFieldExpectation or not callable(self.read_current):
            raise ValueError("text input guard requires immutable expectation and local reader")

    def validate_command(
        self,
        *,
        text: str,
        clear_existing: bool,
        window_handle: int,
        click_point: tuple[int | float, int | float],
    ) -> None:
        parameters = self.expectation.parameters
        identity = self.expectation.before.identity
        if (
            text != parameters.text
            or clear_existing is not parameters.reviewed.clear_existing
            or window_handle != identity.window_handle
            or not self._contains_point(click_point)
        ):
            raise ValueError("text field precondition changed or is unavailable")

    def verify_before_selection(self) -> None:
        self._validate_current()

    def verify_before_paste(self) -> None:
        current = self._read_current()
        try:
            validate_text_field_precondition(self.expectation, current)
        except Exception:
            raise ValueError("text field precondition changed or is unavailable") from None
        # 当前同字段值经复读确认为空时没有待替换字符；选区仍保留未知，不伪造全选证据。
        if self.expectation.parameters.reviewed.clear_existing and current.value != "":
            if current.selection != (0, len(current.value)):
                raise ValueError("text field precondition changed or is unavailable")

    def _validate_current(self) -> None:
        current = self._read_current()
        try:
            validate_text_field_precondition(self.expectation, current)
        except Exception:
            raise ValueError("text field precondition changed or is unavailable") from None

    def _read_current(self) -> TextFieldSnapshot:
        try:
            current = self.read_current()
        except Exception:
            raise ValueError("text field precondition changed or is unavailable") from None
        if type(current) is not TextFieldSnapshot:
            raise ValueError("text field precondition changed or is unavailable")
        return current

    def _contains_point(self, point: tuple[int | float, int | float]) -> bool:
        if type(point) is not tuple or len(point) != 2:
            return False
        try:
            x, y = point
            left, top, width, height = self.expectation.before.identity.control_bbox
            return left <= x < left + width and top <= y < top + height
        except Exception:
            return False


__all__ = ["TextInputGuard"]
