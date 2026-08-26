# Task 6 P1/P2 Read-Only Authority Prerequisites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the two smallest read-only authority projections required for Task 6 Amendment C to bind current Task 5 evidence and pre-cancel B1 launch ownership without caller-supplied raw paths, private-journal duplication, cross-run authority, or cleanup ambiguity.

**Architecture:** Task 5 remains the sole owner of window-binding serialization and publishes a create-only exact-ref authority record behind separate opaque publisher/resolver capabilities. B1 remains the sole owner of process/Job/assignment journals and exposes one read-only, controller-guarded launch-owner inspection. Amendment C consumes those projections; this plan does not add a model, provider, generic artifact store, directory scanner, route, UI, action authority, Task 7 behavior, or a new threat model.

**Tech Stack:** Python 3, Pydantic-compatible canonical JSON documents, Windows process/Job supervision, pytest, existing workflow store and worker registry.

**Spec:** `D:/agent-gui-runtime/.superpowers/sdd/2026-08-26-portfolio-hybrid-v1-1-task6-prerequisite-amendment/task6-post-review-blocker-adjudication.md`

## Global Constraints

- Preserve Portfolio v1 and the reviewed-execution boundary; models never receive execution authority.
- Keep `real_clicks = 0`, `live_fills = 0`, and `live_submits = 0`.
- Add only two read-only authority projections over existing Task 5 and B1 evidence.
- Do not modify A or B2 contracts, add a result-byte anchor before first inspection, or broaden the local-admin/threat model.
- Never scan Task 5 or B1 directories to discover authority; resolve exact filenames from closed refs.
- Production and test roots/capabilities must fail closed on substitution or cross-pairing.
- Use TDD, focused verification, independent review, explicit staging, one single-purpose commit per task, and no push.
- Do not touch `tests/test_agent_runtime_actual_adapter_portfolio_v1.py`.
- Every test that starts a process, listener, window, Job, event, or mutex must close it in an outer `finally` and independently prove zero residue.

---

### Task 1: Task 5 exact-ref binding authority publisher and resolver

**Files:**
- Modify: `app/learn/hybrid/benchmark_v2_worker_binding.py`
- Modify: `app/learn/workflow_service.py`
- Test: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py`
- Test: `tests/test_learning_workflow_stage_execution.py`

**Interfaces:**
- Consumes: the existing Task 5 server-owned window-binding serialization cut, owner journal, ready-event evidence, capture ref, and existing adoption validator.
- Produces:

```python
def publish_server_worker_window_binding(
    *,
    publisher: object,
    run_id: str,
    stage: str,
    operation_id: str,
    owner: Mapping[str, object],
    capture_ref: Mapping[str, object],
) -> Mapping[str, object]: ...

