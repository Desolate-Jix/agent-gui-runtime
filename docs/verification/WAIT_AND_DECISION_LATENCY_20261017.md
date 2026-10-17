# Wait and Decision latency — source candidate / 等待与 Decision 延迟——源码候选

> Historical first-stage source evidence. These changes are included in the later [0.1.5 refresh](EXECUTION_015_REFRESH_20261017.md); the dates, samples and failure records below describe the original stage. / 本文保留第一阶段源码证据，改动已纳入后续 [0.1.5 更新](EXECUTION_015_REFRESH_20261017.md)；下文日期、样本及失败记录描述当时阶段。

2026-10-17. Base: `18cf8ac1912f2b8ffbfb6e7ba32a773b9f334e86`; branch: `codex/dev-main-review-resume`. This is an **unreleased source change**, not a replacement for the published 0.1.5 installer. No version change, package, commit or push was performed in this work session.

本轮为**未发布源码改动**，不是已发布 0.1.5 安装包的数据；版本未变，未打包、提交或推送。

## Scope / 范围

- Ordinary `task_plan.v3` clicks with `agent_judgment`, default waiting and no `wait_policy` may capture early after a substantial visual change and at least three stable samples. Sampling begins within the existing two-second grace; minimum elapsed time is 400 ms. An unchanged or continuously changing screen retains the original grace. Stability only selects when to observe: it never proves task success.
- If an authenticated early semantic assessment does not pass, one final read-only observation is allowed after the **original absolute deadline**. Identical image bytes reuse the assessment; a changed image gets at most one new Decision assessment under the existing ordinary-review policy. There is no action replay, new two-second wait, or automatic retry of HTTP/protocol errors.
- Input sequences, Enter, video policies, explicit waits, learning/memory and native-condition routes retain their existing behavior. Grounding model, resolution, prompts, Decision acceptance rules and input gates are unchanged.
- The HTTP transport shares a verified SSL context for the same CA bundle and default policy. Connection pools remain separate. Certificate/hostname verification stays enabled; changed/unreadable CA data cannot silently reuse the old context.

普通点击仅在默认等待、无显式等待策略时启用提前观察；有足够画面变化、至少三次稳定采样且经过 400 毫秒后，才可能提前送图核验。稳定不等于成功。早图语义判断未通过时，保留原两秒绝对截止，之后最多补一次只读末帧；同图复用判断，异图按原规则再判断一次，不重做动作，也不重试 HTTP／协议错误。输入、回车、视频、显式等待、学习和原生条件路线保持原行为。定位模型／分辨率／提示词及核验门禁未改。SSL 上下文仅在相同证书包和验证策略下复用，保留证书及主机名校验。

## Live method / 实测口径

Three applications, two three-step plans per app and arm, one persistent session/window for each pair. A used an immutable archive of the base commit; B used the frozen modified source. Actual order was all A runs followed by all B runs because an early-observation boundary needed offline repair. This is a small before/after comparison, **not a randomized causal benchmark**: network, model response and cache variation remain.

每组同一应用在同一会话／窗口内连续跑两轮，每轮三步；A 为冻结旧源码，B 为冻结候选。实际先完成全部 A，再完成全部 B；因候选边界修复而改变了原交错顺序。网络、模型响应及缓存状态并不完全受控，不能把整段差值全部归因于本地改动。

- Notepad: replace fresh note text → File → Save. Main read exact UTF-8 disk content after each round and inspected original PNGs.
- 7-Zip: A → nested → Up, then root → B → prepared bundle.zip. Main checked original path/content images. This tests navigation, not compression/extraction.
- Edge: enter Bing URL → search Wikipedia Rust/Python → open the ordinary article. Main checked article title, visible URL and body in the original screenshots. No separate native address read was performed, although the prepared oracle listed it. The named independent browser profile was retained; no cache, cookie, login or daily-profile data was cleared.

记事本逐轮核对真实磁盘内容；7-Zip 核对目录及预制 ZIP 的路径和内容原图；浏览器核对原图中的 URL、标题和正文，没有额外使用原生地址栏读取。所有真实截图和动作都走项目维护接口。独立浏览器资料目录保留，未清理缓存或日常浏览器资料。

