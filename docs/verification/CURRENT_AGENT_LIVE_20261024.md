# Current Agent mode — live acceptance, 2026-10-24

This record separates the source run from the 0.1.7 installation candidate.
The new managed entry supports a basic click loop; it does not add no-API
typing, scrolling or linear-plan support to that adapter.

## Source run

The actual Codex main Agent read the original Runtime PNG on every step,
returned `grounding.v1`, resolved it, continued the original command and
inspected the bound after image before recording its judgment. No visual
subagent or separate vision/Decision API was used.

One owned 7-Zip window navigated only a newly created test directory:
`Files → Stage01 → Files → Stage02 → Files → … → Stage10 → Files`.
The **20 logical steps completed on their first dispatch**, using one
persistent `CurrentAgentClient` / MCP connection. Folder entry used a double
click; Up used a single click. Twenty logical steps are not twenty physical
mouse-down events. Each request had a new grounding capture identity.

Negative controls after step 20:

- A success judgment with the wrong image hash was rejected.
- An `uncertain` judgment kept the adapter in `verification_required`; a new
  prepare was rejected before a worker or input was created.
- A correct, evidence-bound success judgment allowed explicit completion.
- Prepare after completion was rejected. `finish` returned
  `cleanup_verified=true`, and the owned client exited normally.

A separate current-Agent connection tested cancellation while awaiting
grounding. Cancel retained the original command identity and reached actual
worker `cancelled` with `action_executed=false`. A late continue was rejected;
explicit completion and owned-host cleanup passed. It did not open Stage11.

The source test ran before the release-version bump, so its MCP server
reported **0.1.6**. These results belong to the new source adapter, not the old
published 0.1.6 installer. Installation evidence must identify the later
0.1.7 payload separately.

## Separate-model usage evidence

The test launcher removed `*_API_KEY` and `AGENT_GUI_DECISION_PROFILE` only
from its own subprocess environment. The client independently isolated the
ambient Decision profile; Runtime was configured as `agent_current`, with no
API, Decision, local-model or delegate profile and no model preparation.
Session records and usage artifacts are audited separately. This is
configuration/dispatch evidence, not a packet capture of all machine traffic.
The hosting Codex service and its quota still apply; its token usage is not
reported as zero or as Runtime provider usage.

An independent read-only audit passed 27 checks: 20 original commands,
20 canonical local invocations and 20 dispatch attempts; ten double clicks
plus ten single clicks produced 30 unique mouse-down records. All 20 grounding,
local-before, result-after and delivered-after image hashes matched, and all
20 success judgments bound the correct after evidence. Session configuration
had no provider/delegate profile, Decision was unconfigured with zero usage,
and no provider-usage artifacts were found. Pending/cleanup and client exit
checks passed; the negative controls created no additional worker.

The normal 40-capture retention policy removed 30 auxiliary recognition,
pre-action and dispatch-recheck PNGs from the first ten steps. Their saved and
removed records still match. All primary grounding/before/after evidence
remains available; this record does not claim every auxiliary PNG can still
be reopened.

## Preserved preparation issues

The initial launch attempt assumed `C:/Program Files/7-Zip`; the actual
registered executable was `D:/7-Zip/7zFM.exe`. No input occurred in that failed
launch. A read-only preliminary discovery session was normally closed.

The logging harness also initially kept an obsolete local JavaScript state
reference; its pre-dispatch check refused the first grounding attempt. Reading
the actual latest receipt corrected the harness without changing the Runtime,
replaying a click or issuing another grounding request. These preparation
issues are excluded from claims about an uninterrupted task time.

## Installation candidate

Candidate 0.1.7 installer SHA-256:
`cb49707acc3de3df636521732e9e0f71a5c206ec2e631f19f9de95db63c6c73e`.
Native check-install wrote no normal OS integration. All **684 payload files**
matched size/hash before and after the real run; the isolated installed-entry
check also passed. The prepared external Python 3.12 environment was reused,
so this is not a clean-machine dependency-installation test.

The actual installed CLI ran with Python `-I -B` from that installation root,
with provider keys/Decision profile removed from its own environment. The
main Agent read each original PNG and each after image in a second application:
Windows Calculator **C → 1 → + → 2 → =**, five first-dispatch clicks ending at
the visible expression `1 + 2 = 3`.

After the last action, cancellation correctly kept the completed action facts
(`runtime_status=completed`, `action_executed=true`) while blocking the next
prepare with `current_agent_cancelled`. It did not retroactively claim the
completed click had been cancelled. Bound verification, explicit completion
and cleanup then succeeded.

A second installed connection cancelled a digit-9 request while awaiting
grounding: actual worker `cancelled`, `action_executed=false`, no dispatch;
late continue was rejected. Both installed clients returned
`cleanup_verified=true` and exited 0. The two task-owned application windows
were normally closed after the hosts had stopped. Native check-uninstall
passed; its worker and entire owned temporary installation root were removed.

The caller retained the actual ChildProcess arguments and the installation
working-directory argument after cleanup. Installation hashes and isolated
entrypoint checks identify 0.1.7. The live transcript did not separately retain
MCP initialize's serverInfo version or a process-internal module-path trace;
these are distinct evidence boundaries, not fabricated measurements.

The final release repacks documentation only. Its **583 Python modules and
all other production/configuration bytes must match this accepted candidate**;
the final release attachment report owns the final EXE/ZIP hashes and packaging
checks. Do not validate the final EXE against the candidate hash above or
describe a documentation rebuild as a second desktop run.

## Release regression

- Original affected suite: **368 passed** on Python 3.12 before the version
  metadata update; see the original offline checkpoint.
- Final 0.1.7 component collection/identity checks: **10 passed** on Python
  3.11. These include temporary payload/import checks, not actual GUI input.
- Final current-Agent/client/config/cancel plus HTTP checks: **116 passed,
  one initially skipped** on Python 3.12. Selecting the real Amadeus interpreter
  for that external-client check then passed it (**1 passed**).
- The unchanged extension's canonical manifest/Skill and native HTTP
  projection passed **2 unittest checks** under Amadeus's existing Python.
  Its environment has no pytest; the initial pytest launch failed for that
  missing test runner, then the existing unittest entry ran normally without
  installing a dependency.

These are overlapping suites and are not added into a larger unique-test total.
The external-client/extension checks use harmless synthetic HTTP sessions:
they prove those contracts, not a new Pi current-Agent desktop journey.

## Scope and evidence

Local evidence root:
`D:/AgentGUI-Projects/evidence/current-agent-mode-20261024/live01/`.
Original JSONL caller transcripts, server command/worker/response files and
authenticated PNGs are retained there. Only synthetic directory names were
used; this run did not use a browser profile, clear caches or change user files.

No matched API comparison was performed. The source run's timing includes
caller/tool/image-review gaps and preparation; no model-only latency,
four-second interval, speedup percentage, general accuracy or token-saving
claim follows from this acceptance.

MuMu, arbitrary cross-window workflows, administrator sessions and automatic
reconnect/restart recovery were not accepted in this run. Older MuMu task
results remain historical evidence of the underlying route.

See [offline checks](CURRENT_AGENT_MODE_20261024.md),
[mode guide](../development/CURRENT_AGENT_MODE.md) and
[中文模式指南](../development/CURRENT_AGENT_MODE.zh-CN.md).
