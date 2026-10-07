# 2026-10-07 当前release-ready状态 / Current release-ready status

第三批source14/GUI12已完成匹配冻结与实装限定验收，状态为release-ready。Main与独立Sol各记录2个教学事件、6个预期连续场景（5个正例完成，负例一次点击后判失败，无重复输入）；GUI Save原job为completed并返回captured状态的动作后截图，关闭重开后图像关闭选项保持，最终cleanup完成。第一批终态JSON读取失败及第二批空标题清除绑定失败原记录保留；旧便携candidate02未知退出未宣称修复，stablev0.1.1保持原发布。网络发布与下载核对单独记录在对应发行页。 / The matched third source14/GUI12 pair is release-ready after bounded installed acceptance. Main and independent Sol each recorded two teaching events and six expected continuous cases: five positive completions and one negative failure after a single click without replay. The original GUI Save job completed with captured post-action evidence; image disablement persisted across close/reopen and cleanup completed. Both earlier failures and the unexplained excluded portable exit remain historical. Stablev0.1.1 is unchanged; publication and download verification are recorded separately on the release page.

当前安装包含默认图像规则提议、人工区域编辑及可关闭图像核验；不确定保留原请求交Agent审核，不重放输入。流程图引用图钉固定的界面版本，附加成员不自动创建跳转。GUI页签为“结果与读取”。本地模型权重可选；本轮没有新增真实API供应商测试，不宣称通用准确率、速度或模型用量收益。 / Current installers include default image proposals, editable regions and persistent disablement. Uncertain evidence retains the original request for Agent review without replay. Graphs pin interface versions and membership does not create transitions. The GUI tab is Results and readback. Local weights are optional; no new real API-provider tests or general accuracy, speed or usage claims.

| 组件 / Component | 版本 / Version | 冻结批次 / Frozen pair | Setup SHA256 |
|---|---|---|---|
| 执行 / Execution | `0.1.2-preview.1` | source14 / installers-execution-13 | `fc8e343549d84d3deceb3d116451bc739729402fdefc2b5a1ba5a097e96ea5e7` |
| 可选学习 / Optional learning | `0.1.0-preview.1` | GUI12 / installers-learning-12 | `d67443fdb9c77d60db4063a66b501e1be1ae45baf9c2af2b2a8cbecad86728b9` |

[最终限定验收 / Final bounded acceptance](docs/verification/LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)。下方原段落为原冻结时点历史记录；版本与限制以本节及最终验收为准，不覆盖首次失败。 / Original sections below describe historical freezes; use this section and final acceptance for current scope while preserving first failures.

---

# 可选学习候选范围 / Optional learning candidate scope

学习0.1.0-preview.1与兼容执行0.1.2-preview.1分别安装、升级和卸载；学习是可选组件。离线编辑库不需宿主或模型，采集及试运行按需连接已有兼容执行会话。API/当前Agent/明确视觉委派不强制本地模型。 / Components have separate lifecycles; learning is optional and its offline library needs no host or model. Explicit attachment enables teaching/trials, with local weights optional for API/Agent routes.

已有source11/Setup10与GUI09/Setup09的新内容限定实装验收作为旧冻结基线保留；当前图像规则、编辑及等待修复尚未进入这两个安装器，最终候选需重新冻结并验收。本次只交付新的独立安装器，旧candidate02不交付，未知退出记录保留，不宣称根因修复。 / Retain the installed source11/Setup10 and GUI09/Setup09 acceptance as a prior baseline. Current image and wait changes require a new frozen pair and installed acceptance. Deliver independent installers only; exclude candidate02 and preserve its unexplained exit without claiming a fix.

最终文档可与冻结包不同；非文档生产实现和资源必须匹配验收冻结清单。公开源码/资产排除用户库、截图、模型、凭据及本地构建证据。 / Final documentation may differ from the freeze, but production code/resources must match. Exclude user data, models, secrets and local evidence from public assets.

见[使用说明](docs/LEARNING_PREVIEW_QUICKSTART.md)与[实装验收](docs/verification/LEARNING_PREVIEW_NATIVE_ACCEPTANCE.md)。以下正式v0.1.1范围保留，不代表学习候选已发布。 / The stable v0.1.1 scope below remains separate.