def resolve_server_worker_window_binding(
    *,
    resolver: object,
    run_id: str,
    stage: str,
    operation_id: str,
    window_binding_ref: Mapping[str, object],
    capture_ref: Mapping[str, object],
    worker_process_identity: Mapping[str, object] | None = None,
    normal_binding_evidence_ref: Mapping[str, object] | None = None,
) -> Mapping[str, object]: ...
```

- Adds exactly one composition field: `benchmark_v2_worker_binding_resolver: object | None`.
- Publisher and resolver are distinct opaque capabilities. Production composition binds the production Task 5 authority root; a benchmark-enabled test composition must bind a test resolver to the same temporary Task 5 root as its publisher. Non-benchmark composition may keep the field null.

- [ ] **Step 1: Write RED tests for exact publication and fresh resolution**

Create tests that publish at the existing server-owned serialization cut, discard the caller/owner mapping, construct a fresh resolver, and recover byte-identical `serialized_window_binding` from only the exact `window_binding_ref` and `capture_ref`. Monkeypatch `glob`, `rglob`, `scandir`, and directory iteration to fail so a passing test proves direct exact-filename lookup.

The durable authority document must be a create-only sealed mapping with exactly these semantic fields:

```text
contract_version = benchmark_v2_worker_window_binding_authority_v1
authority_kind
run_id, stage, operation_id
window_binding_ref = {id, content_sha256}
capture_ref = {id, content_sha256}
serialized_window_binding
owner_binding_ref = {content_sha256}
owner_journal_ref = {content_sha256}
owner_ready_event_ref = {content_sha256}
artifact_is_authorization = false
execute_binding_enabled = false
predecessor_content_sha256
content_sha256
```

The resolution document must be sealed and contain:

```text
contract_version = benchmark_v2_worker_window_binding_resolution_v1
authority_kind
run_id, stage, operation_id
window_binding_ref, capture_ref
binding_authority_ref = {content_sha256}
serialized_window_binding
worker_process_identity = null | {pid, create_time_ns}
normal_binding_evidence_ref = null | {content_sha256}
artifact_is_authorization = false
execute_binding_enabled = false
content_sha256
```

- [ ] **Step 2: Run RED1 and preserve the failure output in the task report**

Run only the new publication/fresh-resolution tests. The expected failure is a missing public publisher/resolver or composition field, not an unrelated fixture/process failure.

- [ ] **Step 3: Implement opaque capabilities and exact-file validation**

Implement separate private capability classes and public factory/validation functions following the existing production/test root-binding pattern. Derive the authority filename from `window_binding_ref.content_sha256`; reject any noncanonical ref before filesystem access. Make `window_binding_ref.content_sha256` exactly equal the existing serialized binding `payload_sha256`, and derive its `id` from Task 5 owner identity rather than caller input.

Prelaunch resolution requires `worker_process_identity` and `normal_binding_evidence_ref` both null. Result-parent resolution requires both non-null and reuses Task 5's existing normal-clear evidence validation internally. Add a thin adoption-from-resolver entry that reopens the same exact authority document before delegating to the existing adoption validator. Never expose or call `_owner_from_journal` from Amendment C.

- [ ] **Step 4: Add substitution, corruption, provenance, and zero-side-effect negatives**

Cover wrong run/stage/operation/root/authority kind/ref id/ref SHA/capture/owner-ready parent; deleted, corrupt, and resealed authority documents; wrong PID/create-time; wrong A normal evidence ref; production/test capability substitution; and two-root composition substitution. Each negative must assert zero B1 prepare, workflow-store CAS, spawn, provider, and action calls.

- [ ] **Step 5: Prove no raw Task 5 authority enters workflow-store/C durable JSON**

Add static and dynamic assertions that no persisted C/store document contains `serialized_window_binding`, `capture_image_path`, or `owner_journal_path`. Verify fresh adoption rebuild matches the existing Task 5 receipt byte-for-byte.

- [ ] **Step 6: Run focused GREEN and residue verification**

Run the full Task 5 worker-binding test module plus affected workflow-stage composition tests. In an outer `finally`, close any Task 5 window and temporary authority root. Independently assert zero owned processes, Jobs, HWNDs, events, mutexes, handles, listeners, and test UI.

- [ ] **Step 7: Commit Task 1**

Stage only the four named files and commit:

```text
feat(benchmark-v2): resolve task5 binding by closed refs
```

---

### Task 2: B1 read-only launch-owner inspection

**Files:**
- Modify: `app/learn/workflow_worker.py`
- Test: `tests/test_learning_workflow_stage_worker.py`

**Interfaces:**
- Consumes: existing B1 per-operation controller guard, Registry lock, reservation, operation anchor, expected/actual supervision, owner journal, assignment proof, and process identity validation.
- Produces:

```python
def inspect_benchmark_worker_launch_owner(
    self,
    *,
    worker_id: str,
    run_id: str,
    stage: str,
    operation_id: str,
    reservation_ref: Mapping[str, object],
    expected_operation_anchor: Mapping[str, object],
    supervision_root: BenchmarkWorkerSupervisionRoot,
) -> Mapping[str, object]: ...
```

- [ ] **Step 1: Write RED tests for every launch-owner phase and fresh replay**

Cover anchored/no-owner, acquiring/pre-assignment, assignment-proven, gate-released, result-completed, cleanup-finalization-intent, cleanup-verified, and cleanup replay. Destroy and reconstruct the Registry between write and read where possible; require byte-identical sealed projection on replay.

The projection must contain exactly these semantic fields:

```text
contract_version = benchmark_worker_launch_owner_inspection_v1
authority_kind
run_id, stage, operation_id
worker_id, model_request_id, payload_sha256, execution_nonce
reservation_ref
current_reservation_ref
operation_anchor_ref
expected_supervision_ref
supervision_ref
reservation_state
owner_phase
assignment_state = not_proven | proven
process_identity = null | {pid, create_time_ns}
scope_name = null | str
assignment_proven_ref = null | {content_sha256}
artifact_is_authorization = false
execute_binding_enabled = false
content_sha256
```

- [ ] **Step 2: Run RED2 and preserve the failure output in the task report**

Run only the new inspection tests. The expected failure is the missing public read-only inspection, not a worker launch or cleanup leak.

- [ ] **Step 3: Implement inspection using existing locks and private validation internally**

Acquire the existing per-operation controller guard and then `Registry._lock`. Validate reservation, operation anchor, expected/actual supervision, owner, assignment, PID/create-time, scope, and assignment proof using B1-owned helpers. Perform no workflow-store callback, mutation, spawn, provider call, termination, cleanup, or gate release.

Return all three of `process_identity`, `scope_name`, and `assignment_proven_ref` as null only after B1 positively validates `assignment_state=not_proven`. Return all three non-null for assignment-proven, gate-released, result-completed, cleanup-finalization-intent, and cleanup-verified phases. Missing, ambiguous, corrupt, or mismatched owner state raises `LearningStageWorkerError`; it never degrades to pre-assignment nulls.

- [ ] **Step 4: Add identity, root, remint, and zero-mutation negatives**

Cover wrong run/stage/operation/worker/root/reservation/anchor/expected supervision/actual supervision/process/scope/assignment, plus resealed private journals. Assert inspection leaves workflow-store, journals, spawn/provider/termination counters, process/Job state, and existing cleanup receipt bytes unchanged.

- [ ] **Step 5: Run focused GREEN and residue verification**

Run the B1 worker test module's focused inspection and cleanup selectors, then the full allowed B1 module if focused tests are green. In an outer `finally`, resume any pending cleanup and independently assert zero owned process, Job, event, mutex, handle, listener, and UI residue.

- [ ] **Step 6: Commit Task 2**

Stage only the two named files and commit:

```text
feat(benchmark-v2): inspect b1 launch owner safely
```

---

### Task 3: Rewire Amendment C to closed Task 5/B1 evidence and add real recorded-response E2E

**Files:**
- Modify: `app/learn/workflow_service.py`
- Modify: `app/learn/hybrid/benchmark_v2_incumbent_operation.py`
- Modify: `app/api/panel.py` only if exact frozen request/error bytes require removal of raw fields
- Test: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py`
- Test: `tests/test_learning_workflow_stage_execution.py`

