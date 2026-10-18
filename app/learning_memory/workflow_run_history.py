"""只读展示原运行的逐步结果及局部计量。"""
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem
from .workbench_i18n import tr, ui, bind_text


_VERDICTS = {"success": "通过", "failure": "未通过", "uncertain": "不确定"}
_SOURCES = {"rule": "规则核验", "agent": "Agent 判断", "runtime": "运行时结算"}
_PENDING = {"verification_required": "等待核验", "grounding_required": "等待定位",
            "result_unknown": "结果未知", "queue_busy": "等待入队"}


class WorkflowRunHistory(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        # 保留表头的 Python 包装对象，避免弱引用文案绑定随包装对象回收。
        self._header_items = tuple(QTableWidgetItem() for _ in range(5))
        for index, item in enumerate(self._header_items):
            self.setHorizontalHeaderItem(index, item)
        ui(self.setHorizontalHeaderLabels, [tr("步骤"), tr("结果"), tr("核验方式"), tr("已观测时长"), tr("已记录模型调用")])
        ui(self.setAccessibleName, tr("本次运行的步骤结果"))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.setMinimumHeight(170)
        ui(self.setToolTip, tr("结果来自本次原步骤账本。时长只包含已记录阶段；模型调用总量与 token 可能未知。"))

    def show_snapshot(self, snapshot, titles):
        history = snapshot.get("history")
        rows = [(entry, False) for entry in history if isinstance(entry, dict)] if isinstance(history, list) else []
        pending = snapshot.get("pending")
        if isinstance(pending, dict):
            rows.append((pending, True))
        metrics = snapshot.get("metrics")
        by_step = metrics.get("by_step", {}) if isinstance(metrics, dict) and metrics.get("status") != "unavailable" else {}
        if not isinstance(by_step, dict):
            by_step = {}
        self.setRowCount(len(rows))
        for index, (entry, is_pending) in enumerate(rows):
            step_id = entry.get("step_id")
            title = titles.get(step_id, tr("第 {index} 步", index=index + 1))
            verdict = tr(_PENDING.get(snapshot.get("wait_reason"), "等待原回执") if is_pending
                       else _VERDICTS.get(entry.get("verdict"), "结果未知"))
            if is_pending and snapshot.get("status") == "cancel_requested":
                verdict = tr("取消处理中")
            if not is_pending and entry.get("cancel_reason"):
                verdict = tr("已取消并结算")
            source = tr("尚未结算") if is_pending else tr(_SOURCES.get(entry.get("judged_by"), "来源未记录"))
            duration, calls = tr("未知"), tr("未知")
            observed = by_step.get(step_id)
            if isinstance(observed, dict) and type(observed.get("event_count")) is int and observed["event_count"] > 0:
                elapsed = observed.get("elapsed_ns")
                if type(elapsed) is int and elapsed >= 0:
                    duration = tr("{seconds:.3f} 秒", seconds=elapsed / 1_000_000_000)
                model_calls = observed.get("model_calls")
                count = model_calls.get("total") if isinstance(model_calls, dict) else None
                if type(count) is int and count >= 0:
                    calls = tr("{count} 次；总量未知", count=count)
            for column, text in enumerate((title, verdict, source, duration, calls)):
                item = QTableWidgetItem(text)
                if column != 0 or hasattr(text, "render"):
                    bind_text(item, "setText", text)
                if column == 0:
                    ui(item.setToolTip, tr("步骤：{step}\n原执行请求：{request}", step=step_id, request=entry.get('execution_request_id', tr('未记录'))))
                elif column == 3:
                    ui(item.setToolTip, tr("仅统计本步骤有证据的时段，包括等待；不是完整步骤用时或模型推理时长。"))
                elif column == 4:
                    ui(item.setToolTip, tr("只计已记录的实际调用；审核/定位交接次数不等于模型调用。完整总量与 token 仍可能未知。"))
                self.setItem(index, column, item)
        self.resizeRowsToContents()
