from __future__ import annotations

from types import SimpleNamespace

from app.api import action as action_api
from app.models.request import ClickTextRequest, ROIModel, ScrollRequest, TypeTextRequest
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def test_click_text_uses_roi_offset_and_returns_success(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Demo",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        ),
    )
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda roi=None, save_image=True, **kwargs: {
            "image_path": "capture.png",
            "roi": {"x": 100, "y": 200, "width": 300, "height": 200},
            "roi_adjusted": False,
            "window_size": {"width": 800, "height": 600},
        },
    )
    monkeypatch.setattr(
        action_api.ocr_service,
        "scan_image",
        lambda path: OCRResult(
            image_path=path,
            matches=[
                OCRTextMatch(
                    text="Start",
                    score=0.93,
                    bbox=OCRBoundingBox(x=20, y=30, width=40, height=20),
                )
            ],
        ),
    )
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda roi=None, action_name=None: {"image_path": "before.png"})
    monkeypatch.setattr(action_api.verifier, "verify_action", lambda *args, **kwargs: {"verified": True})
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/click_text.json")

    clicked: dict[str, int] = {}

    def fake_click(x: int, y: int, **kwargs):
        clicked["x"] = x
        clicked["y"] = y
        return {"clicked": True, "window_point": {"x": x, "y": y}}

    monkeypatch.setattr(action_api.input_controller, "click_point", fake_click)

    response = action_api.click_text(
        ClickTextRequest(text="Start", roi=ROIModel(x=100, y=200, width=300, height=200), partial_match=False)
    )

    assert response.success is True
    assert clicked == {"x": 140, "y": 240}
    assert response.data["result"]["selected_match"]["text"] == "Start"
    assert response.data["result"]["execution_path"]["vision_model_used"] is False
    assert response.data["result"]["trace_path"].endswith("click_text.json")


def test_click_text_returns_text_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Demo",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        ),
    )
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda roi=None, save_image=True, **kwargs: {
            "image_path": "capture.png",
            "roi": None,
            "roi_adjusted": False,
            "window_size": {"width": 800, "height": 600},
        },
    )
    monkeypatch.setattr(action_api.ocr_service, "scan_image", lambda path: OCRResult(image_path=path, matches=[]))
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/click_text-not-found.json")

    response = action_api.click_text(ClickTextRequest(text="Missing"))

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "text_not_found"
    assert response.data["trace_path"].endswith("click_text-not-found.json")


def test_type_text_dispatches_real_input(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Demo",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/type_text.json")

    typed: dict[str, object] = {}

    def fake_type_text(text: str, **kwargs):
        typed.update({"text": text, **kwargs})
        return {"typed": True, "text_length": len(text)}

    monkeypatch.setattr(action_api.input_controller, "type_text", fake_type_text)

    response = action_api.type_text(
        TypeTextRequest(
            text="ai latest progress",
            x=20,
            y=30,
            click_before_typing=True,
            clear_existing=True,
            submit=True,
        )
    )

    assert response.success is True
    assert typed["text"] == "ai latest progress"
    assert typed["x"] == 20
    assert typed["y"] == 30
    assert typed["click_before_typing"] is True
    assert typed["clear_existing"] is True
    assert typed["submit"] is True
    assert response.data["result"]["execution_path"]["action_executed"] is True


def test_type_text_dry_run_does_not_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Demo",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/type_text-dry-run.json")
    monkeypatch.setattr(
        action_api.input_controller,
        "type_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry run should not type")),
    )

    response = action_api.type_text(TypeTextRequest(text="dry", dry_run=True))

    assert response.success is True
    assert response.data["result"]["dry_run"] is True
    assert response.data["result"]["execution_path"]["action_executed"] is False


def test_scroll_dry_run_validates_without_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Demo",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/scroll-dry-run.json")
    monkeypatch.setattr(
        action_api.input_controller,
        "scroll_window",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("dry run should not scroll")),
    )

    response = action_api.scroll(ScrollRequest(direction="down", wheel_clicks=3, dry_run=True))

    assert response.success is True
    result = response.data["result"]
    assert result["contract_version"] == "scroll_action_v1"
    assert result["point"] == {"x": 400, "y": 300}
    assert result["execution_path"]["action_executed"] is False
    assert result["trace_path"].endswith("scroll-dry-run.json")


