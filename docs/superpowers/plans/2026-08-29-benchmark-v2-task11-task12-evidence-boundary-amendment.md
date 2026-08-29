# Benchmark v2 Task 11/12 Evidence-Boundary Amendment

**Goal:** Close the public-validation, leakage-review, and dependency-evidence contracts that block Tasks 11 and 12 before S4, without redesigning the existing B1 supervision/cleanup machinery.

**Authority and supersession:** This amendment is subordinate to `2026-08-26-portfolio-hybrid-v1-1-benchmark-v2-plan.md` and `2026-08-28-benchmark-v2-scoring-bridge-prerequisite-amendment.md`. It supersedes those documents **only** where their Task 11/12 public evidence boundary, leakage-review shape, dependency-evidence shape, or ordering conflicts with this document. `2026-08-29-benchmark-v2-probe-authority-bridge-amendment.md` authoritatively supersedes this document's conflicting Task 11 probe/profile clauses, Task 11/12 probe inputs, authorization version, and DAG placement. All unrelated canonical plan text, S1-S4 contracts, Task 11A durable-claim rules, B1 infrastructure, estimand, gates, safety rules, and actual-run rules remain authoritative.

---

## 1. Frozen order and stop boundary

The only authorized implementation order is:

```text
S3
  -> public boundary
  -> P0 genuine probe evidence
  -> P1 public probe authority
  -> Task 11
  -> Task 12
  -> S4
  -> deterministic integration
  -> STOP before actual models
```

Task 13 may later perform the no-model pre-final-seal work needed to mint fresh dependency result/review receipts, build the release dependency manifest, update the final seal, and only then proceed to actual models. This amendment and its implementation slices do not run a provider or model, acquire a GPU, open or control a GUI, create a real authorization/claim/anchor, seal production fixtures, or make an empirical claim that Hybrid was selected or is superior.

S4 remains one logical prerequisite in this order; its S4a/S4b subdivision in the scoring-bridge amendment does not move either part ahead of Tasks 11/12.

---

## 2. Public-safe score boundary

### 2.1 One stdlib-only authority

Create `app/learn/hybrid/benchmark_v2_public_score.py`. It must use only the Python standard library and must own:

- the closed public v3 scorer validator;
- the public recursive leakage scanner;
- public score/ref/hash helpers needed by Tasks 11 and 12.

`app/learn/hybrid/benchmark_scorer_v2.py` remains the producer and keeps a compatibility alias to the validator exported by the new module. The implementation direction is one-way: scorer may import public boundary; public boundary must never import scorer.

Task 11 and Task 12 production scripts and tests must never import:

- `app.learn.hybrid.benchmark_scorer_v2`;
- `app.learn.hybrid.benchmark_v2_private_release`;
- a sealer-private helper;
- Gold, a Gold validator, a private manifest parser, or a private-score payload.

The public validator may accept the already-frozen, pathless `private_manifest_ref` carried by public v3, but only in its exact closed public shape. It never resolves that ref, reads the private manifest, or derives Gold.

The Task 11 authorizer may read the exact `--private-manifest` bytes once only as an opaque byte string, compute their file SHA-256, and compare that digest with the already validated public v3 binding. It must not JSON-parse those bytes, import a private validator, resolve a private path from them, or expose them to the leakage review/report boundary.

### 2.2 Bounded recursive scan

The scanner walks mappings, lists, keys, string values, and decoded public envelopes with these exact limits:

```text
maximum JSON/container depth       = 32
maximum visited nodes              = 100000
maximum UTF-8 bytes in one string  = 16777216
maximum nested base64 decode depth = 8
maximum decoded bytes in one scan  = 67108864
```

Every field named `canonical_bytes_b64` or ending in `_bytes_b64` is decoded with strict RFC 4648 base64 validation. Decoded bytes must be UTF-8. If they parse as JSON, scanning recurses into the parsed value; otherwise the decoded UTF-8 text is scanned as text. Invalid base64/UTF-8, trailing JSON data, or any bound exhaustion is a leakage failure, never a skipped subtree. Hash-valid outer bytes do not excuse an unscanned inner payload.

The forbidden field-name set is exactly:

```text
acceptable_regions
annotator_identity_hash
gold
gold_path
private_manifest_path
private_output
reviewer_identity_hash
target_id
```

The forbidden case-insensitive text fragments are exactly:

```text
gold.v1.json
corpus-manifest.v1.json
benchmark_v2_privileged_projector.py
```

