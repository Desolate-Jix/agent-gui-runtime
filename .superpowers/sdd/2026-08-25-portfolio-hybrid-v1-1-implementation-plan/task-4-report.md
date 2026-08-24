# Task 4 report — candidate-ID-closed Qwen semantic binding

## Status

DONE_WITH_CONCERNS. Implemented and committed the exact managed `panel_learning_hybrid_qwen_binding` slice without invoking a real model, GPU, GUI, browser, or action path. The only concerns are nine unrelated pre-existing failures in the full panel test file caused by absent historical artifact fixtures and one stale mojibake assertion; all Task 4-focused panel checks pass.

## Design classification

This was a bounded extension of the approved Portfolio Hybrid v1.1 plan: reuse the Task 2 capture bundle, Task 3 immutable Omni inventory, existing understanding/Qwen model profile, managed worker lifecycle, model cancellation, and panel allowlist. The supplied brief and binding decisions were treated as the approved short design; no new subsystem, dependency, server, public UEI contract, or API architecture was introduced.

## Changed

### Closed request and parser

- Added `build_qwen_binding_request(capture_bundle, omni_inventory) -> dict`.
  - Revalidates the sealed Omni inventory and exact capture identity.
  - Includes the canonical screenshot artifact ref/SHA/dimensions/coordinate space, immutable candidate IDs with original Omni geometry, and the sealed same-capture OCR/UIA context.
  - Requires exactly one OCR and one UIA source, both bound to the same capture lineage.
  - Produces a content-addressed `hybrid_qwen_binding_request_v1` without exposing a filesystem path.
- Added `parse_qwen_candidate_bindings(raw, omni_inventory) -> dict`.
  - Accepts only `bindings` and `orphan_semantics` at the outer boundary.
  - Allows binding fields only for candidate ID, role, label, description, semantic confidence, task relevance, relation, and ambiguity.
  - Rejects unknown/duplicate/omitted candidate IDs, duplicate semantic targets bound to multiple IDs, geometry, coordinates, action authority, free-created candidates, and unbound prose.
  - Defines a semantic target deterministically as the exact `(role, label, description, relation)` tuple; confidence/relevance/ambiguity cannot evade the one-target/one-candidate invariant.
  - Requires orphan IDs to use the `semantic/` namespace and exact reason `ORPHAN_SEMANTIC`; an orphan cannot use or fabricate a candidate-shaped ID.
  - Preserves UTF-8 labels exactly.

### Verified execution and artifact lifecycle

- Added `run_qwen_candidate_binding(payload, *, model_runner, cancellation_event=None) -> dict`.
  - Reloads and verifies the Task 2 bundle for the exact run/revision.
  - Revalidates Task 3's sealed inventory and exact screenshot bytes/dimensions.
  - Passes a controlled cancellation token into the model runner.
  - Converts model timeout/cancel into explicit exceptions before producing a new artifact.
  - Seals the validated `hybrid_qwen_bindings_v1` result before returning.
  - Never mutates or deletes the prior Omni inventory/artifact on timeout or cancellation.
- Added the server-owned `hybrid_qwen` task wrapper.
  - Rejects client `project_root` and injects the repository root.
  - Releases Qwen only after receiving and verifying the sealed binding artifact.

### Existing Qwen server reuse and managed lifecycle

- Added a minimal OpenAI-compatible JSON runner to `app/core/model_server.py` using the existing `understanding` profile and endpoint.
  - Uses the managed `AGENT_GUI_MODEL_REQUEST_ID` in both request body and header.
  - Sends the canonical screenshot plus the closed request; no second model server or dependency was added.
- Added sealed-artifact-gated Qwen release through the existing `stop_model_server` path.
- Extended existing model cancellation for `panel_learning_hybrid_qwen_binding` to resolve the same understanding profile and stop its server, returning the existing structured cancellation result.
- Added exact managed kind `panel_learning_hybrid_qwen_binding` to the worker and panel allowlists.
- The worker reuses existing understanding-stage resource preflight/acquisition and generic managed cancellation. Task 3's special cooperative Omni cancellation branch and public UEI contracts are unchanged.

