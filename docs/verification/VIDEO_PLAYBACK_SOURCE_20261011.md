# 视频播放核验源码检查 / Video playback source checkpoint

后续用户已批准实测；首次失败与修复进度见[真实验收记录](VIDEO_PLAYBACK_LIVE_20261011.md)。下文保留此前离线冻结证据，不改写成实机通过。 / Live testing was subsequently authorized; the linked record preserves failures separately from this offline checkpoint.

## Main 整合检查与读取开销修复 / Main integration and ledger optimization

- 首轮Main：`main-final.xml`，**541 passed，1 deselected**（完整打包测试按范围排除），290.60s；1082个app/scripts/tests Python文件前后SHA一致。 / First integrated suite:541 passes, one full-build deselection;1082 Python hashes unchanged.
- 随后真实单调时钟的离线模拟暴露了账本重复读取瓶颈，7帧分支在发判断前耗尽8秒预算。原失败保留在 `offline-clock-pre-cache-summary.json`，没有调大预算。 / A real-clock offline simulation exposed ledger overhead before assessment; its timeout remains recorded.
- 仅在同一同步阶段缓存已验证账本；定位、截图、模型调用、追加事件及最终采用边界重读真实字节。读取向外返回副本，失败清空/封锁缓存；同大小、同修改时间的篡改也拒绝。 / Phase-local reuse preserves full byte validation at external/adoption boundaries, with immutable caller views and sticky failure.
- 最后修复仅修改 `video_playback_verification.py` 及其测试；Main受影响路径最终 **41 passed，46.86s**，1082个Python文件前后SHA一致，记录在 `main-cache-final.xml`，不把两轮重叠用例相加当唯一测试数。 / The final narrow change affects the ledger and its tests; overlapping suite counts are not summed.

| 离线真实时钟场景 / Offline real-clock case | 修复前 / Before | 修复后 / After |
|---|---:|---:|
| 3帧本地进度 / Three-frame local proof | 3.330s，completed | 1.544s，completed |
| 7帧时序分支 / Seven-frame temporal route | 10.236s返回Main；预算8.170s处超时、未判断 / review, no assessment | 4.711s，completed，一次模拟Decision / one mock assessment |

表中从核验预算起到最终tick返回，含调度与证据检查；locator、截图、OCR和Decision使用离线替身，未测真实网站、模型或OCR准确率，不能换算为整任务提速百分比。修复后来源：`offline-clock-post-cache-initial-summary.json`。 / These clocks isolate the runtime with mocked external/pixel-observation boundaries. They do not measure actual website/model/OCR latency or end-to-end speedup.


工作树 `C:/Users/DesolateJix/.codex/worktrees/decision-api/agent-gui-runtime`，分支 `codex/dev-decision-api`。用户批准开发，随后选择“先完成源码和离线测试，实测稍后”。本批零桌面输入、零真实API、未打包、未改版本、未提交或发布。 / Source and offline work only; live tests are explicitly deferred.

## 行为 / Behavior

- task_plan.v2新增video_playback，复用原执行器、输入票据与后续门禁；仅本步骤默认render grace500ms。 / The new kind reuses the existing runner and gates with a dedicated500ms render grace.
- 同一外部视觉客户端只读定位一次主播放器，随后最多7张维护接口新图；至少3帧跨1秒、间隔500ms。实际时间取截图完成时刻，OCR单独计时。 / One localization, at most seven fresh captures; capture and analysis timings remain distinct.
- 本地要求合理播放时间在多个间隔持续增加和可信播放控件，无已识别暂停/加载/广告/错误。分块运动仅作诊断，不单独成功。 / Sustained plausible progress plus playing controls are required; motion alone cannot pass.
- 本地不足时，一次Decision上传两张选图并绑定全链真实时刻、逐帧状态/读数、区域、分析规则版本。拒绝/不确定返回原Main及v4全链，不重复输入。 / One temporal assessment precedes original-Main review with all evidence.
- 共用8秒调度/采用预算，不因重连重置。同步截图/OCR可能迟到；迟到证据不采用，实际耗时保留。always_main继续有效。 / One budget survives interruption; synchronous operations are not hard-cancelled.

## 验证记录 / Verification

原始记录：`D:/AgentReviewAcceptance/video-playback-source-20261011-01`。RED、修复及GREEN分别保留；最终Main组合XML和冻结清单定义本批结果。 / Original RED and repaired runs remain separate; Main XML and manifests identify the freeze.

集成审查修复：截图时刻混入OCR耗时、纳秒多次读取导致绑定不一致、定位图未交叉绑定原after、时序上下文缺逐帧读数及动画PNG单样本歧义。两个“单步审核后应ready”的测试改为正确的completed期待，未改运行器语义。 / Repairs address timestamps, locator lineage, temporal readings and animated PNGs. Two fixture expectations changed without altering runner semantics.

## 限制与下一步 / Limits and next step

1. 2–3秒本地、5–8秒含定位是未验证目标。没有新的实机速度、准确率或误判率；旧流程数据不转计此功能。 / Latency targets and accuracy remain unmeasured.
2. 首版自动播放器定位需要配置的external_api客户端，其他路线保留原Main；没有接受调用方直接提交坐标的捷径。 / Automatic localization currently requires the external grounder; unavailable routes return to Main.
3. 控制条隐藏、OCR不可用、全屏缺锚点、周边变化或进度不清时，本地不确认。无标识广告、复杂遮挡及特殊播放器须实测，有限截图不能保证识别所有广告。 / Local uncertainty is explicit; difficult negatives need live calibration.
4. 用户另行批准后，用全新数据验证Bilibili及另一真实播放器，覆盖播放、暂停/恢复、加载和清理；分别报告定位、采集、OCR/差异、Decision、Main及整任务用时。Main单项/连续通过后才交同冻结候选独立验收。 / Fresh live and then independent acceptance remain pending.
