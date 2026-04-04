# agent-gui-runtime

A local Windows-only GUI automation runtime for AI agents.

`agent-gui-runtime` is **not** a full agent. It is an execution layer that exposes stable visual and action APIs over local HTTP so an upper-layer LLM/agent can interact with desktop applications in a more controlled way.

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
- long-term memory
- multi-step autonomous reasoning
- acting as a full desktop agent by itself

In short:

> Agent -> local HTTP API -> GUI runtime -> target window

---

## MVP scope

Current MVP goals:

1. bind to a target window
2. inspect runtime state
3. capture the bound window
4. find templates inside the bound window
5. run OCR in a region of interest
6. click based on template or text
7. wait for a named scene/state

For the MVP, the project is intentionally:

- Windows only
- local-only HTTP API
- vision-first
- single-session
- no frontend
- no database
- modular but small

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

- only one active bound window/session is needed for the MVP
- all GUI operations must go through this runtime
- no ad-hoc scripts should bypass the runtime once APIs are in place

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

The MVP is organized into these layers:

### 1. API layer
Exposes local HTTP endpoints that upper-layer agents can call.

### 2. Session / window binding layer
Tracks which window is currently bound and stores runtime session state.

### 3. Screenshot layer
Captures the currently bound window or ROI.

### 4. Vision layer
Performs template matching and OCR.

### 5. Input / action layer
Dispatches GUI actions such as clicks based on structured requests.

### 6. Verification layer
Confirms whether an action produced the expected change.

This separation is intentional so the MVP can stay small while still being extensible.

---

## Current project structure

```text
agent-gui-runtime/
├─ app/
│  ├─ api/
│  │  ├─ session.py
│  │  ├─ state.py
│  │  ├─ vision.py
│  │  ├─ action.py
│  │  └─ wait.py
│  ├─ core/
│  │  ├─ window_manager.py
│  │  ├─ screenshot.py
│  │  ├─ template_matcher.py
│  │  ├─ ocr_engine.py
│  │  ├─ input_controller.py
│  │  ├─ scene_detector.py
│  │  └─ verifier.py
│  ├─ models/
│  │  ├─ request.py
│  │  └─ response.py
│  └─ main.py
├─ configs/
│  ├─ templates/
│  ├─ rois/
│  └─ scenes/
├─ logs/
├─ pyproject.toml
└─ README.md
```

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
- small MVP before advanced abstraction
- clear layering between perception, action, and verification

---

## Current implementation status

### Already working

- FastAPI app bootstraps correctly
- routers are registered
- Swagger UI is available at `/docs`
- OpenAPI schema is generated
- all current endpoints return structured JSON
- project skeleton is stable enough for iterative development

### Already scaffolded

Endpoints currently present:

- `POST /session/bind_window`
- `GET /state`
- `POST /vision/find_template`
- `POST /vision/ocr_region`
- `POST /action/click_template`
- `POST /action/click_text`
- `POST /wait/scene`
- `GET /health`

### Not implemented yet

The current build is still an execution framework skeleton.

Real logic still needs to be added for:

- real window binding
- real screenshot capture
- template matching
- OCR integration
- GUI click/input dispatch
- scene detection and waiting
- post-action verification

---

## Development roadmap

### Phase 1 — first real capability

Priority order:

1. real `bind_window`
2. real `get_state`
3. real `capture_window`

Milestone:

> Agent -> bind_window -> capture_window -> can see the target window

### Phase 2 — first closed loop

4. `find_template`
5. `click_template`

Milestone:

> Agent can locate a stable visual target and perform a validated click

### Phase 3 — text-aware interaction

6. `ocr_region`
7. `click_text`
8. `wait_for_scene`

Milestone:

> Agent can use OCR-driven interaction and basic state transitions

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

### 3. Open docs

- Swagger UI: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>

---

## Development notes

- Keep the MVP small and working.
- Do not over-engineer multi-session or config systems yet.
- Prefer shipping real vertical slices over adding too many abstractions.
- Add technical details to this README incrementally as real functionality lands.

This README is expected to evolve together with the implementation.
