# Benchmark v2 Probe-Authority Bridge Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan one slice at a time.

**Goal:** Give Task 11 one minimal, pathless public authority proving the six required regression probes, without changing accepted/scorer/provider/dependency contracts or widening B1 infrastructure.

**Architecture:** Task 9 produces one production lifecycle receipt for each independent probe attempt. A probe-only verifier selects the first complete verified attempt in each Omni/Qwen/VISTA × cancel/timeout cell and projects the six receipts into one public bundle. Task 11 and Task 12 accept that single public file but independently rebuild it from the two canonical raw ledgers before using its pathless ref.

**Tech Stack:** Python 3.11 standard-library canonical JSON, SHA-256, `time.monotonic_ns`, existing Task 7 lifecycle parents, existing Task 9 runner ledger/cleanup, pytest.

**Spec:** This amendment is subordinate to `docs/superpowers/plans/2026-08-26-portfolio-hybrid-v1-1-benchmark-v2-plan.md` and supersedes only conflicting probe-authority, Task 11 profile-binding, Task 11/12 ordering, and canonical CLI clauses in the 2026-08-28 scoring-bridge and 2026-08-29 Task 11/12 evidence-boundary amendments. All unrelated estimand, scoring, leakage, durable-claim, holdout, B1, S1-S4, and safety contracts remain authoritative.

**Authoritative P0-D correction:** the narrow P0-C contract in `docs/superpowers/plans/2026-08-29-benchmark-v2-probe-raw-evidence-plumbing-amendment.md` is complete and does not define runner/deadline behavior. Section 2 of this plan is now the canonical P0-D contract, subject to this correction: P0 records `collection_policy="one_requested_attempt_per_provider"` and `status="terminal"` and makes no first-complete claim; `first_complete_verified_attempt_per_cell` remains exclusively the P1 canonical-ledger rebuild/public-bundle rule. P0-D must not reopen B1 supervision, create a general durable process supervisor, or revive the superseded raw-evidence expansion. The existing public bundle field set and all unrelated clauses below remain unchanged.

## Global constraints

- Keep exactly four benchmark arms and the frozen release, corpus, estimand, gate, and threshold semantics.
- Do not version or add fields to `benchmark_v2_accepted_regression_score_input_v2`, `benchmark_v2_prediction_run_v3`, `benchmark_v2_lifecycle_bundle_v3`, `private_scorer_input_binding_v1`, `private_scorer_public_ref_v3`, `portfolio_hybrid_v1_1_provider_manifest_v2_1`, `benchmark_v2_leakage_review_v1`, or `benchmark_v2_release_dependency_manifest_v1`.
- Do not add provider profiles to `sealed_runtime.profile_refs`; those refs remain release configuration refs and are not provider runtime-profile authority.
- Do not redesign `WorkflowService`, add a model/provider/supervisor/remote witness, or change B1 ownership and cleanup.
- All public data is pathless. Raw attempt directories, native paths, PIDs, process creation times, socket/listener addresses, lease IDs, owner-journal roots, and private-manifest data remain local inputs and never enter the public bundle, stdout, authorization public ref, or final report.
- Every new artifact is closed, canonical UTF-8, nonauthorizing unless it is the existing native holdout authorization, and create-new-or-byte-identical.

---

## 1. Why the current contracts cannot authorize Task 11

The current implementation has five concrete contradictions:

1. `scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py` correctly fails closed because accepted regression v2, lifecycle bundle v3, private scorer binding v1, and public score v3 contain no probe ref.
2. `benchmark_v2_lifecycle_probe_receipt_v1` exists only in lifecycle validation/tests; Task 9 produces no production receipt that Task 11 can consume.
3. The existing lifecycle matrix verifier compares all six receipts with one actual-attempt `run_id/stage/operation_id/model_request_id`. Task 9 correctly reserves six distinct attempts and operations, so that join is impossible.
4. Both current probe kinds call `cancel_operation` immediately. A `timeout` label is therefore not evidence that a deadline expired.
5. Task 11 currently derives `profile_sha256_by_id` from provider-manifest `sealed_runtime.profile_refs[*].role`. Those entries are release configuration roles, not the Omni/Qwen/VISTA runtime profiles observed by dispatch.

No production probe receipt, public probe bundle, authorization v2, claim, anchor, or report is created by writing or implementing this amendment.

---

## 2. Production probe evidence v2

### 2.1 Raw receipt

`benchmark_v2_lifecycle_probe_receipt_v2` is local evidence and has exactly these top-level fields, in semantic contract order:

