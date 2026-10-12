"""追加观察只采集当前窗口；取消、漂移与超时不能产生可采用记录。"""
from copy import deepcopy
from contextlib import contextmanager
from hashlib import sha256
from importlib import import_module, util
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest


def _module():
    name = "app.execution.task_plan_observation_capture"
    assert util.find_spec(name) is not None, "正式只读追加采集适配器尚未实现"
    return import_module(name)


class Owner:
    def __init__(self):
        self.calls = 0
        self.active = False
        self.before = lambda: None
        self.after = lambda: None

    def call(self, operation):
        self.calls += 1
        self.before()
        self.active = True
        try:
            result = operation()
        finally:
            self.active = False
        self.after()
        return result


def _setup(monkeypatch, tmp_path):
    module = _module()
    original_path = tmp_path / "original-after.png"
    Image.new("RGB", (100, 70), "white").save(original_path)
    raw = original_path.read_bytes()
    source = tmp_path / "maintained-current.png"
    source.write_bytes(raw)
    identity = {"handle": 12, "process_id": 34, "process_create_time": 123.0}
    original = {"capture_id": "original-capture", "image_path": str(original_path),
        "sha256": sha256(raw).hexdigest(), "image_size": {"width": 100, "height": 70},
        "window_identity": identity, "window_rect": [10, 20, 110, 90],
        "application": {"executable_name": "fixture.exe", "window_class": "Fixture"}, "role": "after"}
    current = {**deepcopy(original), "capture_id": "new-current-capture", "image_path": str(source)}
    owner = Owner()
    state = SimpleNamespace(module=module, root=tmp_path / "session", owner=owner,
        coordinator=SimpleNamespace(_owner=owner), original=original, current=current,
        identity=deepcopy(identity), raw=raw, source=source, time=0.0, stopped=False, captures=0)

    def capture(coordinator, handle, pid, **kwargs):
        assert owner.active
        assert coordinator is state.coordinator and (handle, pid) == (12, 34)
        assert kwargs == {"recipe": None}
        state.captures += 1
        return deepcopy(state.current), {"uia": {"status": "not_required"}}

    monkeypatch.setattr(module, "capture_memory_observation", capture)
    monkeypatch.setattr(module, "monotonic", lambda: state.time)
    return state


@pytest.fixture
def scene(monkeypatch, tmp_path):
    return _setup(monkeypatch, tmp_path)


def _call(scene, **changes):
    options = dict(session_dir=scene.root, target_identity=scene.identity, original_frame=scene.original,
        observation_id="followup-1", cancelled=lambda: scene.stopped, remaining_seconds=lambda: 12.0)
    options.update(changes)
    return scene.module.capture_followup(scene.coordinator, **options)


def _reject(scene, reason, **changes):
    with pytest.raises(scene.module.FollowupObservationError) as failure:
        _call(scene, **changes)
    assert failure.value.reason_code == "task_plan_observation_" + reason
    assert str(failure.value) == failure.value.reason_code


def test_new_capture_with_unchanged_pixels_is_owned_and_original_is_unchanged(monkeypatch, tmp_path):
    scene = _setup(monkeypatch, tmp_path)
    original = deepcopy(scene.original)
    scene.owner.after = lambda: setattr(scene, "time", 0.125)
    record = _call(scene)
    destination = scene.root / "task-plan-observations" / "followup-1.png"
    assert set(record) == {"observation_id", "frame", "capture_elapsed_ms"}
    assert record["observation_id"] == "followup-1"
    assert record["capture_elapsed_ms"] == 125
    assert Path(record["frame"]["image_path"]) == destination.resolve()
    assert record["frame"]["capture_id"] == "new-current-capture"
    assert record["frame"]["sha256"] == original["sha256"]
    assert record["frame"]["window_identity"] == {"handle": 12, "process_id": 34, "process_create_time": 123.0}
    assert set(record["frame"]) == {"capture_id", "sha256", "image_path", "window_identity", "role"}
    assert record["frame"]["role"] == "observation"
    assert destination.read_bytes() == scene.raw
    scene.source.write_bytes(b"later unrelated source contents")
    assert destination.read_bytes() == scene.raw
    assert scene.original == original
    assert Path(original["image_path"]).read_bytes() == scene.raw


def test_cancel_before_owner_dispatch_does_not_start_capture(scene):
    scene.stopped = True
    _reject(scene, "cancelled")
    assert scene.owner.calls == scene.captures == 0
    assert not scene.root.exists()


@pytest.mark.parametrize("late", ["cancel", "timeout"])
def test_owner_queue_delay_rechecks_before_starting_capture(scene, late):
    def delayed():
        if late == "cancel":
            scene.stopped = True
        else:
            scene.time = 12.0
    scene.owner.before = delayed
    _reject(scene, "cancelled" if late == "cancel" else "timeout")
    assert scene.captures == 0
    assert not scene.root.exists()


