# Qwen2.5 Semantic Binding Replacement Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that Qwen2.5-VL-7B can replace Qwen3 as an independently sealed `semantic_binding` provider and reach the existing reviewed-learning path without changing frozen Hybrid v1.1 or Benchmark v2.

**Architecture:** Reuse the provider capability/bundle contracts from the companion plan and the existing llama.cpp OpenAI-compatible transport. Add only a Qwen2.5 renderer/native parser, an explicit model profile and bundle descriptor, and a three-screen read-only provider smoke. The phase stops after smoke; the frozen Benchmark v2 runner cannot legally score the new bundle.

**Tech Stack:** Python 3.11, llama.cpp `llama-server.exe`, GGUF Q4_K_M model plus Q8_0 mmproj, existing model-server lease/cleanup path, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-provider-capability-contracts-design.md`

## Global Constraints

- Tasks 1–8 of `docs/superpowers/plans/2026-09-03-provider-capability-contracts-implementation-plan.md` must be complete and green first.
- Qwen2.5 is a new bundle; it never overwrites Qwen3 files, identity, profile, results, or scores.
- Reuse the canonical Semantic Binding PromptSpec, neutral result, and existing `hybrid_qwen_bindings_v1` compatibility projection.
- Provider-specific renderer/parser/config may change only under the new Qwen2.5 bundle revision.
- Do not modify `configs/learn_hybrid_v1_1.json`, `load_hybrid_config`, `app/learn/hybrid/benchmark_v2_*.py`, any Benchmark v2 manifest/fixture, Gold, corpus, scorer, estimand, Gate, accepted attempt, or holdout code/data.
- Do not run `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py` for Qwen2.5.
- Do not add a candidate-regression runner in this plan.
- Before any real model start, notify the user and receive explicit approval for that run.
- Real smoke is read-only: no Desktop I/O dispatch and no action API.
- Any schema, lineage, cleanup, listener, process, or lease ambiguity fails closed; do not fall back to Qwen3.
- Each independently verified code/config slice receives one atomic commit; never auto-push.

## Verified Local Artifact Inputs

The already downloaded source artifacts are located through the operator-local, uncommitted environment variable `AGENT_GUI_MODEL_CACHE_ROOT`. Only filenames, sizes, and hashes belong in repository documentation:

```text
Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf
size: 4,683,072,032 bytes
sha256: 9258bf05b12686d097ff3b6b18d968ab393649780aa2b3cd67fec43d50554392

mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf
size: 853,119,712 bytes
sha256: 2ddb555391bae966e412deab9e07b58afa18bcc06930ba0f1c78a3695ab9e506
```

The implementation verifies these values before deployment. A mismatch is a stop condition, not a reason to update the expected hash.

## File Structure

- Create: `app/learn/hybrid/qwen2_5_semantic_binding.py` — Qwen2.5 renderer, strict native parser, and `SemanticBindingProvider` implementation.
- Create: `tests/test_qwen2_5_semantic_binding_bundle.py` — no-model contract and projection tests.
- Create: `configs/model_profiles/qwen2_5_vl_7b_q4_k_m.json` — explicit llama.cpp profile on port 13246.
- Create: `configs/provider_bundles/qwen2-5-semantic-binding-v1.json` — exact sealed bundle descriptor after artifacts are present.
- Create: `configs/provider_bundles/provider-candidate-qwen2-5-v1.json` — new candidate selection; the compatibility config remains unchanged.
- Create: `scripts/run_semantic_binding_provider_smoke.py` — three-case read-only smoke with durable non-authorizing evidence and stable-zero cleanup checks.
- Create: `tests/test_semantic_binding_provider_smoke.py` — fake transport/lifecycle and CLI regression.
- Create: `tests/fixtures/provider_capabilities/qwen2_5_vl_7b/complex-smoke-v1.json` — three exact public regression case refs selected without holdout access.
- Modify after proof: `CURRENT_STATE.md` and `NEXT_STEPS.md`; modify `README.md` only if public usage/status changes.

---

### Task 9: Qwen2.5 Renderer, Native Parser, and Bundle Adapter

**Files:**
- Create: `app/learn/hybrid/qwen2_5_semantic_binding.py`
- Create: `tests/test_qwen2_5_semantic_binding_bundle.py`

**Interfaces:**
- Consumes: `SemanticBindingRequestV1`, `SemanticBindingResultV1`, `SemanticBindingItemV1`, and `project_semantic_result_to_hybrid_qwen_v1` from the completed compatibility phase.
- Produces: `render_qwen2_5_semantic_binding_request(request)`, `parse_qwen2_5_semantic_binding_response(raw, request)`, `validate_exact_model_lease(value, expected_profile_id)`, and `Qwen2_5SemanticBindingProvider.invoke(request)`.

- [ ] **Step 1: Write RED no-model protocol tests**

Freeze the provider-native wire contract to exactly:

```json
{
  "bindings": [
    {
      "candidate_id": "candidate/example",
      "role": "button",
      "label": "Quick apply",
      "binding_status": "BOUND",
      "confidence": 0.94
    }
  ]
}
```

Tests must prove:

```python
def test_qwen2_5_parser_covers_exact_candidates_and_projects_to_legacy_v1():
    request = semantic_request_fixture(candidate_count=3)
    raw = qwen2_5_wire_fixture(request)
    result = parse_qwen2_5_semantic_binding_response(raw, request)
    assert tuple(item.candidate_id for item in result.bindings) == request.ordered_candidate_ids
    legacy = project_semantic_result_to_hybrid_qwen_v1(
        result=result,
        inventory=request.omni_inventory,
        context_ref=request.context_ref,
    )
    assert legacy["contract_version"] == "hybrid_qwen_bindings_v1"
    assert legacy["approved_to_click"] is False
```

Parameterize duplicate, unknown, omitted, reordered, and cross-capture candidates; nested authority/geometry fields; invalid JSON; prose before/after JSON; NaN/infinite/out-of-range confidence; oversize bytes/string/items; whitespace-only label/role; bundle-ref mismatch; timeout; and pre/mid/post cancellation. Use a fake callable transport and set:

```powershell
$env:AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER='1'
```

Assert the fake adapter never calls a real model wrapper.

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
uv run pytest tests/test_qwen2_5_semantic_binding_bundle.py -q
```

Expected: import failure because the Qwen2.5 provider module does not exist.

- [ ] **Step 3: Implement the compact provider**

Use these signatures:

```python
def render_qwen2_5_semantic_binding_request(
    request: SemanticBindingRequestV1,
) -> dict[str, object]:
    """渲染 Qwen2.5 消息；只允许对已有 candidate_id 分类和命名。"""


def parse_qwen2_5_semantic_binding_response(
    raw: str | Mapping[str, object],
    request: SemanticBindingRequestV1,
) -> SemanticBindingResultV1:
    """严格解析短 JSON，不接受 prose、几何或权限字段。"""


def validate_exact_model_lease(
    value: object,
    *,
    expected_profile_id: str,
) -> dict[str, object]:
    """验证 active managed lease 与 bundle profile 完全一致。"""


class Qwen2_5SemanticBindingProvider:
    capability = "semantic_binding"

    def __init__(
        self,
        *,
        bundle_descriptor: dict[str, object],
        transport: Callable[..., object],
    ) -> None:
        self.bundle_descriptor = validate_provider_bundle_descriptor_v1(bundle_descriptor)
        self.bundle_ref = provider_bundle_ref(self.bundle_descriptor)
        self._transport = transport

    def invoke(self, request: SemanticBindingRequestV1) -> SemanticBindingResultV1:
        if request.envelope.bundle_ref != self.bundle_ref:
            raise UEIValidationError("provider_bundle_mismatch")
        lease = validate_exact_model_lease(
            request.envelope.resource_lease,
            expected_profile_id=str(self.bundle_descriptor["profile_id"]),
        )
        native_request = render_qwen2_5_semantic_binding_request(request)
        raw = self._transport(
            request=native_request,
            screenshot_bytes=request.screenshot_bytes,
            screenshot_media_type=request.screenshot_media_type,
            screenshot_sha256=request.screenshot_sha256,
            cancellation_event=request.envelope.cancellation_event,
            model_lease=lease,
            timeout_seconds=request.envelope.budget.timeout_ms / 1000.0,
        )
        return parse_qwen2_5_semantic_binding_response(raw, request)
```

