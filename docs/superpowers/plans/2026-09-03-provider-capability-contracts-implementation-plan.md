# Provider Capability Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make discovery, semantic binding, and grounding refinement independently replaceable behind sealed, non-authorizing provider contracts while preserving every frozen Hybrid v1.1 artifact and behavior.

**Architecture:** Add two focused internal modules: one for sealed provider-bundle identity and explicit resolution, and one for transient capability requests/results. Current OmniParser, Qwen, and VISTA entrypoints become compatibility projections through those neutral forms; existing UEI and Hybrid v1 artifacts remain the only persisted outputs. A separate candidate configuration selects exact bundle refs and never changes `learn_hybrid_v1_1.json` or its loader.

**Tech Stack:** Python 3.11, dataclasses, `typing.Protocol`, RFC 8785/JCS helpers in `app.learn.recognition.uei.canonical`, pytest, existing UEI/Hybrid validators.

**Spec:** `docs/superpowers/specs/2026-09-03-provider-capability-contracts-design.md`

## Global Constraints

- The public boundary remains Canonical UEI; all new capability shapes are transient and internal.
- Provider output is evidence only and cannot grant execution authority.
- Preserve `configs/learn_hybrid_v1_1.json`, `load_hybrid_config`, Benchmark v2 Gold/corpus/scorer/estimand/Gate, accepted attempts, historical receipts, and historical hashes byte-for-byte.
- Do not rename or rewrite `hybrid_qwen_*`, `hybrid_vista_*`, OmniParser, or Benchmark v2 persisted artifacts.
- Do not add automatic routing, fallback, a fourth capability, or a general process supervisor.
- Slices 1–3 use deterministic fakes only and must not start a model process.
- Every implementation task uses RED → GREEN focused TDD, one single-purpose commit, explicit staging, and no push.
- Before each commit, run `git diff --cached --check` and inspect `git diff --cached --stat` plus the complete cached diff.
- Do not stage pre-existing or unrelated dirty files.

## File Structure

### New modules

- `app/learn/recognition/uei/provider_bundles.py` — closed `ProviderBundleDescriptorV1`, canonical sealing/ref validation, exact capability-aware registry.
- `app/learn/recognition/uei/provider_capabilities.py` — transient invocation envelope, three request/result types and Protocols, budget intersection, recursive non-authority validation, deterministic neutral source IDs.
- `app/learn/hybrid/provider_capability_adapters.py` — compatibility adapters and legacy projections for OmniParser, Qwen, and VISTA.
- `app/learn/hybrid/provider_bundle_config.py` — closed loader for the separate candidate bundle configuration.

### New configuration

- `configs/provider_bundles/omniparser-discovery-compat-v1.json`
- `configs/provider_bundles/qwen3-semantic-binding-compat-v1.json`
- `configs/provider_bundles/vista-grounding-refinement-compat-v1.json`
- `configs/provider_bundles/provider-candidate-config-v1.json`

### New tests

- `tests/test_uei_v1_provider_bundles.py`
- `tests/test_uei_v1_provider_capabilities.py`
- `tests/test_learn_hybrid_provider_capability_adapters.py`
- `tests/test_learn_hybrid_provider_bundle_config.py`

### Existing files changed only where compatibility composition requires it

- `app/learn/hybrid/qwen_binding.py` — split compact/native normalization from unchanged v1 projection; keep public entrypoints.
- `app/learn/hybrid/vista_refinement.py` — split provider-result normalization from unchanged v1 projection; keep public entrypoints.
- `app/learn/recognition/uei/__init__.py` and `app/learn/hybrid/__init__.py` — export only stable internal symbols needed by callers.
- `README.md`, `PROJECT_SUMMARY.md`, `ARCHITECTURE.md`, `CURRENT_STATE.md`, `NEXT_STEPS.md` — record the implemented boundary and honest status after code verification.

---

### Task 1: Sealed Provider Bundle Identity

**Files:**
- Create: `app/learn/recognition/uei/provider_bundles.py`
- Create: `tests/test_uei_v1_provider_bundles.py`

**Interfaces:**
- Consumes: `canonical_json_bytes`, `content_sha256`, `immutable_ref`, and `seal_immutable` from `app.learn.recognition.uei.canonical`; `ProviderRunBudget` from `app.learn.recognition.uei.provider_adapters`.
- Produces: `PROVIDER_CAPABILITIES`, `validate_provider_bundle_descriptor_v1(value)`, `seal_provider_bundle_descriptor_v1(value)`, `provider_bundle_ref(value)`, `ResolvedProviderBundle`, and `TrustedProviderBundleRegistry.resolve(capability, bundle_ref)`.

- [ ] **Step 1: Write the failing descriptor and registry tests**

Create tests that construct this exact unsealed descriptor shape:

```python
def descriptor_fixture(*, capability: str = "semantic_binding") -> dict[str, object]:
    return {
        "contract_version": "provider_bundle_descriptor_v1",
        "bundle_id": "bundle/local.qwen3.semantic-binding",
        "bundle_revision": "compat-v1",
        "capability": capability,
        "provider_id": "provider/local.qwen3",
        "profile_id": "profile/local.qwen3-vl-8b",
        "model_id": "Qwen3-VL-8B-Instruct",
        "model_revision": "q4-k-m",
        "prompt_spec_sha256": "1" * 64,
        "prompt_renderer_sha256": "2" * 64,
        "native_parser_sha256": "3" * 64,
        "adapter_sha256": "4" * 64,
        "preprocessing_sha256": "5" * 64,
        "transport_sha256": "6" * 64,
        "coordinate_convention": "capture_pixel_xyxy",
        "decoding_config_sha256": "7" * 64,
        "artifact_sha256s": ["8" * 64, "9" * 64],
        "resource_budget": {
            "timeout_ms": 30_000,
            "max_output_bytes": 65_536,
            "max_element_count": 256,
            "max_string_length": 4_096,
            "resource_group": "gpu_vision",
        },
    }
```

