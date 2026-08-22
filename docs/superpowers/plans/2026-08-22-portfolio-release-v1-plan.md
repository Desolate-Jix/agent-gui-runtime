# Portfolio Release v1 — Frozen Project Plan

**Status:** Frozen planning baseline<br>
**Plan date:** 2026-08-22<br>
**Release target:** 2026-09-13<br>
**Scope owner:** Main Codex / repository owner<br>
**Change rule:** After this document is accepted, only verified runtime failures may change tasks. They must not redefine the product or expand the release scope.

## 1. Frozen Product Position

### Target product definition

> **A model- and agent-agnostic Windows GUI workflow runtime that turns replaceable perception into human-reviewed operational knowledge and exposes gated, verifiable semantic actions to interchangeable computer-use agents.**

> **Reviewed workflows constrain and inform the Agentic Loop; they never replace current observation or authorize execution.**

中文：

> **一个模型与 Agent 无关的 Windows GUI 工作流 Runtime：把可替换感知产生的不确定证据转化为经人工审核的操作知识，并向可替换的 Computer-Use Agent 提供受 Gate 约束、可验证的语义动作。**

The runtime normalizes provider-supplied evidence, compiles durable reviewed workflow assets, accepts semantic agent intents rather than historical coordinates, re-grounds each permitted action against the current interface, gates execution, verifies the observed effect, and returns an auditable receipt.

“Learning” 在本项目中指 **capture、review、compile 和 reuse operational GUI knowledge**，不是训练 foundation model。

### Product boundary

本项目不与大厂持续竞赛基础视觉模型能力，也不制造另一个 Computer-Use foundation model。它位于 perception / computer-use agent 与真实 Windows GUI 之间，负责：

```text
Replaceable Perception
        ↓
Canonical UEI Evidence
        ↓
Learning + Human Review
        ↓
Reviewed Workflow Asset
        ↓
Reliability Runtime
        ↕
Observation / Intent / Receipt
        ↕
Interchangeable Computer-Use Agent
```

### Three authority rules

> **Providers propose evidence.**<br>
> **Agents propose intent.**<br>
> **The runtime grants bounded execution authority.**

模型的 confidence、Agent 的决策、历史 bbox 或旧 click point 均不能直接授权真实动作。

## 2. Four Stable Contracts

### Contract 1 — Perception Provider Contract

```text
Provider-native output → trusted adapter → Canonical UEI Evidence
```

- Provider 原始能力不需要相同。
- UEI 统一 capture identity、coordinate space、elements/regions、provenance、provider revision、confidence 和可选 evidence extensions。
- Provider 结果保持 `review_only`；不能产生 `approved_to_click`。
- Portfolio v1 证明 Built-in 与 OmniParser recorded/Shadow 两条输入，而不是宣称通用 live provider marketplace。

### Contract 2 — Reviewed Workflow Asset Contract

```text
Reviewed evidence → semantic states/transitions → durable reviewed asset
```

资产包含语义状态、动作、anchors、preconditions、expected effects、verification policy、risk boundary、safe stop、provenance、revision/hash。Historical coordinates may be retained as evidence or relocation hints, but never as executable authority.

### Contract 3 — Agent Runtime Contract

Runtime 面向 Computer-Use Agent 输出当前 `Observation` 与可用语义动作；Agent 仅返回 `Action Intent`，例如 `open_apply_flow`，不能绕过 Runtime 直接提交历史坐标。

Portfolio v1 只要求：

- `agent_observation_v1`；
- `agent_intent_v1`；
- 当前内部 Agent adapter 通过 conformance test；
- 未知 action、过期 observation、越权参数 fail closed。

第二个外部 Computer-Use adapter 是 stretch，不是 release blocker。

### Contract 4 — Runtime Result & Verification Receipt Contract

每次 intent 必须得到结构化 receipt，而不是仅返回 `success: true`：

