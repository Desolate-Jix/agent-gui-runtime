"""启动参数的排版控制符校验与可比较显示。"""
import json
import unicodedata
from typing import Any

_DISPLAY_CONTROLS = {"Cc", "Cf", "Zl", "Zp", "Cs"}


def has_launch_display_controls(value: str) -> bool:
    return any(unicodedata.category(char) in _DISPLAY_CONTROLS for char in value)


def launch_display_json(value: Any, *, indent: int | None = None) -> str:
    # JSON 已转义字符串内的换行；保留缩进换行，其余不可见排版符显式展示。
    serialized = json.dumps(value, ensure_ascii=False, indent=indent, allow_nan=False)
    return "".join(
        (f"\\u{ord(char):04x}" if ord(char) <= 0xffff else f"\\U{ord(char):08x}")
        if char != "\n" and unicodedata.category(char) in _DISPLAY_CONTROLS else char
        for char in serialized
    )


def launch_display_text(value: str) -> str:
    return launch_display_json(value)[1:-1]