```text
contract_version
benchmark_release_id
partition
probe_id
attempt_ref
provider
probe_kind
operation_ref
request_in_flight_ref
trigger_observation
body_completion_observation
termination_observation
stable_zero_observation
cleanup_receipt_ref
observer_identity
status
artifact_is_authorization
execute_binding_enabled
content_sha256
```

Its closed nested shapes are:

```text
provider = {
  provider_id,
  provider_revision,
  profile_id,
  profile_sha256
}

trigger_observation = {
  kind,
  action,
  request_in_flight_ref,
  triggered_monotonic_ns,
  deadline_expiration_ref
}

deadline_expiration_ref = null OR {content_sha256}

body_completion_observation = {
  state,
  observed_monotonic_ns,
  evidence_ref
}

termination_observation = {
  outcome,
  process_identities,
  evidence_ref
}

stable_zero_observation = {
  job_members,
  active_listeners,
  active_leases,
  stable_zero_observations,
  evidence_ref
}

observer_identity = {
  kind,
  module_ref,
  content_sha256
}
```

`process_identities` is the exact ordered non-empty `{pid,create_time_ns}` list
fixed by the durable P0-C trigger intent. It is never collapsed to one process,
and every identity must have a matching fail-closed live absence observation.

`stable_zero_observation.evidence_ref` resolves one sealed local
`benchmark_v2_probe_stable_zero_evidence_v1` parent. That parent joins the same
attempt and cleanup receipt and contains at least three ordered samples taken
after cleanup. Every sample carries a strictly increasing
`observed_monotonic_ns` plus the complete `resource_counts` object; every count
must be zero. A single cleanup result, three copies of one observation, or a
runner-authored count cannot satisfy this requirement.

For timeout only, `deadline_expiration_ref` resolves a sealed local `benchmark_v2_probe_monotonic_deadline_expiration_v1` parent with exactly:

```text
contract_version
attempt_ref
operation_ref
request_in_flight_ref
clock
owner
started_monotonic_ns
duration_ns
deadline_monotonic_ns
expired_monotonic_ns
content_sha256
```

`attempt_ref` and `operation_ref` retain their existing closed local shapes. Every field ending in `_ref` above is the existing exact ref shape required by its validated parent; it is never a path string. `process_identity` remains local raw evidence and is removed by the public projection.

For both kinds, `partition="regression"`, `status="PASS"`, `artifact_is_authorization=false`, and `execute_binding_enabled=false`. The receipt is PASS only when:

- `provider.provider_revision` equals `evaluation_projection.provider_policy.provider_revisions[provider_id]` from the validated provider manifest;
- `provider.profile_id/profile_sha256` equal the profile identity rederived from that attempt's validated dispatch receipt/runtime attestation, not from `sealed_runtime.profile_refs`;
- request, trigger, body, termination, stable-zero, cleanup, attempt, and operation parents all join to this one probe attempt;
- the request was observed `request_in_flight` before the trigger;
- `body_completion_observation.state == "not_complete"` after the trigger;
- `termination_observation.outcome == "same_incarnations_exited"` for the exact ordered P0-C process-identity list;
- `job_members`, `active_listeners`, and `active_leases` are empty and `stable_zero_observations >= 3`;
- cleanup is terminal stable zero and binds the same attempt.

`content_sha256 = sha256(J(receipt_without_content_sha256))`, where `J` is compact canonical UTF-8 JSON with sorted keys, no insignificant whitespace, `ensure_ascii=False`, and no NaN. File bytes are sorted-key, two-space-indented UTF-8 JSON plus one LF. The receipt is written once at the fixed local `attempt_dir/lifecycle-probe-receipt.json`; existing different bytes fail closed.

### 2.2 Genuine cancel versus timeout

For cancel:

```text
trigger_observation.kind = "cancel"
trigger_observation.action = "explicit_cancel"
trigger_observation.deadline_expiration_ref = null
```

For timeout:

```text
trigger_observation.kind = "timeout"
trigger_observation.action = "monotonic_deadline_expired"
deadline_expiration.clock = "time.monotonic_ns"
deadline_expiration.owner = "BenchmarkV2Runtime"
deadline_expiration.duration_ns = 120000000000
deadline_monotonic_ns = started_monotonic_ns + duration_ns
started_monotonic_ns < deadline_monotonic_ns <= expired_monotonic_ns <= triggered_monotonic_ns
```