```text
intent → current capture → re-ground → Gate → execute → verify
       → execution receipt + verification receipt + next observation / safe stop
```

Receipt 至少绑定 request/intent、workflow revision、observation/capture、current candidate、Gate decision、bounded action、expected/observed effect、next state、safe-stop status 和 trace ref。

## 3. Evidence Grades

公开材料和 release acceptance 只使用以下等级：

1. **Contract Proof** — schema、conformance、fail-closed unit/integration tests。
2. **Recorded Provider-Output Conformance Proof** — 固定且可复查的真实 provider 输出通过 adapter/UEI；不得称为 live integration。
3. **Local Live Provider Smoke** — 本地模型真实推理；资源允许时可提供，不是 v1 blocker。
4. **Controlled Live Workflow Proof** — 当前窗口真实 capture、re-ground、Gate、动作和语义效果验证。

Fixture、recorded replay、synthetic harness 和 live GUI 证据必须分别标记，不能合并成一个成功率或泛化 claim。

## 4. Current State Snapshot

状态仅描述 2026-08-22 当前工作树，不把 Target State 当成已实现。

| Area | Status | What is actually working | Current boundary |
|---|---|---|---|
| Built-in screenshot / OCR / UIA / recognition | Partial | 受控 capture、OCR/UIA 候选与 recognition path 可用 | 通用识别质量与陌生界面可靠性未证明 |
| UEI v1 canonical schemas/store/registry/projections | Stable — offline contract | immutable refs、trusted registration、OCR/UIA/parser projection、fail-closed tests | 当前为离线/Shadow 合同，不授权动作 |
| OmniParser Shadow adapter | Implementation stable — release conformance pending | bounded trusted local Shadow path、recorded/fake-worker contract tests | 真实 cold + 3 warm inference 因 GPU free memory `< 8 GiB` 未验证；先前 README wording failure 已修复，但 release conformance receipt 仍待完成 |
| UEI → Learning | Prototype | Draft 可显示 compact `uei_shadow_provider_summary_v1` | 未进入完整 review/compile/action-candidate 主链 |
| Learn Mode / human review / workflow graph | Partial | review workspace、节点/边编辑、人工确认和历史工作流 UI 存在 | 当前资产链条较多，release 纵向 slice 尚未统一 |
| Reviewed Workflow v2 compiler/store | Stable — offline contract | fail-closed compile、CAS-style immutable storage、preview/reload tests | production live replay orchestrator 缺失 |
| Agent-facing Observation / Intent contract | Current — internal composition proof; public/live integration pending | `agent_observation_v1` / `agent_intent_v1` closed schemas、strict validators，以及 server-owned/server-loaded reviewed context → Observation adapter，已经由 W3b composition 消费；Session/intent identity、current capture/state/fact freshness、integrity 与 geometry-free action projection 均 fail closed | 无 public route、external Agent/demo callsite 或 Controlled Live Workflow Proof |
| Runtime Result & Verification Receipt Contract | Partial — deterministic internal W5 proof; live/public pending | durable verification checkpoint 先于 fresh C2；server-side target-state verification 只接受 compiler-emitted `target_state_identity`，并将 exact checkpoint 配对到 `VERIFIED`、dispatched `SAFE_STOP` 或 `VERIFICATION_FAILED` terminal；restart lookup zero redispatch | actual-adapter `open_apply_flow` → application-entry stop-boundary、Controlled Live Workflow Proof 与 public/demo callsite 尚未证明 |
| Current capture / runtime relocation | Current — verified internal W4 proof | W3b 使用 server-owned passive bound-window capture、exact session/capture/SHA/viewport/HWND/PID、current re-ground 与 pre-dispatch pixel freshness；旧坐标不授予 authority | 尚无 Controlled Live Workflow Proof 或 live SEEK receipt |
| Gate / zero-click rejection | Current — verified internal W4 proof | 只有 `LiveController` mint authority；Windows backend 是唯一 scope caller；所有 raw input sinks leading-guard；stale/wrong/ambiguous/unsupported paths zero dispatch | 内部 deterministic/code-audit proof，不是 public/live integration |
| Semantic effect verification | Partial — deterministic internal proof | internal W5 对 fresh C2 执行 closed target-state identity verification；production evidence-adapter 类在确定性依赖下从未经修改的 compiler asset 让 `open_detail` 到达 `VERIFIED` | `open_apply_flow` 的 actual-adapter stop-boundary 与真实 SEEK before/after semantic evidence 尚未证明 |
| Safe stop | Partial | controller 对已派发且解析到 `stop_boundary` 的目标产生 exactly paired terminal `SAFE_STOP`，verification failure 同样 fail closed | actual-adapter `open_apply_flow` → application-entry safe stop 与 controlled live receipt 尚未证明 |
| Trace lineage | Partial | internal W5 已绑定 workflow/intent、C1 selection/current grounding、Gate、backend receipt、fresh C2 verification、next observation 与 exact terminal receipt | 尚无 public/live workflow trace graph 或 Controlled Live Workflow receipt |
| Public demo | Partial | controlled GIF / two bounded SEEK actions 已有记录 | 不是完整 semantic workflow replay，也不是 unattended apply |

