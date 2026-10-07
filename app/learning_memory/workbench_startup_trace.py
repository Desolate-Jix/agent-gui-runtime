"""可选启动边界日志；旁观 Qt 事件，不改变接受、关闭或退出策略。"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QWidget


class TraceWriteError(RuntimeError):
    """诊断证据无法完整保存，启动不得报告成功。"""


class StartupTrace(QObject):
    def __init__(self, application, path):
        super().__init__()
        destination = Path(path)
        if not destination.is_absolute():
            raise TraceWriteError("startup trace requires an absolute new file")
        try:
            self._stream = destination.open("x", encoding="utf-8", newline="\n")
        except OSError as error:
            raise TraceWriteError("cannot create startup trace: " + str(error)) from error
        self._application = application
        self._attached = False
        self._closed = False
        self._failure = None
        self._sequence = 0
        self.exit_code = 0

    def record(self, event, **fields):
        if self._failure is not None:
            raise self._failure
        if self._closed:
            raise TraceWriteError("startup trace is closed")
        value = {"schema": "workbench_startup_trace.v1", "sequence": self._sequence,
                 "at": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        try:
            self._stream.write(json.dumps(value, ensure_ascii=False) + "\n")
            self._stream.flush()
        except (OSError, ValueError) as error:
            self._failure = TraceWriteError("startup trace write failed: " + str(error))
            self._failure.__cause__ = error
            raise self._failure
        self._sequence += 1

    def _observe(self, event, **fields):
        try:
            self.record(event, **fields)
        except TraceWriteError:
            # Qt 回调不能强制退出；首个失败由下一同步边界或关闭合同明确抛出。
            pass

    def _last_window_closed(self):
        self._observe("last_window_closed")

    def _about_to_quit(self):
        self._observe("about_to_quit")

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self._application and kind == QEvent.Type.Quit:
            self._observe("qt_quit")
        elif kind in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Close):
            top_level = ((isinstance(watched, QWidget) and watched.isWindow())
                         or (isinstance(watched, QWindow) and watched.isTopLevel()))
            if top_level:
                self._observe("top_level_" + kind.name.lower(),
                    object_type=type(watched).__name__, object_name=watched.objectName(),
                    visible=watched.isVisible())
        return False

    def __enter__(self):
        try:
            self.record("launcher_start")
        except TraceWriteError:
            # context 入口失败不会自动调用退出钩子，仍须关掉已创建的日志流。
            self.close()
            raise
        self._application.installEventFilter(self)
        self._application._workbench_startup_trace = self
        self._application.lastWindowClosed.connect(self._last_window_closed)
        self._application.aboutToQuit.connect(self._about_to_quit)
        self._attached = True
        return self

    def close(self):
        if self._attached:
            if getattr(self._application, '_workbench_startup_trace', None) is self:
                del self._application._workbench_startup_trace
            self._application.removeEventFilter(self)
            self._application.lastWindowClosed.disconnect(self._last_window_closed)
            self._application.aboutToQuit.disconnect(self._about_to_quit)
            self._attached = False
        if not self._closed:
            try:
                self._stream.close()
            except (OSError, ValueError) as error:
                if self._failure is None:
                    self._failure = TraceWriteError("startup trace close failed: " + str(error))
                    self._failure.__cause__ = error
            finally:
                self._closed = True
        if self._failure is not None:
            raise self._failure

    def __exit__(self, exception_type, exception, traceback):
        try:
            if exception is not None:
                self.record("startup_error", error_type=exception_type.__name__)
            self.record("launcher_exit", exit_code=2 if exception is not None else self.exit_code)
        except TraceWriteError:
            # 首个日志异常已经持久保存在对象内；关闭必定重抛，不能改记成功。
            pass
        finally:
            try:
                self.close()
            except TraceWriteError as failure:
                if exception is not None:
                    raise failure from exception
                raise
        return False
