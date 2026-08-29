# Benchmark v2 Probe Raw-Evidence Plumbing Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace runtime-authored probe conclusions with fixed-path, durable raw parents that the lifecycle validator and runner independently reopen before P0 can terminate.

**Architecture:** Keep the current Task 9 probe flow and B1 ownership model. Add two local versioned parent contracts at the existing dispatch and lock-before-cancel boundaries, retain exact provider-native cleanup documents without re-projecting them, and make receipt v2 validation rebuild identity, body, termination, and stable-zero conclusions from those files. P0 collects one requested attempt per provider; only P1 enumerates canonical ledgers and selects the first complete verified attempt per cell.

**Tech Stack:** Python 3.11, canonical UTF-8 JSON, SHA-256, existing dispatch attestation, `LearningStageWorkerRegistry`, `WorkflowService`, B1 validators, provider-native cleanup validators, pytest.

**Spec:** This planning-only amendment is authoritative over conflicting P0 raw-parent and P0 runner-summary clauses in `docs/superpowers/plans/2026-08-29-benchmark-v2-probe-authority-bridge-amendment.md`. It does not change the existing public probe-authority bundle, accepted/scorer/provider/dependency contracts, or P1 selection semantics.

## Global Constraints

- Implementation starts by deleting or shrinking the current synthetic body/termination/stable-zero and hard-coded profile paths; do not layer another projection over them.
- The only incremental P0 allowlist is the six files in §2. No model-server, adapter, process-scope, supervisor, public-contract, or new test-module change is allowed.
- Add no model, general supervisor, remote witness, public API, provider contract, accepted/scorer/provider/dependency field, or B1 contract/validator redesign.
- `WorkflowService` changes only the internal lock-before-cancel persistence path. Its public method signatures and response shapes remain byte-for-byte contract-compatible.
- The runtime may orchestrate and locate evidence but may not author conclusions used as parents. An opaque `{content_sha256}` ref, runtime dictionary, status label, or provider profile reconstruction is not evidence.
- New local artifacts are nonauthorizing, contain native paths/process identities only locally, use canonical UTF-8 JSON, end with one LF, and are create-new-or-byte-identical.
- The lifecycle validator and runner receive trusted local roots, derive every fixed path themselves, read exact bytes again, verify seals and joins, and reject caller-injected replacements.
- Do not run an actual benchmark, model, provider, or GUI until all four slices pass and the preflight in §9 returns PASSABLE.

---

## 1. Blocking findings and authority rule

The existing P0 diff is not acceptable because it lets `BenchmarkV2Runtime` reconstruct provider profiles, invent `body_completion_observation.state="not_complete"` after service terminal, describe termination without exact PID/create-time lineage, and generate empty resource lists from its own view. The runner also labels one requested attempt as `first_complete_verified_attempt_per_cell`, although it does not enumerate the canonical ledgers.

The repair is deliberately narrow:

1. The dispatch boundary persists the exact attested runtime identity and exact profile payload identity before its dispatch receipt becomes durable.
2. The operation service persists the pre-cancel body observation while the service operation lock and registry lock are both authoritative and before cancellation mutates the worker.
3. The worker registry retains exact provider-native cleanup bytes and the existing B1 raw chain; it does not translate them into a new truth contract.
4. Lifecycle validation reopens all fixed raw parents and rebuilds the receipt. Runner validation invokes that rebuild and does not trust runtime projections.

The runtime-produced receipt candidate is therefore only a locator/request. A receipt is valid only after independent raw revalidation.

---

## 2. Frozen incremental allowlist

These are the only six files added to the current P0 implementation allowlist:

| File | Exact permitted symbols/regions |
|---|---|
| `app/learn/hybrid/benchmark_v2_dispatch_attestation.py` | `attest_benchmark_provider_dispatch`; `_attest_exact_provider_runtime`, `_attest_qwen_runtime`, `_attest_vista_runtime`, `_attest_scoped_process_runtime`; new `_compose/_validate/_write/_read_benchmark_v2_dispatch_runtime_parent_v1` helpers |
| `app/learn/workflow_worker.py` | `LearningStageWorkerRegistry` internal pre-cancel persistence and provider-raw retention helpers; existing provider cleanup reconciliation and existing create-only writer only |
| `app/learn/workflow_service.py` | `_cancel_benchmark_v2_hybrid_workflow_service` internal call ordering only; no new exported function or method |
| `tests/test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation.py` | dispatch raw-parent RED/GREEN tests |
| `tests/test_learning_workflow_stage_worker.py` | pre-cancel body, exact worker incarnation, provider raw retention, and create-new-or-identical tests |
| `tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py` | operation-lock-before-registry-lock-before-cancel ordering and public-shape non-regression tests |