### Verification baselines

- **Earlier release-focused UEI checkpoint:** `109 passed, 1 failed`；唯一失败是 README 缺少 `Universal Evidence Interface v1` 文案。该文案现已补齐，当前 `tests/test_uei_v1_static_conformance.py` 为 `5 passed`；这证明静态 conformance 已恢复，不冒充完整 UEI suite 重跑。
- **Last full offline repository baseline:** Python `2762 passed, 1 skipped`；JavaScript `128 passed, 0 failed`。这是完整离线回归基线，不是 live SEEK 或 Portfolio v1 live-controller 证明。
- **Portfolio v1 Contract Foundation:** schema/validator、server-owned/server-loaded reviewed-context Observation adapter（current capture/state/fact freshness 与 integrity bindings、geometry-free action projection、blocker/state fail-closed）、reviewed replay Receipt adapter（validated reviewed asset + strict post observation 内部重算 existing replay verifier、canonical application/source/next-observation lineage、拒绝 unproven dispatch/Gate 与 arbitrary operation refs）组成的 focused combined suite 为 `394 passed, 2 skipped`。它证明 offline Contract Foundation 与真实代码边界映射，不证明 Live Controller、Session mutation ledger、唯一 Gate dispatch、GUI dispatch、backend receipt、semantic verification owner 或 durable runtime persistence。
- **Release-focused W3b/W4 implementation proof:** `595 passed, 3 skipped in 25.10s`。它覆盖 internal composition、durable dispatch receipt、current re-ground/freshness 与 unique raw-input authority；独立严格审计为 PASS，W4 Stop Condition MET。它是保留的历史 focused baseline，不是 full-repository baseline 或 live Windows/SEEK proof。
- **Release-focused W5 + actual-adapter composition proof:** compiler/replay/Observation/claim/receipt/controller/Gate/composition suites 为 `351 passed, 2 skipped in 23.65s`。production `ExistingWindowsCurrentEvidenceAdapter` 类在 deterministic window/screenshot/UIA/recognition doubles 与 `DeterministicFakeBackend` 下消费未经修改的 compiler asset，使 `open_detail` source → target 到达 `VERIFIED`，restart 返回 exact receipt 且 zero redispatch。它不是真实 Windows/SEEK I/O、physical Windows dispatch + C2、Controlled Live Workflow Proof、public integration、external Agent integration 或 full-repository baseline。

## 5. Portfolio v1 Proofs

### Proof A — Replaceable perception boundary

```text
Built-in ──────┐
               ├→ UEI → Same provider-agnostic Review Model
Omni recorded ─┘
```