## Actual action intervals / 实际操作间隔

The primary measure is the first recorded mouse-down of one **logical task-plan step** to the first mouse-down of the next. Internal focus/re-anchor clicks are not extra logical steps and do not dilute this metric. It includes the preceding action, checking, and preparation for the next action. Mouse-up timestamps are unavailable, so these are start-to-start intervals, not pure idle gaps. First dispatch and final verification are reported separately in raw evidence.

主指标为一个**逻辑步骤的首次实际鼠标按下，到下一逻辑步骤首次按下**，包含前步执行、核验和下步准备；同一输入步骤内部的重新锚定点击不额外算一步。没有鼠标释放时间，因此不是纯空闲等待时间。

| Matched scope / 匹配范围 | A intervals / 旧间隔 (s) | B intervals / 新间隔 (s) | Median A → B / 中位数 (s) |
| --- | --- | --- | --- |
| Notepad round 2 / 记事本第二轮 | 5.214, 8.198 | 5.279, 6.582 | **6.706 → 5.931** |
| 7-Zip both rounds / 两轮 | 8.589, 10.679, 9.809, 9.472 | 7.307, 8.028, 7.325, 6.860 | **9.640 → 7.316** |
| Edge round 1 / 浏览器第一轮 | 12.852, 8.905 | 12.176, 10.039 | **10.878 → 11.108** |

Edge B round 2 intervals were **10.219 / 9.217 s** (median 9.718 s), with no valid A round-2 comparator. Browser round-1 action intervals did **not** improve. The roughly four-second action-interval objective has **not** been reached.

浏览器 B 第二轮间隔为 **10.219／9.217 秒**，没有有效的 A 第二轮对照；第一轮间隔未改善。**尚未达到约四秒的操作间隔目标。**

| Complete three-step plan / 完整三步计划 | A (s) | B (s) |
| --- | ---: | ---: |
| Notepad round 1 / 记事本第一轮 | Assisted; excluded / 主 Agent 协助，不比较 | 23.163 |
| Notepad round 2 / 记事本第二轮 | 23.165 | 20.178 |
| 7-Zip round 1 / 第一轮 | 30.365 | 24.128 |
| 7-Zip round 2 / 第二轮 | 30.736 | 23.560 |
| Edge round 1 / 第一轮 | 33.188 | 32.794 |
| Edge round 2 / 第二轮 | Operator interruption / 人为干扰 | 27.590 |

All six B plans completed on their first attempt, **18/18 steps**, without Main intervention. Two ordinary-model reviews occurred in Notepad. Main's disk/image checks passed for all six rounds, and all three B owned-window closes and host shutdowns passed. This small sample cannot establish general accuracy or absence of false accepts. No new installed-build or independent desktop-agent acceptance was performed.

B 六轮均首次完成，**18/18 步**，无 Main 接管；记事本发生两次普通模型复核。六轮结果独立核对通过，三个 B 窗口与宿主正常关闭。样本不足以证明通用准确率或消除误放；未重新打安装包，也未进行另一 Agent 的独立桌面验收。

## Where time was saved / 时间省在哪里

Measured ordinary-click post-action observation stages include waiting, screenshot capture, hash/difference work and scheduling. Their medians were:

| Application / 应用 | A (ms) | B (ms) | B samples / 点击数 |
| --- | ---: | ---: | ---: |
| Notepad / 记事本 | 2027.760 | 571.475 | 4 |
| 7-Zip | 2085.069 | 762.898 | 6 |
| Edge / 浏览器 | 2033.999 (1 click) | 1798.687 (2 clicks) | Unmatched / 非完整匹配 |

All 12 eligible B clicks captured early. None needed a grace-final capture or extra model call. Browser pages remained visually changing longer; input/Enter waits were not changed. Full-window repeated sampling consumes additional local capture/processing work; it is included in these stage totals, not treated as free. Exact total capture-only cost for every sample is not separately recorded.

本批 12 次适用点击均提前采图，没有触发末帧补查或新增模型请求。浏览器画面变化持续更久，且输入／回车等待未改，因此收益小。多次截图与像素处理有本地开销，已包含在观察阶段总耗时中；不能用末次截图耗时乘采样数冒充准确的全部采图开销。