## TDD evidence

### RED

Initial request/parser/task command:

`uv run pytest -q tests/test_learn_hybrid_qwen_binding.py tests/test_learning_workflow_stage_worker.py -k "qwen or hybrid"`

Result: exit 1; `14 failed, 3 passed, 23 deselected`. All new Task 4 tests failed because `qwen_binding.py` and `hybrid_qwen.py` did not exist.

Managed/model/panel command:

`uv run pytest -q tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_web_panel_route.py -k "qwen"`

Result: exit 1; five expected failures for the absent worker task kind/dispatch, Qwen cancellation/release helpers, and panel allowlist entry.

Additional RED regressions found during self-review:

- `uv run pytest -q tests/test_learn_hybrid_qwen_binding.py -k "fabricate_candidate"` → exit 1 because an orphan `semantic_id="candidate/fabricated"` was initially accepted.
- `uv run pytest -q tests/test_learn_hybrid_qwen_binding.py -k "extra_or_cross"` → exit 1 because a sealed context with a third duplicate OCR source was initially accepted.

Both were fixed at the parser/request boundary and rerun GREEN.

### GREEN

- Qwen unit/integration slice:
  - `uv run pytest -q tests/test_learn_hybrid_qwen_binding.py`
  - exit 0; `16 passed in 1.50s`.
- Required focused Task 4 suite:
  - `uv run pytest -q tests/test_learn_hybrid_qwen_binding.py tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_web_panel_route.py -k "qwen or hybrid or cancellation"`
  - exit 0; `31 passed, 190 deselected in 3.43s`.
- Full worker and model cancellation suites:
  - `uv run pytest -q tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py`
  - exit 0; `34 passed in 8.60s`.
- Relevant panel checks:
  - `uv run pytest -q tests/test_web_panel_route.py -k "qwen or hybrid or cancellation or task_kind"`
  - exit 0; `4 passed, 167 deselected in 1.77s`.
- Relevant Hybrid regressions:
  - `uv run pytest -q tests/test_learn_hybrid_contracts.py tests/test_learning_hybrid_vertical_slice.py tests/test_learn_hybrid_omni_discovery.py`
  - exit 0; `68 passed in 5.97s`.
- UTF-8 source verification: exit 0; exact `申请职位` and `缺少 Omni 候选` are present with no replacement character.
- Required `py_compile` over Task 4 plus modified integration modules: exit 0 with no output.
- `git diff --cached --check` and committed patch check: exit 0 with no output.

## Full panel out-of-scope finding

Command:

`uv run pytest -q tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_web_panel_route.py`

Result: `196 passed, 9 failed`. All failures are unrelated to Task 4:

- Eight tests require absent historical files under `artifacts/demo`, `artifacts/wikipedia`, `artifacts/github`, `artifacts/docs_search`, and `artifacts/visual-match-smoke/live_seek_20260624`.
- `tests/test_web_panel_route.py:5911` expects a pre-existing mojibake literal that no longer matches the UTF-8 panel source.

These fixtures/assertions are outside the Task 4 allowlist and were not edited or fabricated. The Task 4-focused panel test is green.

## Self-review

- Request geometry originates only from the validated Omni inventory; Qwen output cannot replace or add geometry.
- Every Omni candidate is covered exactly once, including inactive candidates; omission fails closed.
- Unknown/duplicate IDs and candidate-shaped orphan identities are rejected.
- Semantic assignments are candidate-ID-bound and non-authorizing.
- `ORPHAN_SEMANTIC` records have no `candidate_id` and cannot fabricate one.
- Exact capture identity, screenshot bytes, dimensions, and OCR/UIA lineage are rechecked before model dispatch.
- The prior sealed Omni inventory remains byte-equivalent after controlled timeout/cancellation failures.
- Model acquisition uses the existing `understanding` profile; normal release and cancellation use the existing stop path. No additional server was added.
- Normal release requires a valid binding seal and occurs only after sealing. Cancellation can stop Qwen without a new binding artifact to terminate in-flight compute safely.
- The model request ID is propagated through the existing managed environment contract.
- Task 3 Omni cooperative cancellation, claim lifecycle, provider runtime boundary, and public UEI result/receipt schemas were not changed.
- No real model/GPU/GUI/browser/action was invoked.
- The denylisted untracked `tests/test_agent_runtime_actual_adapter_portfolio_v1.py` was not read, edited, staged, deleted, or committed.

