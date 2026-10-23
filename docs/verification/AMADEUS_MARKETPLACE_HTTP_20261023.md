# Amadeus store preparation — 2026-10-23

**Release follow-up:** the final pair is Runtime 0.1.6 / extension 0.0.4. See the [delivery note](../releases/EXECUTION_016_20261023.md) and [pre-action acceptance](MAIN_PRE_ACTION_REVIEW_20261023.md). Candidate03 / 0.0.3 identities and statuses below remain historical; do not install them as the final 0.0.4 package.

Status: local candidate preparation; **not published, submitted, independently
approved or admitted to the catalog**. Runtime candidate 0.1.6 and extension
candidate 0.0.3 are separate artifacts from published 0.1.5 / 0.0.2.

## Sources and distribution boundary

- Amadeus upstream `9547f39ad518134ce4594f5a52a92c8a61629f45`, application
  `0.17.1-alpha.1`, includes the store prototype and merged Work approval changes.
- Catalog protocol repository `e2fc0e93fa7cfd9bf98e378cac6e158f14181b9a`; its
  public index was sequence zero with no reviewed entries when checked.
- Fixed author checker `1840c8e4f646992ddaebea3139c8895f29743a8f`, Windows,
  CPython 3.12.10, exact hashed authoring requirements. Current Host validation is
  a separate check against `9547f39`.
- The local Amadeus checkout was updated on a new branch after preserving its
  changed code and the one colliding untracked file. Its private `.env` remained
  byte-identical; deployment/browser caches, models and user data were retained.
  The existing voice + VAD + local-cu124 dependency selection was preserved.
  No old provider-specific patch was blindly replayed over merged upstream code.

## New route

Runtime reuses `InstantSession`, the existing tool factory, native SDK Streamable
HTTP and the unchanged input/receipt/review owners. It binds only 127.0.0.1,
requires a distinct environment-supplied Bearer connection secret before MCP,
checks Host/Origin and establishes one negotiated HTTP session owner. Status and
cancel remain concurrent with a long receipt wait. Disconnect is not cancellation.
DELETE requires verified Runtime cleanup and no in-flight POST before owner
release; a later Work can initialize its own session. Service shutdown closes the
Runtime session before the lifespan shutdown acknowledgement.

The resource-only 0.0.3 extension declares HTTP MCP + Skill. It neither selects nor
starts an external executable. It has no runtime dependencies, provider API keys,
Runtime payload, model weights, artwork or credentials. URL and secret connection
token replace the 0.0.2 external-launcher configuration. This is a manual
configuration migration; old provider keys must not become connection tokens.

## Python compatibility

The candidate API/Agent execution route supports Python 3.11 and 3.12; new API
environments default to 3.12. Amadeus and the Runtime keep separate environments
and locks. The local-model/UI dependency contract and main local-model lock remain
on Python 3.11. There is no claim that OCR, VISTA, CUDA, or every original project
dependency was migrated to 3.12.

The new 45-package API lock was installed with complete hashes and binary-only
selection in a fresh isolated CPython 3.12.10 environment. Its pins also resolved
for Windows CPython 3.11. Existing supported environments are retained; setup
refuses an in-place minor-version replacement. Only the explicit validated
startup recognition source can select the API environment contract.

## Recorded checks and limits