The canonical prompt requires one short record per candidate and forbids reasoning/explanation fields. It must not ask Qwen2.5 to discover new boxes or choose an action. `validate_exact_model_lease` rejects missing leases, wrong profile IDs, stale/malformed process incarnation, and descriptor/lease mismatch before the transport call; the adapter never permits `run_qwen_binding_model` to use its default Qwen3 fallback.

- [ ] **Step 4: Run GREEN protocol and compatibility tests**

```powershell
uv run pytest tests/test_qwen2_5_semantic_binding_bundle.py tests/test_learn_hybrid_qwen_binding.py tests/test_learn_hybrid_provider_capability_adapters.py -q
uv run python -m py_compile app/learn/hybrid/qwen2_5_semantic_binding.py
Remove-Item Env:AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER
```

Expected: all tests and compilation pass; no listener/process is created.

- [ ] **Step 5: Commit Task 9**

```powershell
git add -- app/learn/hybrid/qwen2_5_semantic_binding.py tests/test_qwen2_5_semantic_binding_bundle.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat(provider): add Qwen2.5 semantic binding adapter"
```

---

### Task 10: Exact Profile, Artifact Deployment, and Bundle Registration

**Files:**
- Create: `configs/model_profiles/qwen2_5_vl_7b_q4_k_m.json`
- Create: `configs/provider_bundles/qwen2-5-semantic-binding-v1.json`
- Create: `configs/provider_bundles/provider-candidate-qwen2-5-v1.json`
- Create: `tests/test_qwen2_5_model_profile.py`
- Modify: `tests/test_qwen2_5_semantic_binding_bundle.py`

**Interfaces:**
- Consumes: existing `scripts/model_servers/start_llama_vision_server.ps1`, `scripts/model_servers/stop_local_vision_server.ps1`, explicit-profile model-server lookup, and Task 1 bundle sealer/registry.
- Produces: explicit profile `qwen2_5_vl_7b_q4_k_m` and sealed bundle `bundle/local.qwen2-5.semantic-binding`.

- [ ] **Step 1: Verify and deploy model artifacts without starting them**

Run:

```powershell
$sourceRoot = [Environment]::GetEnvironmentVariable('AGENT_GUI_MODEL_CACHE_ROOT')
if ([string]::IsNullOrWhiteSpace($sourceRoot)) { throw 'AGENT_GUI_MODEL_CACHE_ROOT is required' }
Get-FileHash -Algorithm SHA256 (Join-Path $sourceRoot 'Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf')
Get-FileHash -Algorithm SHA256 (Join-Path $sourceRoot 'mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf')
```

Expected hashes are the two values in **Verified Local Artifact Inputs**. After checking available disk space, copy only those two files to ignored runtime path:

```text
models/qwen2.5-vl-7b-instruct-q4_k_m-gguf/
```

Recompute SHA-256 and byte sizes at the destination. If space is insufficient, stop and report; do not add an absolute personal path to a committed profile.

- [ ] **Step 2: Write RED profile and bundle tests**

The profile must have these exact operational fields:

