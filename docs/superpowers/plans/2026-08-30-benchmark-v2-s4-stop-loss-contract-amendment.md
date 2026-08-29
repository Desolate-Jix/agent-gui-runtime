# Benchmark v2 S4 Stop-Loss Contract Amendment

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this amendment one independently verified slice at a time.

**Goal:** Correct the minimum internal contradictions that block S4 without reopening B1 supervision, adding a second recovery system, or delaying the actual provider benchmark for theoretical hardening.

**Authority and supersession:** This amendment is subordinate to `2026-08-26-portfolio-hybrid-v1-1-benchmark-v2-plan.md`. It supersedes `2026-08-28-benchmark-v2-scoring-bridge-prerequisite-amendment.md` only where S4.1.2 cleanup-only, S4.4 allowed files/tests, detached-recovery evidence, owner-journal authority, or private inventory conflicts with this document. It supplements the required Task 12 dependency-manifest boundary in `2026-08-29-benchmark-v2-task11-task12-evidence-boundary-amendment.md` and clarifies the S4 inventory timing in `2026-08-29-benchmark-v2-probe-authority-bridge-amendment.md`. All unrelated S1-S4 scoring, pathless evidence, Task 11A claim, P0/P1 probe, B1 cleanup, estimand, gate, leakage, safety, and actual-run contracts remain authoritative.

**Approval:** The operator explicitly approved corrections C1-C5 on 2026-08-30. They are one indivisible stop-loss correction, not a new benchmark feature.

---

## 1. Frozen scope

S4 still produces only holdout schemas, validators, consumers, tests, and final private source/test inventory. This amendment does not:

**S4 must not reopen B1/runtime supervision.** Any implementation that requires such a change is outside this amendment and stops for separate operator approval.

- modify or widen B1 supervision;
- modify `benchmark_v2_runtime.py`, `workflow_service.py`, `workflow_worker.py`, model-service supervision, or worker supervision for S4 recovery;
- create a general durable process supervisor, resource enumerator, remote witness, or second desktop runtime;
- authorize a model, provider, GUI, window, click, form mutation, network action, or score;
- rehabilitate a recovered attempt, select a later attempt, mint a second claim, or weaken stable-zero cleanup;
- migrate, delete, replace, or repair an existing production authorization, claim, sentinel, registry anchor, or raw ledger;
- treat stdout, a detached file, report prose, or a success return value as execution authority.

The only normal score-eligible holdout chain remains:

```text
opened -> body_complete -> cleanup -> result
```

Every recovery branch remains permanently non-selectable and non-scorable.

---

## 2. C1 — Exact production owner-journal authority

The one production owner-journal authority is frozen as:

```text
PRODUCTION_HOLDOUT_OWNER_JOURNAL_ROOT_TOKEN =
  "runtime_state/benchmark-v2-worker-window-binding-authority"

PRODUCTION_HOLDOUT_OWNER_JOURNAL_ROOT =
  resolve_from_compile_time_ROOT(PRODUCTION_HOLDOUT_OWNER_JOURNAL_ROOT_TOKEN)
```

It must be byte-identical after canonical resolution to both:

- `app.learn.hybrid.benchmark_v2_runtime._AUTHORITY_ROOT`; and
- the production server worker-window-binding authority root in `benchmark_v2_worker_binding.py`.

Task 11A authorization payload v2 field `absolute_owner_journal_root`, its claim payload copy, and every production backend equality check must bind this exact root. The former production value under `%LOCALAPPDATA%\AgentGuiRuntime\PortfolioHybridBenchmarkV2\Claims\owner` is not an owner-journal authority and must not be accepted for a new authorization.

Test backends retain their isolated test-owned owner-journal root. A test root must not overlap the production owner root, claim roots, ledger roots, or another test root.

There is no migration path. If a production authorization, file sentinel, HKCU claim, or claim envelope bound to a different owner root exists, the release fails permanently before acquisition or dispatch. Do not delete, rewrite, mirror, migrate, or mint a parallel claim namespace.

