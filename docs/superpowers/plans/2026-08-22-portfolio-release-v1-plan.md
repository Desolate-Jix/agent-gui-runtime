# Portfolio Release v1 — Frozen Project Plan

**Status:** Frozen bounded Quick Apply-only release<br>
**Plan date:** 2026-08-22<br>
**Evidence status updated:** 2026-08-24<br>
**Release target:** 2026-09-13<br>
**Scope owner:** Main Codex / repository owner<br>
**Change rule:** After this document is accepted, only verified runtime failures may change tasks. They must not redefine the product or expand the release scope.

**2026-08-24 freeze decision:** Portfolio v1 acceptance is exactly the bounded already-open Job Detail → confirmed `open_apply_flow` → fresh Apply Entry → `SAFE_STOP/stop_boundary` slice. `open_detail` is post-v1: current semantic `open_detail` live proof is deferred and is not a Portfolio v1 acceptance predicate.

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

本节以 2026-08-22 冻结的工作树基线为起点，并纳入截至 2026-08-24 的已验证证据；不把 Target State 当成已实现。

| Area | Status | What is actually working | Current boundary |
|---|---|---|---|
| Built-in screenshot / OCR / UIA / recognition | Partial | 受控 capture、OCR/UIA 候选与 recognition path 可用 | 通用识别质量与陌生界面可靠性未证明 |
| UEI v1 canonical schemas/store/registry/projections | Stable — offline contract | immutable refs、trusted registration、OCR/UIA/parser projection、fail-closed tests | 当前为离线/Shadow 合同，不授权动作 |
| OmniParser Shadow adapter | Current — recorded contract proof | bounded trusted local Shadow path、tracked recorded worker success/failure receipt proof | 真实 cold + 3 warm inference 因 GPU free memory `< 8 GiB` 未验证；不把 recorded proof 描述为 live inference |
| UEI → Learning | Current — provider-contract proof | Server-owned Built-in OCR ref 与 recorded OmniParser Shadow success/failure 都进入同一 compact `uei_shadow_provider_summary_v1` | 仍不进入 compile/action-candidate 主链，不能授权执行 |
| Learn Mode / human review / workflow graph | Current for release slice; Partial generally | Panel 已完成 Job Detail 大图修正、Quick apply + Save 多框审核、一次确认入库；Apply Entry 保持 stop boundary | 只证明本 release 两状态纵向 slice，不证明通用识别或陌生软件审核质量 |
| Reviewed Workflow v2 compiler/store | Stable for release packaging | 当前 reviewed source 可 byte-exact 编译为 active asset `8284e172...391b7`，并由新进程 reload exact revision/hash | 资产仍不授权执行；通用 production orchestration 不由此证明 |
| Agent-facing Observation / Intent contract | Current — internal loopback + one bounded live path | closed schemas、strict validators、server-owned context、geometry-free intent 与 loopback callsite 已进入受限 controlled-live path | 第二个外部 Computer-Use Agent adapter 与通用兼容性未证明 |
| Runtime Result & Verification Receipt Contract | Current for one bounded live receipt | receipt `receipt.38d529e464f94dbf858ec4d18de90c7c` 绑定 current asset、Gate、one dispatch、fresh C2、verified effect/destination 与 `SAFE_STOP/stop_boundary` | 只证明一个 `open_apply_flow` path；不证明通用 live reliability |
| Current capture / runtime relocation | Current for one bounded live path | server-owned current capture、current re-ground、exact pre-dispatch freshness 与一次 physical Windows dispatch 已进入同一 receipt | 仅限已经打开的 Job Detail，不含 homepage/list traversal |
| Gate / zero-click rejection | Current — one bounded live allow + deterministic negative matrix | real action 经过 Gate；六类 canonical negative controls 与两个 supplemental controls 通过 typed Runtime decision/Receipt 形成公开投影 | negative controls 主要是 deterministic exact-current 或 behavior-equivalent synthetic evidence，不冒充 live fault injection |
| Semantic effect verification | Current for frozen bounded scope | `open_apply_flow` fresh C2 匹配 `Choose documents`，effect/destination verified；internal composition 仍保留 deterministic `open_detail` proof | current semantic `open_detail` live proof 属于 post-v1，不是冻结 release 验收项 |
| Safe stop | Current for bounded Quick Apply path | verified Apply Entry observation 只投影 `safe_stop`，terminal Receipt 为 `SAFE_STOP/stop_boundary`，无后续 mutation/redispatch | 不表示完整 application flow 或表单能力 |
| Trace lineage | Current for bounded Quick Apply path | public projection可从 reviewed source/active asset 追到 Observation/Intent/Gate/backend/effect/next state/safe stop | 只覆盖该 receipt，不是通用 tracing reliability claim |
| Public demo | Partial | controlled GIF 与一次 receipt-backed bounded live `open_apply_flow` 已有记录 | 不是完整 semantic workflow replay，也不是 unattended apply |

