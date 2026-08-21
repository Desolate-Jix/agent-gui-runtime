# agent-gui-runtime

**版本 0.3.0 · Windows GUI Agent Runtime**

[English](README.en.md)

## Hero

> 一个 Windows GUI Agent 运行时：把不确定的界面探索转化为可复用、经人工审核、在运行时重新定位并可验证的语义工作流。

这不是重复点击旧截图坐标的工具。每次尝试都绑定当前窗口、当前证据和明确 Gate；证据不足时安全停止，而不是猜测。

![SEEK recorded gated Agent path](docs/media/seek-three-interface-real-agent-demo.gif)

公开、脱敏的 SEEK **recorded gated Agent path**：没有表单填写、输入、上传、Continue/Next 或提交。它展示受控 gated path，不证明 Agent 可以自主端到端遍历已保存 workflow 图。

## Why GUI Agents Break

GUI 会变化、窗口会切换、滚动可能作用到错误容器；模型或 OCR 猜测也不等于可执行目标。历史学习结果只是**语义和证据先验**：真实操作必须在当前 UI 重新定位、通过 Gate，并验证效果。

## Core Workflow

```text
Uncertain exploration → evidence → human-reviewed reusable workflow
→ runtime relocation on the current UI → Gate → bounded execution-attempt budget
→ Verify, recover safely, or stop
```

1. **Explore**：收集当前窗口的截图、UIA、OCR、视觉和可选 parser 证据。
2. **Review**：人工修正界面、候选操作和转移；学习结果本身从不授权执行。
3. **Reuse**：保存审核后的语义状态、条件和验证规则。
4. **Relocate**：重新捕获并在当前窗口重新 grounding；历史坐标不能直接执行。
5. **Gate and execute**：只对低风险、当前证据充分的单个动作开放受限的执行尝试预算。
6. **Verify or stop**：检查效果；漂移、歧义、失败或风险升级时保存诊断证据并停止。

## What Makes This Different

- **Evidence is not authority**：模型输出、旧坐标和面板按钮都不能绕过当前 UI Gate。
- **Human review is revision-bound**：语义或证据变化会撤销旧的人审事实。
- **Semantic replay, not coordinate replay**：复用状态、目标语义、条件和验证规则；runtime 仍须重新定位。
- **Gate-first safety**：终端提交、发送、确认、付款和删除保持禁止。
- **Verification is first-class**：未能证明效果的尝试不会被包装成成功。

## SEEK Reference Workflow

SEEK 是**参考实现**，不是产品身份。受控路径覆盖：**SEEK 首页 → 岗位详情 → 同站点 Apply / Quick Apply 入口**。

路径在申请入口停止：没有表单填写、输入、上传、Continue/Next 或提交。它检验的是“当前 UI 重新定位 → Gate → 操作后验证”的受控切片；不代表 ATS 端到端、live safe-fill、无人值守求职，或已保存 workflow 图的自主遍历。

## Evidence and Current Status

下表是能力边界，不是“全部测试通过”或生产可靠性徽章。

| Capability | Status | Evidence today | Not claimed |
| --- | --- | --- | --- |
| Bounded Gate contract and terminal-action blocking | **Stable** | 在受限合同范围内约束单步动作；危险终端动作 fail closed。 | 不表示任意网站、控件或长流程都可自动执行。 |
| Reviewed workflow assets and persistence | **Stable** | 人审 revision、evidence lineage、编译和内容寻址发布拥有受控持久化与篡改检查。 | 已发布资产不是操作授权；仍需当前捕获、重新定位、Gate 和验证。 |
| Learning evidence, human review, and workflow creation | **Partial** | 面板可生成 display-only 学习草稿、审核候选和应用范围 workflow review。 | 不证明泛化视觉理解、人工审阅质量或真实多窗口成功率。 |
| Runtime relocation, execution, verification, and Agent integration | **Partial** | 受控 SEEK 入口路径与离线/受控 replay 覆盖部分重新定位、Gate 和停止行为。 | Production live workflow orchestrator 与 server-owned current-observation bridge 尚未完成。 |
| Scroll wrong-scope effect verification | **Partial** | 有显式错误作用域检测合同和回归路径。 | effect-verification 缺口尚未关闭；不声称滚动验证完整。 |
| Deterministic framework demo | **Prototype** | 公共 synthetic framework/harness 的 click 能力和 synthetic-result observation。 | 不证明 live GUI、真实 Agent、模型准确率或已保存 workflow 的端到端 replay。 |
| Universal Evidence Interface v1 (UEI) / OmniParser Shadow support | **Prototype** | 离线、review-only provider/shadow 基础设施和受限摘要投影。 | 不是主叙事，也不是生产 Learn、GUI、replay 或 Execute 集成。 |

## Architecture

