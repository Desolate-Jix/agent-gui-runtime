# agent-gui-runtime

**版本 0.3.0 · Windows GUI Agent Runtime · Portfolio v1 已冻结 · 受限 Quick Apply-only release**

[English](README.md)

## 位于 Computer-Use Agent 与 Windows GUI 动作之间的可靠性 Runtime 目标

这是一个仍在完善中的 Windows GUI Runtime，目标是把不确定的界面探索转化为经人工审核的操作知识，再针对当前界面重新定位、Gate、执行并验证语义动作。

**感知可以替换。经审核的知识可以持久复用。**

**目标不变量：** Runtime Authority 必须不可绕过。**当前 release asset 已同时具备确定性 callsite proof 和一次受限 controlled-live proof：全新的 Job Detail observation 经过 Runtime 授权，只执行一次 Windows `open_apply_flow`，随后重新观察到 `Choose documents` stop boundary，并持久化 `SAFE_STOP/stop_boundary` receipt。**

> **目标 Authority 模型：** Provider 只提出 evidence。Agent 只提出 semantic intent。只有 Runtime 能授予受限的执行权限。

[![经过脱敏的 reviewed workflow 总览](docs/media/private-prototype-workflow.png)](docs/media/private-prototype-workflow.png)

*来自[早期公开展示仓库](https://github.com/Desolate-Jix/windows-gui-agent-runtime)的脱敏 workflow 总览：经审核的界面知识用于约束 intent，而 Runtime 必须针对当前 observation 重新定位并独立 Gate 每次动作。这是产品故事示意，不是当前 Portfolio v1 live proof。*

### 来自早期公开展示仓库的产品界面

> **历史展示 UI。** 这些面板让 Learn → Human Review → Runtime 的交接过程更直观。它们展示的是产品与设计沿革，不是当前 Portfolio v1 live proof；当前界面可能已经不同。

<table>
  <tr>
    <td width="50%" align="center"><a href="docs/media/private-prototype-learn-mode.png"><img src="docs/media/private-prototype-learn-mode.png" alt="带 workflow graph 和框选界面 evidence 的历史 Learn Mode 面板" width="100%"></a></td>
    <td width="50%" align="center"><a href="docs/media/private-prototype-execute-mode.png"><img src="docs/media/private-prototype-execute-mode.png" alt="带 runtime state、available actions、Gate 和 Trace 的历史 Execute Mode 面板" width="100%"></a></td>
  </tr>
  <tr>
    <td valign="top"><strong>Learn / Review</strong><br>审核者查看带框的界面 evidence、修正 semantic state，并连接可复用的 workflow graph。该面板不授予执行权限。</td>
    <td valign="top"><strong>Execute / Runtime</strong><br>展示目标中的 current-state、available-action、Locate、Gate 与 Trace 界面。该图不证明当前 dispatch、observed semantic effect 或 live replay。</td>
  </tr>
</table>

![脱敏的历史 workflow sequence](docs/media/private-prototype-seek.gif)

*脱敏历史示意：results → detail → application-entry blocker / Safe Stop。它不是 Agent 实际运行录屏，也不证明 click、表单修改或提交。*

- **Today：** 离线合同基础；带两个 reviewed region、可在 tracked workspace 中重新编译并由新进程精确 reload 的 Job Detail workflow；精确的 deterministic release-callsite proof；以及一次经过独立审查、server-owned confirmation、全新 Apply Entry 验证和 durable `SAFE_STOP/stop_boundary` 的受限 Windows live proof。
- **内部已实现：** reviewed asset → passive bound-window capture → observed UIA origin → pinned recognition → strict Observation/Intent → current re-ground → Gate → reviewed-target-region pre-dispatch freshness → one-shot Windows backend → fresh C2 observation → semantic target-state verification → durable terminal receipt。
- **Not yet：** 通用 SEEK 导航、表单填写、文件上传、Continue/Next、提交、无人值守可靠性、production readiness、公开外部 Agent 集成、外部/远程 Provider 集成或 live 外部 Agent adapter。

## 为什么需要这个 Runtime

常见的 Computer-Use 主线很短：

```text
screenshot → model → coordinate → click
```

它也很脆弱：模型结果可能已经过期，窗口可能发生切换，同一个标签可能出现多次，而成功 dispatch 也不代表预期效果已经发生。重复调用更强的模型不会自动产生可持久化的知识，也不会建立执行授权边界。

本项目补上中间的可靠性层：

```text
不确定探索 → evidence → 人工审核 → 可持久化的语义工作流
→ 当前界面重新定位 → Gate → 受限执行 → Verify / Safe Stop
```

本项目**不与** Qwen、OpenAI、Anthropic、OmniParser 或其他 foundation-model/parser 团队竞争感知更新速度。更强的新感知能力可以接入 evidence boundary。仓库内置的 screenshot、UIA、OCR 和 recognition 是可用的 baseline/fallback，不是项目的 moat，也不代表已经具备通用视觉理解能力。

## 与常见方案的区别

| Screenshot-to-click 系统 | agent-gui-runtime |
| --- | --- |
| 一次临时模型输出可以直接变成坐标。 | Provider 输出在通过受信边界和审核前始终只是 evidence。 |
| 可能直接重放历史几何信息。 | 复用的是已审核语义；几何必须在当前 capture 上重新定位。 |
| 模型或 Agent 拥有动作决定权。 | Agent 提出 semantic intent；Runtime Authority 决定是否允许一次受限尝试。 |
| 发出 click 可能就被报告为成功。 | 必须验证 observed effect，否则结果为未验证或 Safe Stop。 |
| 更换模型可能改变整套自动化。 | 四个公开合同分别约束 Provider evidence、reviewed asset、Agent intent 和 runtime receipt。 |

## Target lifecycle

以下是必须达到的目标状态；当前已有一个狭窄的 controlled-live slice 证明这条链，但更广泛使用和 production use 仍未完成：

1. **Explore** 不确定的 Windows 或浏览器路径。
2. **Capture evidence**，记录 capture identity、coordinate space、provider provenance 和 freshness。
3. **Review** 语义、候选动作、转移、预期效果与风险边界。
   - Panel 的“修正与确认”会直接打开一个大图工作台。用户点击任意识别框即可查看对应语义，必要时修改 geometry、说明和当前 outgoing operation；workflow-bound 界面最后只需一次“确认并入库”。系统会先验证全部 outgoing operation，再记录 target control/region、exact action candidate、transition edge 与 source node 四类独立 revision receipt。standalone source 只能“仅保存草稿”，不能批准 workflow。
4. **Compile** 不可变 reviewed workflow asset。它描述要找什么、如何验证，但不授权动作。
5. **Observe again**：Agent 请求语义动作时重新观察。
6. **Relocate**：针对当前界面重新定位已审核目标；历史坐标只能作为 hint。
7. **Gate**：结合当前窗口、候选、lineage、歧义和危险检查，最多开放一次受限尝试。
8. **Execute**：通过位于 Runtime Authority 下方的内部 Desktop I/O backend seam 执行动作。W3b 已组合 reviewed asset、passive bound-window capture、真实 UIA origin、pinned recognition、strict intent、current re-ground、Gate、reviewed-target-region pre-dispatch freshness、one-shot Windows backend 和 durable receipt。
9. **Verify**：确定性 proof 会加载精确 release asset、获取全新 C2，并验证 duplicate 不会重新 dispatch；一次受限 controlled-live run 还真实 dispatch 了一次 Windows `open_apply_flow`，解析出全新 `Choose documents` evidence，并持久化 `SAFE_STOP/stop_boundary`。

## Target authority architecture

公开架构冻结四个合同：

1. **Perception Provider Contract** — provider-native output 经 trusted adaptation 进入 canonical UEI evidence。
2. **Reviewed Workflow Asset Contract** — reviewed evidence 形成可持久化的语义状态、转移、verification policy、provenance 和 revision/hash。
3. **Agent Runtime Contract** — Runtime 暴露 Observation 和可用语义动作；Agent 返回与 Observation 绑定的 semantic intent。
4. **Runtime Result & Verification Receipt Contract** — outcome 明确区分 Gate、dispatch、observed effect、next state 和 Safe Stop。

固定后的 `WorkflowRef` 会把原始人工审核流程的 `workflow_id` 与编译产物 `asset_id` 明确分开。Compiler 会把经过 registry/path/SHA 校验的源流程身份写入不可变 lineage；Runtime、adapter 与 controller 边界会拒绝身份替换，而不会从 asset 名称猜测 ID。缺少该 lineage 字段的旧 v2 对象会 fail closed，必须重新编译；历史 geometry 仍不会获得 authority。

内部 W3b/W4/W5 controller slices 与 exact release-callsite composition 已通过确定性测试和严格审计验证，覆盖 current re-grounding、唯一 authority、受保护的 dispatch、全新 post-action observation、semantic destination verification，以及 checkpoint 与 terminal receipt 的精确配对。确定性 proof 仍使用 window/screenshot/UIA/recognition doubles 和 `DeterministicFakeBackend`；下面单独列出的受限 controlled-live receipt 是另一层证据，不能被推广成通用可靠性：

```text
内置 fallback 或受信 perception provider
                    │
        trusted adapter → Canonical UEI Evidence
                    │              （不授权动作）
                    ▼
             Learning + 人工审核
                    │
                    ▼
       Reviewed Workflow Asset + lineage
                    │              （不授权动作）
                    ▼
Computer-Use Agent ◄── Observation / Receipt
        │
        └── 仅 semantic intent ───► Runtime Authority
                                      │
                            当前 capture + relocation
                                      │
                              Gate + 受限尝试
                                      │
                       [internal Desktop I/O backend seam]
                                      │
                            Verify / Safe Stop / Receipt
```

任何 perception provider 都可以通过实现 **trusted adapter**，把 provider-native output 投影到 Universal Evidence Interface v1（UEI），从而面向这一架构接入。这是一个合同边界，并不是已经开放的插件市场：当前公开证据覆盖本地、静态和 Shadow 路径，不覆盖任意远程 Provider。

当前 OmniParser 路径只是 **review-only provider/shadow** prototype；它不能授权点击。

在未来设计中，外部 Agent 接收 Observation 和可用语义动作，再返回与该 Observation 绑定的 semantic intent。它无权提交历史坐标、绕过 Gate 或把效果标记为已验证。今天没有任何外部/远程 Provider 或外部 Agent adapter 完成 live integration。

Desktop I/O Backend SPI 是位于 Runtime Authority 下方的内部实现边界，不是第五个公开 Contract。W3b 只有在 passive bound-window capture、observed UIA origin、pinned recognition、current re-ground、Gate 和 reviewed-target-region pre-dispatch freshness 之后才绑定 backend；Windows backend 只能 one-shot dispatch，durable duplicate receipt 防止重复发送。deterministic fake backend 继续用于测试。未来更换 backend 时不得扩大 Authority。

## 诚实状态矩阵

| 能力 | 状态 | 这一状态实际表示什么 |
| --- | --- | --- |
| UEI schemas、immutable refs、trusted registration 和静态 projection | **Current — Contract Proof** | 已有 canonical、保留 provenance、不可授权动作的 evidence boundary。 |
| Reviewed Workflow v2 compiler 和内容寻址持久化 | **Current — Contract Proof** | 可离线编译、保存、检查并重新加载已审核语义资产；发布资产不等于执行许可。 |
| Agent Observation / Intent / Receipt schemas 与内部 controller composition | **Current — deterministic + one bounded live proof** | loopback-only `/runtime/agent` callsite 会把服务器持有的 active asset/window state 投影为 Observation，只接收不含 geometry 的 intent ID，并返回 durable Receipt。受限 live proof 使用了同一 callsite 和生产 Windows backend。 |
| Server-owned one-shot confirmation 与安全恢复 | **Current — deterministic + one bounded live proof** | Immutable request/decision/resume/closed marker 会绑定 exact claim、workflow revision/hashes、transition/action、capture/state evidence、HWND/PID 与固定过期时间。本地 approval route 只接收服务器 confirmation ID 与 decision；受限 live proof 通过同一路径后才发生一次 dispatch。 |
| 受限 SEEK 浏览器导航录屏 | **Partial** | 有界的历史 live GUI 录屏；不是 Portfolio v1 Controlled Live Workflow Proof，也不证明 saved-workflow replay 或 semantic verification。 |
| 内置 Windows perception baseline/fallback | **Partial** | 已有 screenshot、UIA、OCR 和本地 recognition 路径；未证明陌生界面可靠性。 |
| Built-in 与 OmniParser 进入同一 provider-neutral Review model | **Current — Contract Proof** | 固定 Built-in capture 与 recorded OmniParser-shaped success/failure 会进入同一个不授权动作的 UEI Review projection；这不是 live OmniParser inference 或 accuracy proof。 |
| 人工审核和应用范围 workflow 创建 | **Current — Portfolio v1 release asset** | Job Detail 已在单一大图工作台中修正 Quick Apply，并加入第二个不可执行的 Save evidence box。tracked release workspace 可按 content SHA `8284e1729409aa0a4f6a751a1a03d85fc51db1c7d53d473bd012455a3fc391b7` 逐字节重新编译并由新进程 reload active asset。5 个无法恢复的历史 draft snapshot 已明确标为 unresolved、non-authoritative，不影响当前资产。Apply Entry 仍是 `needs_learning/stop_boundary`。 |
| Current relocation、Gate 与唯一 dispatch authority（W4） | **Current — internal + one bounded live proof** | 只有 `LiveController` 能签发 authority；生产 Windows backend 是唯一 authority-scope consumer。受限 live run 通过当前 target-region freshness 后只 dispatch 一次；这不证明通用可靠性或公开 integration。 |
| 动作后 semantic verification 与 verified receipt promotion（W5） | **Current — deterministic + one bounded live proof** | 当前 release asset 真实执行一次 `open_apply_flow`，全新解析 `Choose documents`，验证 effect/destination 并持久化 `SAFE_STOP/stop_boundary`；`attempt_count=1`，没有 form fill、upload、Continue/Next、submit 或 redispatch。 |
| Portfolio v1 收口（W6） | **已冻结 — 受限 Quick Apply-only release** | tracked release workspace、12 秒隐私检查 GIF、公开 receipt/negative-control/cleanup package、active revision 精确 reload 和受限 `open_apply_flow` proof 已完成并通过独立审查。current semantic `open_detail` live proof 已移入 post-v1，不是 Portfolio v1 验收条件。 |
| Desktop I/O Backend SPI | **Partial** | 已有内部 SPI、deterministic fake backend 和受保护的 one-shot Windows backend；它不是公开 HTTP route、agent/demo callsite 或 production-readiness 主张。 |
| Primary / Assist / Automatic provider routing 和远程 Provider | **Planned** | 仅为 Target State；尚未实现自动 Provider fallback。 |
| Live external Computer-Use Agent adapters | **Planned** | 今天没有任何 live-integrated 实现。 |
| 生产可靠性或陌生站点泛化 | **Not claimed** | 不提供全站点覆盖或无人值守可靠性承诺。 |

### 受限 controlled-live receipt

一次 scoped run 从已经打开的 SEEK Job Detail 开始，使用同一个 reviewed asset、loopback Agent Runtime contract、server-owned confirmation、current re-grounding、Gate、Windows backend、post-action observation 和 durable receipt path：

![Portfolio v1 受控 Runtime 回放](docs/media/portfolio-v1-controlled-live.gif)

*12 秒隐私检查后的编辑式回放，不是连续录屏。PRE capture 只有独立哈希、未与 receipt 绑定；POST capture 与 receipt 绑定。详见 [媒体 manifest](docs/media/portfolio-v1-controlled-live.manifest.json) 与 [公开证据 package](release/portfolio-v1/evidence/manifest.json)。*

- workflow：`portfolio_v1_seek_apply_entry`
- active asset SHA：`8284e1729409aa0a4f6a751a1a03d85fc51db1c7d53d473bd012455a3fc391b7`
- receipt：`receipt.38d529e464f94dbf858ec4d18de90c7c`
- receipt object SHA：`8d5f94cebbbb7b6de6b2a144390fbbb37fa6c018f51e82789af0f797266c485e`
- result：一次 `open_apply_flow` dispatch → 全新 `Choose documents` state → `SAFE_STOP/stop_boundary`
- negative controls：六类 canonical failure 已全部映射到 Runtime 边界，exact-current controls 与 behavior-equivalent synthetic fixtures 明确分级；全程零 form fill、typing、upload、Continue/Next、final submit 或 redispatch

这只证明一个受限 Runtime 路径；不证明 Provider accuracy、通用 SEEK 导航、陌生站点可靠性、无人值守、完成求职申请或 production readiness。含个人信息的 application screenshot 和 raw field 不进入公开证据。

## 历史原型证据

> **历史展示证据。** 以下截图来自早期公开展示仓库，仅用于展示设计沿革。它们**不是当前 Portfolio v1 live proof**，当前界面可能不同。SEEK 以及所有雇主名称和标识均归其各自权利人所有；这里不暗示任何关联或背书。

### SEEK reference states · 历史截图

<table>
  <tr>
    <td width="33%" align="center"><a href="docs/media/private-prototype-seek-results.png"><img src="docs/media/private-prototype-seek-results.png" alt="历史私有原型中的 SEEK results 识别" width="100%"></a></td>
    <td width="33%" align="center"><a href="docs/media/private-prototype-seek-job-detail.png"><img src="docs/media/private-prototype-seek-job-detail.png" alt="历史私有原型中的 SEEK job-detail 状态" width="100%"></a></td>
    <td width="33%" align="center"><a href="docs/media/private-prototype-seek-application.png"><img src="docs/media/private-prototype-seek-application.png" alt="历史私有原型中经过脱敏的 SEEK application entry" width="100%"></a></td>
  </tr>
  <tr>
    <td align="center"><strong>Results</strong><br>搜索控件、结果区域和 job-card evidence。</td>
    <td align="center"><strong>Job Detail</strong><br>详情抽屉、metadata、description 和独立的 Quick apply 入口。</td>
    <td align="center"><strong>Application Entry</strong><br>个人内容已脱敏。这里只展示 document-selection entry，不证明表单完成、Continue/Next 或 submission。</td>
  </tr>
</table>

### SEEK reference recording · Partial historical visual corroboration

![受控 SEEK 浏览器录屏](docs/media/seek-three-interface-real-agent-demo.gif)

这段经过脱敏的 16 秒历史录屏覆盖 SEEK 首页/列表上下文、岗位详情和同站点 Apply entry。它没有填写表单、输入文字、上传文件、点击 Continue/Next，也没有 final submission。它只是有界 GUI 转移的视觉佐证，不是 Portfolio v1 Controlled Live Workflow Proof。它本身**不能**证明 restart/reload、current relocation、Gate lineage、semantic verification、receipt 或已保存 workflow graph 的自主遍历。

SEEK 只是 **reference workflow**，不是产品定位。冻结的 Portfolio v1 目标刻意更窄：**Job Detail → `open_apply_flow` → Apply Entry → Safe Stop**。`open_detail` 是 post-v1 工程目标，不是 v1 验收条件或 Homepage traversal 主张。

## 工程亮点

- **Capture freshness 和 lineage：** 候选绑定 capture identity、viewport、source、bbox、click point 和 freshness，避免静默混用新旧坐标。
- **Revision-bound review：** evidence 或语义变化会撤销过期的人审事实，不会乐观继承旧批准。
- **可持久化但不授权的资产：** workflow revision 和 hash 保存经审核知识，但 storage 不能变成权限。
- **Semantic action taxonomy：** `open_detail`、`open_apply_flow` 与字段修改、继续流程和终端提交严格区分。
- **Fail-closed ambiguity：** stale observation、错误窗口、identity 不匹配、unknown intent 和 ambiguous candidate 都是 zero-click outcome。
- **Durable verification receipts：** 内部 controller 会持久化 dispatch、verification checkpoint、C2 evidence 和精确配对的 terminal receipt；duplicate/restart lookup 不会盲目重新 dispatch。如果在 terminal persistence 前崩溃，恢复时可能被动地重新 capture C2，但绝不会重新 dispatch 动作。这是确定性的内部证据，不是 live proof。

## 本地运行

要求：Windows 10/11、Python `>=3.11,<3.12`、`uv`。

```powershell
git clone https://github.com/Desolate-Jix/agent-gui-runtime.git
cd agent-gui-runtime
uv sync
.\start_test_panel.bat
```

也可以直接启动本地 API：

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

受限本地 Agent Runtime callsite 提供 `POST /runtime/agent/session/start`、`POST /runtime/agent/intent/submit` 与 `POST /runtime/agent/confirmation/decide`。它仅允许 loopback，并假设单个 uvicorn worker。唯一 active reviewed asset、当前 bound window、workflow hashes、semantic action binding、evidence 与生产 backend 均由服务器选择，客户端不能提供。除了确定性 route proof，当前只有上文记录的一次受限真实 Windows/SEEK safe-stop receipt；不要把它推广成通用可用性。

仓库不分发模型权重和可选本地视觉服务。请勿提交个人截图、浏览器会话、凭据、模型权重或私有 trace。

## Target State 与 Roadmap

Portfolio v1 已作为**受限 Quick Apply-only release 冻结**，并拥有经过独立审查的 tracked public evidence package：

> **W2 人工审核的 Job Detail → release asset 精确 reload → deterministic exact-asset proof → 一次 controlled-live `open_apply_flow` → 全新 Apply Entry `SAFE_STOP/stop_boundary` receipt → public evidence review 已通过。**

current semantic `open_detail` live proof 已移入 **post-v1**，不再是 Portfolio v1 验收条件。历史 `open_detail` artifact 的 semantic verifier 不适用，因此仍不会被提升为 live proof。“已冻结”只表示声明的受限范围已闭合，不表示 Stable、通用可靠性、Provider accuracy、通用 SEEK 导航、表单填写、Continue/Next、上传、final submit、无人值守或 production readiness。

Automatic provider selection、remote execution、raw-coordinate Agent authority、ATS traversal、表单填写、上传、Continue/Next 和 final submission 都不是 Portfolio v1 能力。

## Safety 与 Non-goals

- Learning draft、provider evidence、workflow graph 和已发布资产永远不授权动作。
- `final_submit`、`send`、`confirm`、`payment` 和 `delete` 在本 Portfolio slice 中保持禁止。
- v1 reference workflow 遇到表单字段、上传和 Continue/Next 时必须 Safe Stop；proof 中不包含任何 form mutation。
- 看似合理的模型输出不是执行许可。Unknown、stale、ambiguous、wrong-window 或 unverified 状态应停止，而不是猜测。
- 本项目不是无人值守的求职申请服务，也不声称覆盖所有 Windows 应用、网站、模型或 Provider。

## 仓库地图

- `app/learn/` — evidence contracts、recognition、learning tasks 和 review projections。
- `app/agent/` — reviewed workflow assets、semantic Agent contracts、replay 和 receipt logic。
- `app/operation/` — window binding、observation、grounding 和 operation boundaries。
- `app/gate/` — candidate、window、dataflow 和 dangerous-action checks。
- `app/web_panel/` — 本地 learning、review 和 replay workspace。
- `schemas/uei/v1/` — Universal Evidence Interface contracts。
- `tests/` — contract、regression 和 safety-boundary checks。
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — 详细架构边界和不变量。
- [`CHANGELOG.md`](CHANGELOG.md) — release 范围变更和限制。
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) — 可选组件和许可证边界。

