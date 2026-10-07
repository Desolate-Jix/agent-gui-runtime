"""真实记忆文件到原执行适配器；仅替换原生观察边界。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from app.desktop_review.external_mapping import canonical_json_bytes
from app.learning_memory.target_recipe import action_semantics_sha256, save_target_recipe
from app.learning_memory.templates import save_template
from app.learning_memory.workspace import MemoryWorkspace
from tests.test_learning_memory_v1 import learned


@pytest.fixture
def runtime_scene(learned, monkeypatch, tmp_path):
    _, root, content, original = learned
    scope = {"task_id": "memory-local", "interface_key": "search", "state_key": "home",
             "application": {"executable_name": "fixture.exe"},
             "anchors": [{"kind": "uia", "name": "Search page", "control_type": "Text"}]}
    action = {"kind": "click", "goal": "Search", "click_kind": "single"}
    with MemoryWorkspace(root) as library:
        template = save_template(library, {"interface_id": content["interface_id"],
            "version_id": content["version_id"], "region_id": "search-button", "padding": 0, "radius": 50})
        strategies = [{"kind": "template", "template_id": template["template_id"]}]
        body = {"contract_version": "target_recipe.v1", "scope": scope, "strategies": strategies,
            "interface_id": content["interface_id"], "interface_version_id": content["version_id"],
            "action_semantics_sha256": action_semantics_sha256(action, scope=scope, strategies=strategies),
            "evidence_refs": [{"kind": "interface_content", "content_sha256": content["content_sha256"],
                               "source_image_sha256": original["sha256"]}]}
        recipe = save_target_recipe(library, {**body,
            "recipe_id": "target-recipe-" + sha256(canonical_json_bytes(body)).hexdigest()})
    reference = {"recipe_id": recipe["recipe_id"], "interface_key": "search", "state_key": "home"}
    bound = SimpleNamespace(handle=17, process_id=29)
    manager = SimpleNamespace(bind_window_by_handle=lambda handle: bound)
    co = SimpleNamespace(_memory_library_root=root, _windows=lambda: manager)
    identity = {"handle": 17, "process_id": 29, "process_create_time": 123.0}
    current = tmp_path / "now.png"
    pixels = np.array(Image.open(original["image_path"]).convert("RGB"))
    patch = pixels[25:45, 35:65].copy()
    pixels[25:45, 35:65] = 0
    pixels[35:55, 45:75] = patch
    Image.fromarray(pixels).save(current)
    state = {"anchor": True, "calls": 0, "identity": identity, "current": current}
    def capture(coordinator, handle, pid, *, image_path=None, recipe=None):
        state["calls"] += 1
        # 截图/UIA 读取期间不得持有库的进程锁。
        with MemoryWorkspace(root):
            pass
        path = Path(image_path or state["current"])
        frame = {"capture_id": f"fresh-{state['calls']}", "image_path": str(path),
            "sha256": sha256(path.read_bytes()).hexdigest(), "image_size": {"width": 160, "height": 100},
            "window_identity": deepcopy(state["identity"]), "application": {"executable_name": "fixture.exe"}}
        controls = [{"name": "Search page", "control_type": "Text", "visible": True, "enabled": True,
                     "bbox": {"x": 2, "y": 2, "w": 20, "h": 10}}] if state["anchor"] else []
        observation = {"uia": {"status": "ok", "capture_id": frame["capture_id"],
            "window_identity": deepcopy(state["identity"]), "snapshot": {"status": "ok", "scan_complete": True,
            "truncated": False, "window": {"handle": 17, "process_id": 29}, "controls": controls}}}
        return frame, observation
    monkeypatch.setattr("app.learning_memory.memory_observation.capture_memory_observation", capture)
    return co, reference, state


def prepare(scene, *, request_overrides=None, **extra):
    from app.learning_memory.runtime_target import prepare_memory_grounding
    co, reference, _ = scene
    request = {"goal": "Search", "target_memory": reference, **(request_overrides or {})}
    return prepare_memory_grounding(co, request=request,
                                    handle=17, pid=29, **extra)


def test_pinned_recipe_resolves_moved_template_and_rechecks_current_scope(runtime_scene):
    target, resolution = prepare(runtime_scene)
    state = runtime_scene[2]
    assert resolution["candidate"]["click_point"] == {"x": 60, "y": 45}
    identity = {"target_window_handle": 17, "process_id": 29, "process_create_time": 123.0}
    plan = target.plan(image_path=state["current"], goal="Search", identity=identity)
    assert plan["execution_path"]["vision_model_used"] is False
    assert state["calls"] == 2
    state["anchor"] = False
    with pytest.raises(ValueError, match="memory_grounding"):
        target.plan(image_path=state["current"], goal="Search", identity=identity)


def test_expected_context_miss_is_reported_without_target(runtime_scene):
    runtime_scene[2]["anchor"] = False
    target, resolution = prepare(runtime_scene)
    assert target is None and resolution["status"] == "miss"
    assert resolution["reason"] == "context_anchor_miss"


def test_foreign_root_or_changed_action_never_silently_falls_back(runtime_scene, tmp_path):
    co, _, state = runtime_scene
    with pytest.raises(ValueError, match="^memory_action_click_kind_mismatch$"):
        prepare(runtime_scene, action={"kind": "click", "goal": "Search", "click_kind": "double"})
    with pytest.raises(ValueError, match="^action_semantics_changed$"):
        prepare(runtime_scene, request_overrides={"click_kind": "double"},
                action={"kind": "click", "goal": "Search", "click_kind": "double"})
    assert state["calls"] == 0
    co._memory_library_root = tmp_path / "foreign-library"
    with pytest.raises(ValueError, match="memory_library_unavailable"):
        prepare(runtime_scene)


def test_corrupt_recipe_fails_before_current_observation(runtime_scene):
    co, reference, state = runtime_scene
    path = co._memory_library_root / "desktop-review" / "target-recipes" / (reference["recipe_id"] + ".json")
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="target_recipe_invalid"):
        prepare(runtime_scene)
    assert state["calls"] == 0
