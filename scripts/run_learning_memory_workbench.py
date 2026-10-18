"""轻量记忆工作台；只附着已有执行宿主，不创建宿主或模型。"""
from pathlib import Path
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Edit learned workflows and attach an existing execution session")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--session-dir", type=Path, help="Existing Instant session; runtime attachment is explicit in the workbench")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.learning_memory.workbench_i18n import ui, translated_dialog, tr, bind_text, initialize_i18n, language_manager
    from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
        QTabWidget, QToolBar, QMessageBox, QPlainTextEdit, QVBoxLayout)
    from PySide6.QtCore import QSize, Qt
    from app.desktop_review.content_library import InterfaceContentLibrary
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    from app.learning_memory.editor_client import MemoryEditorClient
    from app.learning_memory.workflow_steps_pane import WorkflowStepsPane
    from app.learning_memory.workbench_navigation import WorkbenchTabBar, system_motion_enabled
    from app.learning_memory.workbench_theme import apply_workbench_theme
    from app.learning_memory.workbench_icons import workbench_icon
    from app.learning_memory.workbench_typography import configure_workbench_font
    from app.learning_memory.workbench_window import WorkbenchWindow
    from app.learning_memory.workbench_popup_ownership import prepare_owned_popup

    class MemoryWindow(WorkbenchWindow):
        def __init__(self, library):
            super().__init__()
            self.library = library
            ui(self.setWindowTitle, tr('Agent Review · 执行记忆草稿（未验收）'))
            self.resize(1380, 900)
            self.tabs = QTabWidget()
            self.tabs.setObjectName('memoryNavigation')
            self.tabs.setTabBar(WorkbenchTabBar())
            self.tabs.setIconSize(QSize(18, 18))
            self.steps = WorkflowStepsPane(library, args.session_dir)
            self.projects = WorkflowProjectsPane(library)
            self.interfaces = InterfaceContentLibrary(library, embedded=True, task_id="memory-local")
            self.interfaces.pane.targetRuleRequested.connect(self.open_target_rule)
            ui(self.tabs.addTab, self.steps, workbench_icon('steps'), tr('任务步骤'))
            ui(self.tabs.addTab, self.projects, workbench_icon('graph'), tr('流程项目'))
            ui(self.tabs.addTab, self.interfaces, workbench_icon('library'), tr('独立界面库'))
            self.setCentralWidget(self.tabs)
            toolbar = QToolBar()
            toolbar.setObjectName('memoryHeader')
            toolbar.setMovable(False)
            toolbar.setFloatable(False)
            toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toolbar.setIconSize(QSize(16, 16))
            self.addToolBar(toolbar)
            ui(toolbar.addAction, workbench_icon('refresh'), tr("刷新项目"), self.projects.refresh)
            ui(toolbar.addAction, workbench_icon('check'), tr("采用所选界面最新版本"), self.adopt_interface)
            toolbar.addSeparator()
            ui(toolbar.addAction, workbench_icon('crop'), tr("局部截图模板"), self.open_templates)
            ui(toolbar.addAction, workbench_icon('image'), tr("采用新截图"), self.open_source_adoption)
            view = ui(self.chrome_menu.addMenu, tr('视图'))
            prepare_owned_popup(self, view)
            self.reduced_motion_action = ui(view.addAction, tr('减少动画'))
            self.reduced_motion_action.setCheckable(True)
            self.reduced_motion_action.setChecked(not system_motion_enabled())
            self.reduced_motion_action.toggled.connect(lambda reduced: self.tabs.tabBar().set_motion_enabled(not reduced))
            developer = ui(self.chrome_menu.addMenu, tr('开发者'))
            prepare_owned_popup(self, developer)
            ui(developer.addAction, tr('查看记忆连接与当前版本'), self.show_developer_info)
            settings = ui(self.chrome_menu.addMenu, tr("设置"))
            prepare_owned_popup(self, settings)
            languages = ui(settings.addMenu, tr("语言"))
            prepare_owned_popup(self, languages)
            from PySide6.QtGui import QActionGroup
            self.language_actions = {}
            group = QActionGroup(self)
            group.setExclusive(True)
            for locale, label in (("zh-CN", "简体中文"), ("en-US", "English")):
                action = languages.addAction(label)
                action.setCheckable(True)
                action.setChecked(language_manager().language == locale)
                group.addAction(action)
                action.triggered.connect(lambda checked=False, value=locale: language_manager().set_language(value))
                self.language_actions[locale] = action
            language_manager().languageChanged.connect(self._language_changed)
            ui(self.statusBar().showMessage, tr('编辑后保存确切版本；在运行页连接已有会话并开始，关闭工作台不停止宿主。'))
            apply_workbench_theme(self)
            self.tabs.tabBar().setFocus(Qt.FocusReason.OtherFocusReason)

        def _language_changed(self, locale):
            for value, action in self.language_actions.items():
                action.setChecked(value == locale)

        def open_target_rule(self, link):
            try:
                if self.steps.open_target_link(link):
                    self.tabs.setCurrentWidget(self.steps)
                else:
                    self.interfaces.error.setText(self.steps.status.text())
            except (ValueError, OSError, RuntimeError) as error:
                ui(self.interfaces.error.setText, tr('目标规则读取失败：{v0}', v0=error))

        def open_templates(self):
            self.tabs.setCurrentWidget(self.interfaces)
            pane = self.interfaces.pane
            if pane._target_link is not None:
                translated_dialog(QMessageBox.information, self, tr('选择界面标注'), tr('请先在上方切换到界面标注。步骤目标使用它自己的动作截图，通过定位规则入口修改。'))
                return
            if pane.dirty:
                translated_dialog(QMessageBox.information, self, tr('先保存修改'), tr('请先保存或放弃识别框修改；模板必须绑定已保存的确切版本。'))
                return
            snapshot = pane.snapshot
            if not snapshot:
                translated_dialog(QMessageBox.information, self, tr('选择界面'), tr('请先打开独立界面，再选择需要保存为模板的框。'))
                return
            if snapshot["source"].get("kind") != "execution_memory_v1":
                translated_dialog(QMessageBox.information, self, tr('需要新学习内容'), tr('请选择由当前执行记忆记录的界面；不使用旧演示内容。'))
                return
            from app.learning_memory.template_dialog import ControlTemplateDialog
            dialog = ControlTemplateDialog(self.library, snapshot, pane._selected_region_id, self)
            dialog.exec()

        def open_source_adoption(self):
            self.tabs.setCurrentWidget(self.interfaces)
            pane = self.interfaces.pane
            if pane.dirty or not pane.snapshot:
                translated_dialog(QMessageBox.information, self, tr('选择已保存界面'), tr('请先打开独立界面并保存或放弃当前修改。'))
                return
            from app.learning_memory.source_dialog import SourceAdoptionDialog
            dialog = SourceAdoptionDialog(self.library, pane.snapshot, self)
            dialog.exec()
            if dialog.adopted_snapshot:
                pane.set_snapshot(dialog.adopted_snapshot)
                self.interfaces._saved(dialog.adopted_snapshot)

        def show_developer_info(self):
            import json
            snapshot = self.interfaces.pane.snapshot or {}
            project = self.projects.snapshot or {}
            value = {"mode": "memory_editor_source_draft", "runtime_verified": False,
                "data_dir": str(args.data_dir.resolve()),
                "memory_library": str(args.data_dir.resolve() / "memory-library"),
                "library_lock": "per_service_call", "execution_host_started_by_editor": False,
                "selected_interface": {key: snapshot.get(key) for key in
                    ("interface_id", "version_id", "revision", "content_sha256")},
                "selected_project": {key: project.get(key) for key in
                    ("logical_workflow_id", "source_sha256")}}
            dialog = QDialog(self); ui(dialog.setWindowTitle, tr('开发者 · 记忆入口（只读）')); dialog.resize(760, 540)
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit(); text.setReadOnly(True)
            ui(text.setPlainText, tr("Agent 使用已配置的 Instant MCP，数据目录必须与这里一致。\n"
                "此窗口只显示本地编辑状态，不证明 MCP 在线或执行宿主已启动。\n"
                "入口与契约见 AGENT_GUIDE.md、docs/verification/LEARNING_RECEIPT_RECORDING_DRAFT.md。\n\n")
                + json.dumps(value, ensure_ascii=False, indent=2))
            layout.addWidget(text)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
            dialog.exec()

        def adopt_interface(self):
            pane = self.projects
            if pane.is_busy or pane.dirty or self.interfaces.pane.dirty:
                translated_dialog(QMessageBox.information, self, tr('暂不能采用'), tr('请先完成读取，并保存或放弃当前修改。'))
                return
            if not pane.snapshot or not pane._node_id:
                translated_dialog(QMessageBox.information, self, tr('选择界面'), tr('请先在流程图中选择一个已学习界面节点。'))
                return
            try:
                updated = self.library.adopt_project_interface(pane.snapshot["logical_workflow_id"],
                    pane._node_id, pane.snapshot["source_sha256"])
                pane._install(updated)
            except Exception as error:
                translated_dialog(QMessageBox.warning, self, tr('采用失败'), str(error))

        def closeEvent(self, event):
            if self.interfaces.pane.is_busy:
                self.interfaces.pane.cancel_loading()
                ui(self.statusBar().showMessage, tr('正在结束界面证据读取，请稍后再关闭。'))
                event.ignore()
                return
            if self.steps.is_busy:
                self.steps.cancel_loading()
                ui(self.statusBar().showMessage, tr('正在结束任务步骤读取，请稍后再关闭。'))
                event.ignore()
                return
            if self.projects.is_busy:
                self.projects.cancel_loading()
                ui(self.statusBar().showMessage, tr('正在结束后台读取，请稍后再关闭。'))
                event.ignore()
                return
            if self.steps.dirty or self.projects.dirty or self.interfaces.pane.dirty:
                ui(self.statusBar().showMessage, tr('有未保存修改；请先保存或放弃，再关闭。'))
                event.ignore()
                return
            self.steps.run_panel.close_client()
            super().closeEvent(event)

    application = QApplication.instance() or QApplication(sys.argv[:1])
    initialize_i18n(application)
    configure_workbench_font(application)
    with MemoryEditorClient(args.data_dir.resolve() / "memory-library") as library:
        window = MemoryWindow(library)
        window.show()
        from app.desktop_review.window_placement import fit_initial_window
        fit_initial_window(window)
        return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
