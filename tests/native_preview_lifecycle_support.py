"""实机测试的过期提示：不延长权限，不关窗，不中断已经开始的操作。"""
from datetime import datetime, timezone
import math

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QLabel


class PreviewExpiryNotice(QObject):
    def __init__(self, dialog, expires_at, *, clock=lambda: datetime.now(timezone.utc)):
        super().__init__(dialog)
        self.dialog, self.expires_at, self.clock = dialog, expires_at, clock
        self.cleanup_requested = False
        self.state = "active"
        self.label = QLabel(dialog)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setAccessibleName("测试预览倒计时与过期说明")
        dialog.layout().insertWidget(2, self.label)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        dialog.finished.connect(self.timer.stop)
        self.timer.start()
        self.tick()

    def tick(self):
        remaining = math.ceil((self.expires_at - self.clock()).total_seconds())
        if remaining > 0:
            self.label.setText(f"动作预览剩余 {remaining // 60:02d}:{remaining % 60:02d} · 到期不会自动关窗。")
            return
        dialog = self.dialog
        dialog._tick()
        if dialog._jobs:
            self.state = "expired_waiting_job"
            self.label.setText("预览有效期已结束，等待当前操作返回；不强行中断、不自动重试，窗口保留。")
        elif self.cleanup_requested and dialog._has_owner:
            self.state = "expired_release_failed"
            self.label.setText("本次预览已过期，资源释放未完成；请查看错误并手动处理。不会自动重试或关窗。")
        elif dialog._phase in {"completed", "recovery_required"}:
            self.state = "expired_retaining_result"
            self.label.setText("本次操作已返回或需要核验，请查看回执和状态；不会自动关窗，旧预览不能重用。")
        elif not self.cleanup_requested and dialog._has_owner:
            self.cleanup_requested = True
            self.state = "expired_releasing"
            self.label.setText("本次预览已过期，正在释放本轮运行资源；窗口将保留，不会自动重试。")
            dialog._cancel()
        elif not dialog._has_owner:
            self.state = "expired_released"
            self.label.setText("本次预览已过期，运行资源已释放。窗口保留供你查看；请手动关闭，下次需生成新预览。")

    def snapshot(self):
        return {"state": self.state, "cleanup_requested": self.cleanup_requested,
                "expires_at": self.expires_at.isoformat(), "auto_close": False}