## Files

- `app/learn/hybrid/qwen_binding.py` (new)
- `app/learn/workflow_tasks/hybrid_qwen.py` (new)
- `app/core/model_server.py`
- `app/learn/workflow_worker.py`
- `app/api/panel.py`
- `tests/test_learn_hybrid_qwen_binding.py` (new)
- `tests/test_learning_workflow_stage_worker.py`
- `tests/test_model_request_cancellation.py`
- `tests/test_web_panel_route.py`

## Concerns

- Full `tests/test_web_panel_route.py` remains red only for the nine documented out-of-scope baseline fixture/mojibake failures. No Task 4-focused failure remains.
- No production Qwen/GPU run was performed, as explicitly forbidden. Endpoint formatting, request-ID propagation, cancellation/release, parser closure, and lifecycle ordering are verified with controlled runners/responses.

## Commit

`66a6240b` — `feat(learn): bind qwen semantics to omni candidates`

---

# Task 4 independent-review repair — round 1

## Status

DONE_WITH_CONCERNS. Closed C1 and I1–I6 within the Task 4 allowlist without a real model, GPU, GUI, browser, or action. The managed lifecycle now owns an exact request/profile/server lease rather than treating the whole understanding server as one operation's property.

## Review findings closed

- **C1 request-owned lifecycle**
  - Added a cross-process, atomically locked Qwen lease registry keyed by the exact acquired profile and managed `AGENT_GUI_MODEL_REQUEST_ID`.
  - Carries the exact lease and acquired profile/server identity through worker acquisition, task dispatch, HTTP runner, successful release, and cancellation.
  - Uses the acquired profile's exact `request_cancel_endpoint` before any stop fallback; a later config change cannot redirect cancellation.
  - Cancelling or releasing operation A removes only A's lease while operation B remains active. A shared server is never stopped.
  - Stops only a final server proven to have been started by this runtime, then verifies health is no longer `running`, `loading`, or `busy`. Stop-script exit success alone is not accepted.
  - Deletes final lease state so a later externally owned server cannot inherit stale runtime ownership.
  - Qwen receives a real process-shared cancellation event in the managed registry; the event is set before request-owned provider cancellation.
- **I1 sealed Omni input**
  - Requires a lowercase 64-character `content_sha256`, verifies it exactly, and rejects missing/mismatched seals.
  - The managed worker validates the seal before model preflight/acquisition, while the direct runner and task validate it again at their boundaries.
- **I2 exact screenshot bytes**
  - Reads the canonical screenshot once, verifies SHA, dimensions, decode, and media type from that immutable byte buffer, and passes the same bytes/media/hash into the HTTP adapter.
  - The HTTP data URL encodes exactly those bytes; a later file mutation cannot change the request.
- **I3 bounded untrusted response**
  - Caps the HTTP body at 1 MiB before decode.
  - Bounds JSON depth, requires binding count to equal inventory size, caps orphans at 64, and caps every model-controlled UTF-8 string/key at 4096 bytes before recursive forbidden-field traversal or sealing.
- **I4 timeout/cancellation typing**
  - Normalizes direct `TimeoutError`, `socket.timeout`, and timeout-valued `URLError.reason` into `QwenModelRequestTimeout`, which the binding runner maps to `QwenBindingTimeout`.
  - Verifies the managed Qwen token is non-null, reaches task/runner, and is set before provider cancellation.
- **I5 canonical semantic uniqueness**
  - Defines the semantic target key as NFKC-normalized, Unicode-casefolded, whitespace-collapsed `(role, label, description)`.
  - Enforces uniqueness across candidate bindings, across orphans, and between bindings and orphans. Relation is metadata, not target identity.