```json
{
  "profile_id": "qwen2_5_vl_7b_q4_k_m",
  "exclusive_resource_group": "gpu_vision",
  "label": "Qwen2.5-VL 7B Q4_K_M semantic binding candidate",
  "role": ["understanding", "learning", "deep_understanding"],
  "provider_mode": "local_understanding",
  "input_format": "openai_compatible_vision",
  "model_name": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
  "model_path": "models/qwen2.5-vl-7b-instruct-q4_k_m-gguf/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
  "mmproj_path": "models/qwen2.5-vl-7b-instruct-q4_k_m-gguf/mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf",
  "server_path": "tools/llama.cpp-b8892-cuda13/llama-server.exe",
  "endpoint": "http://127.0.0.1:13246/v1/chat/completions",
  "start_script": "scripts/model_servers/start_llama_vision_server.ps1",
  "stop_script": "scripts/model_servers/stop_local_vision_server.ps1",
  "pid_file": "logs/qwen2.5-vl-7b-q4_k_m-server.pid",
  "port": 13246,
  "context_size": 8192,
  "gpu_layers": 99,
  "gpu_memory_gib": 7,
  "image_min_tokens": 1024,
  "launchable": true
}
```

The committed JSON may include the existing descriptive profile fields, but these operational values cannot differ. Tests verify explicit profile lookup, model/mmproj/server existence and hashes, one `gpu_vision` group, localhost endpoint, and no modification to `STAGE_PROFILE_IDS`.

Bundle tests verify the descriptor binds the exact model/mmproj/runtime/profile/renderer/parser/adapter hashes. Compared with `provider-candidate-config-v1.json`, the new candidate config must change only its `config_id`, self-hash, `semantic_binding` ref, and the corresponding Qwen descriptor path; discovery and grounding refs plus descriptor paths remain byte-identical.

- [ ] **Step 3: Run tests and confirm RED**

```powershell
$env:AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER='1'
uv run pytest tests/test_qwen2_5_model_profile.py tests/test_qwen2_5_semantic_binding_bundle.py tests/test_learn_hybrid_provider_bundle_config.py -q
```

Expected: missing profile/descriptor failures and zero model starts.

- [ ] **Step 4: Create the profile and seal the bundle from real file hashes**

Create the profile without changing `STAGE_PROFILE_IDS`. Build the bundle descriptor with `seal_provider_bundle_descriptor_v1`; write it using `canonical_json_bytes(descriptor) + b"\n"`. Create `provider-candidate-qwen2-5-v1.json` by copying the validated compatibility config, replacing the `semantic_binding` ref with `provider_bundle_ref(descriptor)`, replacing `configs/provider_bundles/qwen3-semantic-binding-compat-v1.json` with `configs/provider_bundles/qwen2-5-semantic-binding-v1.json`, assigning a new `config_id`, and resealing it. Never type a hash manually and never modify `provider-candidate-config-v1.json`.

- [ ] **Step 5: Run GREEN no-model registration tests**

```powershell
uv run pytest tests/test_qwen2_5_model_profile.py tests/test_qwen2_5_semantic_binding_bundle.py tests/test_learn_hybrid_provider_bundle_config.py tests/test_learn_recognition_model_profiles.py -q
uv run python -c "from app.core.model_server import profile_for_stage; p=profile_for_stage('understanding','qwen2_5_vl_7b_q4_k_m'); assert p['profile_id']=='qwen2_5_vl_7b_q4_k_m'"
Remove-Item Env:AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER
git diff --name-only
```

Expected: tests pass; no Benchmark v2, frozen Hybrid v1.1, compatibility candidate config, `STAGE_PROFILE_IDS`, or model binary appears in the diff.

- [ ] **Step 6: Commit Task 10**

```powershell
git add -- configs/model_profiles/qwen2_5_vl_7b_q4_k_m.json configs/provider_bundles/qwen2-5-semantic-binding-v1.json configs/provider_bundles/provider-candidate-qwen2-5-v1.json tests/test_qwen2_5_model_profile.py tests/test_qwen2_5_semantic_binding_bundle.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat(provider): register Qwen2.5 semantic bundle"
```