Cover:

```python
def test_bundle_descriptor_is_closed_jcs_sealed_and_ref_resolves():
    sealed = seal_provider_bundle_descriptor_v1(descriptor_fixture())
    assert sealed["content_sha256"] == content_sha256(sealed)
    assert provider_bundle_ref(sealed) == {
        "id": sealed["bundle_id"],
        "content_sha256": sealed["content_sha256"],
    }


@pytest.mark.parametrize("field", [
    "prompt_spec_sha256", "native_parser_sha256", "adapter_sha256",
    "coordinate_convention", "decoding_config_sha256",
])
def test_each_load_bearing_mutation_changes_or_invalidates_bundle_identity(field):
    sealed = seal_provider_bundle_descriptor_v1(descriptor_fixture())
    mutated = deepcopy(sealed)
    mutated[field] = "f" * 64 if field.endswith("sha256") else "image_normalized_xyxy"
    with pytest.raises(UEIValidationError):
        validate_provider_bundle_descriptor_v1(mutated)


def test_registry_rejects_duplicate_key_and_wrong_capability_or_ref():
    sealed = seal_provider_bundle_descriptor_v1(descriptor_fixture())
    adapter = object()
    with pytest.raises(UEIValidationError, match="duplicate"):
        TrustedProviderBundleRegistry([(sealed, adapter), (sealed, adapter)])
    registry = TrustedProviderBundleRegistry([(sealed, adapter)])
    with pytest.raises(UEIValidationError, match="capability"):
        registry.resolve(
            capability="candidate_discovery",
            bundle_ref=provider_bundle_ref(sealed),
        )
    bad_ref = {**provider_bundle_ref(sealed), "content_sha256": "0" * 64}
    with pytest.raises(UEIValidationError, match="bundle"):
        registry.resolve(capability="semantic_binding", bundle_ref=bad_ref)
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
uv run pytest tests/test_uei_v1_provider_bundles.py -q
```

Expected: collection/import failure because `provider_bundles.py` does not exist.

- [ ] **Step 3: Implement the closed descriptor and exact registry**

Use these public signatures:

```python
PROVIDER_CAPABILITIES = frozenset({
    "candidate_discovery",
    "semantic_binding",
    "grounding_refinement",
})


def validate_provider_bundle_descriptor_v1(value: object) -> dict[str, object]:
    """返回闭合、已封存且可机器验证的 Provider Bundle。"""


def seal_provider_bundle_descriptor_v1(value: object) -> dict[str, object]:
    """验证未封存描述符并使用 JCS content hash 封存。"""


def provider_bundle_ref(value: object) -> dict[str, str]:
    """只返回 bundle_id 与已验证 content_sha256。"""


@dataclass(frozen=True)
class ResolvedProviderBundle:
    descriptor: dict[str, object]
    adapter: object


class TrustedProviderBundleRegistry:
    def __init__(self, entries: list[tuple[dict[str, object], object]]) -> None:
        self._entries: dict[tuple[str, str], ResolvedProviderBundle] = {}

    def resolve(
        self, *, capability: str, bundle_ref: dict[str, str]
    ) -> ResolvedProviderBundle:
        key = (capability, bundle_ref["id"])
        resolved = self._entries.get(key)
        if resolved is None or provider_bundle_ref(resolved.descriptor) != bundle_ref:
            raise UEIValidationError("provider_bundle_unresolved")
        return resolved
```

Validation must use an exact key set, lowercase 64-character SHA-256 strings, unique sorted `artifact_sha256s`, a capability from `PROVIDER_CAPABILITIES`, the existing `ProviderRunBudget` constructor for `resource_budget`, and `content_sha256` for self-hash verification.

- [ ] **Step 4: Run focused GREEN tests**

Run:

```powershell
uv run pytest tests/test_uei_v1_provider_bundles.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- app/learn/recognition/uei/provider_bundles.py tests/test_uei_v1_provider_bundles.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat(provider): seal capability bundle identity"
```

---

### Task 2: Transient Capability Requests and Results

**Files:**
- Create: `app/learn/recognition/uei/provider_capabilities.py`
- Create: `tests/test_uei_v1_provider_capabilities.py`

**Interfaces:**
- Consumes: `ProviderRunBudget`, `RestrictedCaptureLease`, `provider_bundle_ref`, and sealed descriptor validation from Task 1.
- Produces: `ProviderInvocationEnvelopeV1`, `CandidateDiscoveryRequestV1`, `CandidateDiscoveryResultV1`, `SemanticBindingRequestV1`, `SemanticBindingResultV1`, `GroundingRefinementRequestV1`, `GroundingRefinementResultV1`, the three provider Protocols, `effective_provider_budget`, `deterministic_neutral_source_item_id`, and `reject_authority_shaped_payload`.

- [ ] **Step 1: Write RED tests for the common envelope and evidence-only result boundary**

Use the exact authority-key set:

```python
AUTHORITY_SHAPED_KEYS = frozenset({
    "approved_to_click", "execute", "final_submit", "send", "confirm", "payment",
})
```

Write tests for nested dict/list injection in every result:

```python
@pytest.mark.parametrize("factory", [
    discovery_result_fixture,
    semantic_result_fixture,
    grounding_result_fixture,
])
@pytest.mark.parametrize("key", sorted(AUTHORITY_SHAPED_KEYS))
def test_capability_results_recursively_reject_authority_shaped_keys(factory, key):
    value = factory()
    value["provider_payload"] = {"nested": [{key: True}]}
    with pytest.raises(UEIValidationError, match="non_authorizing"):
        reject_authority_shaped_payload(value)
```