| Layer | Result / scope |
| --- | --- |
| Amadeus update | Desktop TypeScript/Pi/Vite build passed; 95 targeted Electron extension/store checks passed. |
| Existing GPU environment | Official `cu124` environment verification passed: Python 3.12.14, torch/torchaudio 2.6.0+cu124; 199 installed packages checked. This is environment qualification, not a new speech-quality test. |
| API/Agent Python 3.12 | 302 offline checks passed: 47 environment/setup/import-boundary checks and 255 synthetic API/Decision/MCP/review-continuation checks. |
| Existing Python 3.11 | 211 related checks passed, one new-default-3.12 setup case skipped there and passed under 3.12. Suites overlap; do not add them as unique tests. |
| HTTP protocol and repaired handshake | 32 checks passed on each of Python 3.11 and 3.12, including a real external Amadeus Python 3.12.14 / MCP 2.2.0 client. Authentication, Host/Origin, session ownership, status/cancel during receipt waits, failed initialization, verified release and shutdown were covered. |
| Component collection | Ten component checks passed under Python 3.12, including a real copied payload, installation identity, and isolated functional-entrypoint validation. |
| Native Runtime over HTTP | Production `InstantSession` on Python 3.12 completed two child-host start/ready/stop/cleanup/DELETE cycles. The queues contained only two cleanup `close` commands; no GUI command, screenshot, model request or desktop action was submitted. |
| Extension wheel preflight | Final 0.0.3 bytes passed current Host static validation and fixed catalog preflight. Human/runtime review remains pending. |
| Final extension installer lifecycle | Actual compiled Host installer/settings/helper passed eight stages and 24 assertions on the final wheel: configuration, Pi binding, launch snapshot, disable, data-retaining removal, reinstall and explicit data deletion. Actual Electron safeStorage was used with a synthetic token; confirmation callbacks were synthetic. |
| Native Pi HTTP routing | Final frozen HTTP module completed two independent Work sessions through Pi 1.2.0: eight successful tools and eight Host permission grants. The original PNG reached both Host results and the controlled loopback model request in each Work; both session DELETEs returned 200 and cleanup passed. This used source-manifest projection and a harmless Runtime fixture, not an installed end-to-end desktop task. |
| Packaged Skill | Official `read_skill_with_pi` read the Skill and reference and resumed native Pi successfully: two reads. The initial fixture omitted its enabled flag and was correctly rejected; that diagnostic remains recorded. |

HTTP protocol, final installer-backed extension lifecycle, native Pi routing and
final artifact hashes are recorded in the accompanying local preparation report
and source/receipt manifests. A test using a harmless session proves transport,
not real desktop execution. A controlled loopback model proves provider wiring,
not model judgment quality. Installer confirmation callbacks are labelled when
synthetic; they do not establish real native-dialog acceptance.

The independent HTTP review identified a failed-initialize ownership issue:
an HTTP 200 response containing a JSON-RPC initialization error could occupy the
owner slot. The repair buffers the complete SDK response and commits ownership
only after a valid successful `InitializeResult`; failed SDK sessions are deleted
through the native transport without stopping or closing Runtime input. Regression
covers failed initialize, rejected use of its SID, successful retry, tools,
verified DELETE and a second session. The initial finding remains part of the
record, rather than being represented as an original pass.

Frozen HTTP module SHA-256:
`84a679de075ce430724d2da70f3438251c9dad3925e4f8849a4a4ce990b56620`.
Final Pi rerun `pi-http-native/run-02` verified this hash before and after execution
and matched the final wheel manifest without modifying the wheel.

## Exact extension candidate

Final wheel: `amadeus_agent_gui_runtime-0.0.3-py3-none-any.whl`, 12,439 bytes.
SHA-256: `25adbcfd3d5dddecf06c52848f818370e932603294d7ea269f664b0a097f8758`.
Ten wheel members; no executable launcher, native binary or `.pth` startup hook.
An earlier local preparation wheel was superseded by LF normalization and the
completed setup guide; its preliminary checks are not final-byte qualification.
No released artifact was replaced.

Local evidence root: `amadeus-marketplace-20261023-01/`.
Only curated sanitized results are suitable for submission. Private code/config
recovery copies, runtime data, raw logs and daily user settings are not submission
material. Final author preflight says `review_status=not_reviewed`.

<a id="installed-desktop-acceptance"></a>

## Installed desktop acceptance

The installed candidate was exercised through the updated Amadeus's actual
compiled ExtensionInstaller, shipping Electron/backend Work pipeline, Pi 1.2.0,
authenticated native HTTP MCP, and production Runtime child host. The installed
wheel supplied both the MCP resource and the Skill. The test did not substitute
a harmless Runtime, a loopback Pi model, shell desktop input or native Codex
Computer Use. Host permissions were inspected and granted individually by the
test operator; this is functional acceptance, not an unattended-speed benchmark.

| Attempt | Actual outcome |
| --- | --- |
| Candidate 01, Notepad | Connected and launched. The original ledger recorded a Decisions protocol error before action dispatch; it did not preserve the raw API response. One separately authorized diagnostic using the same bound evidence reproduced parser rejection of valid nested cache-write usage metadata. No typing occurred. Both records remain distinct. |
| Candidate 02 | Independent review found a nested-usage aggregation bug before desktop input. The pending start permission was never approved; the Work was cancelled and its owned processes were cleaned up. This is an aborted test, not a pass. |
| Candidate 03, 7-Zip | Launched the declared synthetic directory. Both model layers rejected the Alpha folder candidate before dispatch; no browse click occurred. Pi cancelled the original plan and cleaned up. This remains a failed business attempt, although HTTP and cleanup passed. |
| Candidate 03, Notepad, controlled double rejection | Entered the declared line once; the TEST proxy rejected the exact field-result check in Decision and ordinary Luna once each. The original Pi viewed the bound after image, explicitly reviewed it as success and separately continued the original run/wait. The edit → File → Save history completed all three steps. Independent disk inspection matched all 49 expected bytes, with no extra newline. |

