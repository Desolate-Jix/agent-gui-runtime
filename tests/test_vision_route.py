from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def test_vision_analyze_returns_artifact_metadata(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (120, 80), color=(255, 255, 255)).save(image_path)

    class DummyProvider:
        def analyze(self, req):
            from app.vision.schemas import ImageSize, VisionAnalyzeResponse

            return VisionAnalyzeResponse(
                provider="dummy",
                screen_summary="dummy page",
                state_guess="dummy_state",
                image_size=ImageSize(width=120, height=80),
                regions=[],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr(
        "app.api.vision.save_region_artifacts",
        lambda image_path, response: {
            "bundle_dir": str(tmp_path / "bundle"),
            "annotated_image_path": str(tmp_path / "bundle" / "annotated.png"),
            "manifest_path": str(tmp_path / "bundle" / "regions.json"),
            "region_count": 0,
            "regions": [],
        },
    )

    client = TestClient(app)
    response = client.post(
        "/vision/analyze",
        json={
            "image_path": str(image_path),
            "task": "analyze_ui",
            "app_name": "demo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert "artifacts" in result
    assert result["artifacts"]["region_count"] == 0