### Verification baselines

- **Earlier release-focused UEI checkpoint:** `109 passed, 1 failed`；唯一失败是 README 缺少 `Universal Evidence Interface v1` 文案。该文案现已补齐，当前 `tests/test_uei_v1_static_conformance.py` 为 `5 passed`；这证明静态 conformance 已恢复，不冒充完整 UEI suite 重跑。
- **Last full offline repository baseline:** Python `2762 passed, 1 skipped`；JavaScript `128 passed, 0 failed`。这是完整离线回归基线，不是 live SEEK 或 Portfolio v1 live-controller 证明。
- **Portfolio v1 Contract Foundation:** schema/validator、server-owned/server-loaded reviewed-context Observation adapter（current capture/state/fact freshness 与 integrity bindings、geometry-free action projection、blocker/state fail-closed）、reviewed replay Receipt adapter（validated reviewed asset + strict post observation 内部重算 existing replay verifier、canonical application/source/next-observation lineage、拒绝 unproven dispatch/Gate 与 arbitrary operation refs）组成的 focused combined suite 为 `394 passed, 2 skipped`。它证明 offline Contract Foundation 与真实代码边界映射，不证明 Live Controller、Session mutation ledger、唯一 Gate dispatch、GUI dispatch、backend receipt、semantic verification owner 或 durable runtime persistence。
- **Release-focused W3b/W4 implementation proof:** `595 passed, 3 skipped in 25.10s`。它覆盖 internal composition、durable dispatch receipt、current re-ground/freshness 与 unique raw-input authority；独立严格审计为 PASS，W4 Stop Condition MET。它是保留的历史 focused baseline，不是 full-repository baseline 或 live Windows/SEEK proof。
- **Release-focused W5 + actual-adapter composition proof:** compiler/replay/Observation/claim/receipt/controller/Gate/composition suites 为 `351 passed, 2 skipped in 23.65s`。production `ExistingWindowsCurrentEvidenceAdapter` 类在 deterministic window/screenshot/UIA/recognition doubles 与 `DeterministicFakeBackend` 下消费未经修改的 compiler asset，使 `open_detail` source → target 到达 `VERIFIED`，restart 返回 exact receipt 且 zero redispatch。它不是真实 Windows/SEEK I/O、physical Windows dispatch + C2、Controlled Live Workflow Proof、public integration、external Agent integration 或 full-repository baseline。
- **2026-08-24 W6 close-out verification:** integrated Portfolio v1 matrix `301 passed`；full JavaScript panel/workflow suite `270 passed`；GIF lineage/privacy suite `38 passed`；canonical negative-control/callsite/controller focused suite `113 passed`。公开矩阵包含六类 canonical controls + 两类 supplemental controls，严格区分 exact-current 与 behavior-equivalent synthetic evidence，并区分 `runtime_result_receipt_v1` 与 `live_controller_decision`。该证据闭合 frozen Quick Apply-only acceptance；不支持 post-v1 `open_detail` live claim。

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

