# Benchmark v2 Scoring-Bridge Prerequisite Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan one task at a time.

**Goal:** Close the production scoring-bridge gap, with provider-safe score-input materialization and closed release/run binding, before Task 13 final seal or any actual model run.

**Architecture:** Task 10 remains the immutable private release authority. Task 9 provider-safe evidence is projected by an offline materializer into a separate immutable accepted-run authority. The existing isolated private-scorer child joins those two authorities, derives Gold cases only in child memory, and emits a public v3 result whose binding can be compared without exposing private data. Regression and holdout use separate accepted-input contracts because their attempt-selection authorities differ.

**Tech Stack:** Python 3.11, canonical UTF-8 JSON/JSONL, SHA-256 refs, pytest, the existing Windows Job/capability-pipe scorer isolation, and the existing benchmark-v2 lifecycle/claim validators.

**Spec:** This amendment is subordinate to `docs/superpowers/plans/2026-08-26-portfolio-hybrid-v1-1-benchmark-v2-plan.md` and incorporates the accepted decisions in `.superpowers/sdd/2026-08-26-portfolio-hybrid-v1-1-benchmark-v2-plan/task-11b-design.md`. Where this amendment freezes a previously missing scoring-bridge field, action, or ordering rule, this amendment controls that bridge only.

---

## 1. Evidence, scope, and frozen DAG

The current production path has four verified gaps:

1. `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py` seals `benchmark_v2_runner_actual_body_v1` and `benchmark_v2_runner_actual_result_v1`, but does not produce `automatic_prediction_v2`, `benchmark_v2_prediction_run_v2`, `benchmark_v2_lifecycle_bundle_v2`, or an accepted scoring input.
2. `app/learn/hybrid/benchmark_v2_actual.py` retains Omni, Qwen, fusion, and final review projections, but drops the exact pre-VISTA submitted request set after the calibration sequence. A later proposal therefore cannot yet be proven to refine a preselected candidate rather than select it.
3. `app/learn/hybrid/benchmark_scorer_v2.py` accepts the legacy inline synthetic private manifest and a separate lifecycle path, while Task 10 seals `portfolio_hybrid_v1_1_benchmark_v2_private_manifest_v1` and Task 13 supplies only the four public flags.
4. The current public v2 score does not expose one identical binding joining Task 10 release authority to Task 9 accepted-run authority, and the holdout accepted-input schema/consumer is not present in the code inventory that Task 10 must finally seal.

Only the following dependency chain is authorized:

```text
Task 9 U0-U3 prerequisite
  -> S1 provider-safe pre-VISTA evidence and accepted regression materializer
  -> S2 shared Task 10 private-release validator and child-only Gold derivation
  -> S3 four-flag scorer bridge and public v3 regression binding
  -> S4a preserve Task 11A genesis/claim and add verify-only anchors plus fixed holdout attempt chain
  -> S4b holdout pathless accepted-input/scoring contracts and consumers
  -> deterministic tests and independent code/seal review
  -> Task 13 final seal
  -> actual regression, then authorized single holdout, then public report
```

S1-S4 are code/schema work and stop before Task 13 final sealing and before `--actual-models`. They do not add a model, provider, supervisor, service, process type, panel route, or action executor. Existing four arms and frozen estimand/gate semantics remain unchanged.

### Global invariants

- Task 10 private manifest contains only frozen release inputs. It must contain no attempt, ledger, automatic prediction, lifecycle, accepted-run, score, authorization, claim, or future-output ref.
- Provider runtime and both materializers must not import or read the private manifest, corpus parent, Gold, private scorer, or private output. They use only provider-public seals and provider-safe runtime evidence.
- Scoring does not authorize execution. Every new artifact uses exact safety:

  ```json
  {"artifact_is_authorization":false,"execute_binding_enabled":false,"display_only":true}
  ```

- No action/click/input is part of S1-S4. Test windows remain noninteractive and test-owned. No production model, provider service, GPU lease, durable claim, file anchor, or HKCU anchor is created by tests.
- Preserve the frozen threat model: local file and HKCU anchors prevent ordinary accidental replay but do not resist the same Windows administrator deleting both roots; `external_append_only_witness_present` remains `false`.
- All contracts are closed shapes. Canonical embedded bytes are decoded, parsed, recanonicalized, and hashed; unknown/missing fields, noncanonical bytes, ref drift, path aliases, symlinks/reparse aliases, or absolute-path leakage fail closed.
- A public `PASS` is display-only and cannot authorize holdout. Holdout still requires the Task 11 authorizer code executed at Task 14, independent leakage/authorization review, dual anchors, and the Task 15 one-claim lifecycle.

---

## S1. Provider-safe selection and the accepted regression producer

**Depends on:** Task 9 U0-U3.
**Produces:** production-materialized `benchmark_v2_accepted_regression_score_input_v2`. Version 1 remains the superseded SDD draft and is never accepted by production.
**Commit after GREEN:** `feat(benchmark-v2): materialize accepted score inputs`

### S1.1 Freeze the pre-VISTA evidence boundary

Add `benchmark_v2_actual_pre_vista_evidence_v1` to every actual screen-group projection. Its exact fields are:

```text
contract_version
provider_group_ref
omni_inventory_envelope
qwen_bindings_envelope
fusion_result_envelope
submitted_vista_request_envelopes
safety
content_sha256
```

Each singular envelope is exactly `{ref, canonical_bytes_b64}`; each list item is the same closed shape. These four existing raw classes do not have `artifact_id`, so their pathless refs use exact class-specific formulas, where `B` is the decoded compact-canonical UTF-8 JSON bytes:

```text
Omni inventory:       id = "omni-inventory/" + sha256(UTF8("benchmark-v2-omni-inventory\0") || B)
Qwen bindings:        id = "qwen-bindings/" + sha256(UTF8("benchmark-v2-qwen-bindings\0") || B)
fusion result:        id = "fusion-result/" + sha256(UTF8("benchmark-v2-fusion-result\0") || B)
submitted VISTA req:  id = "submitted-vista-request/" + sha256(UTF8("benchmark-v2-submitted-vista-request\0") || B)
all four:             content_sha256 = sha256(B)
```

The envelope position determines which formula is legal; a generic `artifact_ref()` that reads a nonexistent `artifact_id` is forbidden. `submitted_vista_request_envelopes` is candidate-ID sorted and must equal, neither omit nor add to, the exact requests returned by the existing `build_vista_requests` call for all and only `BOUND` fusion candidates. Capture this evidence at the existing calibration step. The managed review worker must preserve that exact existing list under final orchestration field `hybrid_vista_requests`; it must not rebuild, rename, or reinterpret the list. The actual projector validates the propagated Omni/Qwen/fusion/request objects with their existing closed validators and may call `build_vista_requests` only as a deterministic validator for canonical byte equality. Published envelopes always contain the propagated validated objects, never a reconstructed fallback. The Runtime persistence/replay boundary must require the complete `pre_vista_evidence` contract and reject the old projection shape.

Use one nonrecursive identity rule for every new sealed projection in S1-S4. Let `semantic_payload` be the closed object without `artifact_id` and `content_sha256`; let `semantic_sha256 = sha256(UTF8("<contract-version>\0") || canonical_json(semantic_payload))`; set `artifact_id = "<artifact-prefix>/" + semantic_sha256`; then set `content_sha256 = sha256(canonical_json(object_without_content_sha256))`. Its public ref is exactly `{id: artifact_id, content_sha256}`. Validators recompute both hashes and reject a caller-supplied ID. Existing contracts retain their existing formula unless this amendment explicitly versions them.

The final review/VISTA proposal is deliberately outside this contract. Materialization has two pure phases:

1. `select_pre_vista_prediction_rows(...)` receives the provider case, target-specific provider-safe incumbent response, Omni inventory, Qwen bindings, fusion result, and submitted VISTA requests. Its signature must not accept VISTA proposals/results. The incumbent response is mandatory because `qwen_only` is selected from its `screen_reading.screen_inventory.available_actions`; Qwen bindings are not a substitute for that raw source.
2. `attach_vista_outcomes(...)` receives the already selected rows and final VISTA proposals, and may only attach an outcome to the row's already bound `candidate_id`, `target_binding_ref`, and `vista_request_ref`.

A proposal/result mutation must leave candidate selection and all sealed binding/request refs byte-identical.

### S1.2 Freeze arm-aware evidence contracts and deterministic target selection

All 120 frozen goals have exact grammar `Select the <role> labeled '<label>'`. Parse it strictly; reject any other grammar. Normalize text only by Unicode-preserving trim and collapsing internal whitespace. Do not case-fold, fuzz, repair OCR characters, rank by confidence, or use VISTA as a tie-breaker.

The exact role equivalence table is:

| Goal role | Accepted provider-safe roles |
|---|---|
| `button` | `button` |
| `checkbox` | `checkbox` |
| `combobox` | `combobox`, `select`, `dropdown` |
| `link` | `link`, `hyperlink` |
| `menuitem` | `menuitem`, `menu_item` |
| `tab` | `tab`, `tab_item` |
| `textbox` | `textbox`, `input`, `text_input`, `search_box`, `search_input`, `edit` |

