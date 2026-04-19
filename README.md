# agent-gui-runtime

A local Windows-only GUI automation runtime for AI agents.

`agent-gui-runtime` is **not** a full agent. It is an execution layer that exposes stable visual and action APIs over local HTTP so an upper-layer LLM/agent can interact with desktop applications in a more controlled way.

## Maintenance workflow

When code changes affect runtime behavior, API shape, architecture, or current progress, update the docs in the same work session.

Expected sync targets:

- `README.md`
- `PROJECT_CONTEXT.md`
- `RULES.md`
- `KNOWLEDGE_BASE.md`
- `PROJECT_SUMMARY.md`
- `ARCHITECTURE.md`
- `CURRENT_STATE.md`
- `NEXT_STEPS.md`

When implementing code, follow the execution loop in `skills/code-implementation-loop/SKILL.md`: make the smallest useful change, run the narrowest meaningful verification, inspect results, fix failures, and rerun until the path is verified or a real blocker remains.

---

## Project positioning

This project is designed as a **GUI execution runtime** rather than a planning or reasoning system.

It is responsible for:

- binding to a target window/session
- capturing the bound window
- running vision operations such as template matching and OCR
- dispatching controlled GUI actions
- validating execution results
- returning structured JSON responses to an upper-layer agent

It is **not** responsible for:

- natural language task planning
- becoming a full desktop agent by itself
- unrestricted autonomous exploration of unknown software

It now also includes an early **software-specific state memory layer** for known apps/pages, but that layer is still subordinate to the runtime role: it helps the execution layer recognize known states, reuse known action targets, and record transitions. It is not a general reasoning or planning system.

In short:

> Agent -> local HTTP API -> GUI runtime -> target window

---

## Runtime model

This runtime now has **two complementary execution modes**.

### 1. Generic visual execution

The original runtime model:

- bind a window
- capture the window or ROI
- run OCR/template matching
- click or verify
- return structured results

This is still the compatibility baseline.

### 2. Software-specific state-aware execution (V1)

A new V1 layer has been added for known software/layouts.

This layer can:

- recognize whether the current screen matches a known `AppState`
- load known `ActionTarget` definitions for that state
- prefer historically successful click strategies
- record `TransitionRecord` and `ReplayCase` artifacts after execution
- preserve validator-based closed-loop verification
- fall back to existing `region_click` behavior if state-aware reuse is not enough

Important V1 scope boundaries:

- it does **not** do blind exploration in unknown states
- it does **not** try to autonomously learn every clickable target in arbitrary software
- it does **not** use LLM visual reasoning inside the runtime
- it is intentionally conservative: unknown recognition should return `unknown`, not a forced guess

---

## MVP / V1 scope

### Baseline runtime goals

1. bind to a target window
2. inspect runtime state
3. capture the bound window
4. find templates inside the bound window
5. run OCR in a region of interest
6. click based on template or text
7. wait for a named scene/state

### Current state-aware V1 goals

1. recognize a known app state for a known software/layout
2. load known action targets for that state
3. prefer history-backed click reuse
4. preserve validator closed loop
5. record state transition experience
6. keep generic `region_click` as fallback

For the current phase, the project is intentionally:

- Windows only
- local-only HTTP API
- vision-first
- single-session
- no frontend
- file-based persistence under `logs/`
- software-specific before software-general

---

## Environment

### Target platform

- **OS:** Windows only
- **Python:** 3.11
- **Runtime style:** local FastAPI service
- **Package/dependency management:** `uv`

### Recommended development environment

- Windows 10 / Windows 11
- Python 3.11 installed
- `uv` installed
- a desktop application window available for local testing

### Current working assumptions

- only one active bound window/session is needed for the MVP/V1
- all GUI operations should go through this runtime
- no ad-hoc scripts should bypass the runtime once APIs are in place
- software-specific memory is file-based and local-first in the current phase

---

## Tech stack

### Core framework

- **FastAPI** — local HTTP API service
- **Pydantic v2** — structured request/response models
- **Uvicorn** — ASGI server
- **loguru** — runtime logging

### Windows GUI automation

- **pywinauto** — window discovery and control primitives
- **pywin32** — lower-level Windows API integration

### Vision and image processing

- **mss** — screenshot capture
- **opencv-python** — template matching and image utilities
- **numpy** — image array operations
- **Pillow** — image helpers and conversions
- **PaddleOCR** — OCR engine for text recognition