`trigger_observation.deadline_expiration_ref` must resolve that exact parent. `BenchmarkV2Runtime` starts and observes the monotonic deadline while the validated request is in flight. The runner supplies neither monotonic values nor an “expired” boolean. Only after the runtime observes expiry may it use the existing cancellation path to stop and clean up the timed-out operation; that cleanup action does not convert immediate cancel into timeout evidence. An explicit cancel, wall-clock timestamp, caller-supplied deadline, early stop, relabelled service terminal, or missing monotonic parent cannot mint a timeout receipt.

Tests use an injected monotonic clock and deterministic wait hook; production uses `time.monotonic_ns`. No test sleeps for 120 seconds, and no WorkflowService API change is required.

### 2.3 Runner result and summary v2

`benchmark_v2_runner_probe_result_v2` has exactly the v1 fields plus the receipt ref:

```text
contract_version
attempt_ref
attempt_dir
provider_id
probe_kind
body_ref
cleanup_receipt_ref
lifecycle_probe_receipt_ref
status
artifact_is_authorization
execute_binding_enabled
content_sha256
```

`lifecycle_probe_receipt_ref` is exactly:

```text
{contract_version,file_sha256,content_sha256}
```

with contract version `benchmark_v2_lifecycle_probe_receipt_v2`, file SHA over the exact pretty-LF receipt bytes, and content SHA equal to the validated receipt. The local result remains private because `attempt_dir` is path-bearing.

`benchmark_v2_runner_probe_summary_v2` has exactly:

```text
contract_version
benchmark_release_id
partition
probe_kind
collection_policy
attempts
status
artifact_is_authorization
execute_binding_enabled
content_sha256
```

`collection_policy` is exactly `one_requested_attempt_per_provider`. `attempts` contains exactly one newly requested, validated result-v2 object for each provider requested by this runner invocation, preserving the validated request order. `status` is exactly `terminal`; P0-D does not select a prior attempt, claim PASS, scan the canonical ledgers for first-complete evidence, or mint public authority. First-complete selection remains a P1-only rule. The cancel and timeout summaries use their existing canonical runtime paths:

```text
runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/cancel-probes/cancel-probes.json
runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/timeout-probes/timeout-probes.json
```

Both summary files are create-new-or-byte-identical. They are never overwritten to select a later attempt.

### 2.4 Probe-only six-cell verifier

Add a probe-only entry point owned by `benchmark_v2_lifecycle.py`. It consumes the validated provider manifest, canonical runner ledger prefix, both summary-v2 files, their six result-v2 files, six receipt-v2 files, and the referenced raw parents. It does **not** receive or compare against one actual-attempt lineage.

The required matrix order is exactly:

```text
omni/cancel
omni/timeout
qwen/cancel
qwen/timeout
vista/cancel
vista/timeout
```

Each cell has a distinct attempt ref and distinct operation/request lineage. Across all six cells, duplicate attempt refs, duplicate operation IDs, duplicate request identities, a provider/kind mismatch, or cross-cell parent reuse fails closed.

For each cell, enumerate complete result events from the canonical ledger in append order. “Complete” means the same attempt has the valid `body_complete -> cleanup -> result` terminal chain, a result-v2 file, and a receipt-v2 file. Select the first complete attempt. Incomplete attempts remain cleanup evidence and are skipped; a first complete FAIL/invalid attempt makes the cell fail and cannot be bypassed by a later PASS. Later complete attempts are nonauthoritative and cannot replace the selection. Missing, extra, duplicate, reordered, or selectively omitted cells fail closed.

The verifier requires the same `provider_revision/profile_id/profile_sha256` for cancel and timeout of one provider. Revisions join the provider manifest policy. Profiles join each selected attempt's dispatch/runtime attestation. The six probe attempts are independent from, and must not equal, `accepted_run_ref.attempt_ref`.

---

## 3. One public probe-authority bundle

### 3.1 Closed artifact and ref

The only new public projection file is `benchmark_v2_regression_probe_authority_bundle_v1`, written canonically to:

```text
runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json
```

Its top-level field set is exactly, with no aliases or additions:

```text
contract_version
artifact_id
benchmark_release_id
partition
provider_manifest_ref
provider_corpus_ref
accepted_run_ref
selection_policy
required_matrix
probe_ledger_horizon_refs
probe_cells
status
safety
content_sha256
```

