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
