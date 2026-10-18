"""新内容滚动经过原生后端适配器，系统滚轮与截图供应方使用合成边界。"""
from contextlib import contextmanager
from copy import deepcopy

import pytest
from PIL import Image, ImageDraw

from app.agent.desktop_backend import ExistingWindowsBackendAdapter
from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.live_controller import LiveControllerDecision
from app.agent.scroll_parameters import ReviewedScrollParameters
from app.core.runtime_input_authority import runtime_backend_input_is_active
from tests.test_fresh_action_risk import _control
from tests.test_fresh_dispatch_graph import _Visible, _close
from tests.test_fresh_learning_action_preview import _recognize
from tests.test_formal_fresh_learning_observation import _owner, _WindowManager, _NativeReader, _UIAProvider, _bound, _ScreenshotService
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_runtime_session import _runtime


class _ScrollUIA(_UIAProvider):
    pattern = True
    def snapshot_window(self, bound):
        result = super().snapshot_window(bound)
        control = _control("fresh.scroll", "Read details", {"x": 10, "y": 10, "w": 120, "h": 40}, control_type="Pane")
        control["patterns"] = ["Scroll"] if self.pattern else []
        result["controls"] = [control]
        return result


class _Frames(_ScreenshotService):
    mode = "target"
    changed = False
    def capture_window(self, **kwargs):
        result = super().capture_window(**kwargs)
        if self.changed:
            with Image.open(self.path) as image:
                changed = image.copy()
            if self.mode != "none":
                box = (15, 15, 90, 40) if self.mode == "target" else (135, 60, 158, 90)
                ImageDraw.Draw(changed).rectangle(box, fill="white")
                changed.save(self.path)
        return result


class _Input:
    def __init__(self, frames):
        self.frames = frames
        self.calls = []
    def scroll_window(self, **kwargs):
        assert runtime_backend_input_is_active()
        self.calls.append(kwargs)
        self.frames.changed = True
        return {"scrolled": True, "window_handle": 4242, "direction": kwargs["direction"],
            "wheel_clicks": kwargs["wheel_clicks"], "wheel_delta": (-120 if kwargs["direction"] == "down" else 120) * kwargs["wheel_clicks"]}
    def click_point(self, *args, **kwargs):
        raise AssertionError("scroll must not dispatch a click")


@contextmanager
def _scroll_runtime(root, mode="target"):
    frames = _Frames(root / "captures")
    frames.mode = mode
    uia = _ScrollUIA()
    def recognize(**kwargs):
        result = _recognize(**kwargs)
        candidate = result["candidate_result"]["candidates"][0]
        candidate["role"] = candidate["element"]["role"] = "region"
        return result
    owner = _owner(root / "captures", screenshot=frames, application={"kind": "native", "executable_path": r"c:\fresh\app.exe"},
        manager=_WindowManager(*[_bound() for _ in range(1000)]), native=_NativeReader(*[100.5] * 1000), uia=uia, runner=recognize)
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    host, connection, segment, _packet, _args, staged = _stage(root, packet)
    owner.project_root = host.fresh_learning.archive.project_root
    runtime, _backend, claims, source = _runtime(host, connection, segment, staged, observation_owner=owner)
    native_input = _Input(frames)
    runtime._backend = ExistingWindowsBackendAdapter(input_controller=native_input, window_manager=owner._window_manager, post_dispatch_settle_seconds=0)
    runtime.set_action_learning_recorder(host.fresh_learning.segments.recorder)
    runtime._window_visibility_checker = _Visible()
    session = runtime.start_session()
    scope = {key: source.reference()[key] for key in ("connection_id", "task_id", "segment_id")}
    host.fresh_learning.segments.attach_runtime(**scope, runtime_session_id=session.session_id)
    intent = FreshLearningIntent.from_dict({"contract_version": "fresh_learning_action_intent_v1", "intent_id": "intent.scroll",
        "session_id": session.session_id, "observation_id": session.current_observation.observation_id,
        "source_sha256": source.reference()["source_sha256"], "action_id": "action.scroll", "semantic_action": "scroll_region",
        "goal": "Read details", "scroll_parameters": ReviewedScrollParameters("fresh.scroll", "vertical", "down", 3, "wheel_detent").to_payload()})
    try:
        yield host, owner, runtime, claims, native_input, session, scope, intent
    finally:
        _close(host, runtime)