`provider_manifest_ref` and `provider_corpus_ref` are byte-equal copies of the already validated refs in accepted regression v2. `accepted_run_ref` is exactly `{contract_version,file_sha256,content_sha256}` for `benchmark_v2_accepted_regression_score_input_v2`. The only permitted logical `relative_path` strings are those already frozen in the exact provider-manifest/provider-corpus refs; no native or newly supplied path is permitted.

`selection_policy` is exactly:

```text
first_complete_verified_attempt_per_cell
```

`required_matrix` is exactly this 3×2 ordered value:

```json
[["omni","cancel"],["omni","timeout"],["qwen","cancel"],["qwen","timeout"],["vista","cancel"],["vista","timeout"]]
```

`probe_ledger_horizon_refs` is exactly two rows in `cancel,timeout` order:

```text
{
  probe_kind,
  ledger_horizon_ref
}
```

`ledger_horizon_ref` is exact pathless `{id,content_sha256}` for an in-memory rebuilt `benchmark_v2_probe_ledger_horizon_verified_projection_v1`. Its semantic projection binds the probe kind, exact raw ledger-prefix SHA, ordered complete/incomplete attempt identities through the frozen horizon, and the three selected first-complete verified attempts. Its identity prefix is `verified-probe-ledger-horizon` under the existing S1.1 formula.

`probe_cells` has exactly six rows in `required_matrix` order. Each row has exactly:

```text
provider_id
probe_kind
attempt_ref
run_id
operation_id
model_request_id
runner_probe_result_ref
lifecycle_probe_receipt_ref
cleanup_receipt_ref
stable_zero_ref
ledger_pre_result_ref
ledger_horizon_ref
deadline_expiration_ref
body_completion_state
termination_outcome
stable_zero_observations
status
```

`attempt_ref`, `ledger_pre_result_ref`, and `ledger_horizon_ref` are exact pathless `{id,content_sha256}` refs. Result/receipt refs are exact `{contract_version,file_sha256,content_sha256}`. Cleanup, stable-zero, and deadline-expiration refs use the exact closed ref shape of their validated parent projection and contain no path. `ledger_pre_result_ref` is rederived from the selected result event's exact pre-result bytes as `benchmark_v2_probe_ledger_pre_result_verified_projection_v1` with S1.1 prefix `verified-probe-pre-result`; it is never a caller-provided digest.

All six `attempt_ref`, `run_id`, `operation_id`, and `model_request_id` values are pairwise distinct. Each row joins its provider/kind to one result-v2, one production receipt-v2, one cleanup/stable-zero lineage, its exact pre-result projection, and the matching kind horizon. Timeout requires a non-null `deadline_expiration_ref` resolving the receipt-v2 monotonic-expiration parent. Cancel requires `deadline_expiration_ref=null`; any expiration ref on cancel fails closed.

Every row has `body_completion_state="not_complete"`, `termination_outcome="same_incarnations_exited"`, `stable_zero_observations >= 3`, and `status="PASS"`. Top-level `status="PASS"`, `partition="regression"`, and safety is exactly:

```json
{"artifact_is_authorization":false,"execute_binding_enabled":false,"display_only":true}
```

The projection is not emitted when any cell fails. Use the S1.1 nonrecursive identity rule exactly. Let `semantic_payload` be the complete bundle without `artifact_id` and `content_sha256`:

```text
semantic_sha256 = sha256(
  UTF8("benchmark_v2_regression_probe_authority_bundle_v1\0")
  || J(semantic_payload)
)
artifact_id = "probe-authority/" + semantic_sha256
content_sha256 = sha256(J(bundle_without_content_sha256))
```

The public ref is exactly `{id:artifact_id,content_sha256:content_sha256}`. File bytes are sorted-key, two-space-indented UTF-8 JSON plus one LF and are create-new-or-byte-identical. Successful materialization prints exactly one compact-canonical line and no path:

```json
{"probe_authority_ref":{"id":"probe-authority/<sha256>","content_sha256":"<sha256>"},"status":"PASS"}
```

### 3.2 Independent raw-ledger reconstruction

Create `app/learn/hybrid/benchmark_v2_probe_authority.py` as the sole production validator/rebuilder for this bundle. It loads the candidate projection only as data, independently derives the fixed raw ledgers from `--ledger-root`:

```text
<ledger-root>/regression/cancel-probes.jsonl
<ledger-root>/regression/timeout-probes.jsonl
```

It then reads the result-v2/receipt-v2/parent bytes selected by those canonical ledgers, invokes the probe-only lifecycle verifier, rebuilds both horizon projections, all six pre-result projections, and the complete bundle, and requires byte equality with the candidate file. A self-consistent `content_sha256`, `artifact_id`, `status="PASS"`, review sentence, or caller-supplied ref is never authority by itself.

