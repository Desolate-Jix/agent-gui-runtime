# agent-gui-runtime

**版本 0.3.0 · Windows GUI Agent Runtime**

[English](README.en.md)

把不确定的计算机操作变成可复核、可重放、可停止的运行时。这个项目的重点不是宣称“更好的 OCR”，而是把学习到的界面证据编译成有语义、有新鲜度约束、可验证且可恢复的操作流程。

## 主线

```text
Learn → Review → Compile → Verified Replay → Recovery
```

- **Learn**：从当前窗口获得截图、UIA、OCR、视觉模型和可选 parser 的证据。
- **Review**：在面板中修正框、页面职责、候选操作和转移关系；学习结果不是授权。
- **Compile**：把审核后的界面和转移编译为带语义动作、前置条件、证据 lineage、风险等级和验证规则的流程。
- **Verified Replay**：每次操作重新捕获当前界面，检查窗口、坐标空间、截图身份和 Gate，再通过统一 action API。
- **Recovery**：点击后验证效果；发生漂移、超时、错误或证据过期时停止并保留可诊断状态，不盲目重试。

## 当前定位与边界

这是一个本地 Windows 运行时和学习面板，不是无人值守的求职提交器。默认安全边界为：

- 学习草稿、审核结果和运行时 evidence 都是非授权资料：`artifact_is_authorization=false`、`execute_binding_enabled=false`。
- `final_submit`、`send`、`confirm`、`payment`、`delete` 等终端动作保持禁止；真实点击必须经过当前窗口、候选、置信度、`pre_click_decision_v1` 和事后验证。
- 运行时可以展示或 dry-run 低风险导航，但不会因为模型输出、旧坐标或面板按钮而自动放行危险动作。
- `artifacts/`、`logs/`、`models/`、`runtime_state/` 是本地运行输出或模型资源，不作为克隆仓库后即可获得的公开资源。

## 当前已验证的路径

### SEEK Quick Apply（受控入口）

当前受控证据覆盖：**SEEK 首页 → 岗位详情 → 同站点 Apply/Quick Apply 入口**。流程在申请入口处停止；没有填字段、输入、上传、Continue/Next，也没有 `Review and submit`、`Submit application`、`Send`、`Complete` 或付款等最终动作。这是用于验证学习回放、当前界面 grounding、Gate 和 post-action verification 的受控路径，不代表 ATS E2E、live safe-fill 或 unattended reliability。

### Learning workspace

面板把学习过程集中到一个工作台：截图/理解、编号和校准、人工修正、证据复核、融合、页面详情和只读 PathGraph。流程状态由后端合同持有；面板只展示状态、发起审核和呈现结果，不自行拼接下游授权。

已审核的界面可以保存为应用范围的流程草稿。流程节点保存源截图身份、证据哈希、页面职责、候选动作和验证规则；跨窗口、跨截图或缺 lineage 的旧候选会 fail closed。当前实现优先支持新内容的审核和回放，不迁移旧运行资产。

## OmniParser 状态

OmniParser 是**可选的 learning shadow/contact-sheet provider**，通过 `screen_parser_result_v1` 接入观察证据：

- 只能补充 review-only 的元素和图标语义提示，不能生成点击授权，也不能替代 UIA、OCR 或当前截图 Gate。
- 当前 smoke 输入是脱敏 contact sheet；这不是通用 UI 识别、实时窗口捕获或可点击性证明。
- OmniParser 代码、权重、虚拟环境和其依赖不随本仓库分发。用户如需启用，必须自行获取并接受对应组件许可；边界见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 安装与启动

