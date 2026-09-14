"""独立非激活浮窗的不可变点击绑定；不产生或签发输入权限。"""
from dataclasses import dataclass, field
import math
from typing import Callable


@dataclass(frozen=True, slots=True)
class PopupTargetSnapshot:
    parent_handle: int
    popup_handle: int
    process_id: int
    process_create_time: float
    executable_path: str
    thread_id: int
    parent_rect: tuple[int, int, int, int]
    popup_rect: tuple[int, int, int, int]
    combo_name: str
    item_name: str
    combo_runtime_id: tuple[int, ...]
    item_runtime_id: tuple[int, ...]
    item_bbox: tuple[int, int, int, int]
    click_point: tuple[int, int]

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in
               (self.parent_handle, self.popup_handle, self.process_id, self.thread_id)):
            raise ValueError('popup requires exact native identities')
        if self.parent_handle == self.popup_handle:
            raise ValueError('popup and foreground parent must be distinct')
        if (type(self.process_create_time) not in (int, float)
                or not math.isfinite(self.process_create_time) or self.process_create_time <= 0):
            raise ValueError('popup requires process birth identity')
        for value in (self.executable_path, self.combo_name, self.item_name):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('popup requires exact executable, combo and item names')
        for rect in (self.parent_rect, self.popup_rect):
            if (type(rect) is not tuple or len(rect) != 4 or any(type(v) is not int for v in rect)
                    or rect[2] <= rect[0] or rect[3] <= rect[1]):
                raise ValueError('invalid native popup or parent rectangle')
        for identity in (self.combo_runtime_id, self.item_runtime_id):
            if type(identity) is not tuple or not identity or any(type(v) is not int for v in identity):
                raise ValueError('popup requires live UIA runtime identities')
        if (type(self.item_bbox) is not tuple or len(self.item_bbox) != 4
                or type(self.click_point) is not tuple or len(self.click_point) != 2
                or any(type(v) is not int for v in (*self.item_bbox, *self.click_point))):
            raise ValueError('invalid popup item geometry')
        x, y, w, h = self.item_bbox
        px, py = self.click_point
        left, top, right, bottom = self.popup_rect
        if (w <= 0 or h <= 0 or (px, py) != (x + w // 2, y + h // 2)
                or not (0 <= x <= px < x + w <= right - left and 0 <= y <= py < y + h <= bottom - top)):
            raise ValueError('only the exact popup item center is permitted')


@dataclass(frozen=True, slots=True)
class PopupClickGuard:
    expectation: PopupTargetSnapshot
    read_current: Callable[[], PopupTargetSnapshot] = field(repr=False)

    def __post_init__(self):
        if type(self.expectation) is not PopupTargetSnapshot or not callable(self.read_current):
            raise ValueError('popup guard requires an immutable snapshot and live reader')

    def validate_command(self, *, window_handle, click_point):
        if (type(window_handle) is not int or window_handle != self.expectation.popup_handle
                or type(click_point) is not tuple or click_point != self.expectation.click_point
                or any(type(v) is not int for v in click_point)):
            raise ValueError('popup command does not match reviewed target')

    def verify_current(self):
        try:
            current = self.read_current()
        except Exception as error:
            raise ValueError('popup relationship could not be revalidated') from error
        if type(current) is not PopupTargetSnapshot or current != self.expectation:
            raise ValueError('popup relationship or target changed before input')
