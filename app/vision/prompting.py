from __future__ import annotations

from app.vision.schemas import ImageSize, VisionAnalyzeRequest


def build_region_analysis_prompt(req: VisionAnalyzeRequest, image_size: ImageSize) -> str:
    app_name = req.app_name or "unknown_app"
    goal = req.goal or "understand the current screenshot and prepare local learning data"
    state_hint = req.state_hint or "unknown"
    return f"""
You are analyzing a GUI screenshot for a local desktop agent runtime.

Screenshot coordinate system:
- origin is the top-left corner
- image width = {image_size.width}
- image height = {image_size.height}
- all pixel coordinates must be based on this exact resolution
- every region must use a diagonal with top-left (x1, y1) and bottom-right (x2, y2)
- x2 and y2 are the outer boundary of the region, so x2 > x1 and y2 > y1

Task:
- app_name: {app_name}
- goal: {goal}
- state_hint: {state_hint}

Return JSON only. Do not return markdown.

Required top-level schema:
{{
  "provider": "local_or_api_model_name",
  "contract_version": "vision_regions_v1",
  "image_size": {{
    "width": {image_size.width},
    "height": {image_size.height}
  }},
  "screen_summary": "one short summary of the full screenshot",
  "state_guess": "best page/state guess",
  "regions": [
    {{
      "region_id": "region_1",
      "label": "short visible name",
      "role": "nav|button|input|tab|card|list|dialog|content|panel|icon|other",
      "diagonal": {{
        "x1": 0,
        "y1": 0,
        "x2": 0,
        "y2": 0
      }},
      "description": "describe what is inside this region, what it means, and what may happen after interacting with it",
      "ocr_text": "main merged text found inside this region",
      "text_lines": ["line 1", "line 2"],
      "possible_destinations": ["possible next page", "possible popup", "possible panel"],
      "confidence": 0.0
    }}
  ],
  "targets": [],
  "observers": [],
  "notes": []
}}

Region rules:
- split the screenshot into semantically meaningful regions, not random boxes
- every important interactive area should become a region
- if a region can trigger navigation, put the likely destination into possible_destinations
- description must include both visible content and likely interaction outcome
- use concise labels, but descriptions should be explicit enough for local learning
- do not invent invisible text
- keep confidence in range 0.0 to 1.0
""".strip()