@pytest.mark.parametrize("mode,status,wrong_scope", [("target", "target_visual_change", False), ("outside", "non_target_visual_change", True), ("none", "no_visual_change", False)])
def test_scroll_is_not_click_and_measures_scope_with_durable_once_receipt(tmp_path, mode, status, wrong_scope):
    with _scroll_runtime(tmp_path, mode) as (host, owner, runtime, claims, native_input, session, scope, intent):
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert not isinstance(claim, LiveControllerDecision), claim
        cid = claim.grounded_confirmation.confirmation_id
        assert native_input.calls == []
        assert runtime.record_grounded_confirmation_decision(confirmation_id=cid, decision="approved").phase == "grounded_confirmation_approved"
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.outcome == "ACTION_RECORDED"
        assert result.action.semantic_action == "scroll_region"
        assert native_input.calls == [{"direction": "down", "wheel_clicks": 3, "x": 60, "y": 30}]
        proof = result.evidence.scroll_verification
        assert proof["spatial"]["status"] == status
        assert proof["spatial"]["wrong_scope_detected"] is wrong_scope
        assert proof["spatial"]["direction_verified"] is None
        assert proof["before"]["capture_id"] != proof["after"]["capture_id"]
        assert runtime.consume_grounded_confirmation(confirmation_id=cid) == result
        assert len(native_input.calls) == 1
        stored = claims.load_terminal_receipt_record(session_id=session.session_id, observation_id=intent.observation_id)
        assert stored.next_observation.to_dict()["capture"]["capture_id"] == proof["after"]["capture_id"]
        synced = host.fresh_learning.sync_actions(**scope)
        graph = host.fresh_learning.facade.load_graph_revision(synced["logical_workflow_id"])["graph"]
        if mode == "target":
            assert len(graph["edges"]) == 1
            edge = graph["edges"][0]
            assert edge["scroll_parameters"]["wheel_clicks"] == 3
            assert edge["scroll_parameters"]["target_container_id"] == edge["target_region_id"]
        else:
            assert graph["edges"] == []
            assert graph["invalid_sources"]
            assert len([node for node in graph["nodes"] if node.get("surface_type") == "recorded_action_observation"]) == 2


def test_scroll_pattern_disappearing_after_confirmation_blocks_input(tmp_path):
    with _scroll_runtime(tmp_path) as (_host, owner, runtime, _claims, native_input, _session, _scope, intent):
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert not isinstance(claim, LiveControllerDecision), claim
        cid = claim.grounded_confirmation.confirmation_id
        runtime.record_grounded_confirmation_decision(confirmation_id=cid, decision="approved")
        owner._uia_provider.pattern = False
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert isinstance(result, LiveControllerDecision) and result.reason_code == "grounded_confirmation_stale"
        assert native_input.calls == []


def test_wrong_container_and_changed_wheel_count_do_not_reuse_confirmation(tmp_path):
    with _scroll_runtime(tmp_path) as (_host, _owner, runtime, _claims, native_input, _session, _scope, intent):
        wrong = intent.to_dict()
        wrong["scroll_parameters"]["target_container_id"] = "another-pane"
        assert isinstance(runtime.request_grounded_confirmation(wrong, target_process_id=9001), LiveControllerDecision)
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert not isinstance(claim, LiveControllerDecision), claim
        changed = intent.to_dict()
        changed["scroll_parameters"]["wheel_clicks"] = 4
        result = runtime.request_grounded_confirmation(changed, target_process_id=9001)
        assert isinstance(result, LiveControllerDecision)
        assert native_input.calls == []