---

# v0.1.1 执行模式正式补丁范围 / Execution-mode patch release scope

源码及隔离包各 2086 项、STDIO 七工具检查通过；294 个包内项目模块、739 项冻结清单核验通过。本方及独立 Agent 在同一冻结运行时完成全新原生单项、连续使用、429 恢复和最终清理，原始回执／PNG／trace 审计通过。首次 identity 拒绝原因未定；Note fixture 修复经 19 项离线检查、长中英前缀本方回归与独立复测通过，未修改冻结运行时。见 [v0.1.1 验收](docs/verification/V011_RELEASE_ACCEPTANCE.md)；[v0.1.0 验收](docs/verification/V010_RELEASE_ACCEPTANCE.md) 保留为历史证据。 / Source and isolated bundle each passed 2086 checks, plus seven-tool STDIO, 294 bundle-local module and 739 manifest checks. Main-agent and independent fresh native single/continuous/429-recovery/cleanup journeys and original-evidence audit passed on the same frozen runtime. The initial identity-rejection cause remains unresolved; Note fixture correction passed 19 offline checks, long Chinese/English-prefix main regression and independent retesting without changing the frozen runtime. v0.1.0 evidence remains historical.

本版只发布执行模式，不包含学习模式。真实输入需有人看护；危险提交操作不在支持范围。 / This release contains execution mode only; learning is excluded. Supervise real input. High-consequence submissions are outside the supported scope.

**验收范围 / Acceptance scope:** 本补丁聚焦执行模块归属、同对象兼容别名、未接线的判断／用量合同及发布依赖。真实操作使用 STDIO、回环 HTTP 与全新原生窗口；回环 fixture 不证明真实供应商连通、识别准确率或费用。local／当前 Agent／委派 Agent 保留且由回归覆盖，历史模型实机结果不冒充本轮重测。 / This patch covers execution ownership, same-object aliases, unwired judgment/usage contracts and delivery dependencies. Real operations use STDIO, loopback HTTP and fresh native windows; loopback fixtures do not certify live-provider connectivity, accuracy or cost. Existing local/current/delegate routes remain regression-covered; historical model-driven runs are not new live acceptance.

本版包含 `agent_current`、`agent_delegate`、外部 `external_api` 定位路由和可恢复 Agent 组合命令。Agent 路线不需本地 VISTA/OCR 权重；`read_text` 返回原图供 Agent 阅读。外部 API 将当前截图发送给配置端点，并把定位结果交给公共执行器；它不自动判断任务完成，错误不重试、不回退。供应商必须支持已定义的图像及 JSON 协议，但本版不保证任意服务兼容或识别准确率。学习启动入口不发布。详见 [API 接入](docs/development/EXTERNAL_VISION_API.md)、[Agent 组合协议](docs/development/AGENT_BATCH_PROTOCOL.md) 与 [Agent 视觉设计](docs/development/AGENT_VISION_BACKENDS_DESIGN.md)。

This release includes `agent_current`, `agent_delegate`, external `external_api` grounding and resumable Agent commands. Agent routes need no local VISTA/OCR weights; `read_text` returns the original image to the Agent. The API route sends the current screenshot to its configured endpoint and passes grounding to the shared executor; it neither judges task completion nor retries or falls back on errors. Providers must support the documented image/JSON protocol, but compatibility and accuracy are not guaranteed for every provider. Learning startup entrypoints are excluded. See the [API guide](docs/development/EXTERNAL_VISION_API.md), [Agent batch protocol](docs/development/AGENT_BATCH_PROTOCOL.md) and [Agent vision design](docs/development/AGENT_VISION_BACKENDS_DESIGN.md).

## Included / 包含

- 八个执行模块迁入 `app.execution`，旧路径为同对象别名，保留类身份及 monkeypatch 传播；原 owner 与公共动作 API 不变。 / Eight execution modules move to `app.execution` with same-object legacy aliases, preserving class identity, patch propagation, owner and public action API. See [模块边界 / Boundaries](docs/EXECUTION_MODULE_BOUNDARIES.md).
- `OptionalJudgment`／`ModelUsage` 仅为未接线合同，不新增公开判断工具或生产模型调用；默认关闭，不采集判断证据、不联网、不授权输入，未知用量保持 null。 / Optional judgment/usage remain unwired contracts without public judgment tools or production model calls; inactive judgment creates no evidence or transport and grants no input authority. Unknown usage stays null. See [合同 / Contract](docs/OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md).

