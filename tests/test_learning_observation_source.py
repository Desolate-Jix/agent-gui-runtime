"""动作前观察必须随真实事件归档，不能用事后或错身份数据补齐。"""
from copy import deepcopy
from hashlib import sha256
import json

from PIL import Image
import pytest

from app.learning_memory.workspace import MemoryWorkspace


@pytest.fixture
def observation_scene(tmp_path):
    image = tmp_path / "before.png"
    Image.new("RGB", (160, 100), "white").save(image)
    identity = {"handle": 17, "process_id": 29, "process_create_time": 123.0}
    frame = {"capture_id": "before-1", "image_path": str(image),
             "sha256": sha256(image.read_bytes()).hexdigest(),
             "image_size": {"width": 160, "height": 100}, "window_identity": identity,
             "window_rect": [20, 30, 180, 130],
             "application": {"executable_name": "fixture.exe", "window_class": "Fixture"}}
    event = {"request_id": "click-one", "command_sha256": "a" * 64,
             "before": {"status": "referenced", "capture_id": "before-1",
                        "sha256": frame["sha256"], "image_path": str(image),
                        "window_size": frame["image_size"]}}
    controls = [{"name": "Record desk", "control_type": "Text", "runtime_id": [1],
                 "visible": True, "enabled": True, "bbox": {"x": 1, "y": 1, "w": 80, "h": 15}},
                {"name": "Search", "control_type": "Button", "runtime_id": [2],
                 "visible": True, "enabled": True, "bbox": {"x": 35, "y": 25, "w": 30, "h": 20}}]
    snapshot = {"status": "ok", "scan_scope": "bound_window", "scan_complete": True,
                "truncated": False, "window": {"handle": 17, "process_id": 29},
                "capture_id": "before-1", "window_identity": identity, "controls": controls}
    observation = {"contract_version": "learning_target_observation.v1", "event_id": "click-one",
                   "command_sha256": event["command_sha256"], "observation_stage": "before",
                   "frame": frame, "uia": {"status": "ok", "capture_id": "before-1",
                                             "window_identity": identity, "snapshot": snapshot},
                   "candidate": {"capture_id": "before-1", "viewport_size": frame["image_size"],
                                 "source": "agent_visual", "bbox": controls[1]["bbox"],
                                 "click_point": {"x": 50, "y": 35}, "freshness": "current_capture"}}
    return tmp_path / "library", event, observation


def test_archive_reopen_uses_immutable_png_after_original_is_removed(observation_scene):
    from app.learning_memory.learning_observation_source import (
        archive_learning_observation, load_learning_observation)
    root, event, observation = observation_scene
    original = deepcopy(observation)
    with MemoryWorkspace(root) as library:
        reference = archive_learning_observation(library, event=event, observation=observation)
        assert archive_learning_observation(library, event=event, observation=observation) == reference
    from pathlib import Path
    Path(observation["frame"]["image_path"]).unlink()
    with MemoryWorkspace(root) as library:
        loaded = load_learning_observation(library, reference)
        assert loaded["uia"] == original["uia"]
        assert loaded["candidate"] == original["candidate"]
        assert loaded["frame"]["sha256"] == original["frame"]["sha256"]
        assert Path(loaded["frame"]["image_path"]).is_file()
    assert observation == original


@pytest.mark.parametrize("change", ["after", "event", "command", "capture", "image_hash",
    "identity", "viewport", "application", "incomplete", "snapshot_identity", "candidate_capture",
    "candidate_point", "candidate_bbox", "candidate_stale", "original_image_changed"])