```text
Window / screenshot / UIA / OCR / vision evidence
                    ↓
         Learning and human review workspace
                    ↓
      Reviewed semantic workflow + evidence lineage
                    ↓
  Current-window capture → relocation / grounding → Gate
                    ↓
      bounded execution-attempt budget → post-action observation
                    ↓
              verified effect, safe recovery, or safe stop
```

审核资产描述“要找什么、为什么可尝试、如何判断效果”；runtime 负责证明这些条件在**此刻**的目标窗口仍成立。

## Engineering Highlights

1. **Capture freshness and lineage**：候选带 capture identity、viewport、来源、bbox、point 和 freshness，防止新旧截图坐标混用。
2. **Bounded human correction**：受限编辑证据框、语义、操作和转移，并让变化撤销过期批准。
3. **Application-scoped workflow review**：多个学习界面可组成应用范围图；每个节点保留自己的证据。
4. **Current-UI relocation**：保存几何只作先验；runtime 重新捕获、重新定位并绑定当前候选。
5. **Gate-first execution**：真实点击应经过统一 gated action API；final-submit 类动作硬阻断。
6. **Post-action evidence and recovery**：dispatch 不是完成；无新证据证明效果时记录可诊断 safe stop。

## Demo and Evidence

### Deterministic synthetic harness — synthetic (15.0 s)

![Deterministic synthetic framework demo](docs/media/demo.gif)

`demo.gif` 唯一主张的证据是：确定性 synthetic framework/harness 具备 click 能力，并能观察 synthetic 结果。它不证明 live GUI 可靠性、真实 Agent 行为、模型准确率、人工审核，或已保存 workflow 的端到端 replay。

公共来源：[`demo.gif`](https://github.com/Desolate-Jix/windows-gui-agent-runtime/blob/main/docs/demo.gif)；SHA-256：`302e049140bc0a2868258ea55b25aec7d22279bfc0d27e46b04efa4d318e73c0`。

### SEEK recorded gated Agent path — public redacted recording (16.0 s)

该 GIF 已置于 Hero。公共来源：[`seek-three-interface-real-agent-demo.gif`](https://github.com/Desolate-Jix/windows-gui-agent-runtime/blob/main/docs/seek-three-interface-real-agent-demo.gif)；SHA-256：`80ab0a5055d0e700f009642bd414ffdbfef1426307537dfd976c822de9d88b4f`。上文的范围和“无表单动作”说明来自该公开源仓库；本仓库不独立主张完整 frame-to-trace lineage，也不主张 autonomous saved-workflow traversal。

## Run Locally

要求：Windows 10/11、Python `>=3.11,<3.12`、[`uv`](https://docs.astral.sh/uv/)。

```powershell
git clone https://github.com/Desolate-Jix/agent-gui-runtime.git
cd agent-gui-runtime
uv sync
.\start_test_panel.bat
```

也可手动启动：`uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`。

模型权重和可选本地视觉服务不随仓库分发。请勿将个人截图、浏览器会话、token、运行日志或模型权重提交到 Git。

## Near-term Roadmap

1. 完成 production live workflow orchestrator 与 server-owned current-observation bridge，并以受控本地窗口验证。
2. 关闭 scroll wrong-scope effect-verification 缺口，再扩展 read/scroll 类动作。
3. 扩展受控跨应用/跨界面 evidence corpus，同时保持人工审核、重新定位和 Gate 边界。

## Safety and Non-goals

- 不是无人值守的求职提交器；“模型看起来合理”不是执行许可。
- 学习草稿、PathGraph、审阅结果和已发布 workflow 都是非授权资产；执行仍需要当前证据与 Gate。
- `final_submit`、`send`、`confirm`、`payment`、`delete` 保持禁止。
- 通用请求使用受限 execution-attempt budget（默认最多 2 次）；reviewed-workflow replay 强制为 1 次。未知、过期、歧义、错误窗口或高风险目标优先停止。
- 不声称全网站、全 Windows 应用、所有模型或无人值守流程可靠性。

## Repository Map and Deep Dives

- `app/learn/` — 学习任务、证据合同、识别和审核投影。
- `app/operation/` — 窗口绑定、观察、定位、候选和 runtime 操作接口。
- `app/gate/` — 共享安全 Gate、数据流合同与最终提交阻断。
- `app/web_panel/` — 本地学习、审核和 replay 面板。
- `tests/` — 合同、回归和安全边界测试。
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — 架构与边界深入说明。
- [`CHANGELOG.md`](CHANGELOG.md) — 窄验证与已知限制。
- [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) — 可选第三方组件、获取与许可证边界。

UEI / OmniParser 是支持性 Prototype：它可提供受限、review-only parser evidence summary，不能成为点击授权或产品主线。

## Release and License

- Version: `0.3.0`
- Root project license: [`ISC`](LICENSE)
- Changes: [`CHANGELOG.md`](CHANGELOG.md)

本文中的“Stable”“Partial”“Prototype”和“Evidence”均描述当前受控范围；它们不是 CI-backed 生产可靠性承诺，也不扩展为通用 live GUI 或自动化成功率声明。