必须证明：Built-in 和 OmniParser recorded/Shadow output 经过同一 UEI core contract；Review 不读取 provider-native payload，也不按 provider 创建 Learning 分支。

**Mandatory evidence:** Adapter Contract Validation / Recorded Provider-Output Conformance Proof。<br>
**Optional evidence:** Local Live Provider Smoke。

### Proof B — Core controlled live workflow

```text
Reviewed Job Detail state
        ↓
Save / process restart / Reload
        ↓
Current Capture + Re-ground
        ↓
Gate
        ↓
open_apply_flow
        ↓
Semantic Verify: Apply Entry
        ↓
Safe Stop
```

Reference scope 是受控的 **SEEK Job Detail → Apply Entry → Safe Stop**。`open_detail` 作为一个独立、受控的 semantic-effect proof 保留，用于证明当前候选可打开预期 Job Detail；它不属于 Proof B 的连续主链，也不能重新引入 Homepage/list traversal。Homepage 只有在完全不引入 scroll、列表遍历、virtualization、ranking/filtering 或 infinite scroll 时才可作为 stretch。

### Proof C — Agent-side boundary

```text
Runtime Observation
        ↓
Current internal Agent Adapter
        ↓
Semantic Intent only
        ↓
Runtime Result & Verification Receipt
```

Portfolio v1 不要求 OpenAI/Qwen/Anthropic 的真实外部 adapter。它要求 northbound contracts、current-adapter conformance、fail-closed negative controls，以及 Proof B 的 receipt evidence。

## 6. Core Runtime Acceptance Matrix — 12 Release Predicates

估算等级：`S < 2h`、`M = 2–6h`、`L = 6–12h`、`XL > 12h / scope risk`。同一底层工作会覆盖多项，因此不得把每行 estimate 直接相加。

