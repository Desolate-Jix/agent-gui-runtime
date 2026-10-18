"""本次截图点、UIA 扫描预算及同名候选的独立离线回归。"""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
import sys

from PIL import Image
import pytest

from app.api import vision
from app.agent.live_runtime_composition import _parse_recognition
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading import uia_provider as provider_module
from app.vision.schemas import ImageSize
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


LABEL = "Find destination"
TARGET = {"contract_version": "recognition_control_target_v1", "label": LABEL,
          "role": "button", "source_binding_sha256": "a" * 64}


def _control(ident="foreground", *, y=180, **kwargs):
    return {"control_id": ident, "name": LABEL, "control_type": "Button",
            "bbox": {"x": 200, "y": y, "w": 100, "h": 40},
            "visible": True, "enabled": True, "patterns": ["Invoke"], **kwargs}


def _recognize(tmp_path, monkeypatch, controls, *, point=None, top_k=5,
               snapshot_metadata=None, ocr_text=LABEL, target=TARGET):
    path = tmp_path / "fresh-current-point.png"
    Image.new("RGB", (500, 360), "white").save(path)
    model_calls = []

    def model(**kwargs):
        model_calls.append(kwargs)
        return {"point": dict(point or {"x": 250, "y": 200}), "provider": "synthetic-vista"}

    def ocr(crop_path):
        with Image.open(crop_path) as crop:
            width, height = crop.size
        return OCRResult(image_path=str(crop_path), matches=[] if ocr_text is None else [
            OCRTextMatch(text=ocr_text, score=0.99,
                         bbox=OCRBoundingBox(x=width // 2 - 50, y=height // 2 - 10, width=100, height=20))])

    monkeypatch.setattr(vision, "_call_vista_point_prompt", model)
    monkeypatch.setattr(vision.ocr_service, "scan_image", ocr)
    metadata = {"target_text": LABEL,
                "vista_direct_grounding": {"enabled": True, "refine": False, "max_edge": 1024}}
    if target is not None:
        metadata["control_target"] = deepcopy(target)
    request = vision.VisionRecognitionPlanRequestModel(
        image_path=str(path), task="locate_element", goal="Locate the Find destination button in the current popup",
        provider_mode="local_grounding", agent_mode="execute", top_k=top_k,
        write_policy={"path_graph": False, "element_memory": False, "trace": False}, metadata=metadata)
    snapshot = {"provider": "windows_uia", "status": "ok", "controls": deepcopy(controls),
                "scan_budget": 1000, "scan_complete": True, "truncated": False,
                **(snapshot_metadata or {})}
    with provider_module.pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(
            request=request, timer=RuntimeTimer(), config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "offline"}, image_path=path,
            input_image_size=ImageSize(width=500, height=360), goal=request.goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    assert response.success
    assert len(model_calls) == 1
    result = response.data["result"]
    _parse_recognition(result)
    return result


@pytest.mark.parametrize("reverse,top_k", [(False, 5), (True, 5), (False, 1), (True, 1)])
def test_current_point_resolves_disjoint_duplicate_without_list_order(tmp_path, monkeypatch, reverse, top_k):
    controls = [_control("background", y=80), _control()]
    result = _recognize(tmp_path, monkeypatch, list(reversed(controls)) if reverse else controls, top_k=top_k)
    candidate = result["candidate_result"]["candidates"][0]
    evidence = candidate["element"]["evidence"]["current_uia_point_disambiguation"]
    assert evidence["selected_control_id"] == "foreground"
    assert evidence["excluded_control_ids"] == ["background"]
    assert evidence["point"] == {"x": 250, "y": 200}
    assert evidence["screenshot_sha256"] == sha256((tmp_path / "fresh-current-point.png").read_bytes()).hexdigest()
    assert "image_path" not in evidence
    assert result["pre_click_decision"]["allowed"] is True
    assert result["pre_click_decision"]["selected_click_point"] == evidence["point"]
    assert result["candidate_result"]["summary"]["vista_direct_current_uia_identity_reconciled"] is True
    assert result["execution_path"]["action_executed"] is False


@pytest.mark.parametrize("case", ["overlap", "point_outside", "visibility_unknown", "enabled_unknown",
                                   "truncated", "no_ocr", "wrong_ocr", "right_edge", "duplicate_source_id"])
def test_missing_current_evidence_never_resolves_duplicate(tmp_path, monkeypatch, case):
    controls = [_control("background", y=80), _control()]
    options = {}
    if case == "overlap":
        controls[0]["bbox"] = deepcopy(controls[1]["bbox"])
    elif case == "duplicate_source_id":
        controls[0]["control_id"] = controls[1]["control_id"]
    elif case == "point_outside":
        options["point"] = {"x": 30, "y": 150}
    elif case == "right_edge":
        options["point"] = {"x": 300, "y": 200}
    elif case == "visibility_unknown":
        controls[1]["visible"] = None
    elif case == "enabled_unknown":
        controls[1]["enabled"] = None
    elif case == "truncated":
        options["snapshot_metadata"] = {"scan_budget": 250, "scan_complete": False, "truncated": True}
    elif case == "no_ocr":
        options["ocr_text"] = None
    elif case == "wrong_ocr":
        options["ocr_text"] = "Confirm payment"
    result = _recognize(tmp_path, monkeypatch, controls, **options)
    assert result["pre_click_decision"]["allowed"] is False
    assert result["pre_click_decision"]["selected_click_point"] is None
    if case == "truncated":
        assert result["candidate_result"]["summary"]["vista_direct_current_uia_identity_rejection"] == "vista_direct_current_uia_scan_incomplete"


def test_duplicate_current_label_without_control_target_uses_same_evidence(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, [_control("background", y=80), _control()], target=None)
    assert result["pre_click_decision"]["allowed"] is True
    assert result["candidate_result"]["candidates"][0]["element"]["evidence"]["current_uia_point_disambiguation"]["selected_control_id"] == "foreground"


def test_disambiguated_candidate_survives_public_projection_without_binding_drift(tmp_path, monkeypatch):
    from app.agent.fresh_learning_observation import _PUBLIC_RECOGNITION_KEYS, _sanitize_result
    from app.agent.fresh_learning_action_preview import _parse_projected_recognition

    original = _recognize(tmp_path, monkeypatch, [_control("background", y=80), _control()])
    projection = _sanitize_result(
        {key: original[key] for key in _PUBLIC_RECOGNITION_KEYS if key in original},
        capture_path=(tmp_path / "fresh-current-point.png").resolve())
    raw_candidates, raw_local = _parse_recognition(original)
    for result in raw_local.results:
        result.crop_path = None
    assert (raw_candidates, raw_local) == _parse_projected_recognition(projection)


def test_known_incomplete_scan_cannot_become_ordinary_unique_uia_primary(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, [_control()], target=None,
                        snapshot_metadata={"scan_complete": False, "truncated": True})
    assert result["pre_click_decision"]["allowed"] is False
    assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is False


def test_current_point_disambiguation_does_not_grant_payment_authority(tmp_path, monkeypatch):
    from app.gate.fresh_action_risk import classify_fresh_action_risk

    label = "Confirm payment"
    controls = [_control("background", y=80, name=label), _control(name=label)]
    result = _recognize(tmp_path, monkeypatch, controls, target={**TARGET, "label": label}, ocr_text=label)
    candidates, local = _parse_recognition(result)
    assert candidates.candidates
    risk = classify_fresh_action_risk(
        proposed_semantic_action="open_detail", goal="Locate current button",
        candidate=candidates.candidates[0], local=local.results[0], capture_id="fresh.synthetic.payment",
        uia_snapshot={"provider": "windows_uia", "status": "ok", "controls": controls})
    assert risk["hard_blocked"] is True


class _Node:
    def __init__(self, index, root=None):
        self.element_info = SimpleNamespace(name=f"node {index}", control_type="Button",
                                            automation_id=f"node-{index}", runtime_id=[index])
        self._parent = root

    def rectangle(self):
        return SimpleNamespace(left=200, top=180, right=300, bottom=220)

    def parent(self):
        return self._parent

    def is_visible(self):
        return True

    def is_enabled(self):
        return True


def _scan(monkeypatch, count, *, limit=None):
    root = _Node(0)
    pulled = []

    def descendants():
        for index in range(1, count):
            pulled.append(index)
            yield _Node(index, root)

    root.iter_descendants = descendants
    root.wrapper_object = lambda: root
    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(
        Desktop=lambda **_: SimpleNamespace(window=lambda **__: root)))
    bound = SimpleNamespace(handle=7, title="synthetic", process_id=12, process_name="synthetic.exe",
                            rect=SimpleNamespace(left=0, top=0, right=500, bottom=360))
    kwargs = {} if limit is None else {"max_controls": limit}
    return provider_module.WindowsUIAProvider().snapshot_window(bound, **kwargs), pulled


def test_default_scan_can_reach_267_controls_without_silent_250_cutoff(monkeypatch):
    snapshot, pulled = _scan(monkeypatch, 267)
    assert snapshot["control_count"] == 267
    assert len(pulled) == 266
    assert snapshot["scan_budget"] == 1000
    assert snapshot["scan_visited_count"] == 267
    assert snapshot["truncated"] is False
    assert snapshot["scan_complete"] is True


@pytest.mark.parametrize("limit,budget", [(250, 250), (1000, 1000), (100_000, 4000), (0, 1)])
def test_scan_budget_is_hard_bounded_and_reports_incomplete(monkeypatch, limit, budget):
    snapshot, pulled = _scan(monkeypatch, 10_000, limit=limit)
    assert snapshot["control_count"] == snapshot["scan_visited_count"] == budget
    assert len(pulled) == budget - 1
    assert snapshot["scan_budget"] == budget
    assert snapshot["truncated"] is True
    assert snapshot["scan_complete"] is False
    assert snapshot["truncation_reason"] == "control_budget_reached"


def test_fast_inventory_preserves_original_pinned_scan_budget(tmp_path, monkeypatch):
    snapshot = {"provider": "windows_uia", "status": "ok", "controls": [_control()],
                "scan_budget": 250, "scan_visited_count": 250,
                "truncated": True, "scan_complete": False, "truncation_reason": "control_budget_reached"}
    with provider_module.pinned_uia_snapshot(snapshot):
        result = vision._execute_fast_inventory_from_uia(
            image_path=tmp_path / "fresh.png", image_size=ImageSize(width=500, height=360),
            app_name=None, goal=LABEL, metadata=None)
    assert result["uia_scan_budget"] == 250
    assert result["uia_scan_truncated"] is True
    assert result["uia_scan_complete"] is False
    assert result["status"] == "incomplete"
    assert result["screen_inventory"] is None
    assert result["screen_reading"]["source_layers"]["windows_uia"]["scan_visited_count"] == 250


@pytest.mark.parametrize("requested,expected", [(None, 1000), ({"max_controls": 99999}, 4000), ({"max_controls": "bad"}, 1000)])
def test_fast_inventory_requests_bounded_sufficient_scan(tmp_path, monkeypatch, requested, expected):
    budgets = []

    def snapshot(*, max_controls):
        budgets.append(max_controls)
        return {"provider": "windows_uia", "status": "ok", "controls": [_control()]}

    monkeypatch.setattr(vision.uia_provider, "snapshot_bound_window", snapshot)
    vision._execute_fast_inventory_from_uia(
        image_path=tmp_path / "fresh.png", image_size=ImageSize(width=500, height=360),
        app_name=None, goal=LABEL, metadata={"execute_fast_inventory": requested})
    assert budgets == [expected]
