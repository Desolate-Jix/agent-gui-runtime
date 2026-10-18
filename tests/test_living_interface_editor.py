from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from app.desktop_review.interface_pane import InterfaceReviewPane

_APP = QApplication.instance() or QApplication([])

def _snapshot():
    return {"interface_id":"i1","version_id":"v1","revision":1,"content_sha256":"a"*64,"review_status":"draft","application_binding":None,"source":{"task_id":"t"},"content":{"meaning":"首页","recognition_text":"标题","regions":[{"region_id":"r1","bbox":[1,2,20,15],"name":"按钮","kind":"button","meaning":"说明","recognition_text":"确定"}]}}

def test_living_editor_exposes_region_fields_and_preserves_full_region_dict():
    pane=InterfaceReviewPane(type("F",(),{})()); pane.set_snapshot(_snapshot())
    pane.canvas.regionSelected.emit("r1")
    assert pane.region_name_edit.text()=="按钮"
    pane.region_name_edit.setText("新按钮")
    changes=pane._changes()
    assert changes["regions"][0]["name"]=="新按钮"
    assert changes["regions"][0]["bbox"]==[1,2,20,15]

def test_selecting_region_does_not_copy_previous_region_metadata():
    snap = _snapshot()
    snap["content"]["regions"].append({"region_id":"r2","bbox":[30,2,10,10],"name":"第二框","kind":"label","meaning":"第二说明","recognition_text":"第二"})
    pane=InterfaceReviewPane(type("F",(),{})()); pane.set_snapshot(snap)
    pane.canvas.regionSelected.emit("r1")
    pane.canvas.regionSelected.emit("r2")
    assert pane._regions[0]["name"] == "按钮"
    assert pane._regions[1]["name"] == "第二框"

def test_living_editor_can_add_and_remove_region():
    pane=InterfaceReviewPane(type("F",(),{})()); pane.set_snapshot(_snapshot())
    pane.add_region(); assert len(pane._regions)==2
    pane.remove_selected_region(); assert len(pane._regions)==1
