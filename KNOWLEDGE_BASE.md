# KNOWLEDGE_BASE

## Recovered Design Intent

The intended system behavior from prior work was:

- use OCR to understand the visible UI
- click specific text when that is reliable
- fall back to region-based clicking when text anchors are insufficient
- verify that the click actually changed the UI
- reuse successful local behavior instead of asking an LLM every time

## Stable Concepts

### OCR

Originally backed by PaddleOCR with:

- recognized text
- confidence scores
- bounding boxes

Current repo status:

- OCR contracts are module boundaries
- `app/core/ocr_service.py` uses RapidOCR first with PaddleOCR fallback
- OCR boxes now feed `page_structure_v1` fusion as the precise text-coordinate source

### click_text

Original intended flow:

`capture -> OCR -> find text -> bbox center -> click`

Current repo status:

- `POST /action/click_text` is restored on top of the OCR contracts
- route-level tests cover ROI offset handling, text-not-found behavior, and retry fallback

### page_structure_v1

Current intended flow:

`vision_regions_v1 + OCRResult -> deterministic fusion -> page_structure_v1`

This layer keeps:

- Qwen semantic regions for meaning, role, likely destination, and layout memory
- OCR text boxes for precise text grounding and click points
- links between semantic regions, OCR boxes, and generated elements
- verification hints for the later closed-loop validator
- memory keys for local learning of successful click strategies

### region_click

This is the strongest surviving concept in the current codebase.

It is built around:

- panel locator
- zone resolver
- point strategy
- validator

and uses multiple candidate points inside a target region to avoid brittle single-point clicks.

### verification

Verification remains a core requirement.

Current repo still supports:

- before/after screenshot capture
- ROI diff detection
- cursor/focus evidence

Counter-based OCR verification exists conceptually and is preserved as pure validation logic in modules.

## Known OpenClaw Failure Modes

- active session pointer drifted to a broken session
- `openai-codex` auth resolution failed in the later session
- memory search had no ready embedding provider
- semantic recall was therefore not reliable

Conclusion:

- do not depend on OpenClaw-style runtime memory for project continuity

## Current Migration Priority

1. keep the runtime importable and testable
2. move stable logic into `modules/`
3. reintroduce OCR/click_text on explicit boundaries
4. add tests before widening the API surface again