Existing P0 allowlist files remain limited to their already approved receipt/runtime/runner work:

- `app/learn/hybrid/benchmark_v2_lifecycle.py`
- `app/learn/hybrid/benchmark_v2_runtime.py`
- `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py`
- `tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py`
- `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py`
- `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py`

Do not pre-add `app/core/model_server.py`, `app/learn/recognition/uei/omniparser_shadow_adapter.py`, `app/learn/hybrid/windows_process_scope.py`, or a new test file. If a required raw fact cannot be produced through the six incremental files and existing producers, apply the fail-closed stop in §9.

---

## 3. Local parent contract A: dispatch runtime/profile

### 3.1 Fixed path and closed shape

Contract version: `benchmark_v2_dispatch_runtime_parent_v1`.

Fixed local path:

```text
runtime_state/benchmark-v2-provider-dispatch/<operation-key>.<provider>.1.runtime-parent.json
```

`<operation-key>` is the lowercase SHA-256 of canonical `operation_ref`; `<provider>` is exactly `omni`, `qwen`, or `vista`; `.1` is dispatch index 1. A probe with zero, multiple, or differently indexed dispatches fails closed.

Exact top-level fields:

```text
contract_version
provider
operation_ref
dispatch_receipt_ref
runtime_identity
profile
artifact_is_authorization
execute_binding_enabled
content_sha256
```

Exact `profile` fields:

```text
profile_id
profile_sha256
profile_payload_sha256
```

`runtime_identity` is the complete validated `benchmark_v2_provider_runtime_identity_v1`, including exact `{pid, create_time_ns}` process incarnations, Job membership, listener ownership where applicable, and lease identity where applicable. `profile_sha256` is the producer contract's profile identity; `profile_payload_sha256` is recomputed from the exact canonical profile payload read at dispatch. For profile contracts where those identities are defined identically, both values are equal; neither may be reconstructed later from a provider ID.

### 3.2 Producer ordering

Refactor `_attest_exact_provider_runtime` and its provider branches to return the full validated runtime identity plus the exact profile descriptor rather than only an opaque digest. For Omni, read and validate the exact configured `learn_mode_omniparser_v2.json` payload used by the installed adapter at dispatch; do not use the hard-coded dictionary currently in `_probe_runtime_profile_identity`. Qwen and VISTA reuse the exact lease/profile payloads they already validate.

`attest_benchmark_provider_dispatch` performs this order:

1. validate operation, window, exact live runtime, and exact profile payload;
2. compose the existing dispatch receipt in memory and seal it;
3. compose the local runtime parent with `dispatch_receipt_ref={content_sha256}`;
4. create the fixed parent file, flush and fsync it; an existing file is accepted only if its bytes are identical;
5. append and fsync the existing dispatch receipt journal row;
6. return the existing dispatch receipt shape unchanged.

The parent is intentionally local and path-bearing. A crash after step 4 leaves a harmless orphan that cannot join a missing dispatch receipt. A crash before step 4 leaves no dispatch authority.

### 3.3 Consumer rules

`benchmark_v2_lifecycle.py` derives this path from the validated operation ref and provider, rereads the bytes, verifies canonical form/content seal/closed fields, rereads the dispatch journal, and requires exact mutual joins. It rejects a parent supplied as a runtime mapping and rejects an opaque digest that cannot be resolved from the fixed root.

---

## 4. Local parent contract B: pre-cancel body observation

### 4.1 Fixed path and closed shape

Contract version: `benchmark_v2_hybrid_pre_cancel_body_observation_v1`.

Fixed local path:

```text
logs/workflow-workers/<worker_id>.benchmark-v2-pre-cancel-body.json
```

Exact fields:

```text
contract_version
run_id
stage
operation_id
worker_id
model_request_id
payload_sha256
process_identity
dispatch_receipt_ref
worker_journal_file_ref
state
observed_monotonic_ns
artifact_is_authorization
execute_binding_enabled
content_sha256
```