The source and rule for each arm are fixed:

- `qwen_only`: use only the target-specific incumbent response's `screen_reading.screen_inventory.available_actions`; exact normalized label plus the table above selects its bbox.
- `omni_only_discovery`: use only the Omni provider item `safe_role`/`safe_text` joined to that immutable candidate's bbox.
- `omni_to_qwen` and `omni_to_qwen_vista`: use the same exact Qwen role/label binding joined to the same fusion candidate. Only `BOUND` is eligible, and it must have exactly one matching raw submitted VISTA request. The baseline row retains the request ref even though it does not consume a result.

Replace the unversioned assumption that every selected arm has a fusion parent. New automatic predictions use these four closed artifacts and the S1.1 identity rule:

| Contract | Exact fields | Prefix |
|---|---|---|
| `sealed_prediction_source_parent_v1` | `contract_version, artifact_id, case_ref, arm_scope, source_kind, evidence_refs, actual_screen_group_ref, capture_ref, safety, content_sha256` | `prediction-source-parent` |
| `sealed_prediction_bbox_v1` | `contract_version, artifact_id, case_id, arm_scope, candidate_id, coordinate_space, xyxy, capture_ref, source_parent_ref, safety, content_sha256` | `prediction-bbox` |
| `sealed_target_binding_v4` | `contract_version, artifact_id, case_id, arm_scope, candidate_id, source_parent_ref, capture_ref, bbox_ref, safety, content_sha256` | `target-binding` |
| `sealed_vista_request_v4` | `contract_version, artifact_id, case_id, arm_scope, candidate_id, target_binding_ref, source_parent_ref, capture_ref, bbox_ref, submitted_request_ref, submission_status, safety, content_sha256` | `vista-request` |

`case_ref` is the exact provider `{case_id, case_content_sha256}`. `coordinate_space` is literal `capture_pixel_xyxy`; `xyxy` is four canonical integers with positive area. `arm_scope` is exactly one of `["qwen_only"]`, `["omni_only_discovery"]`, or `["omni_to_qwen","omni_to_qwen_vista"]`. The paired hybrid rows must reference the same source parent, bbox, binding, and request. Only the paired scope can create `sealed_vista_request_v4`, whose `submission_status` is literal `SUBMITTED`.

`source_kind` and the exact `evidence_refs` keys are discriminated and closed:

- `incumbent_qwen_action`: `incumbent_response_ref, available_action_ref`;
- `omni_inventory_item`: `omni_inventory_ref, omni_item_ref`;
- `hybrid_bound_fusion_candidate`: `omni_inventory_ref, qwen_bindings_ref, fusion_result_ref, fusion_candidate_ref`.

For nested raw values lacking native IDs, derive the evidence ref with the same S1.1 rule using contract `benchmark_v2_nested_provider_evidence_ref_v1`, prefix `nested-provider-evidence`, and semantic payload `{evidence_kind, case_ref, actual_screen_group_ref, canonical_value_sha256}`. `canonical_value_sha256` hashes the exact nested canonical value re-extracted while locally validating raw `body.json`; do not trust a copied value, and publish only the resulting pathless ref/projection. Thus Qwen-only and Omni-only bindings contain no `fusion_ref`, while hybrid binding proves an actual `BOUND` fusion candidate. `submitted_request_ref` similarly points to the exact provider-safe raw request in `benchmark_v2_actual_pre_vista_evidence_v1`; it is never synthesized from a proposal.

Zero exact matches emits the arm row as `missing` with reason `target_not_present_pre_vista`; it never fabricates a binding or request. More than one exact match, a matching Qwen binding marked ambiguous, a non-unique ambiguity set, duplicate candidate/request, or conflicting ref is fatal for the whole attempted materialization. A non-`BOUND` hybrid candidate emits `missing` with reason `fusion_not_bound`; it is not repaired by a proposal.

VISTA outcome mapping is closed:

| Proposal state | Prediction outcome |
|---|---|
| `PROPOSED` with canonical in-bounds point | `validated` |
| `VISTA_FAILED` with exact `request_timeout` failure category | `timeout` |
| other `VISTA_FAILED` | `failed` |
| `VISTA_OUT_OF_BOUNDS` | `out_of_bounds` |
| `TRANSFORM_INVALID` | `failed` |
| no proposal for the selected submitted request | `missing` |

Unknown proposal states, multiple results for a selected request, or a result referring to a different candidate/request are fatal. There is no fallback to the highest-confidence candidate.

### S1.3 Freeze the accepted regression envelope

`accepted-run-ref.json` is pretty-canonical UTF-8 JSON with one trailing newline and contract `benchmark_v2_accepted_regression_score_input_v2`. Version 2 adds pathless verified parent projections and transitive runner-result/ledger linkage to the earlier v1 draft. Its exact top-level fields are:

```text
contract_version
content_sha256
benchmark_release_id
partition
corpus_parent_ref
provider_manifest_ref
provider_corpus_ref
selection_policy
attempt_ref
attempt_ledger_ref
automatic_prediction_ref
selected_lifecycle_ref
verified_parent_projections
prediction_run_envelope
lifecycle_bundle_envelope
safety
```

`partition` is literal `regression`; `selection_policy` is literal `first_complete_lifecycle_verified_attempt`. The parent/provider refs are the exact provider-public Task 10 refs, including corpus-parent file SHA. `attempt_ref`, `attempt_ledger_ref`, `automatic_prediction_ref`, and `selected_lifecycle_ref` are exact `{id, content_sha256}` objects.

`verified_parent_projections` has exactly four fields:

```text
runner_ledger_prefix_projection_envelope
attempt_journal_projection_envelope
actual_body_projection_envelope
actual_result_projection_envelope
```

Each field is exactly `{ref, canonical_bytes_b64}`, but the decoded bytes are a new pathless verified projection, never the raw ledger, journal, body, result, cleanup receipt, or lifecycle artifact. The materializer reads those raw files locally, validates their canonical bytes, absolute path fields, file/content hashes, hash chains, aliases, and transitive refs, and then discards the raw bytes before constructing accepted output. Raw files may contain `attempt_dir`, owner-journal roots, screenshot paths, or other absolute paths and therefore must never be embedded, logged, printed, or passed to the scorer.

Using the S1.1 identity rule, the projection contracts and exact fields are:

| Contract | Exact fields |
|---|---|
| `benchmark_v2_runner_ledger_prefix_verified_projection_v1` | `contract_version, artifact_id, partition, raw_prefix_sha256, attempt_ledger_pre_result_ref, through_result_terminal_sequence, through_result_terminal_envelope_sha256, attempt_ref, body_file_ref, cleanup_receipt_ref, result_file_ref, result_event_projection_ref, verified, safety, content_sha256` |
| `benchmark_v2_attempt_journal_verified_projection_v1` | `contract_version, artifact_id, attempt_ref, raw_journal_sha256, terminal_event_ref, started_request_count, terminal_or_unknown_request_count, cleanup_projection_ref, verified, safety, content_sha256` |
| `benchmark_v2_actual_body_verified_projection_v1` | `contract_version, artifact_id, attempt_ref, body_contract_version, raw_file_sha256, body_content_sha256, screen_group_count, case_arm_multiset_sha256, pre_vista_evidence_refs, verified, safety, content_sha256` |
| `benchmark_v2_actual_result_verified_projection_v1` | `contract_version, artifact_id, attempt_ref, result_contract_version, raw_file_sha256, result_content_sha256, body_projection_ref, cleanup_projection_ref, attempt_ledger_pre_result_ref, runner_ledger_prefix_projection_ref, result_event_projection_ref, verified, safety, content_sha256` |

Projection prefixes are respectively `verified-runner-ledger-prefix`, `verified-attempt-journal`, `verified-actual-body`, and `verified-actual-result`; every `verified` is literal `true`. Raw byte SHA fields are hashes only, not refs to retrievable bytes. `body_file_ref` and `result_file_ref` are pathless exact `{file_sha256, content_sha256}`; `attempt_ref` is `{id:"runner-attempt/" + attempt_id, content_sha256:raw_attempt_ref.content_sha256}`. The journal and result projections reference pathless cleanup/lifecycle projections from the new lifecycle bundle below.

### S1.3.1 New production run and lifecycle contracts

Do not reuse or silently reinterpret the scorer's existing synthetic `benchmark_v2_prediction_run_v2` or `benchmark_v2_lifecycle_bundle_v2`. Production accepts only these new closed v3 contracts:

