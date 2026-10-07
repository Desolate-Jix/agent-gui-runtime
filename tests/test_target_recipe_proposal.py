"""固定 UIA 目标建议只来自同帧、已固定的学习证据。"""
from copy import deepcopy
from hashlib import sha256

from PIL import Image
import pytest

from app.learning_memory.target_recipe_proposal import propose_target_recipe
from app.learning_memory.target_recipe import load_target_recipe, save_target_recipe
from app.learning_memory.target_resolution import resolve_target_recipe


INTERFACE = "interface-" + "a" * 8 + "-" + "a" * 4 + "-" + "a" * 4 + "-" + "a" * 4 + "-" + "a" * 12
VERSION = "interface-version-" + "b" * 64


def fixture(tmp_path):
    path = tmp_path / "before.png"
    Image.new("RGB", (300, 200), "white").save(path)
    digest = sha256(path.read_bytes()).hexdigest()
    event = {"request_id": "run-1", "command_sha256": "c" * 64, "kind": "step",
             "operation": "execute_recognition_plan", "status": "returned", "action_executed": True,
             "action_hints": {"goal": "打开详情", "click_kind": "single"},
             "before": {"status": "referenced", "capture_id": "before-1", "sha256": digest}}
    identity = {"handle": 19, "process_id": 20, "process_create_time": 21.0}
    frame = {"capture_id": "before-1", "image_path": str(path), "sha256": digest,
             "image_size": {"width": 300, "height": 200}, "window_identity": identity,
             "window_rect": [0, 0, 300, 200], "application": {"executable_name": "fixture.exe"}}
    target = {"name": "打开详情", "control_type": "Button", "automation_id": "open-detail",
              "bbox": {"x": 100, "y": 50, "w": 40, "h": 20}, "visible": True, "enabled": True}
    anchor = {"name": "记录页面", "control_type": "Text", "automation_id": "page-heading",
              "bbox": {"x": 10, "y": 10, "w": 80, "h": 20}, "visible": True, "enabled": True}
    observation = {"contract_version": "learning_target_observation.v1", "event_id": "run-1",
                   "command_sha256": "c" * 64, "observation_stage": "before", "frame": frame,
                   "uia": {"status": "ok", "capture_id": "before-1", "window_identity": identity,
                           "snapshot": {"status": "ok", "scan_scope": "bound_window", "scan_complete": True,
                                        "truncated": False, "window": {"handle": 19, "process_id": 20},
                                        "controls": [target, anchor]}},
                   "candidate": {"capture_id": "before-1", "viewport_size": frame["image_size"],
                                 "source": "agent", "bbox": target["bbox"],
                                 "click_point": {"x": 120, "y": 60}, "freshness": "current_capture"}}
    interface = {"interface_id": INTERFACE, "version_id": VERSION, "content_sha256": "d" * 64,
                 "source": {"kind": "execution_memory_v1", "task_id": "memory-local",
                            "interface_key": "search", "state_key": "home", "event_id": "run-1",
                            "view": "before", "screenshot_sha256": digest}}
    bindings = {"action": {"kind": "click", "goal": "打开详情"}, "interface": interface, "inputs": {}}
    return event, observation, bindings


def test_proposes_deterministic_pinned_uia_recipe(tmp_path):
    event, observation, bindings = fixture(tmp_path)
    first = propose_target_recipe(event=event, observation=observation, bindings=bindings)
    assert first == propose_target_recipe(event=event, observation=observation, bindings=bindings)
    assert first["unresolved_items"] == []
    recipe = first["recipe"]
    assert recipe["strategies"] == [{"kind": "uia", "name": "打开详情", "control_type": "Button",
                                     "automation_id": "open-detail"}]
    assert recipe["scope"]["anchors"] == [{"kind": "uia", "name": "记录页面", "control_type": "Text",
                                                "automation_id": "page-heading"}]
    assert recipe["evidence_refs"][0]["source_image_sha256"] == observation["frame"]["sha256"]


