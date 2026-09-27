# v0.1.0 执行模式正式版范围 / Execution-mode release scope

源码及隔离候选各 2040 项通过；本方及独立 Agent 在同一冻结候选完成 API 路线实机单项、连续填写、弹窗、限流恢复与清理。具体范围和首次失败见 [验收记录](docs/verification/V010_RELEASE_ACCEPTANCE.md)。 / Source and isolated candidate each passed 2040 checks. Main-agent and independent API-route native journeys cover single actions, repeated forms, dialogs, rate-limit recovery and cleanup on the same frozen runtime; see acceptance for evidence and first failures.

本版只发布执行模式，不包含学习模式。真实输入需有人看护；危险提交操作不在支持范围。 / This release contains execution mode only; learning is excluded. Supervise real input. High-consequence submissions are outside the supported scope.

**验收范围 / Acceptance scope:** 本轮聚焦新增 API 宿主链及发布依赖，使用真实 STDIO、回环 HTTP 和原生窗口；local/当前 Agent/委派 Agent 由新版回归覆盖，其模型实机历史保留在 test.8 记录，不冒充本轮重测。 / This release validates the new API host path and delivery dependencies through real STDIO, loopback HTTP and native windows. Regression covers existing local/current/delegate paths; their model-driven live history remains test.8 evidence, not a new live rerun.

本版包含 `agent_current`、`agent_delegate`、外部 `external_api` 定位路由和可恢复 Agent 组合命令。Agent 路线不需本地 VISTA/OCR 权重；`read_text` 返回原图供 Agent 阅读。外部 API 将当前截图发送给配置端点，并把定位结果交给公共执行器；它不自动判断任务完成，错误不重试、不回退。供应商必须支持已定义的图像及 JSON 协议，但本版不保证任意服务兼容或识别准确率。学习启动入口不发布。详见 [API 接入](docs/development/EXTERNAL_VISION_API.md)、[Agent 组合协议](docs/development/AGENT_BATCH_PROTOCOL.md) 与 [Agent 视觉设计](docs/development/AGENT_VISION_BACKENDS_DESIGN.md)。

This release includes `agent_current`, `agent_delegate`, external `external_api` grounding and resumable Agent commands. Agent routes need no local VISTA/OCR weights; `read_text` returns the original image to the Agent. The API route sends the current screenshot to its configured endpoint and passes grounding to the shared executor; it neither judges task completion nor retries or falls back on errors. Providers must support the documented image/JSON protocol, but compatibility and accuracy are not guaranteed for every provider. Learning startup entrypoints are excluded. See the [API guide](docs/development/EXTERNAL_VISION_API.md), [Agent batch protocol](docs/development/AGENT_BATCH_PROTOCOL.md) and [Agent vision design](docs/development/AGENT_VISION_BACKENDS_DESIGN.md).

## Included / 包含

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
