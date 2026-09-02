# Replaceable Perception Capability Contracts Design

## Status

Approved direction: every perception role is replaceable. This document freezes the smallest backward-compatible design needed to make that direction executable without changing current model behavior or historical Benchmark v2 evidence.

## Product boundary

The product keeps one public perception boundary:

```text
Provider-native input/output
        -> Provider Adapter
        -> Canonical UEI evidence
        -> Human Review
        -> Reviewed Workflow
        -> Runtime / Relocation / Gate / Execute / Verify
```

Provider output is evidence only. It never grants execution authority. Learning, Review, Workflow compilation, and Runtime must not branch on model names.

Inside the perception boundary, providers may implement one or more independent capabilities:

1. `candidate_discovery`
2. `semantic_binding`
3. `grounding_refinement`

A deployment may use one provider for all three capabilities, three separate providers, deterministic/UIA implementations, or omit an optional capability. No specific three-model topology is mandatory.

## Goals

- Replace OmniParser without changing Semantic Binding, Review, or Runtime.
- Replace Qwen without changing Discovery, Review, or Runtime.
- Replace VISTA without changing Discovery, Semantic Binding, Review, or Runtime.
- Reuse canonical task semantics, role ontology, safety constraints, and output schemas across providers.
- Allow provider-specific prompts, preprocessing, transports, parsers, and coordinate conventions behind adapters.
- Preserve exact capture lineage, immutable candidate identity, non-authorizing evidence, bounded resource use, cancellation, and cleanup semantics.
- Preserve the accepted Benchmark v2 attempt and all historical artifact hashes.

## Non-goals

- No new model router, ensemble optimizer, or automatic provider selection.
- No second live Desktop I/O backend.
- No change to Runtime authority, Gate, action taxonomy, or final-submit prohibition.
- No change to Benchmark v2 Gold, corpus, scorer, estimand, thresholds, or accepted attempts.
- No renaming or rewriting of historical sealed artifacts.
- No requirement that every provider emit identical native output.
- No model startup as part of the compatibility-only implementation slices.

## Alternatives considered

### A. Backward-compatible capability SPIs — selected

Introduce provider-neutral internal interfaces and wrap the current OmniParser, Qwen, and VISTA paths. Keep frozen persisted contract versions accepted exactly as they are. New provider bundles target the neutral interfaces.

This proves replaceability with the lowest lineage and regression risk.

### B. Rename all Qwen/VISTA contracts immediately — rejected

Renaming `hybrid_qwen_*` and `hybrid_vista_*` artifacts would invalidate existing hashes, manifests, tests, receipts, and accepted benchmark lineage. It provides cosmetic neutrality at disproportionate migration cost.

### C. Add only model names to configuration — rejected

Configuration-only substitution would leave prompt construction, parsing, validation, cancellation, and cleanup coupled to current providers. It would not prove a reusable contract.

## Capability SPI contracts

The SPI is an internal code boundary. Canonical UEI remains the public interchange format consumed by Learning and Review.

### Candidate Discovery Provider

Purpose: propose possible interface regions from one immutable capture.

Input requirements:

- exact `RestrictedCaptureLease` or equivalent immutable capture reference;
- `capture_id`, screenshot hash, image size, and coordinate-space declaration;
- explicit `ProviderRunBudget`;
- cancellation token and invocation identity.

Normalized output requirements:

- non-empty, stable provider-scoped `source_item_id` before canonicalization;
- `kind`, optional safe text/role/state, optional provider confidence;
- region geometry with declared source coordinate space;
- duration and resource usage;
- no semantic action authority.

Current implementation: `OmniParserShadowAdapter` through the existing UEI screen-parse adapter path.

Provider-native discovery input may omit an identity. In that case the adapter must synthesize a deterministic, collision-checked `source_item_id` from the sealed bundle revision plus native item ordering/fingerprint. Missing, duplicate, or unstable identities fail before the canonical inventory is built.

### Semantic Binding Provider

Purpose: assign semantic identity to an immutable candidate set.

Input requirements:

- exact capture lineage and screenshot bytes;
- immutable ordered candidate set;
- candidate geometry as evidence supplied by Discovery, never model-created replacement geometry;
- optional same-capture OCR/UIA context;
- versioned role vocabulary reference and closed output requirements;
- budget, cancellation token, invocation identity, and provider lease where required.

Normalized output requirements:

- exact candidate coverage and order when the request is closed-world;
- `candidate_id`, role, label, binding status, and confidence;
- no new candidate IDs;
- no geometry, click point, execution permission, or final action;
- explicit ambiguity/conflict representation;
- fail closed on malformed, duplicate, unknown, omitted, or cross-capture output.

Current implementation: the Qwen request/parser/run path in `app/learn/hybrid/qwen_binding.py`.

