# Universal Evidence Interface v1 Milestone 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the offline, content-addressed UEI v1 screen-parse evidence boundary and prove three caller-supplied static projections conform without connecting it to runtime providers or action paths.

**Architecture:** Add eight Draft 2020-12 schema documents as the contract source, then add an isolated `app.learn.recognition.uei` package. Its object store seals and resolves immutable JCS-hashed objects; its registry performs the trusted-registration ∩ manifest ∩ request decision; its projection functions accept only static values and return durable safe results. The existing OCR, UIA, OmniParser, panel, grounding, capture, provider, and action call paths remain untouched.

**Tech Stack:** Python 3.11 standard library, pytest 8, JSON Schema Draft 2020-12 documents, and an in-house RFC 8785/JCS implementation; no package, runtime, network, GUI, model, or vendor dependency changes.

**Spec:** `docs/superpowers/specs/2026-08-21-universal-evidence-interface.md`

## Global Constraints

- Milestone 1 is offline static-fixture sidecar only; adapters receive values from the caller and never import, start, download, scan, or call OCR, UIA, OmniParser, Qwen, or another provider runtime.
- Create exactly the eight versioned contract schemas named in the approved spec; each uses Draft 2020-12 and rejects unknown fields at every object boundary except bounded `opaque_attributes`.
- All persisted UEI objects are UTF-8, JCS content-addressed, immutable, and referenced only as `{"id": ..., "content_sha256": ...}`; artifact byte hashes never substitute for object references.
- Projection entry preconditions fail as structured outer-boundary errors and write neither `provider_error_v1` nor `provider_safe_result_v1`; every later failure writes the error first, then one failed safe result.
- Validate trusted registration ∩ manifest ∩ request for profile, mode, privacy, egress, payload limits, and `uei-v1-static-projection`; rollout permits only `local_only` and `disabled` egress despite the schema retaining future `remote_allowed`.
- Enforce safe payload recursion limits after redaction, retain no wire payload, path, screenshot bytes, tokens, cookies, raw exception dump, click point, action, score, trust, calibration, or authorization field.
- Preserve provider source IDs; generate the specified `sha256:<JCS SHA-256>` ID only for source-ID-less OCR matches. Do not mutate input fixtures.
- Capture-coordinate identity requires exact artifact SHA-256 and image-size binding. Missing non-conflicting transforms remain successful review-only; malformed, conflicting, false-proof, out-of-bounds, or otherwise supplied-invalid transforms fail closed.
- Keep `review_only` non-authorizing. The closed UEI schemas intentionally contain neither `artifact_is_authorization` nor `execute_binding_enabled`; every projection test asserts those fields are absent. Do not add migration, provider adapter, feature-flag wiring, panel, grounding, replay, action, API, or GUI code.
- Preserve UTF-8 and original newline style. Before each code change use the smallest TDD loop; run only the narrow test file until its task is green.

---

## File Map

### New contract and fixture files

- `schemas/uei/v1/trusted_provider_registration_v1.schema.json` — trusted policy contract and closed payload-limit object.
- `schemas/uei/v1/artifact_ref_v1.schema.json` — immutable external-artifact descriptor.
- `schemas/uei/v1/capture_lineage_v1.schema.json` — capture/artifact provenance and capture dimensions.
- `schemas/uei/v1/affine_coordinate_transform_v1.schema.json` — transform declaration; runtime code proves its arithmetic and lineage conditions.
- `schemas/uei/v1/provider_manifest_v1.schema.json` — provider-declared profiles and capability shape.
- `schemas/uei/v1/screen_parse_request_v1.schema.json` — constrained, capture-bound profile request.
- `schemas/uei/v1/provider_safe_result_v1.schema.json` — redacted durable success/failed discriminated result.
- `schemas/uei/v1/provider_error_v1.schema.json` — bounded post-precondition error record.
- `tests/fixtures/uei-v1/static-projection-sidecar-v1.json` — registrations, manifests, artifact/capture/request objects, fixture bindings, and disabled-by-default rollout metadata for the three static cases.
- `tests/fixtures/uei-v1/rfc8785-appendix-b-vectors.json` — complete checked-in binary64 hexadecimal/JCS lexical-output vector table used without network access.
- `tests/fixtures/uei-v1/ocr-result-static.json`, `uia-snapshot-static.json`, `screen-parser-result-static.json` — only public synthetic static inputs.
- `tests/fixtures/uei-v1/expected-safe-results/{ocr,uia,screen-parser}.json` — canonical expected success projections, without hashes before the test seals them.

### New UEI implementation files

- `app/learn/recognition/uei/__init__.py` — exports only the public store, boundary, and projection entry points.
- `app/learn/recognition/uei/canonical.py` — UEI JCS formatting, deterministic IDs, hashing, sealing, immutable references, and JSON-value validation wrappers.
- `app/learn/recognition/uei/contracts.py` — schema loading, strict document validation, bounded opaque-value validation, typed UEI errors, and result/error invariant checks.
- `app/learn/recognition/uei/store.py` — append-only local content-addressed JSON object store used only by caller-supplied test roots.
- `app/learn/recognition/uei/registry.py` — precondition resolution and policy/manifest/request intersection.
- `app/learn/recognition/uei/projections.py` — pure OCRResult, UIA snapshot, and `screen_parser_result_v1` projection plus coordinate and privacy handling.

