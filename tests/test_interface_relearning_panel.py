"""使用真实 façade 验证重学面板的入口、范围及重试。"""
from app.desktop_review.interface_pane import InterfaceReviewPane
from app.desktop_review.interface_relearning_dialog import InterfaceRelearningDialog
from tests.test_interface_relearning_journey import journey, APP


def test_button_disabled_dirty_and_readonly(journey):
    facade, snap, _, _, _ = journey
    pane = InterfaceReviewPane(facade)
    try:
        pane.set_snapshot(snap)
        assert pane.relearn_button.isEnabled()
        pane.meaning_edit.setText("未保存的人工修改")
        assert not pane.relearn_button.isEnabled()
        pane.discard_changes()
        pane.set_read_only(True)
        assert not pane.relearn_button.isEnabled()
    finally:
        pane.close()


def test_relearning_waiting_scope_and_stable_request_key(journey):
    facade, snap, _, _, _ = journey
    region_id = snap["content"]["regions"][0]["region_id"]
    dialog = InterfaceRelearningDialog(facade, snap, region_id)
    try:
        dialog.message.setText("只修正这个框")
        dialog.create_issue()
        issue = dialog.issue
        assert issue["status"] == "open" and issue["region_ids"] == [region_id]
        assert dialog.candidates.count() == 0 and not dialog.adopt_button.isEnabled()
        count = len(facade.list_interface_relearning(snap["interface_id"]))
        dialog.create_issue()
        assert len(facade.list_interface_relearning(snap["interface_id"])) == count
        dialog.scope.setCurrentIndex(0)
        dialog.create_issue()
        assert dialog.issue["region_ids"] == []
        assert len(facade.list_interface_relearning(snap["interface_id"])) == count + 1
    finally:
        dialog.close()


def test_failed_adoption_retry_keeps_exact_key_after_content_write(journey, monkeypatch):
    facade, snap, issue, _, dialog = journey
    import app.desktop_review.interface_relearning as module
    original = module._write_immutable
    failed = False
    def once(path, payload):
        nonlocal failed
        if path.parent.name == "decisions" and not failed:
            failed = True
            raise OSError("synthetic decision write failure")
        return original(path, payload)
    monkeypatch.setattr(module, "_write_immutable", once)
    dialog.compare()
    dialog.adopt()
    assert "失败" in dialog.status.text()
    assert facade.load_interface_content(snap["interface_id"])["revision"] == snap["revision"] + 1
    dialog.adopt()
    assert facade.read_interface_relearning(issue["issue_id"])["status"] == "adopted"
    assert facade.load_interface_content(snap["interface_id"])["revision"] == snap["revision"] + 1
