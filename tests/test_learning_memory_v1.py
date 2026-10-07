"""新记忆契约的临时文件回归；不操作桌面，不复用历史学习资产。"""
import hashlib
from pathlib import Path
import time

import numpy as np
from PIL import Image
import pytest

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.event_store import LearningEventStore, validate_control
from app.learning_memory.receipt_adapter import content_hash
from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.feedback import feedback_control, read_baseline_image
from app.learning_memory.templates import save_template, template_evidence, match_template_frame


def wait_qt_idle(app, *panels):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if all(not panel.is_busy for panel in panels):
            return
        time.sleep(.01)
    raise AssertionError("后台界面任务没有结束")


@pytest.fixture
def learned(tmp_path):
    session = tmp_path / "session-fresh"
    (session / "responses").mkdir(parents=True)
    image = session / "fresh.png"
    pixels = np.random.default_rng(7).integers(0, 256, (100, 160, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(image)
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    frame = {"image_path": str(image), "sha256": sha,
             "window_size": {"width": 160, "height": 100}, "capture_id": "fresh-1"}
    store = LearningEventStore(session)
    store.control("learning_start", {"scope": "interface", "title": "独立界面"}, "start")
    command = {"kind": "capture"}
    ticket = store.prepare("capture-one", command, None)
    store.reserve(ticket)
    response = {"command": command, "status": "returned", "learning_binding": ticket, "observation": frame}
    write_json_snapshot(session / "responses" / "capture-one.json", response)
    store.record("capture-one", ticket)
    event = store.control("learning_event", {"event_id": "capture-one"}, "read")["event"]
    store.control("learning_review", {"review": {"event_id": "capture-one", "event_sha256": content_hash(event),
        "verdict": "success", "reviewer": "unit-contract", "reason": "只验证记录，不是 GUI 成功证明",
        "after": {"interface_key": "search", "state_key": "home", "frame_sha256": sha, "meaning": "搜索首页"}}}, "review")
    content = store.control("learning_import", {"event_id": "capture-one", "view": "after",
        "regions": [{"region_id": "search-button", "bbox": [35, 25, 30, 20], "name": "搜索",
                     "kind": "button", "meaning": "启动搜索", "recognition_text": "搜索"}]}, "import")
    return store, tmp_path / "memory-library", content, frame


def test_standalone_stop_reopen_does_not_create_graph(learned):
    store, root, content, _ = learned
    stopped = store.control("learning_stop", {}, "stop")
    assert stopped["recording_complete"] is True
    with MemoryWorkspace(root) as library:
        assert library.list_workflow_graphs() == []
        loaded = library.load_interface_content(content["interface_id"], content["version_id"])
        assert loaded["content"]["meaning"] == "搜索首页"
        assert len(library.list_interface_contents(task_id="memory-local")) == 1


def test_feedback_candidate_adoption_preserves_old_version(learned):
    _, root, content, frame = learned
    with MemoryWorkspace(root) as library:
        issue = library.request_interface_relearning(content["interface_id"], content["revision"],
            content["content_sha256"], [], "请修正界面含义", "issue-one")
        detail = feedback_control(library, {"action": "read", "issue_id": issue["issue_id"]}, "read")
        assert "png_base64" not in detail["screenshot"]
        candidate = feedback_control(library, {"action": "submit", "issue_id": issue["issue_id"],
            "expected_baseline_sha256": content["content_sha256"], "changes": {"meaning": "可输入关键词的首页"}}, "candidate-one")
        assert candidate["content_adopted"] is False
        library.adopt_interface_relearning(issue["issue_id"], candidate["candidate"]["candidate_id"],
            content["revision"], content["content_sha256"], "adopt-one")
        assert library.load_interface_content(content["interface_id"], None)["content"]["meaning"] == "可输入关键词的首页"
        assert library.load_interface_content(content["interface_id"], content["version_id"])["content"]["meaning"] == "搜索首页"
    assert hashlib.sha256(read_baseline_image(root, detail)).hexdigest() == frame["sha256"]


def test_feedback_exposes_new_region_contract_and_repopulates_empty_source(learned):
    _, root, content, _ = learned
    with MemoryWorkspace(root) as library:
        empty = library.save_interface_content(content["interface_id"], content["revision"],
            content["content_sha256"], {"regions": []}, "clear-regions")
        issue = library.request_interface_relearning(content["interface_id"], empty["revision"],
            empty["content_sha256"], [], "根据原图补充遗漏识别框", "new-regions")
        detail = feedback_control(library, {"action": "read", "issue_id": issue["issue_id"]}, "read")
        contract = detail["region_edit_contract"]
        assert contract["new_region_id_format"] == "region-user-<lowercase UUID>"
        assert contract["list_semantics"] == "complete_replacement"
        assert contract["bbox_coordinate_space"] == "baseline_image_pixels"
        region = {"region_id": "region-user-25c989c1-48ed-42b7-98b9-58d307962af5",
                  "bbox": [35, 25, 30, 20], "name": "搜索", "kind": "button",
                  "meaning": "查询当前关键词", "recognition_text": "搜索"}
        assert set(contract["required_fields"]) == set(region)
        candidate = feedback_control(library, {"action": "submit", "issue_id": issue["issue_id"],
            "expected_baseline_sha256": empty["content_sha256"], "changes": {"regions": [region]}}, "new-candidate")
        assert candidate["content_adopted"] is False
        assert library.load_interface_content(content["interface_id"])["content"]["regions"] == []
        library.adopt_interface_relearning(issue["issue_id"], candidate["candidate"]["candidate_id"],
            empty["revision"], empty["content_sha256"], "adopt-new-region")
        assert library.load_interface_content(content["interface_id"])["content"]["regions"] == [region]
        assert library.load_interface_content(content["interface_id"], empty["version_id"])["content"]["regions"] == []


@pytest.mark.parametrize("change,expected", [("moved", "matched"), ("duplicate", "ambiguous"),
    ("missing", "not_found"), ("resized", "viewport_changed_relearn_required")])
def test_live_template_adapter_uses_current_pixels_or_returns_no_plan(learned, tmp_path, change, expected):
    from app.learning_memory.live_template import template_library_scope, plan_current_template
    _, root, content, frame = learned
    with MemoryWorkspace(root) as library:
        saved = save_template(library, {"interface_id": content["interface_id"], "version_id": content["version_id"],
            "region_id": "search-button", "padding": 0, "radius": 50})
    pixels = np.array(Image.open(frame["image_path"]).convert("RGB"))
    patch = pixels[25:45, 35:65].copy()
    if change in {"moved", "missing"}:
        pixels[25:45, 35:65] = 0
    if change == "moved":
        pixels[35:55, 45:75] = patch
    if change == "duplicate":
        pixels[25:45, 75:105] = patch
    current = Image.fromarray(pixels)
    if change == "resized":
        current = current.resize((200, 125))
    path = tmp_path / "current-route.png"
    current.save(path)
    live = {"image_path": str(path), "capture_id": "current-route-id",
            "window_size": {"width": current.width, "height": current.height}}
    reference = {"template_id": saved["template_id"], "interface_key": "search", "state_key": "home"}
    with template_library_scope(root):
        plan, result = plan_current_template(reference, path, live)
    assert result["status"] == expected
    assert result["input_executed"] is False
    assert result["frame_origin"] == "execution_route_live_capture"
    if change == "moved":
        assert result["candidate"]["capture_id"] == "current-route-id"
        assert result["candidate"]["click_point"] == {"x": 60, "y": 45}
        assert result["candidate"]["freshness"] == "current_route_capture"
        assert plan["execution_path"]["action_executed"] is False
        assert plan["pre_click_decision"]["selected_click_point"] == {"x": 60, "y": 45}
    else:
        assert plan is None
        assert result["candidate"] is None


def test_template_crop_matches_current_frame_without_input(learned):
    _, root, content, frame = learned
    with MemoryWorkspace(root) as library:
        saved = save_template(library, {"interface_id": content["interface_id"], "version_id": content["version_id"],
            "region_id": "search-button", "padding": 3, "radius": 15})
        assert template_evidence(library, saved["template_id"])["png_sha256"] == saved["png_sha256"]
        result = match_template_frame(library, {"template_id": saved["template_id"],
            "interface_key": "search", "state_key": "home", "frame_sha256": frame["sha256"]}, Path(frame["image_path"]), frame)
        assert result["status"] == "matched"
        assert result["candidate"]["bbox"] == {"x": 35, "y": 25, "w": 30, "h": 20}
        assert result["candidate"]["capture_id"] == "fresh-1"


def test_template_rejects_wrong_interface_and_changed_image_size(learned):
    _, root, content, frame = learned
    with MemoryWorkspace(root) as library:
        saved = save_template(library, {"interface_id": content["interface_id"], "version_id": content["version_id"],
            "region_id": "search-button"})
        request = {"template_id": saved["template_id"], "interface_key": "wrong", "state_key": "home",
                   "frame_sha256": frame["sha256"]}
        assert match_template_frame(library, request, Path(frame["image_path"]), frame)["status"] == "interface_mismatch"
        path = Path(frame["image_path"]).with_name("different-size.png")
        Image.new("RGB", (180, 120), "white").save(path)
        changed = {**frame, "image_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "window_size": {"width": 180, "height": 120}}
        request.update(interface_key="search", frame_sha256=changed["sha256"])
        result = match_template_frame(library, request, path, changed)
        assert result["status"] == "viewport_changed_relearn_required"
        assert result["candidate"] is None


def test_template_dialog_saves_and_previews_original_crop(learned, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.learning_memory.editor_client import MemoryEditorClient
    from app.learning_memory.template_dialog import ControlTemplateDialog
    app = QApplication.instance() or QApplication([])
    _, root, content, _ = learned
    with MemoryEditorClient(root) as editor:
        dialog = ControlTemplateDialog(editor, content, "search-button")
        try:
            assert dialog.items.count() == 0
            dialog.save()
            assert dialog.items.count() == 1, dialog.status.text()
            assert not dialog.image.pixmap().isNull(), dialog.status.text()
            assert dialog.image.pixmap().width() == 42
            assert dialog.image.pixmap().height() == 32
            # 对话框保持打开时另一个客户端仍可取库锁。
            with MemoryWorkspace(root) as other:
                assert other.load_interface_content(content["interface_id"], None)["version_id"] == content["version_id"]
        finally:
            dialog.close()
            app.processEvents()


def test_feedback_mcp_delivers_pinned_image_not_json_base64(learned):
    import asyncio
    import base64
    import json
    from app.instant_mcp import InstantSession, build_server
    store, root, content, frame = learned
    with MemoryWorkspace(root) as library:
        issue = library.request_interface_relearning(content["interface_id"], content["revision"],
            content["content_sha256"], [], "修正", "mcp-issue")
    result = store.control("learning_feedback", {"action": "read", "issue_id": issue["issue_id"]}, "feedback-read")
    write_json_snapshot(store.session / "responses" / "feedback-read.json", {
        "status": "returned", "learning_control": "learning_feedback", "result": result})
    session = InstantSession(Path(__file__).resolve().parents[1], root.parent, root.parent)
    session.session = store.session
    response = asyncio.run(build_server(session).call_tool("instant_result", {
        "request_id": "feedback-read", "images": "both"}))
    assert not response.is_error
    payload = json.loads(response.content[0].text)
    assert "png_base64" not in response.content[0].text
    assert payload["image_delivery"][0]["view"] == "before"
    assert len(response.content) == 2
    assert hashlib.sha256(base64.b64decode(response.content[1].data)).hexdigest() == frame["sha256"]


def record_search(store, request_id, *, same_state=False, verdict="success", executed=True):
    frames = []
    for view, color in (("before", "white"), ("after", "blue")):
        image = store.session / (request_id + "-" + view + ".png")
        Image.new("RGB", (160, 100), color).save(image)
        frames.append({"image_path": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                       "window_size": {"width": 160, "height": 100}})
    command = {"kind": "input_sequence", "request": {"field_goal": "搜索关键词", "text": "第一地点",
               "clear_existing": True, "submit_search": True}}
    ticket = store.prepare(request_id, command, None)
    response = {"command": command, "status": "returned", "learning_binding": ticket,
        "result": {"capture": frames[0], "observation": {"capture": frames[1]},
                   "status": "completed", "action_executed": executed, "steps": []}}
    write_json_snapshot(store.session / "responses" / (request_id + ".json"), response)
    store.record(request_id, ticket)
    event = store.control("learning_event", {"event_id": request_id}, request_id + "-read")["event"]
    review = {"event_id": request_id, "event_sha256": content_hash(event), "verdict": verdict,
        "reviewer": "contract", "reason": "契约构造数据，不代表实机成功",
        "input_binding": {"kind": "variable", "name": "place"},
        "before": {"interface_key": "maps", "state_key": "home", "meaning": "搜索首页", "frame_sha256": frames[0]["sha256"]},
        "after": {"interface_key": "maps", "state_key": "home" if same_state else "results",
                  "meaning": "地点结果", "frame_sha256": frames[1]["sha256"]}}
    store.control("learning_review", {"review": review}, request_id + "-review")
    return event


@pytest.fixture
def workflow_store(tmp_path):
    session = tmp_path / "session-workflow"
    (session / "responses").mkdir(parents=True)
    store = LearningEventStore(session)
    store.control("learning_start", {"scope": "workflow", "title": "搜索地点", "project_id": "maps-demo"}, "start")
    return store


def test_graph_roundtrip_variable_reuse_and_pinned_version(workflow_store):
    from app.learning_memory.reader import read_project, prepare_reuse
    from app.learning_memory.graph_source import logical_id
    store = workflow_store
    record_search(store, "search-one")
    store.control("learning_stop", {}, "stop")
    with MemoryWorkspace(store.session.parent / "memory-library") as library:
        graph_id = logical_id("maps-demo")
        memory = read_project(library, graph_id)
        assert len(memory["graph"]["nodes"]) == 2
        assert len(memory["graph"]["edges"]) == 1
        edge = memory["graph"]["edges"][0]
        advice = prepare_reuse(library, graph_id, memory["snapshot_id"], edge["edge_id"], {"place": "另一地点"})
        assert advice["suggested_command"]["request"]["text"] == "另一地点"
        assert advice["input_executed"] is False
        node = library.load_graph_revision(graph_id)["graph"]["nodes"][0]
        pin = node["interface_reference"]
        content = library.load_interface_content(pin["interface_id"], pin["version_id"])
        library.save_interface_content(content["interface_id"], content["revision"], content["content_sha256"],
                                       {"meaning": "后来修改的含义"}, "edit")
        assert read_project(library, graph_id, memory["snapshot_id"])["graph"] == memory["graph"]


@pytest.mark.parametrize("same_state,verdict,executed,node_count,edge_count", [
    (True, "success", True, 1, 1), (False, "failure", True, 2, 0),
    (False, "uncertain", True, 2, 0), (False, "success", False, 2, 0)])
def test_projection_requires_dispatched_success_without_duplicate_states(
        workflow_store, same_state, verdict, executed, node_count, edge_count):
    record_search(workflow_store, "search-one", same_state=same_state, verdict=verdict, executed=executed)
    projection = workflow_store.control("learning_projection", {}, "projection")
    assert len(projection["nodes"]) == node_count
    assert len(projection["edges"]) == edge_count


def test_continued_learning_keeps_previous_project_edges(workflow_store):
    from app.learning_memory.graph_source import logical_id
    from app.learning_memory.reader import read_project
    store = workflow_store
    record_search(store, "search-one")
    store.control("learning_stop", {}, "stop-one")
    root = store.session.parent / "memory-library"
    with MemoryWorkspace(root) as library:
        original = read_project(library, logical_id("maps-demo"))
    store.control("learning_start", {"scope": "workflow", "title": "继续搜索", "project_id": "maps-demo"}, "continue")
    record_search(store, "search-two", same_state=True)
    store.control("learning_stop", {}, "stop-two")
    with MemoryWorkspace(root) as library:
        current = read_project(library, logical_id("maps-demo"))
        assert len(current["graph"]["edges"]) == 2
        assert {e["event_id"] for e in current["graph"]["edges"]} == {"search-one", "search-two"}
        assert read_project(library, logical_id("maps-demo"), original["snapshot_id"])["graph"] == original["graph"]


def test_cross_session_repeated_request_ids_are_not_merged(workflow_store):
    from app.learning_memory.graph_source import logical_id
    from app.learning_memory.reader import read_project, prepare_reuse
    store = workflow_store
    record_search(store, "search-one")
    store.control("learning_stop", {}, "stop-one")
    session = store.session.parent / "session-other"
    (session / "responses").mkdir(parents=True)
    other = LearningEventStore(session)
    other.control("learning_start", {"scope": "workflow", "title": "第二会话", "project_id": "maps-demo"}, "start")
    record_search(other, "search-one", same_state=True)
    other.control("learning_stop", {}, "stop-one")
    with MemoryWorkspace(store.session.parent / "memory-library") as library:
        memory = read_project(library, logical_id("maps-demo"))
        assert len(memory["graph"]["edges"]) == 2
        assert len({row["edge_id"] for row in memory["graph"]["edges"]}) == 2
        for row in memory["graph"]["edges"]:
            value = prepare_reuse(library, logical_id("maps-demo"), memory["snapshot_id"], row["edge_id"], {"place": "新地点"})
            assert value["suggested_command"]["request"]["text"] == "新地点"


def test_concurrent_segment_requires_explicit_graph_conflict_resolution(workflow_store):
    from app.learning_memory.graph_source import logical_id
    store = workflow_store
    session = store.session.parent / "session-other"
    (session / "responses").mkdir(parents=True)
    other = LearningEventStore(session)
    other.control("learning_start", {"scope": "workflow", "title": "并发段", "project_id": "maps-demo"}, "start")
    record_search(store, "search-one")
    record_search(other, "search-two")
    store.control("learning_stop", {}, "stop-one")
    with pytest.raises(ValueError, match="stale memory graph"):
        other.control("learning_stop", {}, "stop-two")
    with MemoryWorkspace(store.session.parent / "memory-library") as library:
        graph = library.load_graph_revision(logical_id("maps-demo"))
        assert len(graph["graph"]["edges"]) == 1
    other.control("learning_commit", {"expected_sha256": graph["content_sha256"]}, "resolve")
    with MemoryWorkspace(store.session.parent / "memory-library") as library:
        assert len(library.load_graph_revision(logical_id("maps-demo"))["graph"]["edges"]) == 2


def record_replacement(store):
    image = store.session / "replacement.png"
    Image.new("RGB", (170, 110), "green").save(image)
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    command = {"kind": "capture"}
    ticket = store.prepare("replacement", command, None)
    write_json_snapshot(store.session / "responses" / "replacement.json", {"command": command,
        "status": "returned", "learning_binding": ticket, "observation": {
            "image_path": str(image), "sha256": digest, "window_size": {"width": 170, "height": 110}}})
    store.record("replacement", ticket)
    event = store.control("learning_event", {"event_id": "replacement"}, "read-replacement")["event"]
    store.control("learning_review", {"review": {"event_id": "replacement", "event_sha256": content_hash(event),
        "verdict": "success", "reviewer": "contract", "reason": "新截图对照",
        "after": {"interface_key": "search", "state_key": "home", "meaning": "新截图",
                  "frame_sha256": digest}}}, "review-replacement")
    return digest


def test_source_candidates_preview_and_adoption(learned):
    store, root, content, _ = learned
    digest = record_replacement(store)
    with MemoryWorkspace(root) as library:
        listing = library.list_source_candidates(content["interface_id"])
        assert len(listing["candidates"]) == 1
        candidate = listing["candidates"][0]
        preview = library.preview_source_candidate(content["interface_id"], candidate)
        assert hashlib.sha256(preview["png"]).hexdigest() == digest
        adopted = library.adopt_source_candidate(content["interface_id"], candidate,
            content["revision"], content["content_sha256"], "adopt-replacement")
        assert adopted["content"]["regions"] == []
        assert adopted["source"]["screenshot_sha256"] == digest
        assert adopted["content"]["meaning"] == content["content"]["meaning"]
        assert len(library.load_interface_content(content["interface_id"], content["version_id"])["content"]["regions"]) == 1


def test_source_adoption_dialog_requires_explicit_choice(learned, monkeypatch):
    import time
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from app.learning_memory.editor_client import MemoryEditorClient
    from app.learning_memory.source_dialog import SourceAdoptionDialog
    app = QApplication.instance() or QApplication([])
    store, root, content, _ = learned
    digest = record_replacement(store)
    with MemoryEditorClient(root) as editor:
        dialog = SourceAdoptionDialog(editor, content)
        def wait_idle():
            deadline = time.monotonic() + 5
            while dialog.busy and time.monotonic() < deadline:
                # 显式释放 GIL，让 Python 后台任务运行；仅 Qt 等待会让此测试偶发饥饿。
                app.processEvents(); time.sleep(0.01)
            assert not dialog.busy, dialog.status.text()
        try:
            wait_idle()
            assert dialog.items.count() == 1, dialog.status.text()
            dialog.items.setCurrentRow(0)
            wait_idle()
            assert not dialog.adopt_button.isEnabled()
            dialog.confirm.setChecked(True)
            assert dialog.adopt_button.isEnabled()
            dialog.adopt()
            wait_idle()
            assert dialog.adopted_snapshot["source"]["screenshot_sha256"] == digest
            assert dialog.adopted_snapshot["content"]["regions"] == []
        finally:
            dialog.close(); app.processEvents()



def _source_dialog_lifecycle_probe(root, collect):
    import gc
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMainWindow
    from app.desktop_review.content_library import InterfaceContentLibrary
    from app.learning_memory.editor_client import MemoryEditorClient
    from app.learning_memory.source_dialog import SourceAdoptionDialog
    app = QApplication([])
    store, library_root, snapshot, _ = learned.__wrapped__(Path(root))
    digest = record_replacement(store)
    with MemoryEditorClient(library_root) as editor:
        window = QMainWindow()
        library = InterfaceContentLibrary(editor, embedded=True, task_id="memory-local")
        window.setCentralWidget(library)
        window.show()
        library.pane.set_snapshot(snapshot)
        completed = []
        def open_dialog():
            dialog = SourceAdoptionDialog(editor, snapshot, window)
            timer = QTimer(dialog)
            state = [0]
            def advance():
                if dialog.busy:
                    return
                if state[0] == 0:
                    state[0] = 1
                    dialog.items.setCurrentRow(0)
                elif state[0] == 1:
                    state[0] = 2
                    dialog.confirm.setChecked(True)
                    dialog.adopt()
            timer.timeout.connect(advance)
            timer.start(20)
            dialog.exec()
            timer.stop()
            timer.timeout.disconnect(advance)
            adopted = dialog.adopted_snapshot
            assert adopted["source"]["screenshot_sha256"] == digest
            library.pane.set_snapshot(adopted)
            library._saved(adopted)
            # 模拟普通入口局部变量离开作用域，再处理 Qt 延迟析构事件。
            del dialog
            if collect:
                gc.collect()
            completed.append(True)
            QTimer.singleShot(100, app.quit)
        QTimer.singleShot(0, open_dialog)
        app.exec()
        assert completed == [True]
        assert editor.load_interface_content(snapshot["interface_id"])["revision"] == 2
        window.close()
    print("SOURCE_DIALOG_LIFECYCLE_OK", flush=True)


@pytest.mark.parametrize("collect", [False, True])
def test_source_adoption_modal_survives_wrapper_collection(tmp_path, collect):
    import os
    import subprocess
    import sys
    source = ("import runpy; from pathlib import Path; "
        + f"runpy.run_path({str(Path(__file__).resolve())!r})"
        + f"['_source_dialog_lifecycle_probe'](Path({str(tmp_path)!r}), {collect!r})")
    # 原生崩溃必须隔离；仅断言 adopted_snapshot 会漏掉返回主窗口后的退出。
    result = subprocess.run([sys.executable, "-X", "faulthandler", "-u", "-c", source],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SOURCE_DIALOG_LIFECYCLE_OK" in result.stdout

def test_batch_deletion_keeps_graph_and_image_history(workflow_store):
    from app.learning_memory.graph_source import logical_id
    from app.learning_memory.reader import read_project
    store = workflow_store
    record_search(store, "search-one")
    store.control("learning_stop", {}, "stop")
    with MemoryWorkspace(store.session.parent / "memory-library") as library:
        graph_id = logical_id("maps-demo")
        memory = read_project(library, graph_id)
        contents = library.list_interface_contents(task_id="memory-local")
        selection = [{"interface_id": row["interface_id"], "expected_revision": row["revision"],
                      "expected_sha256": row["content_sha256"]} for row in contents]
        preview = library.preview_interface_content_deletion(selection)
        assert all(item["references"][0]["current_reference"] for item in preview["items"])
        result = library.delete_interface_contents(selection)
        assert result["deleted_count"] == 2
        assert library.list_interface_contents(task_id="memory-local") == []
        assert read_project(library, graph_id, memory["snapshot_id"])["graph"] == memory["graph"]
        for row in contents:
            image = library.load_interface_content_evidence(row["interface_id"], row["version_id"])
            assert library._artifact_file(image["image_path"], "历史图").is_file()


def test_stale_batch_deletion_changes_nothing(workflow_store):
    store = workflow_store
    record_search(store, "search-one")
    store.control("learning_stop", {}, "stop")
    with MemoryWorkspace(store.session.parent / "memory-library") as library:
        contents = library.list_interface_contents(task_id="memory-local")
        selection = [{"interface_id": row["interface_id"], "expected_revision": row["revision"],
                      "expected_sha256": row["content_sha256"]} for row in contents]
        row = contents[-1]
        library.save_interface_content(row["interface_id"], row["revision"], row["content_sha256"], {"meaning": "更新"}, "edit-before-delete")
        with pytest.raises(RuntimeError, match="stale_revision"):
            library.delete_interface_contents(selection)
        assert len(library.list_interface_contents(task_id="memory-local")) == 2


def test_detaching_learned_node_preserves_interface_and_prior_snapshot(workflow_store):
    from app.learning_memory.graph_source import logical_id
    from app.learning_memory.reader import read_project
    store = workflow_store
    record_search(store, "search-one")
    store.control("learning_stop", {}, "stop")
    with MemoryWorkspace(store.session.parent / "memory-library") as library:
        graph_id = logical_id("maps-demo")
        old = read_project(library, graph_id)
        graph = library.load_graph_revision(graph_id)
        pin = graph["graph"]["nodes"][0]["interface_reference"]
        library.detach_interface_from_workflow(graph_id, pin["interface_id"], pin["version_id"],
            graph["revision"], graph["content_sha256"], "detach")
        assert len(read_project(library, graph_id)["graph"]["nodes"]) == 1
        assert read_project(library, graph_id)["graph"]["edges"] == []
        assert len(library.list_interface_contents(task_id="memory-local")) == 2
        assert read_project(library, graph_id, old["snapshot_id"])["graph"] == old["graph"]


@pytest.mark.parametrize("payload", [{"action": "list", "extra": True},
    {"action": "read", "issue_id": "../bad"},
    {"action": "submit", "issue_id": "interface-issue-00000000-0000-0000-0000-000000000000",
     "expected_baseline_sha256": "0" * 64, "changes": {"execute": True}}])
def test_feedback_rejects_invalid_contract(payload):
    with pytest.raises(ValueError):
        validate_control("learning_feedback", payload)


def test_normal_workbench_entry_resizes_edits_saves_and_reopens(learned, monkeypatch):
    import sys
    import importlib.util
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.learning_memory.editor_client import MemoryEditorClient
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _, root, original, _ = learned
    module_path = Path(__file__).resolve().parents[1] / "scripts/run_learning_memory_workbench.py"
    spec = importlib.util.spec_from_file_location("tested_memory_entry", module_path)
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    monkeypatch.setattr(sys, "argv", [str(module_path), "--data-dir", str(root.parent)])
    revisions = []

    def exercise():
        window = next(w for w in app.topLevelWidgets() if hasattr(w, "interfaces") and w.isVisible())
        try:
            wait_qt_idle(app, window.steps, window.projects, window.interfaces.pane)
            index = next(i for i in range(window.tabs.count()) if window.tabs.tabText(i) == "独立界面库")
            QTest.mouseClick(window.tabs.tabBar(), Qt.MouseButton.LeftButton,
                             pos=window.tabs.tabBar().tabRect(index).center())
            app.processEvents()
            pane = window.interfaces.pane
            assert window.interfaces.items.count() == 1
            assert pane.snapshot["interface_id"] == original["interface_id"]
            assert pane.canvas._pixmap_item.pixmap().width() == 160
            if not revisions:
                region = pane.canvas._regions["search-button"]
                QTest.mouseClick(pane.canvas.viewport(), Qt.MouseButton.LeftButton,
                                 pos=pane.canvas.mapFromScene(QPointF(45, 35)))
                assert pane._selected_region_id == "search-button"
                start = pane.canvas.mapFromScene(region.mapToScene(region.rect().bottomRight()))
                finish = pane.canvas.mapFromScene(QPointF(72, 51))
                QTest.mousePress(pane.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
                QTest.mouseMove(pane.canvas.viewport(), finish, delay=15)
                QTest.mouseRelease(pane.canvas.viewport(), Qt.MouseButton.LeftButton, pos=finish)
                assert pane._regions[0]["bbox"][2] > 30
                assert pane._regions[0]["bbox"][3] > 20
                pane.region_meaning_edit.setText("Search with the current variable")
                QTest.mouseClick(pane.save_button, Qt.MouseButton.LeftButton)
                wait_qt_idle(app, pane)
                assert not pane.dirty, window.interfaces.error.text()
                revisions.append(pane.snapshot["version_id"])
            else:
                assert pane.snapshot["version_id"] == revisions[0]
                assert pane.snapshot["content"]["regions"][0]["meaning"] == "Search with the current variable"
            # 窗口空闲时另一客户端可读取；原版本不被当前编辑覆盖。
            with MemoryEditorClient(root) as second:
                old = second.load_interface_content(original["interface_id"], original["version_id"])
                assert old["content"]["regions"][0]["bbox"] == [35, 25, 30, 20]
        finally:
            window.projects.cancel_loading()
            if window.interfaces.pane.dirty:
                window.interfaces.pane.discard_changes()
            window.interfaces.pane.cancel_loading()
            wait_qt_idle(app, window.steps, window.projects, window.interfaces.pane)
            assert window.close()
            window.deleteLater()
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        return 0

    monkeypatch.setattr(app, "exec", exercise)
    assert entry.main() == 0
    assert revisions[0] != original["version_id"]
    assert entry.main() == 0


def test_native_feedback_entry_agent_candidate_compare_and_adopt(learned, monkeypatch):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.desktop_review.content_library import InterfaceContentLibrary
    from app.desktop_review.interface_relearning_dialog import InterfaceRelearningDialog
    from app.learning_memory.editor_client import MemoryEditorClient
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    store, root, original, _ = learned
    errors = []
    with MemoryEditorClient(root) as editor:
        library = InterfaceContentLibrary(editor, embedded=True, task_id="memory-local")
        library.show(); app.processEvents()
        wait_qt_idle(app, library.pane)

        def respond():
            dialog = next(w for w in app.topLevelWidgets() if isinstance(w, InterfaceRelearningDialog) and w.isVisible())
            try:
                dialog.message.setText("Clarify the search control")
                QTest.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
                assert dialog.issues.count() == 1, dialog.status.text()
                dialog.issues.setCurrentRow(0)
                issue = dialog.issue
                response = store.control("learning_feedback", {"action": "submit", "issue_id": issue["issue_id"],
                    "expected_baseline_sha256": original["content_sha256"],
                    "changes": {"meaning": "Search page corrected by Agent"}}, "ui-agent-candidate")
                assert not response["content_adopted"]
                QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
                dialog.issues.setCurrentRow(0)
                app.processEvents()
                candidate_rect = dialog.candidates.visualItemRect(dialog.candidates.item(0))
                assert candidate_rect.height() >= 32
                assert dialog.issues.visualItemRect(dialog.issues.item(0)).height() >= 32
                QTest.mouseClick(dialog.candidates.viewport(), Qt.MouseButton.LeftButton,
                                 pos=candidate_rect.center())
                assert dialog.candidate_id == response['candidate']['candidate_id']
                assert not dialog.adopt_button.isEnabled()
                QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
                assert dialog.adopt_button.isEnabled(), dialog.status.text()
                assert dialog.diff_table.rowCount() == 1
                assert dialog.baseline_canvas._pixmap_item is not None
                QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
            except BaseException as error:
                errors.append(error)
            finally:
                dialog.reject()

        QTimer.singleShot(0, respond)
        QTest.mouseClick(library.pane.relearn_button, Qt.MouseButton.LeftButton)
        try:
            wait_qt_idle(app, library.pane)
            if errors:
                raise errors[0]
            assert library.pane.snapshot["content"]["meaning"] == "Search page corrected by Agent"
            assert editor.load_interface_content(original["interface_id"], original["version_id"])["content"]["meaning"] == "搜索首页"
        finally:
            library.pane.cancel_loading()
            wait_qt_idle(app, library.pane)
            library.close(); app.processEvents()


def test_graph_panel_edit_keeps_pin_until_explicit_adoption(workflow_store, monkeypatch):
    import time
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    from app.learning_memory.editor_client import MemoryEditorClient
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    store = workflow_store
    record_search(store, "search-one")
    store.control("learning_stop", {}, "stop")
    with MemoryEditorClient(store.session.parent / "memory-library") as editor:
        panel = WorkflowProjectsPane(editor)
        panel.resize(1380, 900); panel.show()
        def idle():
            deadline = time.monotonic() + 5
            while panel.is_busy and time.monotonic() < deadline:
                app.processEvents()
                # 释放 GIL，让文件读取线程推进；qWait 在此绑定中会饿死后台任务。
                time.sleep(0.01)
            assert not panel.is_busy, panel.status.text()
        try:
            idle()
            QTest.mouseClick(panel.project_list.viewport(), Qt.MouseButton.LeftButton,
                pos=panel.project_list.visualItemRect(panel.project_list.item(0)).center())
            idle()
            assert len(panel.snapshot["graph"]["nodes"]) == 2
            source_sha = panel.snapshot["source_sha256"]
            node = panel.snapshot["graph"]["nodes"][0]
            old_pin = dict(node["interface_reference"])
            item = panel.graph_view._node_items[node["node_id"]]
            QTest.mouseClick(panel.graph_view.viewport(), Qt.MouseButton.LeftButton,
                pos=panel.graph_view.mapFromScene(item.sceneBoundingRect().center()))
            idle()
            assert panel.interface_pane.snapshot["version_id"] == old_pin["version_id"]
            panel.interface_pane.meaning_edit.setText("Human-corrected search interface")
            QTest.mouseClick(panel.interface_pane.save_button, Qt.MouseButton.LeftButton)
            idle()
            assert not panel.interface_pane.dirty, panel.status.text()
            assert panel.snapshot["source_sha256"] == source_sha
            assert panel.interface_pane.snapshot["version_id"] == old_pin["version_id"]
            assert panel.interface_pane._read_only
            assert "固定" in panel.status.text()
            latest = editor.load_interface_content(old_pin["interface_id"])
            assert latest["content"]["meaning"] == "Human-corrected search interface"
            updated = editor.adopt_project_interface(panel.snapshot["logical_workflow_id"], node["node_id"], source_sha)
            panel._install(updated)
            panel.node_selected(node["node_id"])
            idle()
            assert panel.interface_pane.snapshot["version_id"] == latest["version_id"]
            assert not panel.interface_pane._read_only
            assert editor.load_interface_content(old_pin["interface_id"], old_pin["version_id"])["content"]["meaning"] != latest["content"]["meaning"]
        finally:
            panel.discard_changes(); panel.cancel_loading(); idle()
            panel.close(); app.processEvents()


def test_graph_long_transition_labels_do_not_hide_behind_nodes(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.desktop_review.graph_view import NativeWorkflowGraphView
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    view = NativeWorkflowGraphView()
    graph = {"nodes": [{"node_id": "a", "display_name": "Search"},
                       {"node_id": "b", "display_name": "Article"}],
             "edges": [{"edge_id": "forward", "source_node_id": "a", "target_node_id": "b",
                        "action_type": "input_sequence", "label": "input_sequence"},
                       {"edge_id": "back", "source_node_id": "b", "target_node_id": "a",
                        "action_type": "execute_recognition_plan", "label": "execute_recognition_plan"}]}
    scene, nodes, edges = view._build_scene(graph)
    try:
        for edge in edges.values():
            bounds = edge._label_background.sceneBoundingRect()
            assert all(not bounds.intersects(node.sceneBoundingRect()) for node in nodes.values())
        assert not edges["forward"]._label_background.sceneBoundingRect().intersects(
            edges["back"]._label_background.sceneBoundingRect())
    finally:
        scene.deleteLater(); view.close(); app.processEvents()