- **I6 complete release gate**
  - Requires the exact active opaque lease, exact sealed Omni inventory, exact sealed binding artifact, canonical parser output, same capture, complete candidate coverage, and all non-authorizing/closed-shape invariants before normal release.
  - A trivial tag/self-hash, omitted binding, wrong capture, or inactive/forged lease cannot release the server.

## TDD evidence

### RED

- `uv run pytest -q tests/test_learn_hybrid_qwen_binding.py`
  - exit 1; `9 failed, 14 passed`. Expected failures covered missing/mismatched Omni seals, canonical semantic duplicates, binding/orphan collision, depth/orphan/string bounds, immutable-byte runner handoff, and exact lease task release.
- `uv run pytest -q tests/test_model_request_cancellation.py`
  - exit 1; `9 failed, 3 passed`. Expected failures covered absent lease registry, shared cancellation/release, release gate, exact-byte runner API, timeout typing, and body cap.
- `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k "managed_hybrid_qwen"`
  - exit 1; `2 failed, 26 deselected`. The worker did not acquire/pass an exact lease and its managed Qwen cancellation event was absent.
- Additional focused RED checks:
  - acquired request endpoint vs changed live config: failed by calling `should-not-use` instead of the acquired endpoint;
  - final request cancellation: failed by leaving an owned server running;
  - release artifact with omitted candidate: failed by accepting incomplete coverage;
  - unsealed managed inventory before acquisition: failed because model acquisition was reached first.

### GREEN

- Required focused Task 4 suite:
  - `uv run pytest -q tests/test_learn_hybrid_qwen_binding.py tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_web_panel_route.py -k "qwen or hybrid or cancellation"`
  - exit 0; `47 passed, 190 deselected in 4.52s`.
- Full worker and cancellation suites:
  - `uv run pytest -q tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py`
  - exit 0; `42 passed in 8.76s`.
- Relevant panel suite:
  - `uv run pytest -q tests/test_web_panel_route.py -k "qwen or hybrid or cancellation or task_kind"`
  - exit 0; `4 passed, 167 deselected in 1.81s`.
- Relevant Hybrid regressions:
  - `uv run pytest -q tests/test_learn_hybrid_contracts.py tests/test_learning_hybrid_vertical_slice.py tests/test_learn_hybrid_omni_discovery.py`
  - exit 0; `68 passed in 5.94s`.
- `uv run python -m py_compile` over every Task 4 production/test path: exit 0.
- `git diff --check`: exit 0.
- Explicit UTF-8 verification over every changed Python file: `utf8-ok`; no replacement character and exact `申请职位` retained.

## Self-review

- Exact acquired profile identity, endpoint, server identity, lease ID, and owner request ID are never reconstructed from client payload.
- Two active leases prove cancel-vs-inference and release-vs-inference isolation: operation B remains active and the server is not stopped when A ends.
- The final owned lease stop requires a verified health postcondition; a fake successful stop with a still-running health response raises and preserves the lease.
- Final lease state is removed, preventing stale runtime ownership from causing a later external server to be stopped.
- The canonical screenshot path is used only to obtain one immutable byte buffer. The HTTP adapter has no filesystem reread path.
- The parser applies complexity/string bounds before recursive forbidden-field inspection.
- Normal release cannot be forged with a contract tag and self-hash; it reruns the same closed parser against the exact sealed inventory.
- Task 3 Omni cancellation/claim behavior, public UEI contracts, Runtime/action authority, and the panel public result schema are unchanged.
- The denylisted untracked `tests/test_agent_runtime_actual_adapter_portfolio_v1.py` was not read, edited, staged, deleted, or committed.

## Files changed in repair

- `app/core/model_server.py`
- `app/learn/hybrid/qwen_binding.py`
- `app/learn/workflow_tasks/hybrid_qwen.py`
- `app/learn/workflow_worker.py`
- `tests/test_learn_hybrid_qwen_binding.py`
- `tests/test_learning_workflow_stage_worker.py`
- `tests/test_model_request_cancellation.py`
- this report