Any drive-qualified path, UNC path, URI/file path, rooted POSIX path, backslash path, `.`/`..` segment, percent-decoded path alias, or value under a `path`/`*_path` key is forbidden. There are only these logical-path exceptions:

1. `provider_manifest_ref.relative_path == "benchmark-v2-provider-manifest.json"`;
2. `provider_corpus_ref.relative_path == "provider-corpus.v2.json"`;
3. while scanning the already validated provider manifest, the exact `relative_path` values in its validated `sealed_runtime.code_refs`, `sealed_runtime.release_code_refs`, and `sealed_runtime.profile_refs`;
4. while scanning the already validated provider corpus, each exact `cases[*].image.path` value derived internally from that snapshot, and only at that schema location. Every such value must already have passed the provider-corpus validator's exact normalized relative POSIX pattern `^tests/fixtures/portfolio_hybrid_v1_1/corpus/(regression|holdout)/case-[0-9]{3}\.png$`, including exact partition agreement, case, and `/` separators.

Exceptions 3 and 4 are derived internally from their validated snapshots; neither is a caller-supplied allowlist. Exception 4 is not a general exemption for `path`/`*_path`: the same image string at any other location, any corpus-unlisted image, or any case/separator/dot/parent/absolute/URI alias remains a path finding. Every exception must be a normalized relative POSIX path and must still reject absolute, parent, dot, backslash, URI, drive, case-alias, or separator-alias forms. No logical-path exception makes the referenced bytes provider release code or authorizes execution.

---

## 3. Task 11 leakage review

### 3.1 Closed artifact

`benchmark_v2_leakage_review_v1` has exactly these fields, in semantic contract order:

```text
contract_version
benchmark_release_id
provider_manifest_ref
provider_corpus_ref
accepted_run_ref
finding_codes
status
safety
content_sha256
```

The three refs are copied from validated public inputs and retain their already-frozen exact closed shapes. `safety` is exactly:

```json
{"artifact_is_authorization":false,"execute_binding_enabled":false,"display_only":true}
```

`finding_codes` is a sorted unique list drawn only from this exact enumeration:

```text
ABSOLUTE_PATH
FORBIDDEN_FIELD_NAME
FORBIDDEN_LOGICAL_PATH
FORBIDDEN_TEXT_FRAGMENT
INVALID_BASE64_PAYLOAD
SCAN_BOUND_EXCEEDED
```

`status` is `PASS` iff `finding_codes == []`; otherwise it is `FAIL`. Unknown codes, duplicates, non-lexicographic order, a PASS with findings, or a FAIL without findings are invalid. Structural invalidity, ref/hash drift, release mismatch, or noncanonical input is a hard validation error and must not be converted into a PASS review.

Let `J(x)` be compact canonical UTF-8 JSON with sorted keys, no insignificant whitespace, and `ensure_ascii=False`. The excluding-self hash is exactly:

```text
content_sha256 = sha256(J(review_without_content_sha256))
```

The file bytes are the full object serialized as sorted-key, two-space-indented UTF-8 JSON plus exactly one trailing LF. The output is create-new-or-byte-identical: never truncate, replace, or reinterpret an existing different file.

On successful creation/identical replay, stdout is exactly one compact-canonical line with exactly three top-level fields:

```json
{"content_sha256":"<review content_sha256>","review_ref":{"contract_version":"benchmark_v2_leakage_review_v1","file_sha256":"<sha256 exact pretty-LF file bytes>","content_sha256":"<review content_sha256>"},"status":"PASS|FAIL"}
```

No path is printed. Errors go to stderr and produce no success object.

### 3.2 Profile binding

**Superseded for provider probe profiles:** `2026-08-29-benchmark-v2-probe-authority-bridge-amendment.md` replaces the provider-profile interpretation below. `sealed_runtime.profile_refs` remains release configuration authority only. Task 11 must derive Omni/Qwen/VISTA `profile_sha256_by_id` while independently rebuilding the public probe projection from production receipt-v2 and dispatch/runtime-attestation lineage; the bundle itself adds no profile map. The following legacy map must not authorize provider profiles.

After the shared provider-manifest validator succeeds, Task 11 computes the authorization profile map exactly as:

```python
profile_sha256_by_id = {
    profile_ref["role"]: profile_ref["file_sha256"]
    for profile_ref in validated_provider_manifest["sealed_runtime"]["profile_refs"]
}
```