| # | Acceptance | Current | Exact gap / minimal work | Primary files / evidence | Dependency | Required acceptance evidence | Estimate |
|---|---|---|---|---|---|---|---|
| 1 | Built-in output enters UEI | Partial | 把真实 Built-in result 投影到 UEI ref，并由同一 review projection 消费；不只显示 Shadow summary | `app/learn/recognition/uei/projections.py`, `app/learn/workflow_tasks/recognition.py`, `app/learn/draft_review.py` | UEI schemas/store | Built-in fixed capture → sealed UEI result → review projection conformance | M |
| 2 | OmniParser recorded/Shadow output passes same UEI contract | Implementation stable — release conformance pending | 固定 path-neutral recorded output并输出可发布 receipt；把 live smoke 保持 optional；README conformance wording 已修复 | `app/learn/recognition/uei/omniparser_shadow_adapter.py`, UEI tests/fixtures | none; #3 consumes shared review projection | Recorded Provider-Output Conformance Proof + failure receipt | S |
| 3 | Review UI has no provider-specific Learning branch | Partial | UI 只读 canonical review model；provider 仅作为 provenance 展示 | `app/web_panel/panel.js`, `app/web_panel/learning_workflow_review.js`, JS tests | #1–2 | 两 provider fixture 投影得到同一 UI model；无 provider branch test | M |
| 4 | Human review forms a reviewed workflow | Partial | 收缩成 Job Detail、Apply Entry 两状态，一个 `open_apply_flow` transition 和一个 stop boundary；独立 `open_detail` proof 使用独立 reviewed source/target，不接入主链 | review UI, `app/agent/reviewed_workflow_compiler.py` | #1–3 | Panel/API review → compile-ready source with reviewed node/edge hashes | M |
| 5 | Asset survives save, process restart and reload | Stable — offline; release proof pending | 用 release slice 做独立进程 round-trip，并验证 exact revision/hash | `app/agent/reviewed_workflow_asset.py`, `app/api/panel.py`, v2 tests | #4 | save → restart → load exact immutable asset/active revision | S |
| 6 | Runtime uses current window capture | Current — verified internal W4 proof | W3b server-owned passive capture 与 exact session/capture/SHA/viewport/origin/HWND/PID binding 已实现并 fail closed | W3b composition/current-evidence tests + strict W4 audit；live receipt 留给 Controlled Live Workflow Proof | L |
| 7 | Action is re-grounded before dispatch | Current — verified internal W4 proof | reviewed semantic target 只经 current pinned recognition/ranking 与 exact pre-dispatch pixel freshness 产生当前 click point；历史 bbox 不授予 authority | current-grounding/freshness positive and stale negative tests；internal W5 已闭合，live effect 留给 Controlled Live Workflow Proof | L |
| 8 | Stale/wrong/ambiguous means zero click | Current — verified internal W4 proof | freshness、window identity、lineage、score ambiguity 和 unsupported backend capability 均 fail closed、zero dispatch | matched deterministic negative controls + strict W4 audit；不是 live proof | M |
| 9 | Every real action passes Gate | Current — verified internal W4 authority proof | only `LiveController` mints one-time authority；only `ExistingWindowsBackendAdapter` enters authority scope；all raw sinks leading-guard；scripts zero raw dispatchers；SEEK `WM_CLOSE` disabled | authority audit/tests + one-step dispatch budget；Controlled Live Workflow receipt 仍待收集 | L |
| 10 | `open_detail` / `open_apply_flow` have real semantic verification | Partial — deterministic `open_detail` composition proof | compiler/controller/production evidence-adapter class 已用 fresh C2 与 closed target identity 使未经修改的 `open_detail` asset 到达 `VERIFIED`；禁用/失败不得写 verified | W5 focused suites + actual-adapter composed test；真实 SEEK evidence 与 `open_apply_flow` stop-boundary 仍待证明 | #9 | before/after semantic evidence + expected-effect assertion for both actions | L |
| 11 | Safe stop at application entry | Partial | controller 内部可将 verified stop-boundary 绑定为 terminal `SAFE_STOP`，且无 blind redispatch | actual-adapter `open_apply_flow` → application-entry stop-boundary 和 controlled live receipt 仍待证明 | #10 | `safe_stop=true`, reason/boundary, zero later action | M |
| 12 | Trace follows workflow to observed effect | Partial — deterministic internal lineage proof | internal W5 已统一 workflow/asset revision、observation、intent、candidate、Gate、backend、verification checkpoint、C2 与 terminal refs | public/live end-to-end trace graph 仍待证明 | #5–11 | one replay trace graph with resolvable hashes/refs end to end | M |

## 7. Boundary Contract Acceptance — 4 Additional Gates

这些 gates 不增加新的实际 GUI 行为；它们把 Proof B 已有输入/输出固定成可替换 Agent 能消费的稳定边界。

| ID | Contract gate | Current | Minimal v1 proof | Estimate |
|---|---|---|---|---|
| N1 | `agent_observation_v1` | Current — internal composition proof; external/live integration pending | 版本化 schema 包含 workflow/revision、application/current-state identity、current capture、semantic facts/evidence、blockers、eligible reviewed actions、expected effect、verification、risk/safe-stop boundary；W3b Observation adapter 使用 server-owned/server-loaded reviewed context并对 blocker/state fail closed | 已纳入 W3a/W3b；无 public/external Agent callsite 或 live proof |
| N2 | `agent_intent_v1` | Current — internal composition proof; external/live integration pending | Agent 只提交 observation-bound semantic action id；unknown/stale/cross-workflow intent、raw coordinate authority 与越权 parameters 均拒绝；W3b controller 已消费该 intent | 已纳入 W3a/W3b；无 public/external Agent callsite 或 live proof |
| N3 | `runtime_result_receipt_v1` | Partial — deterministic internal W5 proof; live/public pending | 七类 outcome matrix 严格区分 Gate、dispatch、effect、destination；durable checkpoint → fresh C2 → exact semantic terminal 已组合，duplicate/restart 不 re-dispatch | actual-adapter `open_apply_flow` stop-boundary、public callsite 与 Controlled Live Workflow receipt 仍待证明 |
| N4 | Current internal adapter conformance | Current — deterministic actual-adapter composition proof | server-loaded reviewed context → Observation → Intent → current re-ground → Gate → one-shot fake backend → fresh C2 → exact `VERIFIED` terminal 已由 production evidence-adapter 类和未经修改的 compiler asset 组合；W4 authority Stop Condition MET | 无 public/external Agent callsite、physical Windows dispatch + C2 或 live workflow proof |