This correction fixes wrong binding. It does not change window-owner semantics or add an owner-journal discovery API.

---

## 3. C2 — Narrow cleanup-only recovery

### 3.1 Authority and derivation

`--cleanup-only` must validate the exact native authorization ref, fixed authorization object, exact claim anchors, and `EXACT_HOLDOUT_COMMAND`. It then derives the authorized output root, claim-bound attempt ID, attempt directory, and complete raw holdout attempt ref from authorization and claim only.

It must not use any of the following as cleanup authority:

- raw event `attempt_dir`;
- a directory glob or recursive search;
- CWD or a default output directory;
- a caller-supplied output root;
- a last parseable or guessed event;
- a PID, HWND, listener, lease, or process selected by enumeration.

Any mismatch is detected before append or resource operation.

### 3.2 Existing Runtime cleanup only

Cleanup-only may call only the existing exact-attempt Runtime cleanup path:

```text
runtime.cleanup_attempt(
  attempt=<claim-and-authorization-derived exact attempt ref>,
  reason="cleanup_only_after_interrupted_holdout_attempt"
)
```

It must then obtain a fresh exact resource-count map and require every count to be zero. The existing Runtime attempt journal and cleanup receipt are the only durable cleanup evidence for a ledger-damaged attempt. This amendment adds no detached cleanup authority and no alternative resource supervision.

AccessDenied, owner-journal or Runtime-journal absence, API failure, identity ambiguity, receipt mismatch, nonzero resources, or inability to re-attest stable zero is `cleanup_indeterminate`. It blocks the release, performs no blind retry, guesses no replacement identity, and cannot be converted into PASS by report prose or a later attempt.

### 3.3 Canonical interrupted chain

When the entire fixed `holdout/attempt-events.jsonl` chain is canonical and its legal tail is `opened` or `body_complete`:

1. derive and perform the exact existing Runtime cleanup;
2. require fresh stable zero;
3. use the runner-only typed appender to append exactly one `event_kind=recovery_cleanup` with exact reason `cleanup_only_after_interrupted_holdout_attempt`;
4. make that event a permanent terminal failure branch with `selection_eligible=false`;
5. on reinvocation, validate the byte-identical terminal event and append nothing.

A recovery-cleanup event cannot transition to normal cleanup/result and cannot enter a materializer, scorer, authorizer, or final report as accepted holdout evidence.

### 3.4 Missing or damaged attempt ledger

When the attempt ledger is missing, truncated, noncanonical, or hash-invalid:

- preserve all existing bytes exactly;
- never append, truncate, rewrite, synthesize, skip, mirror, or repair the ledger;
- allow exact cleanup only when the independently derived existing Runtime journal proves the same attempt and produces a valid stable-zero terminal cleanup receipt;
- keep the run permanently ineligible for materialization and scoring;
- fail with `cleanup_indeterminate` if that independent Runtime evidence cannot be verified.

The following prior S4.1.2 requirements are superseded and deferred as limitations:

- `benchmark_v2_holdout_detached_recovery_cleanup_evidence_v1`;
- `benchmark_v2_holdout_detached_recovery_cleanup_verified_projection_v1`;
- `owner_journal_projection_refs`;
- missing/partial/noncanonical/hash-invalid detached evidence publication;
- reconstruction when both attempt and Runtime journals are unavailable or damaged;
- generalized process/window/listener/lease discovery outside existing exact Runtime ownership.

No new public cleanup contract is created by this amendment. Cleanup evidence remains benchmark non-authorizing evidence and never grants execution or score eligibility.

---

## 4. C3 — Minimal S4 allowlist correction

The existing S4.4 allowed files remain authoritative, with only these five additions:

```text
app/learn/hybrid/benchmark_v2_public_score.py
app/learn/hybrid/benchmark_v2_pathless.py
app/learn/hybrid/benchmark_v2_lifecycle.py
tests/test_portfolio_hybrid_v1_1_benchmark_v2_pathless.py
tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py
```