### New tests

- `tests/uei_v1_helpers.py` — synthetic sealed-object builders and static sidecar loaders used only by UEI tests.
- `tests/test_uei_v1_schemas.py`
- `tests/test_uei_v1_canonical.py`
- `tests/test_uei_v1_store.py`
- `tests/test_uei_v1_registry.py`
- `tests/test_uei_v1_coordinates.py`
- `tests/test_uei_v1_projections.py`
- `tests/test_uei_v1_fail_closed.py`
- `tests/test_uei_v1_static_conformance.py`

### Existing documentation updated after behavior is proven

- `README.md` — describe UEI v1 as an offline, non-authorizing evidence boundary and state its exclusions.
- `ARCHITECTURE.md` — add the schema/store/registry/projection boundary and its no-runtime integration.
- `CURRENT_STATE.md` — locally record completed offline scope and remaining integration milestones.
- `NEXT_STEPS.md` — locally list the next separately approved integration decision; do not imply it is enabled.

## Public Interfaces Established by This Plan

```python
# canonical.py
def canonical_json_bytes(value: object) -> bytes: ...
def content_sha256(value: dict[str, object]) -> str: ...
def seal_immutable(value: dict[str, object]) -> dict[str, object]: ...
def immutable_ref(value: dict[str, object], *, id_field: str) -> dict[str, str]: ...
def deterministic_result_id(*, request_ref: dict[str, str], provider_id: str, profile_id: str, fixture_kind: str) -> str: ...
def deterministic_error_id(*, request_ref: dict[str, str], provider_id: str, profile_id: str, stage: str, code: str) -> str: ...

# contracts.py
class UEIValidationError(ValueError): ...
class UEIOuterBoundaryError(UEIValidationError): ...
class UEIProjectionFailure(UEIValidationError): ...
def validate_contract(value: dict[str, object], *, contract_version: str) -> dict[str, object]: ...
def validate_opaque_attributes(value: object, *, limits: dict[str, object]) -> None: ...

# store.py
class UEIObjectStore:
    def __init__(self, *, root: Path) -> None: ...
    def put(self, value: dict[str, object]) -> dict[str, str]: ...
    def get(self, ref: dict[str, str], *, contract_version: str) -> dict[str, object]: ...
    def object_count(self, *, contract_version: str) -> int: ...
    @property
    def write_order(self) -> tuple[str, ...]: ...

# registry.py
def resolve_projection_context(*, store: UEIObjectStore, request_ref: dict[str, str]) -> dict[str, object]: ...
def resolve_requested_profile(*, context: dict[str, object], registration_ref: dict[str, str] | None, manifest_ref: dict[str, str] | None, provider_id: str, profile_id: str) -> dict[str, object]: ...

# projections.py
def project_ocr_result(*, store: UEIObjectStore, request_ref: dict[str, str], registration_ref: dict[str, str] | None, manifest_ref: dict[str, str] | None, provider_id: str, profile_id: str, fixture: OCRResult | dict[str, object], fixture_binding: dict[str, object], transform_ref: dict[str, str] | None = None) -> dict[str, object]: ...
def project_uia_snapshot(*, store: UEIObjectStore, request_ref: dict[str, str], registration_ref: dict[str, str] | None, manifest_ref: dict[str, str] | None, provider_id: str, profile_id: str, fixture: dict[str, object], fixture_binding: dict[str, object], transform_ref: dict[str, str] | None = None) -> dict[str, object]: ...
def project_screen_parser_result(*, store: UEIObjectStore, request_ref: dict[str, str], registration_ref: dict[str, str] | None, manifest_ref: dict[str, str] | None, provider_id: str, profile_id: str, fixture: dict[str, object], fixture_binding: dict[str, object], transform_ref: dict[str, str] | None = None) -> dict[str, object]: ...
def project_capture_bbox(*, source_bbox: list[int | float], source_coordinate_space: str, binding: dict[str, object], request_artifact_sha256: str, request_image_size: dict[str, int], transform: dict[str, object] | None) -> tuple[list[int] | None, dict[str, str] | None, bool]: ...
def make_source_item(*, provider_id: str, profile_id: str, capture_lineage_ref: dict[str, str], source_index: int, source_item_id: str | None, source_id_origin: str, kind: str, safe_text: str | None, safe_role: str | None, safe_states: list[str], source_bbox: list[int] | None, source_coordinate_space: str, capture_bbox: list[int] | None, coordinate_transform_ref: dict[str, str] | None, opaque_attributes: dict[str, object], provider_confidence: float | None) -> dict[str, object]: ...

# tests/uei_v1_helpers.py
@dataclass(frozen=True)
class UEITestContext:
    store: UEIObjectStore
    case: str
    request_ref: dict[str, str]
    registration_ref: dict[str, str] | None
    manifest_ref: dict[str, str] | None
    provider_id: str
    profile_id: str
    fixture_binding: dict[str, object]
    transform_ref: dict[str, str] | None
    def for_case(self, case: str) -> dict[str, object]:
        if case != self.case:
            raise ValueError(f"context is bound to {self.case}, not {case}")
        return {"store": self.store, "request_ref": self.request_ref,
                "registration_ref": self.registration_ref, "manifest_ref": self.manifest_ref,
                "provider_id": self.provider_id, "profile_id": self.profile_id,
                "fixture_binding": self.fixture_binding, "transform_ref": self.transform_ref}
def build_context_from_sidecar(tmp_path: Path, case: str) -> UEITestContext:
    """Load `static-projection-sidecar-v1.json`, seal/store its objects in tmp_path, and return one case-bound context."""
def project_case(context: UEITestContext) -> dict[str, object]:
    """Dispatch `ocr`, `uia`, or `screen-parser` to its project_* function with load_fixture(context.case)."""
def load_expected(case: str) -> dict[str, object]:
    """Return the UTF-8 JSON object at expected-safe-results/{case}.json."""
from app.learn.recognition.uei.canonical import deterministic_error_id, deterministic_result_id

```