The final saved text was `Pi HTTP Main review - continued without retyping.`
Its SHA-256 is
`192b74fef990dc689a3248f17c94deca25bc0cb549c37ac83bb396960fe2f669`.
The accepted review retained the original execution request, original image hash,
packet hash and evidence-set hash. It did not erase the two rejected assessments,
restart the plan or retype the text. The suffix used the ordinary action gates.
The original Pi's image read, review and continue are distinct recorded calls.

Both candidate 03 sessions closed their original owned windows, then reached
`host_alive=false`, `pending_ids=[]`, `cleanup_verified=true` through the original
MCP connection. A fresh no-input native HTTP client could initialize, read
status and DELETE with HTTP 200 after each original Work, proving owner release.
The original transport also recorded session termination; its DELETE response
status was not separately captured and is not borrowed from the fresh probe.
The test controller then stopped only its owned product/service processes;
their recorded exit code was 1, not a graceful-exit assertion. The actual native
ExtensionInstaller removed each isolated extension and its test data. This does
not remove or stop a user's independently installed Runtime.

The controlled proxy only targeted the declared field-result check. Other model
calls used the configured real API. Injection proves recovery behavior, **not**
natural model accuracy, a latency improvement, a general success rate or a
reduction in billed tokens. The model's ability to reject a correct target
remains a known limitation. Pi also guessed a tool name in the 7-Zip Work before
self-correcting to the actual discovered shortened name; that outer error was
retained, rather than reporting an error-free first attempt.

Pre-dispatch and post-input review have different contracts. The observed 7-Zip
pre-dispatch packet offered `recover`, `resume_pre_dispatch` and `cancel`;
it did not offer the successful Notepad field review/continue ticket.
`resume_pre_dispatch` creates a new attempt with fresh grounding and model
checks; it is not a Main override of the rejected candidate. It was not exercised
in this attempt. Do not promise that Main can directly approve every refusal.

### Response compatibility repair

The one-call diagnostic after the first live failure reproduced rejection of
real API metadata of this shape; its response is not substituted for the
uncaptured original response:

```json
{"cache_write_tokens_details":{"ttl_30m_tokens":0,"ttl_12h_tokens":0}}
```

The parser now accepts only the two validated non-negative integer TTL counts;
malformed structures remain rejected. The ordinary-review usage aggregator adds
these nested counts without adding the metadata to the billable token total.
Choice semantics, prompts, thresholds, models and input gates were unchanged.
The related regression selection passed **390 checks on Python 3.11 and 390 on
Python 3.12**; these are overlapping suites, not 780 distinct tests. Independent
incremental review ran the 18 cache-write cases and closed the aggregation finding.

### Frozen installed identity

Runtime candidate 03 installer SHA-256:
`6d4ccf5ab134e6a93e9ff6adf6fe9f1ca2a03d607bc9a963bc20cae13b5eb001`.
The installed payload contained 669 verified files. Installation used the actual
installer's isolated check mode; daily Runtime installation, OS registration and
shortcuts were not replaced. The extension wheel retained the exact 0.0.3 hash
listed above. This evidence does not qualify the superseded candidate 01/02
installers or the already published 0.1.5 release.

No browser was used, no browser cache or existing tabs were changed, and no
wallpaper or new speech-quality test was performed. The private Amadeus recovery
copy, credentials, raw desktop images and raw sessions must not enter the public
submission. Curated receipt summaries and hashes are the submission material.

## Remaining public gates

Record final payload identity and relevant local checks. Before a public
submission, supply a real versioned wheel URL, public source/build evidence,
ownership and ISC rights evidence, migration/lifecycle instructions and precise
coverage limits. An eligible non-author reviewer owns independent approval;
catalog maintainers own the publication PR and verified live index. A passing
author preflight does not authorize self-approval or manufacture a published entry.