## Decision first-call diagnosis / Decision 首次调用诊断

An isolated construction profile found about **621 ms** inside `SSLContext.load_verify_locations`, within a **629 ms** first client setup. In six fresh-process local construction runs (no paid requests), the second transport averaged **546.795 ms without reuse versus 8.450 ms with reuse**. The first CA load still occurs once per process; this does not remove server inference or network latency.

离线剖析确认一项重复开销：客户端首次初始化 629 毫秒中，约 621 毫秒在加载 CA 证书。六个新进程的本地构造对照中，同进程第二个传输对象平均由 546.795 毫秒降到 8.450 毫秒；每个新进程首次加载仍存在。这不能解释或消除服务端推理、网络及普通模型复核时间。

Live B first-Decision client setup was **1.488 ms (Notepad), 2.390 ms (7-Zip), 1.545 ms (Edge)**, after the earlier grounding transport initialized the shared certificate context. Notepad's first overall decision still took **2904.480 ms**:

| Nested timing / 分层计时 | ms |
| --- | ---: |
| Primary provider call / 主 Decision 调用 | 775.931 |
| Within provider: client setup / 其中客户端初始化 | 1.488 |
| Within provider: HTTP / 其中 HTTP | 756.580 |
| Within HTTP: TCP / TLS / 等待响应头 | 7.965 / 9.734 / 733.924 |
| Result assessment, including ordinary review / 结果判定，含普通复核 | 2108.174 |
| Within assessment: ordinary HTTP / 其中普通复核 HTTP | 2085.316 |

Nested rows must not be added together. The 2.9-second first result in this example was dominated by ordinary review, not client construction. Transport header time includes network/server effects and is not a pure model-inference measurement. Stage instrumentation is complete for all **46 B Decision requests**; old A receipts have no such breakdown and are recorded as unavailable, not zero. No speculative keepalive request or paid prewarming was added.

上述是嵌套耗时，不能相加。这次 2.9 秒主要来自普通复核，不是初始化；等待响应头也不等于纯模型推理时间。B 的 46 条 Decision 阶段记录完整，A 无此字段，明确留空。未添加付费预热或无任务请求。

## Calls and preserved exceptions / 调用与保留异常

| Arm / 分组 | Grounding / 定位 | Decision | Ordinary / 普通复核 | Total HTTP / 合计 |
| --- | ---: | ---: | ---: | ---: |
| A, including exceptions / 含异常 | 16 | 37 | 2 | 55 |
| B, six completed rounds / 六轮完成 | 18 | 46 | 2 | 66 |
| Total / 总计 | 34 | 83 | 4 | **121** |

B used **127,665 reported API tokens**. Across A+B the known subtotal was **238,208**, with one A HTTP 503 lacking usage; the complete token total is unknown. Main/worker subscription usage is excluded. Browser requires 10 Decision requests per three-step plan (4+4+2); B's test cap was corrected from 19 to 24 for two rounds, within the existing 150-request overall budget. Acceptance thresholds were not changed.

B 六轮记录 127,665 个 API token；A+B 已知小计 238,208，一条 A 的 503 无用量，不能宣称完整总数。浏览器每轮三步实际需要 10 次 Decision（4+4+2），因此 B 测试名额由 19 修正为 24，整批仍在 150 次请求预算内；不是调整通过阈值。

- **A Notepad round 1:** entered text was correct; result verification received HTTP 503. Main reviewed the original image and continued without retyping. The 62.055-second cross-Main gap is excluded; the round is assisted, not an automatic pass.
- **A Edge round 2:** mouse position changed before mouse-down. The user confirmed using the mouse. No click was replayed. Cancel did not settle within the 30-second client wait; owned-window close was then refused as a plan remained active. Host shutdown completed and the original window was later confirmed absent. This is **not a complete workflow/close pass**. The planned rerun was not dispatched. Cancellation settlement remains a separate existing follow-up, not a fix delivered here.

