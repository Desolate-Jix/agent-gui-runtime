# Installed operation timings / 安装版具体操作用时

**Current 0.1.4:** installed Notepad plans took **30.621 s / 22.873 s** and the six-step 7-Zip plan took **69.515 s**, with recording enabled. Independent fresh three-step plans took **25.467 s / 29.261 s**. These are different tasks, not a speed comparison with the browser rows below. Full scope and per-step intervals are in the [multi-application report](MULTI_APP_EXECUTION_20261015.md). / **当前 0.1.4：** 开启录屏时，安装态记事本计划耗时 **30.621 秒／22.873 秒**，六步 7-Zip 计划 **69.515 秒**；独立全新三步计划为 **25.467 秒／29.261 秒**。任务不同，不能与下方浏览器数据作提速对比，完整范围与逐步区间见[多应用报告](MULTI_APP_EXECUTION_20261015.md)。

## Historical 0.1.3 reconstruction / 历史 0.1.3 记录重建

These measurements are reconstructed from the original successful **0.1.3 Candidate02 installed** two-round Bing → search `Rust standard library collections documentation` → first ordinary result journey. They are not a live measurement of the new source without a fixed plan-step cap, and are not a controlled speedup comparison. Both rounds used the same connection, browser window and retained profile, with no Main handoff. / 本统计来自 **0.1.3 Candidate02 安装版**原有成功记录：Bing → 搜索 `Rust standard library collections documentation` → 首个普通结果，同连接、同窗口、保留资料目录连续两轮，均无 Main 接管。本轮没有重新操作桌面或调用模型，不是取消固定步数限制后源码的实测，也不是受控提速对比。

## Operations / 操作

| Operation / 操作 | Round 1 / 第一轮 | Round 2 / 第二轮 |
| --- | ---: | ---: |
| Enter Bing URL and confirm navigation / 输入 Bing 网址并确认跳转 | 12.203 s | 9.654 s |
| Enter search query, press Enter and confirm results / 输入搜索词、回车并确认结果 | 9.587 s | 10.023 s |
| Open first ordinary result and confirm page / 打开首个普通结果并确认页面 | 8.614 s | 7.648 s |
| **Exact client plan duration / 客户端完整计划精确耗时** | **30.809249 s** | **27.353576 s** |

The operation rows use server command-received handoff intervals, including verification and scheduling. The final operation ends at the next round's start request or this run's owned-window close request, because a separate runner-terminal timestamp is missing. These intervals are not exact click durations and their sum is not the independently timed client plan total. Server interval sums are 30.403388 s and 27.325334 s; differences from client timing are 0.405861 s and 0.028242 s, left unattributed. / 操作行采用服务端从本步原输入命令接收到下一步命令接收的交接区间，包含核验和调度。末步缺少独立运行器终态戳，以下一轮启动或本轮关窗请求作保守外边界。这不是单次点击耗时，也不能把各行之和强称为客户端完整计划用时。服务端区间分别合计 30.403388／27.325334 秒，与客户端边界差为 0.405861／0.028242 秒，不擅自归因。

## Phase breakdown / 阶段拆分

Seconds; categories do not overlap. / 单位为秒，分类不重叠。

| Round / 轮次 | Operation / 操作 | Grounding HTTP / 定位 | Decision HTTP | Before capture and scene / 前置采图与场景检查 | Measured input fragments / 已计量输入片段 | Wait and result observation / 等待与结果观察 | Other / 其余 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | Bing URL / 网址 | 4.767 | 1.852 | 0.487 | 0.592 | 2.132 | 2.373 |
| 1 | Search / 搜索 | 3.928 | 1.068 | 0.516 | 0.659 | 2.093 | 1.323 |
| 1 | First result / 首结果 | 4.903 | 0.439 | 0.242 | 0.284 | 2.040 | 0.707 |
| 2 | Bing URL / 网址 | 4.544 | 1.114 | 0.249 | 0.573 | 2.113 | 1.061 |
| 2 | Search / 搜索 | 4.274 | 0.963 | 0.540 | 0.594 | 2.249 | 1.403 |
| 2 | First result / 首结果 | 4.189 | 0.432 | 0.145 | 0.285 | 2.042 | 0.555 |

- Six grounding calls total **26.605582 s**, mean **4.434264 s/call**. Twenty Decision calls total **5.869257 s**, mean **0.293463 s/call**; ordinary secondary review was not called. These are HTTP durations, distinct from complete operations. / 6 次视觉定位合计 **26.605582 秒**，平均 **4.434264 秒／次**；20 次 Decision 合计 **5.869257 秒**，平均 **0.293463 秒／次**，普通复核为 0 次。它们是 HTTP 耗时，不是完整动作耗时。
- Result observation totals **12.668068 s**, including six nominal 2-second render-grace waits. Do not add another 12 seconds. / 结果观察合计 **12.668068 秒**，已包含六次名义 2 秒渲染等待，不应再叠加 12 秒。
- Input fragments include logged click-controller spans and paired selection/text dispatch events. Clipboard preparation/restoration, unmeasured Enter backend time and unsampled gaps remain in “Other”; the fragments are not total typing time. Nested route/receipt totals are not added again. / 输入片段仅包含点击控制器日志跨度及 selection／text 成对事件；剪贴板准备和还原、未单独计量的 Enter 后端耗时及未采样间隙留在“其余”，不能冒充完整输入耗时。嵌套的路由／回执总时长没有重复相加。

## Startup and cleanup / 启动与收尾

Browser launch command: **2.391840 s**, including a nominal 500 ms presentation wait. Owned-window close command: **0.062939 s**. The driver recorded **61.751743 s** for the two-round journey including launch/control/cleanup; it starts after formal client/session construction, so it is not total process cold-start time. Offline preparation has no independently recorded duration and remains unknown. These lifecycle values have overlapping boundaries and must not all be summed. / 浏览器启动命令 **2.391840 秒**，含名义 500 ms 显示等待；本轮窗口关闭命令 **0.062939 秒**。驱动记录的两轮流程含启动／控制／收尾共 **61.751743 秒**，但计时从正式 Client／会话构造后开始，不能称为进程总冷启动。离线准备未独立计时，保持未知。生命周期区间存在包含关系，不能全部相加。

## Evidence and reproduction / 证据与复算

Original evidence: `D:/AgentGUI-Projects/evidence/execution-release-013-candidate02-main-01`. Analysis: `D:/AgentGUI-Projects/evidence/task-plan-unbounded-20261015-01/timing/`. Main independently reran the standard-library-only analysis into `timing-main-recheck/`; parsed results match exactly. All 37 source-file hashes were unchanged. Requests were joined by original execution/request IDs, with 20 Decision and six grounding calls counted once; token accounting matches the original **41,097 tokens** (22,828 Decision + 18,269 grounding). The analysis does not read keys, decrypt the ledger, access the network or drive the desktop. / 原始证据与分析路径如上。Main 使用只依赖标准库的脚本独立复算，解析后结果完全一致，37 个原文件哈希保持；按真实 execution／request ID 关联并去重 20 次 Decision 与 6 次定位，用量与原记录 **41,097 tokens** 一致（Decision 22,828＋定位 18,269）。分析不读取密钥、不解密账本、不联网、不操作桌面。

See [original release timing and acceptance](EXECUTION_SPEED_20261015.md#candidate02-installed-and-independent-closure--候选02安装与独立验收闭合) and [new source scope](UNBOUNDED_TASK_PLANS_20261015.md). / 另见原发布验收及新源码范围，避免混用验证结论。
