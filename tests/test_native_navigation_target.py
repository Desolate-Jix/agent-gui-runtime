"""NativeNavigationTarget 的隔离 Qt 契约测试。"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from native_navigation_target import NativeNavigationTarget


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_initial_list_state_and_controls(qt_app, tmp_path: Path):
    target = NativeNavigationTarget(tmp_path)
    assert target.state_name == "list"
    assert target.windowTitle() == "Agent Review Test Target - List"
    assert target.open_button.text() == "查看示例详情"
    assert target.back_button.text() == "返回列表"
    target.close()


def test_button_navigation_records_list_detail_list(qt_app, tmp_path: Path):
    target = NativeNavigationTarget(tmp_path)
    QTest.mouseClick(target.open_button, Qt.MouseButton.LeftButton)
    QTest.qWait(1)
    assert target.state_name == "detail"
    assert target.windowTitle() == "Agent Review Test Target - Detail"
    QTest.mouseClick(target.back_button, Qt.MouseButton.LeftButton)
    QTest.qWait(1)
    assert target.state_name == "list"
    events = [json.loads(line) for line in (tmp_path / "state-transitions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["state"] for event in events] == ["list", "detail", "list"]
    assert all(event["source"] == "test_target_widget" and event["framework_action_proof"] is False for event in events)
    latest = json.loads((tmp_path / "latest-state.json").read_text(encoding="utf-8"))
    assert latest["state"] == "list" and latest["source_file_sha256"]
    target.close()


def test_import_has_no_qapplication_or_window_side_effect():
    script = "import sys; from PySide6.QtWidgets import QApplication; before=QApplication.instance(); import native_navigation_target; assert before is None and QApplication.instance() is None; print('clean')"
    env = {**__import__('os').environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    env.pop("PYTHONUTF8", None)
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parent, env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "clean"


def test_cli_refuses_existing_evidence_dir_without_append(tmp_path: Path):
    evidence = tmp_path / "existing"
    evidence.mkdir()
    sentinel = evidence / "state-transitions.jsonl"
    sentinel.write_text("sentinel\\n", encoding="utf-8")
    env = {**__import__('os').environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    env.pop("PYTHONUTF8", None)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("native_navigation_target.py")), "--evidence-dir", str(evidence)],
        cwd=Path(__file__).parent,
        env=env,
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode != 0
    assert "FileExistsError" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "sentinel\\n"