Purpose is closed:

- `benchmark_v2_public_score.py` receives the already required holdout public-v3/binding validation without importing private scorer authority;
- `benchmark_v2_pathless.py` registers and validates the distinct holdout pathless contracts already frozen by S4.1.2;
- `benchmark_v2_lifecycle.py` verifies the holdout lifecycle/stable-zero projection already required by S4;
- the two tests provide focused regression coverage for those existing responsibilities.

This addition does not authorize changes to B1/runtime supervision, service/worker code, unrelated provider code, or a new recovery subsystem. Any further allowlist expansion requires separate operator approval.

---

## 5. C4 — Required Task 12 dependency-manifest precondition

The final report canonical fixed-flag order contains:

```text
--leakage-review
--dependency-manifest
--ledger-root
```

The only accepted dependency-manifest token is:

```text
runtime_state/portfolio-hybrid-v1-1/benchmark-v2/release-dependency-manifest.json
```

Final report assembly must load and call:

```text
validate_dependency_manifest_for_final_report(...)
```

before probe-authority validation, holdout/regression joins, report construction, or output creation. Missing input, non-release build mode, stale SHA, non-PASS result/review, wrong argv/DAG, ref drift, alias, or path drift fails before report output.

The dependency manifest remains a publication precondition. It does not add a final-report field, change the final-report contract/version, enter Task 11 authorization, or authorize execution.

---

## 6. C5 — Final private inventory correction

At S4, add the following exact existing source/test files to the shared private final-seal inventory:

```text
app/learn/hybrid/benchmark_v2_public_score.py
app/learn/hybrid/benchmark_v2_probe_authority.py
scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py
scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py
scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py
tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py
tests/test_portfolio_hybrid_v1_1_release_gate_v2.py
```

`benchmark_v2_probe_authority.py` is production verification source code, not a generated probe runtime artifact. It therefore belongs in private `code_sha256_by_path`. Generated `probe-authority.json`, raw ledgers, receipts, claims, journals, reports, and other runtime artifacts do not belong in source inventory.

All source/test files already present in inventory whose bytes changed through S4 must be rehashed. Missing, extra, alias, symlink/reparse, or byte-drifted inventory entries fail the final seal.

These seven entries are private final-seal source/test inventory only. Do not add them to the provider manifest, `release_code_refs`, runtime profile refs, or provider-dispatch imports.

---

## 7. Required implementation order and acceptance

The corrected order remains:

```text
S4 fixed holdout attempt chain
  -> accepted holdout/pathless/lifecycle projections
  -> holdout scorer and public-v3 binding
  -> offline holdout materializer
  -> Task 11/12 holdout consumers
  -> final private inventory
  -> deterministic integration and independent review
```

Every implementation slice must be test-first, independently verifiable, and committed separately. No implementation slice may produce a real authorization, claim, anchor, model result, GUI/window, service/process, score, or final seal.

The corrected S4 acceptance requires:

- normal four-event chain is the only score-eligible chain;
- canonical interrupted chains append exactly one terminal recovery-cleanup event;
- damaged ledgers remain byte-identical and permanently ineligible;
- cleanup ambiguity fails closed without detached evidence or generalized discovery;
- actual, cleanup-only, and materializer derive the one authorized root before side effects;
- public output contains no native path, native three-field authorization ref, raw attempt ref, raw pre-result object, owner-journal root, PID, HWND, listener, or lease identity;
- Task 12 validates the exact release dependency manifest before any output;
- private inventory binds every final source/test file above, while provider manifest remains unchanged;
- focused holdout, runner, pathless, lifecycle, scoring, seal, leakage, and release-gate tests pass;
- `git diff --check`, UTF-8 validation, and relevant `py_compile` checks pass;
- B1/runtime supervision files remain unchanged by this amendment.

Anything requiring a detached recovery proof, new public recovery schema, alternate resource discovery, second claim, anchor migration, or B1/runtime supervision change is out of scope and requires separate explicit operator approval.
