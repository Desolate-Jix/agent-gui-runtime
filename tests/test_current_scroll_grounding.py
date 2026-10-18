"""滚动是当前容器的独立语义，不把按钮命中或历史坐标当作滚动证据。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.agent.fresh_scroll_region import current_scroll_container
from app.agent.live_runtime_composition import _parse_recognition, _run_existing_read_only_recognition
from app.operation.recognition.decision import decide_pre_click


def _control(ident, bbox, *, kind="Group", ancestors=(), axes=None):
    return {"control_id": ident, "runtime_id": [42, len(ident)], "name": ident,
        "control_type": kind, "bbox": bbox, "visible": True, "enabled": True,
        "patterns": ["Scroll"], "ancestor_control_ids": list(ancestors),
        "scroll_axes": axes if axes is not None else {"current_vertical": True, "current_horizontal": False}}


def _controls():
    outer = {"x": 0, "y": 0, "w": 160, "h": 100}
    root = _control("root", outer, kind="Window")
    root["patterns"] = []
    document = _control("document", outer, kind="Document", ancestors=("root",))
    panel = _control("panel", {"x": 10, "y": 10, "w": 130, "h": 80}, ancestors=("document", "root"))
    return [root, document, panel]


def test_nested_real_ancestor_resolves_but_parallel_overlay_does_not():
    controls = _controls()
    assert current_scroll_container(controls, {"x": 50, "y": 50}, axis="vertical")["control_id"] == "panel"
    overlay = _control("overlay", controls[1]["bbox"], ancestors=("root",))
    with pytest.raises(ValueError, match="ambiguous"):
        current_scroll_container([*controls, overlay], {"x": 50, "y": 50}, axis="vertical")
    overlay["scroll_axes"]["current_vertical"] = False
    assert current_scroll_container([*controls, overlay], {"x": 50, "y": 50}, axis="vertical")["control_id"] == "panel"


@pytest.mark.parametrize("change", ["button_scroll", "axis_unknown", "axis_false", "disabled", "duplicate", "broken_ancestor"])
def test_scroll_rejects_unknown_axis_controls_and_unproven_ancestry(change):
    controls = _controls()
    if change == "button_scroll": controls[2]["control_type"] = "Button"
    elif change == "axis_unknown": controls[2]["scroll_axes"]["current_vertical"] = None
    elif change == "axis_false": controls[2]["scroll_axes"]["current_vertical"] = False
    elif change == "disabled": controls[2]["enabled"] = None
    elif change == "duplicate": controls.append(deepcopy(controls[2]))
    else: controls[2]["ancestor_control_ids"] = ["document", "missing"]
    with pytest.raises(ValueError):
        current_scroll_container(controls, {"x": 50, "y": 50}, axis="vertical", target_container_id="panel")


def _public_observe(tmp_path, monkeypatch, *, alter=None):
    from app.agent.fresh_learning_observation import FreshLearningObservationOwner
    from tests.test_native_control_hit_context import _setup
    dependencies, args, state, _, _, _ = _setup(tmp_path, monkeypatch)
    uia = deepcopy(args["uia_snapshot"])
    uia["controls"] = _controls()
    uia["controls"][1]["scroll_axes"]["current_vertical"] = False
    button = _control("button", {"x": 65, "y": 40, "w": 20, "h": 20}, kind="Button", ancestors=("panel", "document", "root"))
    button["patterns"] = ["Invoke"]
    uia["controls"].append(button)
    uia["control_count"] = len(uia["controls"])
    if alter: alter(uia)
    owner = FreshLearningObservationOwner(project_root=tmp_path,
        application_identity={"kind": "native", "executable_path": "c:\\fake.exe"},
        screenshot_service=dependencies._screenshot_service, window_manager=dependencies._window_manager,
        native_identity_reader=dependencies._native_identity_reader,
        uia_provider=SimpleNamespace(snapshot_window=lambda _: deepcopy(uia)),
        recognition_runner=_run_existing_read_only_recognition)
    parameters = {"contract_version": "reviewed_scroll_parameters_v1", "target_container_id": "panel",
        "axis": "vertical", "direction": "down", "wheel_clicks": 3, "unit": "wheel_detent"}
    bundle = owner.observe_for_action(target_window_handle=7, target_process_id=8,
        goal="Read more details", semantic_action="scroll_region", scroll_parameters=parameters)
    return bundle, state


def test_public_owner_scroll_uses_current_empty_region_without_model_or_ocr(tmp_path, monkeypatch):
    bundle, state = _public_observe(tmp_path, monkeypatch)
    result = bundle.recognition_result()
    candidates, local = _parse_recognition(result)
    candidate, grounding = candidates.candidates[0], local.results[0]
    assert candidate.role == "region" and candidate.element.interaction_type == "scroll"
    assert candidate.text == candidate.element.text == "" and candidate.score_breakdown.text_similarity == 0
    assert grounding.matched_text is None and grounding.matched_text_bbox is None
    assert candidate.element.bbox.to_dict() == _controls()[2]["bbox"]
    assert grounding.refined_click_point != {"x": 75, "y": 50}
    decision = decide_pre_click(goal=result["goal"], candidates=candidates, grounding=local,
        uia_snapshot=bundle.uia_snapshot(), screenshot_sha256=sha256(bundle.packet.png_bytes).hexdigest())
    assert decision.allowed, decision.to_dict()
    assert state["hits"] == [] and len(state["captures"]) == 1


@pytest.mark.parametrize("change", ["incomplete", "missing_id", "unknown_axis", "fully_covered"])
def test_public_scroll_refuses_incomplete_or_unavailable_target(tmp_path, monkeypatch, change):
    def alter(uia):
        if change == "incomplete": uia["scan_complete"] = False
        elif change == "missing_id": uia["controls"][2]["control_id"] = "other"
        elif change == "unknown_axis": uia["controls"][2]["scroll_axes"]["current_vertical"] = None
        else: uia["controls"][-1]["bbox"] = deepcopy(uia["controls"][2]["bbox"])
    with pytest.raises(ValueError):
        _public_observe(tmp_path, monkeypatch, alter=alter)


@pytest.mark.parametrize("change", ["hash", "point", "axes", "type", "viewport", "invented_text"])
def test_scroll_gate_recomputes_binding_and_rejects_tampering(tmp_path, monkeypatch, change):
    bundle, _ = _public_observe(tmp_path, monkeypatch)
    result = bundle.recognition_result()
    candidates, local = _parse_recognition(result)
    uia = bundle.uia_snapshot()
    digest = sha256(bundle.packet.png_bytes).hexdigest()
    if change == "hash": digest = "a" * 64
    elif change == "point": local.results[0].refined_click_point = {"x": 75, "y": 50}
    elif change == "axes": uia["controls"][2]["scroll_axes"]["current_vertical"] = False
    elif change == "type": candidates.candidates[0].element.interaction_type = "click"
    elif change == "viewport": candidates.candidates[0].element.evidence["current_scroll_container_binding"]["viewport_size"] = []
    else: candidates.candidates[0].text = "invented"
    assert not decide_pre_click(goal=result["goal"], candidates=candidates, grounding=local,
        uia_snapshot=uia, screenshot_sha256=digest).allowed


@pytest.mark.parametrize("vertical,horizontal,expected", [(0, 0, (False, False)), (1, 0, (True, False)),
    (False, True, (False, True)), (None, 0, (None, False)), ("0", 2, (None, None))])
def test_real_uia_provider_records_axis_values_not_pattern_existence(vertical, horizontal, expected):
    from app.operation.screen_reading.uia_provider import WindowsUIAProvider
    rect = SimpleNamespace(left=0, top=0, right=160, bottom=100)
    wrapper = SimpleNamespace(rectangle=lambda: rect,
        element_info=SimpleNamespace(name="panel", control_type="Group", runtime_id=[42, 9]),
        window_text=lambda: "panel", is_visible=lambda: True, is_enabled=lambda: True,
        iface_scroll=SimpleNamespace(CurrentVerticallyScrollable=vertical, CurrentHorizontallyScrollable=horizontal))
    result = WindowsUIAProvider()._control_from_wrapper(wrapper, bound=SimpleNamespace(rect=rect), index=0).to_dict()
    assert result["patterns"] == ["Scroll"]
    assert result["scroll_axes"] == dict(zip(("current_vertical", "current_horizontal"), expected))


def test_axis_property_failure_is_unknown_not_false():
    from app.operation.screen_reading.uia_provider import _scroll_axes
    class BrokenScroll:
        @property
        def CurrentVerticallyScrollable(self):
            raise RuntimeError("native property unavailable")
        CurrentHorizontallyScrollable = 0
    assert _scroll_axes(SimpleNamespace(iface_scroll=BrokenScroll())) == {
        "current_vertical": None, "current_horizontal": False}


def test_scroll_typed_grounding_never_authorizes_click_semantics(tmp_path, monkeypatch):
    from app.gate.fresh_action_risk import classify_fresh_action_risk
    bundle, _ = _public_observe(tmp_path, monkeypatch)
    ranked, local = _parse_recognition(bundle.recognition_result())
    result = classify_fresh_action_risk(proposed_semantic_action="open_detail", goal="Read more details", candidate=ranked.candidates[0],
        local=local.results[0], uia_snapshot=bundle.uia_snapshot(), capture_id=bundle.packet.evidence()["capture"]["capture_id"])
    assert result["hard_blocked"] is True
