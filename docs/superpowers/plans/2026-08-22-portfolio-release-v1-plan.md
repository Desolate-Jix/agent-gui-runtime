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
| OmniParser Shadow adapter | Implementation stable — release conformance pending | bounded trusted local Shadow path、recorded/fake-worker contract tests | 真实 cold + 3 warm inference 因 GPU free memory `< 8 GiB` 未验证；当前 focused suite 仍有 1 个 README wording failure |
| UEI → Learning | Prototype | Draft 可显示 compact `uei_shadow_provider_summary_v1` | 未进入完整 review/compile/action-candidate 主链 |
| Learn Mode / human review / workflow graph | Partial | review workspace、节点/边编辑、人工确认和历史工作流 UI 存在 | 当前资产链条较多，release 纵向 slice 尚未统一 |
| Reviewed Workflow v2 compiler/store | Stable — offline contract | fail-closed compile、CAS-style immutable storage、preview/reload tests | production live replay orchestrator 缺失 |
| Agent-facing Observation / Intent contract | Prototype | 内部 API 和 runner 有零散 `available_actions` / action selection 结构 | 无统一 northbound schema、版本和 conformance boundary |
| Runtime Result & Verification Receipt Contract | Prototype | action trace、pre-click、post-click 字段分散存在 | 无统一 receipt；semantic verification 不是强制不变量 |
| Current capture / runtime relocation | Partial | 某些 live 与 approved-plan 路径能 current capture | `require_current_grounding` 仍为条件分支；旧 reuse path 可保留历史 point |
| Gate / zero-click rejection | Partial | 正式 gated action API、窗口/候选/危险动作检查已存在 | 尚未证明 Portfolio replay 每一步都不可绕过且默认强制 |
| Semantic effect verification | Partial | 若启用可记录 post-action verification | 当前 SEEK 证据主要是像素/焦点变化；禁用时不能提升为 verified |
| Safe stop | Partial | no-submit fixtures、apply-entry 边界与受控停止已有基础 | 尚未绑定统一 Agent receipt / live workflow controller |
| Trace lineage | Partial | 多类 trace、asset hash 和 action trace 已存在 | 缺少一个 workflow revision → intent → current observation → effect 的统一链 |
| Public demo | Partial | controlled GIF / two bounded SEEK actions 已有记录 | 不是完整 semantic workflow replay，也不是 unattended apply |

### Verification baselines

- **Release-focused UEI conformance:** `109 passed, 1 failed`。唯一失败是 README 缺少 `Universal Evidence Interface v1` 文案；因此 UEI release conformance 尚未全绿。
- **Last full offline repository baseline:** Python `2762 passed, 1 skipped`；JavaScript `128 passed, 0 failed`。这是完整离线回归基线，不是 live SEEK 或 Portfolio v1 live-controller 证明。

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
| 2 | OmniParser recorded/Shadow output passes same UEI contract | Implementation stable — release conformance pending | 固定 path-neutral recorded output并输出可发布 receipt；把 live smoke 保持 optional；修正文档 conformance failure | `app/learn/recognition/uei/omniparser_shadow_adapter.py`, UEI tests/fixtures | none; #3 consumes shared review projection | Recorded Provider-Output Conformance Proof + failure receipt | S |
| 3 | Review UI has no provider-specific Learning branch | Partial | UI 只读 canonical review model；provider 仅作为 provenance 展示 | `app/web_panel/panel.js`, `app/web_panel/learning_workflow_review.js`, JS tests | #1–2 | 两 provider fixture 投影得到同一 UI model；无 provider branch test | M |
| 4 | Human review forms a reviewed workflow | Partial | 收缩成 Job Detail、Apply Entry 两状态，一个 `open_apply_flow` transition 和一个 stop boundary；独立 `open_detail` proof 使用独立 reviewed source/target，不接入主链 | review UI, `app/agent/reviewed_workflow_compiler.py` | #1–3 | Panel/API review → compile-ready source with reviewed node/edge hashes | M |
| 5 | Asset survives save, process restart and reload | Stable — offline; release proof pending | 用 release slice 做独立进程 round-trip，并验证 exact revision/hash | `app/agent/reviewed_workflow_asset.py`, `app/api/panel.py`, v2 tests | #4 | save → restart → load exact immutable asset/active revision | S |
| 6 | Runtime uses current window capture | Partial | 为 release replay 建立 server-owned current-observation bridge；禁止 caller 注入 observation，禁止从资产复用旧 capture | `app/api/action.py`, `app/agent/reviewed_workflow_replay.py`, `app/api/panel.py` | #5 + Agent Intent | receipt 中 current observation/capture id、SHA、viewport、origin 与运行时窗口一致 | L |
| 7 | Action is re-grounded before dispatch | Partial | 使 reviewed replay 默认且强制 current re-ground；历史 bbox 仅 hint | `app/api/action.py`, grounding/candidate path | #6 | reviewed semantic target → current unique candidate → current click point | L |
| 8 | Stale/wrong/ambiguous means zero click | Partial | 将 freshness、window identity、lineage、score ambiguity 变成 replay 不可选强制条件 | `app/gate/window.py`, `app/gate/candidates.py`, `app/api/action.py` | #6–7 | 三个 matched negative controls 均 `BLOCKED` 且 operation count = 0 | M |
| 9 | Every real action passes Gate | Partial | reviewed workflow controller 只能调用 gated action API；禁止 direct click adapter；建立唯一 server dispatch envelope | `app/gate/actions.py`, `app/api/action.py`, replay controller | #7–8 | 每个 live receipt 含 `pre_click_decision_v1` + Gate pass + one-step budget | L |
| 10 | `open_detail` / `open_apply_flow` have real semantic verification | Partial | 验证 job identity/detail state 与 application-entry state；禁用/失败不得写 verified | `app/api/action.py`, verification path, SEEK fixture/live smoke | #9 | before/after semantic evidence + expected-effect assertion for both actions | L |
| 11 | Safe stop at application entry | Partial | application-entry、Continue/form-fill/final boundary 统一转成 terminal safe-stop，无后续 dispatch | workflow asset/replay controller, danger policy | #10 | `safe_stop=true`, reason/boundary, zero later action | M |
| 12 | Trace follows workflow to observed effect | Partial | 统一 workflow/asset revision、observation、intent、candidate、Gate、operation、verification refs | asset/store, action trace, new receipt contract | #5–11 | one replay trace graph with resolvable hashes/refs end to end | M |