Also cover:

```python
def test_budget_intersection_uses_the_strictest_limit_and_exact_resource_group():
    caller = ProviderRunBudget(30_000, 65_536, 256, 4_096, "gpu_vision")
    bundle = ProviderRunBudget(20_000, 32_768, 128, 2_048, "gpu_vision")
    assert effective_provider_budget(caller, bundle) == ProviderRunBudget(
        20_000, 32_768, 128, 2_048, "gpu_vision"
    )


def test_budget_intersection_rejects_resource_group_mismatch():
    with pytest.raises(UEIValidationError, match="resource_group"):
        effective_provider_budget(
            ProviderRunBudget(30_000, 65_536, 256, 4_096, "gpu_vision"),
            ProviderRunBudget(30_000, 65_536, 256, 4_096, "cpu_vision"),
        )


def test_neutral_source_id_is_stable_but_changes_on_bundle_item_or_fingerprint():
    first = deterministic_neutral_source_item_id(
        bundle_ref={"id": "bundle/local.omni", "content_sha256": "1" * 64},
        source_index=3,
        native_fingerprint="2" * 64,
    )
    assert first == deterministic_neutral_source_item_id(
        bundle_ref={"id": "bundle/local.omni", "content_sha256": "1" * 64},
        source_index=3,
        native_fingerprint="2" * 64,
    )
    assert first != deterministic_neutral_source_item_id(
        bundle_ref={"id": "bundle/local.omni", "content_sha256": "1" * 64},
        source_index=4,
        native_fingerprint="2" * 64,
    )
```

Add closed-world tests for missing, duplicate, unknown, and reordered semantic candidate IDs; strict-interior tests for all four edges and four corners; open non-empty role strings such as `"site-specific-quick-apply-control"` must remain valid.

- [ ] **Step 2: Run the tests and confirm RED**

```powershell
uv run pytest tests/test_uei_v1_provider_capabilities.py -q
```

Expected: import failure because the capability module does not exist.

- [ ] **Step 3: Implement the transient types and validators**

Use frozen dataclasses with these fields:

```python
@dataclass(frozen=True)
class ProviderInvocationEnvelopeV1:
    bundle_ref: dict[str, str]
    capability: str
    invocation_id: str
    capture_lineage_ref: dict[str, str]
    budget: ProviderRunBudget
    resource_lease: dict[str, object] | None = None
    cancellation_event: Event | None = None


@dataclass(frozen=True)
class CandidateDiscoveryRequestV1:
    envelope: ProviderInvocationEnvelopeV1
    capture: RestrictedCaptureLease


@dataclass(frozen=True)
class CandidateDiscoveryItemV1:
    source_item_id: str
    kind: str
    source_bbox: tuple[int, int, int, int] | None
    source_coordinate_space: str
    safe_text: str | None = None
    safe_role: str | None = None
    safe_states: tuple[str, ...] = ()
    confidence: float | None = None


@dataclass(frozen=True)
class CandidateDiscoveryResultV1:
    bundle_ref: dict[str, str]
    invocation_id: str
    capture_lineage_ref: dict[str, str]
    items: tuple[CandidateDiscoveryItemV1, ...]
    duration_ms: int
    resource_units: int


@dataclass(frozen=True)
class SemanticBindingRequestV1:
    envelope: ProviderInvocationEnvelopeV1
    ordered_candidate_ids: tuple[str, ...]
    capture_bundle: dict[str, object]
    omni_inventory: dict[str, object]
    context_ref: dict[str, str]
    screenshot_bytes: bytes
    screenshot_media_type: str
    screenshot_sha256: str


@dataclass(frozen=True)
class SemanticBindingItemV1:
    candidate_id: str
    role: str
    label: str
    binding_status: str
    confidence: float


@dataclass(frozen=True)
class SemanticBindingResultV1:
    bundle_ref: dict[str, str]
    invocation_id: str
    capture_lineage_ref: dict[str, str]
    bindings: tuple[SemanticBindingItemV1, ...]
    duration_ms: int
    resource_units: int


@dataclass(frozen=True)
class GroundingRefinementRequestV1:
    envelope: ProviderInvocationEnvelopeV1
    candidate_id: str
    candidate_bbox: tuple[int, int, int, int]
    permitted_roi: tuple[int, int, int, int]
    provider_request: dict[str, object]


@dataclass(frozen=True)
class GroundingRefinementResultV1:
    bundle_ref: dict[str, str]
    invocation_id: str
    capture_lineage_ref: dict[str, str]
    candidate_id: str
    status: str
    point: tuple[float, float] | None
    coordinate_space: str
    confidence: float | None
    evidence_refs: tuple[dict[str, str], ...]
    duration_ms: int
    resource_units: int
```

Each Protocol exposes `bundle_ref` and one typed `invoke(request)` method. Dataclass `__post_init__` methods enforce exact capability/ref/lineage, bounded values, closed-world candidate order, and strict interior `x1 < x < x2` plus `y1 < y < y2`. `resource_lease` is required before dispatch for bundles whose transport requires a managed model/resource; its exact `profile_id` and incarnation are checked by the provider adapter against the sealed descriptor. Raw native payload is deliberately absent from these result dataclasses.

- [ ] **Step 4: Run focused GREEN tests**

```powershell
uv run pytest tests/test_uei_v1_provider_capabilities.py tests/test_uei_v1_provider_bundles.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- app/learn/recognition/uei/provider_capabilities.py tests/test_uei_v1_provider_capabilities.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat(provider): add neutral perception capability contracts"
```

---

### Task 3: Deterministic Invocation Envelope Conformance