def test_invalid_before_evidence_is_rejected_before_archival(observation_scene, change):
    from app.learning_memory.learning_observation_source import archive_learning_observation
    root, event, observation = observation_scene
    if change == "after": observation["observation_stage"] = "after"
    elif change == "event": observation["event_id"] = "other"
    elif change == "command": observation["command_sha256"] = "b" * 64
    elif change == "capture": event["before"]["capture_id"] = "other"
    elif change == "image_hash": event["before"]["sha256"] = "b" * 64
    elif change == "identity": observation["uia"]["window_identity"] = {"handle": 18}
    elif change == "viewport": observation["frame"]["image_size"] = {"width": 161, "height": 100}
    elif change == "application": observation["frame"]["application"] = {}
    elif change == "incomplete": observation["uia"]["snapshot"]["scan_complete"] = False
    elif change == "snapshot_identity": observation["uia"]["snapshot"]["window"]["process_id"] = 30
    elif change == "candidate_capture": observation["candidate"]["capture_id"] = "other"
    elif change == "candidate_point": observation["candidate"]["click_point"] = {"x": 155, "y": 95}
    elif change == "candidate_bbox": observation["candidate"]["bbox"] = {"x": -1, "y": 25, "w": 30, "h": 20}
    elif change == "candidate_stale": observation["candidate"]["freshness"] = "stale"
    elif change == "original_image_changed": Image.new("RGB", (160, 100), "black").save(observation["frame"]["image_path"])
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match="learning_observation_"):
            archive_learning_observation(library, event=event, observation=observation)
        assert not list((root / "desktop-review" / "learning-observations").glob("*.json"))


@pytest.mark.parametrize("change", ["payload", "png", "reference"])
def test_changed_archive_is_not_accepted(observation_scene, change):
    from app.learning_memory.learning_observation_source import (
        archive_learning_observation, load_learning_observation)
    root, event, observation = observation_scene
    with MemoryWorkspace(root) as library:
        reference = archive_learning_observation(library, event=event, observation=observation)
        if change == "payload":
            path = root / "desktop-review" / "learning-observations" / (reference["sha256"] + ".json")
            value = json.loads(path.read_text(encoding="utf-8"))
            value["candidate"]["click_point"]["x"] += 1
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        elif change == "png":
            path = root / "desktop-review" / "evidence-objects" / (observation["frame"]["sha256"] + ".png")
            Image.new("RGB", (160, 100), "black").save(path)
        else:
            reference["sha256"] = "../bad"
        with pytest.raises(ValueError, match="learning_observation_"):
            load_learning_observation(library, reference)


def record_learning_click(observation_scene):
    from app.core.json_snapshot import write_json_snapshot
    from app.learning_memory.event_store import LearningEventStore
    from app.learning_memory.receipt_adapter import content_hash
    root, _, observation = observation_scene
    session = root.parent / "fresh-session"
    (session / "responses").mkdir(parents=True)
    store = LearningEventStore(session)
    started = store.control("learning_start", {"scope": "workflow", "title": "查询记录",
        "project_id": "search-records"}, "start")
    command = {"kind": "step", "operation": "execute_recognition_plan",
               "request": {"goal": "Search", "click_kind": "single"}}
    ticket = store.prepare("click-one", command, None)
    observation = deepcopy(observation)
    observation["command_sha256"] = ticket["command_sha256"]
    from pathlib import Path
    before_path = session / "actual-before.png"
    before_path.write_bytes(Path(observation["frame"]["image_path"]).read_bytes())
    observation["frame"]["image_path"] = str(before_path)
    after_path = session / "after.png"
    Image.new("RGB", (160, 100), "blue").save(after_path)
    after = {"image_path": str(after_path), "sha256": sha256(after_path.read_bytes()).hexdigest(),
             "capture_id": "after-1", "window_size": {"width": 160, "height": 100}}
    result = {"phase": "returned", "capture": after, "observation": {"capture": after},
              "response": {"success": True, "data": {"result": {
                  "execution_path": {"action_executed": True}, "learning_observation": observation}}}}
    write_json_snapshot(session / "responses/click-one.json", {
        "command": command, "status": "returned", "learning_binding": ticket, "result": result})
    store.record("click-one", ticket)
    event = store.control("learning_event", {"event_id": "click-one"}, "read")["event"]
    store.control("learning_review", {"review": {"event_id": "click-one", "event_sha256": content_hash(event),
        "verdict": "success", "reviewer": "synthetic-contract", "reason": "合成终态仅用于源码契约",
        "before": {"interface_key": "search", "state_key": "home", "meaning": "查询首页",
                   "frame_sha256": observation["frame"]["sha256"]},
        "after": {"interface_key": "search", "state_key": "results", "meaning": "查询结果",
                  "frame_sha256": after["sha256"]}}}, "review")
    store.control("learning_stop", {}, "stop")
    return store, root.parent / "memory-library", started, event, observation


