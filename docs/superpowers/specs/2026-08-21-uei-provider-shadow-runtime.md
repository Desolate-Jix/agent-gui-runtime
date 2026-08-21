# UEI Provider Shadow Runtime M2 Design

## Status and intent

This design is the next vertical slice after Universal Evidence Interface v1 Milestone 1. It adds a provider-agnostic runtime boundary, uses the existing local OmniParser installation as the first real provider, and makes the sealed result reviewable in the Learning Draft panel.

The slice is deliberately Shadow-only. It does not authorize clicks, create action candidates, perform grounding, call the gated action API, or enable Execute.

## Goals

1. Define one generic local provider adapter protocol that can later support another local model or a policy-approved remote API without changing the learning or panel contracts.
2. Resolve the exact stored UEI request, capture lineage, artifact, registration, and manifest before any provider starts.
3. Run the first real provider through a controlled, local-only worker boundary with explicit timeout, output, resource, and cleanup limits.
4. Persist one immutable runtime receipt plus the existing `provider_error_v1 -> provider_safe_result_v1` terminal pair or a successful `provider_safe_result_v1`.
5. Project only a compact, revalidated, display-only summary into Learning Draft review.
6. Prove real offline OmniParser execution, fail-closed behavior, performance measurements, privacy, and non-authorization.

## Non-goals

- No Primary, Assist, or Advisory provider execution.
- No remote egress in M2.
- No public request may supply an image path, command, raw payload, bbox, click point, provider identity, or runtime options.
- No live desktop capture, GUI input, grounding, replay, PathGraph promotion, or action execution.
- No reuse of Qwen, VISTA, or unrelated model processes.
- No migration of historical learning artifacts.
- No change to the frozen meaning of existing UEI v1 safe-result or error fields.

## Architecture

### 1. Trusted invocation service

`ShadowProviderRuntime` is an internal service. Its input is an immutable request reference plus a server-owned `RestrictedCaptureLease`. The lease contains the resolved capture and artifact references, a local path usable only inside the worker boundary, the verified artifact SHA-256, image size, and a unique capture identity.

Before dispatch, the service re-runs the existing UEI outer preconditions and trusted registration/manifest/request intersection. It permits only:

- request profile mode `Shadow`;
- registration enabled;
- registration egress policy `local_only`;
- a namespaced provider/profile pair present in the trusted in-process adapter registry;
- exact request/capture/artifact/ref/hash/size agreement.

The service never trusts provider identity, profile identity, capture identity, or path returned by a worker.

### 2. Generic adapter protocol

The internal protocol is:

```python
class ScreenParseProviderAdapter(Protocol):
    provider_id: str
    profile_id: str
    provider_version: str

    def invoke(
        self,
        *,
        capture: RestrictedCaptureLease,
        budget: ProviderRunBudget,
        invocation_id: str,
    ) -> NormalizedScreenParseOutput: ...
```

`ProviderRunBudget` contains a timeout, maximum output bytes, maximum element count, maximum string length, and resource group. `NormalizedScreenParseOutput` contains only source-space items, bounded timing/resource aggregates, and safe provenance identifiers. It cannot contain a filesystem path, raw stdout/stderr, raw wire data, credentials, commands, or authorization fields.

Adapters are selected only from a trusted static registry. There is no dynamic import path or client-controlled command template.

### 3. Process and resource boundary

The OmniParser implementation uses a fresh controlled worker process for each invocation. The adapter owns:

- fixed interpreter, code, weight, and cache paths from trusted local configuration;
- offline environment variables;
- a `gpu_vision` resource lease acquired before spawn;
- process-group termination on timeout, cancellation, malformed output, or failure;
- a restricted temporary directory for one input/output exchange;
- output byte and element limits before JSON normalization;
- cleanup and process-exit verification before returning.

The worker receives only a server-verified capture lease and fixed trusted configuration. It must not inherit arbitrary provider options from an API or panel request.

### 4. Immutable runtime receipt

Add `provider_runtime_receipt_v1`. It records only:

- immutable request and capture-lineage references;
- namespaced provider/profile identifiers and `Shadow` mode;
- invocation status: `succeeded`, `failed`, or `rejected`;
- bounded reason class;
- retryable boolean;
- duration/resource aggregates;
- resulting safe-result reference and optional error reference;
- cleanup status.

The receipt contains no local path, raw exception, worker output, bbox, text content, token, cookie, command, or environment dump.

