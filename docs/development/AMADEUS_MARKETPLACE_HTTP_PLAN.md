# Amadeus marketplace preparation — 2026-10-23

## Accepted scope

The user selected an authenticated, loopback-only native HTTP MCP route. Preserve
the existing stdio route and all existing input permissions, request IDs, receipts,
image evidence and Main review/continue semantics. This is a new candidate, not a
capability of the frozen Runtime 0.1.5 or extension 0.0.2 artifacts.

Also evaluate unifying Runtime's Python 3.11 environment with Amadeus's Python
3.12. Establish dependency and runtime evidence before changing compatibility
claims or removing 3.11 support. Distinguish API execution from optional local
model dependencies.

## Work and completion checks

1. Preserve Amadeus local code changes and configuration; update source and the
   existing voice/VAD/CUDA dependency selection to upstream
   `9547f39ad518134ce4594f5a52a92c8a61629f45` (`0.17.1-alpha.1`). Build its desktop
   and run proportionate extension/store checks. Existing browser data is retained.
2. Reuse `InstantSession` and `build_server()` in a separate maintained native
   Streamable HTTP MCP entry point. No MCP-to-REST bridge or second executor.
   Authentication must precede protocol processing; reject unauthenticated calls,
   unsafe Host/Origin and non-loopback binding. Define the authenticated operator
   and single-input-owner/session boundary explicitly. Native HTTP lifecycle must
   start the SDK session manager and close the Runtime session on service shutdown.
3. Add real local-protocol tests: initialize, list tools, harmless calls and image
   content; invalid/missing token, Host/Origin, competing input ownership,
   disconnect/reconnect, explicit session close and daemon shutdown. Synthetic
   inputs only initially; no real desktop action in transport tests.
4. Prepare a new extension candidate (`0.0.3`) containing a declarative `http` MCP
   connection and packaged Skill. Configuration selects URL and a secret connection
   token, never a Python executable or external code path. Service-provider API
   keys remain Runtime-owned and distinct from the connection token.
5. Check actual wheel bytes against the current Host and the independently pinned
   catalog checker. Keep schema v0 for current curated admission. Prepare truthful
   submission metadata, build/source hashes, installation/lifecycle instructions
   and coverage limits; no author-written independent review approval.
6. Include the new maintained entry point in execution payload collection and
   entrypoint verification. Record Python compatibility results and preserve
   supported existing routes. Only claim an installed/new-release capability after
   building and testing that artifact.

## Verified policy and current gap

Catalog repository `Code-Amadeus/Amadeus-Extensions` at
`e2fc0e93fa7cfd9bf98e378cac6e158f14181b9a` has an empty reviewed catalog.
`catalog/REVIEW_CHECKLIST.md` excludes configuration selecting executables/modules.
The existing 0.0.2 external launcher therefore cannot be represented as admitted
by a static wheel pass. The same protocol explicitly supports HTTP MCP and secret
Bearer bindings; the new route must still pass independent review.

Public submission, marketplace approval and release publication remain distinct
from local preparation and compatibility checks.
