# agent-gui-runtime

**Version 0.3.0 · Windows GUI Agent Runtime**

[中文](README.md)

## Hero

> **The workflow reliability layer after GUI perception.**
>
> **A Windows GUI agent runtime that turns uncertain exploration into reusable, human-reviewed, runtime-relocated, and verifiable semantic workflows.**

Start with built-in Windows perception—screenshots, UIA, OCR, and local recognition—or bring an external provider. Provider-native output must pass through a trusted adapter into canonical UEI evidence before it can enter learning and review.

Foundation GUI models are evolving quickly; built-in perception is not this project's moat. The focus is durable, reviewed workflow knowledge: evidence that can be reused, relocated on the current interface, gated, and verified.

![SEEK recorded gated Agent path](docs/media/seek-three-interface-real-agent-demo.gif)

**Evidence grade: public, redacted, controlled SEEK Agent recording.** It shows only SEEK home → job detail → same-site Apply / Quick Apply entry: no form filling, typing, upload, Continue/Next, or final submission. It is not proof of autonomous end-to-end traversal of a saved workflow graph.

## Why GUI Agents Break

Perception can propose what may be on screen, but cannot alone prove that a click is correct, allowed, and effective in the current window. Interfaces change, windows switch, scrolling can affect the wrong container, and neither old coordinates nor one model response is execution authority.

## Core Lifecycle

    Explore → Capture Evidence → Human Review → Compile Semantic Workflow
    → Runtime Relocation → Safety Gate → Execute → Verify

1. **Explore** uncertain paths.
2. **Capture Evidence** with lineage.
3. **Human Review** semantics, candidates, transitions, scope, and risk.
4. **Compile Semantic Workflow** as a reusable asset, not a coordinate script.
5. **Runtime Relocation** against the current capture.
6. **Safety Gate** for a bounded allowed attempt.
7. **Execute** only through the gated action path.
8. **Verify** observed effect, or retain diagnostics and stop safely.

## What Makes This Different

- **Reviewed knowledge is durable** — reuse reviewed semantics, conditions, verification rules, and evidence lineage, not screenshot coordinates.
- **Evidence is not authority** — providers, models, old coordinates, and panel buttons cannot bypass the current Gate.
- **Relocation is runtime work** — saved geometry is only a prior.
- **Verification is part of the asset** — dispatch is not completion.
- **Perception is replaceable** — learning, review, compilation, and reuse keep a stable semantic boundary.

## Replaceable Perception, Durable Reviewed Knowledge

**Perception is replaceable. Reviewed knowledge is durable.**

A provider may use UIA, OCR, a parser, or a vision model. Learning need not know its internal output format or identity: trusted adapters convert native output into canonical, safe UEI evidence, which is reviewed before it can contribute to a semantic workflow.

### Provider Resolver (target modes)

| Mode | Intended role | Current status |
| --- | --- | --- |
| **Built-in** | Windows perception baseline. | **Partial**: baseline input, not proof of general live grounding. |
| **Primary** | Preferred main provider. | **Planned** |
| **Assist** | Supplemental/cross-check provider. | **Planned** |
| **Shadow** | Observe provider output without affecting execution. | **Prototype**: trusted local Shadow runtime only; review-only summary. |
| **Automatic** | Policy, health, and capability routing/fallback. | **Planned** |

This is not arbitrary API plug-and-play. There are no external/remote API adapters and no production Primary, Assist, or Automatic routing. UEI / OmniParser is a supporting Prototype, not the product protagonist.

### Provider Manifest + Evidence Contract

A Provider Manifest declares namespaced identity, version, profile, declared output kinds, coordinate spaces, capture support, privacy capabilities, and modes. The Evidence Contract records request/profile resolution, capture lineage, source/capture bounding boxes, proven transform references, safe text/roles/states, confidence, bounded attributes, redaction, immutable references, and runtime receipts.

Provider-specific extensions can enter only as bounded attributes; they cannot become action instructions. If coordinates cannot be proven to map to the **same exact capture**, the result remains review-only evidence.

> **A provider proposes evidence; it never authorizes action.**

It cannot click, choose a workflow node, bypass Gate, or mark an action verified.

### Minimal adapter shape (illustrative pseudocode)

    class ExampleParserAdapter:
        provider_id = "example.parser"
        profile_id = "example.parser/screen-v1"
        provider_version = "1.0"

        def invoke(self, *, capture, budget, invocation_id):
            native = parser.inspect(capture.local_path)
            return normalized_safe_evidence(native, capture, budget)

Target integration: declare a Manifest → implement a budgeted trusted adapter → project to canonical evidence while rejecting/redacting unsafe fields → provide coordinates only with a proven exact-capture transform → keep compilation, relocation, Gate, and Verify outside the adapter.

## SEEK Reference Workflow

SEEK is the **reference implementation**, not the product identity: **SEEK home → job detail → same-site Apply / Quick Apply entry**. It stops at application entry; it does not claim ATS end-to-end behavior, live safe-fill, unattended job application, or autonomous traversal of a saved workflow graph.

## Current Status