def test_original_receipt_archives_actual_target_frame_and_compiles_without_session_files(observation_scene):
    from pathlib import Path
    from app.learning_memory.graph_source import read_source, bundle_segments, logical_id
    from app.learning_memory.learning_observation_source import load_learning_observation
    from app.learning_memory.workflow_compiler import compile_workflow_draft
    store, root, started, event, observation = record_learning_click(observation_scene)
    assert event["before"]["capture_id"] == observation["frame"]["capture_id"]
    reference = event["target_observation"]
    with MemoryWorkspace(root) as library:
        graph = library.load_graph_revision(logical_id("search-records"))
        segment = bundle_segments(read_source(library, graph["source_refs"]))[0]
        assert segment["target_observations"][event["request_id"]] == reference
        archived = load_learning_observation(library, reference)
        assert archived["candidate"] == observation["candidate"]
    Path(observation["frame"]["image_path"]).unlink()
    (store.session / "responses/click-one.json").unlink()
    with MemoryWorkspace(root) as library:
        draft = compile_workflow_draft(library, learning_session_id=started["learning_id"],
                                       parameter_bindings={}, annotations={})
        proposal = draft["proposed_target_recipes"][0]
        assert proposal["source"] == "captured_uia_proposal"
        assert proposal["recipe"]["strategies"][0]["name"] == "Search"
        assert draft["definition"]["steps"][0]["review_status"] == "pending"
        assert not list((root / "desktop-review/target-recipes").glob("*.json"))
        assert compile_workflow_draft(library, learning_session_id=started["learning_id"],
                                     parameter_bindings={}, annotations={}) == draft


def test_generated_recipe_saves_with_program_and_reopens_through_original_control(observation_scene):
    from app.learning_memory.target_recipe import load_target_recipe
    store, root, started, _, _ = record_learning_click(observation_scene)
    compile_request = {"action": "compile", "learning_session_id": started["learning_id"]}
    draft = store.control("learning_workflow", compile_request, "compile")
    baseline = store.control("learning_workflow", {"action": "read", "workflow_id": draft["workflow_id"]}, "read-program")
    request = {"action": "save", "workflow_id": draft["workflow_id"],
               "expected_sha256": baseline["content_sha256"], "definition": draft["definition"],
               "target_recipes": [item["recipe"] for item in draft["proposed_target_recipes"]]}
    saved = store.control("learning_workflow", request, "save-draft")
    assert store.control("learning_workflow", request, "save-draft") == saved
    assert saved["definition"]["steps"][0]["review_status"] == "pending"
    with MemoryWorkspace(root) as library:
        loaded = library.load_workflow_program(saved["workflow_id"], saved["program_id"])
        reference = loaded["definition"]["steps"][0]["action"]["target_memory"]
        assert load_target_recipe(library, reference)["strategies"][0]["name"] == "Search"
    protected = store.control("learning_workflow", compile_request, "compile-again")
    assert protected["existing_program_id"] == saved["program_id"]
    changed = deepcopy(request)
    changed["target_recipes"] = []
    with pytest.raises(ValueError, match="task_program_idempotency_conflict"):
        store.control("learning_workflow", changed, "save-draft")


@pytest.mark.parametrize("change", ["changed_goal", "unreferenced", "bad_recipe", "wrong_revision"])
def test_invalid_proposed_recipe_never_updates_program_or_creates_rules(observation_scene, change):
    store, root, started, _, _ = record_learning_click(observation_scene)
    draft = store.control("learning_workflow", {"action": "compile", "learning_session_id": started["learning_id"]}, "compile")
    baseline = store.control("learning_workflow", {"action": "read", "workflow_id": draft["workflow_id"]}, "read-program")
    request = {"action": "save", "workflow_id": draft["workflow_id"],
               "expected_sha256": baseline["content_sha256"], "definition": draft["definition"],
               "target_recipes": [item["recipe"] for item in draft["proposed_target_recipes"]]}
    if change == "changed_goal": request["definition"]["steps"][0]["action"]["goal"] = "Other"
    elif change == "unreferenced": request["definition"]["steps"][0]["action"].pop("target_memory")
    elif change == "bad_recipe": request["target_recipes"][0]["strategies"][0]["name"] = "Other"
    else: request["expected_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        store.control("learning_workflow", request, "save-invalid")
    assert store.control("learning_workflow", {"action": "read", "workflow_id": draft["workflow_id"]}, "read-after") == baseline
    assert not list((root / "desktop-review/target-recipes").glob("*.json"))
