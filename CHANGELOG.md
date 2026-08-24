# Changelog

## 0.3.0 — 2026-08-21

### Reviewed workflow v2

- Added the immutable, content-addressed `reviewed_workflow_asset_v2` contract and CAS store for reviewed semantic states, transitions, preconditions, expected effects, verification, and bounded recovery; old runtime assets are not migrated.
- Added the server-side v1-to-v2 compiler with source-hash, registry-membership, review-integrity, semantic-action, and fail-closed safety checks.
- Added verified replay state resolution, current-capture grounding, Gate binding, post-action verification, and bounded recovery with stale/ambiguous/danger safe-stops.
- Added panel APIs for compile, CAS publish, and read-only replay preview. The server resolves sources and assets; preview requires a current observation and never captures the screen or calls the action API.
- Added panel controls for the compile → publish → preview flow, with stale-state invalidation on workflow edits or switching.
- Added a synthetic three-state SEEK E2E path (home → detail → application-entry stop) using the real compiler, CAS, panel API, replay coordinator, and navigation adapter envelope, with external dependencies replaced by fakes.

### Explicitly not claimed

- The synthetic E2E is not a real GUI, network, or action execution proof, and does not claim ATS E2E, live safe-fill, or unattended reliability.
- `read`/`scroll` executable replay remains deferred until a typed effect verifier exists; OmniParser remains a review-only learning shadow and is not an authorization layer.

### Release checks

- Focused v2 contract, compiler, replay, panel, and navigation tests pass; metadata, lockfile, link/path, diff, and UTF-8 checks are maintained separately.

## 0.2.0 — 2026-08-21

### Direction

- Reframed the project as a reliability layer for computer-use workflows rather than an OCR competition.
- Made the primary lifecycle explicit: `Learn → Review → Compile → Verified Replay → Recovery`.
- Set the next implementation line on new reviewed workflow assets and replay quality; old runtime content is not migrated.

### Included in this release

- Learning workspace and reviewed workflow projections remain non-authorizing and freshness-bound.
- Shared action/Gate contracts continue to distinguish navigation, flow entry, field operations, continuation, and final-submit actions.
- SEEK controlled evidence is limited to home → detail → same-site Apply/Quick Apply entry, with no fill, upload, continuation, or final submit.
- OmniParser is documented and exposed only as an optional read-only learning shadow/contact-sheet provider through `screen_parser_result_v1`.
- Public README, English README, version metadata, ISC license, and third-party notices are synchronized for the current repository content.

### Explicitly not claimed

- No universal OCR or UI-recognition accuracy claim.
- No live ATS end-to-end, live safe-fill, unattended apply, or final-submit capability.
- No distribution of OmniParser source, weights, virtual environments, or optional dependencies.

### Release checks

The release check is intentionally narrow: metadata parsing, lockfile synchronization, README link/path audit, `git diff --check`, and UTF-8 replacement-character scan. See the repository history and focused test files for implementation-level checks; this changelog does not restate a full-suite total.

## Unreleased

- Portfolio v1 is frozen as one bounded Quick Apply-only release: already-open reviewed Job Detail → one confirmed and Runtime-authorized `open_apply_flow` → fresh Apply Entry / `Choose documents` → `SAFE_STOP/stop_boundary`.
- The release includes one scoped controlled-live receipt only. It does not claim general reliability, Provider accuracy, Homepage/list traversal, external Agent compatibility, form mutation, unattended operation, or production readiness.
- Current semantic `open_detail` live proof is deferred to post-v1. Its deterministic internal proof remains engineering evidence and must not be described as live proof.
