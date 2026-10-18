"""图标命中所有者必须绑定原图与当前原生控件，不产生输入权限。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import time

from PIL import Image
import pytest

from app.agent.native_control_hit_context import (
    collect_current_control_hit, make_control_hit_collector, pinned_control_hit_collector,
)
from app.operation.recognition.native_control_hit_binding import validated_hit_control
from tests.test_windows_control_hit_reader import _button
from tests.test_windows_text_field_reader import _Native


def _setup(tmp_path, monkeypatch, kind="Button"):
    from app.agent import windows_control_hit_reader as native

    path = tmp_path / "source.png"
    Image.new("RGB", (160, 100), "white").save(path)
    source = path.read_bytes()
    bound = SimpleNamespace(handle=7, process_id=8,
        rect=SimpleNamespace(left=30, top=50, right=190, bottom=150))
    fact = {"process_create_time": 2.0, "executable_path": "c:/fake.exe"}
    control = {"control_id": "search", "runtime_id": [42, 12], "name": "搜索",
        "control_type": kind, "bbox": {"x": 10, "y": 10, "w": 40, "h": 40},
        "visible": True, "enabled": True, "patterns": ["Invoke"], "ancestor_control_ids": []}
    uia = {"provider": "windows_uia", "status": "ok", "scan_complete": True, "truncated": False,
        "window": {"handle": 7, "process_id": 8, "bbox": {"x": 0, "y": 0, "w": 160, "h": 100}},
        "controls": [control], "control_count": 1}
    wrappers = [_button(kind, "搜索"), _button(kind, "搜索")]
    for wrapper in wrappers:
        wrapper.element_info.runtime_id = (42, 12)
        wrapper.element_info.rectangle = SimpleNamespace(left=40, top=60, right=80, bottom=100)
    state = {"captures": [], "hits": [], "images": [], "capture_hook": None, "wrappers": wrappers,
        "source": source, "native_reads": 0}
    def from_point(x, y):
        wrapper = state["wrappers"][min(len(state["hits"]), len(state["wrappers"]) - 1)]
        state["hits"].append((x, y))
        return wrapper
    monkeypatch.setattr(native, "_desktop_factory", lambda **_: SimpleNamespace(from_point=from_point))
    def capture(**kwargs):
        state["captures"].append(kwargs)
        image = state["images"].pop(0) if state["images"] else Image.new("RGB", (160, 100), "white")
        fresh = tmp_path / f"fresh-{len(state['captures'])}.png"
        image.save(fresh)
        if state["capture_hook"]: state["capture_hook"]()
        return {"image_path": str(fresh), "image_width": 160, "image_height": 100,
            "window_size": {"width": 160, "height": 100}, "roi": None}
    def native_fact(handle):
        state["native_reads"] += 1
        return _Native().read_identity(handle)
    owner = SimpleNamespace(_window_manager=SimpleNamespace(get_bound_window=lambda: bound),
        _native_identity_reader=SimpleNamespace(read_identity=native_fact),
        _read_application_fact=lambda *_: deepcopy(fact), _screenshot_service=SimpleNamespace(capture_window=capture))
    args = dict(image_path=path, image_bytes=source, uia_snapshot=uia, capture_id="capture.control",
        capture_started_ns=time.perf_counter_ns(), captured_at_ns=time.perf_counter_ns(),
        application_fact=fact, target_window_handle=7, target_process_id=8,
        window_rect={"x": 30, "y": 50, "width": 160, "height": 100})
    def call(collector=None, **updates):
        collector = collector or make_control_hit_collector(owner, **args)
        request = dict(image_path=path, uia_snapshot=deepcopy(uia), point={"x": 20, "y": 20})
        request.update(updates)
        with pinned_control_hit_collector(collector):
            return collect_current_control_hit(**request)
    return owner, args, state, call, bound, fact


def test_no_capability_does_not_trust_public_proof():
    assert collect_current_control_hit(image_path="not-used", uia_snapshot={"native_control_hit_v1": True}, point={}) is None


def test_nested_scope_and_exception_restore_previous_capability():
    request = dict(image_path="unused", uia_snapshot={}, point={})
    with pinned_control_hit_collector(lambda **_: "outer"):
        with pytest.raises(RuntimeError):
            with pinned_control_hit_collector(lambda **_: "inner"):
                assert collect_current_control_hit(**request) == "inner"
                raise RuntimeError("stop")
        assert collect_current_control_hit(**request) == "outer"
        with pinned_control_hit_collector(None):
            assert collect_current_control_hit(**request) is None
    assert collect_current_control_hit(**request) is None
    with pytest.raises(ValueError):
        with pinned_control_hit_collector({}): pass


def test_saved_callback_is_revoked_outside_its_exact_scope(tmp_path, monkeypatch):
    owner, args, state, _, _, _ = _setup(tmp_path, monkeypatch)
    callback = make_control_hit_collector(owner, **args)
    request = dict(image_path=args["image_path"], uia_snapshot=args["uia_snapshot"], point={"x": 20, "y": 20})
    with pytest.raises(ValueError, match="outside"):
        callback(**request)
    with pinned_control_hit_collector(callback):
        assert callback(**request)["hit"]["sample_count"] == 2
    with pytest.raises(ValueError, match="outside"):
        callback(**request)
    assert len(state["captures"]) == 2


@pytest.mark.parametrize("kind", ["Button", "Hyperlink"])
def test_real_native_double_hit_through_owner_and_consumer(tmp_path, monkeypatch, kind):
    _, args, state, call, _, _ = _setup(tmp_path, monkeypatch, kind)
    proof = call()
    assert proof["contract_version"] == "current_control_hit_binding_v1"
    assert proof["hit"]["contract_version"] == "native_control_hit_v1"
    assert proof["hit"]["accessible_name"] == "搜索"
    assert proof["hit"]["control_type"] == kind
    assert proof["hit"]["artifact_is_authorization"] is False and proof["hit"]["action_executed"] is False
    assert proof["before_hit_ns"] <= proof["hit"]["observed_at_ns"] <= proof["after_hit_ns"]
    assert state["hits"] == [(50, 70), (50, 70)]
    assert len(state["captures"]) == 2 and state["native_reads"] == 3
    assert all(c["focus_window"] is False and c["save_image"] is True for c in state["captures"])
    assert Path(args["image_path"]).read_bytes() == state["source"]
    pixels = proof["pixels"]
    assert pixels["source_rgb_sha256"] == pixels["before_rgb_sha256"] == pixels["after_rgb_sha256"]
    assert validated_hit_control(proof, args["uia_snapshot"], {"x": 20, "y": 20},
        sha256(args["image_bytes"]).hexdigest()) == args["uia_snapshot"]["controls"][0]


@pytest.mark.parametrize("change", ["source_file", "source_path", "uia"])
def test_changed_source_rejects_without_native_hit(tmp_path, monkeypatch, change):
    owner, args, state, call, _, _ = _setup(tmp_path, monkeypatch)
    callback = make_control_hit_collector(owner, **args)
    updates = {}
    if change == "source_file": Image.new("RGB", (160, 100), "black").save(args["image_path"])
    elif change == "source_path": updates["image_path"] = tmp_path / "other.png"
    else:
        changed = deepcopy(args["uia_snapshot"])
        changed["controls"][0]["name"] = "different"
        updates["uia_snapshot"] = changed
    with pytest.raises(ValueError): call(callback, **updates)
    assert not state["captures"] and not state["hits"]


@pytest.mark.parametrize("when", ["before", "after", "outside"])
def test_target_rgb_must_match_both_captures_not_unrelated_pixels(tmp_path, monkeypatch, when):
    _, _, state, call, _, _ = _setup(tmp_path, monkeypatch)
    changed = Image.new("RGB", (160, 100), "white")
    changed.putpixel((159, 99) if when == "outside" else (20, 20), (1, 2, 3))
    state["images"] = [changed] if when != "after" else [Image.new("RGB", (160, 100), "white"), changed]
    if when == "outside":
        assert call()["pixels"]["before_rgb_sha256"]
    else:
        with pytest.raises(ValueError, match="target pixels changed"): call()
        assert len(state["hits"]) == (0 if when == "before" else 2)


@pytest.mark.parametrize("what", ["runtime", "name", "bbox", "type", "disabled"])
def test_actual_native_identity_cannot_replace_source_identity(tmp_path, monkeypatch, what):
    _, _, state, call, _, _ = _setup(tmp_path, monkeypatch)
    for wrapper in state["wrappers"]:
        if what == "runtime": wrapper.element_info.runtime_id = (42, 13)
        elif what == "name": wrapper.element_info.name = "other"
        elif what == "bbox": wrapper.element_info.rectangle.right += 1
        elif what == "type": wrapper.element_info.control_type = "Edit"
        else: wrapper._enabled = False
    with pytest.raises(ValueError): call()
    assert len(state["hits"]) == (2 if what == "name" else 1)


def test_second_actual_hit_drift_is_rejected_without_retry(tmp_path, monkeypatch):
    _, _, state, call, _, _ = _setup(tmp_path, monkeypatch)
    state["wrappers"][1].element_info.name = "changed between hits"
    with pytest.raises(ValueError): call()
    assert len(state["hits"]) == 2 and len(state["captures"]) == 1


@pytest.mark.parametrize("kind", ["source", "same_fresh"])
def test_capture_paths_cannot_reuse_original_or_previous_proof(tmp_path, monkeypatch, kind):
    owner, args, state, call, _, _ = _setup(tmp_path, monkeypatch)
    original = owner._screenshot_service.capture_window
    first = None
    def capture(**kwargs):
        nonlocal first
        result = original(**kwargs)
        first = first or result["image_path"]
        result["image_path"] = str(args["image_path"]) if kind == "source" else first
        return result
    owner._screenshot_service.capture_window = capture
    with pytest.raises(ValueError, match="reused an evidence path"): call()
    assert len(state["hits"]) == (0 if kind == "source" else 2)


@pytest.mark.parametrize("what", ["window", "process", "rect", "application"])
def test_owner_binding_drift_during_capture_rejects(tmp_path, monkeypatch, what):
    _, _, state, call, bound, fact = _setup(tmp_path, monkeypatch)
    def drift():
        if what == "window": bound.handle = 9
        elif what == "process": bound.process_id = 9
        elif what == "rect": bound.rect.left += 1
        else: fact["process_create_time"] += 1
    state["capture_hook"] = drift
    with pytest.raises(ValueError): call()
    assert len(state["captures"]) == 1 and not state["hits"]


@pytest.mark.parametrize("change", ["incomplete", "truncated", "duplicate", "not_icon", "unnamed"])
def test_unavailable_target_returns_no_proof_without_reading_native(tmp_path, monkeypatch, change):
    _, args, state, call, _, _ = _setup(tmp_path, monkeypatch)
    uia = args["uia_snapshot"]
    if change == "incomplete": uia["scan_complete"] = False
    elif change == "truncated": uia["truncated"] = True
    elif change == "duplicate": uia["controls"].append(deepcopy(uia["controls"][0]))
    elif change == "not_icon": uia["controls"][0]["control_type"] = "Edit"
    else: uia["controls"][0]["name"] = ""
    assert call() is None
    assert not state["hits"] and not state["captures"]


def test_constructor_pins_source_uia_without_mutating_originals(tmp_path, monkeypatch):
    owner, args, _, call, _, _ = _setup(tmp_path, monkeypatch)
    original = deepcopy(args["uia_snapshot"])
    callback = make_control_hit_collector(owner, **args)
    args["uia_snapshot"]["controls"][0]["name"] = "caller changed"
    proof = call(callback, uia_snapshot=original)
    assert proof["hit"]["accessible_name"] == original["controls"][0]["name"] == "搜索"
    assert args["uia_snapshot"]["controls"][0]["name"] == "caller changed"


@pytest.mark.parametrize("what", ["roi", "dimensions"])
def test_capture_metadata_is_validated_before_native_hit(tmp_path, monkeypatch, what):
    owner, _, state, call, _, _ = _setup(tmp_path, monkeypatch)
    original = owner._screenshot_service.capture_window
    def capture(**kwargs):
        result = original(**kwargs)
        if what == "roi": result["roi"] = {"x": 0, "y": 0, "w": 160, "h": 100}
        else: result["image_width"] = 159
        return result
    owner._screenshot_service.capture_window = capture
    with pytest.raises(ValueError): call()
    assert len(state["captures"]) == 1 and not state["hits"]
