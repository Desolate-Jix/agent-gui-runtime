"""原生文本 mock 的进程内控件测试；不等同于真实 OS 输入验收。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from native_text_target import NativeTextTarget


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_text_target_records_keyboard_changes_and_current_value(tmp_path: Path, qt_app) -> None:
    evidence = tmp_path / "evidence"
    target = NativeTextTarget(evidence)
    target.show()
    qt_app.processEvents()
    assert target.windowTitle() == "Agent Review Test Target - Text"
    assert target.search_query.objectName() == "searchQuery"
    assert target.search_query.accessibleName() == "搜索词"
    assert target.search_query.text() == ""

    QTest.keyClicks(target.search_query, "mock text")
    QTest.keyClick(target.search_query, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(target.search_query, Qt.Key.Key_Backspace)
    qt_app.processEvents()

    assert target.current_value.text() == "当前内容："
    events = [json.loads(line) for line in (evidence / "state-transitions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events and events[-1]["state"] == "text" and events[-1]["value"] == ""
    assert all(event["pid"] == events[0]["pid"] for event in events)
    assert all(event["framework_action_proof"] is False for event in events)
    latest = json.loads((evidence / "latest-state.json").read_text(encoding="utf-8"))
    assert latest == events[-1]
    target.close()
