"""字段命中能力必须绑定本次截图，并且永不派发输入。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import time

from PIL import Image
import pytest

from app.agent.native_field_hit_context import (
    collect_current_field_hit, make_field_hit_collector, pinned_field_hit_collector,
)


def _setup(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (160, 100), "white").save(source)
    rect = SimpleNamespace(left=30, top=50, right=190, bottom=150)
    bound = SimpleNamespace(handle=7, process_id=8, rect=rect)
    fact = {"executable_path": "c:/browser.exe", "process_create_time": 2.0}
    field = {"control_id": "search-field", "control_type": "ComboBox", "name": "\ufffc",
        "runtime_id": [42, 12], "bbox": {"x": 10, "y": 10, "w": 120, "h": 40},
        "visible": True, "enabled": True, "patterns": ["Value", "Text"], "ancestor_control_ids": []}
    uia = {"provider": "windows_uia", "status": "ok", "scan_complete": True, "truncated": False,
        "window": {"handle": 7, "process_id": 8, "bbox": {"x": 0, "y": 0, "w": 160, "h": 100}},
        "controls": [field], "control_count": 1}
    state = {"captures": [], "hits": [], "images": [], "hit_change": None, "capture_hook": None}
    def capture(**kwargs):
        state["captures"].append(kwargs)
        image = Image.new("RGB", (160, 100), "white")
        if state["images"]:
            image = state["images"].pop(0)
        path = tmp_path / f"fresh-{len(state['captures'])}.png"
        image.save(path)
        if state["capture_hook"]:
            state["capture_hook"]()
        return {"image_path": str(path), "image_width": 160, "image_height": 100,
            "window_size": {"width": 160, "height": 100}, "roi": None}
    def observe(**kwargs):
        state["hits"].append(kwargs)
        hit = {"contract_version": "windows_field_hit_observation_v1", "provider": "windows_uia.from_point",
            "capture_id": kwargs["capture_id"], "target_field_id": kwargs["target_field_id"],
            "target": {"window_handle": 7, "process_id": 8, "process_create_time": 2.0,
                "window_rect": [30, 50, 160, 100]}, "runtime_id": [42, 12], "control_type": "ComboBox",
            "bbox": deepcopy(field["bbox"]), "point": {"x": 60, "y": 30},
            "observed_at_ns": time.perf_counter_ns(), "sample_count": 2,
            "artifact_is_authorization": False, "action_executed": False}
        if state["hit_change"]:
            state["hit_change"](hit)
        return hit
    owner = SimpleNamespace(_window_manager=SimpleNamespace(get_bound_window=lambda: bound),
        _read_application_fact=lambda *_: deepcopy(fact), _screenshot_service=SimpleNamespace(capture_window=capture),
        _text_field_reader=SimpleNamespace(observe_field_hit=observe))
    arguments = dict(image_path=source, image_bytes=source.read_bytes(), uia_snapshot=uia,
        capture_id="fresh.test", capture_started_ns=time.perf_counter_ns(),
        captured_at_ns=time.perf_counter_ns(), application_fact=fact,
        target_window_handle=7, target_process_id=8, window_rect={"x": 30, "y": 50, "width": 160, "height": 100})
    def call(collector=None, **changes):
        callback = collector or make_field_hit_collector(owner, **arguments)
        request = dict(image_path=source, uia_snapshot=deepcopy(uia), point={"x": 60, "y": 30})
        request.update(changes)
        with pinned_field_hit_collector(callback):
            return callback(**request)
    return owner, arguments, state, call, bound, fact


def test_no_capability_ignores_untrusted_request_proof():
    assert collect_current_field_hit(image_path="unused", uia_snapshot={"current_field_hit_binding_v1": True},
        point={"x": 1, "y": 2}) is None


def test_context_is_nested_and_reset_after_exception():
    arguments = dict(image_path="x", uia_snapshot={}, point={})
    with pinned_field_hit_collector(lambda **_: "outer"):
        assert collect_current_field_hit(**arguments) == "outer"
        with pytest.raises(RuntimeError):
            with pinned_field_hit_collector(lambda **_: "inner"):
                assert collect_current_field_hit(**arguments) == "inner"
                raise RuntimeError("test")
        assert collect_current_field_hit(**arguments) == "outer"
        with pinned_field_hit_collector(None):
            assert collect_current_field_hit(**arguments) is None
    assert collect_current_field_hit(**arguments) is None
    with pytest.raises(ValueError):
        with pinned_field_hit_collector({"proof": True}):
            pass


def test_collector_is_lazy_and_unusable_after_its_scope(tmp_path):
    owner, args, state, _, _, _ = _setup(tmp_path)
    args["uia_snapshot"] = {}
    collector = make_field_hit_collector(owner, **args)
    assert not state["captures"]
    request = dict(image_path=args["image_path"], uia_snapshot={}, point={"x": 60, "y": 30})
    with pytest.raises(ValueError, match="outside"):
        collector(**request)
    with pinned_field_hit_collector(collector):
        with pytest.raises(ValueError, match="UIA snapshot"):
            collect_current_field_hit(**request)
    with pytest.raises(ValueError, match="outside"):
        collector(**request)


def test_owned_hit_has_exact_source_and_two_passive_captures(tmp_path):
    owner, args, state, call, _, _ = _setup(tmp_path)
    result = call()
    assert result["contract_version"] == "current_field_hit_binding_v1"
    assert result["screenshot_sha256"] == sha256(args["image_bytes"]).hexdigest()
    pixels = result["pixels"]
    expected = sha256(Image.new("RGB", (120, 40), "white").tobytes()).hexdigest()
    assert pixels["source_rgb_sha256"] == pixels["before_rgb_sha256"] == pixels["after_rgb_sha256"] == expected
    assert args["captured_at_ns"] <= result["before_hit_ns"] <= result["hit"]["observed_at_ns"] <= result["after_hit_ns"]
    assert len(state["captures"]) == 2 and len(state["hits"]) == 1
    assert all(c["focus_window"] is False and c["save_image"] is True for c in state["captures"])
    assert Path(args["image_path"]).read_bytes() == args["image_bytes"]
    assert state["hits"][0]["expected_runtime_id"] == (42, 12)


def test_produced_proof_passes_common_consumer_with_raw_uia_type(tmp_path):
    from app.operation.recognition.native_field_hit_binding import validated_hit_field

    _, args, _, call, _, _ = _setup(tmp_path)
    proof = call()
    assert proof["hit"]["control_type"] == "ComboBox"
    assert args["uia_snapshot"]["controls"][0]["control_type"] == "ComboBox"
    assert validated_hit_field(proof, args["uia_snapshot"], {"x": 60, "y": 30},
        sha256(args["image_bytes"]).hexdigest()) == args["uia_snapshot"]["controls"][0]


@pytest.mark.parametrize("kind", ["ComboBox", "Edit"])
@pytest.mark.parametrize("phase", ["none", "before", "after"])
def test_real_native_reader_through_collector_and_consumer(tmp_path, monkeypatch, kind, phase):
    from app.agent.windows_text_field_reader import WindowsTextFieldReader
    from app.operation.recognition.native_field_hit_binding import validated_hit_field
    from tests.test_windows_text_field_reader import _Desktop, _Native, _Wrapper

    owner, args, state, call, _, _ = _setup(tmp_path)
    clock = _fake_phase_time(monkeypatch)
    if phase == "before": state["images"] = [_caret_frame()]
    elif phase == "after": state["images"] = [Image.new("RGB", (160, 100), "white"), _caret_frame()]
    field = args["uia_snapshot"]["controls"][0]
    field["control_type"] = kind
    field["patterns"] = ["Text"] if kind == "Document" else ["Value", "Text"]
    wrapper = _Wrapper("PRIVATE_UNREAD_FIELD", control_type=kind, value_pattern=kind != "Document")
    wrapper.element_info.runtime_id = (42, 12)
    wrapper.element_info.rectangle = SimpleNamespace(left=40, top=60, right=160, bottom=100)
    desktop = _Desktop(wrapper)
    owner._text_field_reader = WindowsTextFieldReader(window_manager=owner._window_manager,
        native_identity_reader=_Native(), desktop_factory=lambda **_: desktop)
    owner._text_field_reader._read_text = lambda *_: pytest.fail("native hit must not read value")
    proof = call()
    assert proof["hit"]["control_type"] == kind
    assert proof["hit"]["runtime_id"] == [42, 12]
    assert desktop.calls == [(90, 80), (90, 80)]
    assert len(state["captures"]) == (2 if phase == "none" else 3) and state["hits"] == []
    assert len(clock["waits"]) == (0 if phase == "none" else 1)
    assert validated_hit_field(proof, args["uia_snapshot"], {"x": 60, "y": 30},
        sha256(args["image_bytes"]).hexdigest()) == field


@pytest.mark.parametrize("which", ["before", "after", "outside"])
def test_pixel_comparison_is_full_field_not_unrelated_page(tmp_path, which):
    _, _, state, call, _, _ = _setup(tmp_path)
    changed = Image.new("RGB", (160, 100), "white")
    changed.putpixel((159, 99) if which == "outside" else (12, 12), (1, 2, 3))
    state["images"] = [Image.new("RGB", (160, 100), "white"), changed] if which == "after" else [changed]
    if which == "outside":
        assert call()["pixels"]["source_rgb_sha256"]
    else:
        with pytest.raises(ValueError, match="pixels changed"):
            call()
        assert len(state["hits"]) == (1 if which == "after" else 0)


@pytest.mark.parametrize("change", ["path", "uia", "point", "file", "incomplete", "truncated", "duplicate"])
def test_source_cannot_be_promoted_from_public_or_changed_data(tmp_path, change):
    owner, args, state, call, _, _ = _setup(tmp_path)
    if change in {"incomplete", "truncated"}:
        args["uia_snapshot"]["scan_complete" if change == "incomplete" else "truncated"] = change == "truncated"
        with pytest.raises(ValueError, match="complete"):
            call()
        return
    if change == "duplicate":
        args["uia_snapshot"]["controls"].append(deepcopy(args["uia_snapshot"]["controls"][0]))
    collector = make_field_hit_collector(owner, **args)
    changes = {}
    if change == "path": changes["image_path"] = tmp_path / "other.png"
    elif change == "uia":
        value = deepcopy(args["uia_snapshot"])
        value["controls"][0]["name"] = "different"
        changes["uia_snapshot"] = value
    elif change == "point": changes["point"] = {"x": True, "y": 30}
    elif change == "file": Image.new("RGB", (160, 100), "black").save(args["image_path"])
    with pytest.raises(ValueError):
        call(collector, **changes)
    assert not state["captures"] and not state["hits"]


@pytest.mark.parametrize("when", ["before", "capture", "hit"])
@pytest.mark.parametrize("what", ["window", "process", "rect", "application"])
def test_owner_drift_is_rejected_at_every_boundary(tmp_path, when, what):
    owner, args, state, call, bound, fact = _setup(tmp_path)
    collector = make_field_hit_collector(owner, **args)
    def drift(*_):
        if what == "window": bound.handle = 9
        elif what == "process": bound.process_id = 9
        elif what == "rect": bound.rect.left += 1
        else: fact["process_create_time"] += 1
    if when == "before": drift()
    elif when == "capture": state["capture_hook"] = drift
    else: state["hit_change"] = drift
    with pytest.raises(ValueError):
        call(collector)


@pytest.mark.parametrize("key,value", [("runtime_id", [42, 13]), ("control_type", "group"),
    ("bbox", {"x": 0, "y": 0, "w": 160, "h": 100}), ("point", {"x": 61, "y": 30}),
    ("observed_at_ns", 1), ("capture_id", "other"), ("target_field_id", "other"),
    ("action_executed", True), ("artifact_is_authorization", True), ("sample_count", 1)])
def test_provider_cannot_promote_a_different_target(tmp_path, key, value):
    _, _, state, call, _, _ = _setup(tmp_path)
    state["hit_change"] = lambda hit: hit.update({key: value})
    with pytest.raises(ValueError, match="native result differs"):
        call()
    assert len(state["captures"]) == 1


def test_native_failure_is_visible_without_recapture_or_retry(tmp_path):
    _, _, state, call, _, _ = _setup(tmp_path)
    def fail(_):
        raise ValueError("native_identity_mismatch")
    state["hit_change"] = fail
    with pytest.raises(ValueError, match="native_identity_mismatch"):
        call()
    assert len(state["captures"]) == len(state["hits"]) == 1


@pytest.mark.parametrize("change", ["wrong_size", "roi", "source_path", "reused_path"])
def test_passive_capture_must_be_new_and_validated(tmp_path, change):
    owner, args, state, call, _, _ = _setup(tmp_path)
    original = owner._screenshot_service.capture_window
    first = None
    def capture(**kwargs):
        nonlocal first
        result = original(**kwargs)
        if change == "wrong_size": result["image_width"] = 159
        elif change == "roi": result["roi"] = {"x": 0, "y": 0, "w": 160, "h": 100}
        elif change == "source_path": result["image_path"] = str(args["image_path"])
        elif change == "reused_path":
            first = first or result["image_path"]
            result["image_path"] = first
        return result
    owner._screenshot_service.capture_window = capture
    with pytest.raises(ValueError):
        call()
    assert len(state["hits"]) == (1 if change == "reused_path" else 0)


def test_constructor_pins_original_uia_without_mutating_callers(tmp_path):
    owner, args, _, call, _, _ = _setup(tmp_path)
    original = deepcopy(args["uia_snapshot"])
    collector = make_field_hit_collector(owner, **args)
    args["uia_snapshot"]["controls"][0]["name"] = "changed caller"
    proof = call(collector, uia_snapshot=original)
    assert proof["hit"]["target_field_id"] == "search-field"
    assert original["controls"][0]["name"] == "\ufffc"


def _fake_phase_time(monkeypatch):
    from app.agent import native_field_hit_context as module

    state = {"now": 0.0, "waits": []}
    monkeypatch.setattr(module, "_phase_clock", lambda: state["now"])
    def wait(seconds):
        state["waits"].append(seconds)
        state["now"] += seconds
    monkeypatch.setattr(module, "_phase_wait", wait)
    return state


def _caret_frame(width=1, height=18, x=10, y=13):
    image = Image.new("RGB", (160, 100), "white")
    for px in range(x, x + width):
        for py in range(y, y + height):
            image.putpixel((px, py), (0, 0, 0))
    return image


@pytest.mark.parametrize("phase", ["before", "after"])
def test_transient_caret_retries_only_capture_until_exact(tmp_path, monkeypatch, caplog, phase):
    _, args, state, call, _, _ = _setup(tmp_path)
    clock = _fake_phase_time(monkeypatch)
    state["images"] = [_caret_frame(), _caret_frame(width=2)]
    if phase == "after": state["images"].insert(0, Image.new("RGB", (160, 100), "white"))
    with caplog.at_level("INFO", logger="app.agent.native_field_hit_context"):
        proof = call()
    assert len(state["captures"]) == 4 and len(state["hits"]) == 1
    assert clock["waits"] == [.150, .150]
    pixels = proof["pixels"]
    assert pixels["source_rgb_sha256"] == pixels["before_rgb_sha256"] == pixels["after_rgb_sha256"]
    assert Path(args["image_path"]).read_bytes() == args["image_bytes"]
    assert f"phase={phase} captures=3 elapsed_ms=300.000 outcome=exact" in caplog.text
    assert set(proof) == {"contract_version", "capture_id", "screenshot_sha256", "uia_snapshot_sha256",
        "capture_started_ns", "captured_at_ns", "before_hit_ns", "after_hit_ns", "target", "hit", "pixels"}


@pytest.mark.parametrize("phase", ["before", "after"])
def test_persistent_caret_is_bounded_and_never_accepted(tmp_path, monkeypatch, phase):
    _, _, state, call, _, _ = _setup(tmp_path)
    clock = _fake_phase_time(monkeypatch)
    state["images"] = [_caret_frame() for _ in range(4)]
    if phase == "after": state["images"].insert(0, Image.new("RGB", (160, 100), "white"))
    with pytest.raises(ValueError, match="caret phase did not return to exact source"):
        call()
    assert len(state["captures"]) == (4 if phase == "before" else 5)
    assert len(state["hits"]) == (0 if phase == "before" else 1)
    assert len(clock["waits"]) == 3 and sum(clock["waits"]) <= .650


@pytest.mark.parametrize("second_exact", [False, True])
def test_capture_cost_counts_toward_phase_retry_budget(tmp_path, monkeypatch, second_exact):
    _, _, state, call, _, _ = _setup(tmp_path)
    clock = _fake_phase_time(monkeypatch)
    state["images"] = [_caret_frame(), Image.new("RGB", (160, 100), "white") if second_exact else _caret_frame()]
    state["capture_hook"] = lambda: clock.update(now=clock["now"] + .800)
    with pytest.raises(ValueError, match="caret phase did not return to exact source"):
        call()
    assert len(state["captures"]) == 2 and not state["hits"]
    assert clock["waits"] == [.150]


def test_normal_capture_cost_and_caret_half_cycle_fit_one_second(tmp_path, monkeypatch):
    _, _, state, call, _, _ = _setup(tmp_path)
    clock = _fake_phase_time(monkeypatch)
    state['images'] = [_caret_frame(), Image.new('RGB', (160, 100), 'white')]
    state['capture_hook'] = lambda: clock.update(now=clock['now'] + .300)
    pixels = call()['pixels']
    assert pixels['source_rgb_sha256'] == pixels['before_rgb_sha256'] == pixels['after_rgb_sha256']
    assert len(state['captures']) == 3 and len(state['hits']) == 1
    assert clock['waits'] == [.150]


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_three_realistic_capture_costs_allow_exact_caret_phase(tmp_path, monkeypatch, phase):
    _, _, state, call, _, _ = _setup(tmp_path)
    clock = _fake_phase_time(monkeypatch)
    state['images'] = [_caret_frame(), _caret_frame(), Image.new('RGB', (160, 100), 'white')]
    if phase == 'after':
        state['images'].insert(0, Image.new('RGB', (160, 100), 'white'))
    state['capture_hook'] = lambda: clock.update(now=clock['now'] + .240)
    pixels = call()['pixels']
    assert pixels['source_rgb_sha256'] == pixels['before_rgb_sha256'] == pixels['after_rgb_sha256']
    assert len(state['captures']) == 4 and len(state['hits']) == 1
    assert clock['waits'] == [.150, .150]


@pytest.mark.parametrize("kind", ["wide", "short", "tall", "scattered", "text", "border"])
def test_non_caret_differences_reject_without_waiting(tmp_path, monkeypatch, kind):
    _, _, state, call, _, _ = _setup(tmp_path)
    clock = _fake_phase_time(monkeypatch)
    image = _caret_frame(width=3) if kind == "wide" else _caret_frame(height=5) if kind == "short" else _caret_frame(height=25) if kind == "tall" else _caret_frame()
    if kind == "scattered": image.putpixel((10, 20), (255, 255, 255))
    elif kind == "text": image.putpixel((18, 20), (0, 0, 0))
    elif kind == "border": image = _caret_frame(height=40, y=10)
    state["images"] = [image]
    with pytest.raises(ValueError, match="pixels changed"):
        call()
    assert len(state["captures"]) == 1 and not state["hits"] and not clock["waits"]


def test_reported_18_pixel_caret_shape_is_retryable_but_not_equal():
    from app.agent.native_field_hit_context import _caret_phase_difference

    source = Image.new("RGB", (246, 24), "white")
    current = source.copy()
    for y in range(3, 21): current.putpixel((0, y), (0, 0, 0))
    assert _caret_phase_difference(source, current) is True
    assert sha256(source.tobytes()).digest() != sha256(current.tobytes()).digest()
