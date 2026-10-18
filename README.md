2026-10-18: The sole local development checkout maintains execution mode on `codex/dev-execution-maintained`. Learning development is paused; source archive branches are pushed and superseded environments are backed up and retired. See [archive and recovery notes](docs/LEARNING_PAUSED.md). Installed applications are unchanged.

<div align="center">

**English** · [简体中文](README.zh-CN.md)

<h1>
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-hero.mobile.svg">
    <img src="docs/assets/readme-hero.svg" width="1120" alt="Agent Review Instant — Plan, Ground, Check, Act, Verify">
  </picture>
</h1>

**Execution 0.1.5 — run multi-step Windows tasks from your AI agent.**

Visual grounding finds the target. Decision checks the current step.<br>
Successful steps continue; unresolved cases return to your agent.

**[Download execution v0.1.5](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.5/AgentGUIRuntimeExecution-Setup-0.1.5-20261017-01.exe)** · [Demos](#demos) · [Quick start](#quick-start) · [Architecture](#architecture) · [Evaluation](#evaluation)

**Review, then continue the original input.** The original planning agent (Main) can inspect settled typed input and explicitly continue the same command without retyping. [Independent acceptance status and checksums →](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)

</div>

Agent Review Instant is a Windows computer-use runtime for MCP-compatible agents. Give it an explicit linear plan to navigate an application, click targets, replace text, press keys or scroll. It executes supported steps in one session and checks their results, reducing the need to return to the main agent after every successful action.

**API vision needs no local model weights or GPU.** Use an external vision API, your image-capable agent, or a local model. The **execution runtime 0.1.5** installs as a standalone component.

<a id="demos"></a>

## Demos (0.1.4)

These **0.1.4** demos are compressed previews of the published videos, with lower resolution/frame rate and **no playback acceleration**. Browser and Notepad clips trim the initial wait; GIF length is not a performance measurement. [Full videos and actual plan timings →](#evaluation)

<p align="center">
  <a href="https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Browser.mp4">
    <img src="docs/assets/demos/browser-0.1.4.gif" alt="Browser: Google URL, java search, first ordinary result">
  </a>
</p>

Google URL → search java → open the first ordinary result. [Full MP4](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Browser.mp4)

<p align="center">
  <a href="https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4">
    <img src="docs/assets/demos/notepad-0.1.4.gif" alt="Notepad: edit a note, open File, Save">
  </a>
</p>

Edit a note → File → Save. [Full MP4](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4)

<p align="center">
  <a href="https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-7Zip.mp4">
    <img src="docs/assets/demos/7zip-0.1.4.gif" alt="7-Zip: navigate folders and a prepared ZIP">
  </a>
</p>

Navigate A → nested → Up → root → B → bundle.zip. [Full MP4](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-7Zip.mp4)

## What you can do

| Capability | What it means in practice |
| --- | --- |
| **Keep a task moving** | Run multi-step tasks continuously in the same session—for example, open a search engine, enter a query and follow a result. |
| **Check the step that just happened** | Ground targets from screenshots. Use cropped, annotated evidence to check a target or the requested result with Decision. |
| **Recover with the original agent** | If Decision does not accept, the standard Luna vision model reviews the same evidence once. Unresolved cases return with evidence; after reviewing it, the original agent can explicitly continue without replaying completed actions. |

<a id="quick-start"></a>
## Quick start

You need **Windows x64, Python 3.11, [uv](https://docs.astral.sh/uv/getting-started/installation/)** and an MCP-compatible agent. The installer includes source and setup scripts; first-time setup installs dependencies. Keys and model weights are not bundled.

1. **[Download and install execution 0.1.5](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5).** Check its release notes for checksums and independent final-package acceptance status.
2. **Choose your vision source.** For external Luna + Decision, copy the [vision profile](configs/vision-api-openai-luna.example.json) and [Decision profile](configs/decision-profile.visual-execution.example.json), then make `OPENAI_API_KEY` available to the MCP process.
3. **Run setup and connect your agent.** Follow the [setup commands](docs/EXECUTION_GUIDE.md#install-and-configure), merge the generated `agent-review-instant` MCP entry into your client, and reconnect. Keep other server entries intact.

| Vision source | Local model required? | Setup |
| --- | --- | --- |
| External API | No | [API profiles and credentials](docs/development/EXTERNAL_VISION_API.md) |
| Current agent or reusable visual subagent | No | [Agent integration](AGENT_GUIDE.md) |
| Local VISTA-4B | Yes | [Local setup](FRIEND_SETUP.md) |

Default visual input sequences require Decision in auto mode. Without Decision, basic actions and explicit legacy/native routes remain available with main-agent review; the runtime does not silently switch routes. All routes require the local Windows runtime. API usage is billed by the provider.

**Provider configuration in 0.1.5:** Decision and secondary review each support their own endpoint, model and key environment variable. Defaults remain OpenAI Decisions + ordinary Luna; replacements require Decisions/Responses-compatible services. These settings first shipped in the 2026-10-15 rebuilt 0.1.3 installer. [Configuration and compatibility →](docs/development/DECISION_PROVIDERS.md)

**Amadeus/Pi:** download the [MCP + Pi Skill extension 0.0.2](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.5/amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl) and follow the [extension guide](integrations/amadeus/agent-review-instant/README.md). It requires a compatible Host and an existing Runtime installation; no plugin store is needed.

<a id="evaluation"></a>
## Engineering evidence

**0.1.5 refresh — build 20261017-01:** adaptive observation after Enter and next-step read-only grounding alongside current-result verification. The refreshed installer completed the following tasks on the same frozen payload:

| Installed task | Round 1 | Round 2 | API requests, both rounds | Reported tokens, both rounds |
| --- | ---: | ---: | ---: | ---: |
| Notepad: edit → File → Save | **20.744 s** | **18.191 s** | 21 | 37,482 |
| Edge: Bing → search → Wikipedia article | **27.043 s** | **27.430 s** | 27 | 42,111 |
| 7-Zip: folder / prepared-ZIP navigation | **25.918 s** | **24.324 s** | 18 | 47,585 |

**Six plans / 18 steps completed automatically on their first attempt.** Main checked Notepad and Edge; independent Sol checked 7-Zip. Original screenshots, exact Notepad disk contents and owned-window/host cleanup passed. Each run above is a complete three-step plan including visual verification; launch, between-round inspection and cleanup are excluded from its time. 7-Zip compression/extraction was not tested.

The installed runs used **66 API requests: 18 grounding + 46 Decision + 2 ordinary review; 127,178 reported tokens**, with no missing usage. Consumed prefetch copies are counted once; Main/worker subscription usage is excluded. These scoped passes do not establish a general success rate.

**Measured action intervals, source A → B:** **5.803→5.597 s (Notepad), 7.805→7.254 s (7-Zip), 10.786→9.280 s (Edge)**. These are medians from the first physical mouse-down of one logical step to the next, four matched intervals per application/arm. A already includes the earlier ordinary-click/SSL changes; B adds Enter observation and overlap. This is not a direct old-installer/new-installer comparison. One Edge B plan was slower than A; model/network/cache variation was uncontrolled. **The four-second interval objective is not yet reached.** Models, prompts and acceptance rules are unchanged.

**Verification:** 395 affected checks passed; after race fixes, 82 overlapping checks passed (not added as unique tests). All **659 installed payload hashes** matched before/after acceptance. A new isolated Python 3.11 environment installed **45 locked API-route dependencies** and passed functional-entrypoint checks. [Full measurements, source-comparison usage and limits →](docs/verification/EXECUTION_015_REFRESH_20261017.md) · [Dated installer and checksums →](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)

**Original 0.1.5 build, installed Amadeus/Pi route:** two normal synthetic Notepad tasks completed six steps, exact disk checks and cleanup; no Main semantic override was needed, and outer self-corrections remain recorded. Final source regression: **135 passed**. The final installer independently completed a three-step Notepad plan on its first attempt in **27.70 s / 10 API requests**, with exact disk output and cleanup. This is one scoped sample; total token usage is unknown. [Scope and limitations →](docs/verification/AMADEUS_PI_MAIN_REVIEW_20261015.md) · [Release and checksums →](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)

**Historical 0.1.4 installed tasks, beyond the browser:** fresh Notepad and 7-Zip tasks used the maintained visual execution route.

| Task | Observed result | Plan time |
| --- | --- | ---: |
| Notepad, first round: edit → File → Save | All 3 steps completed automatically; saved UTF-8 alpha content matched exactly | 30.621 s |
| Notepad, same-window second round | All 3 steps completed automatically; saved UTF-8 beta content matched exactly | 22.873 s |
| 7-Zip: A → nested → Up → root → B → bundle.zip | All 6 steps completed automatically; the archive's package folder was visible | 69.515 s |

All 12 installed steps completed without Main review; one ordinary review resolved automatically. Owned-window closure and host cleanup passed. Independent Sol then completed fresh 3-step Notepad and 3-step 7-Zip tasks, with disk/image checks and cleanup. The 7-Zip scope is directory/prepared-ZIP navigation; compression and extraction were not tested.

**Historical 0.1.4 recorded demos:** [Notepad, full window](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4) · [Browser](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Browser.mp4) · [7-Zip](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-7Zip.mp4). The new Notepad/Browser clips skip the initial wait, retaining about one second before first input; later actions and waits play at **1× speed**, with no narration. Clip lengths are **19.8 s / 27.2 s**; the original complete three-step plans took **28.0 s / 31.4 s**. [Recording scope and edits →](docs/verification/DEMO_RECORDING_20261015.md)

Separate historical 0.1.4 source02 evidence covers a **12-step plan plus 4-step continuation**. Nonempty linear plans have no fixed step-count cap; budgets and evidence checks remain. Earlier source false rejection and public-client receipt-cap failures remain recorded as failures. [Current results, exact timings and failure history →](docs/verification/MULTI_APP_EXECUTION_20261015.md) · [Long-plan regression →](docs/verification/UNBOUNDED_TASK_PLANS_20261015.md)

**Historical 0.1.3 browser task:** the installed candidate completed Bing → Rust collections documentation twice in the same window/session, in **30.809 s / 27.354 s**, using **41,097 API tokens**, without Main intervention or ordinary Luna review. These are historical task-specific times, not a controlled speed comparison; token totals exclude Main/worker subscription usage. [Timing and recovery evidence →](docs/verification/EXECUTION_SPEED_20261015.md) · [Operation breakdown →](docs/verification/EXECUTION_OPERATION_TIMINGS_20261015.md)

Historical 0.1.3 prompt evaluation used **39 real UI screenshots across 30 scenario families**. On the held-out set, three-way label agreement rose from **92.5% to 95.0%**, with **1.64% fewer Decision input tokens**. Pass/nonpass accuracy stayed at 95%; the two-stage result stayed at 149/160, including 7 false accepts and 1 false rejection with the adopted prompts. Labels were AI-reviewed: **these are not general GUI success rates**. [Method, split and failure cases →](docs/verification/DECISION_PROMPT_BENCHMARK_20261015.md)


<a id="architecture"></a>
## How it works

**User task → Main-agent plan → Ground → Check → Act → Verify → Continue**

The vision model supplies coordinates. OpenAI's Decisions API checks the target or the current step's result using Choice. A valid pass continues the plan; a nonpass gets one ordinary Luna review before returning to the original main agent if unresolved. Decision does not replace the planner.

The runtime binds evidence to the request, window and screenshot, and validates coordinates and freshness. Default execution uses the visual route; UIA remains available through explicit native routes. Keep one persistent session and one desktop input owner.

**In 0.1.3:** shared observations, preloaded plans and reused HTTP connections reduce repeated preparation. The installed two-round task avoided 10 redundant outer captures. Evidence-bound continuation lets the main agent review a completed step without repeating its action.

**0.1.5 — Main review:** after authenticated dual-model nonpass on settled typed input, inspect the bound image and explicitly continue the same command without retyping. Remaining submit actions retain their fresh-target and verification gates. Earlier live04 recovery used explicit TEST injection on an unreleased payload; it is not a natural-error or performance result. [Contract →](docs/development/MAIN_FIELD_REVIEW_RESUME.md) · [Acceptance and limits →](docs/verification/AMADEUS_PI_MAIN_REVIEW_20261015.md)

[Detailed execution flow →](docs/EXECUTION_GUIDE.md#how-decision-and-the-vision-model-work-together) · [Task-plan contract →](docs/development/TASK_PLAN.md) · [Choice contract →](docs/development/DECISION_CHOICE.md)

## Current limits

- **Since 0.1.4, linear plans:** nonempty plans have no fixed step-count cap. Unique step IDs, per-step verification, context-size limits, evidence checks, cancellation and API/time budgets remain. Existing 0.1.3 installations retain their build-time contract until upgraded. [Source checks](docs/verification/UNBOUNDED_TASK_PLANS_20261015.md)

- Models can reject correct evidence or accept incorrect evidence. A primary false pass skips secondary review; this remains a known limitation. Arbitrary unattended tasks are not guaranteed.
- The installer is unsigned. This refresh verified a new isolated Python environment; clean-machine dependency setup and normal OS registry/shortcut integration were not newly verified. [Release scope and history](docs/EXECUTION_GUIDE.md#release-boundaries-and-history)

## Documentation

| Start using it | Understand and integrate |
| --- | --- |
| [Installation guide](FRIEND_SETUP.md) | [Execution guide and detailed flow](docs/EXECUTION_GUIDE.md) |
| [Agent / MCP guide](AGENT_GUIDE.md) | [Decision API configuration](docs/development/DECISION_API.md) |
| [External vision API](docs/development/EXTERNAL_VISION_API.md) | [Visual text input](docs/development/VISUAL_EXECUTION_INPUT.md) |
| [0.1.5 release notes and checksums](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5) | [Historical 0.1.4 multi-application evidence](docs/verification/MULTI_APP_EXECUTION_20261015.md) |

---

[ISC License](LICENSE). Dependencies and model weights retain their own licenses. The banner illustrates the workflow; it is not a recorded run.

## Optional benchmark data

The [benchmark backup](https://github.com/Desolate-Jix/agent-gui-runtime-benchmarks) is available in a separate **public repository**. The frozen suite contains **39 original screenshots, 30 interface families and 254 labelled cases**. Dataset images, annotations and raw evaluation records are not bundled with the execution installer or downloaded during setup. Clone separately when needed.