`canonical.py` owns `deterministic_result_id` and `deterministic_error_id`; `tests/uei_v1_helpers.py` directly imports those production functions rather than defining aliases. Do not alter `app/learn/recognition/__init__.py` or add import-wiring tests. `project_*` uses the result ID and its post-precondition failure writer uses the error ID before creating the dependent failed-result ID. It returns the stored, sealed safe-result object. It raises only `UEIOuterBoundaryError` before preconditions; after preconditions it returns `status="success"` or the stored `status="failed"` result and never leaks an implementation exception.

### Task 1: Add the eight strict schema sources and schema conformance tests

**Files:**
- Create: all eight `schemas/uei/v1/*.schema.json` files in the File Map.
- Create: `app/learn/recognition/uei/contracts.py`
- Create: `tests/uei_v1_helpers.py`
- Create: `tests/test_uei_v1_schemas.py`

**Interfaces:** `contracts.py` declares `UEI_CONTRACTS = ("trusted_provider_registration_v1", "artifact_ref_v1", "capture_lineage_v1", "affine_coordinate_transform_v1", "provider_manifest_v1", "screen_parse_request_v1", "provider_safe_result_v1", "provider_error_v1")`; consumes JSON dictionaries and produces `validate_contract(value, contract_version)` input contracts for later tasks.

- [ ] **Step 1: Write the failing schema inventory and rejection tests.**

```python
def test_all_eight_uei_schemas_load_and_reject_unknown_nested_fields():
    from app.learn.recognition.uei.contracts import load_contract_schema, validate_contract
    assert set(load_contract_schema(name)["title"] for name in UEI_CONTRACTS) == set(UEI_CONTRACTS)
    value = minimal_provider_safe_result()
    value["items"][0]["x_extension"] = True
    with pytest.raises(UEIValidationError, match="additionalProperties"):
        validate_contract(value, contract_version="provider_safe_result_v1")
```

At the top of `tests/uei_v1_helpers.py`, define `minimal_provider_safe_result() -> dict[str, object]`, `load_fixture(name: str) -> dict[str, object]`, and immutable `UEITestContext` plus its exact functions declared above; each returns only synthetic data and no mutable global state. Parameterize legal minima, wrong version/enum, required `null`, duplicate profile tuples, uppercase/non-hex/short SHA values, `captured_at` offsets lacking `Z`, and impossible dates; assert the schemas reject each through the exact lowercase SHA `pattern` and the application RFC3339-UTC validator.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_uei_v1_schemas.py -q`<br>
Expected: FAIL because `app.learn.recognition.uei.contracts` and schema files do not exist.

- [ ] **Step 3: Create the schemas and strict loader.**

Give every object explicit `required`, `type`, bounds, closed enum, `maxLength`, `maxItems`, and `additionalProperties: false`; the lowercase SHA definition is `{"type":"string","pattern":"^[0-9a-f]{64}$"}`. Put local `$defs` for SHA, immutable reference, size, bbox, and bounded JSON shapes inside each of the eight documents rather than adding a ninth contract file. In `contracts.py`, load schemas from `Path(__file__).resolve().parents[4] / "schemas" / "uei" / "v1"`, parse UTF-8 JSON, and recursively evaluate only the keywords used here: `type`, `required`, `properties`, `additionalProperties`, `minProperties`, `maxProperties`, `const`, `enum`, `oneOf`, `items`, `uniqueItems`, `minItems`, `maxItems`, `minLength`, `maxLength`, `pattern`, `minimum`, `maximum`, `if`, `then`, `else`, and local `$ref`. Do not use `anyOf`, dependent keywords, or other schema keywords; cross-object ref resolution, hash verification, and payload byte/depth semantics remain explicit application validation. In `capture_lineage_v1.schema.json`, define `captured_at` with `"format":"date-time"` and `"pattern":"Z$"`; `validate_contract` must additionally parse it with `datetime.fromisoformat`, require UTC offset exactly zero, and reject all non-RFC3339 forms rather than treating `format` as advisory.

- [ ] **Step 4: Run GREEN.**

Run: `uv run pytest tests/test_uei_v1_schemas.py -q`<br>
Expected: PASS, including all eight load checks and strict nested-field rejection cases.

### Task 2: Add independently tested in-house JCS hashing

**Files:**
- Create: `app/learn/recognition/uei/canonical.py`
- Create: `tests/test_uei_v1_canonical.py`

**Interfaces:** Produces `canonical_json_bytes`, `content_sha256`, `seal_immutable`, and `immutable_ref` exactly as declared above.

- [ ] **Step 1: Write failing JCS, hash, and immutable-reference tests.**

```python
def test_jcs_hash_uses_utf8_and_excludes_only_self_hash(tmp_path: Path):
    value = {"contract_version": "artifact_ref_v1", "artifact_id": "artifact/x", "artifact_sha256": "a" * 64, "media_type": "image/png", "byte_length": 1}
    sealed = seal_immutable(value)
    assert sealed["content_sha256"] == content_sha256(sealed)
    assert canonical_json_bytes({"é": 1, "a": 2}) == b'{"a":2,"\xc3\xa9":1}'
    assert content_sha256({**sealed, "content_sha256": "f" * 64}) == sealed["content_sha256"]
    assert content_sha256({**sealed, "byte_length": 2}) != sealed["content_sha256"]
