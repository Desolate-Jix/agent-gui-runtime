"""生产原生会话、模型客户端与确切审核预览的隔离闭环。"""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image

from app.agent.reviewed_workflow_asset import content_sha256
from tests.test_formal_model_service import backend
from tests.test_native_model_request import _server
from tests.test_native_model_session import _fresh_coordinator
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError


@pytest.fixture(autouse=True)
def no_external_input(monkeypatch):
    from app.agent.desktop_backend import ExistingWindowsBackendAdapter
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("review must not dispatch external input")
    monkeypatch.setattr(ExistingWindowsBackendAdapter, "dispatch", forbidden)
    yield
    assert calls == []


def test_vista_direct_candidate_round_trips_strict_consumer():
    from app.api.vision import _recognition_candidate_from_vista_direct
    from app.agent.live_runtime_composition import _parse_candidate
    from app.operation.page_structure.schemas import ImageSize

    candidate = _recognition_candidate_from_vista_direct(
        goal="Open", point={"x": 20, "y": 10},
        image_size=ImageSize(width=40, height=20), bbox_size=16,
    )
    parsed = _parse_candidate(candidate.to_dict())
    assert parsed.score == 0.6748
    assert parsed.element.click_point == {"x": 20, "y": 10}
    inconsistent = deepcopy(candidate.to_dict())
    inconsistent["score"] = 0.78
    with pytest.raises(ValueError, match="does not match its breakdown"):
        _parse_candidate(inconsistent)


@pytest.mark.parametrize("approve", [False, True])
def test_model_backed_saved_asset_produces_grounded_preview(tmp_path, monkeypatch, backend, approve):
    from app.agent import live_runtime_composition as composition

    captured = []
    original = composition._run_existing_read_only_recognition
    def record(**kwargs):
        result = original(**kwargs)
        captured.append({"goal": kwargs["goal"], "result": result})
        return result
    monkeypatch.setattr(composition, "_run_existing_read_only_recognition", record)
    with _server() as server:
        co, asset = _fresh_coordinator(tmp_path, monkeypatch, server, grounded_scene=True)
        def visibility(*, bound, x, y):
            assert bound.handle == 41 and bound.process_id == 7
            assert (x, y) == (10, 15)
            return {"contract_version": "bound_point_visibility_v1", "allowed": True,
                    "reason": "target_point_owned_by_bound_window"}
        monkeypatch.setattr(co._window_manager, "validate_bound_point_visibility", visibility, raising=False)
        try:
            observed = co.prepare(asset_id=asset["asset_id"], asset_content_sha256=content_sha256(asset),
                                  target_window_handle=41, target_process_id=7)
            for item in captured:
                composition._parse_recognition(item["result"])
            assert observed["actions"]
            review = co.request_review(action_id=observed["actions"][0]["action_id"])
            assert review["phase"] == "pending_review"
            preview = review["preview"]
            assert preview["session_id"] == observed["session_id"]
            assert preview["workflow"]["asset_content_sha256"] == content_sha256(asset)
            assert preview["target_window_handle"] == 41 and preview["target_process_id"] == 7
            assert preview["review_selection"]["transition_id"] == observed["actions"][0]["action_id"]
            assert preview["grounding_preview"]["click_point"] == {"x": 10, "y": 15}
            assert sha256(review["png_bytes"]).hexdigest() == preview["review_selection"]["capture_lineage"]["screenshot_sha256"]
            with Image.open(BytesIO(review["png_bytes"])) as image:
                assert image.size == (40, 20)
            with pytest.raises(NativeSingleStepCoordinatorError):
                co.execute(confirmation_id=review["confirmation_id"])
            with pytest.raises(NativeSingleStepCoordinatorError):
                co.approve(confirmation_id=review["confirmation_id"], preview_content_sha256="0" * 64)
            if approve:
                approved = co.approve(confirmation_id=review["confirmation_id"],
                                      preview_content_sha256=preview["content_sha256"])
                assert approved["phase"] == "approved"
            assert co.cancel() == {"phase": "idle", "cleanup_verified": True}
            assert co._runtime is None and co._model_service is None
            assert co._host.status()["staging_only"] is True
            assert backend.cleanups
            if approve:
                reopened = co.prepare(asset_id=asset["asset_id"], asset_content_sha256=content_sha256(asset),
                                      target_window_handle=41, target_process_id=7)
                new_review = co.request_review(action_id=reopened["actions"][0]["action_id"])
                assert new_review["confirmation_id"] != review["confirmation_id"]
                with pytest.raises(NativeSingleStepCoordinatorError):
                    co.approve(confirmation_id=review["confirmation_id"],
                               preview_content_sha256=preview["content_sha256"])
                assert co._phase == "pending_review"
                assert co.cancel()["cleanup_verified"] is True
        finally:
            co.shutdown()
        assert co._host.status()["phase"] == "stopped"


