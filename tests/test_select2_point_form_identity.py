"""当前模型点位只能确认无名表单控件，不能把标题冒充控件。"""

from app.api import vision
from app.operation.page_structure.schemas import PageStructure
from app.operation.recognition.candidate_ranker import rank_candidates
from app.operation.recognition.schemas import CandidateRankRequest
from app.operation.screen_inventory.builder import _action_from_uia
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from modules.ocr.contracts import OCRResult
from PIL import Image


GOAL = "Click the empty multi-select control beneath the Multi-select boxes (pillbox) heading."
POINT = {"x": 1024, "y": 922}
BOX = {"x": 859, "y": 908, "w": 827, "h": 33}


def _control(control_id="uia_225_combobox", bbox=None):
    box = dict(bbox or BOX)
    return dict(control_id=control_id, runtime_id=[42, 1180450, 4, 29, 5, 821],
        name=None, control_type="ComboBox", bbox=box,
        enabled=True, visible=True, patterns=["Value", "Selection", "ExpandCollapse"],
        form_label_binding={"control_id": control_id, "runtime_id": [42, 1180450, 4, 29, 5, 821],
            "label": "attribute.", "source": "visible_label_geometry", "bbox": dict(box)})


def _inventory(controls, *, complete=True):
    actions = [_action_from_uia(control, source_index=index) for index, control in enumerate(controls)]
    reading = {"image_size": {"width": 2560, "height": 1400},
        "screen_inventory": {"available_actions": actions}}
    fast = {"status": "ready", "uia_scan_truncated": False, "uia_scan_complete": complete,
        "screen_reading": {**reading, "source_layers": {"windows_uia": {
            "status": "ok", "scan_complete": complete, "truncated": False, "controls": controls}}},
        "screen_inventory": reading["screen_inventory"]}
    ranked = rank_candidates(CandidateRankRequest(goal=GOAL,
        page_structure=PageStructure(image_size=vision.ImageSize(width=2560, height=1400),
            screen_summary="current screenshot", state_guess=None, elements=[], texts=[]),
        top_k=5, screen_reading=reading))
    return fast, ranked.candidates


def test_unique_point_under_nameless_select2_combobox_wins_over_heading():
    heading_box = {"x": 1733, "y": 231, "w": 262, "h": 23}
    heading = dict(control_id="uia_129_heading", runtime_id=[42, 129],
        name="Multi-select boxes (pillbox)", control_type="ListItem", bbox=heading_box,
        enabled=True, visible=True, patterns=[])
    controls = [heading, _control()]
    fast, ranked = _inventory(controls)
    selected, reason = vision._vista_direct_current_uia_identity(goal=GOAL, target_text=None,
        point=POINT, fast_inventory=fast, candidates=ranked)
    assert reason is None
    assert selected is not None
    assert selected.role == "combobox"
    assert selected.element.bbox.to_dict() == BOX
    assert selected.element.evidence["screen_inventory_action"]["source_id"] == "uia_225_combobox"
    assert selected.element.evidence["current_uia_point_form_role"]["point"] == POINT


def test_point_form_role_never_overrides_explicit_label_or_incomplete_or_ambiguous_scan():
    for goal, controls, complete in (
        ("Click the dropdown labelled Country", [_control()], True),
        ("Click the button beneath the dropdown", [_control()], True),
        (GOAL, [_control()], False),
        (GOAL, [_control(), _control("second")], True),
        (GOAL, [_control(), dict(control_id="overlap-button", runtime_id=[42, 131],
            name="Other", control_type="Button", bbox=dict(BOX),
            enabled=True, visible=True, patterns=["Invoke"])], True),
        (GOAL, [_control(bbox={"x": 1200, "y": 908, "w": 400, "h": 33})], True),
    ):
        fast, ranked = _inventory(controls, complete=complete)
        selected, _ = vision._vista_direct_current_uia_identity(goal=goal, target_text=None,
            point=POINT, fast_inventory=fast, candidates=ranked)
        assert selected is None


def test_select2_point_reconciles_unrelated_toc_conflict_without_click(tmp_path, monkeypatch):
    image = tmp_path / "select2.png"
    Image.new("RGB", (2560, 1400), "white").save(image)
    heading = dict(control_id="uia_129_heading", runtime_id=[42, 129],
        name="Multi-select boxes (pillbox)", control_type="ListItem",
        bbox={"x": 1733, "y": 231, "w": 262, "h": 23},
        enabled=True, visible=True, patterns=[])
    link = dict(control_id="uia_130_heading_link", runtime_id=[42, 130],
        name="Multi-select boxes (pillbox)", control_type="Hyperlink",
        bbox={"x": 1733, "y": 231, "w": 253, "h": 23},
        enabled=True, visible=True, patterns=["Invoke", "Value"])
    controls = [heading, link, _control()]
    snapshot = {"status": "ok", "scan_complete": True, "truncated": False, "controls": controls}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: {
        "point": dict(POINT), "provider": "isolated-model-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=GOAL,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=2560, height=1400), goal=GOAL,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    assert result["recommended_target"]["element"]["bbox"] == BOX
    assert result["recommended_target"]["element"]["evidence"]["screen_inventory_action"]["source_id"] == "uia_225_combobox"
    assert result["candidate_result"]["summary"]["vista_direct_current_uia_identity_rejection"] is None