| Contract | Exact fields |
|---|---|
| `benchmark_v2_prediction_run_v3` | `contract_version, artifact_id, benchmark_release_id, partition, corpus_parent_ref, provider_manifest_ref, provider_corpus_ref, attempt_ref, projected_attempt_ledger_ref, raw_ledger_prefix_verification_ref, automatic_prediction_ref, selected_lifecycle_ref, sealed_artifact_envelopes, safety, content_sha256` |
| `benchmark_v2_lifecycle_bundle_v3` | `contract_version, artifact_id, benchmark_release_id, partition, attempt_ref, projected_attempt_ledger_ref, raw_ledger_prefix_verification_ref, selected_lifecycle_ref, attempt_cleanup_projection_ref, screen_group_lifecycle_projection_refs, sealed_artifact_envelopes, safety, content_sha256` |
| `benchmark_v2_projected_attempt_ledger_v1` | `contract_version, artifact_id, benchmark_release_id, partition, raw_ledger_prefix_verification_ref, entries, selected_attempt_ref, selected_lifecycle_ref, safety, content_sha256` |
| `benchmark_v2_runner_event_verified_projection_v1` | `contract_version, artifact_id, partition, event_kind, sequence, attempt_ref, previous_event_projection_ref, raw_event_sha256, load_bearing_refs, safety, content_sha256` |
| `benchmark_v2_lifecycle_verified_projection_v1` | `contract_version, artifact_id, attempt_ref, lifecycle_kind, raw_evidence_sha256, terminal_status, cleanup_stable_zero, resource_counts, started_request_count, terminal_or_unknown_request_count, parent_refs, safety, content_sha256` |

Their S1.1 prefixes are `prediction-run`, `lifecycle-bundle`, `projected-attempt-ledger`, `verified-runner-event`, and `verified-lifecycle`, respectively. `lifecycle_kind` is one of `attempt`, `screen_group`, or `cleanup`; `resource_counts` is the existing exact closed zero-count map, not an extensible dictionary.

For `benchmark_v2_runner_event_verified_projection_v1`, raw `event_type=regression_attempt,status=opened/body_complete` maps to `event_kind=opened/body_complete`, while raw `event_type=cleanup/result` maps directly to `cleanup/result`. `sequence` is the original ledger sequence; `previous_event_projection_ref` is `null` only for sequence zero and otherwise resolves to the immediately prior projected event. `raw_event_sha256` hashes the locally validated complete raw event envelope's compact-canonical bytes, but those bytes are not published. `load_bearing_refs` is a closed discriminated object:

```text
opened:        {attempt_ref}
body_complete: {body_file_ref}
cleanup:       {cleanup_receipt_ref, cleanup_projection_ref}
result:        {result_file_ref, attempt_ledger_pre_result_ref}
```

All file/receipt refs above are pathless. Its exact formula is `artifact_id = "verified-runner-event/" + sha256(UTF8("benchmark_v2_runner_event_verified_projection_v1\0") || canonical_json(semantic_payload))`, where `semantic_payload` is the closed object without `artifact_id` and `content_sha256`; `content_sha256 = sha256(canonical_json(object_without_content_sha256))`. No raw event `artifact_id` is assumed.

`benchmark_v2_prediction_run_v3.sealed_artifact_envelopes` contains only provider-safe pathless artifacts: `automatic_prediction_v2`, the projected ledger, every runner-event projection through the selected result, source parents, bboxes, bindings, requests, and pre-VISTA evidence. `benchmark_v2_lifecycle_bundle_v3.sealed_artifact_envelopes` contains the byte-identical projected ledger and complete runner-event projection set plus pathless lifecycle/cleanup projections. No raw runtime bytes appear in either. Validators require exact event-ref set equality across both v3 envelopes; no missing, extra, or reminted copy is allowed.

Each projected-ledger entry is exact `{sequence, attempt_ref, observed_state, event_projection_refs, lifecycle_ref, selection_eligible}`. `sequence` is first-open order; `observed_state` is one of `opened`, `body_complete`, `cleanup`, or `result`; `event_projection_refs` is the ordered nonempty list of pathless event refs; `lifecycle_ref` is an exact ref or `null`; `selection_eligible` is boolean. Mapping is deterministic: replay raw v2 ledger locally, collapse each deduplicated attempt through its last observed state, project raw events without paths, and mark eligible only after result plus stable-zero lifecycle validation. `selected_attempt_ref`/`selected_lifecycle_ref` identify the first eligible entry.

The graph closes without a hash cycle as follows:

1. Validate raw events locally through cleanup and recompute `attempt_ledger_pre_result_ref`; require exact equality with the ref inside raw `actual_result_v2`.
2. Require body-complete event `body_file_ref`, cleanup event `cleanup_receipt_ref`, raw result `body_ref`/`cleanup_receipt_ref`, and result event `result_file_ref` to resolve to the same locally validated body, cleanup, and result hashes.
3. Project events in sequence. The cleanup event's `cleanup_projection_ref` resolves to the lifecycle bundle's cleanup projection. The result event carries the result file ref plus pre-result ref, but does not reference the result projection.
4. Build the result projection afterward; its `result_event_projection_ref` resolves to that result event and its `attempt_ledger_pre_result_ref` is byte-equal to the event's load-bearing ref. This one-way edge avoids self-reference.
5. Require the runner-prefix projection's terminal event ref, every projected-ledger `event_projection_refs` entry, and both v3 envelope event sets to resolve to the same projected event objects. The selected ledger entry ends at the result-event projection ref and carries the selected stable-zero lifecycle ref; the separate actual-result projection resolves that same terminal event.

The two ledger refs are intentionally distinct: top-level accepted `attempt_ledger_ref` equals `prediction_run.projected_attempt_ledger_ref`, while `raw_ledger_prefix_verification_ref` equals `verified_parent_projections.runner_ledger_prefix_projection_envelope.ref`. Both v3 contracts must carry both refs, and the projected ledger must point to the raw verification projection. `actual_result_v2.attempt_ledger_pre_result_ref` remains a local raw through-cleanup hash input; its validated value is represented only in the pathless ledger projection fields.

`prediction_run_envelope` and `lifecycle_bundle_envelope` contain those v3 contracts. Their refs, projected ledger, automatic prediction, selected lifecycle, and four verified-parent projections form one hash-linked attempt. Any local raw byte mutation changes at least one projection hash and therefore remints or invalidates the accepted input, without publishing the raw bytes.

### S1.4 Freeze first-complete selection

Version the production runner chain before any actual run: `portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2` keeps exact outer fields `contract_version,event,event_sha256` and accepts `regression_attempt`, `cleanup`, and `result`; `benchmark_v2_runner_actual_result_v2` has exact fields `contract_version,attempt_ref,attempt_dir,body_ref,cleanup_receipt_ref,attempt_ledger_pre_result_ref,screen_group_count,status,artifact_is_authorization,execute_binding_enabled,content_sha256`; and `benchmark_v2_runner_result_payload_v1` has exact fields `contract_version,attempt_ref,attempt_dir,mode,provider_id,status,output_ref,artifact_is_authorization,execute_binding_enabled,content_sha256`, with literal `status=terminal`.

`actual_result_v2.attempt_ledger_pre_result_ref` is a closed pathless logical ref with exact fields `contract_version,id,attempt_ref,terminal_sequence,terminal_envelope_sha256,prefix_sha256`. For exact raw through-cleanup JSONL bytes `P`, including the final newline:

```text
contract_version = "benchmark_v2_runner_ledger_pre_result_ref_v1"
id = "runner-ledger-pre-result/" + sha256(UTF8("benchmark-v2-runner-ledger-pre-result\0") || P)
attempt_ref = the exact derived runner attempt ref
terminal_sequence = the cleanup event sequence
terminal_envelope_sha256 = sha256(canonical_json(the complete cleanup event envelope))
prefix_sha256 = sha256(P)
```

The raw result is written after cleanup and embeds that exact ref; the final `event_type=result` then references the result file. The complete local prefix ends at the result event, while accepted output carries only verified projections and hashes. No production validator accepts old result/ledger versions.

The authoritative cleanup receipt is persisted at fixed `<attempt_dir>/cleanup.json` before the cleanup event, with create-new-or-byte-identical bytes, flush, and `fsync`. Every replay must revalidate its closed receipt, `stable_zero` status, exact zero resource map, attempt lineage, and required effect refs, and must bind the ledger cleanup payload to that same receipt. If a crash occurs after the file is durable but before the cleanup event append, `--cleanup-open-attempts` performs a fresh zero-resource reconciliation using the receipt's original reason; it may reuse the existing file only when the fresh receipt is byte-identical, then append the missing cleanup event. A differing or non-stable receipt remains fail closed.

Replay the canonical runner ledger in append order. Candidate order is the order of each attempt's first valid `event_type=regression_attempt,status=opened` event. Deduplicate by exact `attempt_ref`: a repeated `opened`, an event before `opened`, more than one `body_complete`, `cleanup`, or `result`, or any cross-attempt directory/ref reuse is invalid rather than a new candidate. An attempt qualifies only when all of the following are true:

1. Its state subsequence is exactly `opened -> body_complete -> cleanup -> result`. The body-complete output ref validates exact `body.json`; cleanup validates the authoritative receipt; result v2 validates the same body/cleanup refs and the through-cleanup ledger prefix; the result event validates exact `result.json`. This transitive chain must reach the same attempt, release, partition, provider refs, file SHA, content SHA, and immediate-child directory.
2. Body contains exactly 12 provider screen groups, five cases per group, and four ordered arms per case, without duplicate group/case/arm keys.
3. Its own append-only attempt journal validates from raw bytes, reaches one terminal result, and binds every started provider request to terminal/unknown lifecycle evidence.
4. The authoritative attempt cleanup receipt is present, hash-linked, `stable_zero`, and has exact zero live service/worker/window/process/lease/resource counts; every screen-group lifecycle also validates stable zero.
5. The projection rules in S1.1-S1.2 produce one closed automatic prediction and one closed lifecycle bundle without ambiguity or ref mismatch.

