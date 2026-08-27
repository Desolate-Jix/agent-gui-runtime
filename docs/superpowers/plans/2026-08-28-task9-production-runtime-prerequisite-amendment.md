# Task 9 Production Runtime Prerequisite Amendment

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Follow TDD, the repository implementation loop, and small-step Git checkpoints.

**Goal:** Close only the three production seams that prevent the frozen Task 9 CLI from running Benchmark-v2 through Task 3–8 without private orchestration access.

**Architecture:** Add one benchmark-scoped production runtime facade. It prepares real screenshot/UIA/OCR lineage, delegates all workflow state changes to the existing production WorkflowService, requires a durable fresh attestation immediately before each provider dispatch, and reconciles attempts from a sealed resource journal. The runner receives one facade and never sees `.composition`, the workflow store, Registry, private labels, or action APIs.

**Tech Stack:** Python 3.11+, pytest, UEI v1 objects, WorkflowService, Win32 suspended processes/Job Objects/HWND/UIA, existing Qwen/Omni/VISTA managed provider lifecycles.

**Spec:** `docs/superpowers/plans/2026-08-26-portfolio-hybrid-v1-1-benchmark-v2-plan.md`, Task 9.

## Global Constraints

- Preserve Hybrid v1.1, the four public Contracts, the four frozen benchmark arms, the 120-case corpus, and the 24 five-case screen groups.
- No new model, provider router, HTTP/panel route, click, input, action authority, publication authority, or general Windows supervisor.
- No real model/provider/window run while implementing this amendment; use deterministic fakes and sealed fixtures only. Real execution begins at Task 13 and remains paused by operator instruction.
- Do not touch or stage `tests/test_agent_runtime_actual_adapter_portfolio_v1.py`.
- Every resource acquisition is preceded by append+fsync intent evidence and followed by exact-incarnation cleanup evidence.
- Every artifact remains non-authorizing: `artifact_is_authorization=false`, `execute_binding_enabled=false`; UI artifacts also remain `display_only=true`.
- `DISPATCHED != BODY_COMPLETE != EFFECT_VERIFIED`; a lost response is reconciled and never blindly retried.
- The runner may import one production runtime getter but may not import `.composition`, store, Registry, handler internals, private scorer/Gold, or action surfaces.

---

### Task U0: Prepare exact production screen groups

**Files:**

- Create: `app/learn/hybrid/benchmark_v2_runtime.py`
- Create: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py`
- Modify: `app/learn/hybrid/benchmark_v2_window_owner.py`
- Modify: `scripts/portfolio_hybrid_v1_1_test_window_v2.py`
- Modify: `app/learn/recognition/uei/builtin_learning_projection.py`
- Modify: `app/learn/recognition/uei/projections.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py`
- Modify: `tests/test_uei_v1_projections.py`

**Interfaces:**

```python
class BenchmarkV2ScreenGroupIterator(Iterator[Mapping[str, object]], Protocol):
    def close(self) -> None: ...
    def __enter__(self) -> "BenchmarkV2ScreenGroupIterator": ...
    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

