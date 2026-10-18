"""当前窗口与独立锚点必须一起证明目标。"""
from copy import deepcopy
from hashlib import sha256

from PIL import Image

import pytest

from app.learning_memory.target_resolution import resolve_target_recipe


REF = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "search", "state_key": "home"}
IDENTITY = {"handle": 19, "process_id": 20, "process_create_time": 21.0}
FRAME = {"capture_id": "current-1", "image_path": "fresh.png", "sha256": "f" * 64,
         "image_size": {"width": 300, "height": 200}, "window_identity": IDENTITY,
         "application": {"executable_name": "fixture.exe", "window_class": "Fixture"}}


def control(name, kind, x, *, automation_id="", enabled=True, visible=True):
    return {"name": name, "control_type": kind, "automation_id": automation_id,
            "bbox": {"x": x, "y": 20, "w": 30, "h": 20}, "enabled": enabled, "visible": visible}


def recipe(*, anchor=True):
    scope = {"task_id": "memory-local", "interface_key": "search", "state_key": "home",
             "application": FRAME["application"]}
    if anchor:
        scope["anchors"] = [{"kind": "uia", "name": "页面", "control_type": "Pane"}]
    return {"scope": scope, "strategies": [{"kind": "uia", "name": "打开", "control_type": "Button"}],
            "action_semantics_sha256": "semantic"}


def observations(*controls):
    return {"uia": {"status": "ok", "capture_id": FRAME["capture_id"], "window_identity": IDENTITY,
                    "snapshot": {"status": "ok", "scan_complete": True, "truncated": False,
                                 "window": {"handle": 19, "process_id": 20}, "controls": list(controls)}}}


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    image = tmp_path / "fresh.png"
    Image.new("RGB", (300, 200), "white").save(image)
    FRAME["image_path"] = str(image)
    FRAME["sha256"] = sha256(image.read_bytes()).hexdigest()
    value = recipe()
    monkeypatch.setattr("app.learning_memory.target_resolution.load_target_recipe", lambda library, reference: value)
    monkeypatch.setattr("app.learning_memory.target_resolution.action_semantics_sha256", lambda *args, **kwargs: "semantic")
    return value


def resolve(observation):
    return resolve_target_recipe(None, REF, frame=FRAME, observations=observation,
                                 bindings={"action": {"kind": "click", "goal": "打开"}})


def test_unique_current_uia_target_and_independent_anchor(prepared):
    result = resolve(observations(control("页面", "Pane", 0), control("打开", "Button", 80)))
    assert result["status"] == "matched" and result["context_verified"] is True
    assert result["candidate"]["source"] == "memory_uia"
    assert result["candidate"]["bbox"] == {"x": 80, "y": 20, "w": 30, "h": 20}
    assert result["candidate"]["click_point"] == {"x": 95, "y": 30}
    assert result["candidate"]["capture_id"] == FRAME["capture_id"]


def test_duplicate_or_missing_target_cannot_match(prepared):
    base = control("页面", "Pane", 0)
    duplicate = resolve(observations(base, control("打开", "Button", 50), control("打开", "Button", 120)))
    assert duplicate["status"] == "ambiguous" and duplicate["candidate"] is None
    missing = resolve(observations(base))
    assert missing["status"] == "miss" and missing["candidate"] is None


def test_context_and_snapshot_binding_fail_closed(prepared):
    prepared["scope"].pop("anchors")
    assert resolve(observations(control("打开", "Button", 80)))["status"] == "unsupported"
    prepared["scope"]["anchors"] = [{"kind": "uia", "name": "页面", "control_type": "Pane"}]
    wrong_app = deepcopy(FRAME)
    wrong_app["application"]["executable_name"] = "other.exe"
    assert resolve_target_recipe(None, REF, frame=wrong_app,
        observations=observations(control("页面", "Pane", 0), control("打开", "Button", 80)),
        bindings={"action": {"kind": "click", "goal": "打开"}})["status"] == "invalid"
    stale = observations(control("页面", "Pane", 0), control("打开", "Button", 80))
    stale["uia"]["capture_id"] = "old"
    assert resolve(stale)["status"] == "invalid"


def test_semantic_change_and_incomplete_snapshot_rejected(prepared):
    prepared["action_semantics_sha256"] = "other"
    assert resolve(observations(control("页面", "Pane", 0), control("打开", "Button", 80)))["status"] == "invalid"
    prepared["action_semantics_sha256"] = "semantic"
    partial = observations(control("页面", "Pane", 0), control("打开", "Button", 80))
    partial["uia"]["snapshot"]["scan_complete"] = False
    assert resolve(partial)["status"] == "unsupported"


def test_template_anchor_and_target_must_be_distinct(prepared, monkeypatch):
    anchor_id = "template-" + "a" * 64
    target_id = "template-" + "b" * 64
    prepared["scope"]["anchors"] = [{"kind": "template", "template_id": anchor_id}]
    prepared["strategies"] = [{"kind": "template", "template_id": target_id}]
    def matched(library, request, path, evidence):
        x = 10 if request["template_id"] == anchor_id else 100
        return {"status": "matched", "label": "锚点" if x == 10 else "打开",
                "candidate": {"bbox": {"x": x, "y": 30, "w": 20, "h": 20}, "score": 0.98}}
    monkeypatch.setattr("app.learning_memory.target_resolution.match_template_frame", matched)
    result = resolve({})
    assert result["status"] == "matched" and result["candidate"]["source"] == "memory_template"
    assert result["evidence"]["anchors"][0]["template_id"] == anchor_id
    prepared["scope"]["anchors"] = [{"kind": "template", "template_id": target_id}]
    assert resolve({})["status"] == "invalid"


def test_current_png_digest_must_match(prepared):
    old = FRAME["sha256"]
    FRAME["sha256"] = "0" * 64
    try:
        assert resolve(observations(control("页面", "Pane", 0), control("打开", "Button", 80)))["status"] == "invalid"
    finally:
        FRAME["sha256"] = old