```

Create `rfc8785-appendix-b-vectors.json` with this exact complete literal table: `0000000000000000/0`, `8000000000000000/0`, `0000000000000001/5e-324`, `8000000000000001/-5e-324`, `7fefffffffffffff/1.7976931348623157e+308`, `ffefffffffffffff/-1.7976931348623157e+308`, `4340000000000000/9007199254740992`, `c340000000000000/-9007199254740992`, `4430000000000000/295147905179352830000`, `c430000000000000/-295147905179352830000`, `44b52d02c7e14af5/9.999999999999997e+22`, `44b52d02c7e14af6/1e+23`, `44b52d02c7e14af7/1.0000000000000001e+23`, `444b1ae4d6e2ef4e/999999999999999700000`, `444b1ae4d6e2ef4f/999999999999999900000`, `444b1ae4d6e2ef50/1e+21`, `3eb0c6f7a0b5ed8c/9.999999999999997e-7`, `3eb0c6f7a0b5ed8d/0.000001`, `41b3de4355555553/333333333.3333332`, `41b3de4355555554/333333333.33333325`, `41b3de4355555555/333333333.3333333`, `41b3de4355555556/333333333.3333334`, `41b3de4355555557/333333333.33333343`, `becbf647612f3696/-0.0000033333333333333333`, and `43143ff3c1cb0959/1424953923781206.2`. The test reconstructs each float via `struct.unpack(">d", bytes.fromhex(bits))`, compares lexical output, and fails the serializer if any vector differs. Also test UTF-16 property ordering, escaped controls, supplementary Unicode, nonfinite/surrogate rejection, and immutable-reference shape.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_uei_v1_canonical.py -q`<br>
Expected: FAIL with missing UEI canonical imports.

- [ ] **Step 3: Add the in-house RFC 8785 serializer.**

`json.dumps(sort_keys=True)` is not RFC 8785-safe for UTF-16 key order and ECMAScript number formatting, and the checked environment has no `jsonschema`, `rfc8785`, or `jcs` module. Implement JCS in-house using only `math`, `struct`, `hashlib`, `decimal`, and UTF-8 string handling: reject non-JSON values, NaN, infinity, and lone UTF-16 surrogates; sort object keys by UTF-16 code units; escape only JCS-required control/quote/backslash characters; emit `null/true/false`; and accept finite IEEE-754 binary64 values plus integers exactly representable as binary64. For a float, start from CPython 3.11 `repr(value)` (shortest round-trip), reject if parsing that text does not round-trip to the original `struct.pack(">d", value)`, normalize `-0.0` to `0`, remove a trailing `.0` only where the result is integral, expand the mantissa to plain decimal for `1e-6 <= abs(value) < 1e21`, otherwise preserve scientific notation, remove exponent leading zeros, and require explicit `+` only for positive exponents. The full checked-in vector table is the compatibility gate: any mismatch raises `UEIValidationError("jcs_binary64_unsupported")` rather than emitting a non-JCS hash. Reject larger integer literals instead of silently rounding. Embed RFC 8785 Appendix B number vectors in `tests/test_uei_v1_canonical.py`, including the expected lexical output and hash tests. `canonical.py` removes exactly the top-level `content_sha256`, canonicalizes UTF-8, SHA-256 hashes lowercase hex, deep-copies before sealing, and makes a ref from the specified stable ID field.

- [ ] **Step 4: Run GREEN.**

Run: `uv run pytest tests/test_uei_v1_canonical.py -q`<br>
Expected: PASS with no dependency or network access.

### Task 3: Add independently tested immutable storage

**Files:**
- Create: `app/learn/recognition/uei/store.py`
- Create: `tests/test_uei_v1_store.py`

