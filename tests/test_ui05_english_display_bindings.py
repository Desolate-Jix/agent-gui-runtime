"""本轮界面库状态与反馈预览标题的离屏语言回归；不读取真实库或执行动作。"""
from copy import deepcopy

import pytest
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QApplication, QGroupBox

from app.desktop_review.content_library import InterfaceContentLibrary
from app.desktop_review.interface_relearning_dialog import InterfaceRelearningDialog
from app.learning_memory.workbench_i18n import initialize_i18n


@pytest.fixture
def localized_app(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / "workbench-preferences.json", "en-US")
    yield app, manager
    manager.set_language("zh-CN", persist=False)


class LibraryReadFacade:
    def __init__(self):
        self.values = []
        self.reads = 0

    def list_interface_contents(self, reviewed_only, task_id):
        assert reviewed_only is True and task_id == "display-only"
        self.reads += 1
        return deepcopy(self.values)


@pytest.mark.parametrize(
    "learning_status,origin_status,english,chinese",
    [
        ("learned", "new", "New learning", "新学内容"),
        ("learned", "modified", "Edited", "有修改"),
        ("observation_only", "new", "Original observation", "原始观察"),
    ],
)
def test_library_status_refresh_and_saved_follow_language_without_changing_content(
    localized_app, learning_status, origin_status, english, chinese
):
    app, manager = localized_app
    facade = LibraryReadFacade()
    library = InterfaceContentLibrary(facade, reviewed_only=True, task_id="display-only", embedded=True)
    snapshot = {
        "interface_id": "display-interface",
        "revision": 1,
        "learning_status": learning_status,
        "origin_status": origin_status,
        "content": {"meaning": "用户含义：新学内容", "regions": []},
    }
    try:
        facade.values = [deepcopy(snapshot)]
        # 本例只核对列表显示；阻止选择触发不属于本例的截图证据读取。
        with QSignalBlocker(library.items), QSignalBlocker(library.filter):
            library.filter.setCurrentIndex(3 if learning_status == "observation_only" else 0)
            library.refresh()
        item = library.items.currentItem()
        assert item is not None
        assert item.text() == f"用户含义：新学内容\n{english} · Revision 1"

        saved = {**deepcopy(snapshot), "revision": 2}
        library._saved(saved)
        read_count = facade.reads
        for language, state, revision_word in (
            ("zh-CN", chinese, "修订"),
            ("en-US", english, "Revision"),
        ):
            manager.set_language(language, persist=False)
            app.processEvents()
            assert item.text() == f"用户含义：新学内容\n{state} · {revision_word} 2"
            assert item.data(Qt.ItemDataRole.UserRole) == saved
            assert library.items.currentItem() is item
            assert facade.values == [snapshot]
            assert facade.reads == read_count
    finally:
        library.close()
        library.deleteLater()
        app.processEvents()


class FeedbackReadFacade:
    def __init__(self):
        self.reads = 0

    def list_interface_relearning(self, interface_id):
        assert interface_id == "display-interface"
        self.reads += 1
        return []


def test_feedback_preview_titles_follow_language_without_resetting_comparison(localized_app):
    app, manager = localized_app
    facade = FeedbackReadFacade()
    snapshot = {"interface_id": "display-interface", "content": {"regions": []}}
    dialog = InterfaceRelearningDialog(facade, snapshot)
    try:
        dialog.message.setText("用户反馈：基线（只读）")
        dialog.issue = {"issue_id": "existing-issue"}
        dialog.candidate_id = "existing-candidate"
        dialog._compared = True
        dialog._compared_identity = ("existing-issue", "existing-candidate")
        dialog.adopt_button.setEnabled(True)
        expected_identity = deepcopy(dialog.issue)
        boxes = dialog.findChildren(QGroupBox)
        assert len(boxes) == 2
        for language, titles in (
            ("en-US", ["Baseline (read-only)", "Candidate (read-only)"]),
            ("zh-CN", ["基线（只读）", "候选（只读）"]),
            ("en-US", ["Baseline (read-only)", "Candidate (read-only)"]),
        ):
            manager.set_language(language, persist=False)
            app.processEvents()
            assert [box.title() for box in boxes] == titles
            assert dialog.message.text() == "用户反馈：基线（只读）"
            assert dialog.snapshot == snapshot and dialog.issue == expected_identity
            assert dialog.candidate_id == "existing-candidate"
            assert dialog._compared is True
            assert dialog._compared_identity == ("existing-issue", "existing-candidate")
            assert dialog.adopt_button.isEnabled()
            assert facade.reads == 1
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
