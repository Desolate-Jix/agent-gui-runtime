from __future__ import annotations

from pathlib import Path

from app.vision.schemas import VisionAnalyzeRequest, VisionAnalyzeResponse


class LocalVisionProvider:
    def __init__(self, endpoint: str | None = None, model_name: str | None = None) -> None:
        self.endpoint = endpoint
        self.model_name = model_name or "local_stub"

    def analyze(self, req: VisionAnalyzeRequest) -> VisionAnalyzeResponse:
        image_path = Path(req.image_path)
        notes: list[str] = []
        if self.endpoint:
            notes.append(f"Local provider endpoint configured but not yet invoked: {self.endpoint}")
        else:
            notes.append("Local provider is currently running in stub mode.")
        return VisionAnalyzeResponse(
            provider="local",
            screen_summary=f"Local provider stub analyzed image: {image_path.name}",
            state_guess=req.state_hint,
            targets=[],
            observers=[],
            notes=notes,
            raw_text=None,
            raw_response={
                "provider": "local",
                "model_name": self.model_name,
                "image_path": str(image_path),
                "task": req.task,
                "goal": req.goal,
                "app_name": req.app_name,
                "state_hint": req.state_hint,
                "mode": "stub",
            },
        )
