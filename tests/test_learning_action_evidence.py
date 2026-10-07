"""同状态动作保留独立来源，不改代表界面或旧规则。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from PIL import Image
import pytest

from app.core.json_snapshot import write_json_snapshot
from app.desktop_review.workspace import DesktopReviewError
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.graph_source import logical_id, read_source, source_path
from app.learning_memory.receipt_adapter import content_hash
from app.learning_memory.target_recipe import load_target_recipe, save_target_recipe
from app.learning_memory.target_recipe_proposal import propose_target_recipe
from app.learning_memory.target_resolution import resolve_target_recipe
from app.learning_memory.workspace import MemoryWorkspace
from test_learning_observation_source import observation_scene


@pytest.fixture
def repeated_state(observation_scene):
    original_root, _, original_observation = observation_scene
    session = original_root.parent / "multi-action-session"
    (session / "responses").mkdir(parents=True)
    store = LearningEventStore(session)
    started = store.control("learning_start", {"scope": "workflow", "title": "同状态多动作",
        "project_id": "same-state"}, "start")
    events, observations = [], []
    for index, (name, color) in enumerate((("Search", "white"), ("Refresh", "green"))):
        event_id = f"click-{index}"
        command = {"kind": "step", "operation": "execute_recognition_plan",
                   "request": {"goal": name, "click_kind": "single"}}
        ticket = store.prepare(event_id, command, None)
        before_path, after_path = session / f"before-{index}.png", session / f"after-{index}.png"
        Image.new("RGB", (160, 100), color).save(before_path)
        Image.new("RGB", (160, 100), "green" if index == 0 else "blue").save(after_path)
        observation = deepcopy(original_observation)
        observation.update(event_id=event_id, command_sha256=ticket["command_sha256"])
        observation["frame"].update(capture_id=f"before-{index}", image_path=str(before_path),
                                    sha256=sha256(before_path.read_bytes()).hexdigest())
        observation["uia"]["capture_id"] = f"before-{index}"
        observation["uia"]["snapshot"]["capture_id"] = f"before-{index}"
        observation["uia"]["snapshot"]["controls"][1]["name"] = name
        observation["uia"]["snapshot"]["controls"].append({"name": "Other action",
            "control_type": "Button", "runtime_id": [3], "visible": True, "enabled": True,
            "bbox": {"x": 100, "y": 25, "w": 40, "h": 20}})
        observation["candidate"]["capture_id"] = f"before-{index}"
        after = {"image_path": str(after_path), "sha256": sha256(after_path.read_bytes()).hexdigest(),
                 "capture_id": f"after-{index}", "window_size": {"width": 160, "height": 100}}
        result = {"phase": "returned", "capture": after, "observation": {"capture": after},
                  "response": {"success": True, "data": {"result": {
                      "execution_path": {"action_executed": True}, "learning_observation": observation}}}}
        write_json_snapshot(session / "responses" / f"{event_id}.json", {
            "command": command, "status": "returned", "learning_binding": ticket, "result": result})
        store.record(event_id, ticket)
        event = store.control("learning_event", {"event_id": event_id}, f"read-{index}")["event"]
        identity = {"interface_key": "search", "state_key": "home", "meaning": "查询界面"}
        store.control("learning_review", {"review": {"event_id": event_id,
            "event_sha256": content_hash(event), "verdict": "success", "reviewer": "synthetic-contract",
            "reason": "合成回执只验证存储契约，不是实机输入验收",
            "before": {**identity, "frame_sha256": observation["frame"]["sha256"]},
            "after": {**identity, "frame_sha256": after["sha256"]}}}, f"review-{index}")
        events.append(event)
        observations.append(observation)
    store.control("learning_stop", {}, "stop")
    return store, session.parent / "memory-library", started, events, observations


def _compile(store, started):
    return store.control("learning_workflow", {
        "action": "compile", "learning_session_id": started["learning_id"]}, "compile")


def test_same_state_actions_use_distinct_evidence_preserving_pin_and_v1(repeated_state):
    store, root, started, events, observations = repeated_state
    with MemoryWorkspace(root) as library:
        original_graph = library.load_graph_revision(logical_id("same-state"))
        assert len(original_graph["graph"]["nodes"]) == 1
        pin = original_graph["graph"]["nodes"][0]["interface_reference"]
        content = library.load_interface_content(pin["interface_id"], pin["version_id"])
        assert content["source"]["event_id"] == "click-0"
        legacy = propose_target_recipe(event=events[0], observation=observations[0], bindings={
            "action": {"kind": "click", "goal": "Search", "click_kind": "single"},
            "interface": content})["recipe"]
        assert legacy["contract_version"] == "target_recipe.v1"
        save_target_recipe(library, legacy)
    protected = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    draft = _compile(store, started)
    proposals = {row["event_id"]: row for row in draft["proposed_target_recipes"]}
    assert set(proposals) == {"click-0", "click-1"}
    assert {row["recipe"]["contract_version"] for row in proposals.values()} == {"target_recipe.v2"}
    second = proposals["click-1"]
    assert second["recipe"]["strategies"][0]["name"] == "Refresh"
    assert second["recipe"]["evidence_refs"][0]["source_image_sha256"] == observations[0]["frame"]["sha256"]
    assert second["recipe"]["evidence_refs"][1]["observation_sha256"] == events[1]["target_observation"]["sha256"]
    assert not any(row["reason"] == "exact_before_interface_required" for row in draft["unresolved_items"])
    baseline = store.control("learning_workflow", {"action": "read", "workflow_id": draft["workflow_id"]}, "read")
    saved = store.control("learning_workflow", {"action": "save", "workflow_id": draft["workflow_id"],
        "expected_sha256": baseline["content_sha256"], "definition": draft["definition"],
        "target_recipes": [row["recipe"] for row in proposals.values()]}, "save")
    for path, raw in protected.items():
        assert path.read_bytes() == raw, path
    with MemoryWorkspace(root) as library:
        assert library.load_graph_revision(logical_id("same-state")) == original_graph
        assert load_target_recipe(library, {"recipe_id": legacy["recipe_id"],
            "interface_key": "search", "state_key": "home"}) == legacy
        value = load_target_recipe(library, second["reference"])
        assert value == second["recipe"]
        current = deepcopy(observations[1])
        current["uia"]["snapshot"]["controls"][1]["bbox"]["x"] += 20
        matched = resolve_target_recipe(library, second["reference"], frame=current["frame"],
            observations={"uia": current["uia"]}, bindings={"action": draft["definition"]["steps"][1]["action"]})
        assert matched["status"] == "matched" and matched["context_verified"] is True
        loaded = library.load_workflow_program(saved["workflow_id"], saved["program_id"])
        assert loaded["definition"] == saved["definition"]
    assert _compile(store, started)["existing_program_id"] == saved["program_id"]


@pytest.mark.parametrize("change", ["event", "observation", "state", "bundle", "unknown_field"])
def test_wrong_action_evidence_is_rejected_before_saving(repeated_state, change):
    store, root, started, events, _ = repeated_state
    draft = _compile(store, started)
    proposals = {row["event_id"]: row for row in draft["proposed_target_recipes"]}
    assert "click-1" in proposals
    recipe = deepcopy(proposals["click-1"]["recipe"])
    evidence = recipe["evidence_refs"][1]
    if change == "event": evidence["event_id"] = "click-0"
    elif change == "observation": evidence["observation_sha256"] = events[0]["target_observation"]["sha256"]
    elif change == "state": evidence["source_node_id"] = "state-" + "0" * 32
    elif change == "bundle": evidence["bundle_sha256"] = "0" * 64
    else: evidence["untrusted_path"] = "elsewhere"
    recipe["recipe_id"] = "target-recipe-" + content_hash({key: value for key, value in recipe.items() if key != "recipe_id"})
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError):
            save_target_recipe(library, recipe)
    assert not list((root / "desktop-review/target-recipes").glob("*.json"))


@pytest.mark.parametrize("change", ["bundle", "observation", "action_image", "representative_image"])
def test_archival_tamper_is_rejected_when_reopening_recipe(repeated_state, change):
    store, root, started, _, observations = repeated_state
    draft = _compile(store, started)
    second = next(row for row in draft["proposed_target_recipes"] if row["event_id"] == "click-1")
    recipe = second["recipe"]
    evidence = recipe["evidence_refs"][1]
    with MemoryWorkspace(root) as library:
        save_target_recipe(library, recipe)
    if change == "bundle":
        path = root / source_path(evidence["bundle_sha256"])
        path.write_bytes(b'{}')
    elif change == "observation":
        path = root / "desktop-review/learning-observations" / (evidence["observation_sha256"] + ".json")
        path.write_bytes(b'{}')
    else:
        index = 1 if change == "action_image" else 0
        path = root / "desktop-review/evidence-objects" / (observations[index]["frame"]["sha256"] + ".png")
        Image.new("RGB", (160, 100), "black").save(path)
    with MemoryWorkspace(root) as library:
        with pytest.raises(DesktopReviewError if change == "representative_image" else ValueError):
            load_target_recipe(library, second["reference"])


@pytest.mark.parametrize("change", ["review_state", "command"])
def test_rehashed_source_cannot_misbind_review_state_or_command(repeated_state, change):
    from app.desktop_review.external_mapping import canonical_json_bytes
    store, root, started, _, _ = repeated_state
    draft = _compile(store, started)
    recipe = deepcopy(next(row["recipe"] for row in draft["proposed_target_recipes"] if row["event_id"] == "click-1"))
    evidence = recipe["evidence_refs"][1]
    with MemoryWorkspace(root) as library:
        graph = library.load_graph_revision(logical_id("same-state"))
        bundle = read_source(library, graph["source_refs"])
    segment = bundle["segments"][0]
    event = next(row for row in segment["events"] if row["request_id"] == "click-1")
    record = segment["reviews"]["click-1"]
    if change == "review_state":
        record["review"]["before"]["state_key"] = "other"
    else:
        event["command_sha256"] = "0" * 64
        record["review"]["event_sha256"] = content_hash(event)
    record["review_sha256"] = content_hash({key: value for key, value in record.items() if key != "review_sha256"})
    evidence["bundle_sha256"] = content_hash(bundle)
    path = root / source_path(evidence["bundle_sha256"])
    path.write_bytes(canonical_json_bytes(bundle) + b"\n")
    recipe["recipe_id"] = "target-recipe-" + content_hash({key: value for key, value in recipe.items() if key != "recipe_id"})
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match="target_recipe_action_"):
            save_target_recipe(library, recipe)
    assert not list((root / "desktop-review/target-recipes").glob("*.json"))


@pytest.mark.parametrize("change", ["target", "anchor", "intent"])
def test_captured_rule_cannot_claim_other_target_anchor_or_action(repeated_state, change):
    from app.learning_memory.target_recipe import action_semantics_sha256
    store, root, started, _, _ = repeated_state
    draft = _compile(store, started)
    recipe = deepcopy(next(row["recipe"] for row in draft["proposed_target_recipes"] if row["event_id"] == "click-1"))
    action = {"kind": "click", "goal": "Refresh", "click_kind": "single"}
    if change == "target": recipe["strategies"][0]["name"] = "Other action"
    elif change == "anchor": recipe["scope"]["anchors"] = deepcopy(recipe["strategies"])
    else: action["goal"] = "Other intent"
    recipe["action_semantics_sha256"] = action_semantics_sha256(action, scope=recipe["scope"], strategies=recipe["strategies"])
    recipe["recipe_id"] = "target-recipe-" + content_hash({key: value for key, value in recipe.items() if key != "recipe_id"})
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match="target_recipe_captured_"):
            save_target_recipe(library, recipe)
    assert not list((root / "desktop-review/target-recipes").glob("*.json"))
