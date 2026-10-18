"""可见行记忆仅使用本次完整 UIA 树及本次运行变量。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

from PIL import Image
import pytest

from app.learning_memory.target_resolution import resolve_target_recipe


IDENTITY = {"handle": 19, "process_id": 20, "process_create_time": 21.0}
REF = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "search", "state_key": "results"}
RULE = {"kind": "visible_row", "container": {"name": "结果列表", "control_type": "List"},
        "row": {"control_type": "ListItem"},
        "properties": [{"property": "title", "control_type": "Text", "read": "name"}],
        "constraints": [{"property": "title", "operator": "eq", "value": {"source": "input", "name": "wanted"}}],
        "action": {"name": "打开", "control_type": "Button"}}


def control(identifier, name, kind, bbox, ancestors):
    return {"control_id": identifier, "ancestor_control_ids": ancestors, "name": name,
            "control_type": kind, "automation_id": "", "bbox": bbox,
            "visible": True, "enabled": True}


def tree(frame, *, duplicate=False):
    controls = [control("anchor", "结果页", "Pane", {"x": 0, "y": 0, "w": 300, "h": 20}, []),
        control("list", "结果列表", "List", {"x": 0, "y": 30, "w": 300, "h": 160}, []),
        control("row1", "", "ListItem", {"x": 0, "y": 40, "w": 300, "h": 50}, ["list"]),
        control("title1", "Alpha", "Text", {"x": 20, "y": 45, "w": 80, "h": 20}, ["list", "row1"]),
        control("action1", "打开", "Button", {"x": 220, "y": 45, "w": 50, "h": 30}, ["list", "row1"])]
    if duplicate:
        controls += [control("row2", "", "ListItem", {"x": 0, "y": 100, "w": 300, "h": 50}, ["list"]),
            control("title2", "Alpha", "Text", {"x": 20, "y": 105, "w": 80, "h": 20}, ["list", "row2"]),
            control("action2", "打开", "Button", {"x": 220, "y": 105, "w": 50, "h": 30}, ["list", "row2"])]
    snapshot = {"provider": "windows_uia", "status": "ok", "scan_scope": "bound_window",
                "scan_complete": True, "truncated": False, "provider_tree_valid": True,
                "capture_id": frame["capture_id"], "window_identity": IDENTITY,
                "window": {"handle": 19, "process_id": 20}, "controls": controls}
    return {"uia": {"status": "ok", "capture_id": frame["capture_id"],
                    "window_identity": IDENTITY, "snapshot": snapshot}}


@pytest.fixture
def current(monkeypatch, tmp_path):
    image = tmp_path / "current.png"
    Image.new("RGB", (300, 200), "white").save(image)
    frame = {"capture_id": "capture-now", "image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
             "image_size": {"width": 300, "height": 200}, "window_identity": IDENTITY,
             "application": {"executable_name": "fixture.exe"}}
    recipe = {"scope": {"task_id": "fresh", "interface_key": "search", "state_key": "results",
                        "application": {"executable_name": "fixture.exe"},
                        "anchors": [{"kind": "uia", "name": "结果页", "control_type": "Pane"}]},
              "strategies": [RULE], "action_semantics_sha256": "semantic"}
    monkeypatch.setattr("app.learning_memory.target_resolution.load_target_recipe", lambda *_: recipe)
    monkeypatch.setattr("app.learning_memory.target_resolution.action_semantics_sha256", lambda *a, **k: "semantic")
    return frame


def call(frame, *, value="Alpha", duplicate=False, bindings=None, snapshot=None):
    obs = tree(frame, duplicate=duplicate) if snapshot is None else snapshot
    b = bindings if bindings is not None else {"action": {"kind": "click", "goal": "打开详情"},
             "run_id": "run-now", "inputs": {"wanted": value}, "outputs": {}}
    return resolve_target_recipe(None, REF, frame=frame, observations=obs, bindings=b)


def test_visible_row_matches_only_current_row_action(current):
    result = call(current)
    assert result["status"] == "matched" and result["context_verified"] is True
    assert result["candidate"]["source"] == "memory_visible_row"
    assert result["candidate"]["bbox"] == {"x": 220, "y": 45, "w": 50, "h": 30}
    assert result["candidate"]["score"] == 1.0
    assert result["evidence"]["anchors"][0]["name"] == "结果页"
    assert result["evidence"]["row"]["row_control_id"] == "row1"


def test_visible_row_missing_ambiguous_and_binding_rejected(current):
    assert call(current, value="Beta")["status"] == "miss"
    assert call(current, duplicate=True)["status"] == "ambiguous"
    missing = call(current, bindings={"action": {"kind": "click", "goal": "打开详情"}})
    assert (missing["status"], missing["reason"]) == ("unsupported", "trial_bindings_required")
    unknown = call(current, bindings={"action": {"kind": "click", "goal": "打开详情"},
        "run_id": "run-now", "inputs": {}, "outputs": {}})
    assert (unknown["status"], unknown["reason"]) == ("invalid", "missing_input")
    stale = tree(current)
    stale["uia"]["snapshot"]["capture_id"] = "old"
    assert call(current, snapshot=stale)["status"] == "invalid"


def test_visible_row_anchor_must_be_independent(current, monkeypatch):
    from app.learning_memory import target_resolution
    original = target_resolution.load_target_recipe(None, REF)
    changed = deepcopy(original)
    changed["scope"]["anchors"] = [{"kind": "uia", "name": "打开", "control_type": "Button"}]
    monkeypatch.setattr(target_resolution, "load_target_recipe", lambda *_: changed)
    assert call(current)["status"] == "invalid"


def test_output_binding_is_from_same_run_and_bad_geometry_is_invalid(current, monkeypatch):
    from app.learning_memory import target_resolution
    changed = deepcopy(target_resolution.load_target_recipe(None, REF))
    changed["strategies"][0]["constraints"][0]["value"] = {
        "source": "output", "step_id": "step1", "name": "title"}
    monkeypatch.setattr(target_resolution, "load_target_recipe", lambda *_: changed)
    binding = {"action": {"kind": "click", "goal": "打开详情"}, "run_id": "run-now",
               "inputs": {}, "outputs": {"step1.title": {"run_id": "run-now", "value": "Alpha"}}}
    assert call(current, bindings=binding)["status"] == "matched"
    binding["outputs"]["step1.title"]["run_id"] = "old-run"
    assert (call(current, bindings=binding)["status"], call(current, bindings=binding)["reason"]) == (
        "invalid", "stale_output")
    binding["outputs"]["step1.title"]["run_id"] = "run-now"
    broken = tree(current)
    broken["uia"]["snapshot"]["controls"][-1]["bbox"]["x"] = 290
    assert call(current, bindings=binding, snapshot=broken)["status"] == "invalid"


def test_observer_binds_visible_row_snapshot_to_capture(monkeypatch, tmp_path):
    from app.learning_memory import memory_observation as module
    image = tmp_path / "fresh.png"
    Image.new("RGB", (300, 200), "white").save(image)
    bound = SimpleNamespace(handle=19, process_id=20,
        rect=SimpleNamespace(left=0, top=0, right=300, bottom=200))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    coordinator = SimpleNamespace(_windows=lambda: manager, _runtime_output_root=tmp_path)

    class Reader:
        def __init__(self, **kwargs):
            pass

        def read_identity(self, handle):
            return {"status": "observed", "target_window_handle": handle, "process_id": 20,
                    "process_create_time": 21.0, "executable_path": "C:\\Fixture\\fixture.exe"}

    class UIA:
        def snapshot_window(self, window):
            return {"provider": "windows_uia", "status": "ok", "scan_complete": True,
                    "truncated": False, "provider_tree_valid": True,
                    "window": {"handle": 19, "process_id": 20}, "controls": []}

    monkeypatch.setattr(module, "WindowsNativeIdentityReader", Reader)
    monkeypatch.setattr(module, "WindowsUIAProvider", UIA)
    monkeypatch.setattr(module, "_window_class", lambda handle: None)
    frame, observations = module.capture_memory_observation(coordinator, 19, 20,
        image_path=image, recipe={"scope": {"anchors": []}, "strategies": [RULE]})
    snapshot = observations["uia"]["snapshot"]
    assert snapshot["capture_id"] == frame["capture_id"]
    assert snapshot["window_identity"] == frame["window_identity"]