Materialization uses the same rebuilder through one offline runner action. The canonical command is:

```powershell
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --partition regression --materialize-probe-authority --regression-run-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json --ledger-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger --output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json
```

The action accepts no explicit probe-ledger path, summary path, output root, provider-selection, model, holdout, authorization, scorer, or private-manifest input. It launches nothing and writes only the create-new-or-byte-identical projection.

Task 14 and Task 12 must call the same rebuilder with their already required `--ledger-root`; neither may trust the projection-only validator result.

### 3.2.1 P1 interpretation freeze

This subsection resolves the remaining machine-checkable P1 ambiguities and
supersedes only conflicting P1 interpretation elsewhere in this amendment.

1. **Ownership.** `benchmark_v2_lifecycle.py` remains unchanged in P1. Its
   lifecycle-owned semantic entry point is the already-public
   `validate_benchmark_v2_lifecycle_probe_receipt_v2`.
   `benchmark_v2_probe_authority.py` owns ledger and summary parsing, six-cell
   selection, projection, and reconstruction, and calls that lifecycle
   validator exactly once for each selected cell with the receipt and its raw
   parents. Section 2.4 therefore does not require a second six-cell function
   in `benchmark_v2_lifecycle.py`; Section 3.2 and the P1 allowlist control the
   orchestration boundary.
2. **Termination literal.** Public
   `probe_cells[*].termination_outcome` is exactly
   `same_incarnations_exited`. The singular spelling is a typo and is
   rejected. There is no alias, normalization, or v1-to-v2 translation.
3. **Public attempt ref.** For a validated raw probe attempt, the only public
   ref is exactly:

   ```text
   {id: "runner-attempt/" + attempt_id,
    content_sha256: raw_attempt_ref.content_sha256}
   ```

4. **Pre-result projection.**
   `benchmark_v2_probe_ledger_pre_result_verified_projection_v1` has exactly:

   ```text
   contract_version
   artifact_id
   benchmark_release_id
   partition
   provider_id
   probe_kind
   attempt_ref
   raw_prefix_sha256
   through_cleanup_terminal_sequence
   through_cleanup_terminal_envelope_sha256
   result_terminal_sequence
   result_terminal_envelope_sha256
   verified
   safety
   content_sha256
   ```

   `raw_prefix_sha256` hashes the exact canonical JSONL bytes from byte zero
   through the selected attempt's cleanup envelope, including that line's LF.
   Both envelope hashes are SHA-256 over compact-canonical envelope bytes.
   `verified=true`; `safety` is the exact three-field public safety object from
   Section 3.1. Apply the S1.1 identity rule with contract string
   `benchmark_v2_probe_ledger_pre_result_verified_projection_v1` and prefix
   `verified-probe-pre-result`. The semantic payload contains every field
   except `artifact_id` and `content_sha256`.
5. **Horizon projection.**
   `benchmark_v2_probe_ledger_horizon_verified_projection_v1` has exactly:

   ```text
   contract_version
   artifact_id
   benchmark_release_id
   partition
   probe_kind
   raw_prefix_sha256
   through_result_terminal_sequence
   through_result_terminal_envelope_sha256
   attempts
   selected_attempt_refs
   verified
   safety
   content_sha256
   ```

   Each `attempts` row has exactly
   `attempt_ref,provider_id,observed_state,completion_state,result_terminal_sequence`,
   is ordered by its opened-event sequence, and reflects state at the cutoff.
   `observed_state` is one of `opened,body_complete,cleanup,result`;
   `completion_state` is `complete` exactly when `observed_state=result`, and
   otherwise is `incomplete`; `result_terminal_sequence` is an integer only
   for a complete row and otherwise is null. `selected_attempt_refs` is
   exactly three refs in `omni,qwen,vista` order. `verified=true`; `safety` is
   the exact three-field public safety object. Apply the S1.1 identity rule
   with contract string
   `benchmark_v2_probe_ledger_horizon_verified_projection_v1` and prefix
   `verified-probe-ledger-horizon`. The semantic payload contains every field
   except `artifact_id` and `content_sha256`.