**Interfaces:** Consumes sealed objects through `UEIObjectStore.put(value)` and produces verified immutable refs; `write_order` is a tuple snapshot recorded per instance, never shared globally.

- [ ] **Step 1: Write the failing store tests.**

```python
def test_store_rejects_tampered_bytes_hash_and_id(tmp_path: Path):
    store = UEIObjectStore(root=tmp_path / "objects")
    ref = store.put(seal_immutable(minimal_artifact_ref()))
    assert store.get(ref, contract_version="artifact_ref_v1")["artifact_id"] == ref["id"]
    assert store.write_order == ("artifact_ref_v1",)
```

Add tests that tamper canonical bytes, hash, reference ID, and contract version; assert no replacement occurs for the same digest with different bytes.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_uei_v1_store.py -q`<br>
Expected: FAIL because `UEIObjectStore` does not exist.

- [ ] **Step 3: Implement append-only storage.**

`put` validates and seals a deep copy before atomically creating `objects/<content_sha256>.json`; an existing path must match exact canonical bytes. `get` validates the two-field immutable ref, reads UTF-8 bytes, recomputes its self hash, validates the requested contract, and verifies the object stable ID equals `ref["id"]`. Keep `write_order` as an instance tuple appended only after a successful write.

- [ ] **Step 4: Run GREEN.**

Run: `uv run pytest tests/test_uei_v1_store.py -q`<br>
Expected: PASS.

### Task 4: Enforce request/capture preconditions and capability intersection

**Files:**
- Create: `app/learn/recognition/uei/registry.py`
- Modify: `app/learn/recognition/uei/contracts.py`
- Create: `tests/test_uei_v1_registry.py`

**Interfaces:** Consumes sealed artifact, capture lineage, request, registration, and manifest objects from `UEIObjectStore`; produces resolved context or `UEIOuterBoundaryError`/a post-precondition resolution record.

- [ ] **Step 1: Write failing boundary and intersection tests.**

```python
def test_invalid_request_ref_is_outer_error_and_writes_no_projection_objects(store):
    with pytest.raises(UEIOuterBoundaryError, match="request_ref"):
        resolve_projection_context(store=store, request_ref={"id": "request/x", "content_sha256": "0" * 64})
    assert store.object_count(contract_version="provider_error_v1") == 0
    assert store.object_count(contract_version="provider_safe_result_v1") == 0
```

Cover invalid/unhashable request, missing lineage, unresolved artifact, artifact-SHA mismatch, unregistered provider, absent manifest profile, disabled registration, invalid profile/mode/privacy, `remote_allowed`, mismatched conformance suite, and payload policy. Assert all post-precondition resolution records carry requested IDs, both resolution enums, and provenance refs exactly when resolved.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_uei_v1_registry.py -q`<br>
Expected: FAIL because no context resolver exists.

- [ ] **Step 3: Implement the two-stage resolver.**

`resolve_projection_context` reads the sealed request, lineage, and artifact in that order and verifies ref IDs/hashes, lineage artifact SHA, and image dimensions before returning; it never catches an outer error. `resolve_requested_profile` resolves registration then manifest and enforces registration ∩ manifest ∩ selected request profile, mode, privacy, restricted-only wire policy, local Milestone-1 egress, limits, and required suite. It returns explicit `resolved/not_found/invalid/not_reached` facts rather than inventing references.

- [ ] **Step 4: Run GREEN.**

Run: `uv run pytest tests/test_uei_v1_registry.py -q`<br>
Expected: PASS; no test writes a provider error/result before a valid request/capture context exists.

### Task 5: Implement coordinate proof and safe-item primitives

**Files:**
- Create: `app/learn/recognition/uei/projections.py`
- Create: `tests/test_uei_v1_coordinates.py`

**Interfaces:** Produces the exact `project_capture_bbox` and `make_source_item` signatures declared in the public-interface section; the helper returns a capture bbox only, while `make_source_item` retains the separately validated source bbox.

- [ ] **Step 1: Write failing coordinate and ID tests.**

```python
def test_missing_transform_retains_source_bbox_but_has_no_capture_bbox():
    capture_bbox, transform_ref, review_only = project_capture_bbox(source_bbox=[1, 2, 8, 9], source_coordinate_space="image_pixel_xyxy", binding={"artifact_sha256": "a" * 64, "image_size": {"width": 10, "height": 10}}, request_artifact_sha256="a" * 64, request_image_size={"width": 10, "height": 10}, transform=None)
    item = make_source_item(provider_id="local.acme.vision/ocr", profile_id="local.acme.vision/ocr/latin-desktop", capture_lineage_ref={"id": "capture/test", "content_sha256": "a" * 64}, source_index=0, source_item_id=None, source_id_origin="uei_deterministic_projection", kind="text", safe_text="Label", safe_role=None, safe_states=[], source_bbox=[1, 2, 8, 9], source_coordinate_space="image_pixel_xyxy", capture_bbox=capture_bbox, coordinate_transform_ref=transform_ref, opaque_attributes={}, provider_confidence=None)
    assert (capture_bbox, transform_ref, review_only) == (None, None, True)
    assert item["source_bbox"] == [1, 2, 8, 9] and item["capture_bbox"] is None

def test_identity_projection_requires_exact_capture_binding():
    assert project_capture_bbox(source_bbox=[1, 2, 8, 9], source_coordinate_space="capture_pixel_xyxy", binding={"artifact_sha256": "a" * 64, "image_size": {"width": 10, "height": 10}}, request_artifact_sha256="a" * 64, request_image_size={"width": 10, "height": 10}, transform=None) == ([1, 2, 8, 9], None, False)
```

