# agent-gui-runtime

Windows GUI Agent Runtime for observing, understanding, locating, safely operating, tracing, and learning reusable interface structures across websites and desktop software.

## Deployment

### Requirements

- Windows 10 or Windows 11
- Python `>=3.11,<3.12`
- [`uv`](https://docs.astral.sh/uv/)
- Local vision models are optional for API and panel inspection, but required for real model understanding and precise grounding

### Quick Start

```powershell
cd D:\agent-gui-runtime
uv sync
.\start_test_panel.bat
```

The launcher starts the FastAPI runtime when needed, waits for `/health`, opens the panel, and writes runtime logs to `logs/test-panel-runtime.log`.

- Panel: `http://127.0.0.1:8000/panel`
- API documentation: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

### Manual Runtime Start

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Local Vision Models

The recommended route is the panel model manager. Learning observation uses Qwen3-VL 8B by default; precise grounding uses VISTA-4B. Profiles live in `configs/model_profiles/` and server scripts live in `scripts/model_servers/`.

Install the optional VISTA dependencies before its first run:

```powershell
uv sync --group vista
```

Manual VISTA start:

```powershell
.\scripts\model_servers\start_transformers_vision_server.ps1 `
  -ModelPath .\models\vista-4b-safetensors `
  -ModelName inclusionAI/VISTA-4B `
  -Port 1244
```

Stop local services after testing:

```powershell
.\scripts\model_servers\stop_local_vision_server.ps1 -Port 1244
```

Stop the manually started API with `Ctrl+C`. The runtime does not authorize real clicks merely because a model or panel is running.

### Generated Data Policy

`artifacts/` and `logs/` are local runtime output and are ignored by Git. They can contain screenshots, traces, learned drafts, candidate data, and browser-session state. Do not force-add either directory. Reusable, privacy-reviewed test fixtures must live under `tests/fixtures/` or another explicitly reviewed source directory.

## Results Preview

### Deterministic First-Recognition Integration

`deterministic_root_partition_v1` is the only formal Stage1 root-partition path. There is no runtime strategy switch, hidden rollback path, or shadow output identity; recovery uses Git history. The reusable coarse-proposal builder lives in `app/learn/recognition/`, and Stage2, fusion, page details, and the read-only PathGraph preview consume the canonical Stage1 contract.

A fixed-trace nine-interface replay covers Apple Music, Python.org, Windows Settings, File Explorer, Steam, WhatsApp, Notepad, WeChat, and Bilibili. The latest post-change run at `logs/region_partition_mvp/nine_interface_after_datagrid_visual_row_fix_20260717/` produced original / root-partition / final-fusion evidence for all nine cases; all nine passed the root validator and Stage1 gate and completed Stage2. Every root, numbering, calibration, fusion, page-detail, and learning-draft count remained unchanged from the preceding protected run. Bottom full-width activity bands are no longer promoted as one partial card, and dense table cells are rendered under row parents instead of repeated in the main overlay.

The nine traces and screenshots remain privacy-sensitive local evidence under ignored `logs/` and `artifacts/`. This benchmark dispatched zero model calls and zero target-application clicks. It proves fixed-trace integration only, not general recognition accuracy, model reliability, Execute readiness, live GUI-operation success, or executable Runtime PathGraph readiness.

An offline Calculator fixed-trace probe exposed two generic root-partition failures: equal-width keypad columns were promoted as a left navigation rail, and repeated keypad row separators created a false bottom bar. The common selector now rejects repeated grid-internal column cuts and excludes repeated row-sequence separators from bottom-bar calibration. The corrected three-image probe is under `logs/region_partition_mvp/new_interface_calculator_holdout_20260717/run_fixed2/`; all nine protected root bboxes and Stage2/fusion counts remained unchanged. Because this Calculator sample drove the fix, it is now a regression sample rather than independent holdout evidence.

An untouched MDN JavaScript screenshot-only probe exposed a separate dataflow defect: conditional OCR recovery produced useful page elements, but Stage1 partitioning still read the pre-recovery empty inventory. Recovered OCR candidates now enter the deterministic root partition before Stage1, while remaining available to later numbering. The corrected probe produces a top bar plus main-content partition and is reviewed in `logs/region_partition_mvp/new_interface_mdn_javascript_20260717/mdn_javascript_triptych_fixed.png`. This is screenshot-only evidence with no bound-window observe trace, model call, or click, and is not proof of general website-recognition reliability.

A live bound-window Task Manager probe exposed two generic defects. Stage1 first promoted data-grid columns as a false left rail; the root selector now rejects internal cuts inside a dominant tabular container. Stage2 then rejected the real table because two valid columns were only 51 pixels apart while the old detector required 80 pixels, allowing vertical text-card groups to take ownership. Explicit dominant DataGrid evidence now enables width-relative column validation, a hidden table parent, and visible horizontal row parents. When OCR/UIA row evidence ends before the visible DataGrid, Stage2 derives the established row interval and adds a review-only row only when the source image contains a matching horizontal content edge; blank tails are not extrapolated. The current three-image review is `logs/region_partition_mvp/task_manager_datagrid_visual_row_fix_20260717/task_manager_original_stage1_final.png`: 22 text-evidenced rows plus 6 visually evidenced rows cover the visible table and stop before the bottom action bar. This fixed-trace result remains review-only and is not recognition-reliability or Execute evidence.

### Current Stage

The deterministic first-recognition path is integrated into read-only Learning Mode with declared limitations.

| Evidence | Current result |
| --- | --- |
| Integration status | `deterministic_root_partition_v1` is the only formal Stage1 path |
| Protected first-recognition replay | 9 checksum-pinned fixed traces |
| Three-image audits | 9 complete original / root / final sets |
| New-interface debugging probes | Calculator fixed trace, MDN screenshot-only dataflow probe, and live bound Task Manager table-layout probe; all are now regression-only |
| Root partitions accepted by manual review | 9 |
| Final fusion images accepted by manual review | 8 |
| Remaining review items | Bilibili has local bottom partial candidates; File Explorer expanded navigation remains visually dense |
| Real no-click first recognition | 3 interfaces: Settings, File Explorer, Notepad |
| Repository verification | 1579 tests passed after the Task Manager DataGrid visual-row completion correction |
| Capability boundary | fixed-trace integration evidence, not general accuracy |

Authoritative reports:

- [Phase acceptance report](logs/benchmarks/learning_mode_stage_acceptance_20260715/stage_acceptance_report.json)
- [Nine-case recursive report](logs/benchmarks/learning_interface_chain_stage_acceptance_20260715_rerun/learning_interface_chain_smoke_report.json)
- [Strict readiness report](logs/benchmarks/learning_mode_stage_acceptance_20260715/learning_mode_demo_goal_readiness_report.json)
- [Panel presentation evidence](logs/benchmarks/learning_mode_stage_acceptance_20260715/learning_interface_presentation_evidence_v1.json)

### Nine-Case Fusion Review

![Nine-case contact sheet](logs/benchmarks/learning_interface_chain_stage_acceptance_20260715_rerun/learning_interface_chain_contact_sheet.png)

| Case | Interface family | Final fusion image | Review status |
| --- | --- | --- | --- |
| Apple Music 2026-07-10 | Media catalog | [Open](artifacts/review-overlays/state-6bacc9cc36d224e3-learn-targets__learn-target-coordinates__20260715-194943-911989.png) | Review-ready |
| Apple Music 2026-07-11 | Media catalog | [Open](artifacts/review-overlays/state-d105e84d6c3a7091-learn-targets__learn-target-coordinates__20260715-195015-547117.png) | Review-ready |
| Python.org | Documentation portal | [Open](artifacts/review-overlays/state-521513ecc2a306e2-learn-targets__learn-target-coordinates__20260715-195025-921057.png) | Stress-only |
| Windows Settings | Settings dashboard | [Open](artifacts/review-overlays/state-2cd40c4415ab239a-learn-targets__learn-target-coordinates__20260715-195053-166912.png) | Review-ready |
| File Explorer | File browser | [Open](artifacts/review-overlays/state-656d16c3985759b7-learn-targets__learn-target-coordinates__20260715-195141-005171.png) | Review-ready |
| Steam 2026-07-13 | Conversation workspace | [Open](artifacts/review-overlays/state-3ee160a08ac3185c-learn-targets__learn-target-coordinates__20260715-195204-990549.png) | Review-ready |
| Steam 2026-07-14 | Conversation workspace | [Open](artifacts/review-overlays/state-038abc0eee06ec39-learn-targets__learn-target-coordinates__20260715-195225-208234.png) | Review-ready |
| WhatsApp | Conversation workspace | [Open](artifacts/review-overlays/state-d74a5379f44f615b-learn-targets__learn-target-coordinates__20260715-195258-709611.png) | Review-ready |
| Notepad | Generic editor | [Open](artifacts/review-overlays/state-b33c83e0d43877fa-learn-targets__learn-target-coordinates__20260715-195312-896997.png) | Review-ready |

### Panel Presentation

Desktop and narrow layouts render the current fused image, page details, and a resizable read-only PathGraph preview without horizontal overflow. Page-detail views with the same explicit report/source identity render once; a genuinely distinct model preview remains visible.

![Desktop learning panel](logs/benchmarks/learning_mode_stage_acceptance_20260715/panel_desktop.png)

![Narrow learning panel](logs/benchmarks/learning_mode_stage_acceptance_20260715/panel_narrow.png)

### Runtime Flow

```text
User conversation
  -> Agent decision
  -> Observe / OCR / vision inventory
  -> Operation candidate
  -> Gate safety decision
  -> Controlled action or safe stop
  -> Trace evidence
```

Learning Mode uses a read-only chain:

```text
Bind and capture
  -> full-screen understanding
  -> Stage1 structure regions
  -> Stage2 numbered regions
  -> page details
  -> OCR + VISTA + rerank + Gate dry-run
  -> fused learning draft
  -> read-only PathGraph preview
```

### Safety and Evidence Boundary

- Learning drafts and preview PathGraphs do not authorize execution.
- Every real click must pass the gated recognition-plan API with current screenshot and coordinate evidence.
- Final submit, send, confirm, and payment actions remain hard-blocked.
- The current evidence does not establish general recognition accuracy, pure-model template reliability, SEEK E2E stability, or live safe-fill reliability.
- No live click, fill, submit, Execute binding, live safe fill, or Runtime PathGraph promotion occurred during the current phase acceptance.

## Project Iteration History

### June 2026: Runtime Foundation

- Established the Agent, Operation, Gate, Trace, and reusable PathGraph architecture.
- Added Windows application discovery, exact window binding, screenshots, OCR/UIA evidence, controlled input, and action verification.
- Built the first SEEK profile and no-submit application safety contracts.

### Early July 2026: Learning Mode

- Separated execution models from learning models.
- Added full-screen understanding, Stage1 structure localization, Stage2 numbering, page-detail drafts, precise grounding, and read-only PathGraph previews.
- Separated model-generated drafts, human-assisted review assets, templates, and executable runtime assets.

### Mid July 2026: Generalization and Review

- Added hierarchy ownership, parent containment, browser-chrome filtering, same-source screenshot checks, stale-fixture detection, and cross-interface anti-pollution regression.
- Repaired dense two-column ROI behavior, non-actionable grounding leakage, stale overlay display, and precise-calibration progress reporting.
- Introduced mandatory source screenshot, Stage1 image, and final fusion image review for every protected interface.

### 15 July 2026: Phase Acceptance

- Completed four current real-interface evidence sets and a nine-case protected recursive regression.
- Verified the desktop and narrow panel presentation with current same-source artifacts.
- Passed the complete repository test suite with 1538 tests.
- Kept strict final readiness blocked until model-only generation and independent holdout evidence are sufficient.

Detailed history and current planning:

- [Full iteration archive](PROJECT_ITERATION_HISTORY.md)
- [Project summary](PROJECT_SUMMARY.md)
- [Current state](CURRENT_STATE.md)
- [Architecture](ARCHITECTURE.md)
- [Next steps](NEXT_STEPS.md)
- [Agent API workflow](AGENT_API_WORKFLOW.md)
- [API field reference](API_FIELD_REFERENCE.zh-CN.md)
