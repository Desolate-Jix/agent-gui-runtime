# Portfolio v1 reviewed-asset workspace

This directory stages the smallest Portfolio v1 review boundary:

```text
Job Detail
  -> open_apply_flow (human confirmation required)
Choose documents / Apply Entry
  -> SAFE STOP
```

## Evidence grade

The checked-in workspace is currently a **mixed-grade review draft**. Job Detail
uses an annotation-free `sanitized_clean_capture` created by a deterministic
top/bottom crop of a historical clean capture; its original and derived SHA-256
values and transform are recorded in the node evidence. Review boxes must be
rendered as independent overlays and must never be baked into this editable
base. Apply Entry remains a privacy-redacted historical derivative, not raw or
forensic pixel evidence, and privacy processing may alter non-reviewed pixels.
Human review is therefore limited to the declared interface responsibility,
semantic `Quick apply` control, `open_apply_flow` transition, and Apply Entry
safe-stop boundary. This workspace is not yet:

- a human-reviewed release asset;
- runtime dispatch authority;
- a deterministic internal composition proof;
- a controlled live SEEK workflow proof.

`review-draft-manifest.json` is the authoritative status marker. Automation must not change `human_review_completed` to `true` or synthesize review confirmation.

## Human-review boundary

Only `job_detail` is intended for approval. Review must confirm:

1. the interface responsibility and fixed identity evidence;
2. the semantic `Quick apply` control and its purpose;
3. the single `open_apply_flow` transition;
4. `requires_user_confirmation: true`;
5. no form fill, Continue/Next, final submit, send, confirm, or payment action;
6. `apply_entry` remains `needs_learning` and has no outgoing transition.

The Panel approval order is intentional and must not be collapsed into a
single node confirmation:

1. set the `apply` semantic control to `human_approved`;
2. set the `open_apply_flow` action candidate to `human_approved`;
3. set the `open_apply_flow` edge to `human_approved`;
4. confirm the `job_detail` node only after those reviewed semantics are saved;
5. save and reload the workflow, then verify that `job_detail` is
   `agent_usable` with exactly one `open_apply_flow` action and that
   `apply_entry` remains a stop boundary.

The Panel now exposes the three distinct granular review gestures and requires all three before source-node confirmation; the compiler independently checks each approval before accepting a candidate. The current Portfolio draft is still unreviewed: W2c remains open until the user reviews the target control, exact action candidate, transition edge, and source node, then saves and supplies exact compile/publish/process-restart/reload proof. This implementation status does not claim human approval, Runtime authorization, or live workflow proof.

Node confirmation alone does not approve a control, action candidate, or edge.
Automation must not perform any of these human-review decisions.

The local ignored `artifacts/` copy is the Panel review surface. After a real Panel review, the exact persisted workflow bytes and evidence provenance are exported back into this portable workspace; the compiler output and release manifest are then generated from those bytes.

## Required release proof after review

The release test must copy this workspace to a temporary project root and prove:

- exact source and registry SHA binding;
- `job_detail` is `agent_usable` with one `open_apply_flow` action;
- `apply_entry` compiles only as a stop boundary;
- compile and publish succeed without historical geometry authority;
- a fresh Python process reloads the exact content-addressed asset;
- the release manifest still declares `controlled_live_workflow_proven: false`.

Until those checks pass, W2 remains open.