**Files:**
- Modify: `app/learn/recognition/uei/provider_capabilities.py`
- Modify: `tests/test_uei_v1_provider_capabilities.py`

**Interfaces:**
- Consumes: Task 2 envelope and Protocols.
- Produces: `invoke_with_capability_envelope(request, adapter, cleanup)`, `CapabilityInvocationFailure`, `CapabilityCleanupOutcomeV1`, and `CapabilityInvocationOutcome[TResult]`. Success and failure both retain the validated terminal cleanup receipt.

- [ ] **Step 1: Write RED tests with a deterministic fake adapter**

Use a fake that records `acquire`, `invoke`, `cleanup`, and `return` transitions. Add these cases:

```python
@pytest.mark.parametrize("cancel_stage", ["before_acquire", "during_invoke", "before_promote"])
def test_cancellation_fails_closed_and_cleanup_is_exactly_once(cancel_stage):
    calls: list[str] = []
    result = run_fake_invocation(cancel_stage=cancel_stage, calls=calls)
    assert result.failure.reason == "cancelled"
    assert calls.count("cleanup") == (0 if cancel_stage == "before_acquire" else 1)
    assert "promote" not in calls


def test_timeout_and_output_bounds_fail_before_promotion_with_one_cleanup():
    calls: list[str] = []
    result = run_fake_invocation(
        calls=calls,
        duration_ms=30_001,
        output_bytes=65_537,
    )
    assert result.failure.stage == "validation"
    assert result.failure.cleanup_status == "clean"
    assert calls.count("cleanup") == 1
    assert "promote" not in calls


def test_cleanup_ambiguity_overrides_success_and_fails_closed():
    result = run_fake_invocation(cleanup_status="indeterminate")
    assert result.failure.reason == "cleanup_ambiguous"
    assert result.promoted is False


def test_structured_cleanup_receipt_is_preserved_on_success_and_failure():
    success = run_fake_invocation(cleanup_status="clean")
    assert success.cleanup.status == "clean"
    assert success.cleanup.receipt["status"] == "released"
    failed = run_fake_invocation(provider_failure=True, cleanup_status="clean")
    assert failed.failure.reason == "provider_failed"
    assert failed.cleanup.receipt["status"] == "released"
```

Also assert unknown bundle ref and capability mismatch fail before adapter invocation and before acquisition.
For a managed-model fake descriptor, add missing lease, wrong `profile_id`, stale incarnation, and bundle mismatch cases; every case must fail before the fake transport records `dispatch`.

- [ ] **Step 2: Run the focused test and confirm RED**

```powershell
uv run pytest tests/test_uei_v1_provider_capabilities.py -q
```

Expected: failures for the missing invocation coordinator.

- [ ] **Step 3: Implement the smallest invocation coordinator**

Use these types and signature:

```python
TRequest = TypeVar("TRequest")
TResult = TypeVar("TResult")


@dataclass(frozen=True)
class CapabilityCleanupOutcomeV1:
    status: str
    receipt: dict[str, object] | None


@dataclass(frozen=True)
class CapabilityInvocationFailure:
    stage: str
    reason: str
    retryable: bool
    cleanup_status: str


@dataclass(frozen=True)
class CapabilityInvocationOutcome(Generic[TResult]):
    result: TResult | None
    failure: CapabilityInvocationFailure | None
    cleanup: CapabilityCleanupOutcomeV1
    promoted: bool


def invoke_with_capability_envelope(
    *,
    request: TRequest,
    adapter: object,
    invoke: Callable[[TRequest], TResult],
    validate_result: Callable[[TResult, ProviderRunBudget], TResult],
    cleanup: Callable[[], dict[str, object]] | None,
    validate_cleanup: Callable[[dict[str, object]], CapabilityCleanupOutcomeV1],
) -> CapabilityInvocationOutcome[TResult]:
    """执行一次受限 provider 调用；不持久化、不重试、不授予权限。"""
```

The coordinator validates before acquisition, checks cancellation before invoke and before promotion, applies the already-intersected budget, calls cleanup at most once in `finally`, validates the structured receipt, and returns it on both success and failure. Any cleanup outcome other than `clean` or `not_required` forces `promoted=False`. It does not create worker processes, supervise PIDs, retry, or write benchmark evidence.

The caller owns acquisition and passes the exact lease in `request.envelope.resource_lease`; `cleanup` is the matching one-shot release owner for that lease. An adapter that requires a managed resource must reject `resource_lease=None` before invoking its transport.

Add an interface test whose fake `cleanup` returns the same public field shape as `release_managed_qwen_model_lease`; the validator must preserve the returned dictionary byte-for-byte in `CapabilityCleanupOutcomeV1.receipt` after checking it.

- [ ] **Step 4: Run GREEN tests**

```powershell
uv run pytest tests/test_uei_v1_provider_capabilities.py -q
```

Expected: all envelope, cancellation, timeout, bounds, and cleanup tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add -- app/learn/recognition/uei/provider_capabilities.py tests/test_uei_v1_provider_capabilities.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat(provider): enforce bounded capability invocation"
```

---

### Task 4: OmniParser Discovery Compatibility Adapter

**Files:**
- Create: `app/learn/hybrid/provider_capability_adapters.py`
- Create: `tests/test_learn_hybrid_provider_capability_adapters.py`

**Interfaces:**
- Consumes: `OmniParserShadowAdapter`, `NormalizedScreenParseOutput`, Task 2 discovery request/result.
- Produces: `OmniDiscoveryCompatibilityAdapter.invoke(request)` and `project_discovery_to_screen_parse_v1(result)`.

- [ ] **Step 1: Write RED compatibility tests**

Use a fake `ScreenParseProviderAdapter` returning two current `NormalizedProviderItem` objects. Assert:

```python
def test_omni_compatibility_projection_is_field_equivalent_to_current_output():
    current = current_screen_parse_output_fixture()
    adapter = OmniDiscoveryCompatibilityAdapter(
        bundle_ref=discovery_bundle_ref(),
        delegate=RecordedScreenParseAdapter(current),
    )
    neutral = adapter.invoke(discovery_request_fixture())
    projected = project_discovery_to_screen_parse_v1(neutral)
    assert projected == current