`state` is exactly `not_complete`. `process_identity` is the exact B1 worker `{pid, create_time_ns}` from the current launch anchor/registry record. The observation is valid only while the matching worker is still running, no result has been adopted or persisted, and the exact dispatch receipt is already durable.

### 4.2 Lock-before-cancel producer hook

Add an internal `LearningStageWorkerRegistry` helper that, under its existing registry lock, validates the live record, the exact B1 incarnation, the missing result, the payload/request/operation joins, and the durable dispatch receipt, then writes the fixed file create-new-or-byte-identical.

Call that helper only inside `_cancel_benchmark_v2_hybrid_workflow_service`, while the existing operation lock is held, immediately before the existing registry cancellation call. Required order:

```text
operation lock acquired
  -> registry lock acquired
  -> pre-cancel body file fsynced
  -> registry lock released
  -> existing cancel_by_operation path
  -> operation lock released
```

Any mismatch, already-complete body, missing exact process, missing dispatch receipt, or different existing bytes aborts cancellation evidence and fails the probe. This is internal persistence only: no `WorkflowService` public API, callback signature, response field, or B1 contract changes.

---

## 5. Provider-native raw evidence reuse

Provider cleanup is retained at the fixed worker-local path:

```text
logs/workflow-workers/<worker_id>.benchmark-v2-provider-cleanup-raw.json
```

This file introduces no new contract. Its bytes are exactly one already-versioned provider-native document after the existing provider validator succeeds. The worker writes it create-new-or-byte-identical before the outer B1 cleanup receipt; it must not wrap, summarize, or alter the source. Lifecycle validation rereads the retained bytes and, where the native document references subparents, resolves those parents from their existing producer-owned fixed stores.

| Provider | Authoritative raw reuse | Required independent checks |
|---|---|---|
| Omni | `omniparser_invocation_cleanup_observation_v1`, resolved originally by `provider_invocation_id` and retained byte-identically | exact Omni PID/create-time equals dispatch identity; exact Job acquisition; nested process-scope cleanup has at least three zero samples; provider/descendant/listener/lease residue arrays are empty; inventory observable; cleanup verified |
| Qwen | `qwen_model_request_owner_receipt_v1` and `qwen_model_request_cleanup_receipt_v1`, resolved by exact `model_request_id` from the existing Qwen owner store | exact lease/incarnation/profile joins dispatch; exact server PID/create-time; termination ref; scope stable-zero ref with at least three observations; listener-zero, no-active-lease, and no-owned-runtime parents all reopen and validate |
| VISTA | `hybrid_provider_cleanup_receipt_v2` embedding `hybrid_vista_cleanup_evidence_v2`, resolved from existing cooperative cleanup/result reconciliation and retained byte-identically | exact model lease/incarnation/profile and every PID/create-time join dispatch; provider probes are observable; nested process-scope cleanup has at least three zero samples; provider/helper/descendant/listener/lease residue is empty |

All three also reuse, without changing B1, the exact outer-worker chain:

```text
benchmark_worker_launch_identity_anchor_v1
benchmark_worker_scope_assignment_v1
benchmark_worker_exit_join_observation_v1
benchmark_worker_stable_zero_observation_v1
benchmark_worker_cleanup_finalization_intent_v1
benchmark_worker_cleanup_receipt_v1
```

The lifecycle validator derives their existing filenames from trusted `worker_root` plus `worker_id`, rereads each document, invokes the existing B1 validators, and requires one continuous predecessor/identity chain. The B1 stable-zero artifact must contain at least three genuinely captured empty Job samples. Termination is `same_incarnation_exited` only when the exit/join and absence observations bind the exact launch-anchor PID/create-time; a status string is insufficient.

If cooperative cancel does not currently expose a complete Omni or VISTA provider-native document, the only permitted producer repair is inside the existing `workflow_worker.py` provider reconciliation path: finish the existing provider cleanup, validate the native document, and retain its exact bytes before outer B1 finalization. Do not fabricate missing provider evidence from the service terminal and do not add a provider adapter/model-server hook. If the native producer never created the required repeated zero observations, stop under §9 rather than counting repeated reads of one observation.

---

## 6. Independent receipt and runner validation