Select the earliest qualifying first-opened attempt. The locally verified runner-ledger projection ends at that attempt's exact result event. Later events are not needed to validate the immutable selection, and a later complete attempt can never replace it. Do not inspect prediction quality, score, gate outcome, or VISTA success rate when choosing. Incomplete or cleanup-indeterminate attempts remain evidence; retry eligibility remains the canonical independent-review decision and is not granted by this materializer.

### S1.5 Exact production action

Add one mutually exclusive runner action, `--materialize-score-input`. It launches no provider and is read-only except for create-only-or-byte-identical publication of `--output`. It accepts no private input and no arbitrary body/result/journal path.

```powershell
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --partition regression --materialize-score-input --attempt-ledger runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger/regression/events.jsonl --output-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/attempts --output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json
```

Resolve the ledger and attempt directories beneath their supplied roots, require each selected attempt directory to be an immediate ordinary child, open fixed filenames only, reject aliases/reparse points, and close every file handle before return. Existing `--dry-run`, `--actual-models`, probe, and cleanup actions retain their semantics.

### S1.6 Allowed files, tests, and acceptance

**Allowed files:**

- Modify `app/learn/hybrid/benchmark_v2_actual.py`.
- Modify `app/learn/hybrid/benchmark_v2_predictions.py`.
- Modify `app/learn/hybrid/benchmark_v2_lifecycle.py`.
- Modify `app/learn/hybrid/benchmark_v2_runtime.py` only for the mandatory persistence/replay validator.
- Modify `app/learn/workflow_worker.py` only to preserve the exact existing `hybrid_vista_requests` list in final orchestration.
- Modify `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py`.
- Modify only the focused tests `tests/test_learning_workflow_stage_execution.py`, `tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py`, `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py`, `tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py`, `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py`, and `tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py`.

**RED tests:** exact goal grammar/role aliases; zero/duplicate/ambiguous matches; all four raw-class ref formulas; arm-aware source/bbox/binding/request formulas; Qwen/Omni rejection of fabricated fusion; non-`BOUND` handling; VISTA-result non-selection; exact submitted-request coverage; local raw-parent tamper/remint; any raw byte or absolute path in accepted output; v1 result/ledger and v2 run/lifecycle rejection; exact pre-result ref shape/formula; duplicate/reordered projected events; wrong event-kind/load-bearing refs; missing/extra/different event projections across the two v3 envelopes; transitive result/cleanup/event mismatch; projected-ledger/raw-verification ref conflation; missing/stale cleanup; later-complete cherry-pick; arbitrary path/alias rejection; noncanonical bytes; and a real Task 9 body/result-to-accepted-input producer test. A test-only handcrafted accepted envelope is not production evidence.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py
```

**GREEN acceptance:** the same command passes; a proposal-only mutation leaves selection refs identical; the exact CLI rematerializes byte-identically from an offline fixture; provider/service/model launch counters remain zero; cleanup assertion reports no process, Job, pipe, handle, lease, window, or temporary-path residue.

---

## S2. Shared Task 10 private-release authority and Gold boundary

**Depends on:** S1 contract frozen.
**Produces:** one private release validator used by both sealer and scorer.
**Commit after GREEN:** `refactor(benchmark-v2): share private release validation`

### S2.1 One authority module

Create `app/learn/hybrid/benchmark_v2_private_release.py`. Move, do not duplicate, Task 10's exact private-manifest schema, inventory key sets, release constants, fixed logical sibling names, path restrictions, and frozen-release verification into this module. The sealer script may construct a manifest through the shared authority; the scorer must never import private helpers from the sealer script.

Required public interfaces:

```python
validate_task10_private_release_manifest(*, manifest_bytes: bytes) -> dict[str, object]
validate_task10_private_release_bundle(*, private_manifest_path: Path) -> dict[str, object]
derive_private_scoring_cases(*, validated_release: Mapping[str, object], partition: str) -> list[dict[str, object]]
```

The manifest-only function supports sealing without requiring not-yet-published siblings. The bundle function reads the private manifest once, requires exact pretty-canonical bytes and self hash, resolves only fixed ordinary siblings `benchmark-v2-provider-manifest.json` and `provider-corpus.v2.json`, and returns validated private state without Gold-derived public data.

Both functions require exact code/config/test inventory key sets, rehash every entry beneath compile-time repository `ROOT`, reject absolute/`..`/symlink/reparse/noncanonical aliases, and require `private_scorer_refs` to equal the scorer module and entrypoint entries in the verified inventory. The bundle validator also verifies frozen parent file/content hashes, canonical parent and Gold, Gold approval/reviewer state, all 24 screenshots and dimensions, exactly 120 targets, zero sealed predictions, provider corpus/manifest lineage, arm order, estimand/gate/profile/code refs, release, and non-authorizing safety.

### S2.2 Child-only Gold derivation

Only the already isolated scorer child may call `derive_private_scoring_cases`. Neither public launcher, provider runner, accepted-input materializer, authorizer, nor report assembler may derive or receive these cases.

For each validated Gold record derive:

```text
case_id     = sha256("benchmark-v2-case\0" + screen_id + "\0" + target_id)
screen_group = sha256("benchmark-v2-screen-group\0" + screen_id)
```

Retain only `case_id`, `screen_group`, `partition`, `important_target`, and `acceptable_regions`. Require the opaque multiset to equal the provider corpus and accepted prediction for the selected partition: 12 groups, five cases per group, 60 cases, four arms per case. Target IDs, labels, geometry beyond acceptable regions, annotations, reviewers, screenshots, Gold paths, inventory maps, and private paths never enter public artifacts or stdout.

The legacy `portfolio_hybrid_v1_1_private_manifest_v2_1_synthetic` may remain only as a direct fixture for pure score-math unit tests. Production launch and bundle validation reject it.

### S2.3 Allowed files, tests, and acceptance

**Allowed files:**

- Create `app/learn/hybrid/benchmark_v2_private_release.py`.
- Modify `scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py`.
- Modify `app/learn/hybrid/benchmark_scorer_v2.py` only to consume the shared authority.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py` and `tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py`.

