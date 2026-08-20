# Agent-Readable Peer Card Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a geometry-free Agent-readable inventory from current Stage2 same-class card evidence.

**Architecture:** Add one focused projection module after layout review enhancement. Attach its read-only result to Stage2 and surface a summary in the existing offline class-rule demo.

**Tech Stack:** Python 3.11, pytest, existing Learn Mode Stage2 and Surface Adapter contracts.

## Global Constraints

- Do not change Execute, Gate, Runtime PathGraph, final-submit policy, or real action behavior.
- Class priors are advisory and cannot create an item without current screenshot evidence.
- Agent-facing output must not contain bbox, click point, or executable selector.
- All artifacts remain review-only and non-authorizing.

---

### Task 1: Peer-card inventory projector

**Files:**
- Create: `app/learn/recognition/peer_card_inventory.py`
- Create: `tests/test_peer_card_inventory.py`

**Interfaces:**
- Consumes: `numbered_regions: list[dict[str, Any]]`, `stage2_policy: dict[str, Any] | None`
- Produces: `build_agent_peer_card_inventory(...) -> dict[str, Any]`

- [ ] Write failing tests for current-evidence projection, geometry stripping, action gating, duplicates, and not-covered behavior.
- [ ] Run `uv run pytest tests/test_peer_card_inventory.py -q` and confirm failures are caused by the missing module.
- [ ] Implement the minimal geometry-free projector.
- [ ] Rerun the focused test until it passes.

### Task 2: Stage2 integration

**Files:**
- Modify: `app/learn/recognition/two_stage.py`
- Modify: `tests/test_learn_recognition_pipeline.py`

**Interfaces:**
- Consumes: enhanced Stage2 regions and Surface Adapter Stage2 policy.
- Produces: `stage2_numbering.agent_peer_card_inventory`.

- [ ] Add a failing pipeline assertion.
- [ ] Run the exact test and confirm the missing field failure.
- [ ] Attach the projection after layout enhancement without changing geometry.
- [ ] Rerun the pipeline test.

### Task 3: Agent evidence and cross-site replay

**Files:**
- Modify: `scripts/run_interface_class_rule_demo.py`
- Modify: `tests/test_interface_class_rule_demo.py`

**Interfaces:**
- Consumes: `stage2_numbering.agent_peer_card_inventory`
- Produces: `decision_support.peer_card_inventory`.

- [ ] Add a failing Agent-evidence contract test.
- [ ] Run it and confirm the missing projection failure.
- [ ] Add the geometry-free inventory summary to demo Agent evidence.
- [ ] Run focused tests and the five-site offline replay.

### Task 4: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Modify: `ARCHITECTURE.md`

- [ ] Document the new evidence contract and its non-authorization boundary.
- [ ] Run focused tests and Python compilation.
- [ ] Run `uv run pytest tests -q`.
- [ ] Report replay evidence without calling it recognition accuracy or live Agent reliability.