Test outward, nearest-half-away-from-zero, and none rounding; clipping; all coordinate spaces; finite/bounds checks; wrong transform hashes/dimensions; false identity proof; missing transform success; and deterministic OCR IDs changing when only the zero-based source index changes.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_uei_v1_coordinates.py -q`<br>
Expected: FAIL with missing projection helpers.

- [ ] **Step 3: Implement coordinate and item rules.**

Use half-open xyxy boxes. Require transform source/target artifact hashes to equal each other and request artifact SHA; require declared source/target sizes and transformed bounds. Apply outward `floor/floor/ceil/ceil`, nearest half-away-from-zero per edge, and `none` only for integer edges. Return `(None, None, True)` for missing or unproven non-conflicting transforms; `make_source_item` retains the validated `source_bbox` separately; a supplied bad transform raises `UEIProjectionFailure(code="coordinate_invalid", stage="coordinate")`. Generate an ID-less source ID from the exact JCS record required by the spec and preserve available provider IDs unchanged.

- [ ] **Step 4: Run GREEN.**

Run: `uv run pytest tests/test_uei_v1_coordinates.py -q`<br>
Expected: PASS.

### Task 6: Add three pure static adapters and their sidecar fixtures

**Files:**
- Create: `app/learn/recognition/uei/__init__.py`
- Modify: `app/learn/recognition/uei/projections.py`
- Create: all `tests/fixtures/uei-v1/` files in the File Map.
- Create: `tests/test_uei_v1_projections.py`

**Interfaces:** Consumes `OCRResult` from `modules.ocr.contracts`, the current `WindowsUIAProvider.snapshot_window` dictionary shape, and the current `screen_parser_result_v1` dictionary shape. Produces sealed provider-safe results only.

- [ ] **Step 1: Write failing adapter tests using synthetic static fixtures.**

```python
def test_ocr_projection_generates_jcs_source_id_without_mutating_fixture(context):
    fixture = load_fixture("ocr-result-static.json")
    before = copy.deepcopy(fixture)
    result = project_ocr_result(**context.for_case("ocr"), fixture=fixture)
    assert result["status"] == "success"
    assert result["items"][0]["source_id_origin"] == "uei_deterministic_projection"
    assert result["items"][0]["source_item_id"].startswith("sha256:")
    assert fixture == before
```

For UIA, assert `control_id` is preserved; convert its relative `bbox={x,y,w,h}` to `[x,y,x+w,y+h]` and label it `window_outer_pixel_xyxy` because `snapshot_window` derives it from `BoundWindow.rect`/GetWindowRect. Assert `screen_bbox` is absent from every durable item and is counted as one dropped/redacted field per control; never relabel it as client space. For OmniParser, assert every emitted item has `provider_confidence is None`; preserve `element_id`, map its valid xyxy box, set `provider_confidence` to `null` because `screen_parser_result_v1` has no provider-confidence field, reject unsafe provenance/raw fields, and assert no result or error contains `action`, `click_point`, `wire_payload`, `image_path`, `artifact_is_authorization`, or `execute_binding_enabled`.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_uei_v1_projections.py -q`<br>
Expected: FAIL because `project_ocr_result`, `project_uia_snapshot`, and `project_screen_parser_result` do not exist.

- [ ] **Step 3: Implement field-whitelist adapters.**

Convert `OCRTextMatch.bbox` from `x,y,width,height` to xyxy; preserve only match text and score. Convert UIA controls only from `control_id,name,control_type,automation_id,class_name,bbox,enabled,visible,patterns`; convert relative outer-window `bbox` to xyxy and drop `screen_bbox`, window handle/title/process, and any screen-space coordinate. Increment `redaction_summary.redacted_field_count` for every dropped `screen_bbox`; never retain it through `opaque_attributes`. Convert OmniParser only from successful element fields defined by its current contract and always emit `provider_confidence: null`. Each adapter selects the exact request pair, validates the intersection before fixture conversion, builds safe items, seals/stores the result, and makes no provider call.

- [ ] **Step 4: Run GREEN.**

Run: `uv run pytest tests/test_uei_v1_projections.py -q`<br>
Expected: PASS for all three static adapters.

### Task 7: Centralize privacy, payload, fixture, and failed-result behavior

**Files:**
- Modify: `app/learn/recognition/uei/contracts.py`
- Modify: `app/learn/recognition/uei/projections.py`
- Create: `tests/test_uei_v1_fail_closed.py`