**RED tests:** Task 10 canonicalization/self hash; extra/missing field; inventory byte/key/direct-ref drift; path aliases; parent/Gold/screenshot/reviewer drift; provider-manifest/corpus/ref drift; release/arm/config/profile mismatch; forbidden future refs; synthetic production input; and leakage of any private field.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py
```

**GREEN acceptance:** the same command passes; sealer and scorer import one shared field/inventory authority; source inspection finds no scorer import from `scripts.seal_portfolio_hybrid_v1_1_benchmark_v2`; only the child derives cases; tests leave only their temporary roots and remove them.

---

## S3. Four-flag scorer bridge, input binding, and public v3

**Depends on:** S1 and S2.
**Produces:** a public-safe regression score bound to release plus accepted attempt.
**Commit after GREEN:** `feat(benchmark-v2): bind scorer pass to release and accepted run`

### S3.1 Exact input binding

After both authorities validate, build closed `private_scorer_input_binding_v1` with exact fields:

```text
contract_version
benchmark_release_id
partition
private_manifest_ref
corpus_parent_ref
provider_manifest_ref
provider_corpus_ref
accepted_run_ref
attempt_ref
attempt_ledger_ref
automatic_prediction_ref
selected_lifecycle_ref
estimand_ref
gate_ref
safety
```

`private_manifest_ref` is exactly `{contract_version, file_sha256, content_sha256}` and omits its path. `corpus_parent_ref` includes `{contract_version, artifact_id, file_sha256, content_sha256}` and omits its path. `provider_manifest_ref` retains only its provider-public logical relative path and file SHA. `provider_corpus_ref` is the exact Task 10 logical ref. `accepted_run_ref` is exactly `{contract_version:"benchmark_v2_accepted_regression_score_input_v2", file_sha256, content_sha256}`. The four attempt/prediction/lifecycle refs are exact `{id, content_sha256}`; specifically, `attempt_ledger_ref` is the v3 projected-ledger ref, never the local raw-prefix verification ref. `estimand_ref` and `gate_ref` are exact `{contract_version, file_sha256}`.

Compute the input binding once and require its canonical bytes to be equal in the private score, child public, launch receipt, final binding, and final public. Freeze the complete graph:

| Contract | Exact fields |
|---|---|
| `portfolio_hybrid_v1_1_private_score_v3` | `contract_version, benchmark_release_id, partition, automatic, point_metric, gate, score_input_binding, automatic_prediction_ref, selected_lifecycle_ref, estimand_ref, gate_ref, safety, content_sha256` |
| `private_scorer_child_public_ref_v1` | `contract_version, status, score_ref, private_score_file_sha256, score_input_binding, execution_receipt, safety, content_sha256` |
| `private_scorer_launch_receipt_v2` | `contract_version, launcher_process_id, launcher_process_identity, child_process_id, child_process_identity, pipe_capability_sha256, argv_sha256, env_sha256, cwd_sha256, job_identity_sha256, child_execution_receipt_sha256, child_score_ref, score_input_binding, safety, content_sha256` |
| `private_scorer_final_binding_v2` | `contract_version, child_score_ref, score_input_binding, launch_receipt_ref, cleanup_receipt_ref, safety, content_sha256` |
| `private_scorer_public_ref_v3` | `contract_version, status, score_ref, score_input_binding, binding, launch_receipt, cleanup_receipt, safety, content_sha256` |

Retain `private_scorer_child_receipt_v2` with its existing exact fields `contract_version, nonce, pipe_capability_sha256, launcher_process_id, launcher_process_identity, process_id, process_identity, job_identity_sha256, argv_sha256, env_sha256, cwd_sha256, safety`. Retain `private_scorer_cleanup_receipt_v1` and its existing envelope/ref formula unchanged.

For each of the five versioned objects above, `content_sha256 = sha256(canonical_json(object_without_content_sha256))`; the stored JSON file is pretty-canonical UTF-8 plus one newline and its file SHA is separate. The private score formula is `score_ref = "private-score/" + private_score.content_sha256`; the child public carries that score ref, its own excluding-self digest, and `private_score_file_sha256 = sha256(exact_private_score_file_bytes)`. `child_score_ref` is exactly `{status, score_ref, content_sha256}` projected from the child public.

The launch envelope is `{ref, canonical_bytes_b64}` with `ref={id:"private-scorer-launch/" + launch.content_sha256, content_sha256:launch.content_sha256}`. Final binding refs that launch envelope and the unchanged cleanup envelope. The final public formula is:

```text
binding.content_sha256 = sha256(canonical_json(binding without content_sha256))
public.score_ref = "private-score-final/" + binding.content_sha256
public.status = binding.child_score_ref.status
public.content_sha256 = sha256(canonical_json(public without content_sha256))
```

The final public stdout projection is exactly `{content_sha256: public.content_sha256, score_ref: public.score_ref, status: public.status}`. Validators recompute every self digest, file digest, envelope ref, and score-ref formula and require all propagated binding copies equal. Public/private leakage scans reject Gold fields, target IDs/labels/regions, reviewer/annotator data, absolute paths, private paths, raw inventory maps, and error text containing them.

### S3.2 Exact CLI and isolation

The scorer entrypoint supports exactly two mutually exclusive modes:

1. Public mode: `--private-manifest`, `--prediction-run-ref`, `--private-output`, `--public-ref-output`.
2. Hidden child mode: `--closed-launch-handle` only.

No provider, corpus, parent, Gold, project-root, lifecycle, authorization, or claim path flag is allowed. The accepted input embeds only its pathless v3 run/lifecycle projections. Production scorer validation rejects v2 run/lifecycle contracts; those remain direct synthetic-helper fixtures only. Public mode calls `run_private_scorer`; the hidden child alone receives private/accepted paths through the existing capability pipe.

Preserve the existing Windows Job membership, closed stdin, neutral empty CWD, minimal environment, private create-only output, pipe/handle closure, stable-zero cleanup, and redacted errors. Do not add a supervisor or alternate launch path. Both modes emit at most one canonical stdout line, with exactly three fields:

```json
{"content_sha256":"<final public content SHA>","score_ref":"<final public score ref>","status":"PASS"}
```

### S3.3 Allowed files, tests, and acceptance

**Allowed files:**

- Modify `app/learn/hybrid/benchmark_scorer_v2.py`.
- Modify `scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py`.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py`.