class BenchmarkV2ProductionRuntimePort(Protocol):
    def load_provider_manifest(self, *, path: Path) -> Mapping[str, object]: ...
    def prepare_screen_groups(
        self,
        *,
        provider_manifest: Mapping[str, object],
        partition: str,
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> BenchmarkV2ScreenGroupIterator: ...

def get_production_benchmark_v2_runtime() -> BenchmarkV2ProductionRuntimePort: ...

def snapshot_owned_window(*, owner: Mapping[str, object]) -> Mapping[str, object]: ...

def seal_builtin_uia_evidence(
    *,
    project_root: Path,
    image_path: Path,
    capture_lineage_ref: Mapping[str, str],
    capture_envelope: object,
    uia_snapshot: Mapping[str, object],
    window_binding: Mapping[str, object],
) -> dict[str, str]: ...
```

`prepare_screen_groups` is lazy: it owns at most one test window at a time. For each screen group it performs:

```text
validated provider manifest and corpus
-> exact corpus PNG bytes and SHA
-> create-only byte-identical copy under artifacts/screenshots
-> launch exact noninteractive owned HWND
-> capture exact UIA snapshot from that HWND
-> seal one capture identity
-> run built-in OCR on the exact PNG
-> seal real OCR provider-safe evidence
-> seal real UIA provider-safe evidence
-> seal one hybrid capture bundle
-> compose one closed Task 8 screen-group start
```

The existing Task 4 helper must accept PNG without transcoding. The attempt-owned byte-identical copy uses the existing `app/learn/hybrid/capture.py` boundary `PROJECT_ROOT/artifacts/screenshots`; it is also the exact path displayed by Task 4 and consumed by Task 5/Task 8. It seals both original-file SHA and deterministic decoded-pixel SHA, so the copy retains the corpus SHA without weakening the capture-root boundary.

The returned iterator is a mandatory owner context. Task 9 must consume it with `with runtime.prepare_screen_groups(...) as groups:` (or an equivalent `try/finally: groups.close()`). Exhaustion, an early `break`, and consumer exceptions must all exit that owner context before the runner retains or returns control; cleanup must not depend on garbage collection.
If exact-owner cleanup fails transiently, the iterator remains cleanup-pending rather than closed; a subsequent `close()` retries the same runtime-owned resource and cannot advance to a second screen group.
The runtime registers a private cleanup owner immediately after `launch_owned_window` succeeds, before OCR/UIA/bundle preparation can fail. Ready `_active` state and pending-cleanup state are distinct; admission rejects either one, and only a verified close of the matching owner token clears them.

- [x] Add failing tests proving PNG launch preserves exact file SHA/pixel SHA and rejects byte tampering.
- [x] Run `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py -k "png or tamper"` and confirm the expected failure.
- [x] Implement native PNG decode in the existing test-window helper and owner validation; retain BMP compatibility.
- [x] Rerun the focused window tests to green.
- [x] Add failing runtime tests proving 120 cases become exactly 24 groups of five, only one group is live at a time, and the two evidence parents share one capture lineage.
- [x] Add a retained-iterator early-break test proving explicit owner-context exit closes the exact live group once.
- [x] Add a transient cleanup failure test proving a second `close()` retries the same exact owner and records one verified cleanup.
- [x] Add a prepare-failure plus transient-cleanup test proving the pending exact owner survives until retry and blocks a second group.
- [x] Add negative tests for empty/fabricated OCR or UIA parents, missing source, stale HWND/PID/create-time, wrong corpus SHA, and runner-facing private internals.
- [x] Run `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py` and confirm the failures are caused by the absent facade/evidence function.
- [x] Implement the facade, real `OCRService.scan_image` projection through `seal_builtin_ocr_evidence`, exact UIA projection through `seal_builtin_uia_evidence`, and lazy group cleanup.
- [x] Run `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py tests/test_learn_hybrid_capture.py`.
- [x] Commit `feat(benchmark-v2): prepare exact production screen groups`.

---

### Task U1: Attest every provider dispatch at the dispatch owner

**Files:**

- Create: `app/learn/hybrid/benchmark_v2_dispatch_attestation.py`
- Create: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation.py`
- Modify: `app/learn/hybrid/windows_process_scope.py`
- Modify: `app/learn/recognition/uei/omniparser_shadow_adapter.py`
- Modify: `app/core/model_server.py`
- Modify: `app/learn/calibration_sequence.py`
- Modify: `app/operation/observe/screen_reader.py`
- Modify: `app/learn/workflow_service.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `app/learn/hybrid/benchmark_v2_incumbent_operation.py`
- Modify: `app/learn/hybrid/benchmark_v2_actual.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py`

**Interfaces:**

```python
def install_benchmark_dispatch_attestor(
    *, dispatch_context: Mapping[str, object]
) -> ContextManager[None]: ...

def attest_benchmark_provider_dispatch(
    *,
    provider: Literal["omni", "qwen", "vista"],
    operation_ref: Mapping[str, object],
    window_binding: Mapping[str, object],
    provider_runtime: Mapping[str, object],
) -> Mapping[str, object]: ...

def spawn_process_in_scope(
    command: Sequence[str],
    *,
    scope_name: str,
    before_resume: Callable[[Mapping[str, object]], None] | None = None,
    **existing_options: object,
) -> object: ...

def attest_managed_model_dispatch(
    *, model_lease: Mapping[str, object], dispatch_context: Mapping[str, object]
) -> Mapping[str, object]: ...
```

The WorkflowService creates the closed dispatch context from server-owned operation/window/capture parents. The spawned worker installs it; client payload cannot supply or override it. Each provider keeps its own sealed server-issued context ref, including the exact operation revision and content SHA that were current when that provider context was issued. Later workflow-store revision changes do not rewrite earlier provider lineage. The attestor appends and fsyncs a receipt before the call can cross the provider boundary. Before Registry adoption mutates state, the service requires the worker-projected context map to equal the durable service binding and validates the exact provider order, count, operation refs, journal rows, contiguous indices, and predecessor chains.

Precise cut-points:

- Omni: `CreateProcess(suspended) -> Job assignment -> PID/create-time observation -> attestation receipt -> ResumeThread`. Callback failure terminates the still-suspended exact child.
- Hybrid Qwen: after the managed lease exists, immediately before the model/HTTP call, under the same cancellation fence.
- VISTA: immediately before every `locate(...)` batch call; one receipt per batch.
- Incumbent Qwen: immediately before every `provider.analyze(...)`; one receipt for each of the five incumbent operations.
- Fusion and Review: zero provider-dispatch receipts.

- [x] Write failing tests for the exact event order and receipt count at all four cut-points.
- [x] Write failing negative tests for stale operation revision, HWND/PID/create-time, Job membership, lease/profile/socket, provider mismatch, short journal writes, receipt fsync failure, and cancellation races; every case asserts zero dispatch.
- [x] Run the focused dispatch tests and confirm the expected failures before implementation.
- [x] Implement the closed provider-specific contexts, suspended-child hook, managed-model attester, and provider-specific cut-point calls.
- [x] Add pre-adoption WorkflowService validation and return only verified receipt refs in Task 8 projections.
- [x] Add deterministic multi-revision coverage for `Omni -> Qwen -> Fusion -> VISTA x2 -> Review`, including stale resealed provider-context rejection.
- [x] Run focused U1, incumbent non-real, worker-binding non-real, provider/cancellation, and Hybrid worker verification; obtain an independent PASS with no Critical or Important findings.
- [x] Commit `feat(benchmark-v2): attest every provider dispatch`.

---

### Task U2: Reconcile benchmark attempts and lifecycle probes

**Files:**

- Modify: `app/learn/hybrid/benchmark_v2_runtime.py`
- Modify: `app/learn/hybrid/benchmark_v2_lifecycle.py`
- Modify: `app/learn/hybrid/benchmark_v2_dispatch_attestation.py`
- Modify: `app/learn/hybrid/benchmark_v2_incumbent_operation.py`
- Modify: `app/learn/workflow_service.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py`
- Create: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime_recovery.py`

**Interfaces:**

```python
class BenchmarkV2ProductionRuntimePort(Protocol):
    def run_actual_screen_group(
        self, *, provider_group: Mapping[str, object],
        attempt_ref: Mapping[str, object], attempt_dir: Path,
    ) -> Mapping[str, object]: ...
    def begin_probe(
        self, *, provider_id: str, probe_kind: str,
        provider_manifest: Mapping[str, object], attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> Mapping[str, object]: ...
    def read_server_journal(
        self, *, probe_context: Mapping[str, object]
    ) -> Mapping[str, object]: ...
    def trigger_probe(
        self, *, probe_context: Mapping[str, object], probe_kind: str,
        request_in_flight_journal: Mapping[str, object],
    ) -> Mapping[str, object]: ...
    def cleanup_attempt(
        self, *, attempt: Mapping[str, object], reason: str
    ) -> Mapping[str, object]: ...
    def resource_counts(self) -> Mapping[str, int]: ...
```

The benchmark-only resource journal has the closed progression:

```text
prepared -> request_in_flight -> body_complete -> terminal
```

Probe selection can name only `omni`, `qwen`, or `vista`. Earlier cascade stages run normally until the selected stage reaches `request_in_flight`. Trigger and recovery bind the exact server-issued dispatch context and the same PID/create-time/Job or managed lease incarnation. A durable `service_start_intent` precedes WorkflowService start; a read-only exact lookup closes the crash window before `service_started` without retrying producer creation. Cleanup order is WorkflowService cancel/reconcile, Task 4 HWND/Job close, authoritative provider/listener/lease cleanup, then stable-zero verification. Aggregate termination strings alone never prove same-incarnation cleanup.

Task 9 actual execution follows the same U2 rule through the facade: a durable screen-group service intent is fsynced first, `lookup_hybrid_operation(...)` runs before any start, the exact service result is fsynced before Task 8 receives it, and only an identical create-only projection replay is idempotent. The facade owns the private WorkflowService/window/lifecycle/prediction composition; the runner receives none of those components.
Each incumbent start also requires a durable intent/result pair and recovery through `lookup_incumbent_observe(provider_case_ref=..., window_binding=...)`; recovery must never replace lookup with a blind start. Before the prediction sink may publish, the runtime must consume the WorkflowService-owned `attest_actual_operations_stable_zero(operation_refs=...)` result for the exact six terminal operation refs and the exact window-close receipt. Runtime aggregate `resource_counts()` remains diagnostic and cannot authorize stable-zero.

- [x] Add failing tests for crash before output, after service start, after window launch, during each provider, body-complete/response-lost, duplicate cleanup, stale attempt ref, PID reuse, and start-before-journal hard crashes.
- [x] Add a service-owned fresh-store initializer and a read-only exact lookup; prove missing intent returns `None` and no recovery path blindly calls start.
- [x] Project the exact pathless provider dispatch context and verify the U1 receipt against its issued revision rather than the later workflow revision.
- [x] Implement append+fsync resource events, bounded journal polling, idempotent reconciliation, best-effort exact cleanup, and closed stable-zero receipts.
- [x] Bind trigger success to authoritative same-incarnation cleanup evidence for Omni, Qwen, and VISTA; reject completed, cross-operation, cross-request, cross-lease, cross-Job, and aggregate-only results before `probe_triggered`.
- [x] Run deterministic U1/U2/runtime/lifecycle/WorkflowService/worker/model-cancellation focused suites and obtain an independent PASS with no Critical or Important findings.
- [x] Commit `feat(benchmark-v2): recover benchmark attempts and probes`.

---

### Task U3: Finish Task 9 production runner wiring

**Files:**

- Modify: `app/learn/hybrid/benchmark_v2_runtime.py`
- Modify: `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py`
- Modify: `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py`

**Interfaces:**

- The script imports only `get_production_benchmark_v2_runtime()` for production orchestration.
- Actual screen groups call only `runtime.run_actual_screen_group(provider_group=..., attempt_ref=..., attempt_dir=...)`; the getter exposes no service/window/lifecycle/sink/component getter.
- Existing exact CLI and attempt-ledger formats remain unchanged.

- [x] Add the narrow public actual-screen-group facade with hybrid and incumbent U2 lookup-before-start recovery, exact active group/attempt/window binding, WorkflowService-owned stable-zero attestation, and create-only durable projection replay.
- [x] Prove journal fsync failure, stale attempt, missing dispatch/cleanup evidence, and different-content replay fail closed without real GUI/provider/model resources.
- [ ] Replace the temporary production-blocked tests with failing tests proving dry-run, actual, probes, and cleanup delegate through the real facade without fake injection.
- [ ] Remove `_ProductionRuntime._unavailable` and the early `RunnerProductionBlocked` branches; preserve fail-closed validation errors.
- [ ] Run `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py`.
- [ ] Run `uv run python -m py_compile scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py` and `git diff --check`.
- [ ] Obtain one independent read-only review of runner inputs, public seam usage, dispatch timing, recovery, and zero-action evidence.
- [ ] Commit `feat(benchmark-v2): add service-bound benchmark runner`.

## Dependency DAG and stop condition

```text
U0 -> U1 -> U2 -> U3/Task9 -> Task10 -> Task11 -> Task12 -> PAUSE before Task13
```

Do not branch into stronger local-admin tamper resistance, general process supervision, another provider, remote/MCP execution, GUI action support, or unrelated hardening. If a finding cannot produce a wrong benchmark, cross-run contamination, orphaned owned resource, or false cleanup/dispatch receipt, record it as a limitation and continue the critical path.
