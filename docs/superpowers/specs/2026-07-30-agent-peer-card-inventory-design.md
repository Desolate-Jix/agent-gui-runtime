# Agent-Readable Peer Card Inventory Design

## Goal

Extend the current Learn Mode repeated-layout review path so a confirmed same-class card set produces a geometry-free, Agent-readable semantic inventory. The inventory must help an Agent understand current content without turning a class prior or historical bbox into action authorization.

## Scope

- Consume the current Stage2 numbered regions after layout review enhancement.
- Project only card-like candidates already present in current screenshot evidence.
- Preserve class-rule context such as `peer_item_family`, but require current candidates.
- Describe each item with stable evidence identity, semantic label, readable content, review status, and safe capability hints.
- Expose the projection in the Stage2 report and offline class-rule demo Agent evidence.
- Validate on the existing five-site aggregate/feed/search replay.

Out of scope:

- New geometry detection or bbox correction.
- Dynamic-region refresh behavior.
- Real model prompt tuning.
- Real click, fill, submit, Gate, Execute, or Runtime PathGraph changes.

## Contract

The new `agent_peer_card_inventory_v1` projection contains:

- `peer_item_family`: advisory class family selected by the Surface Adapter.
- `current_visual_evidence_required=true`.
- `items`: current-image card candidates only.
- Each item has `candidate_id`, `semantic_name`, `content_summary`, `source_kind`, `review_status`, and `capabilities`.
- `capabilities.read_current_content=true`.
- `capabilities.open_detail_candidate=true` only when the source item already carries explicit current interactable/action evidence.
- No bbox, click point, historical coordinate, or executable selector is included.
- `artifact_is_authorization=false` and `execute_binding_enabled=false`.

## Data Flow

`Stage2 candidates -> layout review enhancement -> peer-card inventory projection -> Stage2 report -> Agent evidence demo`

The projection does not alter Stage2 geometry. A missing class prior or missing current card candidates produces `not_covered`, not synthetic items.

## Failure Handling

- Duplicate candidate identities are collapsed and reported.
- Missing readable text produces a generic semantic name and `needs_human_review`.
- Inferred neighbour candidates remain visible as review candidates and never become actionable.
- Unsupported classes or evidence-free pages return an empty inventory with an explicit reason.

## Verification

- Unit tests cover semantic projection, geometry stripping, explicit-action gating, duplicate handling, and no-evidence behavior.
- Pipeline test confirms the inventory is attached after Stage2 enhancement.
- Demo test confirms Agent evidence receives the inventory summary.
- Existing five-site replay must remain read-only with zero live actions.