@pytest.mark.parametrize("late", ["cancel", "timeout"])
def test_late_capture_cannot_return_a_valid_record(scene, monkeypatch, late):
    original_capture = scene.module.capture_memory_observation
    def slow_capture(*args, **kwargs):
        result = original_capture(*args, **kwargs)
        if late == "cancel":
            scene.stopped = True
        else:
            scene.time = 12.001
        return result
    monkeypatch.setattr(scene.module, "capture_memory_observation", slow_capture)
    _reject(scene, "cancelled" if late == "cancel" else "timeout")
    assert scene.captures == 1
    assert not (scene.root / "task-plan-observations" / "followup-1.png").exists()


def test_owner_return_delay_is_also_rejected(scene):
    scene.owner.after = lambda: setattr(scene, "time", 12.001)
    _reject(scene, "timeout")
    assert scene.captures == 1
    assert not scene.root.exists()


@pytest.mark.parametrize("budget", [0, -1, True, float("nan"), float("inf"), "12"])
def test_invalid_or_exhausted_budget_never_dispatches(scene, budget):
    _reject(scene, "timeout" if type(budget) in (int, float) and budget <= 0 else "budget_invalid",
        remaining_seconds=lambda: budget)
    assert scene.owner.calls == scene.captures == 0


def test_external_budget_exhaustion_stops_before_capture(scene):
    budget = {"value": 12.0}
    scene.owner.before = lambda: budget.update(value=0.0)
    _reject(scene, "timeout", remaining_seconds=lambda: budget["value"])
    assert scene.captures == 0


@pytest.mark.parametrize("identifier", ["../outside", "a/b", "a\\b", "C:bad", ".", "", "CON", "nul",
    "COM1", "Lpt9", "ending.", "bad\n", "\u89c2\u5bdf", "a" * 129])
def test_unsafe_observation_id_is_rejected_before_capture(scene, identifier):
    _reject(scene, "id_invalid", observation_id=identifier)
    assert scene.owner.calls == scene.captures == 0


def test_duplicate_observation_id_does_not_capture_or_overwrite(scene):
    destination = scene.root / "task-plan-observations" / "followup-1.png"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"original immutable observation")
    _reject(scene, "id_duplicate")
    assert destination.read_bytes() == b"original immutable observation"
    assert scene.owner.calls == scene.captures == 0


@pytest.mark.parametrize("key,value", [("handle", 13), ("process_id", 35), ("process_create_time", 124.0)])
def test_current_window_birth_drift_is_rejected(scene, key, value):
    scene.current["window_identity"][key] = value
    _reject(scene, "identity_changed")
    assert not scene.root.exists()


@pytest.mark.parametrize("identity", [{"handle": 12, "process_id": 34},
    {"handle": True, "process_id": 34, "process_create_time": 123.0},
    {"handle": 12, "process_id": 34, "process_create_time": float("nan")}])
def test_incomplete_or_invalid_target_identity_cannot_start_capture(scene, identity):
    _reject(scene, "identity_invalid", target_identity=identity)
    assert scene.owner.calls == scene.captures == 0


def test_original_window_identity_must_match_frozen_target(scene):
    scene.original["window_identity"]["process_create_time"] = 124.0
    _reject(scene, "identity_changed")
    assert scene.owner.calls == scene.captures == 0


def test_window_translation_drift_is_rejected_even_with_same_size(scene):
    scene.current["window_rect"] = [11, 20, 111, 90]
    _reject(scene, "geometry_changed")
    assert not scene.root.exists()


@pytest.mark.parametrize("field,value", [("window_rect", [10, 20, 10, 90]),
    ("window_rect", [True, 20, 110, 90]), ("image_size", {"width": True, "height": 70}),
    ("image_size", {"width": 99, "height": 70}), ("window_rect", [10, 20, 110])])
def test_bad_capture_geometry_is_rejected(scene, field, value):
    scene.current[field] = value
    _reject(scene, "frame_invalid")
    assert not scene.root.exists()


def test_new_capture_must_have_a_fresh_id(scene):
    scene.current["capture_id"] = scene.original["capture_id"]
    _reject(scene, "capture_stale")
    assert not scene.root.exists()


@pytest.mark.parametrize("field", ["capture_id", "sha256", "image_path", "image_size", "window_rect", "window_identity"])
def test_missing_capture_metadata_never_produces_record(scene, field):
    del scene.current[field]
    _reject(scene, "frame_invalid")
    assert not scene.root.exists()


def test_capture_bytes_must_match_declared_sha(scene):
    scene.current["sha256"] = "0" * 64
    _reject(scene, "capture_hash_changed")
    assert not scene.root.exists()


def test_original_image_hash_is_verified_before_new_capture(scene):
    Path(scene.original["image_path"]).write_bytes(b"invalid changed original")
    _reject(scene, "original_evidence_invalid")
    assert scene.owner.calls == scene.captures == 0


def test_new_capture_cannot_relabel_the_original_after_path(scene):
    scene.current["image_path"] = scene.original["image_path"]
    _reject(scene, "capture_reused")
    assert not scene.root.exists()
    assert Path(scene.original["image_path"]).read_bytes() == scene.raw


def test_original_after_changed_during_capture_is_rejected(scene):
    scene.owner.after = lambda: Path(scene.original["image_path"]).write_bytes(b"changed outside helper")
    _reject(scene, "original_evidence_invalid")
    assert not scene.root.exists()