6. **S1.1 hashes.** For either projection:

   ```text
   semantic_sha256 = sha256(
     UTF8(contract_version + "\0") || J(semantic_payload)
   )
   artifact_id = prefix + "/" + semantic_sha256
   content_sha256 = sha256(J(object_without_content_sha256))
   ```

   `J` is the existing compact-canonical UTF-8 serialization. Unknown or
   missing fields and caller-supplied IDs or hashes fail closed.
7. **First-complete and cutoff.** Scan validated canonical ledger envelopes in
   append and sequence order. For each provider, its candidate is the attempt
   owning the first `result` event for that provider and kind. An attempt with
   no result event at the horizon is incomplete and may be skipped. Once a
   result event is encountered, missing or mismatched result bytes, a missing
   or mismatched receipt, malformed parents, FAIL status, or any lifecycle
   semantic failure makes that complete candidate invalid and fails the cell
   immediately. It is never reclassified as incomplete and a later PASS may
   not replace it. The kind horizon cutoff is the maximum of the three
   selected result-event sequences: the smallest inclusive prefix containing
   one candidate for every provider. The horizon raw SHA covers exact JSONL
   bytes through that envelope including LF; its terminal-envelope SHA covers
   compact-canonical cutoff-envelope bytes. Events after the cutoff are
   nonauthoritative and do not change the rebuilt bundle or ref. Every
   envelope, payload, ref, and file through the cutoff must validate. Later
   complete attempts before the cutoff are recorded as complete but are not
   selected.
8. **Summary-v2 role.** Both fixed canonical summary-v2 files remain required
   inputs, but are corroborating cohort and integrity inputs only; they are
   never selectors or public parents. Reconstruction first derives candidates
   and horizons only from the two raw ledgers. It then validates each summary
   as canonical and closed with the matching release, regression partition,
   kind, `one_requested_attempt_per_provider`, terminal status, and exactly
   `omni,qwen,vista` attempts in that order, and requires each embedded result
   object to be byte-equal to the selected result-v2 file and object for that
   cell. A missing, drifted, or reordered summary fails. Summary bytes and refs
   contribute to no projection field or hash and cannot redirect selection.

### 3.3 Exact joins

Independent reconstruction enforces all of the following:

1. Release ID, provider manifest ref, provider corpus ref, and the provider corpus's exact `source_parent_ref` match accepted regression v2, its prediction/lifecycle envelopes, both probe ledger horizons, all selected results, and all receipts.
2. `accepted_run_ref` is the exact accepted file/content ref. Its selected actual attempt remains separate from all six probe attempts; no same-attempt join is required or permitted.
3. Each selected cell is the first complete **verified** attempt in append order. Incomplete attempts remain cleanup evidence and are skipped. A first complete but invalid/FAIL attempt fails the cell and cannot be bypassed by a later PASS.
4. Provider/kind, distinct attempt/run/operation/request identities, result-v2, receipt-v2, cleanup/stable zero, pre-result, horizon, and deadline-expiration rules all join exactly. Missing, extra, duplicate, reordered, cross-cell, or selectively omitted evidence fails closed.
5. Cancel and timeout receipts for one provider carry the same profile ID/SHA rederived from their dispatch/runtime attestations. Provider revision equals `evaluation_projection.provider_policy.provider_revisions[provider_id]`. No provider profile is derived from `sealed_runtime.profile_refs`.
6. Recursive validation rejects native paths, attempt directories, observer module paths, process/socket/lease identities, private-manifest data, Gold data, and unknown fields from the projection. Raw-only identities may be used during reconstruction but never copied out.

---

## 4. Task 11, Task 12, and S4 binding

### 4.1 Canonical Task 14 authorizer input

Task 11 adds exactly one CLI input:

```text
--probe-authority runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json
```

The corrected canonical Task 14 command is:

```powershell
uv run python scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py --private-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-private-manifest.json --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --regression-run-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json --score-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json --leakage-review runtime_state/portfolio-hybrid-v1-1/benchmark-v2/leakage-review.json --probe-authority runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json --ledger-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger --output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json
```

The authorizer independently rebuilds the bundle from the two fixed raw ledgers under `--ledger-root`, then joins its provider manifest ref, provider corpus/source-parent ref, accepted ref, release, six cells, and PASS state to the already validated manifest/accepted/score/review inputs. Missing probe input, a missing raw parent, a missing cell, any ref/profile/revision/attempt drift, byte inequality with the rebuilt projection, or any path/private finding fails before publication and before genesis/anchor mutation.

### 4.2 Authorization v2 with stable claim identity

Version the native payload to `portfolio_hybrid_benchmark_v2_holdout_authorization_payload_v2`. Its exact field set is the payload-v1 field set plus:

```text
regression_probe_authority_ref
```

That field is the exact pathless `{id,content_sha256}` bundle ref. `profile_sha256_by_id` is derived as `{profile_id:profile_sha256}` from the three provider profiles independently rederived while rebuilding the six production receipts; the public bundle does not add a profile map. `config_sha256_by_path` continues to derive from provider-manifest release configuration refs. The two maps must not be conflated.

Version the envelope to `portfolio_hybrid_benchmark_v2_holdout_authorization_envelope_v2`. Preserve the existing envelope hash formula, external ref shape, dual-anchor behavior, and fixed paths. `claim_identity`, `claim_id = sha256(J(IDENTITY))`, `authorization_id = "holdout-authorization/" + claim_id`, ledger identity, exact command, and exact run order remain byte-for-byte semantically stable. The new probe ref changes payload/envelope SHA but does not mint a new claim namespace or authorize a second holdout.

No payload/envelope v1 object is accepted as v2. If a production v1 authorization object/ref or either v1-bound anchor already exists in the stable claim namespace, refuse permanently: do not migrate, delete, replace, or mint a parallel claim namespace.

### 4.3 Task 12 final report binding

Task 12 report assembly adds required `--probe-authority` with the same canonical path. Using its existing `--ledger-root`, it independently rebuilds the bundle from both canonical raw ledgers and requires byte equality before use. The final public report's closed contract must include `regression_probe_authority_ref` as the exact bundle `{id,content_sha256}` ref and prove it equals the ref in authorization payload v2. It also joins provider manifest, provider corpus/source parent, accepted regression, and all six PASS cells. It never embeds raw parents or the native authorization payload.

The corrected canonical Task 16 report command is the existing command with:

```text
--probe-authority runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json
```

inserted after `--regression-score-ref .../regression/score-ref.json`. The Task 12 final-report contract is not yet implemented/frozen elsewhere, so adding this field now does not require versioning an existing public report. `benchmark_v2_release_dependency_manifest_v1` is unchanged.

### 4.4 S4 inventory timing

P0, P1, Task 11, and Task 12 finish before S4. Only S4 updates `app/learn/hybrid/benchmark_v2_private_release.py` and its seal tests to inventory the final changed production/test bytes. Existing entries whose bytes changed are rehashed; new public-boundary/authorizer/report files are added once. No probe runtime artifact is added to the source inventory or provider manifest.

Any implementation change after S4 invalidates the pending seal and requires rerunning deterministic tests/reviews and reminting the final seal. No seal is minted in P0/P1/Task 11/Task 12.

---

## 5. Exact implementation slices

### P0: Genuine production probe receipts

**Allowed files only:**

- Modify `app/learn/hybrid/benchmark_v2_runtime.py`.
- Modify `app/learn/hybrid/benchmark_v2_lifecycle.py`.
- Modify `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py`.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py`.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py`.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py`.

**RED:** Add exact focused tests named for `probe_receipt_v2`, `timeout_monotonic_deadline`, `cancel_has_no_deadline_expiration_ref`, `probe_result_v2_receipt_ref`, and `probe_summary_v2_receipt_results`. Prove current timeout fails because it immediately follows cancel and current runner emits v1 without a receipt.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py -k "probe_receipt_v2 or timeout_monotonic_deadline or cancel_has_no_deadline_expiration_ref or probe_result_v2_receipt_ref or probe_summary_v2_receipt_results"
```

**GREEN:**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py -k "probe_receipt_v2 or timeout_monotonic_deadline or cancel_has_no_deadline_expiration_ref or probe_result_v2_receipt_ref or probe_summary_v2_receipt_results"
uv run python -m py_compile app/learn/hybrid/benchmark_v2_runtime.py app/learn/hybrid/benchmark_v2_lifecycle.py scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py
git diff --check
```

**Commit:** `fix(benchmark-v2): prove production probe lifecycles`

### P1: Public bundle and first-complete verifier

**Allowed files only:**

- Create `app/learn/hybrid/benchmark_v2_probe_authority.py`.
- Modify `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py`.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py`.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py`.

**RED:** Add focused tests for the exact bundle field/hash/ref formula, six distinct lineages, `first_complete_verified_attempt_per_cell` with an incomplete predecessor, refusal to skip a first complete FAIL, missing/extra/duplicate/reordered cells, cross-release/provider-manifest/provider-corpus/source-parent/accepted-run/profile/revision drift, timeout deadline-ref presence, cancel deadline-ref absence, stable-zero failure, projection path/private leakage, and Task 14/Task 12-style raw-ledger rebuild detecting a self-hashed forged PASS candidate.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py -k "probe_authority or first_complete_verified_attempt_per_cell or probe_matrix_distinct_lineage"
```