**Interfaces:**
- Consumes: Task 1 closed-ref Task 5 resolver and adoption-from-resolver; Task 2 B1 launch-owner inspection; existing A snapshot; existing B1/B2 cleanup/reconcile projections.
- Produces: a Task 6 C operation that persists only closed selectors/refs, binds one exact operation under one lock, validates current parent lineage before intent, and drives one real Registry/spawn recorded-response path to a replayable terminal receipt.

- [ ] **Step 1: Write RED tests for raw-sidecar removal and cross-run rejection**

Reduce the benchmark request to closed `provider_case_ref`, `window_binding_ref`, and `capture_ref` selectors. Add tests that reject wrong/cross-run/old Task 5 binding, capture, raw path, or serialized mapping before B1 prepare/store CAS/spawn/provider. Assert C durable JSON has no raw binding or path keys.

- [ ] **Step 2: Run RED3a and record the expected failures**

Run only the new source/provenance tests. Expected failures must show current raw request persistence/private journal interpretation or missing closed resolver use.

- [ ] **Step 3: Rebuild payload from current store and opaque resolvers on every launch/restart**

Delete the raw request sidecar. Load only current operation/store refs, resolve the provider case and Task 5 binding from the composition's opaque resolvers, and rebuild the authoritative payload before the existing B1 prepare/launch path. Ensure a fresh process can recover the same reservation/nonce/worker without caller mappings.

- [ ] **Step 4: Write and satisfy terminal parent/remint tests**