**RED tests:** exact four-flag Task 13 invocation against a Task 10-shaped fixture; missing/extra/mixed mode flags; separate lifecycle flag rejection; local raw/projection or inner-ref drift; v2 run/lifecycle production rejection; later-attempt substitution; exact input-binding fields; binding mutation at every propagated copy; public leakage; byte-remint propagation; synthetic production rejection; and existing Job/pipe/CWD/stdin/env/cleanup/redaction tests.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py
```

**GREEN acceptance:** the same command passes; the exact Task 13 four-flag command returns the exact three-field line; semantically equivalent accepted-input byte changes remint accepted, private score, and final public refs; all child resources and private/transient paths are stable zero after success and failure.

---

## S4. Holdout scoring contract before final seal

**Depends on:** S1-S3 and the Task 11/12 code contracts; runtime use additionally depends on an actual regression `PASS` and Task 11 authorization.
**Produces now:** holdout schema, validators, consumers, tests, and seal inventory only.
**Commit after GREEN:** `feat(benchmark-v2): freeze holdout scoring before final seal`

### S4.1 Separate accepted holdout authority

Add closed `benchmark_v2_accepted_holdout_score_input_v1`. It reuses the regression v2 envelope's release/provider refs, pathless four-field verified-parent container, v3 prediction-run envelope, v3 lifecycle-bundle envelope, safety, and self hash, but has literal `partition=holdout` and literal `selection_policy=unique_claim_bound_holdout_attempt`. The holdout materializer validates raw claim-bound attempt-ledger/body/result/journal files locally; its ledger/event refs use the distinct holdout contracts in S4.1.2, while journal/body/result entries remain pathless verified projections. It has four additional, required, non-null fields:

```text
regression_score_precondition_envelope
holdout_authority_evidence
holdout_authorization_ref
holdout_claim_ref
```

`regression_score_precondition_envelope` is exactly `{ref, canonical_bytes_b64}` containing a validated `private_scorer_public_ref_v3` regression `PASS`.

The materializer must first preserve and validate Task 11A's native authority types without normalizing them:

```text
native authorization ref = {authorization_id, envelope_sha256, fixed_authorization_path}
native claim ref         = {id, envelope_sha256}
```

`fixed_authorization_path` must equal the backend-derived fixed `{claim_root}\{claim_id}.authorization.json`, not merely point to a readable file. Read that private authorization object locally and verify its canonical two-layer `payload_sha256 -> envelope_sha256`, claim identity, authorization ID, provider/version/code/profile/arm/command/run order, owner-journal root, and exact external ref. Then use the existing durable-claim backend to verify, without repairing:

1. the sole sentinel is the exact `{claim_id}--{authorization envelope SHA}.claim`, is an ordinary zero-byte file, and has the required attributes/security;
2. the exact HKCU claim-ID key exists and its `ContractVersion`, `ClaimId`, `AuthorizationEnvelopeSha256`, canonical `ClaimEnvelope`, and external `ClaimEnvelopeSha256` reproduce the native claim ref;
3. the claim envelope's private payload matches authorization, derived attempt ID, provider manifest, absolute owner-journal root, and `state=consumed`;
4. the holdout ledger contains one matching genesis and one matching `claim_consumed`, with no other sentinel, key, claim, or attempt.

The complete authorization payload and registry claim envelope are private local validation inputs because their frozen contract intentionally contains absolute paths. Do **not** run the public-output path leak scanner against those input objects. This is a narrow input exemption only: never copy their paths or raw bytes into accepted input, score, stdout, report, logs, or errors, and do not exempt any field of a public artifact from leakage checks.

After local verification, emit only pathless projections under `holdout_authority_evidence`, exactly:

```text
authorization_public_projection_envelope
claim_public_projection_envelope
file_anchor_public_projection_envelope
registry_anchor_public_projection_envelope
```

Each is exactly `{ref, canonical_bytes_b64}` and uses the S1.1 identity rule. Their decoded contracts and exact fields are:

| Contract | Exact fields |
|---|---|
| `benchmark_v2_holdout_authorization_public_projection_v1` | `contract_version, artifact_id, authorization_id, envelope_sha256, claim_id, safety, content_sha256` |
| `benchmark_v2_holdout_claim_public_projection_v1` | `contract_version, artifact_id, claim_ref, claim_id, attempt_id, authorization_projection_ref, state, safety, content_sha256` |
| `benchmark_v2_holdout_file_anchor_public_projection_v1` | `contract_version, artifact_id, anchor_kind, claim_id, authorization_envelope_sha256, size_bytes, verified, safety, content_sha256` |
| `benchmark_v2_holdout_registry_anchor_public_projection_v1` | `contract_version, artifact_id, anchor_kind, claim_id, authorization_envelope_sha256, claim_ref, envelope_verified, state, safety, content_sha256` |

The literal values are `state=consumed`, `anchor_kind=win32_zero_byte_claim_sentinel`/`hkcu_claim_registry_envelope`, `size_bytes=0`, and both verification booleans `true`. The accepted input's `holdout_authorization_ref` is pathless exact `{authorization_id, envelope_sha256}` projected from the validated native ref; `holdout_claim_ref` remains native exact `{id, envelope_sha256}`. Both must equal every corresponding projected value. No public authority envelope contains `fixed_authorization_path`, registry root/key, sentinel path/name, owner-journal root, `ClaimEnvelope`, or raw authorization/claim payload. Regression v2 remains unchanged and has no nullable holdout fields.

There is no holdout first-complete rule. The only eligible attempt is the unique attempt derived from the exact Task 11A authorization and matching file/HKCU claim anchors in the stable release/corpus/partition namespace. The materializer requires: validated regression public v3 `PASS`; exact native authorization and claim refs; identical anchors; one consumed claim; one claim-bound attempt; terminal journal; stable-zero cleanup; no second attempt/claim. Anchor mismatch or missing authority fails permanently rather than selecting another attempt.

### S4.1.1 Verify-only Task 11A anchor API

Add a new public, read-only façade in `app/learn/hybrid/benchmark_v2_holdout.py`:

```python
verify_holdout_claim_anchors_for_public_projection(
    *, authorization_ref: Mapping[str, object], ledger_root: Path
) -> dict[str, object]
```

It validates the exact native external ref and fixed authorization object, then calls a new read-only validator in `app/learn/hybrid/benchmark_v2_durable_claim.py`. Its return is closed `benchmark_v2_holdout_anchor_verification_result_v1` with exact fields `contract_version, authorization_ref, claim_ref, attempt_id, authority_projection_envelopes, safety, content_sha256`; `authorization_ref` is the pathless two-field projection and `authority_projection_envelopes` is the exact four-envelope object in S4.1.

This API may open existing files/registry keys read-only and parse the existing holdout ledger, but it must not acquire/initialize/repair/mirror anything. In particular, it must never call `recover_claim`, `_recover_with_backend`, `_mirror_claim`, `claim_holdout_once`, genesis authorization, `_append_locked`, `_registry_create`, or `_sentinel_create`; the current recovery path can append a missing mirror and is therefore forbidden to materialization. Missing mirror/anchor evidence is a validation failure, not a repair opportunity.

Tests snapshot authorization/sentinel bytes and attributes, registry values, ledger bytes, and directory entries before and after the verify API and require exact equality. Monkeypatch every write/repair primitive above to raise and prove verification still succeeds. Failure tests also leave all snapshots byte-identical.

### S4.1.2 Fixed holdout raw-attempt chain

Do not add attempt states to Task 11A's existing `<ledger-root>/holdout/events.jsonl`; its exact `authorized_genesis -> claim_consumed` chain and contracts remain unchanged. The existing runner is the sole producer of a separate fixed file:

```text
<ledger-root>/holdout/attempt-events.jsonl
```

`app/learn/hybrid/benchmark_v2_holdout.py` owns the fixed-path resolver, closed validator, and event-kind-specific append functions. Authorizer, scorer, materializer, report assembler, durable-claim recovery, and generic callers cannot append. No `--attempt-ledger` flag is added: holdout runner derives this path only from required `--ledger-root`.

Required interfaces are `holdout_attempt_events_path(*, ledger_root)`, `validate_holdout_attempt_events(*, ledger_root, authorization_ref, claim_ref)`, and runner-only typed appenders `append_holdout_attempt_opened`, `append_holdout_attempt_body_complete`, `append_holdout_attempt_cleanup`, `append_holdout_attempt_result`, and `append_holdout_attempt_recovery_cleanup`. There is no generic public `append(event_kind, payload)` escape hatch.

Freeze these raw private contracts. All objects with `content_sha256` use excluding-self canonical JSON hashing; raw JSONL is compact-canonical UTF-8, one envelope plus newline per append.

| Contract | Exact fields / rule |
|---|---|
| `benchmark_v2_holdout_attempt_event_envelope_v1` | `contract_version,event,event_sha256`; inner event is exactly `partition,sequence,event_kind,previous_envelope_sha256,event_payload` |
| `benchmark_v2_holdout_attempt_ref_v1` | `contract_version,attempt_id,authorization_ref,claim_ref,partition,mode,provider_id,safety,content_sha256` |
| `benchmark_v2_holdout_attempt_opened_payload_v1` | `contract_version,attempt_ref,attempt_dir,status,safety,content_sha256` |
| `benchmark_v2_holdout_attempt_body_complete_payload_v1` | `contract_version,attempt_ref,attempt_dir,status,body_file_ref,safety,content_sha256` |
| `benchmark_v2_holdout_attempt_cleanup_payload_v1` | `contract_version,attempt_ref,attempt_dir,status,cleanup_receipt_ref,resource_counts,safety,content_sha256` |
| `benchmark_v2_holdout_attempt_result_payload_v1` | `contract_version,attempt_ref,attempt_dir,status,result_file_ref,attempt_ledger_pre_result_ref,safety,content_sha256` |
| `benchmark_v2_holdout_attempt_recovery_cleanup_payload_v1` | `contract_version,attempt_ref,attempt_dir,status,cleanup_receipt_ref,resource_counts,recovery_reason,safety,content_sha256` |
| `benchmark_v2_attempt_cleanup_receipt_v1` | existing exact `contract_version,attempt_ref,reason,service_terminal_ref,window_cleanup_ref,provider_cleanup_refs,resource_counts,cleanup_status,lost_response_policy,artifact_is_authorization,execute_binding_enabled,content_sha256`; attempt ref must be the holdout ref |
| `benchmark_v2_holdout_runner_actual_body_v1` | `contract_version,attempt_ref,partition,screen_group_results,body_status,safety,content_sha256` |
| `benchmark_v2_holdout_runner_actual_result_v1` | `contract_version,attempt_ref,attempt_dir,body_ref,cleanup_receipt_ref,attempt_ledger_pre_result_ref,screen_group_count,status,safety,content_sha256` |

`authorization_ref` is Task 11A's native exact three-field ref and `claim_ref` its native exact two-field ref. Freeze the output authority at code/seal time:

```text
AUTHORIZED_HOLDOUT_OUTPUT_ROOT_TOKEN = "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout"
AUTHORIZED_HOLDOUT_OUTPUT_ROOT = resolve_from_compile_time_ROOT(AUTHORIZED_HOLDOUT_OUTPUT_ROOT_TOKEN)
```

Task 11A's verified `EXACT_HOLDOUT_COMMAND` must contain exactly one `--output-root` token followed immediately by that exact token string. Parse the verified canonical token vector, not a rendered/split shell string. Missing, duplicate, empty, differently cased, alternate separator, dot segment, absolute-but-equivalent, environment-expanded, quoted-differently, or otherwise byte-different values fail closed even if the OS would resolve them to the same directory. The token must also resolve relative to compile-time repository `ROOT`, never CWD, to byte-identical `AUTHORIZED_HOLDOUT_OUTPUT_ROOT`.

For `--actual-models`, preserve the caller's raw `--output-root` argv token and require it to be byte-for-byte equal to the verified authorization token; then independently resolve it from compile-time `ROOT` and require the authorized root. Perform all command/root validation before holdout claim acquisition, attempt-directory creation, opened append, or provider dispatch.

Only after that validation derive:

```text
attempt_id = sha256(UTF8("benchmark-v2-holdout-attempt\0" + claim_id + "\0" + authorization_ref.envelope_sha256))
attempt_dir = resolve(AUTHORIZED_HOLDOUT_OUTPUT_ROOT/<attempt_id>)
mode = "actual_models"; provider_id = null; partition = "holdout"
```

The directory is the sole immediate ordinary child allowed for that claim-derived attempt; no UUID, suffix, retry directory, alias, symlink, or reparse point is permitted. Fixed files are `body.json` and `result.json` under it. Raw event `attempt_dir` is evidence to cross-check against this derivation, never authority.

`--cleanup-only` has no output-root flag. It must validate the fixed authorization object and `EXACT_HOLDOUT_COMMAND`, recover the unique authorized root from its exact token, derive the claim-bound attempt ID/directory, and only then compare any raw opened event. It cannot use the event's `attempt_dir`, a directory glob, CWD, a default, or filesystem discovery to choose a root. Missing/ambiguous/mismatched authorization command or alternate raw directory fails before cleanup append or resource operation.

The holdout materializer follows the same authorization-only recovery and accepts no output-root flag. It derives the unique root/attempt directory from the verified command, requires `--output` to resolve exactly `AUTHORIZED_HOLDOUT_OUTPUT_ROOT/run-ref.json`, and treats raw event/result paths only as equality assertions. It never discovers or accepts an alternate root.

Raw `body_file_ref`/`result_file_ref` are exact private `{path,file_sha256,content_sha256}` and their path must equal those fixed files; cleanup refs and result `body_ref`/`cleanup_receipt_ref` are exact `{content_sha256}`. Public projections remove `path` and retain only verified file/content hashes. The result event's file ref must resolve the exact result bytes whose inner body/cleanup refs equal the preceding body-complete/cleanup events.

`attempt_ledger_pre_result_ref` is holdout-specific closed `{contract_version,id,attempt_ref,terminal_sequence,terminal_envelope_sha256,prefix_sha256}`. For exact `attempt-events.jsonl` bytes `P` through the normal cleanup event, including its newline:

```text
contract_version = "benchmark_v2_holdout_attempt_ledger_pre_result_ref_v1"
id = "holdout-attempt-ledger-pre-result/" + sha256(UTF8("benchmark-v2-holdout-attempt-ledger-pre-result\0") || P)
attempt_ref = exact benchmark_v2_holdout_attempt_ref_v1 ref
terminal_sequence = cleanup sequence
terminal_envelope_sha256 = sha256(canonical_json(complete cleanup event envelope))
prefix_sha256 = sha256(P)
```

This raw pre-result ref and its embedded raw holdout attempt ref are private runtime data; the attempt may contain Task 11A's native three-field authorization ref including `fixed_authorization_path`. Neither object may appear in any public event, accepted input, v3 envelope, score, report, stdout, log, or error.

The fixed mutex identity is `Local\portfolio-hybrid-v1-1-benchmark-v2-holdout-attempt-` plus `sha256(UTF8(canonical absolute attempt-events path))`; production uses the existing protected mutex/security wrapper. The normal FSM is exact and indivisible:

```text
absent -> opened -> body_complete -> cleanup -> result
```

`event_kind` and payload `status` are identical literals. Sequence starts at zero, increases by one, and every event/attempt/directory/ref must match the unique claim. The runner appends `opened` under the fixed interprocess ledger mutex, flushes and `fsync`s, closes, reopens and validates the entire chain, and confirms the exact opened tail **before the first provider dispatch**. Every later transition repeats locked append, flush, `fsync`, reopen, and full validation. `event_sha256=sha256(canonical_json(inner event))`; `previous_envelope_sha256` hashes the complete previous envelope. Existing invalid/partial/noncanonical bytes cause permanent refusal for append, materialization, and scoring: never truncate, rewrite, skip, synthesize, mirror, or repair. That refusal must not suppress resource cleanup.

`--cleanup-only` first validates the native authorization/claim anchors, derives the claim-bound attempt ID and authorized root, and derives all resource identities from the verified authorization's owner-journal root plus the claim-bound owner/provider journals. It does not use `attempt-events.jsonl`, its `attempt_dir`, or its last parseable event as cleanup authority. It must reconcile/cancel the exact service operations, test HWNDs, Jobs/processes/descendants, listeners, model leases, and handles to the existing closed stable-zero resource-count map even when the attempt ledger is missing, truncated, half-written, noncanonical, or hash-invalid.

After stable zero, cleanup-only may inspect the attempt ledger only to choose evidence storage:

- If the entire chain is canonical and its legal tail is `opened` or `body_complete`, cleanup-only is the sole writer of one `event_kind=recovery_cleanup`; reinvocation validates the identical terminal event without appending.
- If the ledger cannot be fully validated/appended, leave every ledger byte unchanged and publish independent cleanup evidence at fixed `<ledger-root>/holdout/recovery-cleanup/<attempt_id>.json`. Create it with create-new, flush and `fsync`; if it already exists, require byte-identical canonical content. Never truncate, replace, append to, or use it to rehabilitate the attempt chain.

The detached file is closed `benchmark_v2_holdout_detached_recovery_cleanup_evidence_v1` with exact fields `contract_version,attempt_ref,authorization_ref,claim_ref,owner_journal_projection_refs,attempt_ledger_state,cleanup_receipt_ref,resource_counts,cleanup_status,selection_eligible,safety,content_sha256`. Its refs are pathless; `owner_journal_projection_refs` is a sorted nonempty list derived from locally validated owner journals; `attempt_ledger_state` is exactly one of `missing`, `partial`, `noncanonical`, or `hash_chain_invalid`; `cleanup_status=stable_zero`; every count is zero; `selection_eligible=false`.

For later independent cleanup review, project that file as `benchmark_v2_holdout_detached_recovery_cleanup_verified_projection_v1` with exact fields `contract_version,artifact_id,attempt_ref,authorization_ref,claim_ref,owner_journal_projection_refs,attempt_ledger_state,raw_evidence_file_sha256,raw_evidence_content_sha256,cleanup_receipt_ref,resource_counts,cleanup_status,selection_eligible,verified,safety,content_sha256` and S1.1 prefix `verified-holdout-detached-recovery-cleanup`. It is pathless and may appear only in cleanup/failure review evidence, never in an accepted holdout input or scoring v3 envelope.

Both normal `recovery_cleanup` and detached evidence are permanent terminal failure branches with `selection_eligible=false`; neither can transition to normal cleanup/result or become a score input. Normal `cleanup` is valid only after `body_complete`, and `result` only after normal cleanup. Failure to persist cleanup evidence after reconciliation is reported as a release blocker but does not undo or skip stable-zero cleanup.

Publish no raw holdout attempt bytes or paths. Add distinct pathless contracts using S1.1 hashes:

| Contract | Exact fields | Prefix |
|---|---|---|
| `benchmark_v2_holdout_runner_event_verified_projection_v1` | `contract_version,artifact_id,partition,event_kind,sequence,attempt_ref,authorization_ref,claim_ref,previous_event_projection_ref,raw_event_sha256,load_bearing_refs,safety,content_sha256` | `verified-holdout-runner-event` |
| `benchmark_v2_holdout_attempt_ledger_pre_result_verified_projection_v1` | `contract_version,artifact_id,partition,attempt_ref,authorization_ref,claim_ref,raw_pre_result_ref_sha256,raw_prefix_sha256,terminal_sequence,terminal_envelope_sha256,cleanup_event_projection_ref,verified,safety,content_sha256` | `verified-holdout-pre-result` |
| `benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1` | `contract_version,artifact_id,partition,authorization_ref,claim_ref,attempt_ref,raw_prefix_sha256,pre_result_verification_ref,terminal_sequence,terminal_event_projection_ref,event_projection_refs,selection_eligible,safety,content_sha256` | `verified-holdout-attempt-ledger-prefix` |
| `benchmark_v2_holdout_projected_attempt_ledger_v1` | `contract_version,artifact_id,benchmark_release_id,partition,authorization_ref,claim_ref,raw_ledger_prefix_verification_ref,pre_result_verification_ref,entries,selected_attempt_ref,selected_lifecycle_ref,safety,content_sha256` | `projected-holdout-attempt-ledger` |
| `benchmark_v2_holdout_actual_result_verified_projection_v1` | `contract_version,artifact_id,attempt_ref,result_contract_version,raw_file_sha256,result_content_sha256,body_projection_ref,cleanup_projection_ref,pre_result_verification_ref,runner_ledger_prefix_projection_ref,result_event_projection_ref,verified,safety,content_sha256` | `verified-holdout-actual-result` |

For raw closed pre-result object `R`, `raw_pre_result_ref_sha256=sha256(canonical_json(R))`; all other values are rederived from `R`, raw prefix `P`, the public attempt ref, pathless authorization/claim refs, and the projected cleanup event. The pre-result projection uses the S1.1 formula exactly:

```text
artifact_id = "verified-holdout-pre-result/" + sha256(
  UTF8("benchmark_v2_holdout_attempt_ledger_pre_result_verified_projection_v1\0") || canonical_json(semantic_payload)
)
content_sha256 = sha256(canonical_json(object_without_content_sha256))
public ref = {id: artifact_id, content_sha256: content_sha256}
envelope = {ref: public ref, canonical_bytes_b64: base64(canonical_json(complete projection))}
```

Public `authorization_ref` is always exact pathless `{authorization_id,envelope_sha256}`; public attempt ref is exactly `{id:"holdout-runner-attempt/" + attempt_id, content_sha256:raw_holdout_attempt_ref.content_sha256}`; claim ref is exact pathless `{id,envelope_sha256}`. A public runner event never references the raw pre-result ref: result `load_bearing_refs` is exactly `{result_file_ref,pre_result_verification_ref}` and resolves the projection envelope above. The holdout result projection, prefix projection, and projected ledger carry that same `pre_result_verification_ref`.

The prefix projection is eligible only for the exact normal four-event chain plus stable-zero lifecycle; recovery chains remain false. Both holdout v3 `sealed_artifact_envelopes` contain the byte-identical pre-result projection envelope, holdout result projection, projected ledger, prefix projection, and complete event set. `projected_attempt_ledger_ref` must resolve `benchmark_v2_holdout_projected_attempt_ledger_v1`; `raw_ledger_prefix_verification_ref` must resolve `benchmark_v2_holdout_attempt_ledger_prefix_verified_projection_v1`. Validators reject `fixed_authorization_path`, any native three-field authorization ref, raw pre-result object, alternate projection copy, regression projection contract, or native path anywhere in this public graph.

### S4.2 Holdout scorer binding and consumers

For holdout use `private_scorer_holdout_input_binding_v1`. Its exact field set is the S3 regression binding plus:

```text
regression_score_precondition_ref
holdout_authorization_ref
holdout_claim_ref
```

`regression_score_precondition_ref` is the exact `{contract_version:"private_scorer_public_ref_v3", file_sha256, content_sha256}` of the embedded regression score. `holdout_authorization_ref` is exact pathless `{authorization_id, envelope_sha256}` and `holdout_claim_ref` is exact native `{id, envelope_sha256}`; neither is coerced into `{id, content_sha256}`.

The same private score v3, launch v2, final binding v2, and public v3 envelopes carry this binding and apply identical propagation/leakage validation. The child derives exactly 12 holdout groups, five cases each, and 60 cases × four arms. The public scorer CLI remains the same four flags.

Update Task 11 authorizer validation and Task 12 report assembly to consume public v3 and the exact binding refs; neither may consume private score or derive Gold. The final report must compare release/provider/corpus/parent/estimand/gate refs across regression and holdout and additionally match the holdout regression-precondition, authorization, and claim refs. It remains non-authorizing.

### S4.3 Exact offline holdout materializer action

The same `--materialize-score-input` action supports holdout only with the exact extra authority inputs below. Add `--regression-score-ref`; holdout materialization rejects `--output-root`, `--attempt-ledger`, and body/result/journal path flags. It recovers the authorized root solely from verified `EXACT_HOLDOUT_COMMAND`; all materializer and actual/cleanup actions resolve fixed `holdout/attempt-events.jsonl` from `--ledger-root`.

```powershell
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --partition holdout --materialize-score-input --holdout-authorization runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json --regression-score-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json --ledger-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger --output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout/run-ref.json
```

This action is offline, launches no provider, does not create, recover, mirror, or repair anchors, and writes only create-new-or-byte-identical `run-ref.json`. The runner continues to own actual claim acquisition; the materializer calls only the verify-only API and embeds its pathless projections.

### S4.4 Allowed files, tests, seal gate, and acceptance

**Allowed files:**

- Modify `app/learn/hybrid/benchmark_v2_predictions.py`, `app/learn/hybrid/benchmark_v2_holdout.py`, `app/learn/hybrid/benchmark_v2_durable_claim.py`, `app/learn/hybrid/benchmark_scorer_v2.py`, and `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py`.
- Modify the exact inventory authority in `app/learn/hybrid/benchmark_v2_private_release.py`. Do not add an S4 inventory allowlist to `scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py`; after S2 that script only consumes the shared authority.
- Modify `scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py` and `scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py` only after the canonical Tasks 11 and 12 create them.
- Modify only `tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py`, `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py`, `tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py`, `tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py`, and the Task 11/12 files `tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py` and `tests/test_portfolio_hybrid_v1_1_release_gate_v2.py` after those files exist.

**RED tests:** regression accepted v2 rejects holdout fields; holdout requires all authority fields; regression public must be v3 `PASS`; native Task 11A ref shape/path drift; wrong two-layer authorization/claim hash; nonzero/reparse/wrong-name sentinel; registry value/envelope/ref drift; second attempt/claim; missing cleanup; anchor mismatch; verify-only API before/after snapshots; write/repair primitives forbidden; Task 11A genesis/claim ledger byte-identical before/after attempt activity; fixed attempt-ledger path and no `--attempt-ledger`; claim-derived ID/directory; reopened durable `opened` before first dispatch; exact normal FSM/hash chain; duplicate/reordered/partial event refusal; mutex/fsync/reopen evidence; cleanup-only unique `recovery_cleanup` and permanent ineligibility; provider started then half-written `body_complete` plus process kill; cleanup-only derives identities without ledger authority, reaches exact stable zero, preserves corrupt ledger bytes, writes create-only/byte-identical detached evidence, and scorer/materializer reject the run; missing/noncanonical/hash-invalid variants; detached evidence/projection field and path leakage tests; no ledger repair; exact public pre-result projection formula/ref/envelope and containment in both v3 envelopes; any public event carrying the raw pre-result ref or native three-field authorization ref; holdout-specific projection formulas and regression-contract rejection; projected/raw-verification ref separation in both v3 envelopes; accidental raw ledger/result/authorization/claim bytes or paths in public output; `EXACT_HOLDOUT_COMMAND` missing/duplicate/ambiguous output-root token; alternate case/separator/dot/absolute-equivalent root; actual CLI token mismatch rejected before claim/append/dispatch; cleanup-only/materializer authorization-only root recovery; raw event directory mismatch and directory discovery refusal; holdout materializer `--output-root` and alternate `--output` rejection; public input scanner narrowly permits the private authorization payload while every public scanner rejects its paths; v2 public rejection by authorizer/report; exact holdout materializer CLI; production materializer launch counters equal zero; and seal inventory includes every new/modified chain owner and test.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py tests/test_portfolio_hybrid_v1_1_release_gate_v2.py
```