Reference scope 是受控的 **SEEK Job Detail → Apply Entry → Safe Stop**。`open_detail` 的 deterministic internal proof 保留为工程证据，但 current semantic live proof 已移入 post-v1，不属于 frozen Portfolio v1 acceptance，也不能重新引入 Homepage/list traversal。Homepage 只有在完全不引入 scroll、列表遍历、virtualization、ranking/filtering 或 infinite scroll 时才可作为 post-v1 stretch。

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
| 1 | Built-in output enters UEI | Current — contract proof | Server-owned fixed Built-in OCR capture 被 seal 为 UEI ref，且由同一 review projection 消费；不只显示 Shadow summary | `app/learn/recognition/uei/builtin_learning_projection.py`, `app/api/vision.py`, `app/learn/workflow_tasks/recognition.py`, `app/learn/draft_review.py` | UEI schemas/store | Built-in fixed capture → sealed UEI result → review projection conformance | M |
| 2 | OmniParser recorded/Shadow output passes same UEI contract | Current — recorded contract proof | tracked path-neutral recorded worker success/failure 通过真实 adapter/runtime，并输出可发布 proof；live smoke 保持 optional | `app/learn/recognition/uei/omniparser_shadow_adapter.py`, UEI fixtures, `release/portfolio-v1/provider-contract-proof.json` | none; #3 consumes shared review projection | Recorded Provider-Output Conformance Proof + failure receipt | S |
| 3 | Review UI has no provider-specific Learning branch | Current — contract proof | canonical Learn path 只接收 server-issued UEI ref；provider 仅作为 provenance 展示，raw provider payload 在 Panel 与 recognition persistence 边界被丢弃 | `app/web_panel/panel.js`, `app/learn/workflow_tasks/recognition.py`, JS/Python tests | #1–2 | 两 provider fixture 投影得到同一 UI model；raw provider geometry/provenance 无法进入 Review/trace | M |
| 4 | Human review forms a reviewed workflow | Current for release slice | Job Detail 已在 Panel 完成 Quick apply + Save 多框审核；`open_apply_flow` edge human-approved；Apply Entry 保持 stop boundary | review UI, tracked reviewed workspace, compiler tests | #1–3 | Panel/API review → compile-ready source with reviewed node/edge hashes | M |
| 5 | Asset survives save, process restart and reload | Current for release slice | source SHA `a934...27bc` 编译成 active asset `8284...391b7` 并由 fresh process exact reload | tracked release workspace + release tests | #4 | save → restart → load exact immutable asset/active revision | S |
| 6 | Runtime uses current window capture | Current for one bounded live path | controlled-live receipt binds current capture/window/application evidence before one real dispatch | internal composition + public receipt | #5 | current capture identity and receipt lineage | L |
| 7 | Action is re-grounded before dispatch | Current for one bounded live path | current Quick apply target 经 fresh recognition/ranking 与 exact pre-dispatch pixel freshness产生 click point；历史 bbox 不授予 authority | current-grounding tests + controlled-live receipt | #6 | current candidate and freshness refs | L |
| 8 | Stale/wrong/ambiguous means zero click | Current — deterministic release evidence | stale、wrong-window/occlusion、ambiguous 均产生 typed BLOCKED Receipt 与 zero dispatch；exact-current/synthetic grade 分离 | public six-control matrix + strict W4 audit | #6–7 | matched negative-control decisions/receipts | M |
| 9 | Every real action passes Gate | Current for one bounded live path | public receipt记录 Gate allowed 后才发生一次 Windows dispatch；authority audit仍保持唯一 caller/sink guards | controlled-live receipt + authority audit/tests | #7–8 | one-step dispatch budget + Gate ref | L |
| 10 | `open_apply_flow` has current semantic verification | Current for frozen bounded scope | `open_apply_flow` fresh C2 匹配 `Choose documents` 且 effect/destination verified；deterministic `open_detail` internal proof保留但 live proof 属于 post-v1 | public receipt + W5 suites | #9 | exact before/after effect + destination + safe-stop receipt | L |
| 11 | Safe stop at application entry | Current for bounded live path | Apply Entry 只暴露 `safe_stop`；terminal为 `SAFE_STOP/stop_boundary`；zero later mutation/redispatch | exact live receipt + exact-current stop control | #10 | `safe_stop=true`, reason/boundary, zero later action | M |
| 12 | Trace follows workflow to observed effect | Current for bounded live path | public receipt projection解析 source/asset、intent、Gate、backend、verification、fresh C2 和 safe stop refs | public evidence package | #5–11 | one resolvable bounded trace graph | M |

