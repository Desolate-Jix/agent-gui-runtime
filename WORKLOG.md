# WORKLOG

## 2026-04-21

### Summary

This session turned the recent vision/learning work from a draft contract into a partially verified runtime slice:

- OCR is now usable again through a RapidOCR-first adapter with PaddleOCR fallback
- screenshot understanding now has a code-defined `vision_regions_v1` contract
- normalized region results now persist local learning artifacts:
  - full annotated screenshot
  - per-region crops
  - per-region annotated crops
  - `regions.json` manifest
- the next agent-facing abstraction was clarified and documented as `page_structure_v1`

### What changed

#### OCR runtime

- replaced the single-backend OCR assumption with a fallback chain in `app/core/ocr_service.py`
- added support for both:
  - Paddle-style OCR rows: `[polygon, [text, score]]`
  - RapidOCR rows: `[polygon, text, score]`
- fixed a parsing bug where OCR result parsing could collapse to only the first row
- added `rapidocr-onnxruntime` to project dependencies

#### Vision region contract

- added region-level schema fields in `app/vision/schemas.py`
- added deterministic region normalization helpers in `app/vision/region_standard.py`
- added model-facing output instructions in `app/vision/prompting.py`
- updated `app/vision/normalizer.py` so provider output can be normalized into:
  - image size
  - diagonal coordinates
  - normalized coordinates
  - `layout_key`
  - `content_key`
  - `match_key`

#### Local learning artifacts

- added `app/vision/artifacts.py`
- `/vision/analyze` now saves local evidence bundles under `logs/vision-regions/`
- each bundle contains:
  - one full annotated image
  - one crop per region
  - one annotated crop per region
  - one `regions.json` manifest

#### Architecture/documentation direction

- documented the intended next abstraction as `page_structure_v1`
- clarified the desired flow:

`screenshot -> vision_regions_v1 -> local learning artifacts -> page_structure_v1 -> agent decision`

### Validation completed

#### OCR validation

Real OCR run succeeded against:

- `logs/capture-20260413-163327-800177.png`

Observed result:

- engine used: `rapidocr_onnxruntime`
- recognized match count: `17`
- recognized texts included:
  - `https://mousetester.net/zh`
  - `MouseTester`
  - `功能特点`
  - `使用说明`
  - `常见问题`

#### Region artifact validation

A real artifact bundle was written to:

- `logs/vision-regions/20260421-201148-876757-capture-20260413-163327-800177/`

Bundle contents verified:

- full annotated screenshot
- `hero_primary_cta` crop + annotated crop
- `site_top_nav` crop + annotated crop
- `regions.json`

#### Test validation

Full test suite passed during this session:

- `24 passed in 1.43s`

Additional targeted test coverage was added for:

- OCR fallback and RapidOCR parsing
- region normalization and prompt contract
- region artifact writing
- `/vision/analyze` artifact metadata wiring

### Key decisions captured

- the agent should not consume raw OCR or raw region geometry as its primary decision input
- learned `regions` are the evidence layer
- `page_structure_v1` should be the agent-facing decision layer
- artifact persistence is required so local learning can bind saved image evidence to `match_key`

### Remaining follow-up

- implement a real `page_structure_v1` builder on top of normalized regions
- connect a real vision model backend to emit `vision_regions_v1`
- decide how learned `match_key` values map into higher-level page or section identity