### 6.1 Lifecycle rebuild

Shrink `BenchmarkV2Runtime.finalize_probe_receipt` to pass stable local locators and trigger timing; remove `_probe_runtime_profile_identity` from authority and remove runtime-authored body/termination/stable-zero parents. `validate_benchmark_v2_lifecycle_probe_receipt_v2` takes trusted local `runtime_state_root`, `worker_root`, and `attempt_dir` arguments and rebuilds:

- provider/profile from contract A plus the exact dispatch journal;
- body state/time from contract B;
- exact termination from the B1 launch/exit/absence chain;
- Job stable zero from B1 samples;
- provider process/listener/lease zero from the retained native cleanup document and its raw parents;
- attempt/operation/request/cleanup joins from the canonical attempt and runner ledgers.

Every supplied receipt field must equal the rebuilt value. Missing files, symlinks/path escapes, noncanonical bytes, mismatched hashes, duplicate identities, wrong provider/kind, stale create time, fewer than three genuine samples, unresolved refs, or extra fields fail closed.

### 6.2 Runner result and P0 summary

`_validate_probe_result` must reopen the attempt directory, call the lifecycle raw rebuild, and compare the exact result/receipt bytes. It must not accept a prevalidated runtime object as proof.

P0 summary semantics are exactly:

```text
collection_policy = "one_requested_attempt_per_provider"
status = "terminal"
```

The P0 summary makes no selection-authority or PASS claim. Remove `selection_policy` from the P0 summary v2 closed field set. `attempts` remains the three requested terminal result objects in provider order for that invocation. `terminal` means collection ended and all three attempts have terminal result files; it does not authorize any cell.

`first_complete_verified_attempt_per_cell` belongs only to P1. P1 independently enumerates the canonical runner ledgers in append order, rebuilds each candidate from raw parents, selects the first complete verified attempt per Omni/Qwen/VISTA × cancel/timeout cell, and then constructs the existing public bundle. The public bundle field set, required matrix, pathless refs, and all accepted/scorer/provider/dependency contracts remain unchanged.

---

## 7. Four TDD slices and commit boundaries

### Task 1: Dispatch raw runtime/profile parent

**Files:**
- Modify: `app/learn/hybrid/benchmark_v2_dispatch_attestation.py`
- Test: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation.py`

- [ ] Add failing tests proving the parent contains full exact runtime/profile evidence, is durable before the journal append, survives a simulated append failure as a nonjoining orphan, and rejects different existing bytes.
- [ ] Run: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation.py -k "runtime_parent or profile_parent or create_new"`
- [ ] Expected RED: parent helpers/order do not exist and the current attestor returns only an opaque runtime digest.
- [ ] Implement only contract A and the refactor needed to return full attested values; keep the dispatch receipt shape unchanged.
- [ ] Rerun the same command; expected PASS.
- [ ] Review the diff and remove any provider-profile reconstruction from `benchmark_v2_runtime.py` that this slice makes obsolete.
- [ ] Commit boundary when authorized: `fix(benchmark-v2): persist dispatch raw runtime parent`

### Task 2: Lock-before-cancel body and provider raw retention

**Files:**
- Modify: `app/learn/workflow_worker.py`
- Modify: `app/learn/workflow_service.py`
- Test: `tests/test_learning_workflow_stage_worker.py`
- Test: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py`

- [ ] Add failing registry tests for exact running incarnation, result absence, create-new-or-identical replay, mismatch rejection, and byte-identical Omni/Qwen/VISTA native cleanup retention.
- [ ] Add a failing service ordering test that records operation-lock, registry persistence, and cancel events and asserts persistence occurs before cancel without changing the public response shape.
- [ ] Run: `uv run pytest -q tests/test_learning_workflow_stage_worker.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py -k "pre_cancel_body or provider_cleanup_raw or lock_before_cancel"`
- [ ] Expected RED: no pre-cancel parent exists and native cleanup bytes are not retained at the fixed worker path.
- [ ] Implement contract B, native raw retention, and the single internal service call-order change. Do not change B1 validators or public service APIs.
- [ ] Rerun the same command; expected PASS.
- [ ] Commit boundary when authorized: `fix(benchmark-v2): persist pre-cancel and provider raw evidence`

### Task 3: Receipt v2 raw-parent rebuild

**Files:**
- Modify: `app/learn/hybrid/benchmark_v2_lifecycle.py`
- Modify: `app/learn/hybrid/benchmark_v2_runtime.py`
- Test: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py`
- Test: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py`

- [ ] Replace tests that pass runtime-authored parent mappings with filesystem fixtures matching contracts A/B, retained provider-native bytes, and the existing B1 chain.
- [ ] Add matched negative controls for profile substitution, PID reuse/create-time mismatch, body written after cancel, one/two zero samples, opaque-only cleanup ref, reused provider cleanup, and runtime-injected empty arrays.
- [ ] Run: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py -k "probe_receipt_v2 or probe_raw_parent"`
- [ ] Expected RED: the current implementation trusts mappings and synthesized conclusions.
- [ ] Implement fixed-path readers and independent rebuild; then delete the obsolete runtime authority code instead of leaving a fallback.
- [ ] Rerun the same command; expected PASS.
- [ ] Commit boundary when authorized: `fix(benchmark-v2): rebuild probe receipt from raw parents`

