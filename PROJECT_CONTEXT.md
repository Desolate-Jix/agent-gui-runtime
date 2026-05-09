# PROJECT_CONTEXT

## Mission

Build a Windows UI automation runtime that lets AI operate desktop or browser applications through:

- visual understanding
- reusable local action logic
- deterministic click execution
- post-action verification

The target operating loop is:

`Vision -> Learn -> Recall -> Execute -> Verify -> Update`

## Migration Context

This project started in an OpenClaw-centered workflow, but OpenClaw runtime stability, auth complexity, and agent/session confusion made it unsuitable as the long-term execution host.

The new target is a Codex-maintained repository that keeps:

- OCR-driven interaction
- click-by-text behavior
- region-based click fallbacks
- verification logic
- explicit documentation as the source of truth

## Current Reality

The current repo has moved past the initial recovery/refactor stage and now has a verified no-click recognition MVP slice:

- region click and diff-based verification still exist
- MouseTester remains the main proven action path
- unified vision provider plumbing exists, and the local provider can call an OpenAI-compatible Qwen3-VL-style multimodal endpoint
- OCR/click_text behavior has been restored around RapidOCR-first OCR contracts
- `page_structure_v1` now fuses Qwen semantic regions and OCR boxes into executable element candidates
- `POST /vision/recognition_plan` now runs parse -> candidate ranking -> local grounding -> pre-click decision without executing a click
- recognition-plan overlays can be rendered for human inspection under `artifacts/review-overlays/`
- the latest MouseTester no-click run selected `点击此处测试`, refined the candidate bbox to that text line, matched local OCR, and passed pre-click verification
- the current verified suite is `61 passed`

So the migration is no longer only recovering stable pieces; the current phase is turning the staged recognition plan into a safe execution loop with measurable post-click verification.

## Codex Working Assumption

Documentation in this repo is the durable source of context.

There is no trusted hidden memory layer.
