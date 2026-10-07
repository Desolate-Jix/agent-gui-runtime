"""慢证据读取不能阻塞界面，也不能把旧结果装到新选择上。"""
from copy import deepcopy
import hashlib
from pathlib import Path
from threading import Event, get_ident
import time

from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QTimer

from app.desktop_review.interface_pane import InterfaceReviewPane
from tests.test_learning_membership_ui import qt_app


class SlowEvidenceClient:
    background_interface_loading = True

    def __init__(self, root):
        self.images = {}
        self.started = Event()
        self.release = Event()
        self.reads = []
        self.fail = False
        for key, color in (("a", "red"), ("b", "green"), ("c", "blue")):
            path = root / f"{key}.png"
            Image.new("RGB", (160, 100), color).save(path)
            self.images[key] = path

    def snapshot(self, key):
        return {"interface_id": key, "version_id": f"{key}-v1", "revision": 1,
                "content_sha256": f"{key}-content", "origin_status": "new",
                "source": {"kind": "execution_memory_v1"},
                "content": {"meaning": key, "regions": []}}

    def load_interface_content(self, key, version=None):
        return self.snapshot(key)

    def list_interface_contents(self, reviewed=False, task_id=None):
        return [self.snapshot(key) for key in ("a", "b", "c")]

    def load_interface_content_evidence(self, key, version=None):
        self.reads.append(key)
        if key == "a":
            self.started.set()
            self.release.wait(1)
        if self.fail:
            raise ValueError("target_evidence_hash_mismatch")
        return {"image_path": str(self.images[key]),
                "sha256": hashlib.sha256(self.images[key].read_bytes()).hexdigest()}

    def _artifact_file(self, path, label):
        return Path(path)

    def read_learned_target_regions(self, key, version=None):
        return {"regions": [{"region_id": key, "bbox": [10, 10, 20, 20],
                             "name": key, "kind": "button", "meaning": key}]}

    def read_interface_target_links(self, key, version=None):
        return {"targets": [], "issues": []}


