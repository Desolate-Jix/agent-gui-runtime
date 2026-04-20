# AGENTS.md

## Scope

These instructions apply to the repository root `D:\ai agent framework`.

## Required Workflow

When implementing or modifying code, follow the execution loop defined in:

- `skills/code-implementation-loop/SKILL.md`

That means:

1. make the smallest meaningful change
2. run the narrowest relevant verification
3. inspect the result
4. fix failures
5. rerun until the path is verified or a real blocker remains

Do not stop at draft code when a runtime or smoke check is possible.

## Documentation Sync Rule

When code changes affect behavior, API shape, architecture, progress, or known limitations, update documentation in the same work session.

At minimum, review and update the relevant files:

- `README.md`
- `PROJECT_SUMMARY.md`
- `ARCHITECTURE.md`
- `CURRENT_STATE.md`
- `NEXT_STEPS.md`
- `OPENCLAW_RECOVERY.md` when recovered OpenClaw history or migration notes change

For bilingual design docs, keep both language versions in sync in the same work session:

- `RUNTIME_STATE_GRAPH.md`
- `RUNTIME_STATE_GRAPH.zh-CN.md`

Update only the files impacted by the change, but do not leave `README.md` stale when public behavior changed.

## Definition Of Done

A code task is not done unless both are true:

- the changed path was verified with the narrowest meaningful check available
- the affected documentation was brought back in sync

If full execution is blocked, record:

- what changed
- what was verified
- what remains blocked
- what document state was updated despite the blocker

## Notes

- The summary/recovery docs are intentionally `.gitignore`d in this repo, but they still must be kept up to date locally.
- Prefer evidence-based status notes over optimistic summaries.