## Concerns

- The checked-in Qwen profile does not currently declare `request_cancel_supported` / `request_cancel_endpoint`. With one runtime-owned lease, cancellation safely stops and verifies the owned server. With multiple leases and no request-specific endpoint, cancellation fails closed and retains the shared server rather than disrupting another operation. Adding server/config support for request-specific cancellation is outside the Task 4 allowlist.
- The nine previously documented unrelated full-panel fixture/mojibake baseline failures remain outside this repair and were not modified.

## Commit

`fix(learn): close qwen binding lifecycle boundaries` (exact hash returned after commit creation).

---

# Task 4 independent-review repair — round 2

## Status

DONE_WITH_CONCERNS. Closed the remaining C1/I4 and the round-2 lifecycle findings with an internal `qwen_model_server_lease_v2` protocol. No model, GPU, GUI, browser, or action path was invoked. The only concern remains the previously documented unrelated full-panel fixture/mojibake baseline.

## Exact server-incarnation lifecycle

- Lease state is now keyed by an immutable `incarnation_id`, not mutable `profile_id`.
- The incarnation seals the exact endpoint, canonical base URL, model identity, acquired profile digest, listener/service PID, and nanosecond process creation identity.
- An active same-profile state rejects any incompatible endpoint, model, profile digest, PID, or process creation identity.
- Model dispatch rechecks the exact PID/creation identity before sending HTTP, so a replacement process cannot receive an old lease's request.
- Cancellation scans every sealed lease state by `owner_request_id` first and then loads the acquired profile snapshot. Current stage/profile configuration is never used to select the cancellation target.
- Final stop uses a two-phase token/revision protocol: mark `stop_pending` under the state lock, release the lock, prove the exact process identity, invoke stop, prove that exact PID/creation incarnation exited, use health only as secondary evidence, then conditionally delete the matching state.
- If ownership changes, stop fails, the exact process remains, or the finalization token changes, the sealed lease remains `owned_pending`; an external replacement is never reported released or stopped.

## Interprocess coordination

- Replaced mtime lock-file stealing with an OS-backed file lock (`msvcrt.locking` on Windows, `fcntl.flock` elsewhere) plus a process-local thread lock.
- A live lock remains authoritative even when its mtime is moved past the former 30-second expiry.
- No lease-state lock is held across the stop script; a regression reacquires the state lock from inside the controlled stop seam.
- The managed Qwen ensure/start/readiness/lease-publication transition now executes inside `_ManagedCancellationEvent.run_if_not_cancelled`.
  - Cancellation that wins first prevents acquisition/start.
  - Acquisition that wins holds the shared transition lock until the exact lease is durably published; cancellation then observes and owns cleanup.

## Deployed no-endpoint cancellation and reconciliation

- The regression loads the actual checked-in `qwen3_vl_8b_q4_k_m` profile and proves it has no `request_cancel_endpoint`.
- With a shared server and no request endpoint, cancellation records `cancellation_acknowledged_pending` / `owned_pending`, retains both leases, keeps the worker attached, and does not terminate/kill the wrapper or shared model server.
- The registry retries request-owned reconciliation after worker exit; only verified `terminated`/`request_not_active` converts the internal pending operation to cancelled cleanup.
- A sole runtime-owned request may stop only its exact proven incarnation; a sole external lease remains pending unless request completion is proven.

## Failure finalization and typed cancellation

- `run_hybrid_qwen_task` now owns a failure finalizer for timeout, invalid JSON, parser rejection, cancellation, and release failure.
- A model completion notifier distinguishes model-returned parser failures from uncertain transport timeouts.
- The HTTP adapter durably marks compute complete immediately after bounded response bytes are read, before JSON decode, so invalid outer JSON can reconcile a shared lease without stranding it.
- Completed parser/JSON/release failures remove only the exact request lease; a final runtime-owned lease stops only after exact-process proof.
- Uncertain shared/external timeouts persist `owned_pending`; a sole exact runtime-owned timeout can stop the exact incarnation and prove completion.
- Release/finalization failures preserve the exact lease and pending token instead of reporting released.
- Added `QwenModelRequestCancelled`; pre-request, post-request, and event-set transport errors map through `QwenBindingCancelled` rather than generic runtime failure.