### Tooling

- **uv** — virtual environment and dependency management

---

## High-level architecture

The runtime is now organized into these layers:

### 1. API layer
Exposes local HTTP endpoints that upper-layer agents can call.

### 2. Session / window binding layer
Tracks which window is currently bound and stores runtime session state.

### 3. Screenshot layer
Captures the currently bound window or ROI.

### 4. Vision layer
Performs template matching, OCR, page fingerprinting, and ROI comparison.

### 5. Input / action layer
Dispatches GUI actions such as clicks based on structured requests.

### 6. Verification layer
Confirms whether an action produced the expected change.

### 7. State-aware memory layer (V1)
Stores known states, known action targets, validator profiles, replay cases, and transition history for specific software/layouts.

This separation is intentional so the runtime can stay small while still being extensible.

---

## Current project structure

```text
agent-gui-runtime/
├─ modules/
│  ├─ ocr/
│  ├─ click/
│  ├─ region/
│  └─ validation/
├─ tests/
├─ app/
│  ├─ actions/
│  │  └─ known_action_runner.py
│  ├─ api/
│  │  ├─ session.py
│  │  ├─ state.py
│  │  ├─ vision.py
│  │  └─ action.py
│  ├─ core/
│  │  ├─ window_manager.py
│  │  ├─ screenshot.py
│  │  ├─ ocr_service.py
│  │  ├─ input_controller.py
│  │  ├─ verifier.py
│  │  ├─ action_registry.py
│  │  └─ replay_case_store.py
│  ├─ models/
│  │  ├─ request.py
│  │  └─ response.py
│  ├─ schemas/
│  ├─ vision/
│  ├─ vision_protocol/
│  └─ main.py
├─ configs/
├─ logs/
│  ├─ app-states/
│  ├─ app-actions/
│  ├─ app-transitions/
│  ├─ replay-cases/
│  ├─ state-recognition/
│  ├─ region-click-cache/
│  └─ region-click-cases/
├─ PROJECT_CONTEXT.md
├─ RULES.md
├─ KNOWLEDGE_BASE.md
├─ pyproject.toml
└─ README.md
```

For a detailed folder-by-folder map, feature-to-file ownership, config locations, and persistence paths, see `PROJECT_STRUCTURE.md`.

---

## API design principles

The runtime uses a unified JSON envelope for endpoint responses:

```json
{
  "success": true,
  "message": "...",
  "data": {},
  "error": null
}
```

Design principles:

- stable interfaces over raw scripts
- structured JSON over unstructured console output
- vision-first interaction model
- closed-loop verification over blind clicking
- conservative state recognition over forced guesses
- keep generic execution working while layering state-aware reuse on top

---

## Region click model

The current non-text click path is no longer purely OCR-anchor driven.

The runtime now supports a **region-anchored click** flow for known UI layouts:

1. locate a panel
2. resolve a target zone inside that panel
3. generate candidate points (grid / preferred memory-backed point)
4. dispatch click via `SendInput`
5. observe before/after state
6. evaluate strict / weak success
7. cache successful click point geometry
8. persist replay/debug case artifacts

This path remains the baseline execution primitive underneath the new state-aware V1 layer.

---

## State-aware memory model (V1)

The new V1 memory layer introduces five persisted object types.

### AppState
Represents a known screen/page/state for a specific app and window-size bucket.

### ActionTarget
Represents a known action target inside a known state.

### ValidatorProfile
Defines how a target should be verified, including target ROI, OCR ROI, and scoring rules.

### TransitionRecord
Stores a recorded transition such as:

> state A + action B -> state C

### ReplayCase
Stores replay/debug artifacts for a concrete execution attempt.

Persistence is currently file-based under `logs/`.

---

## Recognition strategy (current V1)

The current recognizer is intentionally conservative.

It uses a lightweight three-stage strategy:

1. `window_size_bucket` filtering
2. `thumbnail_hash` coarse matching
3. anchor patch hit scoring

If confidence is insufficient, the recognizer should return `unknown` rather than force a match.

This is deliberate: a false positive state match is often worse than no match.

---

## Validation strategy (current V1)

Validation is moving from large noisy OCR-only checks toward **local target validation**.

Current direction:

- separate `target_roi` from `ocr_roi`
- run OCR only on a smaller localized ROI when configured
- include ROI diff evidence
- compute `strict_score` in addition to `strict_success` / `weak_success`

The long-term goal is a more stable validator based on:

- target ROI
- localized OCR
- local diff
- structured success scoring

This is especially important for noisy numeric counters such as MouseTester.

---

## Current implementation status

### Working / verified in the current codebase

- FastAPI app imports successfully in the project `.venv`
- routers are registered
- `modules/` boundaries now exist for `ocr`, `click`, `region`, and `validation`
- pytest coverage now exists for OCR matching, click geometry, region geometry, validator logic, `click_text`, and state-hint persistence
- `/vision/ocr_region` is restored on top of a PaddleOCR-backed adapter
- `/action/click_text` is restored with OCR matching, ROI-aware coordinate translation, and retry-based fallback
- `/action/click_mouse_tester_left_region` remains the main action entrypoint
- schema + storage layer objects can be written and read back
- state-aware action wiring exists for MouseTester

### State-aware components already added

- `AppState`
- `ActionTarget`
- `ValidatorProfile`
- `TransitionRecord`
- `ReplayCase`
- `state_memory`
- `action_registry`
- `transition_memory`
- `replay_case_store`
- `page_fingerprint`
- `state_recognizer`
- `known_action_runner`

### MouseTester integration status

The first state-aware action path has been wired into:

- `POST /action/click_mouse_tester_left_region`

Current behavior:

- ensure known MouseTester state/action/validator assets exist
- recognize state before action
- run known action using region click
- recognize state after action
- persist replay case and transition artifacts
- keep fallback strategy available

A second alternate action target has also been added for the same known state so the V1 system can try a fallback target profile rather than only a single hardcoded region.

### Not complete yet

The remaining high-value work is end-to-end runtime verification with a real bound target window:

1. bind real MouseTester window
2. execute both `click_text` and state-aware region-click against a live target
3. confirm automatic bootstrap of persisted state/action/validator files
4. confirm transition and replay-case persistence after real execution
5. continue strengthening validator stability
6. replace the stub `/vision/analyze` providers with at least one real backend

---

## Runtime endpoints

### Core runtime endpoints

- `POST /session/bind_window`
- `GET /session/windows`
- `GET /state`
- `POST /state/capture_window`
- `POST /vision/ocr_region`
- `POST /vision/analyze`
- `POST /action/click_text`
- `POST /action/click_mouse_tester_left_region`
- `GET /health`

---

## Development roadmap

### Phase 1 — first real capability

1. real `bind_window`
2. real `get_state`
3. real `capture_window`

Milestone:

> Agent -> bind_window -> capture_window -> can see the target window

### Phase 2 — first closed loop

4. `ocr_region`
5. `click_text`

Milestone:

> Agent can locate text in a target window and perform a validated click

### Phase 3 — region-aware interaction

6. reusable `region_click`
7. point memory cache
8. replay/debug case persistence

Milestone:

> Agent can act on non-text UI targets using panel-relative geometry and closed-loop validation

### Phase 4 — software-specific state-aware V1

9. known `AppState` recognition
10. known `ActionTarget` reuse
11. `TransitionRecord` persistence
12. `ReplayCase` persistence
13. validator-profile-driven local verification
14. fallback from known target profile to compatible region-click behavior

Milestone:

> Agent can recognize a known software state, reuse learned action targets, remember transitions, and keep action verification in the loop

---

## How to run

### 1. Create venv and install dependencies

```bash
uv venv
uv sync
```

### 2. Start the server

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

For cleaner single-instance debugging, a non-`--reload` run is often preferable once the code path under test is known.

### 3. Open docs

- Swagger UI: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>

---

## Minimal state-aware test flow

A practical current test flow for MouseTester is:

1. open the target app/window
2. call `GET /session/windows`
3. bind the correct target with `POST /session/bind_window`
4. call `POST /vision/ocr_region` or `POST /action/click_text`
5. call `POST /action/click_mouse_tester_left_region`
6. inspect persisted artifacts under `logs/`

---

## Development notes

- Keep the runtime small and working.
- Do not over-engineer software-general learning before state-specific reuse works.
- Prefer verified vertical slices over speculative abstraction.
- Preserve compatibility with the existing screenshot/OCR/region-click execution model while layering software-specific state memory on top.
- Continue evolving this README together with the implementation.
