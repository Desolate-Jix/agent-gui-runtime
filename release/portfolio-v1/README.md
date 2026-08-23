# Portfolio v1 reviewed-asset workspace

This directory is a portable, tracked export of the smallest reviewed Portfolio
v1 semantic workflow:

```text
Job Detail (human_approved)
  -> Quick apply / open_apply_flow (human confirmation + Runtime Gate required)
Choose documents / Apply Entry (needs_learning)
  -> SAFE STOP
```

## Current release truth

`review-draft-manifest.json` is the release manifest despite its retained
historical filename. It records:

- `human_review_completed: true` for the executable `job_detail` boundary;
- `compiled_release_asset_present: true`;
- `controlled_live_workflow_proven: false` while the checked-in public evidence
  package awaits independent review and explicit release-status promotion;
- `runtime_dispatch_authorization: false`;
- `artifact_is_authorization: false` and `execute_binding_enabled: false`.

The exported source is byte-exact to the reviewed local source:

- source SHA-256:
  `a934acc82708cfd956110ba2bba35e8d0bc317af9e095606efab87c5f3e027bc`;
- compiled asset SHA-256:
  `8284e1729409aa0a4f6a751a1a03d85fc51db1c7d53d473bd012455a3fc391b7`.

## Reviewed boundary

The `job_detail` node contains two human-visible reviewed regions:

1. **Quick apply** — the only semantic execution candidate. It compiles to one
   `open_apply_flow` transition and still requires current observation, fresh
   grounding, user confirmation, the Runtime Gate, one-time authority, and
   post-action verification.
2. **Save** — `read_only` evidence only. It has no destination, is absent from
   compiled transitions, and must never be activated by this workflow.

`apply_entry` deliberately remains `needs_learning`, has no outgoing action,
and compiles only as `stop_boundary`. Form fill, file upload, Continue/Next,
final submit, send, confirm, and payment remain outside Portfolio v1.

## Evidence and geometry boundary

Job Detail uses an annotation-free `sanitized_clean_capture`. Human-review
boxes are stored as separate overlay evidence. Apply Entry remains a
privacy-redacted historical derivative rather than raw or forensic pixel
evidence.

Editable review sources retain bounding boxes because they document what the
human reviewed. The compiled asset contains no historical `bbox`, `x`, `y`,
window handle, or click authority. Its safety contract declares
`historical_coordinates_used: false` and `fresh_grounding_required: true`.

## Portable workspace layout

```text
reviewed-asset-workspace/
  artifacts/interface-workflow-reviews/
    registry.json
    portfolio_v1_seek_apply_entry/
      reviewed_workflow.json
      node-review-sources/
      node-evidence/
  artifacts/learning-draft-review/
    ... reviewed candidate and overlay lineage ...
  artifacts/portfolio-v1-review-evidence/
    ... sanitized evidence ...
  runtime_state/reviewed-workflow-assets-v2/
    registry.json
    objects/8284e172...391b7.json
```

All registry and evidence paths are workspace-relative. A fresh Python process
can copy this directory to a new project root and load the exact active asset
through `ReviewedWorkflowAssetStore`.

## Verification

Run:

```powershell
uv run pytest -q tests/test_portfolio_v1_release_workspace.py
```

The focused release test proves:

- exact source and compiled-asset SHA binding;
- `job_detail` human approval and granular Quick apply approval;
- Save remains read-only and non-executable;
- `apply_entry` remains a no-mutation stop boundary;
- source compilation reproduces the checked-in asset byte-for-byte;
- compiled runtime knowledge contains no historical geometry authority;
- a fresh process reloads the exact active content-addressed asset;
- all artifacts remain non-authoritative and
  `controlled_live_workflow_proven` remains false.

## Public evidence package

`evidence/manifest.json` content-addresses a privacy-minimized package with:

- an allowlisted projection of one exact-live Runtime receipt;
- matched deterministic controls that distinguish the exact current asset from
  a behavior-equivalent historical visibility fixture;
- an operator cleanup commitment that explicitly records the absence of a raw
  navigation-restore artifact; and
- strict JSON Schemas for each public artifact.

The package contains no raw Runtime object, capture, window/process identity,
full URL, or page-specific personal fields. Its status remains blocked pending
independent review. Until that review and a separate root/release status-sync
slice finish, it must not promote `controlled_live_workflow_proven` or broaden
the claim beyond one bounded live receipt.
