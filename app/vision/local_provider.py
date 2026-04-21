from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.vision.prompting import build_region_analysis_prompt
from app.vision.schemas import ImageSize, VisionAnalyzeRequest, VisionAnalyzeResponse


class LocalVisionProvider:
    def __init__(self, endpoint: str | None = None, model_name: str | None = None) -> None:
        self.endpoint = endpoint
        self.model_name = model_name or "local_stub"

    def analyze(self, req: VisionAnalyzeRequest) -> VisionAnalyzeResponse:
        image_path = Path(req.image_path)
        with Image.open(image_path) as image:
            image_size = ImageSize(width=image.width, height=image.height)
        prompt = build_region_analysis_prompt(req, image_size)
        notes: list[str] = []
        if self.endpoint:
            notes.append(f"Local provider endpoint configured but not yet invoked: {self.endpoint}")
        else:
            notes.append("Local provider is currently running in stub mode.")
        return VisionAnalyzeResponse(
            provider="local",
            image_size=image_size,
            screen_summary=f"Local provider stub analyzed image: {image_path.name}",
            state_guess=req.state_hint,
            regions=[],
            targets=[],
            observers=[],
            notes=notes,
            raw_text=None,
            raw_response={
                "provider": "local",
                "contract_version": "vision_regions_v1",
                "image_size": image_size.to_dict(),
                "model_name": self.model_name,
                "image_path": str(image_path),
                "task": req.task,
                "goal": req.goal,
                "app_name": req.app_name,
                "state_hint": req.state_hint,
                "prompt_contract": prompt,
                "mode": "stub",
            },
        )