## TDD evidence

### RED

- Incarnation/control-plane selection:
  - `uv run pytest -q tests/test_model_request_cancellation.py -k 'incarnation or current_profile_id or no_endpoint_shared or replacement_process or outside_os_state_lock or os_lock'`
  - exit 1; `8 failed, 13 deselected` for incompatible same-ID acquisitions, mutable-profile cancellation selection, deployed no-endpoint terminal misreporting, absent exact PID proof, and the old lock API.
- Atomic managed transition:
  - `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k 'ensure_to_lease'`
  - exit 1 because cancellation and ensure→publication were not one protected transition.
- Pending shared cancellation:
  - `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k 'shared_no_endpoint'`
  - exit 1 because the registry marked cancelled and killed the wrapper.
- Pending recovery after exit:
  - `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k 'pending_cancel_reconciles'`
  - exit 1 because failed/non-running workers bypassed model reconciliation.
- Cancellation typing:
  - HTTP adapter test failed because `QwenModelRequestCancelled` did not exist; binding test exposed generic `RuntimeError`.
- Failure finalization:
  - workflow timeout/invalid JSON/parser/release matrix: `4 failed, 25 deselected` because no failure reconciler existed;
  - sole exact timeout finalizer failed with `owned_pending` instead of verified exact-process termination;
  - invalid outer HTTP JSON failed by leaving the shared request lease pending;
  - partial/forged lease token was initially accepted by the exact release helper.

### GREEN

- Required focused Task 4 suite:
  - `uv run pytest -q tests/test_learn_hybrid_qwen_binding.py tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_web_panel_route.py -k "qwen or hybrid or cancellation"`
  - exit 0; `69 passed, 190 deselected in 6.57s`.
- Full worker and cancellation suites:
  - `uv run pytest -q tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py`
  - exit 0; `58 passed in 9.06s`.
- Relevant panel suite:
  - `uv run pytest -q tests/test_web_panel_route.py -k "qwen or hybrid or cancellation or task_kind"`
  - exit 0; `4 passed, 167 deselected in 1.78s`.
- Relevant Hybrid regressions:
  - `uv run pytest -q tests/test_learn_hybrid_contracts.py tests/test_learning_hybrid_vertical_slice.py tests/test_learn_hybrid_omni_discovery.py`
  - exit 0; `68 passed in 5.99s`.
- Full Qwen binding suite:
  - `uv run pytest -q tests/test_learn_hybrid_qwen_binding.py`
  - exit 0; `30 passed in 4.14s`.
- `uv run python -m py_compile` over every Task 4 production/test path: exit 0.
- `git diff --check`: exit 0; only Git's expected `core.autocrlf=true` normalization warning for `model_server.py` was emitted.

## Self-review

- Lease state and lease token field sets are closed and sealed; a partial `lease_id`/`incarnation_id` object cannot release or select a server.
- All state-file scans validate the self-hash and incarnation/path binding; corruption or ambiguous owner matches fail closed.
- The current configured profile ID/endpoint cannot redirect an acquired request's cancellation or HTTP dispatch.
- A server replacement before request or stop fails exact PID/creation comparison and receives neither request nor stop.
- Health `unreachable` alone never proves termination; exact process-incarnation exit is required.
- Shared no-endpoint cancellation retains compute ownership and worker attachment; no wrapper kill or terminal cancellation occurs while compute is unproven.
- Timeout/parser/invalid JSON/release failures have explicit final-state regressions covering exact release, exact stop, and durable pending ownership.
- I1/I2/I3/I5/I6 tests remain green; Task 3 Omni cleanup/claim behavior and public UEI/Runtime/action authority remain unchanged.
- No config was fabricated or modified. The denylisted untracked `tests/test_agent_runtime_actual_adapter_portfolio_v1.py` was not read, edited, staged, deleted, or committed.

