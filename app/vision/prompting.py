from __future__ import annotations

import json

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
    ocr_anchor_rules = _ocr_anchor_rules(req)
    custom_rules = _custom_prompt_rules(req)
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
- each region must include: region_id, label, role, diagonal, description, ocr_text, text_lines, possible_destinations, anchor_relations, grounding_constraints, confidence
- role must be one of: nav, button, input, tab, card, list, dialog, content, panel, icon, other
- diagonal must be an object with integer keys x1, y1, x2, y2
- anchor_relations must be a list of relation evidence objects; include anchor_id, text, relation, axis, target_edge, anchor_edge, gap_px, overlap_ratio, confidence, evidence when known
- grounding_constraints must be an object with reference_frame, text_inclusion_policy, text_anchor_frame, relative_frame_position, edge_constraints, center_constraints, size_constraints, negative_constraints, final_bbox_reason

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
- before finalizing a region diagonal, build a coordinate grounding chain from visible pixels and nearby OCR anchors
- first define the reference_frame: the smallest visible screen area, card, module, panel, or crop that contains the object
- then build a text_anchor_frame from the nearest OCR text boxes around the object: choose nearest top, bottom, left, and right text anchors when they exist, and imagine boundary lines along the closest text-box edges
- for text-adjacent visual objects, anchor_relations should name the anchors and precise geometry: above/below/left_of/right_of, same_row, same_column, center_aligned_x, center_aligned_y, between, inside, contains, boundary_top, boundary_bottom, boundary_left, boundary_right, or exclusion
- grounding_constraints.text_anchor_frame must include the selected top_anchor_id, bottom_anchor_id, left_anchor_id, right_anchor_id when known, plus frame_bbox or boundary_lines estimated from those text boxes
- grounding_constraints.relative_frame_position must explain where the visual object sits inside that text_anchor_frame using center_fraction_x, center_fraction_y, width_fraction, height_fraction, and frame_zone when possible
- Case A, visual icon/object has no text inside it: set text_inclusion_policy = "exclude_text"; the final diagonal must tightly cover only the visual pixels and must not include OCR text boxes. Use nearby text only as boundary lines, negative constraints, or alignment evidence.
- Case B, the target visually includes text or the text is part of the button/icon label: set text_inclusion_policy = "include_referenced_text"; the final diagonal must include the referenced OCR text boxes with the visible object. Cite those anchor_ids in anchor_relations and edge_constraints.
- use edge_constraints to justify each bbox edge: top, bottom, left, and right should cite visual edges or anchor ids with relation, estimated gap_px, and confidence
- use center_constraints when labels or symmetric anchors imply alignment; use size_constraints for expected aspect ratio or visible object size
- use negative_constraints for text anchors or neighboring widgets that the visual bbox must not include
- if a visual object has no useful OCR anchor, set anchor_relations to [] and say in description that it is visual-only
- do not let a text anchor become the visual object's bbox unless the target itself is text
{compact_rules}
{grid_rules}
{ocr_anchor_rules}
{custom_rules}
""".strip()


def _ocr_anchor_rules(req: VisionAnalyzeRequest) -> str:
    metadata = req.metadata or {}
    payload = metadata.get("ocr_anchors")
    if not isinstance(payload, dict):
        return ""
    anchors = payload.get("anchors") or []
    if not isinstance(anchors, list) or not anchors:
        return ""
    compact_payload = {
        "contract_version": payload.get("contract_version") or "ocr_anchors_v1",
        "coordinate_space": payload.get("coordinate_space") or "current_image",
        "image_size": payload.get("image_size"),
        "total_detected_count": payload.get("total_detected_count") or len(anchors),
        "anchor_count": len(anchors),
        "anchor_fields": {"id": "anchor_id", "t": "text", "b": "[x,y,w,h]", "c": "[center_x,center_y]", "s": "confidence", "g": "goal_similarity"},
        "anchors": [_compact_anchor_for_prompt(anchor) for anchor in anchors],
    }
    anchor_json = json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))
    return f"""

OCR anchor hints:
- OCR has already detected high-confidence text boxes; use them as spatial anchors for nearby icons, buttons, inputs, and cards
- OCR anchors use the same coordinate system as the image you are analyzing in this prompt
- OCR anchor payload uses compact fields: id=anchor_id, t=text, b=[x,y,w,h], c=[center_x,center_y], s=confidence, g=goal_similarity
- first choose the relevant anchor_ids for each visual object, then write anchor_relations, then write grounding_constraints, then choose the bbox
- treat anchors as coordinate evidence, not as the object itself: use their bbox edges, centers, rows, columns, gaps, and exclusions
- prefer a multi-anchor system over one direction word: combine reference_frame, edge_constraints, center_constraints, size_constraints, and negative_constraints
- use the nearest OCR text boxes as boundary-line rulers: the closest text edge above/below/left/right can define a text_anchor_frame around the likely icon position
- for icons without internal text, keep text_inclusion_policy="exclude_text"; return relative_frame_position fractions that say how much of the text_anchor_frame the icon occupies and where it sits, but do not include the text boxes in the final diagonal
- for controls/icons whose visible target includes text, keep text_inclusion_policy="include_referenced_text"; the final diagonal must include the referenced text anchor bboxes plus the visible icon/control pixels
- for large illustrations above a row of labels, use the label anchors as bottom negative/edge constraints, title anchors as top context, and side/symmetric labels as center or horizontal constraints
- do not invent text that is not visible; if an anchor helps identify a visual-only icon, explain the relation in anchor_relations and description
- if the screenshot pixels and OCR anchors conflict, prefer the screenshot and keep confidence lower
- OCR anchor payload: {anchor_json}
""".rstrip()


def _compact_anchor_for_prompt(anchor: object) -> dict[str, object]:
    if not isinstance(anchor, dict):
        return {}
    bbox = anchor.get("bbox") if isinstance(anchor.get("bbox"), dict) else {}
    center = anchor.get("center") if isinstance(anchor.get("center"), dict) else {}
    return {
        "id": anchor.get("anchor_id") or anchor.get("id") or "",
        "t": anchor.get("text") or "",
        "b": [
            int((bbox or {}).get("x") or 0),
            int((bbox or {}).get("y") or 0),
            int((bbox or {}).get("w") or (bbox or {}).get("width") or 0),
            int((bbox or {}).get("h") or (bbox or {}).get("height") or 0),
        ],
        "c": [
            int((center or {}).get("x") or 0),
            int((center or {}).get("y") or 0),
        ],
        "s": anchor.get("confidence"),
        "g": anchor.get("goal_similarity"),
    }


def _custom_prompt_rules(req: VisionAnalyzeRequest) -> str:
    metadata = req.metadata or {}
    raw_overrides = metadata.get("prompt_overrides")
    if not isinstance(raw_overrides, dict):
        return ""
    additional_rules = str(raw_overrides.get("additional_rules") or "").strip()
    if not additional_rules:
        return ""
    return f"""

Additional user-configured grounding rules:
{additional_rules}
""".rstrip()
