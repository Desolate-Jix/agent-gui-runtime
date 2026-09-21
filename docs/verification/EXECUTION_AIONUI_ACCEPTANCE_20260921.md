# 执行优化独立验收 / Independent execution-optimization acceptance

## 结论与范围 / Result and scope

2026-09-21，AionUi 对冻结源码进行真实 Google/Edge 连续验收，任务 `aion-conditional-wait-20260921-01`，报告 PASS。Codex 核对原始回执而非仅采纳总结：最终 attempt 5 为 **8 次 input_sequence 搜索 + 1 次 Escape 负控**；全部输入均由框架执行。之前 4 次客户端中止保留，不宣称首次全通过。 / AionUi reports PASS for the frozen-source real-browser run. Raw receipts establish eight searches and one Escape control in the final fifth attempt; earlier client-aborted runs remain recorded.

- 原始生产源码/脚本/测试/文档清单599项在实机验收期间无变化。 / The 599-entry source manifest remained unchanged during live acceptance.
- 7 个 MCP 工具；组合输入、实际字段值核对、精简回执及原始 PNG；无模型/宿主逐步重启。 / Seven tools, combined input and value checking, compact receipts and original PNG delivery.
- Codex 单独重算最终9张动作后图：传输字节 = 磁盘原图，SHA-256与回执及条件摘要一致；查看条件命中、超时和恢复关键原图。 / Codex independently checked all nine action images against disk and receipt hashes, plus visually inspected key frames.
- 清理：最终正常关闭自建窗口，宿主stopped、pending为空、cleanup_verified=true，客户端退出；未修改用户原窗口。 / The accepted round gracefully closed its own window and stopped the host with no pending requests.

## 条件与耗时 / Conditions and timings

| 用例 / Case | 结果 / Result | Enter＋后图 / Enter + after image |
| --- | --- | --- |
| 普通固定等待 / Fixed wait，2次 | 搜索完成 / Search complete | 2.115–2.161s |
| 有效条件 / Positive conditions，5次 | 3次命中、2次超时；5次搜索均完成 / 3 met, 2 timed out; all searches completed | 命中 / met: 1.376–1.624s |
| 不存在的 Text / Missing text | timed_out，原图显示已搜索 / Search visible despite condition timeout | 2.193s |
| 超时后的恢复 / Recovery | 下一次搜索条件命中，已计入上述5次 / Next search met, included above | 1.376s |
| Escape + 已有标志 / Existing marker | baseline matched，500ms预算后timed_out，没有假报新出现 / No false transition | 整条命令 / whole command 0.632s |

8次搜索命令整体6.30–7.26s；条件不是每次都能提前结束。AionUi 从当时的UIA选中了广告/天气类标志，其中一次标志晚于预算，一次轮换。建议选择稳定的目标正文/标题，不用广告或天气作为通用模板。未硬编码任何网站名或坐标。 / Search commands took 6.30–7.26s. Early completion is not guaranteed: the independently selected advertising/weather markers could arrive late or rotate. Prefer stable content markers; no site or coordinate was hard-coded.

条件只证明指定标志在绑定窗口中出现；任务效果、全页加载仍由Agent判断。同步UIA/采集I/O可能超过轮询预算，回执明确记录deadline_scope/deadline_exceeded。 / A marker is not whole-page or task verification; synchronous I/O may overrun the disclosed polling budget.

## 首次失败与遗留问题 / Original failures and remaining limits

- AionUi 客户端曾未等host ready、过早读取空UIA树、使用大写request_id、未处理queue.Empty、pending时尝试关闭、误读顶层回执；修复其客户端后第5轮完成。 / Client errors preceded the successful fifth run and are retained.
- 第2/4轮客户端中断后出现遗留自建Edge窗口，新协调器拒绝认领旧窗口；AionUi 报告按已记录PID强制清理。**这不是正常关闭路径通过**，跨宿主窗口归属恢复仍未修复；最终第5轮正常关闭单独通过。 / Earlier interrupted clients left owned windows; recovery ownership was rejected and the tester reported process-level cleanup. This does not validate graceful crash recovery; that limitation remains. The final round's graceful cleanup did pass.
- 普通step旧字段task_effect_verified可能为false；组合搜索为null。均不能替代Agent效果判定。 / Legacy step false and sequence null are not effect verdicts.
- 不包含跨设备、长时运行、无障碍接口缺失站点、模态干扰的全面保证。 / No cross-device, long-duration or universal-site guarantee.

## 验收后最小修复 / Minimal post-acceptance fixes

1. 大写/越界request_id原先在_path抛ValueError，绕过工具层结构化错误。共享校验移到入队前，instant_submit/instant_run返回invalid_request_id、validation_rejected和日志，不入队；有效请求随后仍能使用同一连接。 / Invalid IDs now receive structured pre-admission errors without queueing or reconnecting.
2. agent_review.after.observation_stage原先硬编码after_render_wait，与真实after_condition_wait不一致；现在透传原帧阶段，图片路径及摘要不变。 / Review metadata now preserves the recorded frame stage.

位置均在通用MCP回执层，不改输入派发、定位、条件等待或授权策略，适用于所有应用。新增10项回归：修复前8 failed/8 passed，修复后定向67 passed；完整836 passed in 27.29s。后续独立无输入复核单独记录，不冒充重做整条GUI验收。 / Both fixes are generic receipt-layer changes, not input or policy changes. Ten added cases exposed eight failures before repair; 67 targeted and 836 full checks then passed. A separate no-input follow-up checks these fixes without claiming another complete live run.

## 本机证据 / Local evidence

- 独立报告 / report: `D:\AgentReviewAcceptance\20260921-conditional-wait-independent-01\report.json`
- 原始attempt 1–5及归档 / raw attempts and archive: 同目录 / same directory.
- Codex 哈希复核 / hash review: `D:\agent-gui-runtime\reports\aionui-conditional-wait-20260921\independent-evidence-check.json`
- 冻结与最小补丁清单 / freeze and patch: 同目录 `frozen-source-manifest.json`、`receipt-fix-manifest.json`.

原图、浏览历史和完整机器日志不上传GitHub；提交维护源码、回归与本脱敏摘要。未生成新ZIP，原test.4下载不包含本批源码更新。 / Raw images, browser history and machine logs are not uploaded; source, regressions and this summary are. No new ZIP is built; the old test.4 download is unchanged.

### 回执复核终态 / Receipt follow-up result

任务 `aion-conditional-wait-20260921-02` 两项均PASS：独立构造非法ID并确认结构化拒绝/日志/零入队，随后有效请求可入队；将原cw1-023实机回执复制到隔离临时会话只读重投影，阶段正确、原图路径及SHA不变、原会话文件无变化。67项定向测试再次通过（1.11s）。未启动GUI、输入宿主或真实截图；最终源文件哈希与补丁清单一致。 / Both receipt fixes independently passed, including original live-receipt reprojection and 67 tests. This follow-up performed no GUI input or capture; original evidence stayed unchanged and patch hashes matched.

证据 / Evidence: `D:\AgentReviewAcceptance\20260921-conditional-wait-independent-01\receipt-fix-check\receipt-fix-check.json`.