**Interfaces:** Produces `store_post_precondition_failure(*, context: dict[str, object], stage: str, code: str, reason_class: str) -> dict[str, object]`, which uses the deterministic IDs above and stores `provider_error_v1` before its failed `provider_safe_result_v1`.

- [ ] **Step 1: Write failing fail-closed tests.**

```python
def test_post_precondition_payload_failure_stores_error_before_failed_result(context):
    result = project_uia_snapshot(**context.for_case("uia"), fixture=oversized_opaque_fixture())
    assert result["status"] == "failed" and result["items"] == [] and result["review_only"] is True
    error = context.store.get(result["error_ref"], contract_version="provider_error_v1")
    assert error["code"] == "payload_limit_exceeded"
    assert context.store.write_order[-2:] == ("provider_error_v1", "provider_safe_result_v1")
    assert result["result_id"] == deterministic_result_id(request_ref=context.request_ref, provider_id=context.provider_id, profile_id=context.profile_id, fixture_kind="uia")
    assert error["error_id"] == deterministic_error_id(request_ref=context.request_ref, provider_id=context.provider_id, profile_id=context.profile_id, stage="redaction", code="payload_limit_exceeded")
```

Cover `wire_payload`/`raw_payload` rejection; a parameterized redaction case for Bearer, Basic, API-key, password, token, session, cookie, JWT, PEM private key, Windows user path, email, and phone values; recursive bytes/depth/array/object/string limit overflow; unknown fixture field; duplicate/lost source ID; invalid projected schema; and each supplied bad-coordinate case. For every redaction case, assert the original value is absent from JSON of both persisted objects and its category/count is present only in `redaction_summary`. Assert `safe_details` contains only `reason_class` and `redaction_summary` has counts/boolean/category IDs only.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_uei_v1_fail_closed.py -q`<br>
Expected: FAIL because post-precondition errors currently escape or lack a safe-result reference.

- [ ] **Step 3: Implement deterministic redaction and terminal failure writer.**

Redact only explicit secret-bearing string patterns before payload validation: Bearer credentials, `Basic <base64>`, `api_key=`/`api-key=`, `password=`, `token=`, `session=`, `cookie=`, JWT-like three-part tokens, PEM private-key markers, Windows user paths, email addresses, and phone numbers. Replace the field with `null`, count the item/field, and record exactly one category identifier from `credential`, `private_key`, `personal_path`, or `personal_data`. Any wire-payload key fails `wire_payload_forbidden`; malformed fixture/value failures map to `provider_fixture_schema_invalid` or `fixture_invalid`. Catch only `UEIProjectionFailure` after context resolution, build/seal/store the closed error, then build/seal/store the failed result that copies requested IDs/resolutions and includes resolved refs only.

- [ ] **Step 4: Run GREEN.**

Run: `uv run pytest tests/test_uei_v1_fail_closed.py -q`<br>
Expected: PASS with no raw sensitive string, action field, or invented authorization field in stored objects or assertion output.

### Task 8: Prove complete offline static conformance

**Files:**
- Create: `tests/test_uei_v1_static_conformance.py`
- Modify: expected result fixtures only when test-derived canonical projections differ from approved safe static data.

**Interfaces:** Consumes the sidecar and three fixture inputs. Produces a test-only conformance report dictionary; no application API or runtime artifact.

- [ ] **Step 1: Write the failing three-case golden test.**

```python
@pytest.mark.parametrize("case", ["ocr", "uia", "screen-parser"])
def test_static_sidecar_case_matches_safe_projection(case: str, tmp_path: Path):
    context = build_context_from_sidecar(tmp_path, case)
    actual = project_case(context)
    expected = seal_immutable(load_expected(case))
    assert actual == expected
    assert "artifact_is_authorization" not in actual
    assert "execute_binding_enabled" not in actual
```

Add a parameterized disabled-rollout case and mode-change check proving confidence, trust, score, and authorization are absent or unchanged.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_uei_v1_static_conformance.py -q`<br>
Expected: FAIL until the sidecar, adapters, and expected projections agree.

- [ ] **Step 3: Finalize only synthetic sidecar/golden values.**

Make the sidecar declare every fixture binding's capture artifact SHA and image size; set rollout metadata to `Disabled`; keep all fixture data synthetic and public. Do not add provider invocation, runtime registration, migration reader, panel visibility, or feature-flag consumer.

- [ ] **Step 4: Run GREEN.**

Run: `uv run pytest tests/test_uei_v1_static_conformance.py -q`<br>
Expected: PASS for OCR, UIA, and OmniParser static inputs.

### Task 9: Synchronize behavior documentation without claiming runtime integration

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:** Documents the tested public boundary only; no code interface changes.

- [ ] **Step 1: Write failing documentation assertions.**

```python
def test_docs_describe_uei_as_offline_and_non_authorizing():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "Universal Evidence Interface v1" in text
    assert "offline static fixture" in text
    assert "does not authorize actions" in text
```

