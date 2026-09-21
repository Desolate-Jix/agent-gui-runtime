# v0.1.0-test.4 · 执行模式测试版 / Execution-mode test release

本版本集中收拢 test.3 之后的源码修复，作为有人看护的 operator-mode 测试包交付；不是正式稳定版。/ This release consolidates fixes after test.3 as a supervised operator-mode test package; it is not production-stable.

## 本批内容 / Candidate changes

- 修复初始空剪贴板零序号的输入失败，以及精确链接首轮上下文、离屏同名项误判和裁图混入邻行；未放宽框外点、可见重名或不完整树检查。 / Repair empty-clipboard initialization and exact-link current-frame context without weakening ambiguous or inconsistent geometry checks. See EXECUTION_BROWSER_RETEST_20260921.md.

- 补齐直接引号标签、角色及相邻相反按钮的通用定位；唯一真实 UIA 按钮约束首次模型 ROI。进程退出与观察探针失败分开，不等同任务成功。 / Quoted-target identity and real-control grounding repaired; process absence is distinct from probe failure.
- 候选 09 之前的源码同会话 26 条命令曾覆盖真实记事本与文档站；后续独立测试仍暴露缺陷，因此不把历史成功当作最新修复的完整验收。 / The earlier 26-command source journey passed, but later independent defects prevent treating it as acceptance of subsequent repairs.
- 修复命名输入框被泛化为任意 Edit、原生编辑区右键落入滚动条、容器边缘遮挡误拒和绝对鼠标坐标取整。真实客户区与坐标来源明确保留；不新增审批或自动重放。 / Repair named-field identity, native editor context-click geometry, peripheral occlusion and absolute-pointer rounding without new approval or replay behavior.
- UIA 主树、外壳、菜单及浮窗使用有限子元素数组和统一有界遍历；重复、环、缺身份和 COM 异常保留不完整诊断，不把预算耗尽伪装成完整。 / Shared finite UIA enumeration retains incomplete diagnostics for cycles, duplicate/missing identities and read errors.
- 最小 MCP 宿主环境下，仅为模型子进程补齐缺失的 Windows 可执行扩展名与真实账户信息，修复准备阶段提前退出和 Torch 账户查找失败；不修改父进程或全局环境。真实模型准备及清理已验证。 / Worker-only completion of missing Windows environment restores real preparation without global or parent changes; see EXECUTION_MODEL_ENVIRONMENT.md.

- 剪贴板位图句柄不可复制时，在原 DIB/DIBV5 字节完整保存的前提下恢复图像；不吞掉其他格式或覆盖用户更新。 / Preserve verified DIB image bytes when a bitmap handle cannot be copied.
- 关闭等待提供窗口/弹窗诊断；取消弹窗后支持再次明确关闭。输入结果与后图失败分开，返回只读恢复候选，不自动切窗或重放。 / Actionable modal close and separate dispatch/observation results with explicit recovery.
- 增加 8 个选区/文档边界按键，共 23 个；修复抬键、前台不匹配诊断与原生菜单归属。 / Selection keys, key release/focus diagnostics and native menu ownership.
- 词级目标保持、真实控件内 OCR 匹配、浏览器外壳独立范围、唯一当前文字中心派生落点。解析器保留明确推荐身份，不把排名首项冒充模型选中项。 / Shared targeting/scope/coordinate fixes and identity-preserving parsing.
- 新回归与其必要 fixtures 一并入包；隔离入口预检检查全部 23 种按键，不执行桌面输入。 / Shipped no-input regressions and full key-schema dependency checks.

## 当前证据与边界 / Current evidence and boundaries

- 743 项源码回归与 743 项隔离包回归通过（集合有重叠，不相加），另有 7 项构建检查和 241 项运行时导入检查；Codex 同候选原生/浏览器连续测试通过。/ 743 source checks and 743 isolated-bundle checks pass (overlapping, not additive), with 7 build checks and 241 runtime-import checks; Codex's same-candidate native/browser continuous tests pass.
- AionUi 在同一候选完成四个有界组；首轮并非全通过，修复 5 个 tester-client 问题后四组复测通过。记事本覆盖替换、键盘 Undo、菜单 Undo、Don't Save 关闭；Python 文档覆盖 Quick search → 精确文章 → Back，重复两次并关闭/停止清理。/ AionUi completed four bounded groups on the same candidate; the first attempt was not all-pass, and all four passed after five tester-client fixes. Notepad covered replace, keyboard Undo, menu Undo and Don't Save close; Python docs covered Quick search → exact article → Back twice, then close/stop cleanup.
- 562 个归档哈希、23 个图片引用、595 个冻结文件已核验。Back 约 19.95–22.58 秒，链接约 7.85–8.37 秒；这些是观测值，不是通用性能或准确率承诺。/ 562 archive hashes, 23 image references and 595 frozen files were verified. Back was about 19.95–22.58s and links about 7.85–8.37s; observations only, not general performance or accuracy claims.
- 仅验证有人看护的 operator mode；本批未做自动策略验证。首次安装、管理员目标、跨设备未重复。候选 09 的独立失败继续保留为历史，不是 test.4 结果。/ Only supervised operator mode was validated; automatic-policy validation was not performed. Fresh install, elevated targets and cross-device checks were not repeated. Candidate09's independent failure remains historical and is not a test.4 result.

## 已发布 test.3 历史 / Published test.3 history

# v0.1.0-test.3 · 更新与验收范围 / Changes and verification scope

2026-09-20 · 执行模式第三批测试版，不是稳定版；公开状态以GitHub Release为准。 / Execution-mode test.3, not production-stable; publication is determined by GitHub Release.

## 新增与修复 / Changes