**Stretch only:** 第二个 Computer-Use adapter。<br>
**Roadmap only:** raw click/scroll/type computer-use bridge、remote agents、MCP/router、automatic provider selection。

## 8. Minimal Workstreams and Dependencies

### W0 — Position and acceptance freeze

- 本文件是 release 的 canonical plan。
- 同步 `PROJECT_SUMMARY.md`、`ARCHITECTURE.md`、`CURRENT_STATE.md`、`NEXT_STEPS.md` 的顶部 snapshot。
- README 保持暂停，直到纵向证据完成后再重写 claims。

### W1 — Perception-side contract proof

完成 #1–3。Built-in + Omni recorded/Shadow → UEI → same review model。<br>
**Can run in parallel with W2.**

### W2 — Reviewed asset release slice

完成 #4–5。只创建 detail → apply entry → stop 的最小 reviewed workflow。<br>
当前 `open_apply_flow` fixture/ignored artifacts 不满足 Agent Observation confirmation、risk 与 reviewed-release 要求；必须先形成 human-reviewed Job Detail → `open_apply_flow` → Apply Entry stop-boundary release asset，并完成 save/process restart/exact reload。<br>
**Feeds server-owned confirmation and the bounded local public/demo callsite.**

### W3a — Agent-side schemas and offline validation

先完成 N1–N3 的 versioned schema、strict validation 与 offline conformance。不得新增第二个 Computer-Use Agent adapter。<br>
**2026-08-22 update:** N1–N3 schema/validator 已冻结；server-owned/server-loaded reviewed context → Observation 已绑定 current capture/state/fact freshness 与 integrity，输出 geometry-free action projection，并对 blocker/state fail closed；validated reviewed asset + strict post observation → Receipt 会内部重算 existing replay verifier，绑定 canonical application/source/next-observation lineage，并拒绝 unproven dispatch/Gate 与 arbitrary operation refs。focused Contract Foundation 为 `394 passed, 2 skipped`；仅为 offline Contract Foundation，不含 Live Controller、Session mutation ledger、唯一 Gate dispatch、Gate 行为修改、真实 SEEK 点击、backend receipt、semantic verification owner 或 durable receipt store。<br>
**Can start with W1; feeds W4.**

### W4 — Mandatory current relocation and Gate

完成 #6–9。server-owned current observation、re-ground、fail-closed negative controls、所有动作 Gate。<br>
**2026-08-22 final audit update — Stop Condition MET:** W4 is **Current — verified internal authority proof**. Only `LiveController` mints one-time authority; `ExistingWindowsBackendAdapter` consumes it first and is the sole authority-scope caller; all public/private `InputController` and `WindowManager` raw sinks leading-guard; scripts have zero raw dispatchers; SEEK `WM_CLOSE` is disabled; W3b observation/freshness capture remains passive. Independent strict review reports PASS with no D-class bypass. This is internal code/test/audit proof, not a live/control-workflow or public-integration claim.<br>
**Completed internal prerequisite for W5.**

### W3b — Current internal adapter and receipt integration