| Capability | Status | Evidence today | Not claimed |
| --- | --- | --- | --- |
| Reviewed workflow assets, revisions, and persistence | **Stable** | Reviewed assets, lineage, compilation, controlled persistence/tamper checks. | Published asset equals action authority. |
| Learning, human review, workflow creation | **Partial** | Display-only drafts, reviewed candidates, application-scoped review. | General visual understanding or real multi-window success rates. |
| Built-in perception baseline | **Partial** | Screenshots, UIA, OCR, local recognition as baseline evidence. | Reliable grounding on every current UI. |
| Gate and terminal-action handling | **Partial** | Terminal actions default fail closed; structured-authorization branch exists. | Globally Stable Gate for every site, control, or long flow. |
| Relocation, execution, verification, Agent integration | **Partial** | Controlled SEEK and offline/controlled replay cover parts. | Mandatory current grounding across every replay; verification cannot be disabled; complete live orchestration. |
| Scroll wrong-scope effect verification | **Partial** | Detection contract and regression path. | Closed effect-verification gap. |
| Trusted local Universal Evidence Interface v1 (UEI) / OmniParser Shadow | **Prototype** | Review-only summary projection. | Arbitrary API plug-and-play, external adapters, or complete UEI → Learn/Review/Compile/action wiring. |
| Deterministic synthetic demo | **Prototype** | Harness can click and observe a synthetic result. | Live GUI, real Agent behavior, model accuracy, or saved-workflow replay. |
| Primary / Assist / Automatic resolver, remote providers | **Planned** | Target design is explicit. | Implementation or validation today. |

## Architecture

    Built-in or trusted-provider perception
                ↓ canonical evidence + capture lineage
                ↓ learning workspace + human review
                ↓ reviewed semantic workflow + immutable refs
                ↓ current capture → relocation → Safety Gate
                ↓ bounded attempt → observation → Verify / safe stop

Learning, review, compiled assets, and stable reuse are central; perception is replaceable input. Runtime must prove conditions in the **current** target window.

## Engineering Highlights

1. Capture freshness and lineage prevent mixed old/new coordinates.
2. Revision-bound human review revokes stale approval.
3. Application-scoped review retains evidence per learned interface.
4. The canonical evidence boundary validates, bounds, and redacts provider output.
5. Current-UI relocation rebinds candidates instead of replaying geometry.
6. Gate-first execution defaults dangerous terminal classes to refusal.
7. Post-action evidence records a diagnosable safe stop when effect is unproven.

## Demo and Evidence

### Deterministic synthetic harness · synthetic depiction (15.0 s)

![Deterministic synthetic framework demo](docs/media/demo.gif)

demo.gif proves only that the deterministic synthetic framework/harness has click capability and can observe a synthetic result. It is a depiction; it proves neither live GUI reliability, real Agent behavior, model accuracy, human review, nor end-to-end replay of a saved workflow.

Public source: [demo.gif](https://github.com/Desolate-Jix/windows-gui-agent-runtime/blob/main/docs/demo.gif); SHA-256: 302e049140bc0a2868258ea55b25aec7d22279bfc0d27e46b04efa4d318e73c0.

### SEEK recorded gated Agent path · public redacted recording (16.0 s)

This GIF is in the Hero. Public source: [seek-three-interface-real-agent-demo.gif](https://github.com/Desolate-Jix/windows-gui-agent-runtime/blob/main/docs/seek-three-interface-real-agent-demo.gif); SHA-256: 80ab0a5055d0e700f009642bd414ffdbfef1426307537dfd976c822de9d88b4f. Its scope and no-form-action wording come from that public source repository; this repository does not independently claim complete frame-to-trace lineage or autonomous saved-workflow traversal.

## Run Locally

Requirements: Windows 10/11, Python >=3.11,<3.12, and [uv](https://docs.astral.sh/uv/).

    git clone https://github.com/Desolate-Jix/agent-gui-runtime.git
    cd agent-gui-runtime
    uv sync
    .\start_test_panel.bat

Or run: uv run uvicorn app.main:app --host 127.0.0.1 --port 8000.

## Target End State

Not yet implemented: provider routing/fallback receipts; external adapters; complete UEI → Learn → Review → Compile wiring; mandatory current grounding/verification across replay; live saved-workflow orchestration with a server-owned current-observation bridge; and closed-loop scroll wrong-scope effect verification.

## Safety and Non-goals

- This is not an unattended job-submission service; plausible model output is never execution permission.
- Learning drafts, PathGraphs, review outputs, and published workflows are non-authorizing assets.
- final_submit, send, confirm, payment, and delete default fail closed; structured authorization is not blanket permission.
- Generic requests use a bounded execution-attempt budget (default: at most 2); reviewed-workflow replay forces 1.
- No claim covers all sites, Windows applications, models, providers, or unattended workflows.

## Repository Map and Deep Dives

- app/learn/ — learning tasks, evidence contracts, recognition, review projections.
- app/operation/ — window binding, observation, localization, candidates, runtime action interfaces.
- app/gate/ — Safety Gate, dataflow contracts, terminal-action handling.
- app/web_panel/ — local learning, review, replay panel.
- app/learn/recognition/uei/ and schemas/uei/v1/ — provider manifests, canonical evidence, trusted adapters, Shadow prototype.
- tests/ — contract, regression, safety-boundary tests.
- [CHANGELOG.md](CHANGELOG.md) — narrow verification and limitations.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — optional components and license boundaries.

## Release and License

- Version: 0.3.0
- Root project license: [ISC](LICENSE)
- Changes: [CHANGELOG.md](CHANGELOG.md)

“Stable,” “Partial,” “Prototype,” “Planned,” and “Evidence” describe the current controlled scope, not a CI-backed production-reliability promise or general live-GUI success claim.