If Tasks 11/12 have not created their two test files, implement those canonical tasks first; do not weaken this command or seal an incomplete inventory.

**GREEN acceptance:** the full command passes with test-owned file/registry roots only; the Task 11A genesis/claim chain remains unchanged; only runner typed appenders mutate the fixed attempt chain; recovery chains cannot materialize or score; a corrupt ledger remains byte-identical and permanently ineligible while cleanup-only still proves stable zero through detached evidence; no public projection contains a native authorization path/raw pre-result ref; actual, cleanup, and materializer converge on the one compile-time authorized root before side effects; the sealer's shared private-release inventory authority includes every S1-S4 implementation/test file (including runner, holdout, durable-claim, predictions, scorer, and focused tests), and any missing/drifted file prevents final seal. No real authorization, claim, anchor, model, window, service, process, or score artifact is produced by this slice.

---

## 2. Mandatory code/runtime separation

### Must exist now, before Task 13 final seal

- All S1-S4 contracts, pure validators/materializers, CLI parsing, scorer/authorizer/report consumers, closed public v3 validators, and focused RED/GREEN tests.
- The fixed holdout attempt-event path, typed runner-only appenders, closed FSM validator, recovery-cleanup ineligibility, and distinct holdout projection contracts must be code-complete before sealing; no runtime attempt-events file exists yet.
- Exact Task 10 inventory entries and hashes for the complete Task 11/12 plus S1-S4 code/test set.
- Deterministic projection/seal tests and independent review of provider/private boundary, first-complete replay, holdout one-claim rule, leakage, and cleanup assertions.
- No production private manifest is resealed until these files and tests are final. Any later code/config/test change remints the seal.