Seal and CAS the first A mapping as the operation's result identity; every later resume must require byte-exact A mapping equality. Before terminal intent, join current Task 5 resolution, B1 launch-owner inspection, exact A mapping, B1 cleanup, and existing B2 reconcile projection. Compare run/stage/operation/worker/model/payload, source/reservation/anchor/expected+actual supervision, PID/create-time/scope/assignment, acquisition/runtime-owner, and predecessor refs. Use the real B1 worker cleanup parent in terminal intent. Reject same-identity remint after C's first A anchor, cross-parent receipt, and self-sealed fake cleanup with zero terminal-intent/store mutation.

- [ ] **Step 5: Write and satisfy post-launch cancel identity tests**

Before winning cancel-intent CAS, invoke B1 read-only inspection. Only positively validated pre-assignment state may persist three null process fields; assignment and later phases must persist exact process identity, scope name, and assignment proof. Bind subsequent B1 cleanup to those exact persisted fields. Cover crash immediately after intent and fresh resume of the same worker with zero blind retry.

- [ ] **Step 6: Add one true real Registry/spawn harmless recorded-Qwen E2E**

Use `compose_test_learning_workflow_service` with a real `LearningStageWorkerRegistry`, real benchmark supervision root, real spawn, Task 5 authority publisher/resolver, and a fixed harmless recorded Qwen response. Drive one C service path through start, A inspection, terminal intent, exact adoption, Task 5 rebuild/adoption, B1 cleanup, B2 cleanup, terminal receipt, and replay. This test performs no model inference, click, fill, submit, publish, or GUI action. Rebuild store/root/Registry/composition across the critical restart cuts.

- [ ] **Step 7: Prove compatibility, full selectors, and zero residue**

Run all Amendment C tests, affected nonbenchmark workflow API compatibility tests, the integrated frozen-interface selector, Python compilation, `git diff --check`, and privacy/forbidden-call scans. The E2E outer `finally` must resume pending intent, clean provider, clean worker, close Task 5 window, close store, remove temporary roots, and independently assert zero process/Job/Event/mutex/handle/listener/HWND/UI residue.

- [ ] **Step 8: Commit Task 3**

Stage only the named C files and tests and commit:

```text
fix(benchmark-v2): bind incumbent to closed runtime evidence
```

---

### Task 4: Independent prerequisite and Task 6 C acceptance

**Files:**
- Update locally: `.superpowers/sdd/2026-08-26-portfolio-hybrid-v1-1-task6-prerequisite-amendment/progress.md`
- Update locally: `.superpowers/sdd/2026-08-26-portfolio-hybrid-v1-1-task6-prerequisite-amendment/task6-amendment-c-implementation-report.md`
- Create locally: `.superpowers/sdd/2026-08-26-portfolio-hybrid-v1-1-task6-prerequisite-amendment/task6-p1-p2-final-review.md`

**Interfaces:**
- Consumes: complete diffs and test evidence from Tasks 1–3.
- Produces: exact independent verdict `TASK 6 P1/P2 + C FINAL PASS` or a bounded list of load-bearing failures.

- [ ] **Step 1: Build review packages from each task base and the whole P1/P2/C range**

Include commit list, stats, full diffs, plan, adjudication, task reports, test commands/results, and residue evidence. Never use `HEAD~1` for a multi-commit task.

- [ ] **Step 2: Dispatch high-reasoning independent review**

The reviewer must manually trace production/test capability binding, exact-file resolution, lock order, fresh-restart behavior, raw-authority exclusion, terminal parent chain, cancel identity, real Registry/spawn recorded-response composition, compatibility bytes/order/call counts, and outer-finally residue cleanup. The reviewer does not rerun model inference or GUI actions.

- [ ] **Step 3: Fix only load-bearing findings through the scoped review loop**

Resume the responsible implementer for review rounds 1–3; use a fresh high-capability implementer for rounds 4–5. Each round writes RED first, commits one purpose, and receives a scoped re-review. Do not use a finding as permission to expand threat model or infrastructure.

- [ ] **Step 4: Record the final decision and continue directly to Task 7**

Only an exact independent PASS plus fresh main-agent verification closes Task 6. If PASS, append commit/test/verdict evidence to the ledger and begin Task 7. If still load-bearing after the five-round cap, record a ruling and surface the blocker rather than claiming completion.
