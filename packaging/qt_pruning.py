"""PyInstaller 输入的 QtWebEngine 精确剔除规则；不触碰 Widgets 必需插件。"""
from __future__ import annotations

from typing import Iterable, TypeVar


Entry = TypeVar("Entry", bound=tuple)

# 目录和 DLL/模块名称均来自 2026-09-13 formal 环境的只读清单。
_WEBENGINE_MARKER = "webengine"
_WEBENGINE_SHARED_RESOURCES = {"icudtl.dat", "v8_context_snapshot.bin"}


def _pyside6_tail(value: str) -> tuple[str, ...]:
    """返回路径中 PySide6 包根后的部分，避免按任意父目录名误删。"""
    parts = tuple(part for part in value.replace("\\", "/").casefold().split("/") if part)
    matches = [index for index, part in enumerate(parts) if part == "pyside6"]
    return parts[matches[-1] + 1:] if matches else ()


def is_qt_webengine_entry(entry: tuple) -> bool:
    """仅匹配 PySide6 自己的 QtWebEngine 文件及其专用 Chromium 资源。"""
    if not isinstance(entry, tuple) or not entry:
        raise TypeError("PyInstaller entry must be a non-empty tuple")
    values = [value for value in entry if isinstance(value, str)]
    if not values:
        raise TypeError("PyInstaller entry must include a path")
    tails = [_pyside6_tail(value) for value in values]
    if any(any(_WEBENGINE_MARKER in part for part in tail) for tail in tails):
        return True
    return any(
        len(tail) >= 2 and tail[-2] == "resources" and tail[-1] in _WEBENGINE_SHARED_RESOURCES
        for tail in tails
    )


def prune_qt_webengine(entries: Iterable[Entry]) -> list[Entry]:
    """保留条目形状和排序，只从 Analysis/COLLECT 输入排除已证明的 WebEngine 负载。"""
    return [entry for entry in entries if not is_qt_webengine_entry(entry)]