```

Add tests that provider-supplied IDs remain unchanged, missing IDs receive deterministic neutral IDs, duplicate IDs and reorder mismatches fail, and nested authority-shaped payloads cannot enter a neutral item. Confirm cancellation and budget are passed to the existing delegate unchanged after intersection.

- [ ] **Step 2: Run the focused tests and confirm RED**

```powershell
uv run pytest tests/test_learn_hybrid_provider_capability_adapters.py -q
```

Expected: import failure because the compatibility adapter module does not exist.

- [ ] **Step 3: Implement discovery adaptation without production routing**

Use:

```python
class OmniDiscoveryCompatibilityAdapter:
    capability = "candidate_discovery"

    def __init__(
        self,
        *,
        bundle_ref: dict[str, str],
        delegate: ScreenParseProviderAdapter,
    ) -> None:
        self.bundle_ref = dict(bundle_ref)
        self._delegate = delegate

    def invoke(self, request: CandidateDiscoveryRequestV1) -> CandidateDiscoveryResultV1:
        output = self._delegate.invoke(
            capture=request.capture,
            budget=request.envelope.budget,
            invocation_id=request.envelope.invocation_id,
            cancellation_event=request.envelope.cancellation_event,
        )
        return normalize_current_screen_parse_output(request=request, output=output)


def project_discovery_to_screen_parse_v1(
    result: CandidateDiscoveryResultV1,
) -> NormalizedScreenParseOutput:
    """投影回现有 UEI runtime 输入，不持久化 bundle 字段。"""
```

Keep `NormalizedProviderItem` and `ShadowProviderRuntime` unchanged. The compatibility adapter synthesizes a non-empty ID only in its transient neutral result; projection of existing items with provider IDs remains field-equivalent. Do not wire `run_hybrid_omni_discovery` to the new adapter in this task.

- [ ] **Step 4: Run focused compatibility regression**

```powershell
uv run pytest tests/test_learn_hybrid_provider_capability_adapters.py tests/test_uei_v1_provider_runtime.py tests/test_uei_v1_omniparser_shadow_adapter.py tests/test_learn_hybrid_omni_discovery.py -q
```

Expected: all tests pass and no model process starts.

- [ ] **Step 5: Commit Task 4**

```powershell
git add -- app/learn/hybrid/provider_capability_adapters.py tests/test_learn_hybrid_provider_capability_adapters.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat(provider): adapt Omni discovery capability"
```

---

### Task 5: Qwen Semantic Binding Compatibility Projection

**Files:**
- Modify: `app/learn/hybrid/qwen_binding.py`
- Modify: `app/learn/hybrid/provider_capability_adapters.py`
- Modify: `tests/test_learn_hybrid_qwen_binding.py`
- Modify: `tests/test_learn_hybrid_provider_capability_adapters.py`

**Interfaces:**
- Consumes: current compact/legacy Qwen wire forms, Task 2 semantic request/result.
- Produces: `normalize_qwen_semantic_result`, `project_semantic_result_to_hybrid_qwen_v1`, and `QwenSemanticBindingCompatibilityAdapter.invoke(request)`; public `parse_qwen_candidate_bindings` and `run_qwen_candidate_binding` retain signatures and v1 output.

- [ ] **Step 1: Add RED projection-equivalence tests**

Freeze one current compact response and one current legacy response. For each response compare the old expected artifact to the new composition:

```python
def test_qwen_neutral_projection_preserves_existing_hybrid_qwen_bindings_v1():
    inventory = _sealed_inventory(inventory_fixture(candidate_count=4))
    raw = _compact_wire_raw_for(inventory)
    expected = parse_qwen_candidate_bindings(
        raw,
        inventory,
        context_ref={"id": "hybrid-context/test", "content_sha256": "5" * 64},
    )
    neutral = normalize_qwen_semantic_result(
        raw=raw,
        inventory=inventory,
        bundle_ref=semantic_bundle_ref(),
        invocation_id="invocation/qwen-test",
        context_ref={"id": "hybrid-context/test", "content_sha256": "5" * 64},
    )
    actual = project_semantic_result_to_hybrid_qwen_v1(
        result=neutral,
        inventory=inventory,
        context_ref={"id": "hybrid-context/test", "content_sha256": "5" * 64},
    )
    assert canonical_json_bytes(actual) == canonical_json_bytes(expected)
```

Add tests for exact order/coverage, open non-empty role strings, invalid/whitespace roles, confidence bounds, geometry injection, nested authority aliases, prose, duplicates, unknown IDs, and cross-capture refs. Assert `binding_status` is transient and absent from `hybrid_qwen_bindings_v1`.

- [ ] **Step 2: Run Qwen tests and confirm RED only for new composition**

```powershell
uv run pytest tests/test_learn_hybrid_qwen_binding.py tests/test_learn_hybrid_provider_capability_adapters.py -q
```

Expected: existing tests remain green; new imports/assertions fail.

- [ ] **Step 3: Extract normalization and projection while keeping public behavior**

Use these signatures:

```python
def normalize_qwen_semantic_result(
    *,
    raw: Mapping[str, Any] | str,
    inventory: Mapping[str, Any],
    bundle_ref: dict[str, str],
    invocation_id: str,
    context_ref: Mapping[str, Any],
) -> SemanticBindingResultV1:
    """将 Qwen wire result 验证为临时语义绑定，不持久化。"""