## Files changed in repair

- `app/core/model_server.py`
- `app/learn/hybrid/qwen_binding.py`
- `app/learn/workflow_tasks/hybrid_qwen.py`
- `app/learn/workflow_worker.py`
- `tests/test_learn_hybrid_qwen_binding.py`
- `tests/test_learning_workflow_stage_worker.py`
- `tests/test_model_request_cancellation.py`
- this report

## Concerns

- The nine previously documented unrelated full-panel fixture/mojibake failures remain outside the Task 4 allowlist. Relevant Task 4 panel checks are green.
- No real Qwen/GPU run was performed, as explicitly forbidden; exact HTTP/cancellation/process/lease seams are exercised with controlled readiness, PID identities, responses, and stop probes.

## Commit

`fix(learn): bind qwen leases to exact server incarnation` (exact hash returned after commit creation).

---

# Task 4 independent-review repair — round 3

## Status

DONE_WITH_CONCERNS. Closed the remaining C1/I4 findings and all six round-3 lifecycle issues inside the Task 4 allowlist. No model, GPU, GUI, browser, or action path was invoked.

## Finalization CAS and exact termination

- A non-null finalization token is now immutable and single-owner. A concurrent release/cancel attaches to the persisted token and returns `finalization_pending`; it never overwrites the token or launches another stop.
- A completed finalizer writes a sealed owner receipt before deleting the active lease state. A concurrent or later retry recovers the same durable result as `request_not_active` instead of attempting another stop.
- Request-owned finalization no longer calls the generic port/PID-file stop script. It uses one exact PID plus nanosecond creation identity and bounded `terminate -> wait -> kill -> wait` through psutil's PID-reuse guarded process object.
- Process evidence is tri-state: `exact_live`, `proven_absent`, or `unobservable`. `AccessDenied`/`OSError` is `owned_pending` and never terminal process-exit proof.
- A PID replacement observed before or during termination is never terminated. The old exact process must be proven absent before the lease becomes terminal.

## Acquisition transaction and incarnation deduplication

- Qwen ensure/start/readiness and durable lease publication now run under a dedicated OS-backed cross-process acquisition transaction lock.
- The existing per-operation managed cancellation transition remains outside that global transaction, so cancellation that wins first prevents ensure/start; otherwise cancellation observes the durably published exact lease.
- Acquisition scans every active state by canonical server base URL plus exact PID/create-time, independent of profile ID. A renamed or incompatible profile cannot create a second refcount partition for the same listener process.

## Durable pending ownership and reconciliation

- No-endpoint cancellation persists closed evidence fields on the exact lease: `pending_reason`, `capability_blocker`, and `reconciliation_trigger=worker_http_completion_or_explicit_retry`.
- Finalized owners have sealed, request-keyed tombstones containing the exact lease/incarnation and terminal release receipt.
- A real managed cancellation regression now covers: initial deployed-style no-endpoint pending response, real compute-complete finalizer removal while another lease remains, worker exit, and real retry recovery as `request_not_active` without any process termination.

## TDD evidence

### RED

- Initial focused lifecycle command:
  - `python -m pytest tests/test_model_request_cancellation.py -q -k "different_profile_id or pending_reason or single_owner or existing_qwen_finalization or post_stop_access_denied or exact_qwen_termination or global_acquisition_transaction or owner_tombstone"`
  - exit 1; `7 failed, 26 deselected`. Valid failures proved missing cross-profile rejection, finalization CAS/termination APIs, acquisition transaction, and tombstone recovery. Two artifact-based cases also exposed a pre-existing test-module import setup fault; the helper import was corrected before using those cases as evidence.
- CAS wrapper regression after the first implementation pass:
  - the focused command returned `1 failed, 7 passed`; the concurrent cancel attached to the immutable token but `_release_qwen_request_lease` incorrectly relabeled pending as `terminated`. The wrapper was fixed to preserve the pending lifecycle truth.