## 7. Boundary Contract Acceptance — 4 Additional Gates

这些 gates 不增加新的实际 GUI 行为；它们把 Proof B 已有输入/输出固定成可替换 Agent 能消费的稳定边界。

| ID | Contract gate | Current | Minimal v1 proof | Estimate |
|---|---|---|---|---|
| N1 | `agent_observation_v1` | Current — internal loopback + bounded live path | 版本化 schema包含 workflow/revision、application/current-state identity、current capture、semantic facts/evidence、blockers、eligible reviewed actions、expected effect、verification、risk/safe-stop boundary；server-owned context对 blocker/state fail closed | 第二个 external Agent adapter 未证明 |
| N2 | `agent_intent_v1` | Current — internal loopback + bounded live path | Agent只提交 observation-bound semantic action id；unknown/stale/cross-workflow intent、raw coordinate authority与越权 parameters均拒绝；controlled-live action仍由 Runtime所有执行权 | external Agent compatibility 未证明 |
| N3 | `runtime_result_receipt_v1` | Current for one bounded live receipt | exact live Receipt严格区分 Gate、dispatch、effect、destination并绑定 fresh C2、SAFE_STOP与 zero redispatch；deterministic matrix覆盖失败 outcomes | 不证明通用 live reliability |
| N4 | Current internal adapter conformance | Current — deterministic conformance + one bounded live path | server-loaded reviewed context → Observation → Intent → current re-ground → Gate → one-shot backend → fresh C2 → exact terminal 已由 production adapter 组合；W4 authority Stop Condition MET，并保留一条 current-asset physical Windows `open_apply_flow` Receipt | 第二个 external Agent adapter 与通用兼容性未证明 |

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

**2026-08-22 draft update:** `release/portfolio-v1/reviewed-asset-workspace` 现保存一个可移植、已去敏的两状态 review draft，并在本地 ignored `artifacts/` 中 materialize 同字节 Panel review source。它固定 `Job Detail → open_apply_flow (confirmation required) → Choose documents / SAFE STOP`、不含 runtime geometry，并由 focused tests 证明未获人审时 compiler fail closed。该 draft 使用 historical captures 的 privacy-redacted visual derivatives；它们不是 raw/forensic pixel evidence，去敏可能改变非审核像素，因此人审只覆盖声明的界面责任、语义控件、transition 与 safe-stop boundary。`human_review_completed=false`、`controlled_live_workflow_proven=false`，不能替代真实 Panel 人审、compiled release asset、process-restart exact reload 或 controlled live proof。W2 仍为 open。<br>

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

完成 #10–12，并把 W3b receipt 绑定到 fresh observed effect。Proof B 主链只执行 `open_apply_flow` 后 safe stop。**2026-08-24 status:** internal W5 与 actual-adapter deterministic composition 已闭合；当前 active asset 的一条 controlled-live `open_apply_flow` path 也已产生 exact receipt，包含 Gate、one physical Windows dispatch、fresh Apply Entry C2、verified effect/destination 与 `SAFE_STOP/stop_boundary`。frozen Quick Apply-only release acceptance 已闭合；current semantic `open_detail` live proof 属于 post-v1。<br>
**Immediate dependency path:** frozen release 范围内无剩余依赖。W1/W2/W3a/W4/W3b/W5 与 W6 public package、GIF、canonical negative-control matrix、docs close-out 均已完成。不得把这个单路径证明扩大为 general reliability。

