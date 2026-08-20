# Changelog

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

The next mainline is `reviewed_workflow_asset_v2`, followed by the single SEEK `Learning → Review → Publish → Verified Replay` path and generic replay/performance benchmarks.
