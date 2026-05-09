from __future__ import annotations

from app.vision.schemas import ImageSize, VisionAnalyzeRequest


def build_region_analysis_prompt(
    req: VisionAnalyzeRequest,
    image_size: ImageSize,
    *,
    compact: bool = False,
    max_regions: int = 8,
    grid_overlay_spacing: int | None = None,
) -> str:
    app_name = req.app_name or "unknown_app"
    goal = req.goal or "understand the current screenshot and prepare local learning data"
    state_hint = req.state_hint or "unknown"
    compact_rules = ""
    if compact:
        compact_rules = """
- compact mode is active because the screenshot is large or a previous response was truncated
- return at most 6 regions and merge nearby cards when possible
- keep screen_summary and state_guess under 12 words each
- keep description under 8 words
- keep ocr_text under 12 words; use an empty string when the text is too long or noisy
- keep text_lines to at most 2 short items
- keep possible_destinations empty unless one destination is obvious
""".rstrip()
    grid_rules = ""
    if grid_overlay_spacing is not None and grid_overlay_spacing > 0:
        grid_rules = f"""
- the screenshot includes a light coordinate grid with pixel tick labels
- major grid spacing is {int(grid_overlay_spacing)} pixels
- first estimate each bbox edge against the nearest visible grid lines and tick labels
- then convert that estimate back into exact screenshot pixel coordinates
- prefer tight boxes around the visible module itself, not loose outer whitespace containers
- if an edge is unclear, anchor it to the nearest plausible grid reference instead of guessing a shifted box
- report coordinates against the original screenshot pixels, not grid cell indexes
""".rstrip()
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

Required JSON shape:
- top-level keys: provider, contract_version, image_size, screen_summary, state_guess, regions, targets, observers, notes
- contract_version must be "vision_regions_v1"
- image_size must be {{"width": {image_size.width}, "height": {image_size.height}}}
- each region must include: region_id, label, role, diagonal, description, ocr_text, text_lines, possible_destinations, confidence
- role must be one of: nav, button, input, tab, card, list, dialog, content, panel, icon, other
- diagonal must be an object with integer keys x1, y1, x2, y2

Region rules:
- split the screenshot into semantically meaningful regions, not random boxes
- every important interactive area should become a region
- if a region can trigger navigation, put the likely destination into possible_destinations
- description must include both visible content and likely interaction outcome
- use concise labels, but descriptions should be explicit enough for local learning
- do not invent invisible text
- keep confidence in range 0.0 to 1.0
- return at most {max_regions} regions
- keep each description to one short sentence with at most 18 words
- keep label short, ideally 2 to 4 words
- keep text_lines to at most 4 items
- keep possible_destinations to at most 1 short item unless truly necessary
- if multiple promo cards or download recommendations appear together, merge them into one broader ad/promo region
- obvious advertisement, recommendation, download, or promo areas should prefer role = card or content, not button
- only use role = button when the region is a meaningful action target for the user task
{compact_rules}
{grid_rules}
""".strip()
