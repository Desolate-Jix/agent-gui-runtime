"""轻量记忆原生编辑入口；不启动 Agent、模型或执行宿主。"""
from pathlib import Path
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Edit the execution-memory draft; no desktop input is dispatched")
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QMainWindow,
        QTabWidget, QToolBar, QMessageBox, QPlainTextEdit, QVBoxLayout)
    from app.desktop_review.content_library import InterfaceContentLibrary
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    from app.learning_memory.editor_client import MemoryEditorClient

    class MemoryWindow(QMainWindow):
        def __init__(self, library):
            super().__init__()
            self.library = library
            self.setWindowTitle("Agent Review · 执行记忆草稿（未验收）")
            self.resize(1380, 900)
            self.tabs = QTabWidget()
            self.projects = WorkflowProjectsPane(library)
            self.interfaces = InterfaceContentLibrary(library, embedded=True, task_id="memory-local")
            self.tabs.addTab(self.projects, "流程项目")
            self.tabs.addTab(self.interfaces, "独立界面库")
            self.setCentralWidget(self.tabs)
            toolbar = QToolBar()
            self.addToolBar(toolbar)
            toolbar.addAction("刷新项目", self.projects.refresh)
            toolbar.addAction("采用所选界面最新版本", self.adopt_interface)
            toolbar.addAction("局部截图模板", self.open_templates)
            toolbar.addAction("采用新截图", self.open_source_adoption)
            developer = self.menuBar().addMenu("开发者")
            developer.addAction("查看记忆连接与当前版本", self.show_developer_info)
            self.statusBar().showMessage("仅编辑记忆，不操作外部软件。界面版本固定；保存不需要定稿或批准。")

        def open_templates(self):
            self.tabs.setCurrentWidget(self.interfaces)
            pane = self.interfaces.pane
            if pane.dirty:
                QMessageBox.information(self, "先保存修改", "请先保存或放弃识别框修改；模板必须绑定已保存的确切版本。")
                return
            snapshot = pane.snapshot
            if not snapshot:
                QMessageBox.information(self, "选择界面", "请先打开独立界面，再选择需要保存为模板的框。")
                return
            if snapshot["source"].get("kind") != "execution_memory_v1":
                QMessageBox.information(self, "需要新学习内容", "请选择由当前执行记忆记录的界面；不使用旧演示内容。")
                return
            from app.learning_memory.template_dialog import ControlTemplateDialog
            dialog = ControlTemplateDialog(self.library, snapshot, pane._selected_region_id, self)
            dialog.exec()

        def open_source_adoption(self):
            self.tabs.setCurrentWidget(self.interfaces)
            pane = self.interfaces.pane
            if pane.dirty or not pane.snapshot:
                QMessageBox.information(self, "选择已保存界面", "请先打开独立界面并保存或放弃当前修改。")
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
            dialog = QDialog(self); dialog.setWindowTitle("开发者 · 记忆入口（只读）"); dialog.resize(760, 540)
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit(); text.setReadOnly(True)
            text.setPlainText("Agent 使用已配置的 Instant MCP，数据目录必须与这里一致。\n"
                "此窗口只显示本地编辑状态，不证明 MCP 在线或执行宿主已启动。\n"
                "入口与契约见 AGENT_GUIDE.md、docs/verification/LEARNING_RECEIPT_RECORDING_DRAFT.md。\n\n"
                + json.dumps(value, ensure_ascii=False, indent=2))
            layout.addWidget(text)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
            dialog.exec()

        def adopt_interface(self):
            pane = self.projects
            if pane.is_busy or pane.dirty or self.interfaces.pane.dirty:
                QMessageBox.information(self, "暂不能采用", "请先完成读取，并保存或放弃当前修改。")
                return
            if not pane.snapshot or not pane._node_id:
                QMessageBox.information(self, "选择界面", "请先在流程图中选择一个已学习界面节点。")
                return
            try:
                updated = self.library.adopt_project_interface(pane.snapshot["logical_workflow_id"],
                    pane._node_id, pane.snapshot["source_sha256"])
                pane._install(updated)
            except Exception as error:
                QMessageBox.warning(self, "采用失败", str(error))

        def closeEvent(self, event):
            if self.projects.is_busy:
                self.projects.cancel_loading()
                self.statusBar().showMessage("正在结束后台读取，请稍后再关闭。")
                event.ignore()
                return
            if self.projects.dirty or self.interfaces.pane.dirty:
                self.statusBar().showMessage("有未保存修改；请先保存或放弃，再关闭。")
                event.ignore()
                return
            super().closeEvent(event)

    application = QApplication.instance() or QApplication(sys.argv[:1])
    with MemoryEditorClient(args.data_dir.resolve() / "memory-library") as library:
        window = MemoryWindow(library)
        window.show()
        from app.desktop_review.window_placement import fit_initial_window
        fit_initial_window(window)
        return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
