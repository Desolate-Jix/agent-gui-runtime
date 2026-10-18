"""从公开观察入口验证图标能力与原生证据链，不跳过观察所有者。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.fresh_learning_observation import FreshLearningObservationOwner, FreshLearningObservationError
from app.agent.native_control_hit_context import collect_current_control_hit
from app.operation.recognition.native_control_hit_binding import EVIDENCE_KEY, validate_control_hit_observation
from tests.test_native_control_hit_context import _setup


def _owner_entry(tmp_path, monkeypatch, *, fail_runner=False, ocr_text=None):
    from app.api import vision
    from app.agent import native_control_hit_context as context
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from app.vision.schemas import ImageSize
    from modules.ocr.contracts import OCRResult, OCRTextMatch, OCRBoundingBox

    dependencies, args, state, _, _, _ = _setup(tmp_path, monkeypatch)
    state.update(runner_calls=[], callbacks=[], model_calls=[])
    def model(**kwargs):
        state["model_calls"].append(kwargs)
        return {"point": {"x": 20, "y": 20}, "provider": "synthetic-vista"}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", model)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path),
        matches=[] if ocr_text is None else [OCRTextMatch(text=ocr_text, score=0.624,
            bbox=OCRBoundingBox(x=16, y=16, width=10, height=10))]))
    def recognition_runner(**kwargs):
        state["runner_calls"].append(kwargs)
        state["callbacks"].append(context._collector.get())
        image_path = Path(kwargs["image_path"])
        request = vision.VisionRecognitionPlanRequestModel(image_path=str(image_path), task="locate_element",
            goal=kwargs["goal"], provider_mode="local_grounding", agent_mode="execute", top_k=5,
            write_policy={"path_graph": False, "element_memory": False, "trace": False},
            metadata={"target_text": "搜索", "semantic_action": "open_detail",
                "vista_direct_grounding": {"enabled": True, "refine": False, "max_edge": 1024}})
        with pinned_uia_snapshot(kwargs["uia_snapshot"]), pinned_runtime_output_root(tmp_path):
            response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
                config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "offline"},
                image_path=image_path, input_image_size=ImageSize(width=160, height=100), goal=kwargs["goal"],
                observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
        assert response.success
        if fail_runner:
            raise RuntimeError("synthetic recognition failure after scoped native hit")
        return response.data["result"]
    owner = FreshLearningObservationOwner(project_root=tmp_path,
        application_identity={"kind": "native", "executable_path": "c:\\fake.exe"},
        screenshot_service=dependencies._screenshot_service, window_manager=dependencies._window_manager,
        native_identity_reader=dependencies._native_identity_reader,
        uia_provider=SimpleNamespace(snapshot_window=lambda _: deepcopy(args["uia_snapshot"])),
        recognition_runner=recognition_runner)
    return owner, state


def _observe(owner, semantic_action="open_detail"):
    return owner.observe_for_action(target_window_handle=7, target_process_id=8,
        goal="搜索", semantic_action=semantic_action)


def _assert_revoked(state):
    request = state["runner_calls"][0]
    arguments = {key: request[key] for key in ("image_path", "uia_snapshot")}
    arguments["point"] = {"x": 20, "y": 20}
    assert collect_current_control_hit(**arguments) is None
    callback = state["callbacks"][0]
    if callback is not None:
        with pytest.raises(ValueError, match="outside"):
            callback(**arguments)


def test_public_open_detail_entry_enables_real_icon_recognition_and_revokes(tmp_path, monkeypatch):
    owner, state = _owner_entry(tmp_path, monkeypatch)
    bundle = _observe(owner)
    result = bundle.recognition_result()
    assert state["runner_calls"][0]["semantic_action"] == "open_detail"
    assert callable(state["callbacks"][0])
    assert result["pre_click_decision"]["allowed"] is True
    assert result["execution_path"]["action_executed"] is False
    candidate = result["candidate_result"]["candidates"][0]
    proof = candidate["element"]["evidence"][EVIDENCE_KEY]
    assert proof["hit"]["accessible_name"] == "搜索"
    assert proof["hit"]["sample_count"] == 2
    assert result["narrow_search_result"]["results"][0]["matched_text"] is None
    validate_control_hit_observation(proof, bundle.packet.evidence(), bundle.uia_snapshot(), {"x": 20, "y": 20})
    assert state["hits"] == [(50, 70), (50, 70)]
    assert len(state["captures"]) == 3 and len(state["model_calls"]) == 1
    assert all(capture["focus_window"] is False for capture in state["captures"])
    _assert_revoked(state)


def test_no_owner_hint_cannot_enable_icon_by_runner_metadata(tmp_path, monkeypatch):
    owner, state = _owner_entry(tmp_path, monkeypatch)
    bundle = _observe(owner, None)
    assert "semantic_action" not in state["runner_calls"][0]
    assert state["callbacks"] == [None]
    assert bundle.recognition_result()["pre_click_decision"]["allowed"] is False
    assert state["hits"] == [] and len(state["captures"]) == 1
    _assert_revoked(state)


def test_public_entry_failure_revokes_collector_after_actual_native_hit(tmp_path, monkeypatch):
    owner, state = _owner_entry(tmp_path, monkeypatch, fail_runner=True)
    with pytest.raises(FreshLearningObservationError):
        _observe(owner)
    assert len(state["hits"]) == 2 and len(state["captures"]) == 3
    _assert_revoked(state)


def test_public_owner_keeps_q_as_disagreement_not_missing_geometry(tmp_path, monkeypatch):
    from app.operation.recognition.native_control_ocr_observation import KEY, DISAGREEMENT
    owner, state = _owner_entry(tmp_path, monkeypatch, ocr_text='Q')
    bundle = _observe(owner)
    result = bundle.recognition_result()
    assert result['pre_click_decision']['allowed'] is False
    local = result['narrow_search_result']['results'][0]
    assert local['status'] == 'grounded' and DISAGREEMENT in local['reasons']
    candidate = result['candidate_result']['candidates'][0]
    assert candidate['element']['evidence'][KEY]['matches'][0]['text'] == 'Q'
    assert len(state['hits']) == 2
    _assert_revoked(state)
