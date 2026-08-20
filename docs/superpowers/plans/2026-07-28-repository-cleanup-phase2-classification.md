# Repository Cleanup Phase 2 Classification

Date: 2026-07-28

## Scope

This classification follows the repository cleanup safety rules:

- keep local models stopped during cleanup;
- preserve Execute, Gate, final-submit blocking, Trace, and operational memory;
- preserve real learning drafts and human-review evidence;
- delete only evidence-backed disposable output;
- change one responsibility boundary at a time.

Codegraph was attempted first but its transport was unavailable. The audit therefore used targeted repository searches, file-reference scanning, runtime-storage plans, tests, and full-suite verification.

## Storage Evidence

| Root | Approximate size | Classification |
| --- | ---: | --- |
| `models` | 31.646 GiB | Must keep; model assets, not cleanup output |
| `artifacts` | 9.162 GiB | Mixed; preserve learning, benchmark, golden, and review assets |
| `logs` | 9.098 GiB | Mixed; Trace must remain, disposable temporary output is bounded |
| `.venv` | 3.630 GiB | Must keep while this environment is active |
| `tools` | 0.673 GiB | Must keep pending dependency audit |
| `.codegraph` | 0.380 GiB | Keep; indexed development data |
| `.git` | 0.271 GiB | Must keep |
| `.paddlex` | 0.162 GiB | Manual confirmation before removal |

## 1. Confirmed Safe Delete

- Files older than 14 days under `logs/tmp`.
- Review overlays older than 14 days only when no protected source references them.
- Protected references include source, documentation, tests, Trace, learning runs, benchmark/golden manifests, workflow reviews, runtime state, and newest retained files.

Completed checkpoint:

- 1,070 disposable files deleted.
- 115,957,770 bytes reclaimed.
- One changed-after-plan cache file skipped.
- No Trace or learning-run candidate entered the applied plan.

## 2. Recommended Archive

- Superseded, never-applied cleanup dry-run plans created before protected-root enforcement.
- Keep applied plans and their reports together.
- Keep the latest protected-root plan and report directly accessible.

Completed checkpoint:

- Six superseded plans with zero repository references were compressed into:
  `logs/cleanup/archive/runtime_storage_cleanup_superseded_pre_protected_roots_20260728.zip`.
- The archive contains exactly six verified entries.
- Original size: 49,363,606 bytes.
- Archive size: 4,277,787 bytes.

## 3. Recommended Move Or Rename

No source move is approved in this checkpoint.

Potential later moves require an isolated plan:

- split remaining Locate orchestration from `app.api.vision`;
- split Panel application services from HTTP adapters;
- split the large panel JavaScript by user-facing review responsibility.

Public imports, routes, CLI commands, model profiles, and safety contracts must remain compatible during any move.

## 4. Recommended Refactor

Priority order:

1. Design and characterize a neutral evidence-only Locate boundary.
2. Keep Locate separate from Gate and Execute.
3. Audit `app/api/panel.py` for application-service logic still owned by the HTTP layer.
4. Audit `app/web_panel/panel.js` for separable review/editor modules.
5. Remove duplicate helpers only after static references and focused runtime tests prove them unused.

Scheme A completed the Observe boundary. It does not prove that Locate or Panel boundaries are complete.

## 5. Must Keep

- `logs/traces`;
- `artifacts/learning-runs`;
- benchmark and golden fixtures;
- final-submit guard tests and safety fixtures;
- human-review and workflow-review assets;
- operational memory and runtime state;
- model files and active virtual environment;
- demo assets still referenced by documentation or panel workflows;
- regression tests;
- public API and CLI compatibility surfaces with real callers.

The cleanup contract now rejects Trace and learning-run roots even if an older plan explicitly names them.

## 6. Needs Human Confirmation

- duplicate or obsolete local model variants under `models`;
- `.paddlex` caches and model state;
- large historical benchmark directories not referenced by current manifests;
- old external quarantine/worktree directories outside this repository;
- demo assets that are visually useful but have no structured reference;
- any compatibility branch invoked through configuration, subprocess, reflection, or path strings.

## Small-Step Execution Plan

1. Completed: protected-root cleanup contract and regression tests.
2. Completed: conservative 14-day low-risk cleanup.
3. Completed: archive superseded unreferenced dry-run plans.
4. Next: read-only Locate boundary characterization and dependency audit.
5. Then: select one boundary for an isolated test-first refactor.
6. Finally: rerun focused tests, full tests, health check, model shutdown check, and documentation sync.

No cleanup checkpoint may weaken Gate, final-submit blocking, Trace evidence, or artifact non-authorization.
