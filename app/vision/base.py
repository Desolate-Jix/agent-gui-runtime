from __future__ import annotations

from typing import Protocol

from app.vision.schemas import VisionAnalyzeRequest, VisionAnalyzeResponse


class VisionProvider(Protocol):
    def analyze(self, req: VisionAnalyzeRequest) -> VisionAnalyzeResponse:
        ...