---

### Task 11: Three-Screen Read-Only Provider Smoke

**Files:**
- Create: `scripts/run_semantic_binding_provider_smoke.py`
- Create: `tests/test_semantic_binding_provider_smoke.py`
- Create: `tests/fixtures/provider_capabilities/qwen2_5_vl_7b/complex-smoke-v1.json`
- Modify after a completed run: `CURRENT_STATE.md`
- Modify after a completed run: `NEXT_STEPS.md`
- Modify after a completed run only if public usage changes: `README.md`

**Interfaces:**
- Consumes: exact candidate bundle registry/config, Qwen2.5 adapter, existing model lease and cleanup APIs, and three public regression captures with sealed Omni inventories.
- Produces: sealed, display-only, non-authorizing smoke results under `runtime_state/provider-capability-candidates/qwen2_5_vl_7b/complex-smoke-v1`.

**Current gate:** This task is blocked before file creation because this clean worktree contains no portable, independently verified refs for the three previously failing public regression screens. Tasks 9–10 may proceed, but Task 11 must stop until an audited input packet supplies three exact public/non-holdout capture and inventory refs. Do not infer them from the 120-case combined provider corpus and do not read Benchmark v2 private/holdout partition data to manufacture the packet.

- [ ] **Step 1: Validate the externally supplied three-case public input packet**

Require a packet that names its public regression source root and contains exactly three entries with:

- `screen_group_id` and `case_id`;
- capture artifact relative path, capture ref, screenshot SHA-256, and image size;
- sealed Omni inventory relative path/ref/hash and ordered candidate IDs;
- source regression attempt ref/hash proving the entry belongs to regression, not holdout;
- selection-rank integer and selection reason from the frozen ordering `schema/protocol failure count DESC`, then `omni_to_qwen wrong-target count DESC`, then candidate count `DESC`, with `case_id ASC` as the tie-break.

Validate every file/ref/hash against that named source root and reject any entry whose regression membership cannot be proven without reading Gold or holdout. Persist only these references and protocol invariants into `complex-smoke-v1.json`. If the packet is absent or any reference is unresolved, stop before creating the fixture, runner, or tests and report `waiting_exact_public_smoke_refs`.

- [ ] **Step 2: Write RED CLI/lifecycle tests using fake transport**

Tests cover:

```python
def test_smoke_runs_exact_three_cases_and_writes_sealed_non_authorizing_results(tmp_path):
    result = run_smoke(
        project_root=PROJECT_ROOT,
        manifest_path=fixture_manifest_path(),
        output_root=tmp_path,
        transport=FakeSemanticTransport(),
        actual_model=False,
    )
    assert result["case_count"] == 3
    assert result["all_contract_valid"] is True
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
```

Also test duplicate/missing case, cross-capture ref, bundle mismatch, model timeout, invalid JSON, partial candidate coverage, cancellation, lost response, cleanup failure, non-zero listener/process/lease residue, output-root escape, and refusal to accept any path/token containing `holdout`.

- [ ] **Step 3: Run tests and confirm RED**

```powershell
$env:AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER='1'
uv run pytest tests/test_semantic_binding_provider_smoke.py tests/test_qwen2_5_semantic_binding_bundle.py -q
```

Expected: missing smoke runner failure; no model starts.

- [ ] **Step 4: Implement the runner and fake-path GREEN tests**

Use:

```python
def run_smoke(
    *,
    project_root: Path,
    manifest_path: Path,
    output_root: Path,
    transport: Callable[..., object] | None = None,
    actual_model: bool = False,
) -> dict[str, object]:
    """运行三个只读 semantic-binding cases，并证明 terminal cleanup。"""
```

