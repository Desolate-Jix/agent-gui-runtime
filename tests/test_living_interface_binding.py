from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from app.desktop_review.interface_pane import InterfaceReviewPane
from app.desktop_review.content_library import InterfaceContentLibrary

_APP = QApplication.instance() or QApplication([])

def _snapshot(binding=None):
    return {"interface_id":"i1","version_id":"v1","revision":1,"content_sha256":"a"*64,"review_status":"draft","application_binding":binding,"source":{"task_id":"t"},"content":{"meaning":"首页","regions":[]}}

def test_optional_binding_collapsed_and_omitted_when_unchanged():
    pane=InterfaceReviewPane(type("F",(),{})()); pane.set_snapshot(_snapshot())
    assert not pane.binding_section.body.isVisible()
    assert "application_binding" not in pane._changes()

def test_changed_binding_is_included_and_review_button_is_hidden():
    pane=InterfaceReviewPane(type("F",(),{})()); pane.set_snapshot(_snapshot())
    pane.binding_name.setText("记事本"); pane.binding_identity.setText(r"C:\Windows\notepad.exe")
    assert pane.review_button.isHidden()
    assert pane._changes()["application_binding"]["display_name"] == "记事本"

def test_embedded_library_is_widget_and_exposes_dirty():
    class F:
        def list_interface_contents(self, *_args): return []
    library=InterfaceContentLibrary(F(), embedded=True)
    assert library.isModal() is False
    assert library.close_button.isHidden()
    assert library.dirty is False

def test_modified_filter_uses_revision_not_review_status():
    class F:
        def list_interface_contents(self, *_args): return []
        def list_batches(self): return []
    library=InterfaceContentLibrary(F())
    library.filter.setCurrentIndex(2)
    library._scan_incoming_interfaces = lambda: [
        {"interface_id":"new", "revision":1, "review_status":"draft", "content":{"meaning":"new"}},
        {"interface_id":"changed", "revision":2, "review_status":"reviewed", "content":{"meaning":"changed"}},
    ]
    values=library._load_values()
    assert [item["interface_id"] for item in values] == ["changed"]