- Managed real-finalizer reconciliation was added before its production path was accepted; the first direct run was blocked at collection by invoking system Python without project dependencies. Re-running under the project environment exercised the production tombstone path.

### GREEN

- Focused round-3 lifecycle slice:
  - `uv run python -m pytest tests/test_model_request_cancellation.py -q -k "different_profile_id or no_endpoint_shared or single_owner or existing_qwen_finalization or post_stop_access_denied or exact_qwen_termination or global_acquisition_transaction or owner_tombstone"`
  - exit 0; `8 passed, 25 deselected in 0.33s`.
- Full request cancellation suite:
  - `uv run python -m pytest tests/test_model_request_cancellation.py -q`
  - exit 0; `33 passed in 0.64s`.
- Required focused Task 4 suite:
  - `uv run python -m pytest -q tests/test_learn_hybrid_qwen_binding.py tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_web_panel_route.py -k "qwen or hybrid or cancellation"`
  - exit 0; `77 passed, 190 deselected in 6.68s`.
- Full worker and cancellation suites:
  - `uv run python -m pytest -q tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py`
  - exit 0; `66 passed in 9.15s`.
- Full Qwen binding suite:
  - `uv run python -m pytest -q tests/test_learn_hybrid_qwen_binding.py`
  - exit 0; `30 passed in 4.12s`.
- Relevant panel suite:
  - `uv run python -m pytest -q tests/test_web_panel_route.py -k "qwen or hybrid or cancellation or task_kind"`
  - exit 0; `4 passed, 167 deselected in 1.78s`.
- Relevant Hybrid regressions:
  - `uv run python -m pytest -q tests/test_learn_hybrid_contracts.py tests/test_learning_hybrid_vertical_slice.py tests/test_learn_hybrid_omni_discovery.py`
  - exit 0; `68 passed in 5.99s`.
- `uv run python -m py_compile` over every Task 4 production/test path: exit 0.
- `git diff --check`: exit 0; only Git's expected `core.autocrlf=true` normalization warning for `model_server.py` was emitted.
- Explicit UTF-8 verification of all changed Python files: `utf8-ok`.

## Self-review

- The state lock is never held over bounded process termination. The finalization token is published under lock, process work occurs outside it, and the same token/revision is verified before the single terminal transition.
- A second caller can observe pending or the durable owner receipt only; it cannot become a second finalization owner.
- The exact termination primitive contains no port, PID-file, shell, or stop-script path. psutil performs PID-reuse checks again at terminate/kill boundaries.
- Health remains secondary evidence and cannot convert an unobservable exact process into terminal success.
- The acquisition transaction is OS-backed and covers the entire first ensure/start-to-publication window; direct lease acquisition itself creates no process side effect.
- Owner-first cancellation does not consult mutable current profile configuration and survives active-state deletion through a sealed tombstone.
- I1/I2/I3/I5/I6, Task 3 managed cancellation, public UEI/Runtime boundaries, and action authority remain unchanged.
- The denylisted untracked `tests/test_agent_runtime_actual_adapter_portfolio_v1.py` was not read, edited, staged, deleted, or committed.

## Files changed in repair

- `app/core/model_server.py`
- `app/learn/workflow_worker.py`
- `tests/test_learning_workflow_stage_worker.py`
- `tests/test_model_request_cancellation.py`
- this report

## Concerns

- The checked-in Qwen profile still lacks request-scoped cancellation support. The runtime now retains an explicit non-terminal capability blocker until the worker HTTP boundary proves completion or an explicit retry reconciles a sealed owner receipt; it intentionally does not kill shared compute.
- No real Qwen/GPU run was performed, as explicitly forbidden. Process, HTTP, cancellation, lease, and concurrency behavior was exercised with controlled production seams.
- The previously documented unrelated full-panel fixture/mojibake baseline remains outside this Task 4 repair.

## Commit

`fix(learn): serialize qwen incarnation finalization` (exact hash returned after commit creation).