- MCP stdio runtime with seven tools, including `instant_run` and bounded `input_sequence`.
- Fresh visible-image OCR, compact original-image receipts, 23 editing keys, window/session lifecycle and explicit cleanup verification.
- Conditional observation for a known UIA text/control marker; default waits and confirmation boundaries are unchanged.
- Bilingual setup and agent guidance, plus verification reports under `docs/verification/`.
- Installed desktop app discovery and launch by name/ID/path; automatic desktop target resolution. / 安装应用发现与名称/ID/路径启动，桌面目标自动解析。
- Structured model startup/cleanup diagnostics, retained-owner cleanup retry and unresolved-session start rejection. / 模型诊断、保留原 owner 的清理重试与结构化启动拒绝。
- `form_fill` through existing tools: 1–32 text/date/dropdown/checkbox/radio fields with partial receipts and remaining indexes. Optional `tab_sequence` verifies each named writable text field after Tab; default `recognize_each` supports mixed fields. Unique current UIA text geometry may precede visual inference. / 通过既有工具组合填写 1–32 项，返回完成与剩余索引；可选 Tab 续填逐项核对标签，默认逐项识别支持混合字段，唯一当前文本框几何可先于视觉定位。See / 参见 [form-fill contract / 表单契约](docs/verification/EXECUTION_FORM_FILL.md).
- Shared label, popup, date and native-file-dialog fixes; JSON-quoted labels preserve embedded quotes and backslashes rather than selecting a truncated name. No new MCP tool, spreadsheet editing, automatic final submission or replay. / 通用标签、弹窗、日期及原生文件选择修复；转义标签不再截断为另一字段名。不新增 MCP 工具、电子表格编辑、自动提交或重放。
- Learning GUI/STDIO startup entrypoints are excluded. Shared historically named runtime dependencies remain; no new lightweight-learning code or tools are included. / 排除学习 GUI/STDIO 启动入口，保留共用依赖；不带入新轻量学习代码和工具。

## Evidence and limits / 证据与边界

- Source live evidence includes repeated mixed eight-field forms, named-text Tab batches, invalid-option interruption/recovery and native synthetic-file selection/cancel/reopen. See [batch acceptance](docs/verification/BATCH_FORM_LIVE_ACCEPTANCE.md). These source results are not frozen-candidate or independent acceptance. / 源码实测包括混合八项连续填写、具名 Tab 组合、非法选项中断恢复、虚构附件选择及取消重开；不能代替冻结包与独立验收。
- Historical test.7 results, counts and retained failures are in the [test.7 acceptance record](docs/verification/TEST7_CANDIDATE_ACCEPTANCE.md); they are not v0.1.0 evidence. / test.7 的历史结果、数量和首次失败见其验收记录，不计作 v0.1.0 证据。
- Visual multi-select, custom date widgets, automatic option scrolling and arbitrary websites are not universally supported. Model localization may refuse a target; partial completion must be inspected rather than automatically replayed. / 视觉多选、自定义日期控件、自动滚动选项和任意网站尚非通用支持；定位可拒绝，需检查部分结果而非自动重放。
- Final documentation may differ from the frozen candidate; all non-document runtime/configuration/test files must match its manifest before archiving. / 最终文档可更新，归档前所有非文档运行时／配置／测试文件必须与冻结验收包摘要一致。
- This does not claim cross-site accuracy, whole-page completion, unattended automation, arbitrary-provider compatibility or accuracy, universal hardware support, or support for payment, sending, deletion or final submission.
- Models, dependencies and user data are not shipped. Use [FRIEND_SETUP.md](FRIEND_SETUP.md), then run no-input smoke before explicitly authorizing supervised low-risk input.

The package builder is `scripts/build_instant_bundle.py`. The bundle is expected to contain maintained source, `README.md`, `AGENT_GUIDE.md`, `FRIEND_SETUP.md`, `RELEASE_SCOPE.md`, `CHANGELOG.md`, `docs/verification/` and scripts. Run package validation and the acceptance plan before publication.