def test_unknown_scroll_outcome_never_retries_and_keeps_unverified_scope(tmp_path, monkeypatch):
    with _scroll_runtime(tmp_path) as (_host, _owner, runtime, _claims, native_input, _session, _scope, intent):
        original = native_input.scroll_window
        def lost(**kwargs):
            original(**kwargs)
            raise OSError("synthetic response loss")
        monkeypatch.setattr(native_input, "scroll_window", lost)
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        cid = claim.grounded_confirmation.confirmation_id
        runtime.record_grounded_confirmation_decision(confirmation_id=cid, decision="approved")
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.outcome == "EXECUTION_UNKNOWN" and result.effect_status == "not_verified"
        assert result.evidence.scroll_verification["spatial"]["status"] == "unknown"
        assert result.evidence.scroll_verification["after"] is None
        assert runtime.consume_grounded_confirmation(confirmation_id=cid) == result
        assert len(native_input.calls) == 1


def test_forged_success_cannot_hide_wrong_scope(tmp_path):
    from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt
    with _scroll_runtime(tmp_path, "outside") as (_host, _owner, runtime, _claims, _input, _session, _scope, intent):
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        cid = claim.grounded_confirmation.confirmation_id
        runtime.record_grounded_confirmation_decision(confirmation_id=cid, decision="approved")
        receipt = runtime.consume_grounded_confirmation(confirmation_id=cid)
        tampered = receipt.model_dump()
        tampered["evidence"]["scroll_verification"]["spatial"]["wrong_scope_detected"] = False
        with pytest.raises(ValueError):
            RuntimeFreshResultReceipt.from_dict(tampered)


def test_native_panel_shows_actual_scroll_scope_direction_and_count(tmp_path):
    from app.desktop_review.window import ensure_application
    from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget
    ensure_application()
    with _scroll_runtime(tmp_path) as (_host, _owner, runtime, _claims, native_input, _session, _scope, intent):
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        grounded = claim.grounded_confirmation
        view = {"phase": "pending_review", "confirmation_id": grounded.confirmation_id, "preview": grounded.preview.to_dict(),
            "source_kind": "fresh_learning", "requested_at": grounded.requested_at.isoformat().replace("+00:00", "Z"),
            "expires_at": grounded.expires_at.isoformat().replace("+00:00", "Z"), "owner_is_current": True,
            "png_bytes": runtime.get_local_grounded_image(confirmation_id=grounded.confirmation_id)}
        widget = GroundedPreviewWidget()
        try:
            widget.set_review(view)
            shown = widget.metadata_text.toPlainText()
            assert "滚动容器：fresh.scroll" in shown and "方向：向下" in shown and "滚轮刻度：3" in shown
            assert "不点击，不缩放地图" in shown
            assert native_input.calls == []
        finally:
            widget.close()
            widget.deleteLater()


def test_saved_interface_scroll_region_reuses_current_geometry_not_old_box(tmp_path):
    from app.agent.learned_control_reference import resolve_learned_control
    from uuid import uuid4
    with _scroll_runtime(tmp_path) as (host, _owner, runtime, _claims, native_input, _session, scope, intent):
        reference = runtime._binding.source.reference()
        first = host.facade.import_interface_content(scope["task_id"], reference["batch_id"], "observed-screen")
        region = {"region_id": "region-user-" + str(uuid4()), "bbox": [0, 0, 1, 1], "name": "Read details", "kind": "container",
            "meaning": "scrollable details", "recognition_text": "Read details"}
        saved = host.facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"],
            {"regions": [region]}, "save-scroll-region")
        binding = resolve_learned_control(host.fresh_learning, reference,
            {"interface_id": saved["interface_id"], "version_id": saved["version_id"], "region_id": region["region_id"]})
        payload = intent.to_dict()
        payload["learned_control"] = binding
        payload["scroll_parameters"]["target_container_id"] = region["region_id"]
        claim = runtime.request_grounded_confirmation(payload, target_process_id=9001)
        assert not isinstance(claim, LiveControllerDecision), claim
        cid = claim.grounded_confirmation.confirmation_id
        runtime.record_grounded_confirmation_decision(confirmation_id=cid, decision="approved")
        receipt = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(receipt, LiveControllerDecision), receipt
        assert receipt.evidence.scroll_verification["target_bbox"] == {"x": 10, "y": 10, "width": 120, "height": 40}
        assert receipt.evidence.scroll_verification["scroll_parameters"]["target_container_id"] == region["region_id"]
        assert native_input.calls[0]["x"] == 60 and native_input.calls[0]["y"] == 30
