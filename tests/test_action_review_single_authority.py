"""候选语义只审核一次；派发仍核对原始证据、身份和输入绑定。"""
import pytest
from PIL import ImageDraw

from tests.test_agent_grounding_target import scene
from tests.test_action_review_route import route


@pytest.mark.parametrize("presentation", ["caret", "border", "outside", "target"])
def test_approved_candidate_does_not_start_another_pixel_review(scene, monkeypatch, presentation):
    from app.api import action

    captures_after_review = []

    def change_live_presentation():
        changed = scene[2].copy()
        drawing = ImageDraw.Draw(changed)
        if presentation == "caret":
            drawing.line((40, 45, 40, 60), fill="black")
        elif presentation == "border":
            drawing.rectangle((30, 40, 100, 70), outline="black")
        elif presentation == "outside":
            drawing.rectangle((150, 100, 190, 140), fill="red")
        else:
            drawing.rectangle((30, 40, 100, 70), fill="red")
        path = scene[3] / "new-live-frame.png"
        changed.save(path)

        def capture(**kwargs):
            captures_after_review.append(kwargs["purpose"])
            return {"image_path": str(path), "window_size": {"width": 200, "height": 150}, "roi": None}

        monkeypatch.setattr(action.screenshot_service, "capture_window", capture)

    result, provider = route(scene, monkeypatch, mutate=change_live_presentation)
    assert result[0].success, result[0]
    assert result[1] == [(65, 55)]
    assert len(provider.calls) == 1
    assert captures_after_review == []
    assert result[0].data["result"]["action_assessment"]["scope"] == "candidate"


@pytest.mark.parametrize("mutation", ["pid", "birth", "geometry"])
def test_approved_candidate_still_rejects_changed_native_binding(scene, monkeypatch, mutation):
    from tests import test_action_review_route as fixtures

    services = []
    service_class = fixtures.DecisionService

    def create_service(*args, **kwargs):
        service = service_class(*args, **kwargs)
        services.append(service)
        return service

    monkeypatch.setattr(fixtures, "DecisionService", create_service)

    def change_binding():
        _, identity, bound = services[0].runtime_scene
        if mutation == "geometry":
            bound.rect.right += 1
            return
        identity["process_id" if mutation == "pid" else "process_create_time"] += 1

    result, provider = route(scene, monkeypatch, mutate=change_binding)
    assert not result[0].success
    assert result[1] == []
    assert result[0].data["dispatch_status"] == "not_dispatched"
    assert len(provider.calls) == 1


def test_standalone_adopted_decision_also_avoids_duplicate_pixel_veto(scene, monkeypatch):
    from app.api import action
    from tests.test_execution_decision_check import Decisions, run_route

    after_review_captures = []

    def presentation_changes():
        changed = scene[2].copy()
        ImageDraw.Draw(changed).line((40, 45, 40, 60), fill="black")
        path = scene[3] / "standalone-live.png"
        changed.save(path)

        def capture(**kwargs):
            after_review_captures.append(kwargs["purpose"])
            return {"image_path": str(path), "window_size": {"width": 200, "height": 150}, "roi": None}

        monkeypatch.setattr(action.screenshot_service, "capture_window", capture)

    service = Decisions(during=presentation_changes)
    result = run_route(scene, monkeypatch, service)
    assert result[0].success, result[0]
    assert result[1] == [(65, 55)]
    assert len(service.calls) == 1
    assert after_review_captures == []


def test_native_binding_read_crossing_deadline_cannot_release_approved_action(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tests.test_action_review_contract import _review
    from app.execution import action_review_dispatch as dispatch
    from app.execution.decision_check import DecisionCheckRejected

    mod, service, _, args = _review(tmp_path, monkeypatch)
    now = [args["deadline_ns"] - 1]
    monkeypatch.setattr(mod, "perf_counter_ns", lambda: now[0])
    monkeypatch.setattr(dispatch, "perf_counter_ns", lambda: now[0], raising=False)
    bound = SimpleNamespace(handle=10, process_id=20,
        rect=SimpleNamespace(left=0, top=0, right=200, bottom=150))

    def slow_native_read():
        now[0] = args["deadline_ns"]
        return args["identity"], args["candidate"]

    context = {"schema": "action_review_context.v1", "run_id": "run-1",
        "attempt_id": "attempt-1", "step_id": "open", "budget_ms": 5000, "plan": args["plan"]}
    with mod.action_review_scope(service, context=context, deadline_ns=args["deadline_ns"]):
        with pytest.raises(DecisionCheckRejected, match="action_review_not_adoptable"):
            dispatch.review_original_action(capture=args["capture"], identity=args["identity"],
                candidate=args["candidate"], point=args["candidate"]["click_point"],
                goal="Address bar", click_kind="single", manager=SimpleNamespace(get_bound_window=lambda: bound),
                validate_binding=slow_native_read)