def project_semantic_result_to_hybrid_qwen_v1(
    *,
    result: SemanticBindingResultV1,
    inventory: Mapping[str, Any],
    context_ref: Mapping[str, Any],
) -> dict[str, Any]:
    """生成与现有 hybrid_qwen_bindings_v1 完全兼容的 artifact。"""
```

Make `parse_qwen_candidate_bindings` call those functions and then `validate_qwen_bindings`. Keep the current compact-status mapping to `semantic_confidence`, `task_relevance`, `relation`, and `ambiguity`. Do not add `bundle_ref`, `binding_status`, or a closed role enum to the legacy artifact.

`QwenSemanticBindingCompatibilityAdapter` must use the common envelope and call the same model runner path currently used by `run_qwen_candidate_binding`; it must not select a model automatically.

- [ ] **Step 4: Run focused Qwen and workflow regressions**

```powershell
uv run pytest tests/test_learn_hybrid_qwen_binding.py tests/test_learn_hybrid_provider_capability_adapters.py tests/test_learning_workflow_stage_execution.py tests/test_learning_workflow_stage_worker.py -q
```

Expected: all selected tests pass with no model startup.

- [ ] **Step 5: Commit Task 5**

```powershell
git add -- app/learn/hybrid/qwen_binding.py app/learn/hybrid/provider_capability_adapters.py tests/test_learn_hybrid_qwen_binding.py tests/test_learn_hybrid_provider_capability_adapters.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat(provider): adapt semantic binding capability"
```

---

### Task 6: VISTA Grounding Compatibility Projection

**Files:**
- Modify: `app/learn/hybrid/vista_refinement.py`
- Modify: `app/learn/hybrid/provider_capability_adapters.py`
- Modify: `tests/test_learn_hybrid_vista_refinement.py`
- Modify: `tests/test_learn_hybrid_provider_capability_adapters.py`

**Interfaces:**
- Consumes: existing sealed VISTA request and provider result; Task 2 grounding request/result.
- Produces: `normalize_vista_grounding_result`, `project_grounding_result_to_hybrid_vista_refinement_v1`, and `VistaGroundingRefinementCompatibilityAdapter.invoke(request)`; public `validate_vista_proposal` retains signature and output.

- [ ] **Step 1: Add RED grounding projection tests**

Use the current `_request()` and `_raw_result()` fixtures. Assert canonical-byte equality between the old expected v1 artifact and the neutral projection. Add eight strict-interior edge/corner cases for both candidate bbox and permitted ROI.

Add this raw-trace safety case:

```python
@pytest.mark.parametrize("key", [
    "approved_to_click", "execute", "final_submit", "send", "confirm", "payment",
])
def test_vista_raw_trace_authority_keys_are_rejected_before_projection(key):
    request = _request()
    raw = _raw_result(request)
    raw["provenance"]["nested"] = {key: True}
    with pytest.raises(ValueError, match="non_authorizing"):
        normalize_vista_grounding_result(
            request=request,
            raw_result=raw,
            bundle_ref=grounding_bundle_ref(),
            invocation_id="invocation/vista-authority-test",
        )

    legacy = validate_vista_proposal(request=request, raw_result=raw)
    assert legacy["review_status"] == "REVIEW_REQUIRED"
    assert legacy["automatic_acceptance"] is False
    assert legacy["raw_provider_result"] == {
        "quarantined": True,
        "content_sha256": content_sha256({"raw_provider_result": raw}),
    }
    assert legacy["provider_provenance"] == {
        "quarantined": True,
        "content_sha256": content_sha256({"raw_provider_result": raw}),
    }
    reject_authority_shaped_payload(legacy)
```

Confirm the legacy artifact still contains the accepted non-authorizing `raw_provider_result` and `provider_provenance` bytes for existing fixtures.

- [ ] **Step 2: Run VISTA tests and confirm RED only for new safety/composition tests**

```powershell
uv run pytest tests/test_learn_hybrid_vista_refinement.py tests/test_learn_hybrid_provider_capability_adapters.py -q
```

Expected: existing tests pass; new imports or authority rejection fail.

- [ ] **Step 3: Extract neutral normalization and unchanged v1 projection**

Use:

```python
def normalize_vista_grounding_result(
    *,
    request: Mapping[str, Any],
    raw_result: Mapping[str, Any],
    bundle_ref: dict[str, str],
    invocation_id: str,
) -> GroundingRefinementResultV1:
    """验证精确 lineage、变换和严格内点，返回临时证据。"""


def project_grounding_result_to_hybrid_vista_refinement_v1(
    *,
    request: Mapping[str, Any],
    raw_result: Mapping[str, Any],
    result: GroundingRefinementResultV1,
) -> dict[str, Any]:
    """保持现有 hybrid_vista_refinement_proposal_v1 字段与语义。"""
