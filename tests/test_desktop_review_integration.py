"""用真实 Qt 控件贯通 inbox、人工编辑和既有审核保存；不操作外部软件。"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QWidget

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from app.desktop_review.window import ReviewMainWindow, ensure_application


def _wait(app: QApplication, predicate, timeout_ms: int = 8000) -> None:
    for _ in range(timeout_ms // 10):
        app.processEvents()
        if predicate():
            return
        # 显式释放 GIL，让真实 Python 后台作业运行；Qt 的 C++ 等待会饿死它。
        time.sleep(0.01)
    raise AssertionError("native review integration did not reach its expected state")


def _synthetic_batch(app: QApplication) -> dict:
    page = QWidget()
    page.resize(820, 460)
    page.setStyleSheet("QWidget {background: #f8fafc; color: #172033; font: 14px 'Microsoft YaHei UI';} QTableWidget {background: white;} QPushButton {background: #2563eb; color: white; border-radius: 5px;}")
    heading = QLabel("文件工作区 · 合成验收界面", page)
    heading.setGeometry(28, 20, 650, 35)
    heading.setStyleSheet("font-size: 22px; font-weight: 600;")
    notice = QLabel("用于验证审核界面。不是用户文件，不会操作外部软件。", page)
    notice.setGeometry(28, 61, 740, 28)
    table = QTableWidget(3, 3, page)
    table.setGeometry(28, 110, 762, 228)
    table.setHorizontalHeaderLabels(["文件名称", "类型", "状态"])
    table.setColumnWidth(0, 350)
    table.setColumnWidth(1, 175)
    table.setColumnWidth(2, 175)
    for row, values in enumerate([("操作流程说明", "文档", "待检查"), ("界面元素列表", "数据", "已识别"), ("步骤关联记录", "流程", "待审核")]):
        for col, value in enumerate(values):
            table.setItem(row, col, QTableWidgetItem(value))
    action = QPushButton("查看详情", page)
    action.setGeometry(622, 366, 168, 48)
    page.show()
    app.processEvents()
    image = page.grab()
    pixel_scale = image.width() / page.width()
    target_rect = action.geometry()
    target_bbox = [value * pixel_scale for value in (target_rect.x(), target_rect.y(), target_rect.width(), target_rect.height())]
    data = QByteArray()
    buffer = QBuffer(data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    page.close()
    page.deleteLater()
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "native-qa-key",
        "batch_id": "native-qa-batch", "title": "文件详情流程 · 合成验收",
        "learning_outcome": "completed",
        "screenshots": [{"screenshot_id": "screen-list", "png_base64": base64.b64encode(bytes(data)).decode("ascii")}],
        "interfaces": [{"interface_id": "file-list", "screenshot_id": "screen-list", "meaning": "文件列表界面", "regions": [{"region_id": "details-button", "bbox": target_bbox, "name": "查看详情", "kind": "button", "meaning": "打开所选文件的详情"}]}],
        "relationships": [],
        "steps": [{"step_id": "observe-list", "action_type": "observe", "target_region_id": None, "start_state": "file-list", "arrival_state": "file-list", "prerequisites": ["列表可见"], "expected_result": "检查列表含义与详情入口", "stop_condition": "仅审核，不执行"}],
        "issues": [],
    }


def test_native_controls_save_real_review_and_reload_without_mutating_original(tmp_path: Path):
    app = ensure_application()
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, "integration-reviewer-fixture")
    grant = service.reviewer_call("integration-reviewer-fixture", "create_connection", {"task_id": "qa-task", "agent_name": "合成验收，不是真实 Agent"})
    service.agent_call(grant["token"], "submit_batch", _synthetic_batch(app))
    original = copy.deepcopy(service.reviewer_call("integration-reviewer-fixture", "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})["batch"])
    root = tmp_path / "review-data"
    facade = NativeReviewFacade(service, "integration-reviewer-fixture", root)
    window = ReviewMainWindow(facade)
    window.resize(1450, 950)
    window.show()
    try:
        _wait(app, lambda: window.batch_tree.topLevelItemCount() > 0)
        item = window.batch_tree.topLevelItem(0)
        QTest.mouseClick(window.batch_tree.viewport(), Qt.MouseButton.LeftButton, pos=window.batch_tree.visualItemRect(item).center())
        _wait(app, lambda: window.workspace is not None)
        interface = window.batch_tree.topLevelItem(0).child(0)
        interface.setExpanded(True)
        app.processEvents()
        region = interface.child(0)
        QTest.mouseClick(window.batch_tree.viewport(), Qt.MouseButton.LeftButton, pos=window.batch_tree.visualItemRect(region).center())
        _wait(app, lambda: window.region_meaning.isEnabled())
        window.region_meaning.setPlainText("人工修订：只查看所选条目的详情，不执行提交")
        assert window.is_dirty
        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        _wait(app, lambda: window.workspace is not None and window.workspace["revision"] == 1)
        assert not window.is_dirty
        saved = window.workspace
        assert saved["batch"]["interfaces"][0]["regions"][0]["meaning"].startswith("人工修订")
        review = json.loads(Path(saved["workflow_review_path"]).read_text(encoding="utf-8"))
        assert review["artifact_is_authorization"] is False
        assert review["execute_binding_enabled"] is False
        assert all(node["reviewed_by_human"] is False for node in review["nodes"])
        out_dir = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
        out_dir.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(out_dir / "native-review-integrated.png"))
        _wait(app, lambda: not window._jobs)
        assert window.close()
        reloaded = NativeReviewFacade(service, "integration-reviewer-fixture", root)
        try:
            assert reloaded.load_batch("qa-task", "native-qa-batch")["batch"] == saved["batch"]
        finally:
            reloaded.close()
        current_original = service.reviewer_call("integration-reviewer-fixture", "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})["batch"]
        assert current_original == original
        store.close()
        expected_hash = hashlib.sha256(json.dumps(saved["batch"], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        child = subprocess.run(
            [sys.executable, "-c", "\n".join([
                "import hashlib, json, sys",
                "from pathlib import Path",
                "from app.agent_link import AgentLinkService, AgentLinkStore",
                "from app.desktop_review.workspace import NativeReviewFacade",
                "store = AgentLinkStore(Path(sys.argv[1]))",
                "facade = NativeReviewFacade(AgentLinkService(store, 'integration-reviewer-fixture'), 'integration-reviewer-fixture', Path(sys.argv[2]))",
                "try:",
                "    saved = facade.load_batch('qa-task', 'native-qa-batch')",
                "    assert saved['revision'] == 1",
                "    assert hashlib.sha256(json.dumps(saved['batch'], sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest() == sys.argv[3]",
                "    print('fresh-process exact revision reload OK')",
                "finally:",
                "    facade.close(); store.close()",
            ]), str(tmp_path / "inbox.json"), str(root), expected_hash],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert child.returncode == 0, child.stderr
        assert "fresh-process exact revision reload OK" in child.stdout
    finally:
        app.processEvents()
        if window.isVisible() and not window._jobs:
            window._dirty = False
            window.close()
        facade.close()
        store.close()


def test_workspace_owner_lock_rejects_other_process_then_releases(tmp_path: Path):
    store = AgentLinkStore(tmp_path / "owner-inbox.json")
    service = AgentLinkService(store, "owner-fixture-token")
    root = tmp_path / "owner-workspace"
    facade = NativeReviewFacade(service, "owner-fixture-token", root)
    probe = "\n".join([
        "import sys",
        "from pathlib import Path",
        "from app.desktop_review.workspace import NativeReviewFacade, DesktopReviewError",
        "class ReadOnlyService:",
        "    def reviewer_call(self, *_args): raise AssertionError('no inbox call expected')",
        "try:",
        "    owner = NativeReviewFacade(ReadOnlyService(), 'owner-fixture-token', Path(sys.argv[1]))",
        "except DesktopReviewError:",
        "    assert sys.argv[2] == 'locked'",
        "    print('owner conflict correctly rejected')",
        "else:",
        "    owner.close()",
        "    assert sys.argv[2] == 'released'",
        "    print('released owner lock reacquired')",
    ])
    try:
        for state in ("locked", "released"):
            if state == "released":
                facade.close()
            result = subprocess.run(
                [sys.executable, "-c", probe, str(root), state],
                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                text=True, encoding="utf-8", timeout=30,
            )
            assert result.returncode == 0, result.stderr
            assert ("correctly rejected" if state == "locked" else "reacquired") in result.stdout
    finally:
        facade.close()
        store.close()


def test_reload_checks_materialized_workflow_png_not_only_original(tmp_path: Path):
    app = ensure_application()
    store = AgentLinkStore(tmp_path / "copied-png-inbox.json")
    service = AgentLinkService(store, "copied-png-fixture-token")
    root = tmp_path / "review-data"
    facade = NativeReviewFacade(service, "copied-png-fixture-token", root)
    try:
        grant = service.reviewer_call("copied-png-fixture-token", "create_connection", {"task_id": "qa-task", "agent_name": "synthetic-evidence-check"})
        service.agent_call(grant["token"], "submit_batch", _synthetic_batch(app))
        saved = facade.save_revision("qa-task", "native-qa-batch", 0, facade.load_batch("qa-task", "native-qa-batch")["batch"])
        review = json.loads(Path(saved["workflow_review_path"]).read_text(encoding="utf-8"))
        materialized_png = root / review["nodes"][0]["evidence"]["source_screenshot_path"]
        assert materialized_png.is_relative_to(root)
        assert "/node-evidence/" in materialized_png.as_posix()
        original_png = next((root / "desktop-review" / "sources" / saved["source_ref"] / "screenshots").glob("*.png"))
        assert materialized_png != original_png
        original_bytes = original_png.read_bytes()
        materialized_png.write_bytes(b"tampered derived evidence")
        with pytest.raises(DesktopReviewError):
            facade.load_batch("qa-task", "native-qa-batch")
        assert original_png.read_bytes() == original_bytes
        assert materialized_png.read_bytes() == b"tampered derived evidence"
    finally:
        facade.close()
        store.close()


def test_native_exact_review_real_compile_publish_and_fresh_process_library(tmp_path: Path):
    from app.desktop_review.exact_dialog import ExactReviewDialog
    from app.desktop_review.library_dialog import WorkflowLibraryDialog

    app = ensure_application()
    store = AgentLinkStore(tmp_path / "exact-inbox.json")
    token = "native-exact-integration-fixture"
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "qa-task", "agent_name": "synthetic-not-real-agent"})
    batch = _synthetic_batch(app)
    batch["steps"][0].update(action_type="open_detail", target_region_id="details-button")
    service.agent_call(grant["token"], "submit_batch", batch)
    original = copy.deepcopy(service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})["batch"])
    root = tmp_path / "exact-root"
    facade = NativeReviewFacade(service, token, root)
    dialog = library = None
    try:
        saved = facade.save_revision("qa-task", "native-qa-batch", 0, facade.load_batch("qa-task", "native-qa-batch")["batch"])
        dialog = ExactReviewDialog(facade, saved)
        dialog.resize(1250, 850)
        dialog.show()
        dialog.application_display_name.setText("合成文件工作区")
        dialog.application_identity.setText("synthetic-review-fixture.exe")
        QTest.mouseClick(dialog.prepare_button, Qt.MouseButton.LeftButton)
        _wait(app, lambda: dialog.review is not None)
        assert not dialog.publish_button.isEnabled()
        assert dialog.subject_table.rowCount() >= 6
        assert not any(dialog.subject_table.cellWidget(row, 0).isChecked() for row in range(dialog.subject_table.rowCount()))
        first_box = dialog.subject_table.cellWidget(0, 0)
        QTest.mouseClick(first_box, Qt.MouseButton.LeftButton, pos=QPoint(8, first_box.height() // 2))
        assert first_box.isChecked()
        QTest.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
        _wait(app, lambda: dialog.review["approval_revision"] == 1 and not dialog._busy)
        QTest.mouseClick(dialog.compile_button, Qt.MouseButton.LeftButton)
        _wait(app, lambda: dialog.review.get("status") == "blocked" and not dialog._busy)
        assert not dialog.publish_button.isEnabled()
        for row in range(dialog.subject_table.rowCount()):
            box = dialog.subject_table.cellWidget(row, 0)
            assert isinstance(box, QCheckBox)
            if not box.isChecked():
                dialog.subject_table.scrollToItem(dialog.subject_table.item(row, 1))
                app.processEvents()
                QTest.mouseClick(box, Qt.MouseButton.LeftButton, pos=QPoint(8, box.height() // 2))
                assert box.isChecked(), f"subject row {row} did not toggle"
        QTest.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
        _wait(app, lambda: dialog.review["approval_revision"] == 2 and not dialog._busy)
        QTest.mouseClick(dialog.compile_button, Qt.MouseButton.LeftButton)
        try:
            _wait(app, lambda: bool(dialog.review.get("compile_receipt_id")) and not dialog._busy)
        except AssertionError as error:
            raise AssertionError(dialog.status_label.text()) from error
        assert facade.list_reviewed_assets() == []
        assert dialog.publish_button.isEnabled()
        # 未保存的撤回意图也必须阻断旧回执发布，不能误用屏幕上已取消的审核。
        box = dialog.subject_table.cellWidget(0, 0)
        dialog.subject_table.scrollToItem(dialog.subject_table.item(0, 1))
        QTest.mouseClick(box, Qt.MouseButton.LeftButton, pos=QPoint(8, box.height() // 2))
        assert not box.isChecked()
        assert not dialog.publish_button.isEnabled()
        QTest.mouseClick(box, Qt.MouseButton.LeftButton, pos=QPoint(8, box.height() // 2))
        assert box.isChecked()
        if not dialog.publish_button.isEnabled():
            QTest.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
            _wait(app, lambda: not dialog._busy and dialog.publish_button.isEnabled())
        assert dialog.publish_button.isEnabled()
        QTest.mouseClick(dialog.publish_button, Qt.MouseButton.LeftButton)
        _wait(app, lambda: "入库回执" in dialog.status_label.text() and not dialog._busy)
        assets = facade.list_reviewed_assets()
        assert len(assets) == 1 and len(assets[0]["content_sha256"]) == 64
        assert service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})["batch"] == original
        out_dir = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
        out_dir.mkdir(parents=True, exist_ok=True)
        assert dialog.grab().save(str(out_dir / "native-exact-review.png"))
        _wait(app, lambda: not dialog._jobs)
        dialog.close()
        library = WorkflowLibraryDialog(facade)
        library.show()
        _wait(app, lambda: library.asset_table.rowCount() == 1)
        assert library.grab().save(str(out_dir / "native-workflow-library.png"))
        _wait(app, lambda: not library._jobs)
        library.close()
        facade.close()
        store.close()
        child = subprocess.run([sys.executable, "-c", "\n".join([
            "import json, sys", "from pathlib import Path",
            "from app.agent_link import AgentLinkService, AgentLinkStore",
            "from app.desktop_review.workspace import NativeReviewFacade",
            "store = AgentLinkStore(Path(sys.argv[1]))",
            "facade = NativeReviewFacade(AgentLinkService(store, 'native-exact-integration-fixture'), 'native-exact-integration-fixture', Path(sys.argv[2]))",
            "try:", "    print(json.dumps(facade.list_reviewed_assets(), ensure_ascii=False, sort_keys=True))",
            "finally:", "    facade.close(); store.close()",
        ]), str(tmp_path / "exact-inbox.json"), str(root)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert child.returncode == 0, child.stderr
        assert json.loads(child.stdout) == assets
    finally:
        for view in (dialog, library):
            if view is not None:
                _wait(app, lambda: not view._jobs)
                view.close()
        facade.close()
        store.close()
