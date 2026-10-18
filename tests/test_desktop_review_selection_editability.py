"""实际选中行后可输入并持久保存，后台忙碌时仍禁用编辑。"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.window import ReviewMainWindow, ensure_application
from app.desktop_review.workspace import NativeReviewFacade
from tests.test_desktop_review_window import _batch, _wait_loaded, _wait_workers


@pytest.fixture
def review(tmp_path):
    app = ensure_application()
    store = AgentLinkStore(tmp_path / "inbox.json")
    token = "isolated-selection-reviewer-token"
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "task-1", "agent_name": "selection-test"})
    proposal = _batch()
    proposal["relationships"] = [{"relationship_id": "rel-1", "from_interface_id": "screen-1",
                                  "to_interface_id": "screen-1", "kind": "transition"}]
    proposal["steps"].append({**proposal["steps"][0], "step_id": "step-2", "expected_result": "second result"})
    for screenshot in proposal["screenshots"]:
        screenshot.pop("width"); screenshot.pop("height")
    service.agent_call(grant["token"], "submit_batch", proposal)
    root = tmp_path / "review-root"
    facade = NativeReviewFacade(service, token, root)
    window = ReviewMainWindow(facade)
    try:
        window.resize(1080, 680); window.show()
        window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
        _wait_loaded(window); _wait_workers(window)
        yield window, service, token, root
    finally:
        _wait_workers(window)
        window._dirty = False
        window._operation = "idle"
        window.close(); app.processEvents()
        facade.close(); store.close()


@pytest.mark.parametrize("kind", ["step", "relationship"])
def test_selected_row_enables_keyboard_edit_and_persists_revision(review, kind):
        window, service, token, root = review
        app = ensure_application()
        table = window.step_table if kind == "step" else window.relationship_table
        field = window.step_expected if kind == "step" else window.relationship_kind
        fields = ((window.step_action, window.step_target, window.step_expected, window.step_start,
                   window.step_arrival, window.step_prerequisites, window.step_stop) if kind == "step"
                  else (window.relationship_from, window.relationship_to, window.relationship_kind))
        scroll = window.findChild(QScrollArea, "propertiesScrollArea")
        scroll.ensureWidgetVisible(table, 0, 0); QTest.qWait(20)
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                         pos=table.visualItemRect(table.item(0, 0)).center())
        assert all(item.isEnabled() for item in fields), "selected row must enable editable fields after load is idle"
        scroll.ensureWidgetVisible(field, 0, 0); QTest.qWait(20)
        QTest.mouseClick(field.viewport() if kind == "step" else field, Qt.MouseButton.LeftButton)
        QTest.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(field, "reviewed value")
        assert window.is_dirty
        scroll.ensureWidgetVisible(window.save_button, 0, 0); QTest.qWait(20)
        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        _wait_workers(window)
        assert window.workspace["revision"] == 1, window.status.currentMessage()
        key, attribute = ("steps", "expected_result") if kind == "step" else ("relationships", "kind")
        assert window.workspace["batch"][key][0][attribute] == "reviewed value"
        # 模拟已有后台状态的选择通知，不能因此解锁编辑。
        window._operation = "loading"
        window._set_busy(True)
        table.clearSelection(); table.selectRow(0)
        assert all(not item.isEnabled() for item in fields)
        window._operation = "idle"
        window.close(); app.processEvents()
        reloaded = NativeReviewFacade(service, token, root)
        try:
            saved = reloaded.load_batch("task-1", "batch-1")
            assert saved["batch"][key][0][attribute] == "reviewed value"
            assert saved["review_status"] == "needs_human_review"
        finally:
            reloaded.close()


@pytest.mark.parametrize("field_name,key,want", [
    ("step_prerequisites", "prerequisites", ["edited prerequisite"]),
    ("step_stop", "stop_condition", "edited stop"),
])
def test_switching_steps_preserves_multiline_edit_in_saved_revision(review, field_name, key, want):
    window, service, token, root = review
    window.step_table.selectRow(0)
    field = getattr(window, field_name)
    scroll = window.findChild(QScrollArea, "propertiesScrollArea")
    scroll.ensureWidgetVisible(field, 0, 0); QTest.qWait(20)
    field.setFocus()
    QTest.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(field, want[0] if isinstance(want, list) else want)
    scroll.ensureWidgetVisible(window.step_table, 0, 0); QTest.qWait(20)
    QTest.mouseClick(window.step_table.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.step_table.visualItemRect(window.step_table.item(1, 0)).center())
    assert window.workspace["batch"]["steps"][0][key] == want, "row switch must not discard prior field edits"
    window.save_current(); _wait_workers(window)
    assert window.workspace["revision"] == 1
    window.close(); ensure_application().processEvents()
    reloaded = NativeReviewFacade(service, token, root)
    try:
        saved = reloaded.load_batch("task-1", "batch-1")
        assert saved["batch"]["steps"][0][key] == want
        assert saved["batch"]["steps"][1]["expected_result"] == "second result"
    finally:
        reloaded.close()


@pytest.mark.parametrize("kind", ["step", "relationship"])
def test_clear_selection_disables_editing_of_previous_object(review, kind):
    window, *_ = review
    table = window.step_table if kind == "step" else window.relationship_table
    field = window.step_stop if kind == "step" else window.relationship_kind
    table.selectRow(0)
    table.clearSelection()
    assert not field.isEnabled(), "no visible selection must not leave a stale editable object"
    assert (window._selected_step_id if kind == "step" else window._selected_relationship_id) is None
    assert not window.is_dirty


def test_invalid_step_draft_blocks_row_switch_instead_of_discarding_it(review):
    window, *_ = review
    window.step_table.selectRow(0)
    window.step_stop.setPlainText("")
    window.step_table.selectRow(1)
    assert window._selected_step_id == "step-1"
    assert [row.row() for row in window.step_table.selectionModel().selectedRows()] == [0]
    assert window.step_stop.toPlainText() == ""
    assert window.is_dirty


def test_invalid_relationship_draft_blocks_deselection(review):
    window, *_ = review
    window.relationship_table.selectRow(0)
    window.relationship_kind.clear()
    window.relationship_table.clearSelection()
    assert window._selected_relationship_id == "rel-1"
    assert [row.row() for row in window.relationship_table.selectionModel().selectedRows()] == [0]
    assert window.relationship_kind.text() == ""
    assert window.is_dirty
