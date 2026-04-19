from __future__ import annotations

from types import SimpleNamespace

from app.api import action as action_api
from app.models.request import ClickTextRequest, ROIModel
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
        lambda roi=None, save_image=True: {
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
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda roi=None: {"image_path": "before.png"})
    monkeypatch.setattr(action_api.verifier, "verify_action", lambda *args, **kwargs: {"verified": True})

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
        lambda roi=None, save_image=True: {
            "image_path": "capture.png",
            "roi": None,
            "roi_adjusted": False,
            "window_size": {"width": 800, "height": 600},
        },
    )
    monkeypatch.setattr(action_api.ocr_service, "scan_image", lambda path: OCRResult(image_path=path, matches=[]))

    response = action_api.click_text(ClickTextRequest(text="Missing"))

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "text_not_found"


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
        lambda roi=None, save_image=True: {
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
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda roi=None: {"image_path": "before.png"})

    verification_results = iter([{"verified": False}, {"verified": True}])
    monkeypatch.setattr(action_api.verifier, "verify_action", lambda *args, **kwargs: next(verification_results))

    clicked_points: list[tuple[int, int]] = []

    def fake_click(x: int, y: int, **kwargs):
        clicked_points.append((x, y))
        return {"clicked": True, "window_point": {"x": x, "y": y}}

    monkeypatch.setattr(action_api.input_controller, "click_point", fake_click)

    response = action_api.click_text(ClickTextRequest(text="Start", max_retries=2))

    assert response.success is True
    assert clicked_points == [(20, 30), (120, 130)]
    assert response.data["result"]["window_point"] == {"x": 120, "y": 130}