旧记事本第一轮的 503 和 Main 协助保留；旧浏览器第二轮是用户确认的鼠标干扰，随后取消未正常结算、正常关窗被活动任务拦住，最终停宿主后窗口消失。该轮不计成功或性能对照；没有自动重放，也未把计划中的重跑写成已跑。取消结算问题继续保留，未在本轮等待优化中顺带改动。

## Verification and reusable contracts / 验证与通用合同

Main ran the four new test modules together: **69 passed** (`main-candidate-check.xml`). The affected observation/plan regression separately passed **292 tests, 1 skipped** (`grace-frozen-regression.xml`; skip: Windows symlink privilege). HTTP/provider related checks separately passed **476 tests**. These suites overlap and must not be summed as unique tests. Frozen-source hash checks, UTF-8 decoding, AST parsing and whitespace checks passed. Independent read-only review closed two findings before live B testing; no source edits occurred between B applications.

Main 合跑四个新增模块 69 项通过；观察／计划相关回归 292 项通过、1 项因 Windows 符号链接权限跳过；HTTP／Provider 相关回归另有 476 项通过。套件有重叠，不相加为独立测试总数。独立只读审查发现的两个问题已在 B 实测前修正；B 期间代码冻结。

| Failure or risk / 问题 | Reusable invariant and common fix / 通用合同及修复 | Regression / 回归与安全 |
| --- | --- | --- |
| Stable loading screen could be captured before final content / 稳定加载画面被提前截取 | Stability is observation timing, not success; keep original absolute grace for semantic nonpass in `task_plan_adaptive_grace` / 稳定仅决定采图时机，非通过保留原绝对宽限 | Late transition, unchanged image, errors, cancellation, stale bindings; no input replay / 覆盖迟到变化、同图、错误、取消及过期绑定，不重放输入 |
| Final observation lost original click annotation / 末帧丢失原点击标注 | Rebuild validated original-click annotation on fresh identity/hash/geometry / 在新身份、哈希及几何上重建已认证原点击标注 | Real click receipt and binding tamper cases / 真实点击回执及绑定篡改反例 |
| Completed full wait rejected after process-clock change / 完整等待因进程时钟变化被拒 | Expired full waits need no current-process early budget; unfinished early budget remains clock-bound / 完整等待不需要新进程早图预算，未完成早图预算仍绑定时钟 | Old clock/full wait and fractional-deadline cases / 旧时钟及小数截止边界 |
| Repeated CA loading costs roughly half a second / 重复 CA 加载约半秒 | Cache identical verified CA policy in common HTTP transport, not an application adapter / 通用传输层复用相同已验证 CA 策略 | CA change/corruption, hostname verification, concurrent construction, separate pools / 证书变化、损坏、主机名校验、并发及独立连接池 |

These changes apply across applications; no website-specific target rules were added. Existing action authorization, source-window binding, freshness, cancellation and risky-action restrictions remain. The delayed-transition branch has offline coverage but was not naturally exercised by the successful B runs; broad failure/accuracy testing and installed delivery remain future work.

修复位于通用运行时，不加网站特判；动作授权、窗口绑定、新鲜度、取消及高风险限制保留。迟到变化分支有离线反例覆盖，但本批成功实机未自然触发；广泛准确性、异常及安装交付仍需后续验收。

## Evidence / 证据

Local raw evidence is retained at `D:/AgentGUI-Projects/evidence/execution-wait-latency-20261017-01/`; SSL profiling at `D:/AgentGUI-Projects/evidence/decision-first-call-timings-20261017-01/`. Key files: `candidate-source-freeze.json`, `main-candidate-check.xml`, `grace-frozen-regression.xml`, `harness/api-budget-corrected-final.json`, `harness/logical-interval-comparison-corrected-final.json`, `harness/decision-stages-final.json`, `harness/observations-ab-report.json`, and each round's immutable receipts/oracles. The corrected report distinguishes an assisted whole round from its eligible local segments, and host cleanup from successful owned-window/workflow closure; original reports remain preserved. Raw screenshots, credentials and browser data are not added to the repository.

本机保留上述源码摘要、原回执、逐轮结果和统计工具；公开源码文档只保留汇总，不上传原始桌面截图、密钥或浏览器资料。