Canonical JSON sorting determines map order. Neither `relative_path`, list position, a caller-provided ID, nor a release-code role may become a profile ID. Duplicate roles, missing roles, an extra map entry, or any SHA mismatch fails before authorization publication.

---

## 4. Task 12 dependency evidence

### 4.1 Opt-in pytest plugin, not an executor

`scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py` may expose pytest hooks only when explicitly loaded as a plugin and given both a frozen suite ID and an output receipt path. It records the current pytest session; it must not launch pytest, a supervisor, service, provider, helper process, or subprocess. It must not import the agent runtime or use process supervision as evidence.

For equality, `pytest_argv` means the semantic vector `['pytest', *pytest_arguments]` after removing only the plugin transport options (`-p`, plugin name, suite-id option, and receipt-output option). There is no shell normalization, glob expansion, path resolution, option reordering, selector rewriting, or `uv` inference. It must equal the frozen vector byte-for-byte.

The frozen suite IDs and semantic argv vectors are:

| Suite ID | Exact `pytest_argv` |
|---|---|
| `task05_worker_binding_v1` | `["pytest","-q","tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py","tests/test_learning_workflow_stage_worker.py","-k","vision_observe_screen or benchmark_v2 or incumbent"]` |
| `task06a_completed_result_identity_v1` | `["pytest","-q","tests/test_learning_workflow_stage_worker.py","-k","completed_result_identity or adopt_result or read_adopted_result"]` |
| `task06b1_outer_worker_supervision_v1` | `["pytest","-q","tests/test_learn_hybrid_windows_process_scope.py","tests/test_learning_workflow_stage_worker.py","-k","benchmark_worker or exact_process_identity_to_scope or handler_payload_source or payload_projection or managed_qwen_mode"]` |
| `task06b2_qwen_cleanup_sidecar_v1` | `["pytest","-q","tests/test_model_request_cancellation.py","tests/test_learning_workflow_stage_worker.py","-k","qwen_cleanup_sidecar or benchmark_provider_cleanup"]` |
| `task06c_incumbent_cut_point_v1` | `["pytest","-q","tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py","tests/test_learning_workflow_stage_worker.py","tests/test_model_request_cancellation.py","tests/test_learning_workflow_stage_execution.py","-k","benchmark_v2 or incumbent or hybrid or qwen or payload_projection or managed_qwen_mode"]` |
| `task12_release_gate_v1` | `["pytest","-q","tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py","tests/test_learning_workflow_stage_worker.py","tests/test_learn_hybrid_windows_process_scope.py","tests/test_model_request_cancellation.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py","tests/test_learning_workflow_stage_execution.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py","tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py","tests/test_portfolio_hybrid_v1_1_release_gate_v2.py"]` |

The first five suite IDs are the dependency DAG. `task12_release_gate_v1` is the non-circular Task 12 acceptance result consumed by the Task 12 reviewer; it does not replace any of the first five receipts.

### 4.2 Result and review receipt contracts

`benchmark_v2_dependency_result_receipt_v1` has exactly:

```text
contract_version
suite_id
pytest_argv
source_snapshot_sha256
exit_code
collected_count
failed_count
status
safety
content_sha256
```

Immediately before pytest collection and again after session finish, the plugin hashes the exact ordinary files in the production/test path sets frozen in §4.3 and constructs:

```text
source_snapshot = {
  "production_source_sha256_by_path": <exact eight-key map>,
  "test_source_sha256_by_path": <exact six-key map>
}
source_snapshot_sha256 = sha256(J(source_snapshot))
```

The receipt stores the pre-session digest in its single closed `source_snapshot_sha256` field. `status=PASS` iff the argv is exact, both complete pre/post maps validate, their canonical snapshot digests are equal, `exit_code==0`, `collected_count>0`, and `failed_count==0`; otherwise `FAIL`. Missing files, aliases, symlinks/reparse points, read/hash errors, pre/post drift, a malformed digest, or map-key drift cannot produce PASS. The plugin always preserves the observed exit/count fields and may not remint a failing or source-drifted session as PASS.

`benchmark_v2_dependency_review_receipt_v1` has exactly:

```text
contract_version
suite_id
result_receipt_ref
review_name
review_file_sha256
reviewer_identity_sha256
reviewer_independent
unresolved_findings
status
safety
content_sha256
```

`unresolved_findings` is exactly `{critical,important}` with nonnegative canonical integers. `status=PASS` iff the referenced result is PASS, `reviewer_independent=true`, and both counts are zero. `review_name` is one exact basename from this table:

| Suite ID | `review_name` |
|---|---|
| `task05_worker_binding_v1` | `task-10b-slice-5-review.md` |
| `task06a_completed_result_identity_v1` | `task-10b-slice-6-prerequisite-a-review.md` |
| `task06b1_outer_worker_supervision_v1` | `task-10b-slice-6-prerequisite-b1-review.md` |
| `task06b2_qwen_cleanup_sidecar_v1` | `task-10b-slice-6-prerequisite-b2-review.md` |
| `task06c_incumbent_cut_point_v1` | `task-10b-slice-6-review.md` |
| `task12_release_gate_v1` | `task-10b-slice-12-review.md` |

For both receipt types, `content_sha256=sha256(J(object_without_content_sha256))`; file bytes are sorted-key, two-space-indented UTF-8 JSON plus one LF. A receipt ref is exactly `{contract_version,file_sha256,content_sha256}`, with `file_sha256` over those exact file bytes. Writes are create-new-or-byte-identical.

### 4.3 Closed dependency manifest and build mode

`benchmark_v2_release_dependency_manifest_v1` has exactly:

```text
contract_version
benchmark_release_id
build_mode
dependency_order
result_receipt_refs
review_receipt_refs
production_sha256_by_path
test_sha256_by_path
safety
content_sha256
```

`dependency_order` is exactly the pre-Task-12 dependency DAG:

```json
["task05_worker_binding_v1","task06a_completed_result_identity_v1","task06b1_outer_worker_supervision_v1","task06b2_qwen_cleanup_sidecar_v1","task06c_incumbent_cut_point_v1"]
```

Both receipt-ref maps have exactly those five keys. Every result/review is PASS, every review binds the same-key result receipt, and the order cannot be inferred from map iteration. `task12_release_gate_v1` and `task-10b-slice-12-review.md` remain required Task 12 acceptance evidence, but are deliberately outside the dependency manifest so that the manifest does not depend on its own validator/reviewer.

`production_sha256_by_path` has exactly these eight keys:

```text
app/learn/hybrid/benchmark_v2_worker_binding.py
app/learn/workflow_worker.py
app/learn/hybrid/windows_process_scope.py
app/core/model_server.py
app/learn/hybrid/benchmark_v2_provider_corpus.py
app/learn/hybrid/benchmark_v2_incumbent_operation.py
app/learn/workflow_service.py
app/api/panel.py
```

`test_sha256_by_path` has exactly these six keys:

```text
tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py
tests/test_learning_workflow_stage_worker.py
tests/test_learn_hybrid_windows_process_scope.py
tests/test_model_request_cancellation.py
tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py
tests/test_learning_workflow_stage_execution.py
```

Every value is the SHA-256 of the exact current ordinary file bytes. The builder recomputes `sha256(J({"production_source_sha256_by_path":production_sha256_by_path,"test_source_sha256_by_path":test_sha256_by_path}))` and requires it to equal `source_snapshot_sha256` in every one of the five dependency result receipts. The real final seal independently recomputes the same maps/digest and must match the manifest, all five dependency receipts, and the separately reviewed `task12_release_gate_v1` receipt. Missing paths, aliases, symlinks/reparse points, map drift, receipt-snapshot drift, or seal mismatch fails closed.

`build_mode` is exactly `release`. The script's explicit `--build-dependency-manifest` mode is an offline validator/assembler only: it reads the five dependency result receipts, five dependency review receipts, and current files, then writes one create-new-or-byte-identical manifest. It never runs a suite or review. Pure tests may call an injected test-only builder with literal `build_mode=synthetic_test`; a production builder, final report, or final seal must reject `synthetic_test`. The Task 11 authorizer does not accept a dependency manifest; it remains independently fail-closed on its fresh score/leakage/lifecycle/probe inputs.

The manifest uses the same excluding-self compact hash, pretty-LF file bytes, and exact `{contract_version,file_sha256,content_sha256}` ref formula as the receipts. Final report assembly gains a required `--dependency-manifest`; absence, non-release mode, stale SHA, non-PASS receipt/review, wrong argv, wrong DAG, or ref drift fails before report output.

The existing B1 supervisor, service, cleanup, and receipt infrastructure is evidence consumed by these suites; Task 12 does not redesign or launch it. Resistance to a local administrator who can replace all source, receipts, reviews, anchors, and seals remains out of scope and must be stated as a limitation.

---

## 5. Current evidence is not reusable