The Qwen compatibility bundle preserves the current open, non-empty role-string behavior. A stricter canonical ontology requires a new ontology version and a new bundle/artifact version; it must not retroactively reject accepted legacy roles.

### Grounding Refinement Provider

Purpose: refine a point or region only after semantic identity is already established.

Input requirements:

- exact capture lineage;
- one immutable candidate identity and bbox;
- one sealed permitted ROI;
- BOUND semantic/fusion state;
- coordinate transform lineage when provider coordinates differ from capture pixels;
- budget, cancellation token, invocation identity, and provider lease where required.

Normalized output requirements:

- the same candidate identity;
- refined point or classified failure;
- point inside both permitted ROI and immutable candidate bbox;
- declared coordinate space, confidence, and evidence refs;
- review remains required;
- no ability to change semantic identity or authorize execution.

Current implementation: the VISTA request/validation path in `app/learn/hybrid/vista_refinement.py`.

Neutral grounding uses **strict interior** containment: a point on any ROI or candidate-bbox edge is invalid. The VISTA compatibility adapter follows `validate_vista_proposal`; historical aggregate artifacts remain interpreted by their existing versioned validator and are not rewritten.

## Invocation envelope

Every capability adapter accepts one common invocation envelope containing the exact bundle reference, capability, invocation ID, immutable input lineage, budget, cancellation handle, and required resource lease. The adapter must:

1. validate lineage and bundle identity before acquiring resources;
2. intersect the caller budget with existing provider-specific limits;
3. enforce byte, item, string, duration, and resource ceilings;
4. observe cancellation before acquisition, during invocation, and before result promotion;
5. produce exactly one terminal cleanup receipt for every acquired lease.

Compatibility adapters may call the current provider-specific runners internally, but may not weaken their current bounds or cleanup behavior. Slices 1–3 prove pre/mid/post cancellation, timeout, and cleanup with deterministic fake runners only; they do not start models.

## Projection boundary

The neutral request/result shapes are **transient internal validation forms**. They are not persisted, are not directly consumed by Human Review or Runtime, and do not replace existing UEI or Hybrid artifacts.

The compatibility flow is:

```text
provider-native output
        -> capability adapter
        -> transient neutral validation
        -> provider-specific legacy projection
        -> existing canonical/Hybrid validation and persistence
```

The named projections are:

- Discovery adapter -> the existing Omni inventory/UEI canonicalization path and its current persisted contract;
- Semantic Binding adapter -> `hybrid_qwen_bindings_v1` with the current fields such as `semantic_confidence`, `task_relevance`, `relation`, and `ambiguity`; transient `binding_status` is validation state and is not added to the legacy artifact;
- Grounding adapter -> `hybrid_vista_refinement_proposal_v1`, plus `hybrid_vista_proposals_v1` only where the existing aggregate path already requires it.

For a compatibility fixture, the legacy projection must be byte-equivalent where serialization is canonical and field-equivalent otherwise. The transient form may contain stricter validation metadata, but none of that metadata silently changes a persisted v1 contract.

## Provider Bundle

Benchmarking and release identity apply to a Provider Bundle, not model weights alone. A bundle contains:

```text
model identity and revision
transport and runtime
preprocessing revision
canonical prompt-spec revision
provider prompt-renderer revision
native-output parser revision
canonical adapter revision
coordinate convention
decoding/inference configuration
model, projector, and runtime artifact hashes where local
declared capabilities and resource budget
```

Changing any load-bearing member creates a new bundle revision. It must not silently inherit an earlier benchmark score.

This identity is machine-checkable through a closed, sealed `ProviderBundleDescriptorV1`. It binds:

- `bundle_id`, bundle revision, capability, provider/profile/model identity and version;
- prompt spec, renderer, parser, adapter, preprocessing, transport, coordinate, and decoding revisions/hashes;
- local model/projector/runtime artifact hashes when applicable;
- declared capability and resource budget.

The descriptor has a canonical content hash and an immutable `bundle_ref`. Every invocation, neutral result, cleanup receipt, and new benchmark attempt carries the exact `bundle_ref`. Registration rejects duplicate keys, wrong-capability lookup, hash mismatch, and unknown revisions. A benchmark score belongs only to the exact sealed bundle ref used by that attempt; changing one bound field creates a different identity and cannot inherit the old score.

## Prompt reuse

Prompts are split into two layers.

### Canonical PromptSpec

Reusable across providers:

- task kind and input identities;
- versioned role vocabulary/ontology reference;
- required/forbidden fields;
- evidence-only and non-authorizing constraints;
- output contract and coordinate-space semantics;
- closed-world candidate rules;
- ambiguity and safe-stop behavior.

### Provider Prompt Renderer

Provider-specific:

- chat template and message shape;
- native JSON Schema or tool schema;
- action grammar or special grounding tokens;
- normalized-versus-pixel coordinate instructions;
- image resizing/tokenization settings;
- decoding parameters required for deterministic contract compliance.

