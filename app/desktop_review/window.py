"""原生 Qt 审核工作区；单步执行只经独立、显式注入的审核入口。"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont, QFontDatabase, QRawFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox, QFormLayout, QSpinBox, QCheckBox,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QPlainTextEdit, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QStatusBar, QTableWidget,
    QTableWidgetItem, QToolBar, QToolButton, QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.agent.scroll_parameters import ReviewedScrollParameters, SCROLL_SEMANTIC_ACTION
from app.agent.text_parameters import ReviewedTextParameters, TEXT_SEMANTIC_ACTION

from .canvas import ReviewCanvas
from .jobs import FacadeJob, make_job
from .exact_dialog import ExactReviewDialog
from .library_dialog import WorkflowLibraryDialog
from .model_setup_dialog import ModelSetupDialog
from .relearn_dialog import RelearnReviewDialog
from .connection_dialog import ConnectionManagerDialog
from .single_step_dialog import SingleStepDialog
from .application_startup_dialog import ApplicationStartupDialog
from .theme import apply_review_theme
from .transitions import SubtleFadeTransition
from .friendly_controls import ReviewHelpDialog
from .content_library import InterfaceContentLibrary


_ROLE_KIND = int(Qt.ItemDataRole.UserRole)
_ROLE_ID = _ROLE_KIND + 1
_ROLE_BATCH = _ROLE_KIND + 2


class ReviewMainWindow(QMainWindow):
    """仅通过冻结的 NativeReviewFacade API 工作的三栏编辑器。"""

    draftChanged = Signal(bool)

    def __init__(self, facade: Any, *, connections=None, shutdown=None, startup=None, single_step=None, application_startup=None) -> None:
        super().__init__()
        self.facade = facade
        self._connections = connections
        self._single_step = single_step
        self._application_startup = application_startup
        self._shutdown = shutdown
        self._startup = startup
        self._host_closed = False
        self._host_job_succeeded = False
        self._host_discard_confirmed = False
        self._workspace: dict[str, Any] | None = None
        self._graph_pane = None
        self._content_page = None
        self._projects_page = None
        self._close_after_project_load = False
        self._delete_after_project_load = False
        self._daily_section = "new"
        self._last_open_graph_id: str | None = None
        self._last_open_graph_source: tuple[str, str] | None = None
        self._graph_batch_navigation_blocked = False
        self._animations_enabled = os.environ.get("AGENT_REVIEW_REDUCED_MOTION", "").lower() not in {"1", "true", "yes"}
        self._selected_interface_id: str | None = None
        self._selected_region_id: str | None = None
        self._selected_step_id: str | None = None
        self._step_target_start_id: str | None = None
        self._selected_relationship_id: str | None = None
        self._dirty = False
        self._operation = "idle"
        self._request_id = 0
        self._active_load_request: int | None = None
        self._save_bindings: dict[int, tuple[str, str, str, int]] = {}
        self._jobs: set[FacadeJob] = set()
        self._block_fields = False
        self._pending_invalid: set[str] = set()
        self.setWindowTitle("Agent Review · 学习工作台")
        self.setFont(QApplication.instance().font())
        self.setMinimumSize(1080, 680)
        self.resize(1440, 900)
        self._build_ui()
        apply_review_theme(self)
        if startup is not None:
            self._start_host_job("host_starting", startup)
        else:
            self.reload_batches()
            if callable(getattr(self.facade, "import_interface_content", None)):
                self.open_interface_library(pending_only=True)

    # 供集成测试调用的稳定入口。
    @property
    def workspace(self) -> dict[str, Any] | None:
        return self._workspace

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def reload_batches(self) -> None:
        """仅刷新摘要；选中的批次由后台线程读取。"""
        if self._operation != "idle":
            self._set_status("读取或保存进行中，不能刷新批次。")
            return
        self.batch_tree.clear()
        if self._connections is not None:
            self._operation = "refreshing"
            self._set_busy(True, "正在后台刷新在线收件箱…")
            self._request_id += 1
            job = make_job(self._request_id, self.facade.list_batches, self)
            job.succeeded.connect(self._summaries_succeeded)
            job.failed.connect(self._summaries_failed)
            self._jobs.add(job)
            job.finished.connect(lambda: self._summaries_finished(job))
            job.finished.connect(job.deleteLater)
            job.start()
            return
        try:
            summaries = self.facade.list_batches()
        except Exception as error:
            self._set_error(f"无法读取审核收件箱：{error}")
            return
        self._render_batch_summaries(summaries)

    def _summaries_succeeded(self, request_id, result) -> None:
        if request_id != self._request_id:
            return
        if not isinstance(result, list) or any(not isinstance(item, dict) or not isinstance(item.get("task_id"), str) or not isinstance(item.get("batch_id"), str) for item in result):
            self._set_error("在线收件箱摘要无效；未加载为审核对象。")
            return
        self._render_batch_summaries(result)

    def _summaries_failed(self, request_id, message) -> None:
        if request_id == self._request_id:
            self._set_error("在线收件箱读取失败；请刷新重试，未清除人工草稿。")

    def _summaries_finished(self, job) -> None:
        self._jobs.discard(job)
        self._operation = "idle"
        self._set_busy(False)
        if getattr(self, "_open_daily_on_ready", False):
            self._open_daily_on_ready = False
            self.open_interface_library(pending_only=True)

    def _render_batch_summaries(self, summaries) -> None:
        if not summaries:
            self.empty_label.setText("暂无可审核批次。外部提议尚未进入收件箱。")
            self.empty_label.show()
            self._set_status("空收件箱（未读取或修改任何外部应用）")
            return
        self.empty_label.hide()
        for summary in summaries:
            task_id = str(summary.get("task_id", ""))
            batch_id = str(summary.get("batch_id", ""))
            status = summary.get('status', 'needs_human_review')
            status = {"needs_human_review": "待审核", "reviewed": "已审核", "rejected": "需修改"}.get(status, status)
            text = f"{summary.get('title', batch_id)}  ·  {status}"
            item = QTreeWidgetItem([text])
            item.setData(0, _ROLE_KIND, "batch")
            item.setData(0, _ROLE_BATCH, (task_id, batch_id))
            item.setToolTip(0, f"task_id={task_id}\nbatch_id={batch_id}")
            self.batch_tree.addTopLevelItem(item)
        self._set_status(f"已发现 {len(summaries)} 个外部提议；尚未加载详细内容")
        self._filter_inbox()

    def load_batch(self, task_id: str, batch_id: str) -> None:
        if self._graph_active() and not self.show_inbox():
            return
        if self._operation != "idle":
            self._set_status("读取或保存进行中，不能切换批次。")
            return
        if self._dirty and not self._confirm_discard("切换批次将放弃当前未保存修改。是否继续？"):
            return
        self._request_id += 1
        request_id = self._request_id
        self._active_load_request = request_id
        self._operation = "loading"
        self._graph_batch_navigation_blocked = True
        self._set_busy(True, "正在后台读取批次…")
        job = make_job(request_id, lambda: self.facade.load_batch(task_id, batch_id), self)
        job.succeeded.connect(self._load_succeeded)
        job.failed.connect(self._load_failed)
        self._track_job(job)
        job.start()

    def save_current(self) -> None:
        current = self._review_stack.currentWidget()
        if current is self._content_page and self._content_page is not None:
            self._content_page.pane.save_changes()
            return
        if current is self._projects_page and self._projects_page is not None:
            self._projects_page.save_current()
            return
        if self._graph_active():
            self._graph_pane.save_all_changes()
            return
        if self._operation != "idle":
            self._set_status("读取或保存进行中，不能再次保存。")
            return
        if self._workspace is None:
            self._set_status("没有已加载批次可保存。")
            return
        interface_valid = self._commit_interface_meaning()
        region_valid = self._commit_property_fields()
        step_valid = self._commit_step_fields()
        relationship_valid = self._commit_relationship_fields()
        valid = interface_valid and region_valid and step_valid and relationship_valid
        if not valid or self._pending_invalid:
            self._set_error("无法保存：请修正当前保留的无效编辑后重试。")
            return
        if not self._dirty:
            self._set_status("当前修订没有未保存修改。")
            return
        self._operation = "saving"
        self._set_busy(True, "正在后台保存审核修订…")
        self._request_id += 1
        request_id = self._request_id
        outgoing = copy.deepcopy(self._workspace["batch"])
        task_id, batch_id = self._workspace["task_id"], self._workspace["batch_id"]
        revision = int(self._workspace["revision"])
        source_ref = str(self._workspace["source_ref"])
        self._save_bindings[request_id] = (task_id, batch_id, source_ref, revision)
        job = make_job(request_id, lambda: self.facade.save_revision(task_id, batch_id, revision, outgoing), self)
        job.succeeded.connect(self._save_succeeded)
        job.failed.connect(self._save_failed)
        self._track_job(job)
        job.start()

    # 构造原生界面。
    def _build_ui(self) -> None:
        self._build_actions()
        root = QSplitter(Qt.Orientation.Horizontal)
        root.setChildrenCollapsible(False)
        root.addWidget(self._make_navigation())
        root.addWidget(self._make_canvas_pane())
        root.addWidget(self._make_properties())
        root.setStretchFactor(0, 1)
        root.setStretchFactor(1, 4)
        root.setStretchFactor(2, 2)
        root.setSizes([270, 720, 410])
        self._legacy_review = root
        self._review_stack = QStackedWidget()
        self._review_stack.addWidget(root)
        self._review_stack.currentChanged.connect(self._sync_navigation)
        self.setCentralWidget(self._review_stack)
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self.source_status = QLabel("来源：尚未加载")
        self.revision_status = QLabel("修订：—")
        self.dirty_status = QLabel("状态：空闲")
        self.source_status.setObjectName("sourceStatusLabel")
        self.revision_status.setObjectName("revisionLabel")
        self.dirty_status.setObjectName("dirtyStatusLabel")
        for label in (self.source_status, self.revision_status, self.dirty_status):
            label.setProperty("role", "muted")
            label.setFrameStyle(QFrame.Shape.NoFrame)
            self.status.addPermanentWidget(label)
        self._set_busy(False)
        self._set_status("等待 Agent 提交学习内容；修改后保存即可复用。")

    def _build_actions(self) -> None:
        toolbar = QToolBar("导航", self)
        toolbar.setObjectName("reviewNavigation")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setFixedWidth(154)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, toolbar)
        brand = QLabel("Agent Review")
        brand.setObjectName("reviewBrand")
        toolbar.addWidget(brand)
        subtitle = QLabel("学习内容工作台")
        subtitle.setProperty("role", "muted")
        toolbar.addWidget(subtitle)
        toolbar.addSeparator()
        self.developer_menu = self.menuBar().addMenu("开发者")
        self.inbox_action = QAction("待审核流程", self)
        self.inbox_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon))
        self.inbox_action.setCheckable(True)
        self.inbox_action.setChecked(True)
        self.inbox_action.triggered.connect(self.show_inbox)
        self.inbox_action.triggered.connect(self._sync_navigation)
        self.developer_menu.addAction(self.inbox_action)
        self.refresh_action = QAction("刷新内容", self)
        self.refresh_action.triggered.connect(self.refresh_current_page)
        self.help_action = QAction("操作指南", self)
        self.help_action.setShortcut("F1")
        self.help_action.triggered.connect(self.open_user_guide)
        self.addAction(self.help_action)
        self.graph_review_action = QAction("流程图审核", self)
        self.graph_review_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.graph_review_action.setCheckable(True)
        self.graph_review_action.triggered.connect(lambda: self.open_graph_review())
        self.graph_review_action.triggered.connect(self._sync_navigation)
        self.graph_review_action.setEnabled(callable(getattr(self.facade, "load_batch_graph_revision", None)))
        self.developer_menu.addAction(self.graph_review_action)
        self.save_action = QAction("保存修订", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.save_action.triggered.connect(self.save_current)
        self.developer_menu.addAction(self.save_action)
        self.exact_review_action = QAction("精确人审", self)
        self.exact_review_action.triggered.connect(self.open_exact_review)
        self.developer_menu.addAction(self.exact_review_action)
        self.workflow_library_action = QAction("已发布流程", self)
        self.workflow_library_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.workflow_library_action.triggered.connect(self.open_workflow_library)
        self.developer_menu.addAction(self.workflow_library_action)
        self.interface_library_action = QAction("界面库", self)
        self.interface_library_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.interface_library_action.triggered.connect(lambda: self.open_interface_library())
        toolbar.addAction(self.interface_library_action)
        self.pending_interfaces_action = QAction("新学内容", self)
        self.pending_interfaces_action.triggered.connect(lambda: self.open_interface_library(pending_only=True))
        toolbar.insertAction(self.interface_library_action, self.pending_interfaces_action)
        self.graph_library_action = QAction("流程项目", self)
        self.graph_library_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.graph_library_action.triggered.connect(self.open_graph_library)
        toolbar.addAction(self.graph_library_action)
        for action in (self.pending_interfaces_action, self.interface_library_action, self.graph_library_action):
            action.setCheckable(True)
        self.relearn_action = QAction("重学与候选", self)
        self.relearn_action.triggered.connect(self.open_relearn_review)
        self.developer_menu.addAction(self.relearn_action)
        self.connections_action = QAction("Agent 连接", self)
        self.connections_action.setEnabled(self._connections is not None)
        self.connections_action.triggered.connect(self.open_connections)
        self.developer_menu.addAction(self.connections_action)
        self.application_startup_action = QAction("Agent 软件启动请求…", self)
        self.application_startup_action.setEnabled(self._application_startup is not None)
        self.application_startup_action.setToolTip("读取 Agent 暂存的目录应用请求；必须显示完整参数并独立确认，绝不自动启动。")
        self.application_startup_action.triggered.connect(self.open_application_startup)
        self.developer_menu.addAction(self.application_startup_action)
        self.developer_menu.addSeparator()
        self.single_step_action = QAction("单步验证", self)
        self.single_step_action.setEnabled(self._single_step is not None)
        self.single_step_action.setToolTip("单独检查截图、批准并执行一步；不会自动继续。" if self._single_step is not None else "离线审核未接入单步 Runtime；需由同进程共享宿主启动。")
        self.single_step_action.triggered.connect(self.open_single_step)
        self.developer_menu.addAction(self.single_step_action)
        self.model_setup_action = QAction("首次模型配置…", self)
        self.model_setup_action.setEnabled(self._single_step is not None and callable(getattr(self._single_step, "model_setup_status", None)) and callable(getattr(self._single_step, "configure_vista_model", None)))
        self.model_setup_action.triggered.connect(self.open_model_setup)
        self.developer_menu.addAction(self.model_setup_action)

        spacer = QWidget()
        spacer.setObjectName("navSpacer")
        spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        toolbar.addWidget(spacer)
        developer_button = QToolButton()
        developer_button.setObjectName("developerToolsButton")
        developer_button.setText("开发者工具")
        developer_button.setMenu(self.developer_menu)
        developer_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addWidget(developer_button)
        view_menu = self.menuBar().addMenu("显示")
        self.reduce_motion_action = QAction("减少动画", self)
        self.reduce_motion_action.setCheckable(True)
        self.reduce_motion_action.setChecked(not self._animations_enabled)
        self.reduce_motion_action.toggled.connect(self._set_reduced_motion)
        view_menu.addAction(self.reduce_motion_action)

        header = self.addToolBar("工作区")
        header.setObjectName("reviewHeader")
        header.setMovable(False)
        header.setFloatable(False)
        self.header_title = QLabel("待审核流程")
        self.header_title.setObjectName("reviewHeaderTitle")
        header.addWidget(self.header_title)
        self._header_transition = SubtleFadeTransition(self.header_title)
        self._header_transition.set_enabled(self._animations_enabled)
        hint = QLabel("Agent 发起学习 · 随时修正保存 · 持续复用")
        hint.setProperty("role", "muted")
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        hint.setMinimumWidth(0)
        header.addWidget(hint)
        header_spacer = QWidget()
        header_spacer.setObjectName("headerSpacer")
        header_spacer.setObjectName("headerSpacer")
        header_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(header_spacer)
        header.addAction(self.refresh_action)
        header.addAction(self.help_action)

    def open_user_guide(self) -> None:
        dialog = ReviewHelpDialog(self)
        dialog.exec()
        dialog.deleteLater()

    def _sync_navigation(self, *_args) -> None:
        graph = self._graph_active()
        current = self._review_stack.currentWidget()
        content = self._content_page is not None and current is self._content_page
        projects = self._projects_page is not None and current is self._projects_page
        self.inbox_action.setChecked(current is self._legacy_review)
        self.graph_review_action.setChecked(graph)
        self.pending_interfaces_action.setChecked(content and self._daily_section == "new")
        self.interface_library_action.setChecked(content and self._daily_section != "new")
        self.graph_library_action.setChecked(projects)
        title = ("新学内容" if self._daily_section == "new" else "界面库") if content else (
            "流程项目" if projects else ("流程图审核（开发者）" if graph else "批次检查（开发者）"))
        changed = self.header_title.text() != title
        self.header_title.setText(title)
        if changed:
            self._header_transition.play()

    def _set_reduced_motion(self, reduced: bool) -> None:
        self._animations_enabled = not reduced
        self._header_transition.set_enabled(self._animations_enabled)
        if self._graph_pane is not None:
            self._graph_pane.set_animations_enabled(self._animations_enabled)

    def _graph_active(self) -> bool:
        return self._graph_pane is not None and self._review_stack.currentWidget() is self._graph_pane

    def _current_batch_scope(self) -> tuple[str, str] | None:
        if self._workspace is None:
            return None
        task, batch = self._workspace.get("task_id"), self._workspace.get("batch_id")
        return (task, batch) if isinstance(task, str) and isinstance(batch, str) else None

    def open_graph_review(self, logical_workflow_id: str | None = None) -> None:
        if not self._allow_daily_leave():
            return
        if self._operation != "idle" or self._jobs or (self._graph_pane is not None and self._graph_pane.is_busy):
            self._set_status("请等待当前读取或保存完成后打开流程图。")
            return
        if self._dirty or (self._graph_pane is not None and self._graph_pane.is_dirty):
            self._set_status("请先保存或取消当前修改；不会自动丢弃草稿。")
            return
        if logical_workflow_id is None:
            if self._graph_batch_navigation_blocked:
                self._set_status("所选内容尚未读取成功，请重新选择或重试；不会打开旧流程图。")
                return
            if self._last_open_graph_id is not None and self._last_open_graph_source == self._current_batch_scope():
                remembered_id = self._last_open_graph_id
                operation = lambda: self.facade.load_graph_revision(remembered_id)
            elif self._workspace is not None:
                task, batch = self._workspace["task_id"], self._workspace["batch_id"]
                operation = lambda: self.facade.load_batch_graph_revision(task, batch)
            else:
                self._set_status("请先从收件箱选择内容，或先打开一个流程图。")
                return
        else:
            operation = lambda: self.facade.load_graph_revision(logical_workflow_id)
        self._operation = "graph_loading"
        self._request_id += 1
        job = make_job(self._request_id, operation, self)
        job.succeeded.connect(self._graph_loaded)
        job.failed.connect(self._graph_load_failed)
        self._track_job(job)
        self._set_busy(True, "正在读取当前流程图和来源证据…")
        job.start()

    def _graph_loaded(self, request_id: int, snapshot: object) -> None:
        if request_id != self._request_id or self._operation != "graph_loading":
            return
        from .graph_review_pane import GraphReviewPane
        self._operation = "idle"
        if self._graph_pane is None:
            self._graph_pane = GraphReviewPane(self.facade, self)
            self._graph_pane.set_animations_enabled(self._animations_enabled)
            self._graph_pane.errorRaised.connect(self._set_error)
            self._graph_pane.busyChanged.connect(lambda _: self._set_busy(self._operation != "idle"))
            self._graph_pane.dirtyChanged.connect(lambda _: self._update_dirty_status())
            self._graph_pane.revisionChanged.connect(self._graph_revision_changed)
            self._graph_pane.reviewRequested.connect(self._review_graph)
            self._review_stack.addWidget(self._graph_pane)
        if not self._graph_pane.set_revision(snapshot):
            self._set_busy(False)
            self._set_error("无法安装有效流程图；不会替换当前图或显示成功状态。")
            return
        self._last_open_graph_id = snapshot["logical_workflow_id"]
        self._last_open_graph_source = self._current_batch_scope()
        self._review_stack.setCurrentWidget(self._graph_pane)
        self._set_busy(False)
        self._set_status("已打开流程图；选择节点检查截图，选择连线检查跳转。")

    def _graph_load_failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self._operation = "idle"
        self._set_busy(False)
        self._set_error(f"无法打开有效流程图；不会自动导入旧知识：{message}")

    def _graph_revision_changed(self, snapshot: dict) -> None:
        self.source_status.setText("流程图 · 未授权执行")
        self.revision_status.setText(f"图修订：{snapshot['revision']}")
        self._update_dirty_status()

    def _review_graph(self, snapshot: dict) -> None:
        if self._graph_pane.is_busy or self._graph_pane.is_dirty:
            self._set_status("请先完成流程图保存，再审核这一修订。")
            return
        dialog = ExactReviewDialog(self.facade, snapshot, self)
        dialog.setObjectName("graphExactReviewDialog")
        dialog.exec()
        dialog.deleteLater()

    def show_inbox(self) -> bool:
        if not self._allow_daily_leave():
            return False
        if self._graph_pane is not None and (self._graph_pane.is_busy or self._graph_pane.is_dirty):
            self._set_status("请先保存或取消流程图修改，并等待读取结束。")
            return False
        self._review_stack.setCurrentWidget(self._legacy_review)
        self._set_busy(self._operation != "idle")
        if self._workspace is not None:
            self.revision_status.setText(f"批次修订：{self._workspace['revision']}")
            self.source_status.setText(f"来源：{self._workspace.get('source', 'untrusted_external')}（未授权）")
        else:
            self.revision_status.setText("修订：—")
            self.source_status.setText("来源：尚未加载")
        self._set_status("选择待审核内容，再打开流程图检查界面与跳转。")
        return True

    def open_model_setup(self) -> None:
        if self._operation != "idle" or not self._model_setup_available():
            return
        dialog = ModelSetupDialog(self._single_step, self)
        dialog.setObjectName("modelSetupDialog")
        dialog.exec()
        dialog.deleteLater()

    def _model_setup_available(self) -> bool:
        return all(callable(getattr(self._single_step, name, None))
                   for name in ("model_setup_status", "configure_vista_model"))

    def _make_navigation(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        panel.setObjectName("reviewInbox")
        layout.addWidget(QLabel("待审核内容"))
        self.inbox_search = QLineEdit()
        self.inbox_search.setObjectName("inboxSearch")
        self.inbox_search.setPlaceholderText("按名称查找流程")
        self.inbox_search.textChanged.connect(self._filter_inbox)
        layout.addWidget(self.inbox_search)
        guidance = QLabel("1. 选择 Agent 提交的内容\n2. 打开流程图，检查界面与跳转")
        guidance.setWordWrap(True)
        guidance.setProperty("role", "muted")
        layout.addWidget(guidance)
        self.batch_tree = QTreeWidget()
        self.batch_tree.setObjectName("batchTree")
        self.batch_tree.setHeaderLabels(["审核对象"])
        self.batch_tree.setHeaderHidden(True)
        self.batch_tree.setWordWrap(True)
        self.batch_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.batch_tree.itemSelectionChanged.connect(self._tree_selected)
        layout.addWidget(self.batch_tree, 1)
        self.empty_label = QLabel("正在读取批次摘要…")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        self.open_selected_graph_button = QPushButton("打开所选流程图")
        self.open_selected_graph_button.setObjectName("openSelectedGraphButton")
        self.open_selected_graph_button.setProperty("role", "primary")
        self.open_selected_graph_button.clicked.connect(lambda: self.open_graph_review())
        layout.addWidget(self.open_selected_graph_button)
        self.reload_button = QPushButton("刷新收件箱")
        self.reload_button.clicked.connect(self.reload_batches)
        layout.addWidget(self.reload_button)
        return panel

    def _filter_inbox(self) -> None:
        query = self.inbox_search.text().strip().casefold()
        visible = 0
        for index in range(self.batch_tree.topLevelItemCount()):
            item = self.batch_tree.topLevelItem(index)
            matches = not query or query in item.text(0).casefold()
            item.setHidden(not matches)
            visible += int(matches)
        if query and not visible:
            self.empty_label.setText("没有匹配的流程，试试换个名称或清空搜索。")
            self.empty_label.show()
        elif self.batch_tree.topLevelItemCount():
            self.empty_label.hide()

    def _make_canvas_pane(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        heading = QHBoxLayout()
        self.canvas_title = QLabel("截图审核画布")
        # 标题只使用剩余宽度，长说明不能挤压两侧审核面板。
        self.canvas_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(self.canvas_title, 1)
        zoom_hint = QLabel("Ctrl+滚轮缩放；中键平移；拖动边角改框")
        zoom_hint.setStyleSheet("color: #555;")
        heading.addWidget(zoom_hint)
        layout.addLayout(heading)
        self.canvas = ReviewCanvas()
        self.canvas.setObjectName("reviewCanvas")
        self.canvas_actual_size = QPushButton("100%")
        self.canvas_actual_size.setObjectName("canvasActualSizeButton")
        self.canvas_actual_size.setToolTip("原图像素：一个截图像素对应一个屏幕物理像素")
        self.canvas_actual_size.clicked.connect(self.canvas.show_actual_size)
        self.canvas_fit = QPushButton("适应")
        self.canvas_fit.setObjectName("canvasFitButton")
        self.canvas_fit.clicked.connect(self.canvas.fit_image)
        self.canvas_zoom_label = QLabel("—")
        self.canvas_zoom_label.setObjectName("canvasZoomLabel")
        self.canvas_zoom_label.setMinimumWidth(38)
        self.canvas.zoomChanged.connect(lambda value: self.canvas_zoom_label.setText(f"{value:.0f}%"))
        for control in (self.canvas_actual_size, self.canvas_fit, self.canvas_zoom_label):
            heading.addWidget(control)
        self.canvas.regionSelected.connect(self._region_selected_from_canvas)
        self.canvas.regionGeometryChanged.connect(self._region_geometry_changed)
        layout.addWidget(self.canvas, 1)
        return panel

    def _make_properties(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("属性与流程审核"))
        self.selection_label = QLabel("未选择区域")
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)
        form = QFormLayout()
        self.interface_meaning = QLineEdit()
        self.interface_meaning.setObjectName("interfaceMeaningField")
        self.interface_meaning.setPlaceholderText("选择界面后可修改其语义说明")
        form.addRow("界面含义", self.interface_meaning)
        self.interface_recognition_text = QLineEdit()
        self.interface_recognition_text.setObjectName("interfaceRecognitionTextField")
        self.interface_recognition_text.setPlaceholderText("截图中实际可见的界面标题或文字；不是用途说明")
        form.addRow("界面识别文字", self.interface_recognition_text)
        self.region_name = QLineEdit()
        self.region_kind = QLineEdit()
        self.region_meaning = QPlainTextEdit()
        self.region_name.setObjectName("regionNameField")
        self.region_kind.setObjectName("regionKindField")
        self.region_meaning.setObjectName("regionMeaningField")
        self.region_meaning.setFixedHeight(86)
        form.addRow("名称 / 标签", self.region_name)
        form.addRow("类型", self.region_kind)
        form.addRow("语义说明", self.region_meaning)
        self.bbox_spins: list[QDoubleSpinBox] = []
        names = (("X", "bboxXField"), ("Y", "bboxYField"), ("宽", "bboxWidthField"), ("高", "bboxHeightField"))
        for name, object_name in names:
            spin = QDoubleSpinBox()
            spin.setObjectName(object_name)
            spin.setDecimals(2)
            spin.setRange(0.0 if name in {"X", "Y"} else 1.0, 99999.0)
            spin.setSingleStep(1.0)
            spin.valueChanged.connect(self._bbox_edited)
            form.addRow(name, spin)
            self.bbox_spins.append(spin)
        layout.addLayout(form)
        self.interface_meaning.editingFinished.connect(self._commit_interface_meaning)
        self.interface_meaning.textChanged.connect(self._interface_meaning_edited)
        self.interface_recognition_text.editingFinished.connect(self._commit_interface_meaning)
        self.interface_recognition_text.textChanged.connect(self._commit_interface_recognition_text)
        self.region_name.editingFinished.connect(self._commit_property_fields)
        self.region_kind.editingFinished.connect(self._commit_property_fields)
        self.region_name.textChanged.connect(self._region_text_edited)
        self.region_kind.textChanged.connect(self._region_text_edited)
        self.region_meaning.textChanged.connect(self._meaning_edited)
        self.step_table = QTableWidget(0, 5)
        self.step_table.setObjectName("flowStepTable")
        self.step_table.setHorizontalHeaderLabels(["步骤", "动作", "目标区域", "预期结果", "停止条件"])
        self.step_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.step_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 只读表用方向键选行，Tab 留给审核控件间的焦点切换。
        self.step_table.setTabKeyNavigation(False)
        self.step_table.itemSelectionChanged.connect(self._step_selected)
        layout.addWidget(QLabel("流程步骤（只编辑审核草稿）"))
        layout.addWidget(self.step_table, 1)
        order_controls = QHBoxLayout()
        self.step_up_button = QPushButton("上移步骤")
        self.step_down_button = QPushButton("下移步骤")
        self.step_up_button.setObjectName("moveStepUpButton")
        self.step_down_button.setObjectName("moveStepDownButton")
        self.step_up_button.clicked.connect(lambda: self.move_selected_step(-1))
        self.step_down_button.clicked.connect(lambda: self.move_selected_step(1))
        order_controls.addWidget(self.step_up_button)
        order_controls.addWidget(self.step_down_button)
        layout.addLayout(order_controls)
        layout.addWidget(QLabel("调整审核顺序不会自动修改连接或执行流程。"))
        step_form = QFormLayout()
        # 窄窗口时把长标签换到字段上方，避免表单的最小宽度撑出横向滚动条。
        step_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.step_action = QLineEdit()
        self.step_target = QComboBox()
        self.scroll_direction = QComboBox()
        self.scroll_direction.setObjectName("scrollDirectionField")
        self.scroll_direction.addItem("up", "up")
        self.scroll_direction.addItem("down", "down")
        self.scroll_wheel_clicks = QSpinBox()
        self.scroll_wheel_clicks.setObjectName("scrollWheelClicksField")
        self.scroll_wheel_clicks.setRange(1, 20)
        self.scroll_contract = QLabel("vertical / wheel_detent; container follows the selected target region")
        self.scroll_contract.setObjectName("scrollParametersContractLabel")
        self.text_content_kind = QComboBox()
        self.text_content_kind.setObjectName("textContentKindField")
        self.text_content_kind.addItem("固定内容", "literal")
        self.text_content_kind.addItem("执行前填写变量", "variable")
        self.text_literal = QPlainTextEdit()
        self.text_literal.setObjectName("textLiteralField")
        self.text_literal.setFixedHeight(72)
        self._text_literal_original = ""
        self._text_literal_dirty = False
        self.text_variable = QLineEdit()
        self.text_variable.setObjectName("textVariableField")
        self.text_variable.setPlaceholderText("例如 query_text；执行前再输入实际内容")
        self.text_clear_existing = QCheckBox("先清空字段原内容")
        self.text_clear_existing.setObjectName("textClearExistingField")
        self.text_clear_existing.setChecked(True)
        self.text_sensitive = QCheckBox("敏感内容（不进入普通日志）")
        self.text_sensitive.setObjectName("textSensitiveField")
        self.step_expected = QPlainTextEdit()
        self.step_start = QLineEdit()
        self.step_arrival = QLineEdit()
        self.step_prerequisites = QPlainTextEdit()
        self.step_stop = QPlainTextEdit()
        self.step_action.setObjectName("stepActionField")
        self.step_target.setObjectName("stepTargetField")
        self.step_expected.setObjectName("stepExpectedField")
        self.step_start.setObjectName("stepStartField")
        self.step_arrival.setObjectName("stepArrivalField")
        self.step_prerequisites.setObjectName("stepPrerequisitesField")
        self.step_stop.setObjectName("stepStopField")
        self.step_expected.setFixedHeight(58)
        step_form.addRow("动作", self.step_action)
        step_form.addRow("目标区域", self.step_target)
        step_form.addRow("滚动方向", self.scroll_direction)
        step_form.addRow("滚轮次数", self.scroll_wheel_clicks)
        step_form.addRow("滚动契约", self.scroll_contract)
        step_form.addRow("填写内容来源", self.text_content_kind)
        step_form.addRow("固定内容", self.text_literal)
        step_form.addRow("变量名称", self.text_variable)
        step_form.addRow("填写方式", self.text_clear_existing)
        step_form.addRow("内容保护", self.text_sensitive)
        step_form.addRow("填写边界", QLabel("只填写，不按 Enter、不提交；执行前另行预览确认。"))
        step_form.addRow("预期结果", self.step_expected)
        step_form.addRow("起始界面", self.step_start)
        step_form.addRow("到达界面", self.step_arrival)
        step_form.addRow("前置条件（每行一项）", self.step_prerequisites)
        step_form.addRow("停止条件", self.step_stop)
        layout.addLayout(step_form)
        self.step_action.editingFinished.connect(self._commit_step_fields)
        self.step_action.textChanged.connect(self._step_expected_edited)
        self.step_target.currentIndexChanged.connect(self._commit_step_fields)
        self.scroll_direction.currentIndexChanged.connect(self._scroll_fields_edited)
        self.scroll_wheel_clicks.valueChanged.connect(self._scroll_fields_edited)
        self.text_content_kind.currentIndexChanged.connect(self._text_fields_edited)
        self.text_literal.textChanged.connect(self._text_literal_edited)
        self.text_variable.textChanged.connect(self._text_fields_edited)
        self.text_clear_existing.toggled.connect(self._text_fields_edited)
        self.text_sensitive.toggled.connect(self._text_fields_edited)
        self.step_expected.textChanged.connect(self._step_expected_edited)
        for widget in (self.step_start, self.step_arrival, self.step_prerequisites, self.step_stop):
            widget.editingFinished.connect(self._commit_step_fields) if isinstance(widget, QLineEdit) else widget.textChanged.connect(self._step_text_edited)
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._step_text_edited)
        self.relationship_table = QTableWidget(0, 4)
        self.relationship_table.setObjectName("relationshipTable")
        self.relationship_table.setHorizontalHeaderLabels(["关系", "来源", "目的", "类别"])
        self.relationship_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.relationship_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.relationship_table.setTabKeyNavigation(False)
        self.relationship_table.setMaximumHeight(125)
        self.relationship_table.itemSelectionChanged.connect(self._relationship_selected)
        layout.addWidget(QLabel("界面关系（稳定 ID 不可修改）"))
        layout.addWidget(self.relationship_table)
        relationship_form = QFormLayout()
        self.relationship_from = QLineEdit(); self.relationship_from.setObjectName("relationshipSourceField")
        self.relationship_to = QLineEdit(); self.relationship_to.setObjectName("relationshipDestinationField")
        self.relationship_kind = QLineEdit(); self.relationship_kind.setObjectName("relationshipKindField")
        relationship_form.addRow("来源界面", self.relationship_from)
        relationship_form.addRow("目的界面", self.relationship_to)
        relationship_form.addRow("关系类别", self.relationship_kind)
        layout.addLayout(relationship_form)
        for widget in (self.relationship_from, self.relationship_to, self.relationship_kind):
            widget.editingFinished.connect(self._commit_relationship_fields)
            widget.textChanged.connect(self._relationship_text_edited)
        self.save_button = QPushButton("保存审核修订")
        self.save_button.setObjectName("saveRevisionButton")
        self.save_button.clicked.connect(self.save_current)
        layout.addWidget(self.save_button)
        self.exact_review_button = QPushButton("打开精确人审")
        self.exact_review_button.setObjectName("exactReviewButton")
        self.exact_review_button.clicked.connect(self.open_exact_review)
        layout.addWidget(self.exact_review_button)
        self.workflow_library_button = QPushButton("查看工作流库")
        self.workflow_library_button.setObjectName("workflowLibraryButton")
        self.workflow_library_button.clicked.connect(self.open_workflow_library)
        layout.addWidget(self.workflow_library_button)
        # 长说明随面板宽度换行，避免把整张表单撑到视口之外。
        for label in panel.findChildren(QLabel):
            label.setWordWrap(True)
        # 长表单滚动显示，不挤压字段高度或移动另外两栏。
        scroll = QScrollArea()
        scroll.setObjectName("propertiesScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        return scroll

    def open_exact_review(self) -> None:
        if self._graph_active():
            self._set_status("请使用流程图中的审核入口，不能审核旧批次替代当前图。")
            return
        if self._operation != "idle" or self._workspace is None:
            self._set_status("读取或保存进行中，不能打开精确审核。")
            return
        if self._dirty or not self._workspace.get("workflow_review_path"):
            self._set_status("当前草稿尚未保存为固定修订，不能以旧版本准备精确审核。")
            return
        dialog = ExactReviewDialog(self.facade, self._workspace, self)
        dialog.setObjectName("exactReviewDialog")
        dialog.exec()

    def open_workflow_library(self) -> None:
        if self._operation != "idle":
            self._set_status("读取或保存进行中，不能读取工作流库。")
            return
        dialog = WorkflowLibraryDialog(self.facade, self)
        dialog.setObjectName("workflowLibraryDialog")
        dialog.exec()

    def open_interface_library(self, *, pending_only: bool = False) -> None:
        if self._operation != "idle":
            self._set_status("读取或保存进行中，不能读取独立界面库。")
            return
        if not callable(getattr(self.facade, "import_interface_content", None)):
            self._set_status("当前宿主尚未支持独立界面内容库。")
            return
        if self._dirty or (self._graph_pane is not None and self._graph_pane.is_dirty) or not self._allow_daily_leave():
            self._set_status("请先保存或取消当前修改，再打开界面库。")
            return
        if self._content_page is None:
            self._content_page = InterfaceContentLibrary(self.facade, self, embedded=True)
            self._content_page.openLearningFlow.connect(self.open_learning_flow)
            self._content_page.setObjectName("interfaceContentLibrary")
            self._review_stack.addWidget(self._content_page)
        self._daily_section = "new" if pending_only else "library"
        self._content_page.filter.setCurrentIndex(1 if pending_only else 0)
        self._content_page.refresh()
        self._review_stack.setCurrentWidget(self._content_page)
        self._sync_navigation()
        self._daily_status()

    def open_graph_library(self) -> None:
        if self._operation != "idle" or self._jobs or self._dirty or (self._graph_pane is not None and (self._graph_pane.is_busy or self._graph_pane.is_dirty)) or not self._allow_daily_leave():
            self._set_status("请先完成当前读取、保存或修改，再打开流程图库。")
            return
        from .workflow_projects_pane import WorkflowProjectsPane
        if self._projects_page is None:
            self._projects_page = WorkflowProjectsPane(self.facade, self)
            self._projects_page.busyChanged.connect(self._project_loading_changed)
            self._projects_page.setObjectName("workflowProjects")
            self._review_stack.addWidget(self._projects_page)
            self._review_stack.setCurrentWidget(self._projects_page)
        else:
            self._review_stack.setCurrentWidget(self._projects_page)
            self._projects_page.refresh()
        self._daily_status()

    def open_learning_flow(self, workflow_id: str) -> None:
        """从学习界面直达同段项目，不另建空图或丢弃编辑。"""
        self.open_graph_library()
        if self._projects_page is not None and self._review_stack.currentWidget() is self._projects_page:
            self._projects_page.open_project(workflow_id)

    def _allow_daily_leave(self) -> bool:
        if self._projects_page is not None and self._projects_page.is_edit_busy:
            self._set_status("界面选择器仍在读取或保存，请完成后再切换页面。")
            self._sync_navigation()
            return False
        for page in (self._content_page, self._projects_page):
            if page is not None and page.dirty:
                self._set_status("有未保存修改：请先保存或放弃，再切换页面。不会自动丢弃内容。")
                self._sync_navigation()
                return False
        return True

    def _daily_status(self) -> None:
        self.source_status.setText("保存为流程记忆 · 非执行授权")
        self.revision_status.setText("可持续修改")
        self.dirty_status.setText("使用页面内的保存修改")
        self.save_action.setEnabled(True)
        self._set_status("选择界面或流程项目，直接修改并保存；不需要另行审核或定稿。")

    def refresh_current_page(self) -> None:
        current = self._review_stack.currentWidget()
        if current in (self._content_page, self._projects_page):
            current.refresh()
        else:
            self.reload_batches()

    def open_relearn_review(self) -> None:
        if self._graph_active():
            self._set_status("当前为图修订；不能使用旧批次重学入口。")
            return
        if self._operation != "idle" or self._workspace is None:
            self._set_status("读取或保存进行中，或尚未选择批次，不能开始重学审核。")
            return
        if self._dirty or not self._workspace.get("workflow_review_path"):
            self._set_status("请先保存人工修订，再绑定确切版本提交重学问题。")
            return
        dialog = RelearnReviewDialog(self.facade, self._workspace, self)
        dialog.setObjectName("relearnReviewDialog")
        dialog.exec()
        if getattr(dialog, "requires_workspace_reload", False):
            self.load_batch(self._workspace["task_id"], self._workspace["batch_id"])

    # 选择和草稿修改。
    def open_connections(self) -> None:
        if self._operation != "idle" or self._connections is None:
            self._set_status("当前不是可管理连接的就绪宿主。")
            return
        dialog = ConnectionManagerDialog(self._connections, self)
        dialog.setObjectName("connectionManagerDialog")
        dialog.exec()

    def open_application_startup(self) -> None:
        if self._operation != "idle" or self._application_startup is None:
            self._set_status("当前没有可用的软件启动人工确认入口，或审核工作区仍在忙。")
            return
        dialog = ApplicationStartupDialog(self._application_startup, self)
        dialog.setObjectName("applicationStartupDialog")
        dialog.exec()
        dialog.deleteLater()

    def open_single_step(self) -> None:
        if self._operation != "idle" or self._single_step is None:
            self._set_status("当前没有可用的单步 Runtime，或审核工作区仍在忙。")
            return
        dialog = SingleStepDialog(self._single_step, self)
        dialog.setObjectName("singleStepDialog")
        dialog.exec()
        dialog.deleteLater()

    def _tree_selected(self) -> None:
        items = self.batch_tree.selectedItems()
        if not items:
            return
        item = items[0]
        kind = item.data(0, _ROLE_KIND)
        if kind == "batch":
            pair = item.data(0, _ROLE_BATCH)
            if pair:
                self.load_batch(str(pair[0]), str(pair[1]))
        elif kind == "interface":
            self._show_interface(str(item.data(0, _ROLE_ID)))
        elif kind == "region":
            self._show_interface(str(item.parent().data(0, _ROLE_ID)))
            self._select_region(str(item.data(0, _ROLE_ID)))

    def _show_interface(self, interface_id: str) -> None:
        batch = self._batch()
        if batch is None:
            return
        self._selected_interface_id = interface_id
        self._selected_region_id = None
        self.canvas.set_interface(batch, interface_id)
        interface = self._interface(interface_id)
        self.canvas_title.setText(f"截图审核画布 · {interface.get('meaning', interface_id) if interface else interface_id}")
        self._fill_interface_field(interface)
        self._fill_region_fields(None)

    def _select_region(self, region_id: str) -> None:
        region, interface = self._region(region_id)
        if region is None:
            return
        self._selected_interface_id = str(interface["interface_id"])
        self._selected_region_id = region_id
        self.canvas.select_region(region_id)
        self._fill_interface_field(interface)
        self._fill_region_fields(region)

    def _region_selected_from_canvas(self, region_id: str) -> None:
        self._select_region(region_id)
        self._select_tree_region(region_id)

    def _region_geometry_changed(self, region_id: str, bbox: list[float]) -> None:
        region, _ = self._region(region_id)
        if region is None:
            return
        updated = self._clamped_bbox(region_id, bbox)
        if region.get("bbox") == updated:
            return
        region["bbox"] = updated
        self._fill_region_fields(region)
        self._mark_dirty()

    def _bbox_edited(self) -> None:
        if self._block_fields or self._selected_region_id is None:
            return
        region, _ = self._region(self._selected_region_id)
        if region is None:
            return
        updated = self._clamped_bbox(self._selected_region_id, [item.value() for item in self.bbox_spins])
        if region.get("bbox") == updated:
            return
        region["bbox"] = updated
        self.canvas.set_region_bbox(self._selected_region_id, region["bbox"])
        self._fill_region_fields(region)
        self._mark_dirty()

    def _meaning_edited(self) -> None:
        if not self._block_fields and self._selected_region_id is not None:
            self._mark_dirty()
            self._commit_property_fields()

    def _region_text_edited(self) -> None:
        if not self._block_fields and self._selected_region_id is not None:
            self._mark_dirty()

    def _commit_property_fields(self) -> bool:
        if self._block_fields or self._selected_region_id is None:
            return True
        region, _ = self._region(self._selected_region_id)
        if region is None:
            return True
        name = self.region_name.text().strip()
        kind = self.region_kind.text().strip()
        meaning = self.region_meaning.toPlainText().strip()
        candidate = copy.deepcopy(region)
        if name:
            name_key = "name" if "name" in candidate or "label" not in candidate else "label"
            candidate[name_key] = name
            candidate.pop("label" if name_key == "name" else "name", None)
        else:
            candidate.pop("name", None)
            candidate.pop("label", None)
        if kind:
            kind_key = "kind" if "kind" in candidate or "type" not in candidate else "type"
            candidate[kind_key] = kind
            candidate.pop("type" if kind_key == "kind" else "kind", None)
        else:
            candidate.pop("kind", None)
            candidate.pop("type", None)
        if not meaning or not any(candidate.get(key) for key in ("name", "label", "kind", "type")):
            self._pending_invalid.add("区域属性")
            self._mark_dirty()
            return False
        self._pending_invalid.discard("区域属性")
        candidate["meaning"] = meaning
        if candidate != region:
            region.clear()
            region.update(candidate)
            self._mark_dirty()
        return True

    def _interface_meaning_edited(self) -> None:
        if not self._block_fields and self._selected_interface_id is not None:
            self._mark_dirty()

    def _commit_interface_meaning(self) -> bool:
        if self._block_fields or self._selected_interface_id is None:
            return True
        interface = self._interface(self._selected_interface_id)
        meaning = self.interface_meaning.text().strip()
        if not meaning:
            self._pending_invalid.add("界面含义")
            self._mark_dirty()
            return False
        self._pending_invalid.discard("界面含义")
        if interface is not None and interface.get("meaning") != meaning:
            interface["meaning"] = meaning
            self.canvas_title.setText(f"截图审核画布 · {meaning}")
            self._mark_dirty()
        self._commit_interface_recognition_text()
        return True

    def _commit_interface_recognition_text(self) -> None:
        if self._block_fields or self._selected_interface_id is None:
            return
        interface = self._interface(self._selected_interface_id)
        recognition_text = self.interface_recognition_text.text().strip()
        # 空白和缺失等价；即时更新独立字段，切换界面时不丢失编辑。
        if interface is not None and (interface.get("recognition_text") or "") != recognition_text:
            if recognition_text:
                interface["recognition_text"] = recognition_text
            else:
                interface.pop("recognition_text", None)
            self._mark_dirty()

    # 流程步骤编辑。
    def _commit_before_flow_selection(self, table: QTableWidget, selected_id: str | None, commit) -> bool:
        if selected_id is None or self._operation != "idle" or commit():
            return True
        # 无效草稿留在原对象；恢复可见选中行，不静默丢弃输入。
        blocked = table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and item.data(_ROLE_ID) == selected_id:
                    table.selectRow(row)
                    break
        finally:
            table.blockSignals(blocked)
        self._set_status("当前流程字段无效，已保留输入；请修正后再切换审核对象。")
        return False

    def _step_selected(self) -> None:
        if self._block_fields or not self._commit_before_flow_selection(self.step_table, self._selected_step_id, self._commit_step_fields):
            return
        rows = self.step_table.selectionModel().selectedRows() if self.step_table.selectionModel() else []
        if not rows:
            self._selected_step_id = None
            self._update_flow_editor_availability(self._operation != "idle")
            self._update_scroll_controls()
            self._update_step_order_controls()
            return
        step_id = self.step_table.item(rows[0].row(), 0).data(_ROLE_ID)
        self._selected_step_id = str(step_id)
        step = self._step(self._selected_step_id)
        if step is None:
            return
        self._block_fields = True
        self._populate_step_targets(step)
        self.step_action.setText(str(step.get("action_type", "")))
        index = self.step_target.findData(step.get("target_region_id"))
        self.step_target.setCurrentIndex(max(0, index))
        self.step_expected.setPlainText(str(step.get("expected_result", "")))
        self.step_start.setText(str(step.get("start_state", "")))
        self.step_arrival.setText(str(step.get("arrival_state", "")))
        self.step_prerequisites.setPlainText("\n".join(str(item) for item in step.get("prerequisites", [])))
        self.step_stop.setPlainText(str(step.get("stop_condition", "")))
        parameters = step.get("scroll_parameters") if isinstance(step.get("scroll_parameters"), dict) else {}
        direction = parameters.get("direction", "down")
        self.scroll_direction.setCurrentIndex(max(0, self.scroll_direction.findData(direction)))
        wheel_clicks = parameters.get("wheel_clicks", self.scroll_wheel_clicks.minimum())
        self.scroll_wheel_clicks.setValue(wheel_clicks if type(wheel_clicks) is int else self.scroll_wheel_clicks.minimum())
        text_parameters = step.get("text_parameters") if isinstance(step.get("text_parameters"), dict) else {}
        content = text_parameters.get("content", {})
        self.text_content_kind.setCurrentIndex(max(0, self.text_content_kind.findData(content.get("kind", "literal"))))
        self._text_literal_original = content.get("text", "")
        self.text_literal.setPlainText(self._text_literal_original)
        self._text_literal_dirty = False
        self.text_variable.setText(content.get("name", ""))
        self.text_clear_existing.setChecked(text_parameters.get("clear_existing", True))
        self.text_sensitive.setChecked(text_parameters.get("sensitive", False))
        self._block_fields = False
        self._update_scroll_controls()
        self._update_step_order_controls()
        self._update_flow_editor_availability(self._operation != "idle")

    def _can_move_step(self, direction: int) -> bool:
        steps = (self._batch() or {}).get("steps", [])
        index = next((index for index, step in enumerate(steps) if step["step_id"] == self._selected_step_id), -1)
        if self._operation != "idle" or direction not in (-1, 1) or index < 0 or not 0 <= index + direction < len(steps):
            return False
        if self._pending_invalid - {"流程步骤"}:
            return False
        start, arrival = self.step_start.text().strip(), self.step_arrival.text().strip()
        action, target = self.step_action.text().strip(), self.step_target.currentData()
        interfaces = {item["interface_id"] for item in self._batch()["interfaces"]}
        optional = action in {"safe_stop", "observe"}
        return bool(
            start in interfaces and arrival in interfaces and action
            and self.step_expected.toPlainText().strip() and self.step_stop.toPlainText().strip()
            and ((optional and (target is None or target in self._known_region_ids()))
                 or (not optional and target in self._source_region_ids(steps[index], start)))
        )

    def _update_step_order_controls(self) -> None:
        self.step_up_button.setEnabled(self._can_move_step(-1))
        self.step_down_button.setEnabled(self._can_move_step(1))

    def move_selected_step(self, direction: int) -> None:
        if not self._can_move_step(direction):
            return
        valid = [self._commit_interface_meaning(), self._commit_property_fields(),
                 self._commit_step_fields(), self._commit_relationship_fields()]
        if not all(valid) or self._pending_invalid:
            self._set_error("无法调整顺序：请先修正保留的无效编辑。")
            return
        steps = self._batch()["steps"]
        index = next(index for index, step in enumerate(steps) if step["step_id"] == self._selected_step_id)
        destination = index + direction
        steps[index], steps[destination] = steps[destination], steps[index]
        self.step_table.blockSignals(True)
        self._populate_steps()
        self.step_table.blockSignals(False)
        self.step_table.selectRow(destination)
        self._mark_dirty()
        self._set_status("步骤审核顺序已修改，请保存修订；未改连接或执行外部动作。")

    def _step_expected_edited(self) -> None:
        if not self._block_fields and self._selected_step_id:
            self._mark_dirty()
            self._commit_step_fields()

    def _scroll_fields_edited(self, _: Any = None) -> None:
        if not self._block_fields and self._selected_step_id:
            self._mark_dirty()
            self._commit_step_fields()

    def _update_scroll_controls(self) -> None:
        enabled = (
            self._operation == "idle"
            and self._selected_step_id is not None
            and self.step_action.text().strip() == SCROLL_SEMANTIC_ACTION
        )
        self.scroll_direction.setEnabled(enabled)
        self.scroll_wheel_clicks.setEnabled(enabled)
        self._update_text_controls()

    def _update_text_controls(self) -> None:
        enabled = self._operation == "idle" and self._selected_step_id is not None and self.step_action.text().strip() == TEXT_SEMANTIC_ACTION
        self.text_content_kind.setEnabled(enabled)
        self.text_literal.setEnabled(enabled and self.text_content_kind.currentData() == "literal")
        self.text_variable.setEnabled(enabled and self.text_content_kind.currentData() == "variable")
        self.text_clear_existing.setEnabled(enabled)
        self.text_sensitive.setEnabled(enabled)

    def _text_literal_edited(self) -> None:
        if not self._block_fields:
            self._text_literal_dirty = True
            self._text_fields_edited()

    def _text_fields_edited(self, _: Any = None) -> None:
        if not self._block_fields and self._selected_step_id:
            self._update_text_controls()
            self._mark_dirty()
            self._commit_step_fields()

    def _step_text_edited(self) -> None:
        if not self._block_fields and self._selected_step_id:
            self._mark_dirty()

    def _commit_step_fields(self) -> bool:
        if self._block_fields or not self._selected_step_id:
            return True
        step = self._step(self._selected_step_id)
        if step is None:
            return True
        action = self.step_action.text().strip()
        target = self.step_target.currentData()
        expected = self.step_expected.toPlainText().strip()
        start = self.step_start.text().strip()
        arrival = self.step_arrival.text().strip()
        prerequisites = [item.strip() for item in self.step_prerequisites.toPlainText().splitlines() if item.strip()]
        stop = self.step_stop.toPlainText().strip()
        known_interfaces = {item["interface_id"] for item in (self._batch() or {}).get("interfaces", [])}
        if start != step.get("start_state") and start in known_interfaces and self._step_target_start_id != start:
            candidate_step = copy.deepcopy(step)
            candidate_step["start_state"] = start
            self._block_fields = True
            self._populate_step_targets(candidate_step)
            self._block_fields = False
            target = self.step_target.currentData()
        valid_targets = self._source_region_ids(step, start)
        optional_target = action in {"safe_stop", "observe"}
        if not action or not expected or not stop or start not in known_interfaces or arrival not in known_interfaces or (not optional_target and target not in valid_targets) or (optional_target and target is not None and target not in self._known_region_ids()):
            self._pending_invalid.add("流程步骤")
            self._mark_dirty()
            return False
        candidate = copy.deepcopy(step)
        candidate.update(action_type=action, target_region_id=target, expected_result=expected, start_state=start, arrival_state=arrival, prerequisites=prerequisites, stop_condition=stop)
        if action == SCROLL_SEMANTIC_ACTION:
            try:
                candidate["scroll_parameters"] = ReviewedScrollParameters(
                    target_container_id=str(target),
                    axis="vertical",
                    direction=str(self.scroll_direction.currentData()),
                    wheel_clicks=self.scroll_wheel_clicks.value(),
                    unit="wheel_detent",
                ).to_payload()
            except ValueError:
                self._pending_invalid.add("滚动参数")
                self._mark_dirty()
                return False
        else:
            candidate.pop("scroll_parameters", None)
        if action == TEXT_SEMANTIC_ACTION:
            kind = self.text_content_kind.currentData()
            # 未编辑时保留原始换行，避免 Qt 的显示规范化改写已审核文本。
            literal = self.text_literal.toPlainText() if self._text_literal_dirty else self._text_literal_original
            try:
                candidate["text_parameters"] = ReviewedTextParameters.from_payload({
                    "contract_version": "reviewed_text_parameters_v1", "target_field_id": str(target),
                    "content": {"kind": "literal", "text": literal} if kind == "literal" else {"kind": "variable", "name": self.text_variable.text()},
                    "clear_existing": self.text_clear_existing.isChecked(), "sensitive": self.text_sensitive.isChecked(),
                    "submit": False, "clipboard_policy": "restore_previous",
                }).to_payload()
            except ValueError as error:
                self._pending_invalid.add("填写参数")
                self._mark_dirty()
                self._update_text_controls()
                self._set_status(f"填写参数未保存：{error}")
                return False
        else:
            candidate.pop("text_parameters", None)
        self._pending_invalid.discard("流程步骤")
        self._pending_invalid.discard("滚动参数")
        self._pending_invalid.discard("填写参数")
        if candidate != step:
            step.clear()
            step.update(candidate)
            self._update_step_row(step)
            self._mark_dirty()
        self._update_scroll_controls()
        return True

    def _relationship_selected(self) -> None:
        if self._block_fields or not self._commit_before_flow_selection(self.relationship_table, self._selected_relationship_id, self._commit_relationship_fields):
            return
        rows = self.relationship_table.selectionModel().selectedRows() if self.relationship_table.selectionModel() else []
        if not rows:
            self._selected_relationship_id = None
            self._update_flow_editor_availability(self._operation != "idle")
            return
        item = self.relationship_table.item(rows[0].row(), 0)
        if item is None:
            return
        relation = self._relationship(str(item.data(_ROLE_ID)))
        if relation is None:
            return
        self._selected_relationship_id = str(relation["relationship_id"])
        self._block_fields = True
        self.relationship_from.setText(str(relation.get("from_interface_id", "")))
        self.relationship_to.setText(str(relation.get("to_interface_id", "")))
        self.relationship_kind.setText(str(relation.get("kind", "")))
        self._block_fields = False
        self._update_flow_editor_availability(self._operation != "idle")

    def _relationship_text_edited(self) -> None:
        if not self._block_fields and self._selected_relationship_id:
            self._mark_dirty()

    def _commit_relationship_fields(self) -> bool:
        if self._block_fields or self._selected_relationship_id is None:
            return True
        relation = self._relationship(self._selected_relationship_id)
        if relation is None:
            return True
        source, destination, kind = self.relationship_from.text().strip(), self.relationship_to.text().strip(), self.relationship_kind.text().strip()
        known = {item["interface_id"] for item in (self._batch() or {}).get("interfaces", [])}
        if source not in known or destination not in known or not kind:
            self._pending_invalid.add("界面关系")
            self._mark_dirty()
            return False
        self._pending_invalid.discard("界面关系")
        if (relation.get("from_interface_id"), relation.get("to_interface_id"), relation.get("kind")) != (source, destination, kind):
            relation.update(from_interface_id=source, to_interface_id=destination, kind=kind)
            self._update_relationship_row(relation)
            self._mark_dirty()
        return True

    # 后台响应绑定。
    def _load_succeeded(self, request_id: int, workspace: object) -> None:
        if request_id != self._active_load_request or self._operation != "loading":
            return
        self._active_load_request = None
        self._operation = "idle"
        self._set_busy(False)
        if not isinstance(workspace, dict) or not isinstance(workspace.get("batch"), dict):
            self._set_error("审核服务返回的工作区格式无效。")
            return
        self._workspace = copy.deepcopy(workspace)
        # 用户明确切换批次后，后续图入口必须解析新批次，不回到旧图。
        self._graph_batch_navigation_blocked = False
        self._last_open_graph_id = None
        self._last_open_graph_source = None
        self._dirty = False
        self._pending_invalid.clear()
        self._selected_step_id = None
        self._selected_relationship_id = None
        self._clear_step_fields()
        self._rebuild_loaded_tree()
        batch = self._batch()
        interfaces = batch.get("interfaces", []) if batch else []
        if interfaces:
            self._show_interface(str(interfaces[0]["interface_id"]))
        else:
            self.canvas.clear_canvas()
        self._populate_steps()
        self._populate_relationships()
        self.source_status.setText(f"来源：{self._workspace.get('source', 'untrusted_external')}（未授权）")
        self.revision_status.setText(f"修订：{self._workspace.get('revision', 0)}")
        self._update_dirty_status()
        self._set_status("已加载外部提议；编辑仅存在于本地审核草稿，未批准。")

    def _load_failed(self, request_id: int, message: str) -> None:
        if request_id != self._active_load_request or self._operation != "loading":
            return
        self._active_load_request = None
        self._operation = "idle"
        self._set_busy(False)
        self._set_error(f"读取批次失败：{message}")

    def _save_succeeded(self, request_id: int, workspace: object) -> None:
        binding = self._save_bindings.pop(request_id, None)
        if binding is None or self._operation != "saving" or self._workspace is None:
            return
        task_id, batch_id, source_ref, revision = binding
        if (self._workspace.get("task_id"), self._workspace.get("batch_id"), self._workspace.get("source_ref"), self._workspace.get("revision")) != (task_id, batch_id, source_ref, revision):
            self._operation = "idle"
            self._set_busy(False)
            self._set_status("已忽略不属于当前批次的保存响应。")
            return
        self._operation = "idle"
        self._set_busy(False)
        if not isinstance(workspace, dict) or not isinstance(workspace.get("batch"), dict):
            self._set_error("保存返回格式无效；当前编辑仍保留，未标记为已保存。")
            return
        if (workspace.get("task_id"), workspace.get("batch_id"), workspace.get("source_ref"), workspace.get("revision")) != (task_id, batch_id, source_ref, revision + 1):
            self._set_error("保存返回与请求修订不匹配；当前草稿未替换。")
            return
        self._workspace = copy.deepcopy(workspace)
        self._dirty = False
        self._pending_invalid.clear()
        self.revision_status.setText(f"修订：{self._workspace.get('revision', '?')}")
        self._update_dirty_status()
        self._set_status("审核修订已持久化；状态仍为 needs_human_review，未批准或执行。")

    def _save_failed(self, request_id: int, message: str) -> None:
        binding = self._save_bindings.pop(request_id, None)
        if binding is None or self._operation != "saving":
            return
        if self._workspace is None or (self._workspace.get("task_id"), self._workspace.get("batch_id"), self._workspace.get("source_ref"), self._workspace.get("revision")) != binding:
            self._operation = "idle"
            self._set_busy(False)
            self._set_status("已忽略不属于当前批次的保存失败响应。")
            return
        self._operation = "idle"
        self._set_busy(False)
        self._set_error(f"保存失败，草稿未丢失：{message}")

    def _track_job(self, job: FacadeJob) -> None:
        self._jobs.add(job)
        job.finished.connect(lambda: self._jobs.discard(job))
        job.finished.connect(job.deleteLater)

    # 呈现与辅助方法。
    def _rebuild_loaded_tree(self) -> None:
        if self._workspace is None:
            return
        self.batch_tree.blockSignals(True)
        self.batch_tree.clear()
        batch = self._batch() or {}
        root = QTreeWidgetItem([f"{batch.get('title', self._workspace['batch_id'])} · 当前修订"])
        root.setData(0, _ROLE_KIND, "batch")
        root.setData(0, _ROLE_BATCH, (self._workspace["task_id"], self._workspace["batch_id"]))
        self.batch_tree.addTopLevelItem(root)
        for interface in batch.get("interfaces", []):
            ui = QTreeWidgetItem([f"界面：{interface.get('meaning', interface.get('interface_id'))}"])
            ui.setData(0, _ROLE_KIND, "interface")
            ui.setData(0, _ROLE_ID, interface["interface_id"])
            root.addChild(ui)
            for region in interface.get("regions", []):
                name = region.get("name") or region.get("label") or region.get("kind") or region.get("type") or region["region_id"]
                child = QTreeWidgetItem([f"框：{name}"])
                child.setData(0, _ROLE_KIND, "region")
                child.setData(0, _ROLE_ID, region["region_id"])
                ui.addChild(child)
        root.setExpanded(True)
        self.batch_tree.blockSignals(False)

    def _populate_steps(self) -> None:
        batch = self._batch()
        self.step_table.setRowCount(0)
        if batch is None:
            self._clear_step_fields()
            return
        for row, step in enumerate(batch.get("steps", [])):
            self.step_table.insertRow(row)
            values = (step.get("step_id", ""), step.get("action_type", ""), step.get("target_region_id") or "—", step.get("expected_result", ""), step.get("stop_condition", ""))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(_ROLE_ID, step.get("step_id"))
                self.step_table.setItem(row, column, item)
        self.step_table.resizeColumnsToContents()

    def _populate_relationships(self) -> None:
        self.relationship_table.setRowCount(0)
        for row, relation in enumerate((self._batch() or {}).get("relationships", [])):
            self.relationship_table.insertRow(row)
            for column, value in enumerate((relation.get("relationship_id", ""), relation.get("from_interface_id", ""), relation.get("to_interface_id", ""), relation.get("kind", ""))):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(_ROLE_ID, relation.get("relationship_id"))
                self.relationship_table.setItem(row, column, item)
        self.relationship_table.resizeColumnsToContents()

    def _update_relationship_row(self, relation: dict[str, Any]) -> None:
        for row in range(self.relationship_table.rowCount()):
            item = self.relationship_table.item(row, 0)
            if item is None or item.data(_ROLE_ID) != relation.get("relationship_id"):
                continue
            for column, value in enumerate((relation.get("relationship_id", ""), relation.get("from_interface_id", ""), relation.get("to_interface_id", ""), relation.get("kind", ""))):
                table_item = self.relationship_table.item(row, column)
                if table_item is not None:
                    table_item.setText(str(value))
            return

    def _source_region_ids(self, step: dict[str, Any], start_state: str | None = None) -> set[str]:
        interface = self._interface(str(start_state if start_state is not None else step.get("start_state", "")))
        return {str(region["region_id"]) for region in (interface or {}).get("regions", [])}

    def _known_region_ids(self) -> set[str]:
        return {
            str(region["region_id"])
            for interface in (self._batch() or {}).get("interfaces", [])
            for region in interface.get("regions", [])
        }

    def _populate_step_targets(self, step: dict[str, Any]) -> None:
        interface = self._interface(str(step.get("start_state", "")))
        self._step_target_start_id = str(step.get("start_state", ""))
        self.step_target.blockSignals(True)
        self.step_target.clear()
        self.step_target.addItem("— 无目标（仅观察/停止）", None)
        for region in (interface or {}).get("regions", []):
            name = region.get("name") or region.get("label") or region["region_id"]
            self.step_target.addItem(str(name), region["region_id"])
        target = step.get("target_region_id")
        if step.get("action_type") in {"safe_stop", "observe"} and target is not None and target not in self._source_region_ids(step):
            region, _ = self._region(str(target))
            if region is not None:
                name = region.get("name") or region.get("label") or region["region_id"]
                self.step_target.addItem(f"{name}（跨界面保留）", target)
        self.step_target.blockSignals(False)

    def _update_step_row(self, step: dict[str, Any]) -> None:
        for row in range(self.step_table.rowCount()):
            identifier = self.step_table.item(row, 0)
            if identifier is None or identifier.data(_ROLE_ID) != step.get("step_id"):
                continue
            values = (step.get("step_id", ""), step.get("action_type", ""), step.get("target_region_id") or "—", step.get("expected_result", ""), step.get("stop_condition", ""))
            for column, value in enumerate(values):
                item = self.step_table.item(row, column)
                if item is not None:
                    item.setText(str(value))
            return

    def _clear_step_fields(self) -> None:
        self._block_fields = True
        self.step_table.clearSelection()
        self.step_action.clear()
        self.step_target.clear()
        self._step_target_start_id = None
        self.step_expected.clear()
        self.step_start.clear()
        self.step_arrival.clear()
        self.step_prerequisites.clear()
        self.step_stop.clear()
        self.scroll_direction.setCurrentIndex(0)
        self.scroll_wheel_clicks.setValue(self.scroll_wheel_clicks.minimum())
        self.text_content_kind.setCurrentIndex(0)
        self.text_literal.clear()
        self.text_variable.clear()
        self._text_literal_original = ""
        self._text_literal_dirty = False
        self.text_clear_existing.setChecked(True)
        self.text_sensitive.setChecked(False)
        self._update_scroll_controls()
        self.relationship_from.clear()
        self.relationship_to.clear()
        self.relationship_kind.clear()
        self._block_fields = False

    def _fill_region_fields(self, region: dict[str, Any] | None) -> None:
        self._block_fields = True
        enabled = region is not None and self._operation == "idle"
        for widget in (self.region_name, self.region_kind, self.region_meaning, *self.bbox_spins):
            widget.setEnabled(enabled)
        if region is None:
            self.selection_label.setText("未选择区域。选择左侧框或截图上的框以编辑。")
            self.region_name.clear(); self.region_kind.clear(); self.region_meaning.clear()
            for spin in self.bbox_spins:
                spin.setValue(spin.minimum())
        else:
            self.selection_label.setText(f"区域：{region['region_id']}（坐标以原始截图像素计）")
            self.region_name.setText(str(region.get("name") or region.get("label") or ""))
            self.region_kind.setText(str(region.get("kind") or region.get("type") or ""))
            self.region_meaning.setPlainText(str(region.get("meaning", "")))
            for spin, value in zip(self.bbox_spins, region["bbox"]):
                spin.setValue(float(value))
        self._block_fields = False

    def _fill_interface_field(self, interface: dict[str, Any] | None) -> None:
        self._block_fields = True
        enabled = interface is not None and self._operation == "idle"
        self.interface_meaning.setEnabled(enabled)
        self.interface_recognition_text.setEnabled(enabled)
        self.interface_meaning.setText(str(interface.get("meaning", "")) if interface else "")
        self.interface_recognition_text.setText(str(interface.get("recognition_text", "")) if interface else "")
        self._block_fields = False

    def _batch(self) -> dict[str, Any] | None:
        return self._workspace.get("batch") if self._workspace else None

    def _interface(self, interface_id: str) -> dict[str, Any] | None:
        batch = self._batch()
        return next((item for item in (batch or {}).get("interfaces", []) if item.get("interface_id") == interface_id), None)

    def _region(self, region_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        batch = self._batch()
        for interface in (batch or {}).get("interfaces", []):
            for region in interface.get("regions", []):
                if region.get("region_id") == region_id:
                    return region, interface
        return None, None

    def _step(self, step_id: str) -> dict[str, Any] | None:
        return next((item for item in (self._batch() or {}).get("steps", []) if item.get("step_id") == step_id), None)

    def _relationship(self, relationship_id: str) -> dict[str, Any] | None:
        return next((item for item in (self._batch() or {}).get("relationships", []) if item.get("relationship_id") == relationship_id), None)

    def _clamped_bbox(self, region_id: str, bbox: list[float]) -> list[float]:
        region, interface = self._region(region_id)
        if region is None or interface is None:
            return bbox
        screenshot = next((item for item in self._batch()["screenshots"] if item.get("screenshot_id") == interface.get("screenshot_id")), None)
        if screenshot is None:
            return bbox
        max_w, max_h = float(screenshot["width"]), float(screenshot["height"])
        x, y, width, height = (float(value) for value in bbox)
        width, height = max(1.0, min(width, max_w)), max(1.0, min(height, max_h))
        x, y = max(0.0, min(x, max_w - width)), max(0.0, min(y, max_h - height))
        return [round(x, 3), round(y, 3), round(width, 3), round(height, 3)]

    def _select_tree_region(self, region_id: str) -> None:
        def visit(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, _ROLE_KIND) == "region" and item.data(0, _ROLE_ID) == region_id:
                return item
            for index in range(item.childCount()):
                match = visit(item.child(index))
                if match:
                    return match
            return None
        for index in range(self.batch_tree.topLevelItemCount()):
            match = visit(self.batch_tree.topLevelItem(index))
            if match:
                self.batch_tree.blockSignals(True)
                self.batch_tree.setCurrentItem(match)
                self.batch_tree.blockSignals(False)
                return

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self.draftChanged.emit(True)
        self._update_dirty_status()

    def _update_dirty_status(self) -> None:
        graph_active = self._graph_active()
        graph_busy = self._graph_pane is not None and self._graph_pane.is_busy
        dirty = self._graph_pane.is_dirty if graph_active else self._dirty
        self.dirty_status.setText("状态：有未保存修改" if dirty else "状态：已保存 / 未修改")
        enabled = not graph_active and self._workspace is not None and self._dirty and self._operation == "idle"
        self.save_action.setEnabled(enabled or (graph_active and not graph_busy and dirty and self._operation == "idle"))
        self.save_button.setEnabled(enabled)
        self._update_step_order_controls()
        exact_enabled = not graph_active and self._operation == "idle" and self._workspace is not None and not self._dirty and bool(self._workspace.get("workflow_review_path"))
        self.exact_review_action.setEnabled(exact_enabled)
        self.exact_review_button.setEnabled(exact_enabled)
        library_enabled = self._operation == "idle" and not graph_busy
        self.workflow_library_action.setEnabled(library_enabled)
        self.workflow_library_button.setEnabled(library_enabled)
        self.relearn_action.setEnabled(not graph_active and self._operation == "idle")
        self.graph_review_action.setEnabled(library_enabled and callable(getattr(self.facade, "load_batch_graph_revision", None)))
        self.open_selected_graph_button.setEnabled(library_enabled and self._workspace is not None and not self._dirty and callable(getattr(self.facade, "load_batch_graph_revision", None)))

    def _update_flow_editor_availability(self, busy: bool) -> None:
        # 选中与后台状态共用同一可编辑规则，不重填或丢弃未保存字段。
        for widget in (self.step_action, self.step_target, self.step_expected, self.step_start,
                       self.step_arrival, self.step_prerequisites, self.step_stop):
            widget.setEnabled(not busy and self._selected_step_id is not None)
        for widget in (self.relationship_from, self.relationship_to, self.relationship_kind):
            widget.setEnabled(not busy and self._selected_relationship_id is not None)

    def _set_busy(self, busy: bool, text: str | None = None) -> None:
        busy = busy or (self._graph_pane is not None and self._graph_pane.is_busy)
        for page in (self._content_page, self._projects_page):
            if page is not None:
                page.setEnabled(not busy)
        for action in (self.pending_interfaces_action, self.interface_library_action, self.graph_library_action):
            action.setEnabled(not busy)
        self.model_setup_action.setEnabled(not busy and self._model_setup_available())
        self.connections_action.setEnabled(not busy and self._connections is not None)
        self.single_step_action.setEnabled(not busy and self._single_step is not None)
        self.application_startup_action.setEnabled(not busy and self._application_startup is not None)
        self.batch_tree.setEnabled(not busy)
        self.canvas.setEnabled(not busy)
        self.refresh_action.setEnabled(not busy)
        self.reload_button.setEnabled(not busy)
        self._fill_interface_field(self._interface(self._selected_interface_id) if self._selected_interface_id else None)
        if busy:
            self.interface_recognition_text.setEnabled(False)
        self._fill_region_fields(self._region(self._selected_region_id)[0] if self._selected_region_id else None)
        self.step_table.setEnabled(not busy)
        self.relationship_table.setEnabled(not busy)
        self._update_flow_editor_availability(busy)
        self._update_scroll_controls()
        if busy:
            self.scroll_direction.setEnabled(False)
            self.scroll_wheel_clicks.setEnabled(False)
        self._update_dirty_status()
        if text:
            self._set_status(text)

    def _set_status(self, text: str) -> None:
        self.status.showMessage(text)

    def _set_error(self, text: str) -> None:
        self._set_status(text)
        self.dirty_status.setText("状态：错误（编辑未自动清除）")

    def _confirm_discard(self, message: str) -> bool:
        result = QMessageBox.question(self, "未保存的审核修改", message, QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        return result == QMessageBox.StandardButton.Discard

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._projects_page is not None and self._projects_page.is_edit_busy:
            self._set_status("界面选择器仍在读取或保存；结束前不会关闭工作台资源。")
            event.ignore()
            return
        if self._host_closed:
            event.accept()
            return
        if self._graph_pane is not None and self._graph_pane.is_busy:
            self._set_status("流程图仍在读取或保存；结束前不会关闭审核资源。")
            event.ignore()
            return
        if self._operation in {"host_starting", "host_closing"}:
            self._set_status("宿主正在启动或停止；等待当前线程结束，不重复操作。")
            event.ignore()
            return
        if self._operation not in {"idle", "host_failed"} or self._jobs:
            QMessageBox.information(self, "后台任务仍在运行", "请等待读取或保存完成后再关闭，以保护审核修订。")
            event.ignore()
            return
        dirty = self._dirty or (self._graph_pane is not None and self._graph_pane.is_dirty) or any(
            page is not None and page.dirty for page in (self._content_page, self._projects_page))
        if dirty and not self._host_discard_confirmed and not self._confirm_discard("关闭将放弃当前未保存修改。是否关闭？"):
            event.ignore()
            return
        if self._projects_page is not None and self._projects_page.is_busy:
            self._projects_page.cancel_loading()
            self._close_after_project_load = True
            self._host_discard_confirmed = True
            self._set_status("正在结束项目读取，完成后自动关闭；数据资源尚未释放。")
            event.ignore()
            return
        if self._shutdown is not None:
            self._host_discard_confirmed = True
            event.ignore()
            self._start_host_job("host_closing", self._shutdown)
            return
        try:
            self.facade.close()
        except Exception as error:
            self._set_status(f"关闭审核资源失败：{error}")
            event.ignore()
            return
        event.accept()

    def _project_loading_changed(self, busy) -> None:
        if not busy and self._close_after_project_load and not self._delete_after_project_load:
            self._close_after_project_load = False
            QTimer.singleShot(0, self.close)

    def event(self, event):
        if (event.type() == QEvent.Type.DeferredDelete
                and self._projects_page is not None and self._projects_page.is_busy):
            self._delete_after_project_load = True
            self._projects_page.cancel_loading()
            QTimer.singleShot(0, self._finish_project_delete)
            return True
        return super().event(event)

    def _finish_project_delete(self):
        from shiboken6 import delete, isValid
        if not isValid(self):
            return
        if self._projects_page is not None and self._projects_page.is_busy:
            QTimer.singleShot(25, self._finish_project_delete)
            return
        delete(self)

    def _start_host_job(self, kind, operation) -> None:
        self._operation = kind
        self._host_job_succeeded = False
        self._set_busy(True, "正在启动本机接收服务…" if kind == "host_starting" else "正在停止接收并等待在途请求结束；尚未释放数据锁…")
        self._request_id += 1
        request_id = self._request_id
        job = make_job(request_id, operation, self)
        job.succeeded.connect(lambda result_id, result: self._host_job_result(result_id, result, kind))
        job.failed.connect(self._host_job_failed)
        self._jobs.add(job)
        job.finished.connect(lambda: self._host_job_finished(job, kind))
        job.finished.connect(job.deleteLater)
        job.start()

    def _host_job_result(self, request_id, result, kind) -> None:
        if request_id != self._request_id:
            return
        if kind == "host_starting":
            if not ConnectionManagerDialog._valid_view({"host": result, "connections": []}) or result["phase"] != "ready":
                self._host_job_failed(request_id, "宿主未返回确切就绪回执")
                return
        elif result is not None:
            self._host_job_failed(request_id, "宿主关闭回执无效")
            return
        self._host_job_succeeded = True

    def _host_job_failed(self, request_id, message) -> None:
        if request_id != self._request_id:
            return
        self._host_job_succeeded = False
        self._set_status("宿主操作失败或清理仍在进行；审核已暂停。请再次关闭以重试清理；不会切换到离线模式或提前释放数据锁。")

    def _host_job_finished(self, job, kind) -> None:
        self._jobs.discard(job)
        if self._host_job_succeeded and kind == "host_closing":
            self._host_closed = True
            self.close()
        elif self._host_job_succeeded:
            self._operation = "idle"
            self._set_busy(False, "本机接收服务已就绪；通过 Agent 连接管理授权。真实产品与会话尚未验证。")
            self.reload_batches()
            if callable(getattr(self.facade, "import_interface_content", None)):
                self._open_daily_on_ready = True
        else:
            self._operation = "host_failed"


def ensure_application() -> QApplication:
    """返回进程 QApplication，供 offscreen 集成测试复用。"""
    application = QApplication.instance() or QApplication([])
    # offscreen 平台不枚举 Windows 字体时，只注册已安装的系统字体。
    if os.environ.get("QT_QPA_PLATFORM", "").casefold() == "offscreen" and not QFontDatabase.families():
        font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc"
        if font_path.is_file():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
            family = next((item for item in families if item == "Microsoft YaHei UI"), families[0] if families else "")
            candidate = QFont(family, 10)
            raw_font = QRawFont.fromFont(candidate)
            if raw_font.isValid() and raw_font.supportsCharacter(0x4E2D):
                application.setFont(candidate)
    return application