Add matching architecture assertions for trusted intersection, JCS immutable refs, and explicit absence of provider/panel/action integration.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_uei_v1_static_conformance.py::test_docs_describe_uei_as_offline_and_non_authorizing -q`<br>
Expected: FAIL because the UEI documentation text is absent.

- [ ] **Step 3: Update the four documents.**

State exactly that eight schemas, an offline static sidecar, and pure non-authorizing projections now exist; state that runtime providers, capture, network, GUI, panel, grounding, replay, actions, migrations, and remote egress are not connected. In local state/next-step documents, identify a separately approved future integration as required before enablement.

- [ ] **Step 4: Run GREEN.**

Run: `uv run pytest tests/test_uei_v1_static_conformance.py::test_docs_describe_uei_as_offline_and_non_authorizing -q`<br>
Expected: PASS.

### Task 10: Run acceptance verification and a pre-commit privacy gate

**Files:**
- Verify only all files created or modified above.

- [ ] **Step 1: Run the complete UEI suite.**

Run: `uv run pytest tests/test_uei_v1_schemas.py tests/test_uei_v1_canonical.py tests/test_uei_v1_store.py tests/test_uei_v1_registry.py tests/test_uei_v1_coordinates.py tests/test_uei_v1_projections.py tests/test_uei_v1_fail_closed.py tests/test_uei_v1_static_conformance.py -q`<br>
Expected: PASS.

- [ ] **Step 2: Run narrow import/syntax checks.**

Run: `uv run python -m py_compile app/learn/recognition/uei/__init__.py app/learn/recognition/uei/canonical.py app/learn/recognition/uei/contracts.py app/learn/recognition/uei/store.py app/learn/recognition/uei/registry.py app/learn/recognition/uei/projections.py`<br>
Expected: PASS.

- [ ] **Step 3: Run UTF-8, replacement-character, schema-path, and plan-completeness checks.**

Run:
```powershell
uv run python -c "from pathlib import Path; paths=[Path('docs/superpowers/plans/2026-08-21-universal-evidence-interface.md'),Path('README.md'),Path('ARCHITECTURE.md'),Path('CURRENT_STATE.md'),Path('NEXT_STEPS.md'),*Path('schemas/uei/v1').glob('*.json'),*Path('tests/fixtures/uei-v1').rglob('*.json'),*Path('app/learn/recognition/uei').glob('*.py'),*Path('tests').glob('uei_v1_helpers.py'),*Path('tests').glob('test_uei_v1_*.py')]; [(_ for _ in ()).throw(AssertionError(path)) for path in paths if chr(0xfffd) in path.read_text(encoding='utf-8')]; assert len(list(Path('schemas/uei/v1').glob('*.schema.json'))) == 8"
git diff --check
```
Expected: all assertions pass and `git diff --check` emits no whitespace errors.

- [ ] **Step 4: Perform the privacy gate before any future commit; do not push.**

Run:
```powershell
rg -n -i --glob '!docs/superpowers/plans/2026-08-21-universal-evidence-interface.md' 'authorization:|bearer |basic |api[_-]?key|password=|token=|cookie=|session=|BEGIN [A-Z ]*PRIVATE KEY|[A-Za-z]:\\Users\\|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|image_path|raw_payload|wire_payload' schemas/uei/v1 tests/fixtures/uei-v1 app/learn/recognition/uei tests/test_uei_v1_*.py README.md ARCHITECTURE.md CURRENT_STATE.md NEXT_STEPS.md
```
Expected: no secret, personal path, raw payload, or wire payload is present; allowed code identifiers in explicit rejection tests must be reviewed as literals that prove non-persistence only. Do not run `git push`.

## Self-Review

- **Spec coverage:** Task 1 implements eight schemas and strict contract validation. Task 2 implements in-house JCS/hash/ref rules with Appendix B vectors; Task 3 implements storage. Task 4 proves outer preconditions and trusted intersection. Task 5 covers identity/affine coordinates and deterministic IDs. Tasks 6–8 cover all three static projections, policy/privacy/payload failures, error-before-result ordering, no side effects, and disabled rollout. Task 9 synchronizes documentation. Task 10 verifies acceptance and privacy.
- **No-scope audit:** The plan creates no runtime/provider/network/panel/grounding/action integration, no dependency entry, and no migration reader.
- **Interface consistency:** `canonical.py` owns all deterministic IDs; the immutable helper context imports them directly. `make_source_item` receives all deterministic source-ID fields, retains source geometry separately, and never derives a source ID from mutable state. Every later task uses the declared `UEIObjectStore`, resolver, and `project_*` signatures; failed outputs contain the error reference and outer errors never produce either projection object. UIA durable items use only relative outer-window geometry and never retain `screen_bbox`.
- **Plan text scan:** Before execution, run `uv run python -c "from pathlib import Path; text=Path('docs/superpowers/plans/2026-08-21-universal-evidence-interface.md').read_text(encoding='utf-8'); banned=[''.join(('T','BD')),''.join(('TO','DO')),'implement'+' later','fill in '+'details']; assert not [word for word in banned if word.lower() in text.lower()]"`; expected output is empty.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-21-universal-evidence-interface.md`. Execute it either with fresh task-by-task workers using `superpowers:subagent-driven-development`, or inline with `superpowers:executing-plans`; both paths must preserve the TDD checks and the no-runtime-integration boundary above.