Provider/runtime failures do not expand the frozen UEI v1 error taxonomy. The existing failed result remains `projection_failed`; the receipt carries a closed runtime reason class such as `runtime_timeout`, `runtime_resource_rejected`, `runtime_worker_invalid`, `runtime_provider_failed`, or `runtime_cleanup_failed`.

### 5. Safe-result persistence

On success, the runtime converts normalized provider items directly into the existing generic `provider_safe_result_v1` item boundary and seals it in the UEI store. On a post-precondition failure it persists `provider_error_v1` first, then a failed `provider_safe_result_v1`, then the runtime receipt.

The service is idempotent by deterministic invocation identity. Repeating a completed invocation returns verified stored refs and does not run the provider again. An in-progress or uncertain execution never starts a second worker for the same invocation identity.

### 6. Learning and panel projection

The runtime result enters learning only by immutable ref:

```json
{
  "uei_shadow_result_ref": {
    "id": "...",
    "content_sha256": "..."
  }
}
```

The Learning Draft boundary loads the result from a fixed server-owned UEI shadow store, validates `provider_safe_result_v1`, loads its capture lineage, and derives `uei_shadow_provider_summary_v1`. Trial JSON may cache the ref but cannot be the authority for the summary.

The summary exposes only status, provider/profile/version, item count, registration/manifest resolution, capture comparison, redaction aggregates, safe failure stage/code, and immutable result identity. It always includes:

- `display_only=true`;
- `review_only=true`;
- `execution_authorized=false`;
- `artifact_is_authorization=false`;
- `execute_binding_enabled=false`;
- `action_candidates=[]`.

The panel displays this summary inside the existing Learning Draft provider card. It does not display items, text, bboxes, source IDs, transforms, opaque attributes, raw provider output, or complete internal refs. Changing or failing to load a draft clears the panel summary. Reload always revalidates the immutable ref; a cached summary is never a fallback.

## Failure behavior

- Invalid request/capture/artifact preconditions: structured outer rejection, no provider start, no UEI runtime object.
- Disabled/unregistered/non-Shadow/non-local profile: rejected receipt, no provider start.
- Resource preflight failure: rejected receipt, no provider start.
- Timeout/cancel/process failure: terminate process group, verify cleanup, persist failed pair and receipt.
- Malformed, oversized, secret-bearing, or lineage-conflicting output: no success items; persist failed pair and receipt.
- Missing/corrupt result ref on draft load: display `invalid` or `unavailable`, discard cached summary, expose no items/actions.
- Capture mismatch at review time: historical display remains review-only with `capture_match_status=mismatch`; no action or grounding projection.

## Performance evidence

The real smoke records cold duration, at least three warm durations, P50/P95, peak GPU memory when available, element count, invalid item count, and cleanup state. These metrics belong to the receipt/report, not to action authorization. No latency SLO is introduced in M2; the result establishes a reproducible baseline.

## Security and privacy acceptance

1. The provider cannot start unless the exact stored request/capture/artifact and trusted profile intersection pass.
2. No public panel/API payload accepts a path, command, bbox, click point, raw provider payload, or runtime policy override.
3. Persisted UEI objects, receipt, learning draft, panel response, logs, and reports contain no user path, credential, raw stdout/stderr, raw exception, or raw provider wire payload.
4. Every successful or failed result is review-only and non-authorizing; no result item becomes an action candidate or grounding candidate.
5. Timeout, cancellation, and failure leave no provider worker, resource lease, or restricted temporary directory behind.
6. The existing clean import of `app.learn.recognition.uei` still loads no provider/runtime/model dependency.

## Verification matrix

- Pure protocol tests with a deterministic fake adapter.
- Stored-context identity, Shadow mode, registration, egress, and capture-lineage negatives.
- Worker timeout, cancellation, malformed output, secret output, size limit, and cleanup tests.
- Runtime receipt schema/hash/idempotence tests.
- Safe-result-to-learning summary tests for success, failure, missing/corrupt ref, and capture mismatch.
- Panel render/clear/stale-load tests and assertions that no action/grounding fields appear.
- Real pinned offline OmniParser cold/warm smoke against a synthetic, privacy-safe screenshot.
- Full UEI M1 regression, OmniParser provider regression, Learning Draft review regression, UTF-8 and change-scope privacy scan.

## Rollout

M2 rollout remains `Shadow`. The provider may run only through the internal runtime or explicit local operator smoke. The panel may review the sealed summary. Execute, action APIs, grounding, replay, and remote egress remain disabled.