**2026-08-22 implementation update:** The internal composition slice is implemented and independently reviewed (Sol High final review: PASS). It composes the exact active reviewed asset -> passive bound-window capture -> real observed UIA origin -> pinned current recognition -> strict Agent Observation/Intent -> current re-ground -> real Gate -> exact pre-dispatch pixel freshness -> one-shot ExistingWindowsBackend -> durable backend/runtime receipt. Exact session/capture/SHA/viewport/HWND/PID binding is retained; ranking/margin is recomputed; zero/low/ambiguous anchors fail closed; duplicate durable receipt lookup prevents re-dispatch. The release-focused W3b/W4 regression suite reports `595 passed, 3 skipped in 25.10s`. This remains a preserved focused implementation baseline, not a full-repository baseline.

W5 now extends this internal path through a durable pre-C2 verification checkpoint, fresh projected C2, closed target-state verification, and an exactly paired semantic terminal. The actual-adapter composed proof uses the production `ExistingWindowsCurrentEvidenceAdapter` class with deterministic dependencies and `DeterministicFakeBackend`; it consumes an unmutated compiler asset, reaches `VERIFIED` for `open_detail`, returns the exact receipt after restart, and performs zero redispatch. This is still not real Windows/SEEK I/O, physical Windows dispatch + C2, Controlled Live Workflow Proof, public HTTP route, agent/demo callsite, external Agent integration, or release completion.<br>
**Internal prerequisite closed; feeds controlled live proof.**

### W5 — Semantic verification, safe stop and lineage

完成 #10–12，并把 W3b receipt 绑定到 fresh observed effect。`open_detail` 是独立 effect proof；Proof B 主链只执行 `open_apply_flow` 后 safe stop。**2026-08-22 internal closure:** internal W5 与 actual-adapter deterministic composition 已闭合，focused suites 为 `351 passed, 2 skipped in 23.65s`。compiler-emitted rule、fresh C2、semantic destination verification、next observation、exact checkpoint/terminal pairing、restart exact receipt 与 zero redispatch 均已验证。release acceptance 仍为 Partial：actual-adapter `open_apply_flow` → application-entry stop-boundary、physical Windows dispatch + C2 和 Controlled Live Workflow receipt 尚未证明。<br>
**Immediate dependency path:** W2 human-reviewed Job Detail → `open_apply_flow` → Apply Entry stop-boundary release asset + save/restart/reload evidence → server-owned confirmation and bounded local public/demo callsite → actual-adapter `open_apply_flow` → application-entry terminal `SAFE_STOP` deterministic proof → controlled live SEEK proof → W6 close-out. W1 runs in parallel but is required before W6. The current confirmation path hard-stops as `NEEDS_REVIEW`, and no public route exists.

### W6 — Evidence package and public close-out

- 固定 Contract/Recorded/Live 证据等级；
- 收集 positive + negative control receipts；
- 生成 10–15 秒真实受控 GIF；
- 最后才更新 README / architecture diagram / status claims。

```text
W1 ─────────────────────┐
                        ├→ W6
W2 ─────→ W4 → W3b → W5 ┤
           ↑             │
W3a ───────┘─────────────┘
```

依赖摘要（冻结设计）：**`{W2, W3a} → W4 → W3b → W5`；W1 parallel；W6 close-out。** 当前实现状态中 W4/W3b/W5 `open_detail` internal prerequisites 已通过，但 release 依赖路径仍是 **W2 human-reviewed Job Detail → `open_apply_flow` → Apply Entry stop-boundary release asset + save/restart/reload evidence → server-owned confirmation and bounded local public/demo callsite → actual-adapter `open_apply_flow` → application-entry terminal `SAFE_STOP` deterministic proof → controlled live SEEK proof → W6 close-out**。W1 parallel，但必须在 W6 前完成；不得用 internal `open_detail` composition proof 替代 W1/W2。

## 9. Effort and Calendar Estimate

初始工程估算（以当前工作树为基线，需在每个 workstream 首个 focused test 后校正）：

