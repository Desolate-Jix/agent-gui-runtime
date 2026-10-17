# Execution 0.1.5 refresh / 执行版 0.1.5 同版本更新

2026-10-17. This refresh keeps version **0.1.5**. Dated release assets identify the new build; the original tag and original assets remain intact. Final installer checks and source/asset hashes are recorded in the [release notes](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5). Source results below are not substituted for installed acceptance.

本次保留 **0.1.5** 版本号，以日期区分新构建；原标签和原附件保留。最终安装验收及源码、附件摘要见[发布说明](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)。下列源码结果不代替安装验收。

## Changes / 改动

- Default visual Enter submissions now use the same adaptive observation contract as ordinary clicks: at least 400 ms, sufficient change and three stable samples, bounded by the original two-second grace. A stable frame chooses when to check; it does not prove success. An authenticated semantic nonpass retains one final read-only observation at the original deadline, without replaying input or retrying HTTP/protocol failures.
- Current-result verification can overlap with **one next-step read-only grounding request** on the same bound frame. The next action can consume it only after predecessor success is persisted and existing target/freshness/action gates pass. Cancellation, handoff, a changed frame and host closure invalidate it. Failed or discarded requests remain accounted for.
- The earlier ordinary-click adaptive wait and verified SSL-context reuse are included. The grounding model, resolution, prompts, Decision acceptance rules and action permissions are unchanged. Explicit waits and native/temporal routes retain their contracts.

默认视觉 Enter 提交复用普通点击的自适应观察：至少经过 400 毫秒、有足够变化并连续三次稳定采样，受原两秒宽限约束。稳定仅决定送图时机；早图语义未通过时保留原截止末帧，不重放输入、不重试 HTTP／协议错误。当前结果复核可与**一个下一步只读定位**并行，前步成功落账后才能经原门禁消费；取消、接管、换图或关闭使预取失效，失败及弃用调用仍计入调用记录／费用统计。包含上一批普通点击等待与 SSL 上下文复用；定位模型、分辨率、提示词、通过规则和输入权限未变。

## Source comparison / 源码对照

A is the frozen source with the **earlier ordinary-click/SSL optimizations already included**; B adds Enter observation and lookahead. This is not a comparison against the original published 0.1.5 installer. Each application/arm used a fresh session and fixture, with two consecutive three-step plans. Order: Notepad A→B, 7-Zip B→A, Edge B→A. The same named independent Edge profile was retained; no browser data was cleared. Network, model and cache variation were not randomized or controlled.

A 已含上一批普通点击／SSL 优化，B 再加入 Enter 观察及预取，**不是旧发布安装器与新包的直接对照**。每应用／组使用新会话、新测试数据，连续两轮三步计划；顺序为记事本 A→B、7-Zip B→A、Edge B→A。浏览器使用并保留同一个具名独立资料目录，不清缓存。模型、网络和缓存差异未受严格控制。

| Application / 应用 | A plans 1 / 2 (s) | B plans 1 / 2 (s) | Action-interval median A → B (s) / 动作间隔中位数 |
| --- | ---: | ---: | ---: |
| Notepad / 记事本 | 30.540 / 19.958 | 21.142 / 16.713 | **5.803 → 5.597** |
| 7-Zip | 25.029 / 26.947 | 24.528 / 22.933 | **7.805 → 7.254** |
| Edge | 30.660 / 32.547 | 31.180 / 24.827 | **10.786 → 9.280** |

Action intervals are the first physical mouse-down of one logical plan step to that of the next, four matched intervals per app/arm. Internal re-anchor clicks and the second mouse-down of a double-click are not counted as extra steps. This is start-to-start time, not pure idle time. Whole-plan time includes model calls, actions and verification. Edge's first B plan was slower than A; the four-second interval objective **has not been reached**. Whole-plan differences cannot be attributed entirely to these changes.

动作间隔是相邻逻辑步骤的首次真实鼠标按下时间差，每应用／组四个匹配区间；内部重锚和双击第二次按下不另算步骤，不是纯空闲等待。完整计划包含模型调用、操作和核验。Edge 第一轮 B 比 A 慢，**尚未达到四秒间隔目标**，不能将整段差值全部归因于代码优化。

All **12 plans / 36 steps** completed automatically on their first attempt, including B's six plans / 18 steps. Main separately inspected original bound screenshots; Notepad saved UTF-8 contents matched disk exactly. 7-Zip covered folder and prepared-ZIP navigation, not compression/extraction. Edge covered Bing → Rust/Python Wikipedia articles; visible URL/title/body were inspected, but no native address read was performed. The B Python page had a donation banner with the correct article still visible; no donation control was used. All six owned windows and hosts closed normally.

