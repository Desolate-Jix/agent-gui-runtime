"""认证点击仅收窄派发遮挡足迹；候选证明及真实点门禁仍完整保留。"""
from copy import deepcopy
from hashlib import sha256
from time import perf_counter_ns

from PIL import Image
import pytest

from tests.test_agent_grounding_target import scene
from tests.test_action_review_route import route
from tests.test_action_review_contract import _review
from tests.test_nonmodal_popup_parent_click import scene as controller_scene


def test_authenticated_route_uses_one_pixel_footprint_and_keeps_candidate(scene, monkeypatch):
    from app.api import action

    dispatched = []

    def install_input_boundary():
        def click(x, y, **options):
            dispatched.append((x, y, deepcopy(options)))
            return {"clicked": True, "point": {"x": x, "y": y}}
        monkeypatch.setattr(action.input_controller, "click_point", click)

    result, provider = route(scene, monkeypatch, mutate=install_input_boundary)
    receipt = result[0]
    assert receipt.success, receipt
    assert len(dispatched) == 1
    assert dispatched[0][:2] == (65, 55)
    assert dispatched[0][2]["target_bbox"] == (65, 55, 1, 1)
    candidate = provider.calls[0]["action"]["candidate"]
    assert candidate["bbox"] == {"x": 30, "y": 40, "w": 71, "h": 31}
    actual = receipt.data.get("result", receipt.data)
    assert actual["action_assessment"]["evaluation_request"]["action"]["candidate"] == candidate
    assert actual["click_visibility_scope"]["candidate_bbox"] == {
        "x": 30, "y": 40, "width": 71, "height": 31}
    assert actual["click_visibility_scope"]["scope"] == "reviewed_click_point"


@pytest.mark.parametrize("availability", ["denied", "disabled"])
def test_unadopted_decision_never_reaches_narrow_input_scope(scene, monkeypatch, availability):
    from app.api import action
    from tests import test_action_review_route as route_fixture

    dispatched = []

    def install_input_boundary():
        monkeypatch.setattr(action.input_controller, "click_point",
            lambda *args, **options: dispatched.append(deepcopy(options)))

    if availability == "disabled":
        service_type = route_fixture.DecisionService
        def disabled_service(*args, **options):
            options["profile"] = options["profile"].model_copy(update={"mode": "off"})
            return service_type(*args, **options)
        monkeypatch.setattr(route_fixture, "DecisionService", disabled_service)
    result, provider = route(scene, monkeypatch, mutate=install_input_boundary,
        deny=availability == "denied")
    assert not result[0].success
    assert dispatched == [] and result[1] == []
    assert result[0].data["dispatch_status"] == "not_dispatched"
    assert result[0].data["click_visibility_scope"]["scope"] == "candidate_bbox"
    assert result[0].data["click_visibility_scope"]["target_bbox"] == {
        "x": 30, "y": 40, "width": 71, "height": 31}
    if availability == "disabled":
        assert provider.calls == []