要求：Windows 10/11、Python `>=3.11,<3.12`、[`uv`](https://docs.astral.sh/uv/)。

```powershell
git clone https://github.com/Desolate-Jix/agent-gui-runtime.git
cd agent-gui-runtime
uv sync
.\start_test_panel.bat
```

启动脚本会复用或选择本地端口，并打开面板。也可以手动启动：

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

可选的本地视觉模型需要额外资源；模型服务和权重不属于本仓库的发布内容。请先在面板模型管理器中确认显存与端口，再按对应 profile 启动。不要把个人截图、浏览器会话、token、运行日志或模型权重强制加入 Git。

## 代码入口

- `app/learn/`：学习任务、证据合同、识别与审核投影。
- `app/operation/`：窗口绑定、观察、定位、操作候选和执行接口。
- `app/gate/`：共享安全 Gate、数据流和最终提交阻断。
- `app/web_panel/`：学习/审核/回放面板。
- `configs/model_profiles/`：模型和 shadow provider 的声明式 profile。
- `scripts/`：离线 smoke、报告和维护工具。
- `tests/`：合同、回归和安全边界测试。

关键原则是**通用运行时合同优先于站点补丁**：候选必须带 `capture_id`、viewport、source、bbox、click point 和 freshness；滚动必须绑定目标容器；观察结果更新详情文本时，下游只能读取最新 snapshot；最终提交检测必须限定在活动表单/模态范围内。

## 后续主线

1. 已建立 `reviewed_workflow_asset_v2`：把人工审核结果、语义状态、转移、前置条件、预期效果、验证和恢复策略放进一个不可变、可追溯的资产；不迁移旧内容。
2. 后端已提供 `POST /panel/compile_reviewed_workflow_asset`、`/panel/publish_reviewed_workflow_asset` 和 `/panel/preview_reviewed_workflow_replay`：源工作流和资产均由服务端解析；发布前即时重编译并以 CAS revision/最终 SHA 做保护；预览为只读、非授权且必须提供 current observation，不会捕获屏幕或调用 action API。
3. 现有面板已提供明确的 Compile → CAS Publish → read-only Preview 控件：操作绑定已保存且 SHA 精确匹配的工作流，并要求 current observation；工作流编辑或切换会使状态失效，且不授予 action/capture 授权。纯离线 synthetic SEEK 三状态 E2E 已完成（首页 → 详情 → 申请入口停止），使用真实 compiler/CAS、面板 API、replay coordinator 和 navigation adapter envelope，仅替换依赖为 fake；已覆盖错误 origin、stale、ambiguous 和 recovery 负例，但没有真实 GUI、网络或 action。下一步是受控本地面板/current-observation smoke，经操作者批准后再做真实外部窗口 Demo；v2 当前仍不覆盖 `read`/`scroll` 的可执行回放。
4. 做通用窗口/坐标映射、长截图和滚动容器回放的性能基线；以可验证的稳定性优先，不把 OmniParser 当作授权层。
5. 已新增外部 checksum manifest 固定的纯离线合同基准：用不可变的 recorded Bare events 与 Runtime replay 比较分类、停止质量、有限恢复、延迟和派生 evidence digest。它不是实时 Bare Agent、模型能力、感知准确率或真实点击成功率测试。

生产级 live replay orchestrator 和服务器采集 current observation 的接线仍未完成；当前 preview 不能执行。Replay 模式已把单次动作请求限制为一次 attempt，`read`、`scroll`、`fill_field`、`continue_next_step`、上传和所有 final-submit 类动作仍 fail closed。本里程碑没有合入 recovery-feedback 持久化权威层，恢复证据仅来自结构化 `recovery_decision_v1` 和离线回放报告。

## 发布信息

- 版本：`0.3.0`
- 根项目许可证：[`ISC`](LICENSE)。
- 可选第三方组件的许可和获取边界：[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
- 本版本变更：[`CHANGELOG.md`](CHANGELOG.md)。

文档中的“已验证”只表示对应的受控路径或窄 smoke 已有证据；它不扩展为全软件、全网站或无人值守可靠性承诺。窄验证和已知限制见 `CHANGELOG.md` 及仓库内的设计文档。