**GREEN:**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py -k "probe_authority or first_complete_verified_attempt_per_cell or probe_matrix_distinct_lineage"
uv run python -m py_compile app/learn/hybrid/benchmark_v2_probe_authority.py scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py
git diff --check
```

**Commit:** `feat(benchmark-v2): materialize regression probe authority`

### Task 11: Consume probe authority before authorization

**Allowed files only:**

- Modify `app/learn/hybrid/benchmark_v2_durable_claim.py`.
- Modify `scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py`.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py`.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py`.

**RED:** Add tests that require the exact `--probe-authority` flag/path, reject missing/non-PASS/malformed/path-bearing bundles and every join drift, derive profile IDs only from bundle/runtime evidence, require payload/envelope v2, and prove `claim_identity`, `claim_id`, `authorization_id`, paths, and one-claim namespace remain stable.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py -k "probe_authority or authorization_payload_v2 or stable_claim_identity"
```

**GREEN:**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py
uv run python -m py_compile app/learn/hybrid/benchmark_v2_durable_claim.py scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py
git diff --check
```

**Commit:** `feat(benchmark-v2): bind probe authority before holdout`

### Task 12: Bind the final public report

**Allowed files only:**

- Modify `scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py`.
- Modify `tests/test_portfolio_hybrid_v1_1_release_gate_v2.py`.

**RED:** Add tests requiring `--probe-authority`, exact pathless ref propagation, equality with authorization payload v2, regression accepted/provider/release joins, and refusal of missing, FAIL, mismatched, path-bearing, or raw-parent data. Preserve all dependency-manifest v1 tests unchanged.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_release_gate_v2.py -k "probe_authority or public_report"
```

**GREEN:**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_release_gate_v2.py
uv run python -m py_compile scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py
git diff --check
```

**Commit:** `feat(benchmark-v2): assemble probe-bound public report`

S4 remains its existing separately reviewed commit. No slice combines P0, P1, Task 11, Task 12, or S4.

---

## 6. Frozen DAG and later runtime order

Implementation order:

```text
S3
  -> public boundary
  -> P0 genuine probe evidence
  -> P1 public probe authority
  -> Task 11 authorization consumer
  -> Task 12 report consumer
  -> S4 inventory and holdout bridge
  -> deterministic integration
  -> STOP before actual models
```

Deferred runtime order, outside this implementation and only after separately authorized sealing:

1. Run dry-run, then regression actual.
2. Run cancel probes, then genuine timeout probes, for Omni/Qwen/VISTA. Each selected probe is its own attempt and operation; cleanup reaches stable zero.
3. Materialize accepted regression v2 under its existing first-complete policy.
4. Materialize `regression/probe-authority.json` under `first_complete_verified_attempt_per_cell`.
5. Run the unchanged four-flag regression scorer and independent regression review.
6. Task 14 runs leakage review and the corrected authorizer command with `--probe-authority`.
7. Task 15 runs the one authorized holdout and cleanup/materialization flow.
8. Task 16 scores holdout and assembles the final report with the same probe-authority input.

The accepted actual attempt and six probe attempts need not be adjacent; their release, provider-manifest, provider-corpus, and source-parent bindings must be identical.

---

## 7. Explicit implementation stop and deferrals

P0/P1/Task 11/Task 12 use only synthetic, temporary, test-owned evidence. They must not:

- run Omni, Qwen, VISTA, any model/provider/service, a GPU, or a GUI;
- execute the real 120-second deadline path;
- write canonical `runtime_state/.../cancel-probes.json`, `timeout-probes.json`, `probe-authority.json`, authorization, claim, anchor, score, report, dependency receipt, review, or seal;
- create or repair file/HKCU anchors, mutate the real ledger, reseal fixtures, commit runtime evidence, push, or make an empirical PASS claim.

If deterministic tests cannot prove runtime-owned monotonic expiry, production receipt v2, six distinct-lineage first-complete selection, public pathlessness, and stable claim identity, Task 11 remains fail-closed. Do not fall back to v1 receipts, relabel cancel as timeout, add probe fields to accepted/scorer contracts, reinterpret provider-manifest profile refs, or solicit manual review prose as authority.
