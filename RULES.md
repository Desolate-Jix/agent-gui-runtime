# RULES

## Working Rules

1. Use the execution loop from `skills/code-implementation-loop/SKILL.md` whenever code changes.
2. Prefer the smallest verified vertical slice over broad scaffolding.
3. Do not claim a feature works without runtime evidence.
4. Update docs in the same work session when behavior or architecture changes.

## Documentation Rules

When changes affect project understanding, update the relevant files:

- `README.md`
- `PROJECT_CONTEXT.md`
- `RULES.md`
- `KNOWLEDGE_BASE.md`
- `PROJECT_SUMMARY.md`
- `ARCHITECTURE.md`
- `CURRENT_STATE.md`
- `NEXT_STEPS.md`

## Architecture Rules

1. Keep Windows-specific execution details separate from pure logic.
2. Favor testable pure functions for:
   - OCR post-processing
   - region geometry
   - click candidate generation
   - verification heuristics
3. Keep provider-specific vision logic behind explicit interfaces.
4. Treat logs as runtime artifacts, not canonical configuration.

## Migration Rules

1. Replace OpenClaw memory files with repo-local documentation.
2. Do not reintroduce hidden runtime memory as the primary source of project context.
3. Preserve useful behavior even if the original OpenClaw framing is removed.
