# agent-gui-runtime

**Version 0.3.0 · Windows GUI Agent Runtime**

[中文](README.md)

Turn uncertain computer interaction into reviewed, replayable, stoppable runtime behavior. This project is not positioned as “better OCR”; it compiles learned interface evidence into semantic, freshness-bound, verifiable, recoverable workflows.

## The mainline

```text
Learn → Review → Compile → Verified Replay → Recovery
```

- **Learn**: collect screenshot, UIA, OCR, vision-model, and optional parser evidence from the current window.
- **Review**: correct boxes, page responsibilities, candidate actions, and transitions in the panel. Learning output is not authorization.
- **Compile**: turn reviewed interfaces and transitions into a workflow with semantic actions, preconditions, evidence lineage, risk levels, and verification rules.
- **Verified Replay**: capture the current UI again before every action, check window binding, coordinate space, capture identity, and the Gate, then use the shared action API.
- **Recovery**: verify the effect after an action; on drift, timeout, error, or stale evidence, stop with diagnosable state instead of blindly retrying.

## Positioning and safety boundary

This is a local Windows runtime and learning panel, not an unattended job-submission service. The default boundary is:

- Learning drafts, reviews, and runtime evidence are non-authorizing: `artifact_is_authorization=false`, `execute_binding_enabled=false`.
- `final_submit`, `send`, `confirm`, `payment`, and `delete` remain forbidden. Real clicks require current-window, candidate, confidence, `pre_click_decision_v1`, and post-action evidence.
- Low-risk navigation may be displayed or dry-run, but model output, old coordinates, or a panel button cannot bypass the current-UI Gate.
- `artifacts/`, `logs/`, `models/`, and `runtime_state/` are local runtime output or model resources, not clone-time public resources.

## What is currently verified

### SEEK Quick Apply (controlled entry path)

The controlled evidence covers **SEEK home → job detail → same-site Apply/Quick Apply entry**. It stops at the application entry: no field fill, typing, upload, Continue/Next, `Review and submit`, `Submit application`, `Send`, `Complete`, payment, or other final action. This validates reviewed replay, current-UI grounding, the Gate, and post-action verification; it does not claim ATS E2E, live safe-fill, or unattended reliability.

### Learning workspace

The panel provides one workspace for capture/understanding, numbering and calibration, human correction, evidence review, fusion, page details, and read-only PathGraph. The backend owns workflow state; the panel renders state, starts review, and presents results without reconstructing execution authorization.

Reviewed interfaces can be saved as application-scoped workflow drafts. Nodes retain source-capture identity, evidence hashes, page responsibility, candidate actions, and verification rules. Cross-capture, cross-window, or lineage-less candidates fail closed. New reviewed content is the priority; old runtime assets are not migrated.

## OmniParser status

OmniParser is an **optional learning shadow/contact-sheet provider** exposed through `screen_parser_result_v1`:

- It may add review-only element and icon-semantic hints. It does not grant click authorization and does not replace UIA, OCR, or the current-capture Gate.
- The current smoke input is a privacy-reviewed contact sheet, not proof of general UI recognition, live-window capture, or clickability.
- OmniParser source, weights, virtual environment, and dependencies are not distributed in this repository. Users who enable it must obtain the components themselves and accept their licenses; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Install and start

Requirements: Windows 10/11, Python `>=3.11,<3.12`, and [`uv`](https://docs.astral.sh/uv/).

```powershell
git clone https://github.com/Desolate-Jix/agent-gui-runtime.git
cd agent-gui-runtime
uv sync
.\start_test_panel.bat
```

The launcher reuses or selects a local port and opens the panel. Manual startup is also available:

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Optional local vision models require separate resources. Model services and weights are not part of this release. Confirm GPU memory and ports in the panel model manager before starting a profile. Do not force-add personal screenshots, browser sessions, tokens, runtime logs, or model weights to Git.

## Code entry points

- `app/learn/`: learning tasks, evidence contracts, recognition, and review projections.
- `app/operation/`: window binding, observation, localization, action candidates, and execution API.
- `app/gate/`: shared safety, dataflow, and final-submit blocking.
- `app/web_panel/`: learning, review, and replay panel.
- `configs/model_profiles/`: declarative model and shadow-provider profiles.
- `scripts/`: offline smoke, reports, and maintenance tools.
- `tests/`: contract, regression, and safety-boundary tests.

The reusable runtime contract comes before site-specific patches: candidates carry `capture_id`, viewport, source, bbox, click point, and freshness; scrolling is bound to a target container; detail updates consume only the latest snapshot; and final-submit detection is scoped to the active form or modal.

## Next mainline

1. The `reviewed_workflow_asset_v2` contract, immutable CAS store, semantic compiler, verified replay coordinator, and bounded recovery path are implemented; old content is not migrated.
2. Backend APIs and panel controls now support `Compile → CAS Publish → read-only Preview`; source workflows and assets are resolved and verified server-side, and preview never captures the screen or calls the action API.
3. A synthetic three-state SEEK E2E path (home → detail → application entry stop) is verified with the real compiler, CAS, panel API, replay coordinator, and navigation adapter envelope. It uses fakes for external dependencies and makes no real GUI, network, or action claim; controlled local current-observation smoke is next.
4. Benchmark generic window/coordinate mapping, long screenshots, and scroll-container replay; `read`/`scroll` executable replay remains deferred until a typed effect verifier exists. Compare Bare Agent and Runtime on success, misclicks, stop quality, recovery time, latency, and evidence completeness.

## Release information

- Version: `0.3.0`
- Root project license: [`ISC`](LICENSE).
- Optional third-party component boundaries: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
- Changes: [`CHANGELOG.md`](CHANGELOG.md).

“Verified” in this document means that the corresponding controlled path or narrow smoke has evidence; it is not a claim of universal website, application, or unattended reliability. Narrow checks and known limitations are recorded in `CHANGELOG.md` and the design documents in this repository.