def test_scroll_container_dry_run_resolves_seek_job_detail(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Software Engineer Jobs in All Auckland, Job Vacancies | SEEK - Microsoft Edge",
            rect=SimpleNamespace(left=0, top=0, right=1246, bottom=1194),
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/seek-scroll-dry-run.json")
    monkeypatch.setattr(
        action_api.input_controller,
        "scroll_window",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("dry run should not scroll")),
    )

    response = action_api.scroll(
        ScrollRequest(
            contract_version="scroll_request_v2",
            scroll_scope="container",
            target_pane="job_detail",
            target_container_id="seek:job_detail",
            direction="down",
            dry_run=True,
            reason="required_detail_section_not_visible",
        )
    )

    assert response.success is True
    result = response.data["result"]
    assert result["contract_version"] == "scroll_action_v2"
    assert result["target_container"]["container_id"] == "seek:job_detail"
    assert result["precondition_decision"]["decision"] == "ALLOW"
    assert result["resolved_target"]["point_inside_container"] is True
    assert result["outcome"]["status"] == "dry_run_ready"


def test_scroll_container_rejects_coordinate_window_size_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Software Engineer Jobs in All Auckland, Job Vacancies | SEEK - Microsoft Edge",
            rect=SimpleNamespace(left=0, top=0, right=1246, bottom=1194),
        ),
    )

    response = action_api.scroll(
        ScrollRequest(
            contract_version="scroll_request_v2",
            scroll_scope="container",
            target_pane="results_list",
            target_container_id="seek:results_list",
            coordinate_window_size={"width": 999, "height": 1194},
            dry_run=True,
        )
    )

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "scroll_precondition_rejected"
    assert "coordinate_window_size_mismatch" in response.data["precondition_decision"]["reject_reasons"]


def test_scroll_dispatches_and_verifies(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Demo",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/scroll.json")
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda action_name=None: {"image_path": "before.png"})
    monkeypatch.setattr(
        action_api.verifier,
        "verify_action",
        lambda *args, **kwargs: {
            "verified": True,
            "before": {"image_path": "before.png"},
            "after": {"image_path": "after.png"},
            "diff": {"diff_image_path": "diff.png", "changed": True},
        },
    )
    scrolled: dict[str, object] = {}

    def fake_scroll_window(**kwargs):
        scrolled.update(kwargs)
        return {"scrolled": True, "direction": kwargs["direction"], "wheel_clicks": kwargs["wheel_clicks"]}

    monkeypatch.setattr(action_api.input_controller, "scroll_window", fake_scroll_window)

    response = action_api.scroll(ScrollRequest(direction="up", wheel_clicks=2, x=40, y=50))

    assert response.success is True
    assert scrolled == {"direction": "up", "wheel_clicks": 2, "x": 40, "y": 50, "settle_ms": 100}
    result = response.data["result"]
    assert result["execution_path"]["action_executed"] is True
    assert result["post_scroll_verification"]["verified"] is True
    assert result["trace_path"].endswith("scroll.json")


def test_click_text_retries_next_candidate_when_validation_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Demo",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        ),
    )
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda roi=None, save_image=True, **kwargs: {
            "image_path": "capture.png",
            "roi": None,
            "roi_adjusted": False,
            "window_size": {"width": 800, "height": 600},
        },
    )
    monkeypatch.setattr(
        action_api.ocr_service,
        "scan_image",
        lambda path: OCRResult(
            image_path=path,
            matches=[
                OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=10, y=20, width=20, height=20)),
                OCRTextMatch(text="Start", score=0.80, bbox=OCRBoundingBox(x=110, y=120, width=20, height=20)),
            ],
        ),
    )
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda roi=None, action_name=None: {"image_path": "before.png"})

    verification_results = iter([{"verified": False}, {"verified": True}])
    monkeypatch.setattr(action_api.verifier, "verify_action", lambda *args, **kwargs: next(verification_results))

    clicked_points: list[tuple[int, int]] = []

    def fake_click(x: int, y: int, **kwargs):
        clicked_points.append((x, y))
        return {"clicked": True, "window_point": {"x": x, "y": y}}

    monkeypatch.setattr(action_api.input_controller, "click_point", fake_click)
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/click_text-retry.json")

    response = action_api.click_text(ClickTextRequest(text="Start", max_retries=2))

    assert response.success is True
    assert clicked_points == [(20, 30), (120, 130)]
    assert response.data["result"]["window_point"] == {"x": 120, "y": 130}
    assert response.data["result"]["trace_path"].endswith("click_text-retry.json")