The canonical PromptSpec is reusable. The rendered natural-language prompt is not assumed to be portable between model families.

## Compatibility and migration

The first implementation must not alter model behavior or persisted artifact bytes.

- Existing `hybrid_qwen_binding_request_v1`, `hybrid_qwen_bindings_v1`, Qwen failure traces, Qwen leases, and Benchmark v2 Qwen identities remain valid.
- Existing VISTA artifact, lease, cleanup, and Benchmark v2 identities remain valid.
- Existing OmniParser shadow/provider receipts and cleanup evidence remain valid.
- Provider-neutral interface names are introduced in code, while current provider-specific functions remain compatibility entrypoints.
- `configs/learn_hybrid_v1_1.json` and `load_hybrid_config` remain unchanged and continue to serve only the frozen Hybrid v1.1 path.
- Capability-based bundle selection is carried by a new sealed bundle registry and a new-version candidate configuration/loader. Benchmark v2 accepted attempts load only the frozen v1.1 configuration. A candidate configuration has its own hash and cannot inherit an old score.
- Historical artifacts are read as historical provider-specific versions; they are never rewritten into a generic name.

## Implementation slices

### Slice 1 — neutral interfaces and conformance fixtures

- Add the three Protocols and provider-neutral request/result data shapes in a focused module.
- Add contract tests proving non-authorizing output, exact lineage, bounded resources, capability declaration, sealed bundle identity, and deterministic source-item identity.
- Do not route production calls through the new interfaces yet.

### Slice 2 — current-provider compatibility adapters

- Wrap OmniParser, Qwen, and VISTA behind their matching capability SPIs.
- Prove each named legacy projection is byte/field equivalent to current validated artifacts for stored fixtures.
- Keep existing public functions and model-specific contracts unchanged.

### Slice 3 — explicit bundle resolution

- Add a separate sealed bundle registry and new-version candidate config/loader; do not edit `learn_hybrid_v1_1.json` or `load_hybrid_config`.
- Resolve a provider by capability plus explicit configured bundle ID and exact bundle ref.
- No automatic routing or fallback.
- Unsupported or ambiguous capability resolution fails closed before provider invocation.

### Slice 4 — first replacement proof

- Add Qwen2.5-VL-7B as a separate Semantic Binding Provider Bundle.
- Run protocol smoke on the three previously failing complex screens.
- Only if smoke passes, create a new sealed regression candidate and run the existing 12-screen/60-target regression.
- Do not modify the Qwen3 baseline or run unique holdout.

The remaining Discovery and Grounding challengers are separate future slices. Their interfaces are established now; their models are not integrated in the first replacement proof.

## Failure and safety behavior

- Missing capability, untrusted bundle identity, unsupported coordinate convention, malformed native output, invalid schema, stale capture, unknown/duplicate candidate, out-of-bounds geometry, timeout, cancellation ambiguity, or cleanup ambiguity all fail closed.
- Adapter errors remain structured and retain retryability, cleanup state, duration, and resource usage.
- Provider confidence never becomes Runtime execution authority.
- Authority-shaped keys such as `approved_to_click`, `execute`, `final_submit`, or aliases may appear only inside a restricted/quarantined raw trace. They are recursively rejected from neutral results and legacy projections and are never interpreted by Review or Runtime.
- Runtime continues to require fresh observation, relocation, Gate approval, one-time authority, one bounded dispatch, and post-state verification.

## Verification

Each implementation slice requires focused TDD and one atomic commit.

Minimum acceptance:

1. all current provider-specific tests remain green;
2. stored current-provider fixtures produce unchanged canonical artifacts;
3. capability mismatch, duplicate registration, malformed bundle ref, single-field descriptor tampering, and old-score/bundle mismatch fail closed;
4. semantic providers cannot add geometry or candidates;
5. grounding providers cannot change candidate identity or escape the sealed ROI/bbox; all four edges and four corners fail the strict-interior neutral rule;
6. discovery output remains non-authorizing;
7. no model process is started in Slices 1–3;
8. no Benchmark v2 accepted artifact, Gold, corpus, scorer, estimand, Gate, or historical receipt changes;
9. missing/duplicate/reordered synthesized source identities fail conformance;
10. nested authority-shaped keys in all three capability outputs remain quarantined and cannot reach Review or Runtime;
11. current accepted non-enum Qwen role strings remain valid in the compatibility bundle;
12. pre/mid/post cancellation, timeout, budget ceilings, and exactly-one terminal cleanup receipt pass using fake runners;
13. documentation names the model-neutral interfaces while clearly marking provider-specific historical contracts as compatibility artifacts.

## Completion criterion

The design is proven when Qwen2.5 can be substituted as a separate Semantic Binding Provider Bundle, its output reaches the same canonical review path, and neither Learning, Review, Reviewed Workflow, nor Runtime requires a model-specific code change.