def wait(app, predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("界面读取没有结束")


def cleanup(pane, client, app):
    client.release.set()
    wait(app, lambda: not getattr(pane, "is_busy", False))
    pane.close()
    pane.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_slow_evidence_keeps_event_loop_responsive_and_disables_editing(qt_app, tmp_path):
    client = SlowEvidenceClient(tmp_path)
    pane = InterfaceReviewPane(client)
    heartbeat = []
    try:
        started = time.perf_counter()
        pane.set_snapshot(client.snapshot("a"))
        elapsed = time.perf_counter() - started
        assert elapsed < .15, f"切换阻塞了 {elapsed:.3f}s"
        wait(qt_app, client.started.is_set)
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qt_app.processEvents()
        assert heartbeat == [True]
        assert not pane.save_button.isEnabled()
        assert not pane.add_region_button.isEnabled()
        assert not pane.canvas._regions
        pane.meaning_edit.setText("不能保存的加载中草稿")
        pane.save_changes()
        assert not pane.dirty
        client.release.set()
        wait(qt_app, lambda: not pane.is_busy)
        assert pane.meaning_edit.text() == "a"
        assert list(pane.canvas._regions) == ["a"]
        assert pane.save_button.isEnabled()
    finally:
        cleanup(pane, client, qt_app)


def test_rapid_switches_skip_intermediate_read_and_never_install_old_evidence(qt_app, tmp_path):
    client = SlowEvidenceClient(tmp_path)
    pane = InterfaceReviewPane(client)
    try:
        pane.set_snapshot(client.snapshot("a"))
        wait(qt_app, client.started.is_set)
        pane.set_snapshot(client.snapshot("b"))
        pane.set_snapshot(client.snapshot("c"))
        assert pane.snapshot["interface_id"] == "c"
        assert pane.meaning_edit.text() == "c"
        assert not pane.canvas._regions
        client.release.set()
        wait(qt_app, lambda: not pane.is_busy)
        assert list(pane.canvas._regions) == ["c"]
        assert pane.title.text() == "c"
        assert pane.meaning_edit.text() == "c"
        assert client.reads == ["a", "c"]
        assert not pane.dirty
    finally:
        cleanup(pane, client, qt_app)


def test_close_during_evidence_read_waits_for_safe_thread_cleanup(qt_app, tmp_path):
    client = SlowEvidenceClient(tmp_path)
    pane = InterfaceReviewPane(client)
    pane.show()
    try:
        pane.set_snapshot(client.snapshot("a"))
        wait(qt_app, client.started.is_set)
        assert not pane.close()
        assert pane.isVisible()
        client.release.set()
        wait(qt_app, lambda: not pane.is_busy)
        assert not pane.canvas._regions
        assert pane.close()
    finally:
        cleanup(pane, client, qt_app)


def test_failed_evidence_stays_uneditable_and_can_be_reloaded(qt_app, tmp_path):
    client = SlowEvidenceClient(tmp_path)
    pane = InterfaceReviewPane(client)
    errors = []
    pane.errorRaised.connect(errors.append)
    client.fail = True
    client.release.set()
    try:
        pane.set_snapshot(client.snapshot("a"))
        wait(qt_app, lambda: not getattr(pane, "is_busy", False))
        assert errors and "target_evidence_hash_mismatch" in errors[-1]
        assert not pane.canvas._regions
        assert not pane.save_button.isEnabled()
        assert not pane.edit_target_button.isEnabled()
        client.fail = False
        pane.set_snapshot(client.snapshot("c"))
        wait(qt_app, lambda: not pane.is_busy)
        assert list(pane.canvas._regions) == ["c"]
        assert pane.save_button.isEnabled()
    finally:
        cleanup(pane, client, qt_app)


def test_library_head_version_read_stays_off_ui_thread(qt_app, tmp_path):
    from app.desktop_review.content_library import InterfaceContentLibrary

    class HeadReadClient(SlowEvidenceClient):
        def __init__(self, root):
            super().__init__(root)
            self.head_threads = []

        def load_interface_content(self, key, version=None):
            self.head_threads.append(get_ident())
            return super().load_interface_content(key, version)

    client = HeadReadClient(tmp_path)
    client.release.set()
    library = InterfaceContentLibrary(client, embedded=True)
    ui_thread = get_ident()
    try:
        wait(qt_app, lambda: not getattr(library.pane, "is_busy", False))
        library.items.setCurrentRow(2)
        wait(qt_app, lambda: not getattr(library.pane, "is_busy", False))
        assert library.pane.snapshot["interface_id"] == "c"
        assert client.head_threads and all(thread != ui_thread for thread in client.head_threads)
        assert library.pane.save_button.isEnabled()
    finally:
        client.release.set()
        wait(qt_app, lambda: not getattr(library.pane, "is_busy", False))
        library.close()
        library.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_action_image_switch_uses_only_this_selection_images(qt_app, tmp_path):
    class TargetsClient(SlowEvidenceClient):
        def read_interface_target_links(self, key, version=None):
            targets = []
            for index, image_key in enumerate(("b", "c"), 1):
                path = self.images[image_key]
                targets.append({"workflow_id": "workflow", "program_id": "program-v1",
                    "program_sha256": "program-sha", "step_id": f"step-{index}",
                    "step_title": f"action-{index}", "workflow_title": "workflow",
                    "reference": {"recipe_id": f"recipe-{index}", "content_sha256": "recipe-sha"},
                    "interface_version_id": f"{key}-v1", "selected_version_matches": True,
                    "frame": {"image_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                    "target_boxes": [{"region_id": "strategy-0", "bbox": [index * 30, 10, 20, 20],
                                      "name": f"action-{index}", "kind": "uia"}],
                    "box_issues": [], "evidence_scope": "learning_capture"})
            return {"targets": targets, "issues": []}

    client = TargetsClient(tmp_path)
    client.release.set()
    pane = InterfaceReviewPane(client)
    opened = []
    pane.targetRuleRequested.connect(opened.append)
    try:
        pane.set_snapshot(client.snapshot("a"))
        wait(qt_app, lambda: not getattr(pane, "is_busy", False))
        assert pane.target_choice.count() == 3
        assert pane.canvas._regions["strategy-0"].bbox() == [30, 10, 20, 20]
        # 临时测试图片离开磁盘后，已加载的选择内切换仍应正确；新选择仍须重新校验。
        for path in client.images.values():
            path.unlink()
        pane.target_choice.setCurrentIndex(2)
        assert pane.canvas._regions["strategy-0"].bbox() == [60, 10, 20, 20]
        assert pane.canvas._pixmap_item.pixmap().toImage().pixelColor(0, 0).blue() == 255
        pane.edit_target_button.click()
        assert opened[0]["step_id"] == "step-2"
        assert opened[0]["frame"]["sha256"] == pane.target_choice.currentData()["frame"]["sha256"]
        assert "image_bytes" not in opened[0]
        pane.target_choice.setCurrentIndex(0)
        assert list(pane.canvas._regions) == ["a"]
        assert pane.canvas._pixmap_item.pixmap().toImage().pixelColor(0, 0).red() == 255
        pane.set_snapshot(client.snapshot("a"))
        wait(qt_app, lambda: not getattr(pane, "is_busy", False))
        assert not pane.canvas._regions
        assert not pane.save_button.isEnabled()
    finally:
        cleanup(pane, client, qt_app)


def test_invalid_image_failure_is_reported_without_a_half_loaded_editor(qt_app, tmp_path):
    client = SlowEvidenceClient(tmp_path)
    client.release.set()
    client.images["a"].write_bytes(b"not a PNG")
    pane = InterfaceReviewPane(client)
    errors = []
    pane.errorRaised.connect(errors.append)
    try:
        pane.set_snapshot(client.snapshot("a"))
        wait(qt_app, lambda: not getattr(pane, "is_busy", False))
        assert errors
        assert not pane.canvas._pixmap_item
        assert not pane.save_button.isEnabled()
        assert not pane.compose_button.isEnabled()
        pane.set_snapshot(client.snapshot("c"))
        wait(qt_app, lambda: not pane.is_busy)
        assert pane.save_button.isEnabled()
    finally:
        cleanup(pane, client, qt_app)


def test_synchronous_facade_clear_then_reselect_restores_editor(qt_app, tmp_path):
    client = SlowEvidenceClient(tmp_path)
    client.background_interface_loading = False
    client.release.set()
    pane = InterfaceReviewPane(client)
    try:
        pane.set_snapshot(client.snapshot("a"))
        assert pane.save_button.isEnabled()
        pane.clear_content()
        assert pane.snapshot is None
        pane.set_snapshot(client.snapshot("c"))
        assert pane.save_button.isEnabled()
        assert pane.add_region_button.isEnabled()
        assert list(pane.canvas._regions) == ["c"]
    finally:
        cleanup(pane, client, qt_app)
