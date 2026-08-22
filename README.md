# agent-gui-runtime

**Version 0.3.0 · Windows GUI Agent Runtime · Portfolio v1 in progress**

[简体中文](README.zh-CN.md)

## A reliability runtime target between computer-use agents and Windows GUI actions

An in-progress Windows GUI runtime designed to turn uncertain exploration into human-reviewed operational knowledge, then re-locate, gate, execute, and verify semantic actions against the current interface.

**Perception is replaceable. Reviewed knowledge is durable.**

**Target invariant:** Runtime Authority must be non-bypassable. **The internal W3b Windows composition is implemented and deterministic-test verified: it consumes observation-bound intent through current re-grounding and Gate to one guarded dispatch and a durable receipt. This is not Controlled Live Workflow Proof: W4 legacy-dispatch consolidation and W5 post-action semantic verification remain pending.**

> **Target authority model:** Providers propose evidence. Agents propose semantic intent. The runtime alone grants bounded execution authority.

[![Sanitized reviewed workflow overview](docs/media/private-prototype-workflow.png)](docs/media/private-prototype-workflow.png)

*Sanitized workflow overview from the [earlier public showcase repository](https://github.com/Desolate-Jix/windows-gui-agent-runtime): reviewed interface knowledge guides intent, while the runtime must re-locate against the current observation and independently gate each action. This is a product-story illustration, not current Portfolio v1 live proof.*

- **Today:** offline contract foundations; an internal server-owned W3b controller composition with durable intent/receipt records; and historical live GUI evidence.
- **Implemented internally:** reviewed asset -> passive bound-window capture -> observed UIA origin -> pinned recognition -> strict Observation/Intent -> current re-ground -> Gate -> exact pre-dispatch pixel freshness -> one-shot Windows backend -> durable receipt.
- **Not yet:** W4 closure of legacy production mutation/dispatch bypasses, W5 post-action semantic effect/destination verification, Controlled Live Workflow Proof, public HTTP/demo callsites, external/remote Provider integration, or live external Agent adapters.

## Why this runtime exists

The common computer-use loop is short:

```text
screenshot → model → coordinate → click
```

It can fail when responses become stale, windows change, labels repeat, or dispatch is mistaken for verified effect. A stronger model alone creates neither durable knowledge nor authority.

This project adds the missing reliability layer:

```text
uncertain exploration → evidence → human review → durable semantic workflow
→ current-interface relocation → Gate → bounded execution → Verify / Safe Stop
```

This project does **not** race the perception releases of Qwen, OpenAI, Anthropic, OmniParser, or similar teams. New perception belongs behind the evidence boundary. Bundled screenshot, UIA, OCR, and recognition are a baseline/fallback—not the moat or proof of general visual understanding.

## Visual product tour

> **Historical showcase UI.** These panels come from the [earlier public showcase repository](https://github.com/Desolate-Jix/windows-gui-agent-runtime) and are included to make the product workflow visible. They show design lineage—not current Portfolio v1 live proof—and the current interface and runtime behavior may differ.

### Learn / Review panel

[![Historical Learn Mode panel](docs/media/private-prototype-learn-mode.png)](docs/media/private-prototype-learn-mode.png)

**Evidence: historical showcase UI.** Review captured interface evidence, approve semantic states, and connect them into a reusable workflow graph. The panel does not authorize execution.

### Execute / Runtime panel

[![Historical Execute Mode panel](docs/media/private-prototype-execute-mode.png)](docs/media/private-prototype-execute-mode.png)

**Evidence: historical showcase UI.** Inspect the intended Observation → available semantic actions → Gate → Trace surface. This panel does not prove W4 unique dispatch ownership or W5 semantic verification.

### Sanitized workflow sequence

![Sanitized private-prototype workflow sequence](docs/media/private-prototype-seek.gif)

**Evidence: sanitized historical showcase.** This animation explains reviewed results → detail → application-entry blocker / Safe Stop. It is not the reproducible demo, a live Agent proof, or evidence of form completion or submission.

The panels illustrate the intended **Learn → Human Review → Runtime** handoff. They do not prove current relocation, Gate lineage, semantic verification, or autonomous replay.

## How it differs

| Screenshot-to-click systems | Target runtime behavior |
| --- | --- |
| Model output can become a coordinate. | Provider output remains evidence through trusted adaptation and review. |
| Past geometry may be replayed. | Reviewed semantics are reused; geometry must be relocated on the current capture. |
| The model or Agent owns the action decision. | The Agent proposes semantic intent; Runtime Authority decides whether one bounded attempt is allowed. |
| A sent click may be reported as success. | The observed effect must be verified, otherwise the result is unverified or a safe stop. |
| Changing models can change everything. | Four contracts separate evidence, assets, Agent intent, and receipts. |

## Target lifecycle

Required end state—the live loop is not complete today:

1. **Explore** an uncertain path.
2. **Capture evidence** with identity, coordinates, provenance, and freshness.
3. **Review** semantics, actions, transitions, effects, and risk.
4. **Compile** an immutable semantic asset that grants no authority.
5. **Observe again** for an Agent intent.
6. **Relocate** on the current interface; old coordinates are hints only.
7. **Gate** one attempt using current evidence and danger checks.
8. **Execute** through the internal Desktop I/O backend seam beneath Runtime Authority. W3b composes the reviewed asset, passive bound-window capture, real UIA origin, pinned recognition, strict intent, current re-ground, Gate, exact pixel freshness, one-shot Windows backend, and durable receipt; deterministic tests verify this internal path.
9. **Verify** or Safe Stop. W3b success stops at `DISPATCHED` with `verification_pending`; W5 post-action semantic effect/destination verification remains incomplete.

## Target authority architecture

The public architecture freezes four contracts:

1. **Perception Provider Contract** — native output becomes trusted canonical UEI evidence.
2. **Reviewed Workflow Asset Contract** — reviewed evidence becomes durable semantic states, transitions, verification policy, provenance, and revision/hash.
3. **Agent Runtime Contract** — Runtime exposes Observation/actions; Agent returns observation-bound semantic intent.
4. **Runtime Result & Verification Receipt Contract** — distinguishes Gate, dispatch, effect, next state, and Safe Stop.

Internal W3b composition is implemented and deterministic-test verified. It is not a live proof or public integration: W4 legacy dispatch consolidation and W5 post-action semantic verification remain incomplete:

```text
Built-in fallback or trusted perception provider
                    │
        trusted adapter → Canonical UEI Evidence
                    │              (non-authorizing)
                    ▼
          Learning + Human Review
                    │
                    ▼
       Reviewed Workflow Asset + lineage
                    │              (non-authorizing)
                    ▼
Computer-Use Agent ◄── Observation / Receipt
        │
        └── semantic intent only ──► Runtime Authority
                                      │
                         current capture + relocation
                                      │
                               Gate + bounded attempt
                                      │
                       [internal Desktop I/O backend seam]
                                      │
                            Verify / Safe Stop / Receipt
```

Any Provider can target the architecture through a **trusted adapter** into Universal Evidence Interface v1 (UEI). Current proof covers local/static/Shadow paths, not a remote marketplace.

The current OmniParser path is a **review-only provider/shadow** prototype; it cannot authorize clicks.

<!-- UEI M2 conformance: 不是主叙事，也不是生产 Learn、GUI、replay 或 Execute 集成；不能成为点击授权。 -->

Future external Agents receive observations/actions and return observation-bound semantic intent. They cannot submit old coordinates, bypass Gate, or verify effects. No external/remote Provider or external Agent adapter is live-integrated today.

The Desktop I/O Backend SPI is an **internal implementation seam**, not a fifth public contract. W3b binds it only after passive bound-window capture, observed UIA origin, pinned recognition, current re-ground, Gate, and exact pre-dispatch pixel freshness; the Windows backend is one-shot and durable duplicate receipts prevent re-dispatch. The deterministic fake backend remains available for tests. Replacement must not expand authority.

## Honest status

| Capability | Status | What the claim means |
| --- | --- | --- |
| UEI schemas, refs, registration, static projections | **Current — Contract Proof** | Canonical, provenance-preserving, non-authorizing evidence boundary. |
| Reviewed Workflow v2 compiler and persistence | **Current — Contract Proof** | Offline compile/store/reload; publication grants no authority. |
| Agent Observation / Intent / Receipt schemas and W3b internal composition | **Partial — deterministic composition proof** | The internal path binds exact session/capture/SHA/viewport/HWND/PID identity, recomputes rank/margin, fails closed on zero/low/ambiguous anchors, and records duplicate-safe durable dispatch receipts. It has no public route or agent/demo callsite and is not live proof. |
| Bounded SEEK browser navigation recording | **Partial** | Bounded historical live GUI recording; not Portfolio v1 Controlled Live Workflow Proof. It does not prove saved-workflow replay or semantic verification. |
| Built-in perception baseline/fallback | **Partial** | Screenshot, UIA, OCR, and recognition exist; unfamiliar-interface reliability is unproven. |
| Built-in and OmniParser output entering one provider-neutral review model | **Partial** | UEI and Shadow foundations exist; the release vertical slice is not closed. |
| Human review and workflow creation | **Partial** | Review UI, revisions, and graphs exist; v1 proof is incomplete. |
| Mandatory current relocation, unique Gate dispatch, semantic verification, and durable live receipt | **Partial** | W3b proves the new internal controller path only. W4 remains Partial because legacy production mutation routes/clients can still bypass that owner; W5 semantic verification is not implemented. |
| Desktop I/O Backend SPI | **Partial** | Internal SPI, deterministic fake backend, and guarded one-shot Windows backend exist. It is not a public HTTP route, agent/demo callsite, or production-readiness claim. |
| Provider routing and remote providers | **Planned** | No automatic Provider fallback today. |
| Live external Computer-Use Agent adapters | **Planned** | None live-integrated today. |
| Production or unfamiliar-site reliability | **Not claimed** | No all-site or unattended claim. |

## Historical prototype evidence

> **Historical showcase evidence.** The screenshots below were published by the earlier public showcase repository and are included to show design lineage. They are **not current Portfolio v1 live proof**, and the current interface may differ. SEEK and all employer names and marks belong to their respective owners; no affiliation or endorsement is implied.

### SEEK reference states · Historical screenshots

<table>
  <tr>
    <td width="33%" align="center"><a href="docs/media/private-prototype-seek-results.png"><img src="docs/media/private-prototype-seek-results.png" alt="Historical private prototype showing SEEK results recognition" width="100%"></a></td>
    <td width="33%" align="center"><a href="docs/media/private-prototype-seek-job-detail.png"><img src="docs/media/private-prototype-seek-job-detail.png" alt="Historical private prototype showing the SEEK job-detail state" width="100%"></a></td>
    <td width="33%" align="center"><a href="docs/media/private-prototype-seek-application.png"><img src="docs/media/private-prototype-seek-application.png" alt="Historical private prototype showing redacted SEEK application entry" width="100%"></a></td>
  </tr>
  <tr>
    <td align="center"><strong>Results</strong><br>Search controls, result regions, and job-card evidence.</td>
    <td align="center"><strong>Job Detail</strong><br>Detail drawer, metadata, description, and separate Quick apply entry.</td>
    <td align="center"><strong>Application Entry</strong><br>Personal content is redacted. This shows document-selection entry only—not form completion, Continue/Next, or submission.</td>
  </tr>
</table>

### SEEK reference recording · Partial historical visual corroboration

![Historical SEEK three-state navigation recording](docs/media/seek-three-interface-real-agent-demo.gif)

This 16-second historical recording covers SEEK home/list, job detail, and same-site Apply entry; application content is redacted, with no fill, typing, upload, Continue/Next, or submission. It is bounded visual corroboration—not Portfolio v1 Controlled Live Workflow Proof. Without a matching current runtime trace and receipt, it does **not** establish which component produced each click or prove restart/reload, relocation, Gate lineage, semantic verification, receipts, or autonomous replay.

SEEK is a **reference workflow**, not the product. The v1 target is **Job Detail → `open_apply_flow` → Apply Entry → Safe Stop**. `open_detail` is a separate target proof, not homepage traversal.

## Engineering highlights

- **Freshness and lineage:** candidates bind capture, viewport, source, geometry, and freshness.
- **Revision-bound review:** evidence or semantic changes revoke stale approval.
- **Non-authorizing assets:** revisions preserve knowledge without becoming permission.
- **Semantic actions:** `open_detail` and `open_apply_flow` are distinct from field mutation, continuation, and terminal submission.
- **Fail-closed ambiguity:** stale/wrong/unknown/ambiguous states are zero-click outcomes.
- **Durable runtime receipts:** the internal controller persists exact dispatch/recovery outcomes and returns the same terminal receipt after duplicate/restart lookup. `DISPATCHED` remains `verification_pending`; W5 effect and destination proof are unfinished.

## Run locally

Requirements: Windows 10/11, Python `>=3.11,<3.12`, and `uv`.

```powershell
git clone https://github.com/Desolate-Jix/agent-gui-runtime.git
cd agent-gui-runtime
uv sync
.\start_test_panel.bat
```

Or start the local API directly:

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Model weights and optional vision services are not distributed. Do not commit private evidence or credentials.

## Target state and roadmap

These items are **Planned**, not current capability:

1. Close the Built-in/Omni -> UEI -> provider-neutral Review proof.
2. Close or hard-bound legacy production mutation routes/clients so the W3b controller is the unique dispatch owner (W4).
3. Add post-action capture and semantic effect/destination verification so `DISPATCHED` can become a verified receipt or Safe Stop (W5).
4. Run the controlled live SEEK reference proof only after W4/W5 close, with matched positive and zero-click negative-control receipts.
5. Only then consider more providers, Agent adapters, and workflow classes.

Automatic provider selection, remote execution, raw-coordinate Agent authority, ATS traversal, form filling, upload, Continue/Next, and final submission are not Portfolio v1 capabilities.

## Safety and non-goals

- Learning drafts, provider evidence, workflow graphs, and published assets never authorize action.
- `final_submit`, `send`, `confirm`, `payment`, and `delete` remain prohibited boundaries for this portfolio slice.
- Form fields, upload, and Continue/Next produce a Safe Stop in the v1 reference workflow; no form mutation belongs to the proof.
- A plausible model response is not permission. Unknown, stale, ambiguous, wrong-window, or unverified states stop rather than guess.
- This is not an unattended job-application service and does not claim coverage of all Windows applications, websites, models, or providers.

## Repository map

- `app/learn/` — evidence contracts, recognition, learning tasks, and review projections.
- `app/agent/` — reviewed workflow assets, semantic Agent contracts, replay, and receipt logic.
- `app/operation/` — window binding, observation, grounding, and operation boundaries.
- `app/gate/` — candidate, window, dataflow, and dangerous-action checks.
- `app/web_panel/` — local learning, review, and replay workspace.
- `schemas/uei/v1/` — Universal Evidence Interface contracts.
- `tests/` — contract, regression, and safety-boundary checks.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — detailed boundaries and invariants.
- [`CHANGELOG.md`](CHANGELOG.md) — release-scoped changes and limitations.
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) — optional component and license boundaries.

<details>
<summary>Synthetic framework evidence</summary>

![Synthetic framework demo](docs/media/demo.gif)

`demo.gif` proves only that the deterministic synthetic framework has click capability and can observe a synthetic result. It is **not** live GUI evidence and does not prove Agent behavior, model accuracy, human review, current relocation, or saved-workflow replay.

</details>

## License

[ISC](LICENSE)