def test_cancel_during_persistence_never_returns_or_overwrites_a_record(scene, monkeypatch):
    original_open = Path.open
    @contextmanager
    def cancelled_write(path, *args, **kwargs):
        with original_open(path, *args, **kwargs) as output:
            yield output
        if args and args[0] == "xb":
            scene.stopped = True
    monkeypatch.setattr(Path, "open", cancelled_write)
    _reject(scene, "cancelled")
    destination = scene.root / "task-plan-observations" / "followup-1.png"
    assert destination.read_bytes() == scene.raw
    scene.stopped = False
    _reject(scene, "id_duplicate")
    assert scene.captures == 1
    assert Path(scene.original["image_path"]).read_bytes() == scene.raw


def test_png_signature_without_valid_png_is_rejected(scene):
    raw = b"\x89PNG\r\n\x1a\nnot a png"
    scene.source.write_bytes(raw)
    scene.current["sha256"] = sha256(raw).hexdigest()
    _reject(scene, "capture_png_invalid")
    assert not scene.root.exists()


def test_png_actual_dimensions_must_match_frame_metadata(scene):
    Image.new("RGB", (99, 70), "white").save(scene.source)
    scene.current["sha256"] = sha256(scene.source.read_bytes()).hexdigest()
    _reject(scene, "capture_size_changed")
    assert not scene.root.exists()


def test_capture_failure_is_named_without_echoing_backend_payload(scene, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("private backend payload must not be exposed")
    monkeypatch.setattr(scene.module, "capture_memory_observation", failed)
    with pytest.raises(scene.module.FollowupObservationError) as failure:
        _call(scene)
    assert failure.value.reason_code == "task_plan_observation_capture_failed"
    assert failure.value.error_type == "RuntimeError"
    assert "private" not in str(failure.value)
    assert not scene.root.exists()


def test_destination_race_cannot_overwrite_previous_observation(scene):
    destination = scene.root / "task-plan-observations" / "followup-1.png"
    def raced():
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"another immutable observation")
    scene.owner.after = raced
    _reject(scene, "id_duplicate")
    assert destination.read_bytes() == b"another immutable observation"


def test_redirected_observation_directory_is_rejected_before_capture(scene, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    scene.root.mkdir()
    link = scene.root / "task-plan-observations"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境没有创建符号链接权限")
    _reject(scene, "path_invalid")
    assert scene.owner.calls == scene.captures == 0
    assert list(outside.iterdir()) == []


def test_resolved_destination_outside_session_is_rejected_without_symlink_privilege(scene, monkeypatch, tmp_path):
    resolve = Path.resolve
    expected = scene.root / "task-plan-observations" / "followup-1.png"
    def redirected(path, *args, **kwargs):
        if path == expected:
            return tmp_path / "outside" / "followup-1.png"
        return resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", redirected)
    _reject(scene, "path_invalid")
    assert scene.owner.calls == scene.captures == 0
    assert not scene.root.exists()


def test_maintained_capture_route_has_no_focus_input_or_tree_scan(scene, monkeypatch, tmp_path):
    from app.learning_memory import memory_observation
    manager = SimpleNamespace(get_bound_window=lambda: SimpleNamespace(handle=12, process_id=34,
        rect=SimpleNamespace(left=10, top=20, right=110, bottom=90)))
    coordinator = SimpleNamespace(_owner=scene.owner, _windows=lambda: manager,
        _runtime_output_root=tmp_path / "runtime")
    operations = []

    class Reader:
        def __init__(self, **kwargs):
            pass

        def read_identity(self, handle):
            assert scene.owner.active
            return {"status": "observed", "target_window_handle": 12, "process_id": 34,
                "process_create_time": 123.0, "executable_path": "C:\\Fixture\\fixture.exe"}

    class Screenshot:
        def __init__(self, **kwargs):
            pass

        def capture_window(self, **kwargs):
            assert scene.owner.active and kwargs == {"focus_window": False, "purpose": "memory-current-observation"}
            operations.append("read_capture")
            return {"image_path": str(scene.source), "roi": None}

    class ForbiddenTree:
        def __init__(self, **kwargs):
            raise AssertionError("追加观察不得初始化全树扫描")

    monkeypatch.setattr(memory_observation, "WindowsNativeIdentityReader", Reader)
    monkeypatch.setattr(memory_observation, "ScreenshotService", Screenshot)
    monkeypatch.setattr(memory_observation, "WindowsUIAProvider", ForbiddenTree)
    monkeypatch.setattr(memory_observation, "_window_class", lambda handle: "Fixture")
    monkeypatch.setattr(scene.module, "capture_memory_observation", memory_observation.capture_memory_observation)
    record = scene.module.capture_followup(coordinator, session_dir=scene.root, target_identity=scene.identity,
        original_frame=scene.original, observation_id="read-only-round", cancelled=lambda: False,
        remaining_seconds=lambda: 12.0)
    assert operations == ["read_capture"]
    assert record["frame"]["capture_id"] != scene.original["capture_id"]
    assert Path(record["frame"]["image_path"]).read_bytes() == scene.raw
