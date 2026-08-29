# Benchmark v2 P0-C: Narrow Probe Trigger Evidence Contract

## Status and authority

This document is the canonical P0-C contract. It supersedes the prior
amendment's **unimplemented** pre-cancel worker body, provider-native raw, B1
absence-chain, and runner-selection expansion. The already-committed dispatch
runtime-parent plus commit-marker transaction remains a frozen upstream input.
P0-C is deliberately smaller and does not reopen or extend B1 supervision.

P0-C records non-authorizing benchmark evidence only. It neither grants desktop
input authority nor authorizes a model, provider, or GUI action.

## Fixed scope

P0-C contains exactly these requirements:

1. Persist the exact worker/provider process identity observed before cancellation.
2. Persist a terminal journal record.
3. On recovery or consumption, live re-attest absence for the same exact
   `{pid, create_time_ns}` identity.
4. Treat `AccessDenied`, API failure, malformed evidence, and identity ambiguity
   as fail-closed/indeterminate.
5. Mark all generated evidence as `benchmark_probe_only_non_authorizing`, with
   `artifact_is_authorization=false` and `execute_binding_enabled=false`.
6. Make the cancellation trigger exactly once across a lost response or restart.
7. Do not create a general durable process supervisor.

P0-C must not create a general durable process supervisor, modify B1, add a
provider model, retain provider raw output, change `WorkflowService` or
`LearningStageWorkerRegistry`, or change runner/deadline semantics. P0-D is a
separate follow-up for monotonic deadlines and runner semantics.

## Slice 1: durable pre-cancel trigger intent

Before calling `cancel_operation`, runtime must:

1. validate the committed dispatch receipt and request lineage;
2. reopen the frozen committed dispatch receipt/runtime-parent/commit-marker
   transaction, then derive the ordered exact `process_identities` list from
   `runtime_parent.runtime_identity.process_identities`;
3. append and fsync one `probe_trigger_intent` event to the attempt journal;
4. hold the attempt-journal lock across the full uniqueness scan and append: for one `(attempt, provider, probe_kind, probe_trigger_intent)` tuple, an identical replay returns the existing row and any competing or duplicate row fails closed before cancellation;
5. bind that sealed intent to the exact attempt, provider, probe kind, operation,
   request, dispatch receipt, and runtime-attestation parent;
6. set the fixed non-authorizing evidence scope; and only then
7. call `cancel_operation`.

Missing or unsealed request/dispatch/runtime parent, a cross-operation join,
invalid PID/create-time, an empty identity list, or a duplicate/inconsistent
identity must fail before cancellation. The journal append is the durable
pre-cancel marker; a runtime dictionary is not sufficient evidence.

The intent contract is `benchmark_v2_probe_trigger_intent_v1`. Its closed body
contains:

```text
attempt_ref
provider_id
probe_kind
operation_ref
request_in_flight_ref
dispatch_receipt_ref
dispatch_runtime_parent_ref
process_identities
evidence_scope
artifact_is_authorization
execute_binding_enabled
content_sha256
```

## Slice 2: terminal journal, recovery, and exactly-once trigger

After Slice 1, add only the minimal durable reconciliation needed to ensure a
lost response or restart does not repeat cancellation:

- persist the terminal result after the service responds;
- recover an existing trigger intent from the attempt journal before any retry;
- re-attest the same `{pid, create_time_ns}` live;
- accept only confirmed absence or a different PID incarnation; and
- return an indeterminate/fail-closed result for `AccessDenied`, API failure,
  same-incarnation live, or any ambiguity.

### Implemented Slice 2 behavior

The attempt journal admits one `probe_trigger_intent` and one
`probe_trigger_terminal` per provider/kind. The terminal records only
benchmark-probe non-authorizing evidence and exact identity outcomes. On every
terminal or cleanup-receipt replay, the runtime ignores historical absence as
proof and performs a fresh exact `{pid, create_time_ns}` observation. `NoSuchProcess`
or a different incarnation is acceptable; same incarnation, `AccessDenied`, API
failure, malformed identity, or ambiguity fails closed. PID reuse records the
newly observed `observed_create_time_ns` and is accepted only as absence of the
previous exact incarnation. An intent-only restart uses the existing read-only
WorkflowService lookup first: a confirmed safe stop
is journaled without recancel; a pending exact operation may be cancelled once,
then is freshly re-attested and terminalized. This does not create a general
process supervisor or alter B1.

The resulting evidence remains benchmark-only and non-authorizing. It may
support a benchmark report, never action dispatch.

## Verification and boundaries

Each slice follows TDD: add a focused RED test, observe the expected failure,
make the smallest implementation change, and rerun focused tests. Required
negative controls include missing runtime identity, stale/cross-operation
lineage, duplicate/inconsistent identity, lost response, live same-incarnation,
and API/permission ambiguity.

Do not run models, providers, GUI automation, or an actual benchmark while
P0-C is incomplete. After P0-C reaches FINAL PASS, proceed directly to P0-D;
do not revive the superseded raw-evidence/B1 work.