```

Make `validate_vista_proposal` compose these functions while preserving its existing rule that validation failures return a `REVIEW_REQUIRED` failure artifact rather than raising. Continue using strict `_point_inside`; do not change `contracts.validate_vista_proposals` or historical aggregate interpretation. `normalize_vista_grounding_result` raises on authority-shaped raw input; the public legacy entrypoint catches that error and replaces both `raw_provider_result` and `provider_provenance` with the same deterministic hash-only quarantine object shown in the test. Recursively validate the complete returned artifact as non-authorizing. Normal non-authorizing historical fixtures retain their exact raw bytes and v1 projection.

- [ ] **Step 4: Run focused VISTA and review projection regressions**

```powershell
uv run pytest tests/test_learn_hybrid_vista_refinement.py tests/test_learn_hybrid_provider_capability_adapters.py tests/test_learn_hybrid_contracts.py tests/test_learning_calibration_sequence.py -q
```

Expected: all tests pass with historical aggregate behavior unchanged.

- [ ] **Step 5: Commit Task 6**

```powershell
git add -- app/learn/hybrid/vista_refinement.py app/learn/hybrid/provider_capability_adapters.py tests/test_learn_hybrid_vista_refinement.py tests/test_learn_hybrid_provider_capability_adapters.py
git diff --cached --check
git diff --cached --stat
git commit -m "feat(provider): adapt grounding refinement capability"
```

---

### Task 7: Explicit Candidate Bundle Configuration and Resolution

**Files:**
- Create: `app/learn/hybrid/provider_bundle_config.py`
- Create: `tests/test_learn_hybrid_provider_bundle_config.py`
- Create: `configs/provider_bundles/omniparser-discovery-compat-v1.json`
- Create: `configs/provider_bundles/qwen3-semantic-binding-compat-v1.json`
- Create: `configs/provider_bundles/vista-grounding-refinement-compat-v1.json`
- Create: `configs/provider_bundles/provider-candidate-config-v1.json`

**Interfaces:**
- Consumes: Task 1 descriptor sealing/ref functions and registry.
- Produces: `seal_provider_candidate_config_v1(value)`, `load_provider_candidate_config(project_root, config_path)`, `load_provider_bundle_descriptors(project_root, config)`, and `resolve_configured_bundle(capability, config, registry)`.

- [ ] **Step 1: Write RED closed-config tests**

Build the configuration from real sealed descriptor refs so no hash is hand-written:

```python
sealed_config = seal_provider_candidate_config_v1({
    "contract_version": "provider_candidate_config_v1",
    "config_id": "provider-candidate-config/local-compat-v1",
    "capability_bundle_refs": {
        descriptor["capability"]: provider_bundle_ref(descriptor)
        for descriptor in sealed_descriptors
    },
    "bundle_descriptor_paths": [
        "configs/provider_bundles/omniparser-discovery-compat-v1.json",
        "configs/provider_bundles/qwen3-semantic-binding-compat-v1.json",
        "configs/provider_bundles/vista-grounding-refinement-compat-v1.json",
    ],
})
```

Tests must prove:

```python
def test_candidate_config_resolves_one_exact_bundle_per_capability(project_root):
    config = load_provider_candidate_config(project_root)
    descriptors = load_provider_bundle_descriptors(project_root, config)
    registry = TrustedProviderBundleRegistry([
        (descriptor, FakeCapabilityAdapter(descriptor["capability"]))
        for descriptor in descriptors
    ])
    for capability in sorted(PROVIDER_CAPABILITIES):
        resolved = resolve_configured_bundle(
            capability=capability,
            config=config,
            registry=registry,
        )
        assert resolved.descriptor["capability"] == capability
```

Also test path escape, symlink descriptor, duplicate capability, duplicate descriptor path, unknown/extra key, wrong hash, wrong capability, ambiguous registry entry, and old-score ref mismatch. Hash and compare `configs/learn_hybrid_v1_1.json` before and after the test run.

- [ ] **Step 2: Run config tests and confirm RED**

```powershell
uv run pytest tests/test_learn_hybrid_provider_bundle_config.py -q
```

Expected: import failure because the candidate config loader does not exist.

- [ ] **Step 3: Implement the isolated loader and materialize sealed descriptors**

Use:

```python
def load_provider_candidate_config(
    project_root: Path,
    config_path: str = "configs/provider_bundles/provider-candidate-config-v1.json",
) -> dict[str, object]:
    """只读取独立 candidate config，不回退到 frozen Hybrid v1.1。"""


def seal_provider_candidate_config_v1(value: object) -> dict[str, object]:
    """验证闭合 candidate config，并绑定三个 exact bundle refs。"""


