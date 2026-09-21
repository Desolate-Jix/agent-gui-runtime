"""共享编辑键契约；导入时不初始化桌面或 COM。"""
from types import MappingProxyType
from typing import Literal

EditingKey = Literal[
    "Enter", "Tab", "Shift+Tab", "Escape", "Backspace", "Delete",
    "Left", "Right", "Up", "Down", "Home", "End", "Ctrl+A", "Ctrl+Z", "Ctrl+Y",
    "Shift+Left", "Shift+Right", "Shift+Up", "Shift+Down", "Shift+Home", "Shift+End",
    "Ctrl+Home", "Ctrl+End",
]

EDITING_KEY_CHORDS = MappingProxyType({
    "Enter": (0x0D,), "Tab": (0x09,), "Shift+Tab": (0x10, 0x09),
    "Escape": (0x1B,), "Backspace": (0x08,), "Delete": (0x2E,),
    "Left": (0x25,), "Right": (0x27,), "Up": (0x26,), "Down": (0x28,),
    "Home": (0x24,), "End": (0x23,), "Ctrl+A": (0x11, 0x41),
    "Ctrl+Z": (0x11, 0x5A), "Ctrl+Y": (0x11, 0x59),
    "Shift+Left": (0x10, 0x25), "Shift+Right": (0x10, 0x27),
    "Shift+Up": (0x10, 0x26), "Shift+Down": (0x10, 0x28),
    "Shift+Home": (0x10, 0x24), "Shift+End": (0x10, 0x23),
    "Ctrl+Home": (0x11, 0x24), "Ctrl+End": (0x11, 0x23),
})

# 导航区按键不同于小键盘同名键，需要扩展位。
EXTENDED_EDITING_KEYS = frozenset({0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E})