## 7. Boundary Contract Acceptance — 4 Additional Gates

这些 gates 不增加新的实际 GUI 行为；它们把 Proof B 已有输入/输出固定成可替换 Agent 能消费的稳定边界。

| ID | Contract gate | Current | Minimal v1 proof | Estimate |
|---|---|---|---|---|
| N1 | `agent_observation_v1` | Prototype | 版本化 schema：workflow/revision、matched state、fresh observation ref、available semantic actions、risk/safe-stop boundary；不得泄露可直接执行的历史坐标 | M（与 W3a 合并） |
| N2 | `agent_intent_v1` | Prototype | Agent 只提交 observation-bound semantic action id；拒绝 unknown/stale intent、raw coordinate authority、越权 parameters | M（与 W3a 合并） |
| N3 | `runtime_result_receipt_v1` | Prototype | 返回 blocked/executed/verified/safe_stop 状态、Gate/operation/verification refs 和 next observation；不以裸 `success=true` 代替验证 | M（与 W5 合并） |
| N4 | Current internal adapter conformance | Prototype | 当前 Agent/runner 通过 Observation → Intent → Receipt；unknown-field、coordinate-injection、cross-asset、stale-intent 全部拒绝；无 provider/Agent-specific runtime branch | M（4–6h，high 7h） |

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
**Feeds W4.**

### W3a — Agent-side schemas and offline validation

先完成 N1–N3 的 versioned schema、strict validation 与 offline conformance。不得新增第二个 Computer-Use Agent adapter。<br>
**Can start with W1; feeds W4.**

### W4 — Mandatory current relocation and Gate

完成 #6–9。server-owned current observation、re-ground、fail-closed negative controls、所有动作 Gate。<br>
**Depends on W2; critical path.**

### W3b — Current internal adapter and receipt integration

把 current internal Agent adapter 接到 W3a contract 与 W4 唯一 dispatch envelope，完成 N4；Runtime Receipt 的 final verification fields 由 W5 填充。<br>
**Depends on W3a + W4; feeds W5.**

### W5 — Semantic verification, safe stop and lineage

完成 #10–12，并把 W3b receipt 绑定到真实 observed effect。`open_detail` 是独立 effect proof；Proof B 主链只执行 `open_apply_flow` 后 safe stop。<br>
**Depends on W3b + W4; critical path.**

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

依赖摘要：**`{W2, W3a} → W4 → W3b → W5`；W1 parallel；W6 close-out。**

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
**Critical path:** W2 → W4 → W3b → W5 → W6，约 37–62 工程小时；W1 与 W3a 可平行。<br>
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