def load_provider_bundle_descriptors(
    project_root: Path,
    config: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """解析 project-root 内的普通文件并验证每个 sealed descriptor。"""


def resolve_configured_bundle(
    *,
    capability: str,
    config: Mapping[str, object],
    registry: TrustedProviderBundleRegistry,
) -> ResolvedProviderBundle:
    """只按显式 capability + exact bundle ref 解析；无 fallback。"""
```

Use UTF-8 reads, reject absolute paths and resolved paths outside `project_root`, reject symlinks, and validate exact key sets. Build the three descriptor dictionaries using SHA-256 of the current model profile, prompt renderer/parser/adapter source, transport configuration, and locally present model/runtime artifacts; call `seal_provider_bundle_descriptor_v1`, write each with `canonical_json_bytes(descriptor) + b"\n"`, then build the candidate config from `provider_bundle_ref(descriptor)` and write it the same way. Do not modify model weights or frozen Benchmark fixtures.

- [ ] **Step 4: Run focused config and frozen-config regressions**

```powershell
uv run pytest tests/test_learn_hybrid_provider_bundle_config.py tests/test_learn_hybrid_contracts.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py -q
```

Expected: all tests pass; `configs/learn_hybrid_v1_1.json` and frozen release fixtures remain unchanged.

- [ ] **Step 5: Commit Task 7**

```powershell
git add -- app/learn/hybrid/provider_bundle_config.py tests/test_learn_hybrid_provider_bundle_config.py configs/provider_bundles/omniparser-discovery-compat-v1.json configs/provider_bundles/qwen3-semantic-binding-compat-v1.json configs/provider_bundles/vista-grounding-refinement-compat-v1.json configs/provider_bundles/provider-candidate-config-v1.json
git diff --cached --check
git diff --cached --stat
git commit -m "feat(provider): resolve explicit capability bundles"
```

---

### Task 8: Compatibility Acceptance and Documentation Sync

**Files:**
- Modify: `app/learn/recognition/uei/__init__.py`
- Modify: `app/learn/hybrid/__init__.py`
- Modify: `tests/test_learn_hybrid_provider_capability_adapters.py`
- Modify: `README.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: one importable compatibility surface and verified documentation status; no model execution and no production provider switch.

- [ ] **Step 1: Add the final RED acceptance test**

Create one test that uses deterministic fake provider calls for all three capabilities:

```python
def test_three_replaceable_capabilities_reach_unchanged_legacy_projection():
    discovery_adapter = OmniDiscoveryCompatibilityAdapter(
        bundle_ref=discovery_bundle_ref(),
        delegate=RecordedScreenParseAdapter(current_screen_parse_output_fixture()),
    )
    discovery = discovery_adapter.invoke(discovery_request_fixture())
    screen_parse_v1 = project_discovery_to_screen_parse_v1(discovery)

    inventory = _sealed_inventory(inventory_fixture(candidate_count=1))
    semantic = normalize_qwen_semantic_result(
        raw=_compact_wire_raw_for(inventory),
        inventory=inventory,
        bundle_ref=semantic_bundle_ref(),
        invocation_id="invocation/qwen-acceptance",
        context_ref={"id": "hybrid-context/test", "content_sha256": "5" * 64},
    )
    qwen_v1 = project_semantic_result_to_hybrid_qwen_v1(
        result=semantic,
        inventory=inventory,
        context_ref={"id": "hybrid-context/test", "content_sha256": "5" * 64},
    )

    vista_request = _request()
    raw_vista = _raw_result(vista_request)
    grounding = normalize_vista_grounding_result(
        request=vista_request,
        raw_result=raw_vista,
        bundle_ref=grounding_bundle_ref(),
        invocation_id="invocation/vista-acceptance",
    )
    vista_v1 = project_grounding_result_to_hybrid_vista_refinement_v1(
        request=vista_request,
        raw_result=raw_vista,
        result=grounding,
    )
    assert isinstance(screen_parse_v1, NormalizedScreenParseOutput)
    assert qwen_v1["contract_version"] == "hybrid_qwen_bindings_v1"
    assert vista_v1["contract_version"] == "hybrid_vista_refinement_proposal_v1"
    assert qwen_v1["approved_to_click"] is False
    assert vista_v1["automatic_acceptance"] is False
```

Assert the three adapters may be replaced independently in the registry and that an absent optional grounding bundle fails closed without calling discovery or semantic again.

- [ ] **Step 2: Run acceptance test and confirm RED**

```powershell
uv run pytest tests/test_learn_hybrid_provider_capability_adapters.py -q
```

Expected: only the unwired public import/acceptance assertions fail.

- [ ] **Step 3: Export stable internal symbols and update documentation**

Export only the bundle descriptor/ref/registry, three Protocols, typed request/results, and compatibility adapters. Do not expose model-specific selection through the public Runtime API.

Documentation must state exactly:

```text
Perception is one public evidence boundary with three replaceable internal capabilities:
candidate discovery, semantic binding, and grounding refinement.
Current OmniParser, Qwen, and VISTA integrations are compatibility bundles, not permanent architecture.
Provider evidence never grants execution authority.
```

Mark status honestly:

- capability contracts and fake conformance: Stable after tests pass;
- current-provider compatibility projection: Stable after fixture equivalence passes;
- candidate bundle selection: Partial until one replacement model completes regression;
- automatic routing: not implemented and out of scope.

- [ ] **Step 4: Run the complete no-model acceptance set**

```powershell
uv run pytest tests/test_uei_v1_provider_bundles.py tests/test_uei_v1_provider_capabilities.py tests/test_learn_hybrid_provider_capability_adapters.py tests/test_learn_hybrid_provider_bundle_config.py tests/test_uei_v1_provider_runtime.py tests/test_uei_v1_omniparser_shadow_adapter.py tests/test_learn_hybrid_omni_discovery.py tests/test_learn_hybrid_qwen_binding.py tests/test_learn_hybrid_vista_refinement.py tests/test_learn_hybrid_contracts.py tests/test_learn_hybrid_fusion.py tests/test_learning_calibration_sequence.py tests/test_learning_workflow_stage_execution.py tests/test_learning_workflow_stage_worker.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py -q
```

Then run:

```powershell
git diff --check
git status --short
```

Expected: all selected tests pass, no model listeners/processes are created, frozen Benchmark v2 fixture diffs are empty, and only Task 8 files are dirty.

- [ ] **Step 5: Request independent review before the final compatibility commit**

The reviewer must check: no historical artifact/schema change, no authority promotion, no frozen config change, exact bundle identity, cancellation/cleanup behavior, and no automatic routing. Resolve every Critical/Important issue before committing.

- [ ] **Step 6: Commit Task 8**

```powershell
git add -- app/learn/recognition/uei/__init__.py app/learn/hybrid/__init__.py tests/test_learn_hybrid_provider_capability_adapters.py README.md PROJECT_SUMMARY.md ARCHITECTURE.md CURRENT_STATE.md NEXT_STEPS.md
git diff --cached --check
git diff --cached --stat
git commit -m "docs(architecture): document replaceable perception boundary"
```

## Phase Completion Gate

The compatibility phase is complete only when Tasks 1–8 are committed, the no-model acceptance set passes, independent review reports no Critical/Important issue, and `git diff` shows no change to frozen Hybrid v1.1 or Benchmark v2 artifacts. Do not claim a real provider has been replaced yet. The separate Qwen2.5 replacement-proof plan governs model startup and regression.