**12 个计划／36 步均首次自动完成**，其中 B 六个计划／18 步。Main 逐轮检查绑定原图；记事本实际 UTF-8 文件内容完全一致；7-Zip 只验目录和预制 ZIP 浏览，不含压缩解压；Edge 检查 Bing→Rust／Python 维基百科的可见 URL、标题和正文，没有原生地址栏读回。B 的 Python 页有募捐横幅但文章仍可见，未操作募捐控件。六个窗口及宿主均正常收尾。此小样本不能证明通用准确率或消除模型误放。

## Measured work overlap / 实际重叠与观察

Across B's performance plans, 12 prefetched groundings were consumed once. Actual intersections of current-result Decision time and next grounding totaled **0.933 s (Notepad), 1.470 s (7-Zip), 2.740 s (Edge)**. These totals are measured overlap, not additional time to add to step totals. Notepad's larger whole-plan improvement also reflects model/precheck variation.

B 性能计划中 12 次预取均被消费一次；当前结果 Decision 与下步定位的真实重叠总量分别为 **0.933／1.470／2.740 秒**。重叠不能与步骤总时长相加；记事本整段收益还包含模型和前置核验的波动。

Four Enter observations per browser arm had medians **2077.258 → 1876.833 ms**. Only **2/4** B Enter observations ended early; the other two exhausted the original grace and took **2099.803 / 2225.573 ms**, including screenshot/hash/scheduling overhead. Repeated sampling costs are included. This does not claim every capture completes within two seconds.

每组四次 Enter 观察的中位耗时为 **2077.258→1876.833 毫秒**。B 只有 **2/4** 提前结束；其余两次用满原宽限，加上采图、哈希和调度共 **2099.803／2225.573 毫秒**。多次采样的本地成本已计入，不宣称每次小于两秒。

## Calls, cancellation and limits / 调用、取消与限制

The 12 performance plans used **132 API requests**. A separate candidate cancellation/recovery probe used **7**, for **139 total: 39 grounding, 96 Decision, 4 ordinary review; 268,593 reported API tokens**, with no unknown usage in this batch. Main/worker subscription usage is excluded. Consumed prefetch copies were deduplicated; failed/discarded/pending calls are retained by the accounting method rather than dropped.

12 个性能计划共 **132 次 API**，独立取消／恢复检查另用 **7 次**；合计 **139 次：定位 39、Decision 96、普通复核 4；268,593 个已报告 API token**，本批无缺失用量。不含 Main／工作 Agent 套餐用量。预取消费副本按请求 ID 去重，统计方法保留失败、弃用和未决调用。

The cancellation probe stopped at grounding before input: `action_executed=false`, no dispatch attempts, saved file unchanged, original request terminally cancelled. A new two-step File→Save recovery plan completed in **13.412 s**, then the host closed normally. These extra requests are excluded from performance plans but included in cost. This does not repair or reinterpret the older mouse-interference case whose input outcome remained unknown.

取消检查发生在定位期间、输入之前：`action_executed=false`、无输入派发、原文件未变，原请求终态取消；随后新建 File→Save 两步任务 **13.412 秒**完成并正常收尾。额外检查不纳入性能样本，但计入费用。上一批人为鼠标干扰后输入结果未知的历史问题仍保留，不能据此宣称修复。

Precise per-step timing spans available in local evidence run from provider grounding-attempt start or first physical mouse-down to current-result Decision return. They exclude preprocessing before the provider attempt and final verification persistence/client notification. Pure OS-input-only time is unavailable. Approximate wall-clock reconstructions are explicitly marked and are not advertised as exact full-operation latency.

本地逐步数据的精确边界为 Provider 定位尝试开始／首次真实按下，到当前结果 Decision 返回；不含定位前处理、最终落账和客户端通知。纯 OS 输入时间未知；壁钟估算单列，不冒充完整操作的精确耗时。

## Installed acceptance / 安装态验收

The dated `20261017-01` installer was checked separately from the source comparison. A fresh isolated Python 3.11 environment installed all 45 locked API-route dependencies; functional entrypoints and all **659 payload hashes** passed before and after live acceptance. Check-mode tests covered an original 0.1.5 → refreshed 0.1.5 update, a separate fresh installation/uninstall, preserved external user data, and injected-failure rollback. This does not add clean-machine or normal OS registry/shortcut integration coverage.