def _wide_review(tmp_path, monkeypatch, controller_scene, *, hit_on_point=False):
    from app.core import input_controller as inputs
    from app.core import window_manager as windows
    from app.execution.action_review_dispatch import review_original_action
    from app.execution.popup_decision import prepare_popup_continuation

    controller, manager, bound, state = controller_scene
    point = {"x": 1225, "y": 59}
    monkeypatch.setattr(inputs.win32api, "GetCursorPos", lambda: (1225, 59))
    monkeypatch.setattr(controller, "_resolve_window_and_screen_point", lambda **options:
        {"window_x": 1225, "window_y": 59, "screen_x": 1225, "screen_y": 59})
    monkeypatch.setattr(windows.win32gui, "GetWindowRect", lambda handle:
        (2154, 76, 2498, 242) if handle == 200 else (0, 0, 2560, 1400))
    monkeypatch.setattr(windows.win32gui, "GetTopWindow", lambda handle: 200, raising=False)
    monkeypatch.setattr(windows.win32gui, "GetWindow", lambda handle, flag: 100 if handle == 200 else 0,
        raising=False)
    monkeypatch.setattr(windows.win32con, "GW_HWNDNEXT", 2, raising=False)
    monkeypatch.setattr(manager, "_capture_surface_rect", lambda handle: (0, 0, 2560, 1400))
    # 恢复真实区域门禁，仅替换底层 Win32 读取和输入派发。
    monkeypatch.delattr(manager, "validate_bound_region_visibility")

    mod, service, provider, args = _review(tmp_path, monkeypatch)
    image = tmp_path / "wide.png"
    Image.new("RGB", (2560, 1400), "white").save(image)
    identity = {"handle": 100, "process_id": 10, "process_create_time": 30.0}
    capture = {"image_path": str(image), "capture_id": "wide-original",
        "sha256": sha256(image.read_bytes()).hexdigest(), "window_identity": identity,
        "image_size": {"width": 2560, "height": 1400}, "window_rect": [0, 0, 2560, 1400]}
    candidate = {"candidate_id": "address", "capture_id": "wide-original", "source": "external_api",
        "bbox": {"x": 76, "y": 43, "w": 2300, "h": 34}, "click_point": point}
    context = {"schema": "action_review_context.v1", "run_id": "run-1", "attempt_id": "attempt-1",
        "step_id": "open", "budget_ms": 5000, "plan": args["plan"]}
    with mod.action_review_scope(service, context=context,
            deadline_ns=perf_counter_ns() + 5_000_000_000):
        reviewed = review_original_action(capture=capture, identity=identity, candidate=candidate,
            point=point, goal="Address bar", click_kind="single", manager=manager,
            validate_binding=lambda: (identity, candidate))
        footprint = reviewed["click_visibility"]
        assert footprint == {
            "target_bbox": {"x": 1225, "y": 59, "width": 1, "height": 1},
            "candidate_bbox": {"x": 76, "y": 43, "width": 2300, "height": 34},
            "scope": "reviewed_click_point", "reason": "authenticated_decision_target_usable"}
        click_box = tuple(footprint["target_bbox"][key] for key in ("x", "y", "width", "height"))
        guard, _ = prepare_popup_continuation(manager=manager, capture=lambda: capture,
            identity=lambda: identity, candidate=candidate, point=point, bbox=click_box,
            goal="Address bar", click_kind="single", click_count=1, image_path=str(image),
            combined_review=reviewed)
        assert guard is not None
        if hit_on_point:
            state.hit = 999
        try:
            result = controller.click_point(1225, 59, hold_ms=0, target_bbox=click_box,
                pre_input_validator=reviewed["validate"], popup_continuation_guard=guard)
        except inputs.TargetPointOccludedError as error:
            result = error
        assert len(provider.calls) == 1
        return result, state, manager, bound


def test_reviewed_wide_target_accepts_clear_click_despite_remote_one_pixel_overlap(
        tmp_path, monkeypatch, controller_scene):
    result, state, manager, bound = _wide_review(tmp_path, monkeypatch, controller_scene)
    assert result["clicked"] is True
    assert state.events == ["down", "up"]
    # 原宽框仍按旧规则拒绝，证明本例未把底层全框门禁 mock 成放行。
    assert manager.validate_nonmodal_parent_click(bound=bound, x=1225, y=59,
        bbox=(76, 43, 2300, 34), popup_handle=200)["reason"] == "nonmodal_parent_popup_overlaps_target"


def test_reviewed_click_still_rejects_actual_point_occlusion_before_input(
        tmp_path, monkeypatch, controller_scene):
    from app.core.input_controller import TargetPointOccludedError

    result, state, _, _ = _wide_review(tmp_path, monkeypatch, controller_scene, hit_on_point=True)
    assert isinstance(result, TargetPointOccludedError)
    assert result.button_down_attempted is False
    assert state.events == []
