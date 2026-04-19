# PROJECT_CONTEXT

## Mission

Build a Windows UI automation runtime that lets AI operate desktop or browser applications through:

- visual understanding
- reusable local action logic
- deterministic click execution
- post-action verification

The target operating loop is:

`Vision -> Learn -> Recall -> Execute -> Verify -> Update`

## Migration Context

This project started in an OpenClaw-centered workflow, but OpenClaw runtime stability, auth complexity, and agent/session confusion made it unsuitable as the long-term execution host.

The new target is a Codex-maintained repository that keeps:

- OCR-driven interaction
- click-by-text behavior
- region-based click fallbacks
- verification logic
- explicit documentation as the source of truth

## Current Reality

The current repo is mid-refactor:

- region click and diff-based verification still exist
- MouseTester remains the main proven action path
- unified vision provider plumbing exists but is still stubbed
- legacy OCR/template/click_text code has been removed from the current branch state

So the migration is not “starting from zero”; it is “recovering the stable pieces and reorganizing them under Codex-owned docs and modules.”

## Codex Working Assumption

Documentation in this repo is the durable source of context.

There is no trusted hidden memory layer.