<details>
<summary>Synthetic framework evidence</summary>

![Synthetic framework demo](docs/media/demo.gif)

`demo.gif` 只证明 deterministic synthetic framework 具备 click capability，并能观察 synthetic result。它**不是** live GUI evidence，也不证明 Agent 行为、模型准确率、人工审核、current relocation 或 saved-workflow replay。

</details>

## License

[ISC](LICENSE)


## Simple-native provider smoke（Phase A）

`python scripts/run_simple_native_provider_smoke.py` 默认进入离线 `preflight`：只校验 `case-001` 至 `case-005`，绝不启动模型，也不执行任何动作。`replay` 使用可注入的原生形状 fixture，写入仅回归诊断、不可 promotion 的 25-target 报告。它把每张公开 regression 图片逐字节复制到 artifact 目录，封存带有明确 empty/unavailable OCR 与 UIA 观测的 capture bundle；所有 candidate bbox 只来自 Omni 输出，ordinal 展开后必须进入既有权威 Qwen parser。

三个协议保持独立：Omni 只输出 `{bbox,type,content,interactivity}`；Qwen 在本地保留完整 runtime request，模型只看 ordinal `{i,box,active}` candidates；VISTA 接收新持久化的 candidate crop，且只返回 bare normalized `[x,y]`。runtime ID、capture lineage、crop hash、坐标变换、metrics 和 review-only 字段均由 adapter 持有。provider 阶段固定批处理为 `Omni -> cleanup -> Qwen -> cleanup -> VISTA -> cleanup`；受管 cleanup 未验证时不得进入下一阶段。只有 scorer 能在 provider artifact 封存后打开 Gold，并先按精确 role + label 连接，再检查 point geometry。


> 实现状态：当前 CLI 仅支持 replay/preflight。即使提供 `--operator-approved-model-start`，`actual` 也会以 `BLOCKED` fail-closed：仓库还缺少带精确逐 provider cleanup 观测的 managed compact-Qwen ordinal-run 边界，以及 managed VISTA acquire/run/release 边界；不会用 generic lifecycle receipt 冒充完成。