### Exist only after actual execution

- Regression runner ledger, attempt journal, body/result, probes, cleanup receipts, automatic prediction, lifecycle bundle, and `regression/accepted-run-ref.json`.
- Regression private score and public `regression/score-ref.json`, followed by leakage review and holdout authorization.
- Holdout authorization, file/HKCU claim anchors, unchanged Task 11A claim ledger, fixed `holdout/attempt-events.jsonl`, the unique claim-bound actual body/result/journal/cleanup, and `holdout/run-ref.json`.
- Holdout private/public score and final public report.

These runtime artifacts are never added to source commits or backfilled into the immutable Task 10 private manifest. A schema fixture is not a substitute for an actual materialized artifact, and an actual artifact is not permission to change sealed code.

### Runtime order after this amendment is implemented and final seal passes

1. **Task 13:** project/seal the three candidates, independently review their hash closure/private boundary, byte-copy the final fixtures, verify, and make only the canonical sealed-fixture commit.
2. **Task 13:** run the canonical dry-run, then the regression actual command once under the existing retry/review policy.
3. **Task 13:** run the real cancel probes and then timeout probes, each for Omni/Qwen/VISTA only after `request_in_flight`; run `--cleanup-open-attempts` and require stable zero.
4. **Task 13:** run the exact S1 regression materializer, then the four-flag regression scorer. Perform the independent regression review of four arms, 12 screens/60 cases, one Hybrid cascade per screen, six probes, first-complete selection, closed HWNDs, raw VRAM, and zero residue; write `task-10b-regression-review.md`.
5. **Task 14:** run leakage review and the native holdout authorizer; independently verify unique authorization, exact zero-claim genesis, and empty sentinel/registry namespace; write `task-10b-slice-14-review.md`.
6. **Task 15:** run the canonical unique holdout actual once. A crash consumes the claim; run only claim-bound cleanup if needed. Run the exact S4 holdout materializer, then independently review dual anchors, one claim/attempt, terminal/unknown requests, closed HWNDs, and stable zero; write `task-10b-holdout-review.md`.
7. **Task 16:** run the same four-flag scorer for holdout, assemble the public report, and perform the final no-Gold lifecycle/anchor/cleanup review; write `task-10b-final-review.md`.

This plan ends before step 1. S1-S4 may make only their four named per-slice code commits after the corresponding GREEN check; do not combine them, commit runtime/review artifacts, push, seal, run actual models, or create real claims/anchors while implementing this amendment.

---

## 3. Final verification and stop condition

After all four GREEN checkpoints, run only deterministic code checks:

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py tests/test_portfolio_hybrid_v1_1_release_gate_v2.py
uv run python -m py_compile app/learn/hybrid/benchmark_v2_actual.py app/learn/hybrid/benchmark_v2_predictions.py app/learn/hybrid/benchmark_v2_lifecycle.py app/learn/hybrid/benchmark_v2_private_release.py app/learn/hybrid/benchmark_scorer_v2.py app/learn/hybrid/benchmark_v2_holdout.py app/learn/hybrid/benchmark_v2_durable_claim.py scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py
git diff --check
```

Stop unless all exact contract fields, local-raw-to-pathless-projection lineage, first-complete replay, child-only Gold boundary, public v3 binding copies, holdout authority, leakage checks, and stable-zero tests pass. Cleanup test-owned paths and registry keys, record zero live resources, and stop before Task 13 final seal and all actual-model commands.