def test_model_point_without_local_evidence_cannot_offer_action(tmp_path, monkeypatch, backend):
    with _server() as server:
        co, asset = _fresh_coordinator(tmp_path, monkeypatch, server)
        try:
            observed = co.prepare(asset_id=asset["asset_id"], asset_content_sha256=content_sha256(asset),
                                  target_window_handle=41, target_process_id=7)
            assert observed["actions"] == []
            assert co._runtime._controller is None
            assert co.cancel()["cleanup_verified"] is True
        finally:
            co.shutdown()


@pytest.mark.parametrize("failure", ["occluded", "pixels_changed"])
def test_model_backed_preview_rejects_current_visibility_failure(tmp_path, monkeypatch, backend, failure):
    from app.core import screenshot
    from types import SimpleNamespace
    with _server() as server:
        co, asset = _fresh_coordinator(tmp_path, monkeypatch, server, grounded_scene=True)
        monkeypatch.setattr(co._window_manager, "validate_bound_point_visibility",
                            lambda **_: {"allowed": failure != "occluded"}, raising=False)
        try:
            observed = co.prepare(asset_id=asset["asset_id"], asset_content_sha256=content_sha256(asset),
                                  target_window_handle=41, target_process_id=7)
            assert observed["actions"]
            if failure == "pixels_changed":
                original = screenshot.mss.grab
                captures = []
                def grab(self, monitor):
                    result = original(self, monitor)
                    captures.append(result)
                    if len(captures) == 2:
                        return SimpleNamespace(size=result.size, rgb=b"\xff\x00\x00" + result.rgb[3:])
                    return result
                monkeypatch.setattr(screenshot.mss, "grab", grab)
            with pytest.raises(NativeSingleStepCoordinatorError) as rejected:
                co.request_review(action_id=observed["actions"][0]["action_id"])
            assert rejected.value.code == "grounded_review_rejected"
            assert co._confirmation_id is None and co._attached is False
            assert co.cancel()["cleanup_verified"] is True
        finally:
            co.shutdown()


@pytest.mark.parametrize("evidence", ["matching", "wrong_place", "absent"])
def test_direct_point_corroboration_uses_actual_crop_text_and_preserves_model_point(tmp_path, monkeypatch, evidence):
    from app.api import vision
    from app.operation.page_structure.schemas import ImageSize
    from app.core.runtime_artifacts import pinned_runtime_output_root
    from modules.ocr.contracts import OCRResult, OCRTextMatch, OCRBoundingBox
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 60), "white").save(source)
    point = {"x": 50, "y": 40}
    candidate = vision._recognition_candidate_from_vista_direct(
        goal="Open", point=point, image_size=ImageSize(width=80, height=60), bbox_size=24,
    )
    offset = 30 if evidence == "matching" else 0
    matches = [] if evidence == "absent" else [OCRTextMatch(
        text="Open", score=0.99, bbox=OCRBoundingBox(x=offset, y=offset, width=12, height=12),
    )]
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=path, matches=matches))
    with pinned_runtime_output_root(tmp_path / "output"):
        local = vision._corroborate_vista_direct_point(
            image_path=source, goal="Open", candidate=candidate, point=point, app_name="synthetic",
        )
    assert local.refined_click_point == point
    assert local.crop_bbox == {"x": 14, "y": 4, "w": 66, "h": 56}
    if evidence == "matching":
        assert local.status == "grounded"
        assert local.matched_text_bbox == {"x": 44, "y": 34, "w": 12, "h": 12}
        assert local.matched_text == "Open" and local.confidence == 0.82
    else:
        assert local.status == "unverified" and local.confidence == 0.0
        if evidence == "absent":
            assert local.matched_text is None and local.matched_text_bbox is None