Historical Task 5/A/B1/B2/C result evidence and review prose is stale, failing, or absent relative to the current source hashes and the machine-readable contracts above. It cannot be wrapped, copied, renamed, or treated as current PASS evidence.

Therefore, at the end of Tasks 11/12/S4 implementation:

- real dependency-manifest build fails closed;
- real report assembly fails closed;
- real authorization still fails closed on its missing fresh score/leakage/lifecycle/probe inputs;
- tests use only temporary synthetic receipts/reviews and never write canonical runtime paths;
- fresh real suite receipts and independent reviews are Task 13 pre-final-seal work, before any actual-model invocation.

No synthetic fixture, historical Markdown review, future command, or claimed expected PASS substitutes for a fresh receipt bound to exact current argv and bytes.

---

## 6. Exact implementation slices

### Public boundary

**Allowed files only:**

- Create `app/learn/hybrid/benchmark_v2_public_score.py`.
- Modify `app/learn/hybrid/benchmark_scorer_v2.py` only to consume/re-export the public validator.
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py`.

**RED:**

The scanner tests must accept the exact internally derived validated `cases[*].image.path` values and reject the same value outside that schema location, an unlisted image, uppercase/lowercase drift, `\` separators, dot/parent segments, partition mismatch, or any caller-provided path allowlist.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py -k "public_score_boundary or public_score_scanner"
```

**GREEN:**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py -k "public_score_boundary or public_score_scanner"
uv run python -m py_compile app/learn/hybrid/benchmark_v2_public_score.py app/learn/hybrid/benchmark_scorer_v2.py
git diff --check
```

**Commit:** `refactor(benchmark-v2): isolate public score validation`

### Task 11

**Probe-authority correction:** The exact P0, P1, Task 11 allowlists/tests/commits and required `--probe-authority` input are frozen by `2026-08-29-benchmark-v2-probe-authority-bridge-amendment.md`. Where they conflict with this subsection, the probe-authority amendment controls; the leakage-review clauses here remain authoritative.

**Allowed files only:**

- Create `scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py`.
- Create `scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py`.
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py`.

The authorizer consumes Task 11A's existing verify-only durable-claim API; it does not modify Task 11A or B1 infrastructure.

**RED:**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py
```

**GREEN:**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py
uv run python -m py_compile scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py
git diff --check
```

**Commit:** `feat(benchmark-v2): validate leakage before authorization`

### Task 12

**Probe-authority correction:** Task 12 must also bind the exact pathless `regression_probe_authority_ref` as frozen by `2026-08-29-benchmark-v2-probe-authority-bridge-amendment.md`. Its dependency result/review and dependency-manifest v1 clauses below remain unchanged.

**Allowed files only:**

- Create `scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py`.
- Create `tests/test_portfolio_hybrid_v1_1_release_gate_v2.py`.

**RED:**

Tests must reject a missing/extra/malformed `source_snapshot_sha256`, any pre/post source or test byte drift even when pytest otherwise passes, a result receipt whose snapshot differs from the current dependency maps, a dependency manifest that mixes receipt snapshots, and a final-seal/current-source snapshot mismatch. Temporary synthetic tests must exercise both stable PASS and drifted FAIL without writing canonical evidence.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_release_gate_v2.py
```

**GREEN:** run the exact `task12_release_gate_v1` argv frozen in §4.1 through the opt-in receipt plugin, then:

```powershell
uv run python -m py_compile scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py
git diff --check
```

**Commit:** `feat(benchmark-v2): assemble dependency-bound public report`

### S4 and deterministic integration

S4 uses the exact S4.4 allowlist and GREEN command in the 2026-08-28 scoring-bridge amendment. Only in S4 may the shared private-release inventory be updated to add:

```text
app/learn/hybrid/benchmark_v2_public_score.py
scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py
scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py
scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py
tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py
tests/test_portfolio_hybrid_v1_1_release_gate_v2.py
```

Do not add inventory placeholders before S4. These entries are private final-seal code/test inventory only; none is a provider-manifest `release_code_refs` entry. The provider runtime must not import them.

Each slice is one single-purpose commit. No slice may modify provider/model configuration, add a model, run a provider/GPU/GUI, produce a result claim, create an authorization/claim/file/HKCU anchor, reseal fixtures, change an estimand/gate/threshold, or write runtime evidence. After S4, run the deterministic integration command already frozen by the scoring-bridge amendment and stop before Task 13 actual models.