### Task 4: Runner collection semantics and P1 boundary

**Files:**
- Modify: `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py`
- Test: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py`

- [ ] Add failing tests that P0 emits only `collection_policy="one_requested_attempt_per_provider"`, `status="terminal"`, never emits a first-complete policy, and rejects a result whose raw parents cannot be reopened.
- [ ] Retain/add a P1 boundary test proving first-complete selection comes only from canonical-ledger enumeration and the existing public bundle fields are unchanged.
- [ ] Run: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py -k "probe_result_v2 or probe_summary_v2 or first_complete"`
- [ ] Expected RED: the current P0 summary falsely claims first-complete/PASS authority.
- [ ] Implement the minimal summary/result changes and remove unused projection helpers.
- [ ] Rerun the same command; expected PASS.
- [ ] Commit boundary when authorized: `fix(benchmark-v2): separate P0 collection from P1 selection`

After every slice, review `git diff --stat` and `git diff --check`; if the production diff grows rather than replacing the known synthetic path, stop and shrink it before continuing.

---

## 8. Verification before any actual benchmark

Run the four focused commands above, then the complete affected suite:

```powershell
uv run pytest -q `
  tests/test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation.py `
  tests/test_learning_workflow_stage_worker.py `
  tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py `
  tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py `
  tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py `
  tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py
```

Required preflight assertions:

- every receipt validator was given only trusted local roots plus the receipt/result locator;
- deleting or changing any fixed raw parent makes validation fail;
- profile, process incarnation, body, termination, and stable-zero conclusions are rederived, not copied;
- all three provider-native artifacts reopen and validate from disk;
- P0 summaries contain collection semantics only;
- P1 first-complete tests still enumerate the canonical ledgers and the public bundle field set is unchanged;
- no public contract snapshot changed;
- no actual model/provider/GUI command ran.

---

## 9. Timebox and fail-closed stop

This is PASSABLE in approximately three hours only if implementation first shrinks the current incorrect P0 diff, all existing provider-native documents are already producible during cooperative cancellation, and P1/public work is not expanded. Allocate roughly 35 minutes to slice 1, 50 minutes to slice 2, 55 minutes to slice 3, 25 minutes to slice 4, and 15 minutes to focused verification/diff review.

Stop before any actual benchmark and report BLOCKED if any of these is true:

- an exact dispatch runtime/profile parent cannot be produced and reopened at the fixed path;
- the exact B1 worker PID/create-time chain cannot be freshly rebuilt;
- `not_complete` cannot be durably observed under lock before cancel mutation;
- any provider cleanup is available only as an opaque ref or runtime projection;
- any required process/Job/listener/lease zero claim lacks the native raw observations, including at least three genuine stable-zero samples;
- a test passes only by injecting runtime-authored parent mappings;
- the repair requires a model-server/adapter/process-scope/public-contract/B1 redesign or a seventh incremental file;
- the focused affected suite does not pass within the timebox.

On BLOCKED, retain no PASS receipt, no first-complete claim, no public probe-authority bundle, and no holdout authorization. Preserve the nonauthorizing local failure/cleanup artifacts, verify cleanup through existing B1/provider paths, and end without invoking actual benchmark, model, provider, or GUI execution.