The CLI accepts exactly `--bundle-ref`, `--manifest`, `--output-root`, and `--actual-model`. Without `--actual-model`, real model startup is impossible. With it, each of the three cases acquires its own explicit-profile lease, places that exact lease into its `ProviderInvocationEnvelopeV1`, passes the matching one-shot `release_managed_qwen_model_lease` owner to the coordinator, invokes once, and releases before the next case. This intentionally pays three startup costs to keep lease ownership unambiguous. Every success/failure artifact carries its own structured terminal cleanup receipt. The runner writes UTF-8/JCS sealed request/result/receipt objects and verifies stable-zero residue before overall success.

Run:

```powershell
uv run pytest tests/test_semantic_binding_provider_smoke.py tests/test_qwen2_5_semantic_binding_bundle.py tests/test_qwen2_5_model_profile.py -q
uv run python -m py_compile scripts/run_semantic_binding_provider_smoke.py
Remove-Item Env:AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER
```

Expected: all fake-path tests pass and launch count remains zero.

- [ ] **Step 5: Commit the runner before any real model execution**

```powershell
git add -- scripts/run_semantic_binding_provider_smoke.py tests/test_semantic_binding_provider_smoke.py tests/fixtures/provider_capabilities/qwen2_5_vl_7b/complex-smoke-v1.json
git diff --cached --check
git diff --cached --stat
git commit -m "test(provider): add Qwen2.5 semantic smoke"
```

- [ ] **Step 6: Stop and obtain explicit user permission to start Qwen2.5**

Report current memory/VRAM availability, verify ports 13240/13244/13246 have no conflicting listener, verify provider/model/lease residue is zero, and ask the user to free GPU/RAM. Do not run the model until the user replies with approval.

- [ ] **Step 7: Run the exact real smoke command**

After approval:

```powershell
uv run python scripts/run_semantic_binding_provider_smoke.py --bundle-ref configs/provider_bundles/qwen2-5-semantic-binding-v1.json --manifest tests/fixtures/provider_capabilities/qwen2_5_vl_7b/complex-smoke-v1.json --output-root runtime_state/provider-capability-candidates/qwen2_5_vl_7b/complex-smoke-v1 --actual-model
```

Success requires all three cases to have exact capture/bundle/candidate order and coverage, valid `hybrid_qwen_bindings_v1` projection, no authority/geometry output, recorded latency and schema status, exactly one structured terminal cleanup receipt for each of the three independently acquired leases, and stable-zero model/provider/window/listener/lease residue.

Any model-quality failure is recorded honestly. Any lineage, runner, cleanup, or residue failure stops the run as invalid infrastructure evidence. Do not change prompt/config after observing results under the same bundle identity.

- [ ] **Step 8: Independently review evidence and update status docs**

Independent review must validate exact bundle ref, three-case manifest, raw UTF-8 response, parsed result, legacy projection, cleanup receipts, and stable-zero proof. Then update status docs with one of:

- `Candidate smoke PASS — replacement remains Partial pending separately approved 12/60 candidate evaluation.`
- `Candidate smoke FAIL — retain Qwen3 baseline and record exact protocol/quality failure.`
- `Smoke INVALID — infrastructure or cleanup evidence failed; no model comparison conclusion.`

Commit only documentation, not ignored runtime evidence:

```powershell
git add -- CURRENT_STATE.md NEXT_STEPS.md README.md
git diff --cached --check
git diff --cached --stat
git commit -m "docs(provider): record Qwen2.5 smoke result"
```

If `README.md` did not change, omit it from `git add`.

## Mandatory Stop Gate After Smoke

Stop after reporting the three-screen result. The frozen Benchmark v2 runner is release-pinned to the existing Qwen revision and rejects a new bundle identity. Running or modifying it would invalidate the comparison boundary.

To obtain a full 12-screen/60-target comparison later, the user must separately approve a design for an isolated bundle-neutral candidate regression runner. That future runner must write explicitly non-Benchmark-v2 candidate evidence and must not inherit Benchmark v2 scores, thresholds, Gate decisions, accepted attempts, or holdout authority.