日期构建 `20261017-01` 与源码对照分开验收：新建隔离 Python 3.11 环境，安装全部 45 个锁定的 API 路线依赖；真实功能入口及 **659 个载荷文件哈希**在实测前后通过。检查模式覆盖原 0.1.5→更新 0.1.5、独立新装与卸载、保留外部用户数据，以及注入失败后的回滚；不代表全新机器或正常注册表／快捷方式集成验收。

| Installed application / 安装态应用 | Reviewer / 验收者 | Three-step plan 1 / 2 (s) / 三步计划耗时 |
| --- | --- | ---: |
| Notepad / 记事本 | Main | **20.744 / 18.191** |
| Edge | Main | **27.043 / 27.430** |
| 7-Zip | Independent Sol / 独立 Sol | **25.918 / 24.324** |

All six plans / 18 steps completed on the first attempt; original screenshots were inspected, Notepad disk contents matched exactly, and all owned windows and hosts closed normally. The independent reviewer used the same frozen installed payload. These are complete plan times, not individual action intervals. The installer is unsigned; model false accepts remain possible.

六个计划／18 步均首次完成；逐轮核对原始截图，记事本磁盘内容精确一致，本轮窗口与宿主均正常关闭。独立验收使用同一冻结安装载荷。表中是完整计划时间，不是单动作间隔；安装器未签名，模型误放仍可能发生。

The installed runs used **66 requests: 18 grounding, 46 Decision and 2 ordinary review**, totaling **127,178 provider-reported tokens**, with no unknown usage. These counts are separate from the source comparison and exclude Main/worker subscription usage; consumed prefetch records are counted only once. / 安装态共 **66 次请求：定位 18、Decision 46、普通复核 2；127,178 个供应商报告的 token**，无缺失用量。与源码对照分开统计，不含 Main／工作 Agent 套餐用量；预取消费副本不重复计数。

Installer SHA-256: `fb24a66fee62d68876d344d0cc09b00df592c2f853f3ca041b810f1621cd5875`. The dated source archive is the exact build input; the linked main commit has identical runtime code and subsequent documentation-status updates. / 日期源码 ZIP 保留确切构建输入；发布说明对应的 main 提交保留相同运行时代码，并补充后续文档状态。

## Verification / 验证

Main ran 18 affected modules: **395 passed**. After independent review identified two prefetch races, event-controlled counterexamples first failed, then passed after repair; Main reran four affected modules: **82 passed**. These overlapping suites are not summed as unique tests. The fixes retain a late HTTP error after discarded consumption and recheck host closure under the lock before starting a request. Final independent source review found no new P0/P1/P2 issue in the changed paths.

Main 合跑 18 个相关模块 **395 项通过**。独立审阅发现两项预取竞态后，先以事件同步反例复现，再修复；Main 合跑四个受影响模块 **82 项通过**。套件重叠，不相加为独立测试数。修复在弃用后保留晚返 HTTP 错误，并在锁内复查关闭状态后才允许启动请求；最后只读审阅未发现新增 P0／P1／P2。

The reusable invariants are exact completed-Enter receipt binding; no prefetch action before persisted predecessor success; one consumption; stale/cancelled frames never authorize input; no hidden protocol-error retry. These are common-runtime changes, not website-specific rules. Offline delayed-transition and stale/forged receipt cases supplement successful live runs. False accepts remain a known model limitation; broader application and failure coverage is still needed.

通用合同包括真实 Enter 完成回执绑定、前步落账成功前禁止预取动作、单次消费、取消／旧图不授权输入、不以重试隐藏协议错误。修复位于公共运行时，不是网站特判；离线覆盖迟到变化、过期和伪造回执，补足成功实测。模型误放仍是已知限制，仍需扩大应用和失败样本。

Raw evidence remains local under `D:/AgentGUI-Projects/evidence/execution-pipeline-016-20261017/` (the initial directory name is historical, not a 0.1.6 release). Files include `multi-app-final.json`, `multi-app-final-tables.md`, `main-integration.xml`, `main-prefetch-r2.xml`, source manifests, original receipts and Main's per-round oracles. Earlier ordinary-click/SSL evidence remains in [its original report](WAIT_AND_DECISION_LATENCY_20261017.md). No raw desktop images, credentials or browser data are published.

原证据保留在上述本机目录（初始 `016` 目录名不是 0.1.6 发布），包括最终统计、测试 XML、源码摘要、原回执和逐轮独立核对。上一批普通点击／SSL 证据另保留原报告；不公开原始桌面图、凭据或浏览器资料。
