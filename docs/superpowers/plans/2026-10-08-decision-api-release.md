# Decision API preview validation and release / 判断 API 测试版验收与发布

**Goal / 目标:** Validate the optional Decision integration on fresh real GUI flows, compare scoped timings against the preceding preview, and publish the next compatible independent preview installers. / 用全新实机流程核验可选判断接入，按相同口径对比前版耗时并更新两个独立测试版安装器。

**Approved scope / 授权:** User requested testing, timing comparison and a new version on 2026-10-08. Earlier authorization permits desktop tests. Use maintained project capture/action interfaces only; no native Codex Computer Use. / 用户已批准测试和更新版本，已有桌面测试授权继续有效。

**Candidate / 候选:** Existing `codex/dev-decision-api` worktree. Preserve original failed attempts and unrelated worktrees. Proposed versions: learning `0.1.0-preview.2`, compatible execution `0.1.2-preview.2`; stable execution remains unchanged. / 沿用现有开发树，递增测试版，稳定执行版保持原标签。

## Verification and release sequence / 验证与发布顺序

- [x] Main runs fresh source single-operation and continuous flows: newly taught HOME → DETAIL → HOME, image success, delayed transition, blocked transition, explicit semantic conditions and recovery/cleanup. Retain original receipts, current screenshots and fixture truth separately. / 主会话先验证单项与连续主链，截图与测试真值分开保存。
- [x] Compare previous published local-image timing with current measured local-image timing; measure Decision HTTP/server/service time and total semantic workflow time separately. Use fresh cases for Agent review comparison; never label caller gaps as pure model inference. Bound real API sends to 20 for this batch, with no automatic retries and no private-window uploads. / 比较同口径历史与新数据，真实 API 最多 20 次，不上传私人窗口，不把编排等待当推理。
- [x] Repair observed common-contract failures with narrow regressions before full reruns. Record first-attempt accuracy, false acceptance, uncertainty, dispatch count and complete cleanup, without inferring universal accuracy from small samples. / 先复现修复再继续，不将复测通过覆盖首败。
- [x] Freeze one source candidate; verify isolated functional dependency closure, build the two independent components and installers, then perform Main installed acceptance and independent Sol Ultra acceptance of the same bytes. Rebuild only for a necessary runtime fix. / 单次集中冻结构建，同载荷先 Main 再独立实装验收。用户后续语言要求仅触发一次 GUI 替换构建，执行载荷未变。
- [ ] Update README, changelog, quickstart, configuration and benchmark/acceptance evidence. Commit the exact maintained files, synchronize main without overwriting unrelated work, publish the new prerelease and verify public asset hashes. Preserve user libraries and existing stable release; clean only this batch's superseded test installs when safe. / 同步文档和 main，发布后核下载哈希；只清理本批明确测试载荷。

## Review focus / 复核重点

- A failed image match must not become a success because only part of the expected state is visible. / 条件缺失不得误放行。
- An API wait must not permit a stale click, duplicate input or duplicate paid dispatch. / 等待不放宽新鲜度或防重。
- No-key/off mode and the local image success path retain ordinary behavior and zero API requests. / 未连接及本地成功不增加判断请求。
- Independent installer roots and offline learning-library use remain supported. / 两组件独立安装，学习库离线使用保持可用。
- Historical timing and contemporary paired timing retain their distinct sample sizes and measurement boundaries. / 历史与本轮对照分别标注口径和样本数。
- User's later language choice: first startup defaults to English, Chinese remains selectable and saved preferences win. Rebuild only the affected learning GUI; retain the unchanged execution candidate and its existing acceptance evidence. / 用户后续要求首次默认英语，中文可切换并保存；只重建受影响的学习界面。

Release-freeze note / 冻结说明：the last checkbox records the pre-publication source snapshot. The external publication and download receipts are recorded separately after the immutable commit/tag exists. Both owned test installers were uninstalled successfully; generated execution caches remain because automatic approval rejected the additional recursive cleanup. / 最后一项为发布前源码快照；提交和标签建立后的发布、下载回执另存。两个测试组件已卸载，额外缓存删除被自动审批拒绝，未绕行删除。
