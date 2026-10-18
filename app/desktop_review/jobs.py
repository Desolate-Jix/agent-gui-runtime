"""轻量 QThread 包装，避免持久化占用 Qt 事件线程。"""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal


class FacadeJob(QThread):
    succeeded = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, request_id: int, operation: Callable[[], dict[str, Any]], parent: Any = None) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self._operation = operation

    def run(self) -> None:
        try:
            self.succeeded.emit(self.request_id, self._operation())
        except Exception as error:  # 异常转回 UI 线程展示，不丢失草稿。
            self.failed.emit(self.request_id, f"{error}\n{traceback.format_exc(limit=2)}")


def make_job(request_id: int, operation: Callable[[], dict[str, Any]], parent: Any) -> FacadeJob:
    """只构造任务；调用方必须先连接信号和登记，再显式启动。"""
    return FacadeJob(request_id, operation, parent)