### W6 — Evidence package and public close-out

- 固定 Contract/Recorded/Live 证据等级；
- 收集 positive + negative control receipts；
- 生成 10–15 秒真实受控 GIF；
- 最后才更新 README / architecture diagram / status claims。

**2026-08-24 status:** tracked release workspace、exact active-asset reload、12 秒隐私检查 editorial GIF、exact-live receipt projection、六类 canonical negative controls + 两类 supplemental controls、cleanup commitment 与 README/Architecture status sync 已完成。controls 严格区分 exact-current 与 behavior-equivalent synthetic evidence，并区分 Receipt 与 pre-dispatch decision。W6 已在声明的 bounded Quick Apply-only scope 内完成并冻结。

```text
W1 ─────────────────────┐
                        ├→ W6
W2 ─────→ W4 → W3b → W5 ┤
           ↑             │
W3a ───────┘─────────────┘
```

依赖摘要（冻结设计）：**`{W2, W3a} → W4 → W3b → W5`；W1 parallel；W6 close-out。** 该 DAG 保留为历史设计和验收依赖；截至 2026-08-24，W1/W2/W3a/W4/W3b/W5 的 Quick Apply-only release slice 与 W6 证据包已完成并冻结。post-v1 `open_detail` live proof 不得用 internal deterministic composition proof 冒充。

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
**Remaining runtime critical path:** frozen Portfolio v1 scope 内为 none。任何 current semantic `open_detail` live proof 必须进入新的 post-v1 plan 或由用户显式解冻。上表保留的是初始总工程估算，不对已完成的 W1–W6 Quick Apply-only slice 重复计费。<br>
如果 W4 或 W5 进入 `XL`，必须缩小实现，不得把 scope 扩大到 Homepage、scroll、表单或新 adapter。

## 10. Negative Controls

Portfolio Release v1 必须同时展示：

```text
stale capture / stale observation → BLOCKED → zero click
wrong window / identity mismatch → BLOCKED → zero click
ambiguous current candidate → BLOCKED → zero click
unknown or unauthorized agent intent → REJECTED decision → zero click
Continue / form-fill / terminal boundary → SAFE STOP → zero later action
semantic verification failure → VERIFICATION_FAILED Receipt → terminal, no blind retry
```

**Encountering form-fill / Continue / terminal-action classes is a negative-control SAFE STOP; no form mutation belongs to Portfolio v1.**

Negative controls 与 positive live path 使用同一 production LiveController/Runtime boundary，不允许测试专用 bypass。进入 Receipt contract 的 failure 必须返回 `runtime_result_receipt_v1`；invalid intent 等在 Receipt 之前被拒绝的输入返回 typed `live_controller_decision`，不得伪造 terminal Receipt。

## 11. Explicit Out of Scope

2026-09-13 前不做：

- SEEK Homepage traversal（除非零新增复杂度的 stretch）；
- current semantic `open_detail` controlled-live proof（post-v1）；
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
4. positive live path 与全部 negative controls 通过同一 Runtime boundary，并按真实阶段返回 typed decision 或 Receipt；
5. README 诚实区分 Stable / Partial / Prototype；
6. 无敏感数据、个人信息、token、私有路径或错误媒体链接进入公开提交；
7. release receipt 能从 reviewed workflow revision 追到 observed effect 和 safe stop。

上述条件已在 bounded Quick Apply-only boundary 内满足，Portfolio v1 于 2026-08-24 冻结。后续只修复已记录 defect；`open_detail` live proof、新 provider、新 agent adapter、raw computer use、scroll/form/ATS 均进入独立 post-v1 roadmap。