| Workstream | Low | Likely | High | Notes |
|---|---:|---:|---:|---|
| W1 Provider contract proof | 8h | 10h | 13h | 含 provider-neutral Review，不含 Omni live inference |
| W2 Reviewed asset release slice | 5h | 6h | 8h | 复用现有 v2 compiler/store |
| W3a + W4 + W3b Agent contracts + current observation / relocation / Gate | 18h | 23h | 28h | 最大风险；不接第二个外部 CU Agent |
| W5 Verification / safe stop / lineage | 5h | 12h | 17h | 这里仅计入与 W3a/W4/W3b 不重叠的净新增工作 |
| W6 Evidence / demo / docs | 4h | 7h | 12h | 真实 GUI 环境稳定性影响工时 |
| **Total engineering effort（去除重叠）** | **40h** | **58h** | **78h** | 可并行，但不能简单折算为日历时间 |

**Expected focused calendar:** 单人按每天 6 个有效工程小时约 7 / 10 / 13 个工作日；保留真实 GUI 复测、证据清理和 README close-out 时间。<br>
**Remaining runtime critical path:** W2 human-reviewed Job Detail → `open_apply_flow` → Apply Entry stop-boundary release asset + save/restart/reload evidence → server-owned confirmation and bounded local public/demo callsite → actual-adapter `open_apply_flow` → application-entry terminal `SAFE_STOP` deterministic proof → controlled live SEEK proof → W6 close-out。W1 parallel，但必须在 W6 前完成；上表是初始总工程估算，不用当前通过的 W4/W3b/W5 `open_detail` internal work 重复计费。<br>
如果 W4 或 W5 进入 `XL`，必须缩小实现，不得把 scope 扩大到 Homepage、scroll、表单或新 adapter。

## 10. Negative Controls

Portfolio Release v1 必须同时展示：

```text
stale capture / stale observation → BLOCKED → zero click
wrong window / identity mismatch → BLOCKED → zero click
ambiguous current candidate → BLOCKED → zero click
unknown or unauthorized agent intent → BLOCKED → zero click
Continue / form-fill / terminal boundary → SAFE STOP → zero later action
semantic verification failure → not verified → SAFE STOP
```

**Encountering form-fill / Continue / terminal-action classes is a negative-control SAFE STOP; no form mutation belongs to Portfolio v1.**

Negative control receipt 与 positive live receipt 使用同一 contract，不允许用测试专用 bypass。

## 11. Explicit Out of Scope

2026-09-13 前不做：

- SEEK Homepage traversal（除非零新增复杂度的 stretch）；
- scrolling、long screenshot runtime replay、list virtualization、job ranking/filtering；
- ATS、跨站跳转、表单填写、上传、Continue/Next、final submit；
- Qwen/OpenAI/Anthropic 多个 perception adapter；
- OpenAI/Qwen/Anthropic 多个 live Computer-Use adapter；
- raw coordinate computer-use authorization；
- remote execution、MCP router、automatic provider selection；
- production-ready、unattended reliability、unfamiliar-site generalization claim；
- 不影响 v1 受控路径的安全债务：记录到 deferred backlog，不在主线扩张。

## 12. Release and Freeze Rule

只有以下全部成立，才标记 **Portfolio Release v1**：

1. 12 个 Core Runtime predicates 全部有对应等级证据；
2. N1–N4 contract gates 全部通过；
3. Proof A 与 Proof B 证据分级正确；
4. positive live path 与全部 negative controls 通过同一 runtime contract；
5. README 诚实区分 Stable / Partial / Prototype；
6. 无敏感数据、个人信息、token、私有路径或错误媒体链接进入公开提交；
7. release receipt 能从 reviewed workflow revision 追到 observed effect 和 safe stop。

满足后停止主动开发并冻结项目。后续只修复已记录 defect；新 provider、新 agent adapter、raw computer use、scroll/form/ATS 均进入独立 post-v1 roadmap。
