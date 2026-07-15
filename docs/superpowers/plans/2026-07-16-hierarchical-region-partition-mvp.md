# Hierarchical Region Partition MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run an isolated, read-only evaluator that organizes existing anonymous GUI candidates into a validated two-level region tree with usable crops.

**Architecture:** A pure experiment module owns candidate normalization, model-output validation, geometry, query, overlays and crops. A CLI loads fixed evidence, performs at most one 8B call per sample, and writes a comparison report without importing the production Stage1 bar classifier.

**Tech Stack:** Python 3.11, Pillow, existing local vision provider/API contracts, pytest.

## Global Constraints

- Keep `bar_detection_v1`, Execute, PathGraph and safety gates unchanged.
- Do not add application-specific coordinates or rules.
- Model output references candidate IDs and never supplies final bbox.
- Maximum hierarchy depth is 2; main evaluation uses no repair prompt.
- All actions are read-only and no-click.

---

### Task 1: Geometry, validator and frame-local region index

**Files:**
- Create: `app/learn/experiments/__init__.py`
- Create: `app/learn/experiments/hierarchical_region_partition.py`
- Create: `tests/test_hierarchical_region_partition_mvp.py`

**Interfaces:**
- `build_anonymous_candidates(items, image_size) -> list[dict]`
- `compile_hierarchical_regions(model_payload, candidates, image_size) -> dict`
- `RegionFrame.get_region/get_region_children/crop_region`

- [ ] Write tests for valid parent/child union, invalid references, disconnected union, overlap and crop.
- [ ] Run the tests and confirm they fail because the module is absent.
- [ ] Implement the minimal module.
- [ ] Run the tests until green.

### Task 2: One-shot evaluator and artifacts

**Files:**
- Create: `scripts/eval_hierarchical_region_partition_mvp.py`
- Modify: `tests/test_hierarchical_region_partition_mvp.py`

**Interfaces:**
- CLI accepts `--case-manifest`, `--out`, `--model-profile`, `--offline-model-output`.
- Report writes raw/parsed model output, candidate and region overlays, crops, validator and comparison JSON.

- [ ] Write a failing CLI fixture test.
- [ ] Implement candidate overlay, one-call model adapter and report writer.
- [ ] Verify an offline fixture run.

### Task 3: Fixed screenshot shadow evaluation

**Files:**
- Create locally under ignored output: `logs/region_partition_mvp/<run_id>/...`
- Update: `CURRENT_STATE.md` and `NEXT_STEPS.md` with evidence-based conclusion.

- [ ] Select saved Steam, WhatsApp, Apple Music, Notepad and one known-good multi-column sample.
- [ ] Run one 8B organization call per valid sample.
- [ ] Generate crops and comparison table.
- [ ] Run focused regressions proving production Stage1 remains unchanged.
- [ ] Record whether the direction is better, inconclusive or worse.