1. 识别点击支持single/right/double，复用同一输入后端，双击记录实际派发间隔。 / Single/right/double clicks share one input backend with dispatch timing.
2. 增加 `read_text`：新截图读取可见文字、行框、时间、capture_id和原图摘要；同一请求取图不重新截图。 / Fresh visible-image OCR with stable source-image retrieval.
3. 增加 `close_launched_window`：正常关闭本会话启动的确切窗口；MCP断连前先关窗再停止并核实清理。 / Gracefully close session-launched windows before stop/disconnect.
4. 修复字段值/方位表达、菜单项语序的目标解析和UIA范围选择；明确菜单目标使用完整菜单子树，不扩大整页扫描预算。 / Generic field/menu wording and current UIA scope fixes.
5. 小范围词级OCR放大识别后映射原图；零宽空格/标点仅作断词，不再导致有效整页词扫描失败。词字符仍须有有效几何，不合成可点击框。 / Small-crop word OCR and zero-area delimiter handling without fabricated word geometry.
6. 保留15种编辑键、文本替换、结构化请求错误、截图故障诊断、原图判断和不自动重放。 / Retain editing keys, replacement, actionable errors, evidence and no automatic replay.

本批不新增安全审批功能、学习模式或模型性能优化。 / No new approval/policy layer, learning feature or model-performance optimization.

## 当前已验证 / Evidence available

- 最新公共OCR修复后，24模块438项源码相关回归通过，2项第三方弃用警告；51项窄回归是重叠集合，不能相加。 / Post-fix source checks: 438 pass across 24 modules; overlapping subsets are not additive.
- Codex在真实Google页面完成右键、菜单全选、整句替换、回车、单词双击及替换、读取/滚动/再读、关窗清理。 / Codex exercised the real Google input/read/scroll/cleanup chain.
- 冻结候选自身270项隔离无输入检查通过，无原工作树运行代码导入泄漏；真实MCP stdio六工具、版本、非法字段恢复、同ID不重放、重连和清理通过。 / 270 isolated shipped checks plus real stdio identity/recovery/receipt/cleanup checks pass, with no worktree runtime imports.
- Codex先实机通过，再交AionUi在同一冻结候选独立执行：22 PASS / 0 FAIL / 0 INCONCLUSIVE。覆盖右击菜单、全选、整句替换、仅双击一个单词再替换、回车、读文、滚动重读、旧ID原图不变、正常关窗及同连接清理。主Agent复核14条命令回执与44项原图摘要。 / Codex-first then independent AionUi real-site acceptance: 22 checks pass; 14 command receipts and 44 image digests were audited.
- 旧候选暴露的零宽标点词框异常已用整张失败原图验证修复，不依赖分块绕行。外部追加复扫曾因误用Python3.13/旧OCR1.2.3报缺元数据；保留失败记录后双环境对照确定为辅助客户端环境偏差。指定Python3.11/OCR1.4.4下双方重复整图均返回301词。 / The delimiter fix passes the original whole image. A later auxiliary failure was traced to the client's wrong interpreter/old OCR, not waived; both agents reproduced the environment difference.
- 本批未重复首次安装下载、管理员应用和跨设备验收；源码检查集合重叠，不相加。 / Fresh-machine setup, elevated targets and cross-device acceptance were not repeated; test subsets overlap.

## 实测命令耗时 / Measured command latency

AionUi同连接一轮：右击19.14秒、菜单全选13.33秒、双击13.94秒、填写0.42–0.49秒、回车2.27–2.48秒、读文6.25–6.85秒、滚动1.12秒、关窗0.063秒。右击包含首轮准备；以上不是包含Agent决策的任务总时间，也不是提速承诺。 / One persistent-connection round: right-click19.14s, menu13.33s, double-click13.94s, type0.42–0.49s, Enter2.27–2.48s, read6.25–6.85s, scroll1.12s and close0.063s. Not end-to-end agent latency or a speedup claim.

## 限制 / Limitations

- 历史偶发双击未选中、已派发后缺图的原始根因仍未全部关闭；单次成功不等于长期稳定。 / Historical intermittent selection/missing-frame causes remain open.
- OCR是可见图像读取，不是DOM、完整文章或精准URL/字段提取；浏览器栏、遮挡、通知、未渲染内容影响结果。 / Visible pixels only; chrome, overlays and incomplete rendering affect results.
- `verified=null`等待Agent复核；输入已派发、画面变化和任务成功是不同概念。缺图只补图，不自动重放。 / Agent-owned null verification; dispatch/change is not task success.
- 冷启动、视觉模型识别仍慢。本机案例不是小目标、任意网站、其他设备、管理员应用或无人值守可靠性保证。 / Cold start/inference remain slow; no universal or unattended reliability claim.
- 首次安装、依赖/模型下载和不同硬件仍需接收者验证；本包不附环境或模型。 / Fresh-machine setup remains recipient-tested; environments/weights are not bundled.
- 使用安装脚本锁定的Python3.11和OCR1.4.4，服务与辅助脚本使用同一解释器。旧OCR1.2.3不支持所需词几何；不能用整行框替代单词框。 / Use the locked environment consistently; OCR1.2.3 lacks required word geometry.
- MCP客户端退出可能通过Windows Job结束派生浏览器。先用框架关闭自己的测试窗口，stop并轮询清理后再断开；不要动用户原有窗口。 / Close owned windows before stop/disconnect; client Job teardown can terminate spawned browsers.

模型下载与配置见FRIEND_SETUP.md，Agent契约见AGENT_GUIDE.md，读取接口见EXECUTION_READ_TEXT.md。 / See setup, agent and visible-text contracts shipped alongside this document.