def test_missing_or_ambiguous_target_and_anchor_remain_unresolved(tmp_path):
    event, observation, bindings = fixture(tmp_path)
    observation["uia"]["snapshot"]["controls"].append(deepcopy(observation["uia"]["snapshot"]["controls"][0]))
    assert propose_target_recipe(event=event, observation=observation, bindings=bindings)["recipe"] is None
    observation["uia"]["snapshot"]["controls"].pop()
    observation["uia"]["snapshot"]["controls"][1]["name"] = "12345"
    assert propose_target_recipe(event=event, observation=observation, bindings=bindings)["recipe"] is None


def test_visual_box_uses_unique_control_at_actual_click_point(tmp_path):
    event, observation, bindings = fixture(tmp_path)
    observation["candidate"]["bbox"] = {"x": 98, "y": 48, "w": 44, "h": 24}
    result = propose_target_recipe(event=event, observation=observation, bindings=bindings)
    assert result["recipe"] is not None
    assert result["recipe"]["strategies"][0]["automation_id"] == "open-detail"
    duplicate = deepcopy(observation["uia"]["snapshot"]["controls"][0])
    duplicate.update(name="重叠的按钮", automation_id="overlapping")
    observation["uia"]["snapshot"]["controls"].append(duplicate)
    assert propose_target_recipe(event=event, observation=observation, bindings=bindings)["recipe"] is None


def test_anchor_must_be_outside_full_selected_control(tmp_path):
    event, observation, bindings = fixture(tmp_path)
    observation["uia"]["snapshot"]["controls"][0]["bbox"] = {"x": 0, "y": 0, "w": 150, "h": 100}
    result = propose_target_recipe(event=event, observation=observation, bindings=bindings)
    assert result["recipe"] is None
    assert result["unresolved_items"] == [{"reason": "independent_stable_anchor_required"}]


def test_identity_and_source_tampering_rejected(tmp_path):
    event, observation, bindings = fixture(tmp_path)
    observation["command_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="command_binding"):
        propose_target_recipe(event=event, observation=observation, bindings=bindings)
    observation["command_sha256"] = event["command_sha256"]
    bindings["interface"]["source"]["screenshot_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source_image"):
        propose_target_recipe(event=event, observation=observation, bindings=bindings)


def test_action_must_match_recorded_intent(tmp_path):
    event, observation, bindings = fixture(tmp_path)
    bindings["action"]["goal"] = "打开别处"
    with pytest.raises(ValueError, match="action_semantics"):
        propose_target_recipe(event=event, observation=observation, bindings=bindings)
    bindings["action"]["goal"] = "打开详情"
    event.pop("action_hints")
    assert propose_target_recipe(event=event, observation=observation, bindings=bindings)["recipe"] is None


def test_save_reopen_and_resolve_current_uia(tmp_path):
    event, observation, bindings = fixture(tmp_path)
    recipe = propose_target_recipe(event=event, observation=observation, bindings=bindings)["recipe"]

    class Library:
        _artifact_root = tmp_path

        def load_interface_content(self, interface_id, version_id):
            assert (interface_id, version_id) == (INTERFACE, VERSION)
            return bindings["interface"]

        def load_interface_content_evidence(self, interface_id, version_id):
            return {"image_path": "before.png", "sha256": observation["frame"]["sha256"]}

        def _artifact_file(self, relative, label):
            return tmp_path / relative

    library = Library()
    saved = save_target_recipe(library, recipe)
    reference = {"recipe_id": saved["recipe_id"], "interface_key": "search", "state_key": "home"}
    assert load_target_recipe(library, reference) == recipe
    matched = resolve_target_recipe(library, reference, frame=observation["frame"],
                                    observations={"uia": observation["uia"]},
                                    bindings={"action": bindings["action"]})
    assert matched["status"] == "matched" and matched["context_verified"] is True
