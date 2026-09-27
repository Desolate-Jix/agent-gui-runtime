# v0.1.0 执行模式发布验收 / Execution release acceptance

2026-09-28。运行时验收通过；最终交付只更新文档，非文档源码须与冻结候选一致。 / Runtime acceptance passed; final delivery changes documentation only and must retain identical non-document sources.

## 范围 / Scope

- 基线 c7a3099607d039fb3e377be1de7ff26151d1101c；只发布执行模式，保留本地、当前 Agent、显式委派 Agent，并正式配送外部视觉 API 宿主接线。学习模式未包含。 / Execution-only baseline; local, current-agent, delegated-agent and external-API routes; no learning product.
- API 验收目标是配置、HTTP 图像协议与公共执行流程。回环测试服务不是真实视觉供应商，不能证明在线兼容性、准确率、速度或费用。 / API acceptance covers configuration, image transport and the shared execution flow. A loopback fixture is not provider/accuracy/latency/cost validation.
- 使用全新数据根及本轮原生测试窗口，不访问、清理或改动日常浏览器配置。模型权重仅只读复用。 / Use fresh data and an owned native fixture; no everyday browser profile access or changes; weights may be reused read-only.

## 验收顺序 / Gates

1. 源码单元与契约、隔离包真实入口依赖及全量新版回归。 / Source contracts, isolated real entrypoints and native regression.
2. 本方同会话单项与连续操作、中断、弹窗、恢复及最终清理。 / Main-agent single/continuous operations, interruption, dialogs, recovery and cleanup.
3. 同一冻结候选独立 Agent 复核与验收；任何产品修复需相关回归后再冻结。 / Independent acceptance on the same frozen candidate; relevant regression and a new freeze after runtime fixes.
4. 非文档文件与冻结 manifest 一致、ZIP/SHA-256、远端提交/tag/公开下载核验。 / Runtime manifest equality, archive/hash and remote/public-download verification.

## 本轮结果 / Results

- 源码复测：2040 passed。首轮因测试驱动未创建 `--basetemp` 父目录得到 1417 passed / 623 setup errors；诊断确认 FileNotFoundError，修复测试目录后复测通过。未将复测改记为首次成功。 / Source rerun: 2040 passed; first attempt retained as a test-harness directory setup failure.
- 冻结候选 `v0.1.0-candidate01`：隔离解释器 `python -I` 在包目录运行新版测试，2040 passed；283 个项目模块均来自包内，无工作树导入；723 项 manifest 摘要一致。真实执行入口导入和请求校验通过，与真实物理输入分别报告。 / Isolated candidate: 2040 passed, 283 in-bundle project module origins, 723 matching manifest hashes; real input-entrypoint dependency checks passed separately from live input.
- 无 torch/transformers 的解释器运行真实 STDIO smoke：服务端 0.1.0、7 工具、非法请求入队前拒绝、同 ID 回读不重放、停止后拒绝、清理和重连回读均通过。此项不请求视觉服务、不派发输入。 / STDIO smoke without torch/transformers passed identity, tools, admission rejection, no replay, cleanup and reconnect; it does not call a provider or dispatch input.
- 本方 API 实机：同一 MCP 连接和原生窗口完成单项计数、两轮双字段填写、弹窗打开/精确绑定/关闭、HTTP 429 零输入、恢复后新命令及清理。HTTP 服务逐次接收真实 PNG，定位新图里的夹具控件，复用公共输入链，未替换 OS 输入或窗口边界。 / Main-agent API journey completed single action, two form rounds, dialog binding/closing, zero-input HTTP 429, explicit recovery and cleanup in one MCP session. The loopback service consumes real PNGs; OS input/window boundaries are real.
- 同候选独立 Agent 重复该链路，全新目录和新窗口；两方最终均为 counter=2、dialog opened=closed=1，字段值与原图一致。主 Agent 复核两方共 28 份终态回执、77 个原图摘要。 / Independent acceptance repeated the journey on the same frozen candidate with fresh data/window; both ended with counter=2, one opened/closed dialog and matching field values. Main-agent audit verified 28 terminal receipts and 77 image hashes.
- 两方宿主均 `cleanup_verified=true` 且退出；Qt 窗口正常关闭，回环服务停止。候选 manifest 自身 SHA-256：`4dba91f904e977a48bb5a3b4f0d8c803868291548938f9d5875b554c3f004c76`，独立复测前后所有文件未变。 / Both hosts exited with verified cleanup; fixture windows and loopback services closed. All candidate files remained unchanged across independent acceptance.

## 首次失败与恢复 / First failures and recovery

- 首轮 pytest 未建立输出父目录，属于测试驱动错误；修正后重新运行，不改记首次结果。 / Missing pytest output parent was a harness error; retained separately from the passing rerun.
- 本方首个 form_fill：测试服务错误地把 City 字段定位成按钮。公共字段身份/焦点检查拒绝派发；修正测试服务的当前 PNG 字段定位后，两轮填写通过，产品源码未改。 / The fixture initially returned a button for City; shared field/focus validation prevented input. Correcting the PNG fixture mapping yielded two passing rounds without product changes.
- 首个 Escape 使用了不符合契约的键名和缺少坐标，入队前拒绝；修正后向父窗口发键又被前台身份检查拒绝。发现并明确绑定本轮弹窗，再发送 Escape 成功；没有削弱检查。 / Invalid Escape syntax was rejected before queueing, then the stale parent binding was blocked by foreground identity. Discovering/binding the exact dialog allowed Escape without weakening checks.
- 独立操作链未遇到产品失败。初次辅助清单文件名查找错误随后改用实际 `MANIFEST.json`；不属于运行时失败。 / No product failure occurred in the independent journey; an auxiliary manifest filename lookup was corrected to MANIFEST.json.

## 边界 / Limits

- 本版按用户范围验证 API 接口与执行流程，未使用真实付费视觉服务；不证明任意服务商兼容性、识别准确率、延迟或费用。管理员进程密钥环境继承、跨设备首次安装未在本轮认证。 / No paid-provider test, universal compatibility/accuracy/latency/cost claim, elevated-key inheritance or cross-device install certification.
- local/当前 Agent/委派 Agent 的实机模型验证保留为 test.8 历史，本轮没有重新运行这些模型；相关公共契约通过本轮回归覆盖。 / Model-driven local/current/delegate live results remain test.8 history; this release reran their regression contracts rather than the models.
- 测试仅使用新建原生窗口，未访问或改动日常浏览器配置。 / Acceptance used fresh native windows without accessing or changing everyday browser profiles.

本机原始记录 / Local raw evidence: `D:/AgentReviewAcceptance/20260928-execution-stable-01`。
